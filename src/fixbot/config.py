from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fixbot.exceptions import ConfigEnvVarError, ConfigError, ConfigMissingKeyError

ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Reasoning effort levels accepted by the Claude Agent SDK.
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "fix_enabled": True,
    "observability_type": "datadog",
    "code_host_type": "github",
    "issue_tracker_type": "linear",
    "mcp_servers": {},
    "repositories": {},
    "log_routing": [],
    "worktree_dir": ".worktrees",
    "orchestrator": {
        "model": "claude-sonnet-4-6",
        "max_turns": 100,
        "max_budget_usd": 5.0,
        "effort": "high",
        "thinking": None,
        "log_query": "status:(error OR warn) env:production",
        "log_query_filters": None,
        "log_window_hours": 6,
        "max_code_fixes_per_run": 3,
        "max_patterns_to_process": 20,
        "filter_instructions": None,
    },
    "bug_fixer": {
        "model": "claude-sonnet-4-6",
        "max_turns": 200,
        "max_budget_usd": 3.0,
        "effort": "high",
        "thinking": None,
    },
    "issue_tracker_settings": {
        "team": "Engineering",
        "project": "fixbot",
        "branch_prefix": "fixbot",
        "ticket_prefix": "ENG",
        "error_priority": 2,
        "warn_priority": 3,
        "error_label": "bug",
        "warn_label": "warning",
        "jira_project_key": "ENG",
        "jira_issue_type": "Bug",
        "jira_error_priority": "High",
        "jira_warn_priority": "Medium",
    },
    "read_only_repos": [],
    "run_log_dir": ".fixbot/logs",
}


@dataclass
class LogRoutingRule:
    key: str
    value: str
    repo: str


@dataclass
class RepositoryConfig:
    name: str
    code_host_repo: str = ""


@dataclass
class AgentConfig:
    model: str
    max_turns: int
    max_budget_usd: float
    effort: EffortLevel
    thinking: dict[str, Any] | None = None


@dataclass
class OrchestratorConfig(AgentConfig):
    log_query: str = "status:(error OR warn) env:production"
    log_query_filters: str | None = None
    log_window_hours: int = 6
    max_code_fixes_per_run: int = 3
    max_patterns_to_process: int = 20
    filter_instructions: str | None = None

    @property
    def effective_log_query(self) -> str:
        if self.log_query_filters:
            return f"{self.log_query} {self.log_query_filters}"
        return self.log_query


@dataclass
class IssueTrackerSettings:
    branch_prefix: str = "fixbot"
    # Linear
    team: str = "Engineering"
    project: str = "fixbot"
    ticket_prefix: str = "ENG"
    error_priority: int = 2
    warn_priority: int = 3
    # GitHub Issues
    error_label: str = "bug"
    warn_label: str = "warning"
    # Jira
    jira_project_key: str = "ENG"
    jira_issue_type: str = "Bug"
    jira_error_priority: str = "High"
    jira_warn_priority: str = "Medium"


@dataclass
class FixbotConfig:
    version: int
    observability_type: str
    code_host_type: str
    issue_tracker_type: str
    mcp_servers: dict[str, dict[str, Any]]
    repositories: dict[str, RepositoryConfig]
    log_routing: list[LogRoutingRule]
    worktree_dir: str
    orchestrator: OrchestratorConfig
    bug_fixer: AgentConfig
    issue_tracker_settings: IssueTrackerSettings
    read_only_repos: list[str]
    run_log_dir: str
    # When False, fixbot runs in triage-only mode: it fetches log patterns,
    # checks the issue tracker, and creates tickets, but never spawns the
    # bug-fixer or touches a code host. The code host is optional in this mode.
    fix_enabled: bool = True
    config_path: Path = field(default_factory=lambda: Path("fixbot.json"))


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_env_vars(obj: Any, path: str = "") -> Any:
    """Recursively resolve ${ENV_VAR} references in string values."""
    if isinstance(obj, str):

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                raise ConfigEnvVarError(var_name, path)
            return value

        return ENV_VAR_PATTERN.sub(_replace, obj)
    elif isinstance(obj, dict):
        return {k: resolve_env_vars(v, f"{path}.{k}" if path else k) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_env_vars(item, f"{path}[{i}]") for i, item in enumerate(obj)]
    return obj


