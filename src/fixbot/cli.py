from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
from pathlib import Path
from typing import Callable, TypeVar

import click

from fixbot import __version__
from fixbot.config import (
    DEFAULT_CONFIG,
    ENV_VAR_PATTERN,
    deep_merge,
    get_nested,
    load_config,
    load_raw_config,
    mcp_server_mismatch_warnings,
    save_raw_config,
)
from fixbot.exceptions import FixbotError

F = TypeVar("F", bound=Callable[..., object])


def handle_fixbot_errors(f: F) -> F:
    """Convert any FixbotError raised by a command into a clean error message
    on stderr and a non-zero exit, instead of an uncaught traceback."""

    @functools.wraps(f)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return f(*args, **kwargs)
        except FixbotError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

    return wrapper  # type: ignore[return-value]


def _find_config(ctx_config: str | None) -> Path:
    if ctx_config:
        return Path(ctx_config)
    return Path("fixbot.json")


def _repo_name_from_code_host(code_host_repo: str) -> str:
    return code_host_repo.rsplit("/", 1)[-1]


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _collect_env_vars(obj: object) -> set[str]:
    """Find all ${VAR} references in a nested dict/list/str structure."""
    if isinstance(obj, str):
        return set(ENV_VAR_PATTERN.findall(obj))
    elif isinstance(obj, dict):
        found: set[str] = set()
        for v in obj.values():
            found |= _collect_env_vars(v)
        return found
    elif isinstance(obj, list):
        found = set()
        for item in obj:
            found |= _collect_env_vars(item)
        return found
    return set()


class FixbotGroup(click.Group):
    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            click.echo(f"Error: No such command '{args[0]}'.")
            click.echo("Run 'fixbot --help' for a list of available commands.")
            ctx.exit(2)


@click.group(cls=FixbotGroup)
@click.version_option(__version__, prog_name="fixbot")
def cli():
    """Fixbot — Automated production bug detection and fixing."""


