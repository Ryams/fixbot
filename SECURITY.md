# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, report privately through:

- **GitHub private vulnerability reporting** — on the repository's **Security** tab, click **Report a vulnerability**. This opens a private advisory visible only to maintainers.

Please include enough detail to reproduce: affected version or commit, configuration (with secrets redacted), and the impact you observed. We aim to acknowledge reports within a few business days and will keep you updated as we investigate and ship a fix.

## Supported versions

Security fixes target the latest `main`; there is no backport guarantee for older revisions. Pin to a specific commit if you need a stable base, and watch releases for security-relevant changes.

## Handling credentials and tokens

Fixbot orchestrates several third-party services and therefore handles multiple API tokens (`ANTHROPIC_API_KEY`, plus observability, issue-tracker, and code-host credentials). Treat every one of these as a secret.

- **Never commit secrets.** Pass tokens via environment variables, not `fixbot.json`. Config string values support `${ENV_VAR}` interpolation precisely so secrets stay in the environment — see [docs/CONFIGURATION.md](docs/CONFIGURATION.md#environment-variable-interpolation). `fixbot.json` is gitignored by default; keep it that way.
- **In CI**, use the platform's secret store (e.g. GitHub Actions encrypted secrets), not plaintext workflow values, and avoid echoing secrets into logs.
- Run `fixbot check-env` to confirm only the variables your configuration actually needs are set.

## Scope your tokens to least privilege

Fixbot does not need broad, organization-wide tokens. Grant the narrowest scope that lets each role do its job:

- **Anthropic (`ANTHROPIC_API_KEY`)** — use a key dedicated to fixbot so its usage is isolated and independently revocable. The `max_budget_usd` caps (orchestrator and bug-fixer) bound spend per run, but a dedicated key is still the safer blast radius.
- **Observability**
  - *Datadog* (`DD_API_KEY` / `DD_APP_KEY`) — the application key needs the scope to read/write data through MCP, but nothing more. Don't reuse an admin-scoped key.
  - *Grafana* (`GRAFANA_API_KEY`) — a read-only / Viewer token is sufficient; fixbot only queries log patterns.
- **Issue tracker** (`LINEAR_API_KEY`, `GITHUB_TOKEN`, or `JIRA_*`) — needs to create and comment on tickets in the configured team/project only. Avoid org-admin tokens.
- **Code host** (`GITHUB_TOKEN`, `GITLAB_TOKEN`, or `BITBUCKET_TOKEN`) — restrict to the specific repositories in your config and to the permissions required to clone and open pull/merge requests. A fine-grained token scoped to those repos is strongly preferred over a classic broad token. In **triage-only mode** (`fix_enabled: false`) no code-host token is required at all.

Rotate tokens periodically and immediately if you suspect exposure.

## Autonomy and untrusted input

Fixbot is an agentic tool: it reads production **log content** — which can include attacker-influenced strings — and can act on it autonomously by creating tickets and opening pull requests. Operate it with that trust boundary in mind:

- **Review before merging.** Fixbot opens PRs; it does not merge them. Keep a human in the loop and require review on the branches fixbot writes to. Do not auto-merge fixbot PRs.
- **Prefer least privilege over convenience.** Combined with scoped tokens (above), this limits what a maliciously crafted log line could cause the agent to attempt.
- Run fixbot in an isolated environment (a dedicated CI job or container) rather than on a developer machine with ambient credentials, so its reach is bounded by the tokens you grant it and nothing else.
- Bug-fixers work in isolated git worktrees and never modify your main checkout; `read_only_repos` entries are readable but never written.
