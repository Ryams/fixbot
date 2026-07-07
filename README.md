<p align="center">
  <img src="https://raw.githubusercontent.com/Ryams/fixbot/main/img/fixbot_logo.png" alt="Fixbot" width="245">
</p>

<p align="center">
  <em>Turn production errors into pull requests, automatically.</em>
</p>

<p align="center">
  <a href="https://github.com/Ryams/fixbot/actions/workflows/ci.yml"><img src="https://github.com/Ryams/fixbot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Ryams/fixbot/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://github.com/Ryams/fixbot/blob/main/pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
</p>

## What fixbot is

Fixbot is a CLI tool for automatically detecting and fixing production errors from your logs. It triages errors, tracks them in your issue tracker, and proposes code fixes as PRs, cutting down the time and engineering effort it takes to resolve production issues. Under the hood, Fixbot is a lightweight harness around an agentic system built with the [Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-agent-sdk), plugging into many of the tools you already use.

## How it works

1. Fixbot fetches log patterns from your observability platform
2. Checks for existing tickets in your issue tracker 
3. New patterns get a new ticket and are addressed by a **bug-fixer** subagent
4. The bug-fixer updates tickets with findings and submits PRs

![fixbot architecture: the orchestrator fetches log patterns from observability and searches/creates tickets in the issue tracker; the bug-fixer it spawns clones the repo from the code host, researches and updates the ticket, and submits a PR](https://raw.githubusercontent.com/Ryams/fixbot/main/img/fixbot_diagram.png)

**Triage-only mode:** set `"fix_enabled": false` (or run `fixbot run --triage-only`) to stop after step 2 — fixbot fetches patterns and files tickets, but never spawns a bug-fixer or opens a PR. Useful when a separate workflow acts on the tickets. In this mode the code host is optional and `repositories` aren't required. See [docs/CONFIGURATION.md](https://github.com/Ryams/fixbot/blob/main/docs/CONFIGURATION.md#fix_enabled-mode).

## Prerequisites

- Python 3.11+
- `git`, `npx` in PATH
- API keys: `ANTHROPIC_API_KEY`, plus keys for your configured providers:
  - **Observability** — `DD_API_KEY`/`DD_APP_KEY` (Datadog) or `GRAFANA_URL`/`GRAFANA_API_KEY` (Grafana)
  - **Issue tracker** — `LINEAR_API_KEY` (Linear), `GITHUB_TOKEN` (GitHub Issues), or `JIRA_MCP_URL`/`JIRA_API_TOKEN` (Jira)
  - **Code host** — `GITHUB_TOKEN`, `GITLAB_TOKEN`, or `BITBUCKET_TOKEN` (not needed in [triage-only mode](https://github.com/Ryams/fixbot/blob/main/docs/CONFIGURATION.md#fix_enabled-mode))

  Run `fixbot check-env` to see which variables your configuration needs.

  `ANTHROPIC_API_KEY` takes priority when set (use it for a dedicated service account); if it is unset, fixbot falls back to an authenticated Claude Code session. See [Anthropic authentication](https://github.com/Ryams/fixbot/blob/main/docs/CONFIGURATION.md#anthropic-authentication).

## Installation

Fixbot is a command-line tool, so the cleanest install is into an isolated environment with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install fixbot
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install fixbot
```

You can also install it into the current environment with pip:

```bash
pip install fixbot
```

To install from source (e.g. for development), see [CONTRIBUTING.md](https://github.com/Ryams/fixbot/blob/main/CONTRIBUTING.md).

## Quick start

### 1. Initialize config

```bash
fixbot init
```

This creates `fixbot.json`, prompting interactively for your observability platform, mode (fix or triage-only), code host, repositories, issue tracker, and other settings.

To generate the config without prompts (for scripts or agents), pass `--non-interactive`/`-y` and supply values via flags; anything omitted falls back to defaults:

```bash
fixbot init -y \
  --observability-type datadog \
  --issue-tracker-type linear \
  --repo myorg/api --repo myorg/worker \
  --branch-prefix fixbot \
  --set team=Engineering --set ticket_prefix=ENG
```

Use `--triage-only` with `--service NAME` for triage mode, and `--set KEY=VALUE` (repeatable) for any `issue_tracker_settings` field. In non-interactive mode an existing `fixbot.json` is overwritten (with a notice). Run `fixbot init --help` for the full list.

### 2. Set environment variables

Set `ANTHROPIC_API_KEY` plus the keys for your chosen providers. Example for the defaults (Datadog + Linear + GitHub):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export DD_API_KEY=...
export DD_APP_KEY=...
export LINEAR_API_KEY=lin_api_...
export GITHUB_TOKEN=ghp_...
```

Then confirm your configuration has everything it needs:

```bash
fixbot check-env
```

### 3. Dry run

```bash
fixbot run --dry-run --verbose
```

Fetches log patterns and checks the issue tracker without creating tickets or PRs.

### 4. Full run

```bash
fixbot run --verbose
```

## CLI commands

| Command | Description |
|---|---|
| `fixbot --version` | Show the fixbot version |
| `fixbot --help` | Show available commands and options |
| `fixbot init` | Interactive config setup |
| `fixbot init -y` | Non-interactive config setup from flags/defaults |
| `fixbot run` | Run the bug fix pipeline |
| `fixbot run --dry-run` | Preview what would happen without making changes |
| `fixbot run --triage-only` | File tickets from log patterns without spawning a bug-fixer or opening PRs |
| `fixbot run --max-fixes N` | Override max code fixes per run |
| `fixbot check-env` | Verify that required environment variables are set |
| `fixbot config get <key>` | Read a config value (e.g. `orchestrator.model`) |
| `fixbot repo add <org/repo>` | Add a repository (use `--read-only` for read-only repos) |
| `fixbot repo list` | List configured repositories |
| `fixbot repo remove <name>` | Remove a repository |
| `fixbot status` | Show the most recent run summary (use `--last N` to show more) |

## Configuration

Fixbot supports several popular providers:

| Role | `*_type` field | Options | Default |
|---|---|---|---|
| Observability | `observability_type` | `datadog`, `grafana` | `datadog` |
| Issue tracker | `issue_tracker_type` | `linear`, `github`, `jira` | `linear` |
| Code host | `code_host_type` | `github`, `gitlab`, `bitbucket` | `github` |

See **[docs/CONFIGURATION.md](https://github.com/Ryams/fixbot/blob/main/docs/CONFIGURATION.md)** and the annotated [`fixbot.example.json`](https://github.com/Ryams/fixbot/blob/main/fixbot.example.json) for a complete description of the configuration file.

> **Note (Grafana/Loki only):** run Loki with the **pattern ingester enabled** (`pattern_ingester.enabled: true`) so `query_loki_patterns` works. Without it fixbot falls back to raw-log fetching, which costs far more tokens. Enabled by default on Grafana Cloud; self-hosted Loki must opt in. See [`observability_type`](https://github.com/Ryams/fixbot/blob/main/docs/CONFIGURATION.md#observability_type).

## Scheduling

Fixbot does not include a built-in scheduler. Run it locally, with any scheduler, or through CI.

See [`examples/github-actions-scheduled.yml`](https://github.com/Ryams/fixbot/blob/main/examples/github-actions-scheduled.yml) for a GitHub Actions example.

In CI/CD, skip `fixbot init` (it is interactive) — provide a `fixbot.json` and supply secrets separately via environment variables.

## Run logs

Each run writes a JSON log to the configured `run_log_dir` (default: `.fixbot/logs/`). View the latest with:

```bash
fixbot status
```

## Getting the best results

Adding `CLAUDE.md` files to your repositories is one way to improve fixbot's tickets and fixes — they give the agent the architecture notes, conventions, and domain context it can't infer from logs and code alone. Log quality matters too: descriptive error messages with stack traces and useful context give fixbot more to work with, while vague or noisy logs make patterns harder to diagnose. Even so, fixbot can't fix everything: infrastructure or config faults, bad data, and issues needing business context aren't always solvable in code. Fixbot can handle the well-scoped, code-level issues and will simply file tickets for the rest.

## Security

Fixbot handles multiple API tokens and acts autonomously on production log content — reading it, filing tickets, and opening PRs. Keep these best practices in mind:

- **Scope tokens to least privilege.** Grant each provider token only the access it needs — repo-scoped code-host tokens, read-only observability keys, a dedicated Anthropic key. In triage-only mode no code-host token is needed at all.
- **Keep a human in the loop.** Fixbot opens PRs but never merges them; review before merging and don't auto-merge.

For further security guidelines, see **[SECURITY.md](https://github.com/Ryams/fixbot/blob/main/SECURITY.md)**.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

Copyright (c) 2026 Ryan Staab
