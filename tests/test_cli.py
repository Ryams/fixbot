import json

from click.testing import CliRunner

from fixbot import __version__
from fixbot.cli import _repo_name_from_code_host, cli
from fixbot.config import load_config


class TestInitNonInteractive:
    def _load(self, tmp_path):
        return json.loads((tmp_path / "fixbot.json").read_text())

    def test_fix_mode_basic(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "-y",
                "--dir",
                str(tmp_path),
                "--observability-type",
                "datadog",
                "--issue-tracker-type",
                "linear",
                "--repo",
                "myorg/api",
                "--repo",
                "myorg/worker",
            ],
        )
        assert result.exit_code == 0, result.output
        cfg = self._load(tmp_path)
        assert cfg["fix_enabled"] is True
        assert cfg["code_host_type"] == "github"
        assert cfg["observability_type"] == "datadog"
        assert cfg["repositories"] == {
            "api": {"code_host_repo": "myorg/api"},
            "worker": {"code_host_repo": "myorg/worker"},
        }
        # Must be a valid config that load_config accepts.
        loaded = load_config(tmp_path / "fixbot.json", resolve_env=False)
        assert loaded.issue_tracker_type == "linear"

    def test_repo_name_dedup(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init", "-y", "--dir", str(tmp_path), "--repo", "myorg/api", "--repo", "other/api"],
        )
        assert result.exit_code == 0, result.output
        repos = self._load(tmp_path)["repositories"]
        assert repos == {
            "api": {"code_host_repo": "myorg/api"},
            "api-2": {"code_host_repo": "other/api"},
        }

    def test_set_coercion_and_branch_prefix(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "-y",
                "--dir",
                str(tmp_path),
                "--repo",
                "myorg/api",
                "--branch-prefix",
                "hotfix",
                "--set",
                "team=Payments",
                "--set",
                "error_priority=1",
            ],
        )
        assert result.exit_code == 0, result.output
        its = self._load(tmp_path)["issue_tracker_settings"]
        assert its["team"] == "Payments"
        assert its["error_priority"] == 1  # coerced to int
        assert its["branch_prefix"] == "hotfix"

    def test_triage_mode_with_services(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "-y",
                "--dir",
                str(tmp_path),
                "--triage-only",
                "--issue-tracker-type",
                "github",
                "--service",
                "api",
                "--service",
                "worker",
            ],
        )
        assert result.exit_code == 0, result.output
        cfg = self._load(tmp_path)
        assert cfg["fix_enabled"] is False
        assert cfg["repositories"] == {"api": {}, "worker": {}}

    def test_unknown_tracker_type_errors(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["init", "-y", "--dir", str(tmp_path), "--issue-tracker-type", "bogus"]
        )
        assert result.exit_code == 2
        assert "Unknown issue tracker type 'bogus'" in result.output
        assert not (tmp_path / "fixbot.json").exists()

    def test_config_flags_require_non_interactive(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--dir", str(tmp_path), "--repo", "myorg/api"])
        assert result.exit_code == 2
        assert "require --non-interactive" in result.output

    def test_service_rejected_in_fix_mode(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-y", "--dir", str(tmp_path), "--service", "api"])
        assert result.exit_code == 2
        assert "--service is only valid with --triage-only" in result.output

    def test_repo_allowed_in_triage_mode(self, tmp_path):
        # In triage-only, --repo is recorded (unused) alongside --service scopes.
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "init",
                "-y",
                "--dir",
                str(tmp_path),
                "--triage-only",
                "--repo",
                "myorg/api",
                "--service",
                "worker",
            ],
        )
        assert result.exit_code == 0, result.output
        cfg = self._load(tmp_path)
        assert cfg["fix_enabled"] is False
        assert cfg["repositories"] == {
            "api": {"code_host_repo": "myorg/api"},
            "worker": {},
        }
        # Triage config with a code_host_repo entry must still load fine.
        loaded = load_config(tmp_path / "fixbot.json", resolve_env=False)
        assert set(loaded.repositories) == {"api", "worker"}

    def test_bad_set_syntax_errors(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-y", "--dir", str(tmp_path), "--set", "teamPayments"])
        assert result.exit_code == 2
        assert "--set expects KEY=VALUE" in result.output

    def test_non_interactive_overwrites_existing(self, tmp_path):
        (tmp_path / "fixbot.json").write_text('{"version": 1}\n')
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "-y", "--dir", str(tmp_path), "--repo", "myorg/api"])
        assert result.exit_code == 0, result.output
        assert self._load(tmp_path)["repositories"] == {"api": {"code_host_repo": "myorg/api"}}
        # An overwrite notice is surfaced on stderr.
        assert "Overwriting existing" in result.output


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "run" in result.output
        assert "config" in result.output
        assert "status" in result.output

    def test_invalid_command_suggests_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["badcommand"])
        assert result.exit_code == 2
        assert "No such command" in result.output
        assert "fixbot --help" in result.output

    def test_run_missing_config(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["run"])
            assert result.exit_code == 1
            assert "not found" in result.output

    def test_run_short_circuits_on_server_mismatch(self, tmp_path, monkeypatch):
        # observability_type=datadog but the server is overridden to Grafana.
        # run must refuse before invoking any agents.
        config = {
            "version": 1,
            "observability_type": "datadog",
            "repositories": {"svc": {"code_host_repo": "org/repo"}},
            "mcp_servers": {
                "observability": {
                    "type": "stdio",
                    "command": "mcp-grafana",
                    "args": ["stdio"],
                    "env": {
                        "GRAFANA_URL": "${GRAFANA_URL}",
                        "GRAFANA_API_KEY": "${GRAFANA_API_KEY}",
                    },
                }
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.setenv("GRAFANA_API_KEY", "grafana-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "inconsistent" in result.output
        assert "observability_type is 'datadog'" in result.output
        assert "Refusing to run" in result.output

    def test_run_triage_only_flag(self, tmp_path, monkeypatch):
        # --triage-only must run without a code host configured or GITHUB_TOKEN set.
        config = {"version": 1, "fix_enabled": False, "issue_tracker_type": "linear"}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        captured = {}

        async def fake_run(config, dry_run=False, verbose=False):
            captured["fix_enabled"] = config.fix_enabled
            from fixbot.agents.orchestrator import RunResult

            return RunResult(summary_text="ok")

        monkeypatch.setattr("fixbot.agents.orchestrator.run_orchestrator", fake_run)

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--triage-only", "--config", str(config_path)])
        assert result.exit_code == 0, result.output
        assert "Mode: triage-only" in result.output
        assert captured["fix_enabled"] is False

    def _stub_run_orchestrator(self, monkeypatch, captured):
        async def fake_run(config, dry_run=False, verbose=False):
            captured["fix_enabled"] = config.fix_enabled
            captured["max_code_fixes_per_run"] = config.orchestrator.max_code_fixes_per_run
            captured["dry_run"] = dry_run
            from fixbot.agents.orchestrator import RunResult

            return RunResult(summary_text="ok")

        monkeypatch.setattr("fixbot.agents.orchestrator.run_orchestrator", fake_run)

    def _base_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

    def test_max_fixes_ignored_with_triage_only(self, tmp_path, monkeypatch):
        config = {"version": 1, "repositories": {"svc": {"code_host_repo": "org/repo"}}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        self._base_env(monkeypatch)
        captured: dict = {}
        self._stub_run_orchestrator(monkeypatch, captured)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--triage-only", "--max-fixes", "7", "--config", str(config_path)]
        )
        assert result.exit_code == 0, result.output
        assert "--max-fixes has no effect with --triage-only" in result.output
        # The override is not applied (default of 3 is left intact).
        assert captured["max_code_fixes_per_run"] == 3

    def test_max_fixes_ignored_with_dry_run(self, tmp_path, monkeypatch):
        config = {"version": 1, "repositories": {"svc": {"code_host_repo": "org/repo"}}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        self._base_env(monkeypatch)
        captured: dict = {}
        self._stub_run_orchestrator(monkeypatch, captured)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["run", "--dry-run", "--max-fixes", "7", "--config", str(config_path)]
        )
        assert result.exit_code == 0, result.output
        assert "--max-fixes has no effect with --dry-run" in result.output
        assert captured["max_code_fixes_per_run"] == 3

    def test_max_fixes_applied_in_normal_run(self, tmp_path, monkeypatch):
        config = {"version": 1, "repositories": {"svc": {"code_host_repo": "org/repo"}}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        self._base_env(monkeypatch)
        captured: dict = {}
        self._stub_run_orchestrator(monkeypatch, captured)

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--max-fixes", "7", "--config", str(config_path)])
        assert result.exit_code == 0, result.output
        assert "no effect" not in result.output
        assert captured["max_code_fixes_per_run"] == 7

    def test_config_get(self, tmp_path):
        config = {
            "version": 1,
            "orchestrator": {"model": "claude-sonnet-4-6"},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(
            cli, ["config", "get", "orchestrator.model", "--config", str(config_path)]
        )
        assert result.exit_code == 0
        assert "claude-sonnet-4-6" in result.output

    def test_status_no_logs(self, tmp_path):
        config = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "org/repo",
                }
            },
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "No run logs found" in result.output

    def test_status_shows_single_run(self, tmp_path):
        log_dir = tmp_path / "logs" / "2026-06-18"
        log_dir.mkdir(parents=True)
        run_log = {
            "started_at": "2026-06-18T10:00:00Z",
            "duration_ms": 45000,
            "summary": {"fix_submitted": 2, "skipped": 1},
            "cost": {"total_usd": 1.50},
        }
        (log_dir / "fixbot-run-100000Z.json").write_text(json.dumps(run_log))

        config = {
            "version": 1,
            "repositories": {"svc": {"code_host_repo": "org/repo"}},
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "2026-06-18T10:00:00Z" in result.output
        assert "45.0s" in result.output
        assert "fix_submitted: 2" in result.output
        assert "$1.50" in result.output

    def test_status_last_n(self, tmp_path):
        log_dir = tmp_path / "logs" / "2026-06-18"
        log_dir.mkdir(parents=True)
        for i, ts in enumerate(["100000Z", "110000Z", "120000Z"]):
            run_log = {
                "started_at": f"2026-06-18T{10 + i}:00:00Z",
                "duration_ms": 10000 * (i + 1),
                "summary": {"fix_submitted": i + 1},
                "cost": {},
            }
            (log_dir / f"fixbot-run-{ts}.json").write_text(json.dumps(run_log))

        config = {
            "version": 1,
            "repositories": {"svc": {"code_host_repo": "org/repo"}},
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--last", "2", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "2026-06-18T12:00:00Z" in result.output
        assert "2026-06-18T11:00:00Z" in result.output
        assert "---" in result.output
        assert "2026-06-18T10:00:00Z" not in result.output


class TestCheckEnv:
    def test_all_set(self, tmp_path, monkeypatch):
        config = {"version": 1, "repositories": {}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output

    def test_missing_var(self, tmp_path, monkeypatch):
        config = {"version": 1, "repositories": {}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "ANTHROPIC_API_KEY: MISSING" in result.output

    def test_includes_custom_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "repositories": {},
            "worktree_dir": "${RUNNER_TEMP}/.worktrees",
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.delenv("RUNNER_TEMP", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "RUNNER_TEMP: MISSING" in result.output

    def test_gitlab_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITLAB_TOKEN", "gl-test")
        monkeypatch.setenv("GITLAB_PERSONAL_ACCESS_TOKEN", "gl-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output

    def test_gitlab_missing_token(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITLAB_PERSONAL_ACCESS_TOKEN", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "GITLAB" in result.output
        assert "MISSING" in result.output

    def test_bitbucket_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("BITBUCKET_TOKEN", "bb-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output

    def test_github_issues_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output
        assert "LINEAR_API_KEY" not in result.output

    def test_jira_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
        monkeypatch.setenv("JIRA_MCP_URL", "https://jira-mcp.example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "jira-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output
        assert "LINEAR_API_KEY" not in result.output

    def test_jira_missing_token(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
        monkeypatch.setenv("JIRA_MCP_URL", "https://jira-mcp.example.com")
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "JIRA_API_TOKEN: MISSING" in result.output

    def test_github_issues_missing_token(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "GITHUB_TOKEN: MISSING" in result.output

    def test_grafana_env_vars(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.setenv("GRAFANA_API_KEY", "grafana-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "MISSING" not in result.output

    def test_grafana_missing_token(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "GRAFANA_API_KEY: MISSING" in result.output

    def test_grafana_no_datadog_vars_needed(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.setenv("GRAFANA_API_KEY", "grafana-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
        monkeypatch.delenv("DD_API_KEY", raising=False)
        monkeypatch.delenv("DD_APP_KEY", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "DD_API_KEY" not in result.output

    def test_observability_override_replaces_default_env_vars(self, tmp_path, monkeypatch):
        # observability_type is datadog (default) but the server is overridden to
        # Grafana. check-env must report only the override's env vars (matching the
        # run path's straight replacement) — NOT the datadog defaults.
        config = {
            "version": 1,
            "repositories": {},
            "mcp_servers": {
                "observability": {
                    "type": "stdio",
                    "command": "mcp-grafana",
                    "args": ["stdio"],
                    "env": {
                        "GRAFANA_URL": "${GRAFANA_URL}",
                        "GRAFANA_API_KEY": "${GRAFANA_API_KEY}",
                    },
                }
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.setenv("GRAFANA_API_KEY", "grafana-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")
        monkeypatch.delenv("DD_API_KEY", raising=False)
        monkeypatch.delenv("DD_APP_KEY", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert "DD_API_KEY" not in result.output
        assert "DD_APP_KEY" not in result.output
        assert "GRAFANA_URL: set" in result.output

    def test_observability_override_mismatch_warns(self, tmp_path, monkeypatch):
        config = {
            "version": 1,
            "observability_type": "datadog",
            "repositories": {},
            "mcp_servers": {
                "observability": {
                    "type": "stdio",
                    "command": "mcp-grafana",
                    "args": ["stdio"],
                    "env": {
                        "GRAFANA_URL": "${GRAFANA_URL}",
                        "GRAFANA_API_KEY": "${GRAFANA_API_KEY}",
                    },
                }
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
        monkeypatch.setenv("GRAFANA_API_KEY", "grafana-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert "Warning:" in result.output
        assert "observability_type is 'datadog'" in result.output

    def test_issue_tracker_override_mismatch_warns(self, tmp_path, monkeypatch):
        # issue_tracker_type=linear but the server is overridden to Jira.
        config = {
            "version": 1,
            "issue_tracker_type": "linear",
            "repositories": {},
            "mcp_servers": {
                "issue_tracker": {
                    "type": "http",
                    "url": "${JIRA_MCP_URL}",
                    "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"},
                }
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("JIRA_MCP_URL", "https://jira-mcp.example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "jira-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert "Warning:" in result.output
        assert "issue_tracker_type is 'linear'" in result.output
        assert "jira" in result.output

    def test_triage_mode_no_github_token_needed(self, tmp_path, monkeypatch):
        config = {"version": 1, "fix_enabled": False}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        runner = CliRunner()
        result = runner.invoke(cli, ["check-env", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "GITHUB_TOKEN" not in result.output
        assert "MISSING" not in result.output

    def test_no_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("DD_API_KEY", "dd-test")
        monkeypatch.setenv("DD_APP_KEY", "dd-app-test")
        monkeypatch.setenv("LINEAR_API_KEY", "lin-test")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test")

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["check-env"])
            assert result.exit_code == 0


class TestRepoNameFromCodeHost:
    def test_simple(self):
        assert _repo_name_from_code_host("myorg/my-api") == "my-api"

    def test_nested_group(self):
        assert _repo_name_from_code_host("myorg/subgroup/my-api") == "my-api"

    def test_no_slash(self):
        assert _repo_name_from_code_host("my-api") == "my-api"


class TestRepoCommands:
    def _make_config(self, tmp_path, repos=None):
        config = {"version": 1, "repositories": repos or {}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))
        return config_path

    def test_repo_list_empty(self, tmp_path):
        config_path = self._make_config(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "list", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "No repositories configured" in result.output

    def test_repo_list_shows_repos(self, tmp_path):
        config_path = self._make_config(
            tmp_path,
            {
                "my-api": {"code_host_repo": "org/my-api"},
            },
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "list", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "my-api" in result.output
        assert "org/my-api" in result.output

    def test_repo_add(self, tmp_path):
        config_path = self._make_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "add", "org/my-repo", "--config", str(config_path)],
        )
        assert result.exit_code == 0
        assert "Added" in result.output

        updated = json.loads(config_path.read_text())
        assert "my-repo" in updated["repositories"]
        assert updated["repositories"]["my-repo"]["code_host_repo"] == "org/my-repo"

    def test_repo_add_with_name_override(self, tmp_path):
        config_path = self._make_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "add", "org/my-repo", "--name", "custom-name", "--config", str(config_path)],
        )
        assert result.exit_code == 0
        assert "Added" in result.output

        updated = json.loads(config_path.read_text())
        assert "custom-name" in updated["repositories"]

    def test_repo_add_deduplicates_name(self, tmp_path):
        config_path = self._make_config(
            tmp_path,
            {
                "my-repo": {"code_host_repo": "org/my-repo"},
            },
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "add", "other-org/my-repo", "--config", str(config_path)],
        )
        assert result.exit_code == 0

        updated = json.loads(config_path.read_text())
        assert "my-repo-2" in updated["repositories"]

    def test_repo_remove(self, tmp_path):
        config_path = self._make_config(
            tmp_path,
            {
                "my-api": {"code_host_repo": "org/my-api"},
            },
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "remove", "my-api", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "Removed" in result.output

        updated = json.loads(config_path.read_text())
        assert "my-api" not in updated["repositories"]

    def test_repo_remove_nonexistent(self, tmp_path):
        config_path = self._make_config(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "remove", "nope", "--config", str(config_path)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_repo_add_read_only(self, tmp_path):
        config_path = self._make_config(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "add", "/shared/utils", "--read-only", "--config", str(config_path)],
        )
        assert result.exit_code == 0
        assert "read-only" in result.output

        updated = json.loads(config_path.read_text())
        assert "/shared/utils" in updated["read_only_repos"]

    def test_repo_add_read_only_duplicate_warns(self, tmp_path):
        config = {"version": 1, "repositories": {}, "read_only_repos": ["/shared/utils"]}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "add", "/shared/utils", "--read-only", "--config", str(config_path)],
        )
        assert "already" in result.output

        updated = json.loads(config_path.read_text())
        assert updated["read_only_repos"].count("/shared/utils") == 1

    def test_repo_list_shows_read_only(self, tmp_path):
        config = {
            "version": 1,
            "repositories": {"my-api": {"code_host_repo": "org/my-api"}},
            "read_only_repos": ["/shared/utils"],
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "list", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "my-api" in result.output
        assert "Read-only:" in result.output
        assert "/shared/utils" in result.output

    def test_repo_list_only_read_only(self, tmp_path):
        config = {"version": 1, "repositories": {}, "read_only_repos": ["/libs/common"]}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(cli, ["repo", "list", "--config", str(config_path)])
        assert result.exit_code == 0
        assert "Read-only:" in result.output
        assert "/libs/common" in result.output

    def test_repo_remove_read_only(self, tmp_path):
        config = {
            "version": 1,
            "repositories": {},
            "read_only_repos": ["/shared/utils", "/libs/common"],
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "remove", "/shared/utils", "--read-only", "--config", str(config_path)],
        )
        assert result.exit_code == 0
        assert "Removed read-only" in result.output

        updated = json.loads(config_path.read_text())
        assert "/shared/utils" not in updated["read_only_repos"]
        assert "/libs/common" in updated["read_only_repos"]

    def test_repo_remove_read_only_nonexistent(self, tmp_path):
        config_path = self._make_config(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["repo", "remove", "/nope", "--read-only", "--config", str(config_path)],
        )
        assert result.exit_code == 1
        assert "not found" in result.output
