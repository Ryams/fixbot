from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import query
from claude_agent_sdk.types import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TaskNotificationMessage,
    TextBlock,
    ToolUseBlock,
)

from fixbot.agents.bug_fixer import build_definition
from fixbot.config import resolve_env_vars
from fixbot.defaults import MCP_ROLE_DEFAULTS
from fixbot.exceptions import (
    AgentBudgetExceeded,
    AgentError,
    ConfigEnvVarError,
    FixbotError,
    MCPServerError,
)
from fixbot.progress import ProgressDisplay, classify_tool, parse_fixer_result
from fixbot.prompts import orchestrator as orchestrator_prompt
from fixbot.run_log import PatternRecord, RunLogger

if TYPE_CHECKING:
    from fixbot.config import FixbotConfig


@dataclass
class RunResult:
    summary_text: str = ""
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int = 0
    session_id: str | None = None
    usage: dict[str, Any] | None = None
    text_blocks: list[str] = field(default_factory=list)
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    run_log_path: str | None = None


def _build_mcp_servers(config: FixbotConfig) -> dict[str, Any]:
    from fixbot.defaults import (
        get_code_host_provider,
        get_issue_tracker_provider,
        get_observability_provider,
    )

    servers: dict[str, Any] = {}
    for role, role_def in MCP_ROLE_DEFAULTS.items():
        # In triage-only mode the bug-fixer never runs, so the code host is
        # never launched and needs no configuration or credentials.
        if role == "code_host" and not config.fix_enabled:
            continue
        if role in config.mcp_servers and config.mcp_servers[role]:
            servers[role] = config.mcp_servers[role]
        elif role == "code_host":
            provider = get_code_host_provider(config.code_host_type)
            servers[role] = provider.get_default()
        elif role == "issue_tracker":
            provider = get_issue_tracker_provider(config.issue_tracker_type)
            servers[role] = provider.get_default()
        elif role == "observability":
            provider = get_observability_provider(config.observability_type)
            servers[role] = provider.get_default()
        else:
            servers[role] = role_def["factory"]()

    for key, server_config in config.mcp_servers.items():
        if key not in MCP_ROLE_DEFAULTS:
            servers[key] = server_config

    return resolve_env_vars(servers)


def _preflight_check(config: FixbotConfig) -> dict[str, Any]:
    """Verify MCP server prerequisites. Returns resolved server configs."""
    try:
        servers = _build_mcp_servers(config)
    except ConfigEnvVarError as e:
        raise MCPServerError(
            f"Missing environment variable: {e.var_name}\n\n"
            f"Set it with: export {e.var_name}=<value>\n"
            "Run 'fixbot check-env' to see all required environment variables."
        ) from e

    errors: list[str] = []

    for role, server in servers.items():
        server_type = server.get("type", "")

        if server_type == "stdio":
            cmd = server.get("command")
            if cmd and not shutil.which(cmd):
                errors.append(f"{role}: command '{cmd}' not found in PATH")

        elif server_type == "http":
            url = server.get("url")
            if not url:
                errors.append(f"{role}: no URL configured")

    if errors:
        raise MCPServerError("MCP server preflight check failed:\n  " + "\n  ".join(errors))

    return servers


