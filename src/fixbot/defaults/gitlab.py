from typing import Any

NAME = "GitLab"
CLONE_BASE_URL = "https://oauth2:${GITLAB_TOKEN}@gitlab.com"
PR_URL_HINT = "gitlab.com/.../-/merge_requests/..."
PR_TERM = "MR"


def get_default() -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gitlab"],
        "env": {
            "GITLAB_PERSONAL_ACCESS_TOKEN": "${GITLAB_TOKEN}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target GitLab?"""
    from fixbot.defaults import server_config_haystack

    return "gitlab" in server_config_haystack(server)
