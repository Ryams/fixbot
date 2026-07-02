from typing import Any

NAME = "Datadog"
DEFAULT_LOG_QUERY = "status:(error OR warn) env:production"


def get_default() -> dict[str, Any]:
    # Datadog's hosted MCP server. It defaults to OAuth but also accepts an API
    # key + application key via the DD_API_KEY / DD_APPLICATION_KEY headers,
    # which is what makes it usable headlessly (CI, no browser). The application
    # key must be scoped to read/write data through MCP, otherwise the server
    # returns 403 "Failed permission authorization checks".
    #
    # The /api/unstable/ path is the currently documented endpoint and may be
    # versioned later; see https://docs.datadoghq.com/bits_ai/mcp_server/setup/.
    # For non-US1 sites the host differs (e.g. mcp.datadoghq.eu).
    return {
        "type": "http",
        "url": "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
        "headers": {
            "DD_API_KEY": "${DD_API_KEY}",
            "DD_APPLICATION_KEY": "${DD_APP_KEY}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target Datadog?"""
    from fixbot.defaults import server_config_haystack

    text = server_config_haystack(server)
    return "datadog" in text or "dd_api_key" in text or "dd_app_key" in text


def orchestrator_log_fetch_instructions(
    log_query: str, log_window_hours: int, max_patterns: int
) -> str:
    return f"""### Step 1: Fetch Log Patterns

Call the observability log search tool with:
- query: `{log_query}`
- from: `now-{log_window_hours}h`
- to: `now`
- use_log_patterns: **true**
- max_tokens: 5000

If no patterns are returned, report that no errors were found and exit.

### Step 1b: Sort and Trim Patterns

Sort patterns by count descending. **Keep only the top {max_patterns} patterns** — discard the rest entirely (do not mention them in output). This is the working set for triage."""


def bug_fixer_log_fetch_instructions(log_window_hours: int) -> str:
    return f"""### Phase 1: Fetch a Representative Raw Log

Use the observability log search tool with:
- query: `status:<error_or_warn> env:production "<key phrase from the pattern>"` — pick a distinctive phrase from the pattern to match raw instances
- from: `now-{log_window_hours}h`
- to: `now`
- use_log_patterns: **false** (we want raw logs)
- max_tokens: 7000
- extra_fields: ["*"]"""
