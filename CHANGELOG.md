# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-07-07

Initial public release.

### Added

- Agentic bug-fixing pipeline built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-agent-sdk): an **orchestrator** fetches production log patterns, files tickets for new issues, and spawns a **bug-fixer** subagent that researches the code, updates the ticket, and opens a PR.
- **Observability providers:** Datadog and Grafana/Loki.
- **Issue trackers:** Linear, GitHub Issues, and Jira.
- **Code hosts:** GitHub, GitLab, and Bitbucket.
- **Triage-only mode** (`fix_enabled: false` / `fixbot run --triage-only`) — file tickets from log patterns without spawning a bug-fixer or opening PRs; no code-host token required.
- **CLI commands:** `init` (interactive and non-interactive `-y`), `run` (with `--dry-run`, `--triage-only`, `--max-fixes`), `check-env`, `config get`, `repo add/list/remove`, and `status`.
- **Configuration** via `fixbot.json` with an annotated `fixbot.example.json` and full reference in `docs/CONFIGURATION.md`.
- **Run logs** written per run to `run_log_dir` (default `.fixbot/logs/`), viewable with `fixbot status`.
- Flexible Anthropic authentication: `ANTHROPIC_API_KEY` when set, with fallback to an authenticated Claude Code session.

[Unreleased]: https://github.com/Ryams/fixbot/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Ryams/fixbot/releases/tag/v1.0.0
