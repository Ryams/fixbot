from typing import Any

NAME = "Bitbucket"
CLONE_BASE_URL = "https://x-token-auth:${BITBUCKET_TOKEN}@bitbucket.org"
PR_URL_HINT = "bitbucket.org/.../pull-requests/..."
PR_TERM = "PR"


def get_default() -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-bitbucket"],
        "env": {
            "BITBUCKET_TOKEN": "${BITBUCKET_TOKEN}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target Bitbucket?"""
    from fixbot.defaults import server_config_haystack

    return "bitbucket" in server_config_haystack(server)
