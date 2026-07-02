from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from claude_agent_sdk.types import AgentDefinition

if TYPE_CHECKING:
    from fixbot.config import FixbotConfig


def build_definition(
    config: FixbotConfig, mcp_server_names: list[str] | None = None
) -> AgentDefinition:
    from fixbot.prompts import bug_fixer

    prompt = bug_fixer.render(config)

    from fixbot.defaults import get_code_host_provider

    provider = get_code_host_provider(config.code_host_type)

    defn = AgentDefinition(
        description=(
            "Investigates a production log pattern, researches the codebase "
            f"in a git worktree, updates the issue tracker, and submits a {provider.PR_TERM} with a fix."
        ),
        prompt=prompt,
        tools=[
            "mcp__observability__*",
            "mcp__issue_tracker__*",
            "mcp__code_host__*",
            "Read",
            "Write",
            "Edit",
            "Grep",
            "Glob",
            "Bash",
            "Agent",
        ],
        # AgentDefinition.mcpServers accepts server names (str) or inline server
        # dicts; we only ever pass names referencing options.mcp_servers.
        mcpServers=cast(list[str | dict[str, Any]] | None, mcp_server_names),
        model=config.bug_fixer.model,
        maxTurns=config.bug_fixer.max_turns,
        permissionMode="bypassPermissions",
        effort=config.bug_fixer.effort,
    )

    return defn
