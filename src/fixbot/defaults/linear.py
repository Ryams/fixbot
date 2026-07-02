from typing import Any

NAME = "Linear"
OPEN_STATES_DESC = "an open state (Review, Todo, Backlog, In Progress)"
DONE_STATES_DESC = "Done or Canceled"


def get_default() -> dict[str, Any]:
    return {
        "type": "http",
        "url": "https://mcp.linear.app/mcp",
        "headers": {
            "Authorization": "Bearer ${LINEAR_API_KEY}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target Linear?"""
    from fixbot.defaults import server_config_haystack

    return "linear" in server_config_haystack(server)


def search_instructions(its: Any) -> str:
    return (
        f"Search for issues with:\n"
        f'- team: "{its.team}"\n'
        f'- project: "{its.project}"\n'
        f"- query: the first 100 characters of the log pattern text\n"
        f"- limit: 10"
    )


def create_instructions(its: Any, log_window_hours: int) -> str:
    return (
        f"Create an issue with:\n"
        f'- team: "{its.team}"\n'
        f'- project: "{its.project}"\n'
        f"- title: The log pattern text (truncate to 200 characters if longer). "
        f"Preserve wildcards like `*`, `[10-20]`, etc., but **strip any markup tags** "
        f"such as `[wildcard]`, `[/wildcard]`, or similar `[tag]`/`[/tag]` wrappers "
        f"— only keep the inner content.\n"
        f"- priority: **{its.error_priority}** (High) for error status, "
        f"**{its.warn_priority}** (Normal) for warn status\n"
        f"- description: A brief placeholder — the bug-fixer will update this with full analysis."
    )


def ticket_id_in_branch() -> str:
    return "<ticket-id-lowercase>-<brief-description>"


def ticket_id_in_branch_example() -> str:
    return "eng-892-model-error"


def ticket_ref_in_commit() -> str:
    return "<TICKET-ID>"


def ticket_id_description() -> str:
    return "`<ticket-id-lowercase>` is the ticket identifier in lowercase (e.g., `eng-892` from `ENG-892`)"