@cli.command()
@click.option("--dir", "target_dir", default=".", help="Directory to create fixbot.json in")
def init(target_dir: str):
    """Initialize a new fixbot configuration."""
    target = Path(target_dir).resolve()
    config_path = target / "fixbot.json"

    if config_path.exists():
        if not click.confirm(f"{config_path} already exists. Overwrite?", default=False):
            raise SystemExit(0)

    missing_tools = []
    for tool in ("git", "npx"):
        if not shutil.which(tool):
            missing_tools.append(tool)
    if missing_tools:
        click.echo(
            f"Warning: required tools not found in PATH: {', '.join(missing_tools)}\n"
            "These are needed at runtime for fixbot to function.",
            err=True,
        )

    config: dict = {
        "version": 1,
        "repositories": {},
    }

    click.echo("\n--- Observability ---")
    from fixbot.defaults import OBSERVABILITY_PROVIDERS

    obs_names = sorted(OBSERVABILITY_PROVIDERS.keys())
    click.echo(f"Available observability platforms: {', '.join(obs_names)}")
    observability_type = click.prompt(
        "Observability platform",
        default="datadog",
        type=click.Choice(obs_names, case_sensitive=False),
    )
    config["observability_type"] = observability_type

    if observability_type == "grafana":
        click.echo(
            "\nNote: fixbot's primary path uses Loki's query_loki_patterns "
            "(/loki/api/v1/patterns).\n"
            "Run Loki with the pattern ingester enabled:\n"
            "    pattern_ingester:\n"
            "      enabled: true\n"
            "Otherwise that endpoint 404s and fixbot falls back to fetching raw "
            "logs and grouping\nthem itself, which uses far more tokens. "
            "(Grafana Cloud has this enabled by default.)",
            err=True,
        )

    click.echo("\n--- Mode ---")
    click.echo("fix:    fixbot files a ticket AND opens a PR with a proposed fix.")
    click.echo("triage: fixbot only files tickets from log patterns, then stops.")
    click.echo("        Use triage if a separate workflow acts on the tickets.")
    fix_enabled = click.confirm("\nEnable automated fixing (open PRs)?", default=True)
    config["fix_enabled"] = fix_enabled

    code_host_type = "github"
    if fix_enabled:
        click.echo("\n--- Code Host ---")
        from fixbot.defaults import CODE_HOST_PROVIDERS

        provider_names = sorted(CODE_HOST_PROVIDERS.keys())
        click.echo(f"Available code hosts: {', '.join(provider_names)}")
        code_host_type = click.prompt(
            "Code host type",
            default="github",
            type=click.Choice(provider_names, case_sensitive=False),
        )
        config["code_host_type"] = code_host_type

        click.echo("\n--- Repositories ---")
        click.echo("Add the code repositories fixbot can investigate and fix.")
        click.echo("Enter the code host repo (e.g., org/repo-name). Press Enter to finish.\n")

        while True:
            code_host_repo = click.prompt(
                "Code host repo (org/repo)",
                default="",
                show_default=False,
            )
            if not code_host_repo:
                break

            default_name = _repo_name_from_code_host(code_host_repo)
            if default_name in config["repositories"]:
                suffix = 2
                while f"{default_name}-{suffix}" in config["repositories"]:
                    suffix += 1
                default_name = f"{default_name}-{suffix}"

            name = click.prompt("  Repository name", default=default_name)
            config["repositories"][name] = {
                "code_host_repo": code_host_repo,
            }
            click.echo()

        if not config["repositories"]:
            click.echo(
                "No repositories configured. You can add them later in fixbot.json.", err=True
            )
            config["repositories"] = DEFAULT_CONFIG["repositories"]

        worktree_dir = click.prompt(
            "\nWorktree directory",
            default=str(target / ".worktrees"),
        )
        config["worktree_dir"] = worktree_dir
    else:
        click.echo("\n--- Service scope (optional) ---")
        click.echo("Restrict ticket creation to specific services (by name).")
        click.echo("Press Enter to leave unscoped — fixbot will ticket any in-scope pattern.\n")
        while True:
            service_name = click.prompt("Service name", default="", show_default=False)
            if not service_name:
                break
            config["repositories"][service_name] = {}

    click.echo("\n--- Issue Tracker ---")
    from fixbot.defaults import ISSUE_TRACKER_PROVIDERS

    it_names = sorted(ISSUE_TRACKER_PROVIDERS.keys())
    click.echo(f"Available issue trackers: {', '.join(it_names)}")
    issue_tracker_type = click.prompt(
        "Issue tracker type",
        default="linear",
        type=click.Choice(it_names, case_sensitive=False),
    )
    config["issue_tracker_type"] = issue_tracker_type

    config["issue_tracker_settings"] = {}
    if fix_enabled:
        # branch_prefix only matters when fixbot pushes branches / opens PRs.
        click.echo("\n--- Git Settings ---")
        config["issue_tracker_settings"]["branch_prefix"] = click.prompt(
            "Branch prefix", default="fixbot"
        )

    click.echo("\n--- Issue Tracker Settings ---")
    if issue_tracker_type == "linear":
        config["issue_tracker_settings"]["team"] = click.prompt("Team name", default="Engineering")
        config["issue_tracker_settings"]["project"] = click.prompt("Project name", default="fixbot")
        config["issue_tracker_settings"]["ticket_prefix"] = click.prompt(
            "Ticket prefix", default="ENG"
        )
    elif issue_tracker_type == "github":
        config["issue_tracker_settings"]["error_label"] = click.prompt("Error label", default="bug")
        config["issue_tracker_settings"]["warn_label"] = click.prompt(
            "Warning label", default="warning"
        )
    elif issue_tracker_type == "jira":
        config["issue_tracker_settings"]["jira_project_key"] = click.prompt(
            "Jira project key", default="ENG"
        )
        config["issue_tracker_settings"]["jira_issue_type"] = click.prompt(
            "Issue type", default="Bug"
        )
        config["issue_tracker_settings"]["jira_error_priority"] = click.prompt(
            "Priority for errors", default="High"
        )
        config["issue_tracker_settings"]["jira_warn_priority"] = click.prompt(
            "Priority for warnings", default="Medium"
        )

    final = deep_merge(DEFAULT_CONFIG, config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(final, indent=2) + "\n")
    click.echo(f"\nConfig written to {config_path}")
    click.echo("Set required environment variables before running:")
    click.echo("  ANTHROPIC_API_KEY         (Anthropic)")

    obs_provider = OBSERVABILITY_PROVIDERS[observability_type]
    obs_env_vars = _collect_env_vars(obs_provider.get_default())
    if obs_env_vars:
        click.echo(f"  {', '.join(sorted(obs_env_vars))}    ({obs_provider.NAME})")

    it_provider = ISSUE_TRACKER_PROVIDERS[issue_tracker_type]
    it_env_vars = _collect_env_vars(it_provider.get_default())
    if it_env_vars:
        click.echo(f"  {', '.join(sorted(it_env_vars))}    ({it_provider.NAME})")

    if fix_enabled:
        provider = CODE_HOST_PROVIDERS[code_host_type]
        code_host_env_vars = _collect_env_vars(provider.get_default())
        code_host_env_vars -= it_env_vars - obs_env_vars
        if code_host_env_vars:
            click.echo(f"  {', '.join(sorted(code_host_env_vars))}    ({provider.NAME})")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Fetch patterns and check tracker without creating tickets or fixes",
)
@click.option("--verbose", is_flag=True, help="Print agent conversation turns to stderr")
@click.option("--max-fixes", type=int, default=None, help="Override max code fixes per run")
@click.option(
    "--triage-only",
    is_flag=True,
    help="Only fetch patterns and create tickets for this run; never spawn a bug-fixer or open a PR",
)
@handle_fixbot_errors
def run(
    config_path: str | None,
    dry_run: bool,
    verbose: bool,
    max_fixes: int | None,
    triage_only: bool,
):
    """Run the bug fix orchestrator."""
    path = _find_config(config_path)
    config = load_config(path)

    if triage_only:
        config.fix_enabled = False

    mismatches = mcp_server_mismatch_warnings(
        config.observability_type,
        config.issue_tracker_type,
        config.code_host_type,
        config.mcp_servers,
        fix_enabled=config.fix_enabled,
    )
    if mismatches:
        click.echo("Error: MCP server configuration is inconsistent:", err=True)
        for msg in mismatches:
            click.echo(f"  - {msg}", err=True)
        click.echo(
            "\nRefusing to run: the agents would call tools the configured servers do "
            "not provide. Fix the config above and re-run. (Use 'fixbot check-env' to verify.)",
            err=True,
        )
        raise SystemExit(1)

    if max_fixes is not None:
        # --max-fixes only bounds the code-fix stage. In triage-only mode no fixes
        # happen at all, and --dry-run stops before any fix, so the flag is a no-op
        # in both — warn rather than silently ignore it.
        if not config.fix_enabled:
            click.echo(
                "Warning: --max-fixes has no effect with --triage-only "
                "(no fixes are made); ignoring it.",
                err=True,
            )
        elif dry_run:
            click.echo(
                "Warning: --max-fixes has no effect with --dry-run "
                "(no fixes are made); ignoring it.",
                err=True,
            )
        else:
            config.orchestrator.max_code_fixes_per_run = max_fixes

    click.echo(f"Query: {config.orchestrator.effective_log_query}")
    if config.fix_enabled:
        click.echo("Mode: fix (file tickets and open PRs)")
        click.echo(f"Max code fixes: {config.orchestrator.max_code_fixes_per_run}")
    else:
        click.echo("Mode: triage-only (file tickets, no PRs)")

    from fixbot.agents.orchestrator import run_orchestrator

    result = asyncio.run(run_orchestrator(config, dry_run=dry_run, verbose=verbose))

    click.echo(result.summary_text)
    if result.usage:
        input_t = (
            result.usage.get("input_tokens", 0)
            + result.usage.get("cache_creation_input_tokens", 0)
            + result.usage.get("cache_read_input_tokens", 0)
        )
        output_t = result.usage.get("output_tokens", 0)
        if input_t or output_t:
            click.echo(f"Tokens: {_format_tokens(input_t)} in / {_format_tokens(output_t)} out")
    if result.duration_ms is not None:
        click.echo(f"Duration: {result.duration_ms / 1000:.1f}s")
    if result.run_log_path:
        click.echo(f"Run log: {result.run_log_path}")


