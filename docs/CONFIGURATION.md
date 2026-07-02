# Configuration reference

Fixbot is configured via `fixbot.json`. See [`fixbot.example.json`](../fixbot.example.json) for a complete example. All fields have sensible defaults — only `repositories` is required.

All string values support `${ENV_VAR}` interpolation, resolved from the environment at startup (see [Environment variable interpolation](#environment-variable-interpolation)).

## Anthropic authentication

Fixbot runs on the Claude Agent SDK, which drives the `claude` CLI. Two ways to authenticate:

- **`ANTHROPIC_API_KEY`** — if this env var is set, it is used and **takes priority** over any logged-in Claude Code session. This is the recommended setup for running fixbot under a **dedicated service account** (separate billing/usage from a developer's personal subscription), and the only option for headless/CI runs.
- **Claude Code session** — if `ANTHROPIC_API_KEY` is *not* set and the host has an authenticated `claude` CLI (via `claude /login` or `CLAUDE_CODE_OAUTH_TOKEN`), fixbot falls back to that session's credentials.

The precedence is enforced by the CLI itself (`ANTHROPIC_API_KEY` outranks the subscription session in its credential order), so to switch to a service account you just export the key — no config change. `fixbot check-env` reports `ANTHROPIC_API_KEY` as missing when it's unset; that is expected if you intend to use a Claude Code session, and the run will still proceed. Conversely, if you set `ANTHROPIC_API_KEY`, make sure it is **valid** — an invalid key fails the run (it does not silently fall back to the session).

## `fix_enabled` (mode)

| Field | Default | Description |
|---|---|---|
| `fix_enabled` | `true` | When `true`, fixbot files a ticket **and** spawns a bug-fixer to open a PR with a proposed fix. When `false`, fixbot runs in **triage-only** mode: it fetches log patterns, checks the issue tracker, creates tickets for unaddressed issues, and stops. |

Triage-only mode is for setups where a separate workflow (your own agent, an on-call rotation, etc.) acts on the tickets fixbot files. In this mode:

- **The code host is not used at all.** `code_host_type`, the `code_host` MCP server, and the code-host credential (e.g. `GITHUB_TOKEN`) are not required and are ignored if present. `fixbot check-env` will not ask for them.
- **`repositories` is optional.** Listed repositories (by name) still scope which services get tickets, but `code_host_repo` is not required on them. With no repositories and no `log_routing`, every fetched pattern is in scope.
- No bug-fixer subagent is registered, no worktrees are created, and no branches or PRs are opened.

You can also force a one-off triage run on a fix-enabled install with `fixbot run --triage-only`. (That run still skips the bug-fixer, but the code host stays configured.)

## Providers

Fixbot integrates with three pluggable provider "roles". Each role has a `*_type` field that selects the provider and, in turn, the default MCP server, the syntax/terminology used in agent prompts, and the relevant settings. You can override the MCP server for any role via [`mcp_servers`](#mcp_servers).

### `observability_type`

Selects the observability platform — determines the default MCP server, the default `log_query` syntax, and how the orchestrator fetches log patterns.

| Value | Default MCP server | Default log query | Env vars |
|---|---|---|---|
| `datadog` (default) | `mcp.datadoghq.com` (hosted, HTTP) | `status:(error OR warn) env:production` | `DD_API_KEY`, `DD_APP_KEY` |
| `grafana` | `mcp-grafana` (stdio) | `{level=~"error\|warn"}` | `GRAFANA_URL`, `GRAFANA_API_KEY` |

In both cases the orchestrator fetches pre-aggregated log patterns with occurrence counts — Datadog's log patterns, or Loki's `query_loki_patterns` (the Grafana flow first calls `list_datasources` to locate the Loki datasource). The two platforms use different query syntaxes, which is why the default `log_query` differs per platform.

> **Datadog:** the default uses Datadog's hosted MCP server over HTTP, authenticating with `DD_API_KEY` / `DD_APPLICATION_KEY` headers (no OAuth, so it works headlessly in CI). The **application key must be scoped to read/write data through MCP** — without that scope the server returns `403 "Failed permission authorization checks"` even though the keys are valid. For non-US1 sites, change the `mcp.datadoghq.com` host accordingly (e.g. `mcp.datadoghq.eu`).

> **Grafana/Loki — enable the pattern ingester.** The orchestrator's primary path is `query_loki_patterns`, which calls Loki's `/loki/api/v1/patterns` endpoint. That endpoint returns **404 unless Loki is run with the pattern ingester enabled**:
> ```yaml
> # loki-config.yaml
> pattern_ingester:
>   enabled: true
> ```
> Without it, fixbot still works — it falls back to fetching raw log lines via `query_loki_logs` and grouping them itself — but that is **substantially more expensive in tokens**. Grafana Cloud has pattern ingestion enabled by default; **self-hosted Loki must opt in.** Note the ingester only builds patterns from logs ingested *after* it is enabled, and needs some live volume before patterns appear.

### `code_host_type`

Selects the code host — determines the default MCP server, clone URLs, and PR/MR terminology in agent prompts.

| Value | Default MCP server | Clone domain | Term |
|---|---|---|---|
| `github` (default) | GitHub Copilot MCP (http) | `github.com` | PR |
| `gitlab` | `@modelcontextprotocol/server-gitlab` (stdio) | `gitlab.com` | MR |
| `bitbucket` | `@modelcontextprotocol/server-bitbucket` (stdio) | `bitbucket.org` | PR |

When set to `gitlab` or `bitbucket`, fixbot expects `GITLAB_TOKEN` or `BITBUCKET_TOKEN` respectively instead of `GITHUB_TOKEN`.

### `issue_tracker_type`

Selects the issue tracker — determines the default MCP server, the ticket terminology and open/done state names in agent prompts, and which [`issue_tracker_settings`](#issue_tracker_settings) fields apply.

| Value | Default MCP server | Env vars |
|---|---|---|
| `linear` (default) | `https://mcp.linear.app/mcp` (http) | `LINEAR_API_KEY` |
| `github` (GitHub Issues) | GitHub Copilot MCP (http) | `GITHUB_TOKEN` |
| `jira` | `${JIRA_MCP_URL}` (http) | `JIRA_MCP_URL`, `JIRA_API_TOKEN` |

The GitHub Issues tracker reuses `GITHUB_TOKEN`, so pairing it with the `github` code host needs no extra credentials.

## `repositories` (required in fix mode)

The code repositories fixbot can investigate and fix. Each key is a short name you choose. Required when `fix_enabled` is `true`; optional in triage-only mode (see [`fix_enabled`](#fix_enabled-mode)).

| Field | Required | Description |
|---|---|---|
| `code_host_repo` | yes | Code host identifier (e.g. `myorg/my-api`) used for PR creation |
| `repo_path` | no | Absolute path to a local git checkout. When omitted, the bug-fixer clones the repository on demand. Supports `${ENV_VAR}` interpolation (e.g. `${GITHUB_WORKSPACE}`) |

Local path (typical for persistent hosts):

```json
{
  "repositories": {
    "my-api": {
      "repo_path": "/home/user/repos/my-api",
      "code_host_repo": "myorg/my-api"
    }
  }
}
```

Clone-on-demand (typical for ephemeral CI):

```json
{
  "repositories": {
    "my-api": {
      "code_host_repo": "myorg/my-api"
    }
  }
}
```

## `orchestrator`

Controls the orchestrator agent that fetches log patterns, triages them, and spawns bug-fixers.

| Field | Default | Description |
|---|---|---|
| `model` | `claude-sonnet-4-6` | Claude model to use for the orchestrator |
| `max_turns` | `100` | Maximum number of agent turns before the orchestrator stops |
| `max_budget_usd` | `5.00` | Spending cap (USD) for the orchestrator's API usage |
| `effort` | `high` | Agent effort level (`low`, `medium`, or `high`) |
| `thinking` | `null` | Extended thinking configuration. Set to `{"type": "enabled", "budget_tokens": N}` to enable |
| `log_query` | platform-specific | Query string passed to the observability platform to fetch log patterns. Uses the platform's native syntax. Defaults to the selected `observability_type`'s default query |
| `log_query_filters` | `null` | Optional extra filter clause appended to `log_query` (space-separated) to form the effective query — e.g. `service:(my-api OR worker-service)`. Keep it separate from `log_query` so the base query stays reusable. Must use the platform's native syntax |
| `log_window_hours` | `6` | How far back to search for log patterns |
| `max_code_fixes_per_run` | `3` | Stop spawning new bug-fixers after this many produce a code change (PR). Patterns that are skipped or produce no fix don't count toward this limit |
| `max_patterns_to_process` | `20` | Maximum number of log patterns to triage per run, regardless of outcome |
| `filter_instructions` | `null` | Natural-language filtering rules the orchestrator follows when deciding which patterns to investigate. Useful for exclusions or conditions that can't be expressed in the `log_query` |

## `bug_fixer`

Controls the bug-fixer subagent that investigates a single log pattern, researches the codebase, and submits a PR.

| Field | Default | Description |
|---|---|---|
| `model` | `claude-sonnet-4-6` | Claude model to use for bug-fixers |
| `max_turns` | `200` | Maximum number of agent turns per bug-fixer |
| `max_budget_usd` | `3.00` | Spending cap (USD) per bug-fixer |
| `effort` | `high` | Agent effort level (`low`, `medium`, or `high`) |
| `thinking` | `null` | Extended thinking configuration, same format as orchestrator |

## `issue_tracker_settings`

Controls how fixbot creates and searches for tickets. Only the fields relevant to your `issue_tracker_type` are used — the others are ignored — so you only need to set the group that matches your tracker.

Applies to every tracker:

| Field | Default | Description |
|---|---|---|
| `branch_prefix` | `fixbot` | Prefix for git branches (e.g. `fixbot/eng-123-fix-timeout`). Typically your username or bot name |

When `issue_tracker_type` is `linear`:

| Field | Default | Description |
|---|---|---|
| `team` | `Engineering` | Linear team name for ticket routing |
| `project` | `fixbot` | Linear project where tickets are created |
| `ticket_prefix` | `ENG` | Prefix used in ticket identifiers (e.g. `ENG-123`) |
| `error_priority` | `2` | Priority assigned to error-status patterns (Linear: 1=Urgent, 2=High, 3=Normal, 4=Low) |
| `warn_priority` | `3` | Priority assigned to warn-status patterns |

When `issue_tracker_type` is `github` (GitHub Issues):

| Field | Default | Description |
|---|---|---|
| `error_label` | `bug` | Label applied to issues created for error-status patterns |
| `warn_label` | `warning` | Label applied to issues created for warn-status patterns |

When `issue_tracker_type` is `jira`:

| Field | Default | Description |
|---|---|---|
| `jira_project_key` | `ENG` | Jira project key where issues are created (e.g. `ENG-123`) |
| `jira_issue_type` | `Bug` | Issue type for created tickets |
| `jira_error_priority` | `High` | Priority name assigned to error-status patterns |
| `jira_warn_priority` | `Medium` | Priority name assigned to warn-status patterns |

## `mcp_servers`

Fixbot uses three MCP server roles with built-in defaults driven by the `*_type` fields above. Override any role to swap in a custom or self-hosted server.

| Role | Default provider | Purpose |
|---|---|---|
| `observability` | Datadog (stdio) | Fetch log patterns |
| `issue_tracker` | Linear (http) | Search/create tickets |
| `code_host` | GitHub (http) | PR creation |

Each server is either `stdio` (local process) or `http` (remote endpoint):

```json
{
  "mcp_servers": {
    "observability": {
      "type": "http",
      "url": "https://your-grafana-mcp.example.com/mcp"
    }
  }
}
```

An override fully replaces the role's default server. Keep it consistent with the role's `*_type` — if the override targets a different known provider (e.g. `code_host_type` is `github` but the override looks like GitLab), fixbot refuses to run, since the agent prompts would call tools the server doesn't provide. Any additional keys beyond the three roles are passed through as extra MCP servers available to both agents.

## `log_routing`

Optional list of rules that map log fields to repositories. When configured, the orchestrator and bug-fixer use these rules to determine which repository to investigate for a given log pattern. When omitted, the bug-fixer searches all configured repositories.

```json
{
  "log_routing": [
    {"key": "service", "value": "my-api", "repo": "my-api"},
    {"key": "service", "value": "api-service", "repo": "my-api"}
  ]
}
```

Each rule requires `key` (the log field), `value` (the field value to match), and `repo` (which must match a key in `repositories`).

## Other fields

| Field | Default | Description |
|---|---|---|
| `worktree_dir` | `.worktrees` | Directory where git worktrees are created for bug-fixer work. Each fix gets an isolated worktree so the main checkout is never modified |
| `read_only_repos` | `[]` | Additional repository paths the bug-fixer can read (via worktree) but not modify. Useful for shared libraries or monorepo dependencies |
| `run_log_dir` | `.fixbot/logs` | Directory where JSON run logs are written. View the latest with `fixbot status` |

## Environment variable interpolation

All string values in the config support `${ENV_VAR}` interpolation, resolved from `os.environ` at startup. This is especially useful for CI environments where paths and secrets vary per run:

```json
{
  "repositories": {
    "my-api": {
      "repo_path": "${GITHUB_WORKSPACE}",
      "code_host_repo": "myorg/my-api"
    }
  },
  "worktree_dir": "${RUNNER_TEMP}/.worktrees"
}
```
