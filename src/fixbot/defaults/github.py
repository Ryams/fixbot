from typing import Any

NAME = "GitHub"
CLONE_BASE_URL = "https://${GITHUB_TOKEN}@github.com"
PR_URL_HINT = "github.com/.../pull/..."
PR_TERM = "PR"


def get_default() -> dict[str, Any]:
    return {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {
            "Authorization": "Bearer ${GITHUB_TOKEN}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target GitHub?"""
    from fixbot.defaults import server_config_haystack

    return "github" in server_config_haystack(server)
