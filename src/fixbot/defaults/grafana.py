from typing import Any

NAME = "Grafana"
DEFAULT_LOG_QUERY = '{level=~"error|warn"}'


def get_default() -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": "mcp-grafana",
        "args": ["stdio"],
        "env": {
            "GRAFANA_URL": "${GRAFANA_URL}",
            "GRAFANA_API_KEY": "${GRAFANA_API_KEY}",
        },
    }


def looks_like(server: dict[str, Any]) -> bool:
    """Heuristic: does this MCP server config appear to target Grafana/Loki?"""
    from fixbot.defaults import server_config_haystack

    text = server_config_haystack(server)
    return "grafana" in text or "loki" in text


def orchestrator_log_fetch_instructions(
    log_query: str, log_window_hours: int, max_patterns: int
) -> str:
    return f"""### Step 1: Discover Loki Datasource

Call `list_datasources` to find the Loki datasource. Note its `uid` — you will need it for log queries.

### Step 1a: Fetch Log Patterns

Call `query_loki_patterns` with:
- datasourceUid: the Loki datasource UID from the previous step
- logql: `{log_query}`
- startRfc3339: an ISO 8601 timestamp from {log_window_hours} hours ago
- endRfc3339: the current ISO 8601 timestamp

The `logql` parameter is a **stream selector only** (no line filters or pipeline stages). It uses LogQL syntax:
- `{{level=~"error|warn"}}` — match error or warn levels
- `{{level="error", namespace="production"}}` — filter by multiple labels
- `{{app=~"svc-a|svc-b"}}` — regex match on a label

This returns a list of patterns with occurrence counts, similar to Datadog log patterns.

If no patterns are returned, report that no errors were found and exit.

### Step 1b: Sort and Trim Patterns

Sort patterns by count descending. **Keep only the top {max_patterns} patterns** — discard the rest entirely (do not mention them in output). This is the working set for triage."""


def bug_fixer_log_fetch_instructions(log_window_hours: int) -> str:
    return f"""### Phase 1: Fetch Representative Raw Logs

First call `list_datasources` to find the Loki datasource and note its `uid`.

Then use the Loki log query tool (`query_loki_logs`) with:
- datasourceUid: the Loki datasource UID from the previous step
- logql: `{{level=~"<error_or_warn>"}} |= "<key phrase from the pattern>"` — pick a distinctive phrase from the pattern to match raw instances
- startRfc3339: an ISO 8601 timestamp from {log_window_hours} hours ago
- endRfc3339: the current ISO 8601 timestamp
- limit: 50

If your initial query returns too few results, broaden it by removing the text filter or widening the time range."""