@cli.group("config")
def config_group():
    """Read or modify fixbot configuration."""


@config_group.command("get")
@click.argument("key")
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@handle_fixbot_errors
def config_get(key: str, config_path: str | None):
    """Read a configuration value by dotted key path."""
    path = _find_config(config_path)
    raw = load_raw_config(path)
    merged = deep_merge(DEFAULT_CONFIG, raw)
    value = get_nested(merged, key)

    if isinstance(value, (dict, list)):
        click.echo(json.dumps(value, indent=2))
    else:
        click.echo(value)


@cli.group("repo")
def repo_group():
    """Manage tracked repositories."""


@repo_group.command("add")
@click.argument("repo")
@click.option("--name", default=None, help="Override the auto-derived repository name")
@click.option(
    "--read-only", is_flag=True, help="Add as a read-only repository (can be read but not modified)"
)
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@handle_fixbot_errors
def repo_add(repo: str, name: str | None, read_only: bool, config_path: str | None):
    """Add a repository to the fixbot configuration.

    REPO is the org/repo identifier (e.g., myorg/my-api) or a local path for read-only repos.
    """
    config_file = _find_config(config_path)
    raw = load_raw_config(config_file)

    if read_only:
        ro_repos = raw.get("read_only_repos", [])
        if repo in ro_repos:
            click.echo(f"Warning: '{repo}' is already in read_only_repos", err=True)
            return
        ro_repos.append(repo)
        raw["read_only_repos"] = ro_repos
        save_raw_config(config_file, raw)
        click.echo(f"Added read-only repo: {repo}")
        return

    repos = raw.get("repositories", {})

    if name is None:
        name = _repo_name_from_code_host(repo)
        if name in repos:
            suffix = 2
            while f"{name}-{suffix}" in repos:
                suffix += 1
            name = f"{name}-{suffix}"

    existing_code_hosts = {r.get("code_host_repo"): rname for rname, r in repos.items()}
    if repo in existing_code_hosts:
        click.echo(
            f"Warning: '{existing_code_hosts[repo]}' already points to {repo}",
            err=True,
        )

    repos[name] = {"code_host_repo": repo}
    raw["repositories"] = repos
    save_raw_config(config_file, raw)
    click.echo(f"Added '{name}' -> {repo}")


