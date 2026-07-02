# Contributing to fixbot

Thanks for your interest in improving fixbot! This guide covers how to set up a dev environment and the conventions the project follows.

## Development setup

Fixbot uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
# Clone your fork
git clone https://github.com/<your-username>/fixbot.git
cd fixbot

# Install the package with dev dependencies into a managed virtualenv
uv sync --extra dev
```

You'll also need `git` and `npx` (Node.js) on your `PATH` to exercise the agent end to end, plus the API keys for whichever providers you're testing against — but those are **not** required to run the test suite, which mocks the Claude Agent SDK and all external services.

## Before you open a PR

The CI pipeline runs lint, type checking, and tests across Python 3.11–3.13. Run the same checks locally:

```bash
uv run ruff format src tests   # auto-format (CI runs `--check`)
uv run ruff check src tests    # lint
uv run mypy src                # type check
uv run pytest                  # tests
```

All four must pass. CI will reject a PR if `ruff format --check`, `ruff check`, `mypy`, or `pytest` fails.

## Conventions

- **Tests are expected.** New behavior should come with tests. The suite is fast (~1s) and mocks external services — see `tests/conftest.py` for the shared config and per-provider env-var fixtures, and the existing `test_*.py` files for patterns (CLI tests use `click.testing.CliRunner`; agent tests mock the SDK `query` with async-generator fakes).
- **Type hints.** The codebase uses modern hints (`str | None`, `from __future__ import annotations`) and is checked with mypy. Keep new code typed.
- **Adding a provider.** Observability, issue-tracker, and code-host providers are pluggable modules under `src/fixbot/defaults/`. To add one, create a module implementing the role's interface (`NAME`, `get_default()`, `looks_like()`, and the role-specific prompt/instruction hooks), register it in `src/fixbot/defaults/__init__.py`, and add prompt-rendering tests mirroring the existing provider tests in `tests/test_prompts.py`.
- **Keep prompts and parsers in sync.** Some orchestrator logic parses the orchestrator prompt template; if you change one, change the other and add a test that pins them together.
- **Docs.** If you add or change a config field or CLI command, update `README.md`, `docs/CONFIGURATION.md`, and `fixbot.example.json` to match.

## Branches and commits

- Branch off `main`; open PRs against `main`.
- Use clear, present-tense commit messages (e.g. `feat: add Sentry observability provider`, `fix: handle empty log pattern list`).
- Keep PRs focused — one logical change per PR is easier to review.

## Reporting bugs and security issues

- **Bugs:** open an issue using the bug-report template.
- **Security vulnerabilities:** do **not** open a public issue — see [SECURITY.md](SECURITY.md) for private reporting.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE) that covers the project.