def _build_options(
    config: FixbotConfig, dry_run: bool, mcp_servers: dict[str, Any]
) -> ClaudeAgentOptions:
    system_prompt = orchestrator_prompt.render(config)

    if dry_run:
        system_prompt += (
            "\n\nDRY RUN MODE\n\n"
            "This is a dry run. Do NOT create tickets, spawn bug-fixers, or make any changes.\n\n"
            "Execute Steps 1 and 2a only (fetch log patterns and search the issue tracker "
            "for existing tickets). Skip steps 2c and 3.\n\n"
            "Output exactly two sections, nothing else:\n\n"
            "PATTERNS\n\n"
            "A numbered list of the top 5 patterns in this format:\n"
            "  1. [status] service (N hits)\n"
            "     Pattern text truncated to ~80 chars\n"
            "     Existing ticket: TICKET-123 or none\n\n"
            "SKIPPED STEPS\n\n"
            "A short numbered list of the steps skipped in dry-run mode "
            "(ticket creation, bug-fixer spawning, PR creation).\n\n"
            "No other output."
        )

    # In triage-only mode there is no bug-fixer subagent to register — the
    # orchestrator can only fetch logs, check the tracker, and file tickets.
    agents: dict[str, Any] = {}
    if config.fix_enabled:
        agents["bug-fixer"] = build_definition(config, mcp_server_names=list(mcp_servers.keys()))

    options = ClaudeAgentOptions(
        model=config.orchestrator.model,
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
        agents=agents,
        permission_mode="bypassPermissions",
        # Pin MCP servers to those built from our config. Without this, the CLI
        # also loads host MCP servers (project .mcp.json, user/global settings,
        # plugins) — so a host could supply an OAuth Datadog or an identically
        # named server that shadows the API-key servers we configured. Hooks and
        # CLAUDE.md (governed by setting_sources) are intentionally left at the
        # CLI default so host conventions still apply to the bug-fixer's edits.
        strict_mcp_config=True,
        max_turns=config.orchestrator.max_turns,
        max_budget_usd=config.orchestrator.max_budget_usd,
        effort=config.orchestrator.effort,
    )

    if config.orchestrator.thinking:
        # JSON-loaded thinking config; shape is validated by the SDK at runtime.
        options.thinking = config.orchestrator.thinking  # type: ignore[assignment]

    return options


_FIELD_RE = {
    "pattern": re.compile(r"\*\*Log Pattern:\*\*\s*\n(.+?)(?=\n\n\*\*)", re.DOTALL),
    "count": re.compile(r"\*\*Pattern Count[^:]*:\*\*\s*(\d[\d,]*)"),
    "status": re.compile(r"\*\*Log Status:\*\*\s*(\S+)"),
    "service": re.compile(r"\*\*Service:\*\*\s*(.+)"),
    "ticket": re.compile(r"\*\*Issue Ticket:\*\*\s*(\S+)"),
}


def _parse_fixer_prompt(tool_input: dict[str, Any]) -> PatternRecord | None:
    prompt = tool_input.get("prompt") or tool_input.get("task") or ""
    if not prompt:
        return None

    def _extract(key: str) -> str:
        m = _FIELD_RE[key].search(prompt)
        return m.group(1).strip() if m else ""

    pattern_text = _extract("pattern")
    if not pattern_text:
        return None

    count_str = _extract("count").replace(",", "")
    return PatternRecord(
        pattern_text=pattern_text,
        status=_extract("status"),
        count=int(count_str) if count_str.isdigit() else 0,
        service=_extract("service"),
        action="spawned_fixer",
        ticket_id=_extract("ticket") or None,
    )