@repo_group.command("list")
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@handle_fixbot_errors
def repo_list(config_path: str | None):
    """List configured repositories."""
    config_file = _find_config(config_path)
    raw = load_raw_config(config_file)

    repos = raw.get("repositories", {})
    ro_repos = raw.get("read_only_repos", [])

    if not repos and not ro_repos:
        click.echo("No repositories configured.")
        return

    if repos:
        for name, repo in repos.items():
            click.echo(f"  {name} -> {repo.get('code_host_repo', '?')}")

    if ro_repos:
        click.echo("Read-only:")
        for repo in ro_repos:
            click.echo(f"  {repo}")


@repo_group.command("remove")
@click.argument("name")
@click.option("--read-only", is_flag=True, help="Remove from read-only repositories")
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@handle_fixbot_errors
def repo_remove(name: str, read_only: bool, config_path: str | None):
    """Remove a repository from the fixbot configuration."""
    config_file = _find_config(config_path)
    raw = load_raw_config(config_file)

    if read_only:
        ro_repos = raw.get("read_only_repos", [])
        if name not in ro_repos:
            click.echo(f"Error: '{name}' not found in read_only_repos", err=True)
            raise SystemExit(1)
        ro_repos.remove(name)
        raw["read_only_repos"] = ro_repos
        save_raw_config(config_file, raw)
        click.echo(f"Removed read-only repo: {name}")
        return

    repos = raw.get("repositories", {})
    if name not in repos:
        click.echo(f"Error: repository '{name}' not found", err=True)
        raise SystemExit(1)

    del repos[name]
    raw["repositories"] = repos
    save_raw_config(config_file, raw)
    click.echo(f"Removed '{name}'")


