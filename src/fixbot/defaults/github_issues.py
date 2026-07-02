from typing import Any

NAME = "GitHub Issues"
OPEN_STATES_DESC = "open"
DONE_STATES_DESC = "closed"


def get_default() -> dict[str, Any]:
    return {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {
            "Authorization": "Bearer ${GITHUB_TOKEN}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target GitHub (Issues)?"""
    from fixbot.defaults import server_config_haystack

    return "github" in server_config_haystack(server)


def search_instructions(its: Any) -> str:
    return (
        "Search for issues using:\n"
        "- query: the first 100 characters of the log pattern text\n"
        "- state: all (include both open and closed)\n"
        "- limit: 10"
    )


def create_instructions(its: Any, log_window_hours: int) -> str:
    return (
        "Create an issue with:\n"
        "- title: The log pattern text (truncate to 200 characters if longer). "
        "Preserve wildcards like `*`, `[10-20]`, etc., but **strip any markup tags** "
        "such as `[wildcard]`, `[/wildcard]`, or similar `[tag]`/`[/tag]` wrappers "
        "— only keep the inner content.\n"
        f'- labels: ["{its.error_label}"] for error status, '
        f'["{its.warn_label}"] for warn status\n'
        "- body: A brief placeholder — the bug-fixer will update this with full analysis."
    )


def ticket_id_in_branch() -> str:
    return "<issue-number>-<brief-description>"


def ticket_id_in_branch_example() -> str:
    return "42-model-error"


def ticket_ref_in_commit() -> str:
    return "#<issue-number>"


def ticket_id_description() -> str:
    return "`<issue-number>` is the GitHub issue number (e.g., `42` from issue #42)"
