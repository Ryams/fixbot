from typing import Any

NAME = "Jira"
OPEN_STATES_DESC = "an open status (Open, To Do, In Progress, Reopened)"
DONE_STATES_DESC = "Done, Closed, or Resolved"


def get_default() -> dict[str, Any]:
    return {
        "type": "http",
        "url": "${JIRA_MCP_URL}",
        "headers": {
            "Authorization": "Bearer ${JIRA_API_TOKEN}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target Jira?"""
    from fixbot.defaults import server_config_haystack

    return "jira" in server_config_haystack(server)


def search_instructions(its: Any) -> str:
    return (
        f"Search for issues using JQL:\n"
        f'- project = "{its.jira_project_key}"\n'
        f"- text ~ the first 100 characters of the log pattern text (quoted)\n"
        f"- include all statuses (open and resolved)\n"
        f"- limit: 10"
    )


def create_instructions(its: Any, log_window_hours: int) -> str:
    return (
        f"Create an issue with:\n"
        f'- project: "{its.jira_project_key}"\n'
        f'- issue type: "{its.jira_issue_type}"\n'
        f"- summary: The log pattern text (truncate to 200 characters if longer). "
        f"Preserve wildcards like `*`, `[10-20]`, etc., but **strip any markup tags** "
        f"such as `[wildcard]`, `[/wildcard]`, or similar `[tag]`/`[/tag]` wrappers "
        f"— only keep the inner content.\n"
        f'- priority: "{its.jira_error_priority}" for error status, '
        f'"{its.jira_warn_priority}" for warn status\n'
        f"- description: A brief placeholder — the bug-fixer will update this with full analysis."
    )


def ticket_id_in_branch() -> str:
    return "<ticket-id-lowercase>-<brief-description>"


def ticket_id_in_branch_example() -> str:
    return "eng-42-model-error"


def ticket_ref_in_commit() -> str:
    return "<TICKET-ID>"


def ticket_id_description() -> str:
    return (
        "`<ticket-id-lowercase>` is the Jira issue key in lowercase (e.g., `eng-42` from `ENG-42`)"
    )