def _print_run_log(log: dict) -> None:
    click.echo(f"{log.get('started_at', 'unknown')}")
    click.echo(f"Duration: {log.get('duration_ms', 0) / 1000:.1f}s")

    summary = log.get("summary", {})
    click.echo(f"Patterns found: {sum(summary.values())}")
    for action, count in summary.items():
        click.echo(f"  {action}: {count}")

    cost = log.get("cost", {})
    if cost:
        click.echo(f"Cost: ${cost.get('total_usd', 0):.2f}")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
@click.option("--last", "last_n", type=int, default=1, help="Number of recent runs to show")
@handle_fixbot_errors
def status(config_path: str | None, last_n: int):
    """Show recent run summaries."""
    path = _find_config(config_path)
    config = load_config(path, resolve_env=False)

    from fixbot.run_log import get_recent_run_logs

    logs = get_recent_run_logs(config.run_log_dir, n=last_n)
    if not logs:
        click.echo("No run logs found.")
        raise SystemExit(0)

    for i, log in enumerate(logs):
        if i > 0:
            click.echo("---")
        _print_run_log(log)


@cli.command("check-env")
@click.option("--config", "config_path", default=None, help="Path to fixbot.json")
def check_env(config_path: str | None):
    """Check that required environment variables are set."""
    path = _find_config(config_path)

    try:
        raw = load_raw_config(path)
    except FixbotError:
        raw = {}

    from fixbot.defaults import (
        MCP_ROLE_DEFAULTS,
        get_code_host_provider,
        get_issue_tracker_provider,
        get_observability_provider,
    )

    merged = deep_merge(DEFAULT_CONFIG, raw)
    fix_enabled = bool(merged.get("fix_enabled", True))

    observability_type = raw.get("observability_type", "datadog")
    obs_provider = get_observability_provider(observability_type)

    code_host_type = raw.get("code_host_type", "github")

    issue_tracker_type = raw.get("issue_tracker_type", "linear")
    issue_tracker_provider = get_issue_tracker_provider(issue_tracker_type)

    mcp_defaults = {}
    for role, role_def in MCP_ROLE_DEFAULTS.items():
        # In triage-only mode the code host is never launched (see
        # _build_mcp_servers), so it requires no credentials.
        if role == "code_host":
            if fix_enabled:
                mcp_defaults[role] = get_code_host_provider(code_host_type).get_default()
        elif role == "issue_tracker":
            mcp_defaults[role] = issue_tracker_provider.get_default()
        elif role == "observability":
            mcp_defaults[role] = obs_provider.get_default()
        else:
            mcp_defaults[role] = role_def["factory"]()

    user_mcp = merged.get("mcp_servers", {})

    # Mirror _build_mcp_servers: a role override fully REPLACES the provider
    # default (not a deep merge), so check-env reports the same env vars the
    # run path will actually use.
    mcp = {}
    for role in MCP_ROLE_DEFAULTS:
        if role == "code_host" and not fix_enabled:
            continue
        if role in user_mcp and user_mcp[role]:
            mcp[role] = user_mcp[role]
        else:
            mcp[role] = mcp_defaults[role]
    for key, server_config in user_mcp.items():
        if key not in MCP_ROLE_DEFAULTS:
            mcp[key] = server_config
    merged["mcp_servers"] = mcp

    for mismatch in mcp_server_mismatch_warnings(
        observability_type, issue_tracker_type, code_host_type, user_mcp, fix_enabled=fix_enabled
    ):
        click.echo(f"Warning: {mismatch}", err=True)

    env_vars = _collect_env_vars(merged)
    env_vars.add("ANTHROPIC_API_KEY")

    all_set = True
    for var in sorted(env_vars):
        if os.environ.get(var):
            click.echo(f"  {var}: set")
        else:
            click.echo(f"  {var}: MISSING")
            all_set = False

    if not all_set:
        raise SystemExit(1)