async def run_orchestrator(
    config: FixbotConfig,
    dry_run: bool = False,
    verbose: bool = False,
) -> RunResult:
    mcp_servers = _preflight_check(config)
    options = _build_options(config, dry_run, mcp_servers)
    result = RunResult()

    logger = RunLogger(config.run_log_dir)
    logger.start(
        {
            "fix_enabled": config.fix_enabled,
            "orchestrator_model": config.orchestrator.model,
            "bug_fixer_model": config.bug_fixer.model,
            "log_query": config.orchestrator.effective_log_query,
            "log_window_hours": config.orchestrator.log_window_hours,
            "max_code_fixes_per_run": config.orchestrator.max_code_fixes_per_run,
            "max_patterns_to_process": config.orchestrator.max_patterns_to_process,
            "dry_run": dry_run,
        }
    )

    prompt = "Run the bug fix triage workflow now."
    if dry_run:
        prompt = "Run the bug fix triage workflow now in dry-run mode — report what you would do but make no changes."

    last_message_text: list[str] = []
    deferred_error: FixbotError | None = None
    got_result = False

    phase = "fetching_logs"
    fixer_count = 0
    progress = ProgressDisplay() if not verbose else None

    if progress:
        from fixbot.defaults import get_observability_provider

        obs_name = get_observability_provider(config.observability_type).NAME
        progress.update(f"Fetching {obs_name} log patterns")

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                last_message_text = []
                for block in message.content:
                    if isinstance(block, TextBlock):
                        result.text_blocks.append(block.text)
                        last_message_text.append(block.text)
                        if verbose:
                            print(block.text, file=sys.stderr)
                    elif isinstance(block, ToolUseBlock):
                        result.tool_uses.append({"name": block.name, "input": block.input})
                        if verbose:
                            print(
                                f"[tool] {block.name}",
                                file=sys.stderr,
                            )

                        tool_phase = classify_tool(block.name)
                        if tool_phase == "spawning_fixer":
                            fixer_count += 1
                            record = _parse_fixer_prompt(block.input)
                            if record:
                                logger.add_pattern(record)
                            if progress:
                                progress.update(f"Spawning bug-fixer {fixer_count}")
                            phase = "spawning_fixer"
                        elif tool_phase == "checking_tracker" and phase == "fetching_logs":
                            phase = "checking_tracker"
                            if progress:
                                from fixbot.defaults import get_issue_tracker_provider

                                tracker_name = get_issue_tracker_provider(
                                    config.issue_tracker_type
                                ).NAME
                                progress.update(f"Searching {tracker_name} issues")

            elif isinstance(message, TaskNotificationMessage):
                if verbose:
                    print(
                        f"[task:{message.status}] summary={message.summary!r}",
                        file=sys.stderr,
                    )
                summary = message.summary or ""
                annotation = parse_fixer_result(summary)

                pr_url = None
                if annotation and annotation.startswith("PR created"):
                    pr_match = re.search(
                        r"https?://\S+(?:pull-requests|pull|merge_requests)/\d+\S*", summary
                    )
                    if pr_match:
                        pr_url = pr_match.group(0)

                fixer_result = (
                    "failed"
                    if message.status == "failed"
                    else (
                        "CODE_CHANGE"
                        if "CODE_CHANGE" in summary and "NO_CODE_CHANGE" not in summary
                        else "NO_CODE_CHANGE"
                        if "NO_CODE_CHANGE" in summary
                        else message.status
                    )
                )
                logger.update_last_pattern(fixer_result=fixer_result, pr_url=pr_url)

                if not annotation:
                    if message.status == "failed":
                        annotation = "failed"
                    elif message.status == "completed":
                        annotation = "done"
                if progress and annotation:
                    progress.annotate(annotation)

            elif isinstance(message, ResultMessage):
                got_result = True
                result.cost_usd = message.total_cost_usd
                result.duration_ms = message.duration_ms
                result.num_turns = message.num_turns
                result.session_id = message.session_id
                result.usage = message.usage

                if message.is_error:
                    errors = message.errors or []
                    if message.stop_reason == "budget_exceeded":
                        deferred_error = AgentBudgetExceeded(
                            f"Budget limit reached (${config.orchestrator.max_budget_usd:.2f}). "
                            f"Errors: {'; '.join(errors)}"
                        )
                    elif message.api_error_status is not None:
                        # A failing API call — e.g. 401 (invalid ANTHROPIC_API_KEY),
                        # 429, or 5xx. The CLI sets api_error_status when is_error
                        # is True with subtype "success"; the run did no real work,
                        # so it must surface instead of looking like a success.
                        deferred_error = AgentError(
                            f"Orchestrator failed: Anthropic API call returned HTTP "
                            f"{message.api_error_status} (stop_reason={message.stop_reason}). "
                            "Check ANTHROPIC_API_KEY / credentials and connectivity."
                        )
                    elif errors:
                        deferred_error = AgentError(
                            f"Orchestrator failed (stop_reason={message.stop_reason}): "
                            f"{'; '.join(errors)}"
                        )
    except Exception as exc:
        if not got_result:
            raise AgentError(f"Orchestrator failed: {exc}") from exc
        if verbose:
            print(f"[warning] post-result error ignored: {exc}", file=sys.stderr)
    finally:
        if progress:
            progress.stop()
        cost = {"total_usd": result.cost_usd} if result.cost_usd is not None else None
        log_path = logger.finish(cost=cost, duration_ms=result.duration_ms, usage=result.usage)
        result.run_log_path = str(log_path)

    if deferred_error is not None:
        raise deferred_error

    result.summary_text = (
        "\n".join(last_message_text) if last_message_text else "No output from orchestrator."
    )
    return result