def get_nested(data: dict, dotted_key: str) -> Any:
    """Get a value from a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ConfigMissingKeyError(dotted_key)
        current = current[key]
    return current


def _parse_repository(name: str, data: dict, require_code_host: bool = True) -> RepositoryConfig:
    if require_code_host and "code_host_repo" not in data:
        raise ConfigMissingKeyError(f"repositories.{name}.code_host_repo")
    return RepositoryConfig(
        name=name,
        code_host_repo=data.get("code_host_repo", ""),
    )


def _agent_config_kwargs(data: dict) -> dict[str, Any]:
    return {
        "model": data.get("model", "claude-sonnet-4-6"),
        "max_turns": data.get("max_turns", 100),
        "max_budget_usd": data.get("max_budget_usd", 5.0),
        "effort": data.get("effort", "high"),
        "thinking": data.get("thinking"),
    }


def _parse_agent_config(data: dict) -> AgentConfig:
    return AgentConfig(**_agent_config_kwargs(data))


def _parse_orchestrator_config(data: dict) -> OrchestratorConfig:
    return OrchestratorConfig(
        **_agent_config_kwargs(data),
        log_query=data.get("log_query", DEFAULT_CONFIG["orchestrator"]["log_query"]),
        log_query_filters=data.get("log_query_filters"),
        log_window_hours=data.get("log_window_hours", 6),
        max_code_fixes_per_run=data.get("max_code_fixes_per_run", 3),
        max_patterns_to_process=data.get("max_patterns_to_process", 20),
        filter_instructions=data.get("filter_instructions"),
    )


def _parse_issue_tracker_settings(data: dict) -> IssueTrackerSettings:
    # Every field has a default, so pass through only the keys present in data
    # and let the dataclass supply the rest.
    overrides = {k: data[k] for k in IssueTrackerSettings.__dataclass_fields__ if k in data}
    return IssueTrackerSettings(**overrides)


def _role_mismatch_warning(
    role: str,
    type_field: str,
    selected_type: str,
    providers: dict[str, Any],
    mcp_servers: dict[str, Any],
) -> str | None:
    """Return a message if the ``mcp_servers[role]`` override targets a different
    provider than ``selected_type``, else ``None``.

    The agent prompts are driven by the ``*_type`` config field, but the MCP server
    actually launched can be overridden via ``mcp_servers[role]``. When those
    disagree, the agent calls tools the running server does not provide. Returns
    ``None`` for matching overrides and for genuinely custom (unrecognized) servers.
    """
    override = mcp_servers.get(role)
    if not override:
        return None

    selected = providers.get(selected_type)
    if selected is None or selected.looks_like(override):
        return None

    for name, provider in providers.items():
        if name != selected_type and provider.looks_like(override):
            return (
                f"{type_field} is '{selected_type}' but the mcp_servers.{role} override "
                f"looks like '{name}'. The agent prompts target '{selected_type}' tools, so "
                f"the agent will likely call tools the configured server does not provide. "
                f"Set {type_field} to '{name}' to match the override (or fix the override)."
            )
    return None


def mcp_server_mismatch_warnings(
    observability_type: str,
    issue_tracker_type: str,
    code_host_type: str,
    mcp_servers: dict[str, Any],
    fix_enabled: bool = True,
) -> list[str]:
    """Detect MCP server overrides that disagree with their selected provider type,
    across all three interchangeable roles. Returns one message per mismatch.

    In triage-only mode (``fix_enabled=False``) the code host is never launched,
    so its override (if any) is ignored rather than flagged."""
    from fixbot.defaults import (
        CODE_HOST_PROVIDERS,
        ISSUE_TRACKER_PROVIDERS,
        OBSERVABILITY_PROVIDERS,
    )

    roles = [
        ("observability", "observability_type", observability_type, OBSERVABILITY_PROVIDERS),
        ("issue_tracker", "issue_tracker_type", issue_tracker_type, ISSUE_TRACKER_PROVIDERS),
    ]
    if fix_enabled:
        roles.append(("code_host", "code_host_type", code_host_type, CODE_HOST_PROVIDERS))
    messages: list[str] = []
    for role, type_field, selected_type, providers in roles:
        msg = _role_mismatch_warning(role, type_field, selected_type, providers, mcp_servers)
        if msg:
            messages.append(msg)
    return messages


def load_config(
    config_path: Path | str,
    resolve_env: bool = True,
) -> FixbotConfig:
    """Load and validate a fixbot.json config file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {config_path}: {e}") from e

    merged = deep_merge(DEFAULT_CONFIG, raw)

    if resolve_env:
        merged = resolve_env_vars(merged)

    from fixbot.defaults import (
        CODE_HOST_PROVIDERS,
        ISSUE_TRACKER_PROVIDERS,
        OBSERVABILITY_PROVIDERS,
    )

    observability_type = merged.get("observability_type", "datadog")
    if observability_type not in OBSERVABILITY_PROVIDERS:
        available = ", ".join(sorted(OBSERVABILITY_PROVIDERS))
        raise ConfigError(
            f"Unknown observability_type '{observability_type}'. Available: {available}"
        )

    obs_provider = OBSERVABILITY_PROVIDERS[observability_type]
    raw_orch = raw.get("orchestrator", {})
    if "log_query" not in raw_orch:
        merged["orchestrator"]["log_query"] = obs_provider.DEFAULT_LOG_QUERY

    fix_enabled = bool(merged.get("fix_enabled", True))

    # The code host is only used when fixbot actually fixes bugs. In triage-only
    # mode it is never launched, so an unset/unknown code_host_type is allowed.
    code_host_type = merged.get("code_host_type", "github")
    if fix_enabled and code_host_type not in CODE_HOST_PROVIDERS:
        available = ", ".join(sorted(CODE_HOST_PROVIDERS))
        raise ConfigError(f"Unknown code_host_type '{code_host_type}'. Available: {available}")

    issue_tracker_type = merged.get("issue_tracker_type", "linear")
    if issue_tracker_type not in ISSUE_TRACKER_PROVIDERS:
        available = ", ".join(sorted(ISSUE_TRACKER_PROVIDERS))
        raise ConfigError(
            f"Unknown issue_tracker_type '{issue_tracker_type}'. Available: {available}"
        )

    repositories = {
        name: _parse_repository(name, repo_data, require_code_host=fix_enabled)
        for name, repo_data in merged.get("repositories", {}).items()
    }

    # Repositories drive PR creation and service-scoping. In triage-only mode they
    # are optional (the orchestrator can file tickets for any in-scope pattern);
    # in fix mode at least one is required so the bug-fixer has somewhere to work.
    if not repositories and fix_enabled:
        raise ConfigMissingKeyError("repositories")

    log_routing: list[LogRoutingRule] = []
    for i, rule in enumerate(merged.get("log_routing", [])):
        if not isinstance(rule, dict):
            raise ConfigError(f"log_routing[{i}]: expected an object, got {type(rule).__name__}")
        for field_name in ("key", "value", "repo"):
            if field_name not in rule:
                raise ConfigError(f"log_routing[{i}]: missing required field '{field_name}'")
        if rule["repo"] not in repositories:
            raise ConfigError(
                f"log_routing[{i}]: repo '{rule['repo']}' is not a known repository. "
                f"Known repositories: {', '.join(repositories) or '(none)'}"
            )
        log_routing.append(LogRoutingRule(key=rule["key"], value=rule["value"], repo=rule["repo"]))

    return FixbotConfig(
        version=merged["version"],
        observability_type=observability_type,
        code_host_type=code_host_type,
        issue_tracker_type=issue_tracker_type,
        mcp_servers=merged["mcp_servers"],
        repositories=repositories,
        log_routing=log_routing,
        worktree_dir=merged["worktree_dir"],
        orchestrator=_parse_orchestrator_config(merged["orchestrator"]),
        bug_fixer=_parse_agent_config(merged["bug_fixer"]),
        issue_tracker_settings=_parse_issue_tracker_settings(merged["issue_tracker_settings"]),
        read_only_repos=merged.get("read_only_repos", []),
        run_log_dir=merged["run_log_dir"],
        fix_enabled=fix_enabled,
        config_path=config_path,
    )


def load_raw_config(config_path: Path | str) -> dict:
    """Load the raw JSON config without parsing into dataclasses."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    try:
        return json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {config_path}: {e}") from e


def save_raw_config(config_path: Path | str, data: dict) -> None:
    """Write a raw config dict to JSON."""
    config_path = Path(config_path)
    config_path.write_text(json.dumps(data, indent=2) + "\n")
