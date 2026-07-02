import json

import pytest

from fixbot.config import (
    FixbotConfig,
    deep_merge,
    get_nested,
    load_config,
    mcp_server_mismatch_warnings,
    resolve_env_vars,
)
from fixbot.exceptions import ConfigEnvVarError, ConfigError, ConfigMissingKeyError


class TestDeepMerge:
    def test_flat_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_override_dict_with_scalar(self):
        base = {"a": {"x": 1}}
        override = {"a": "replaced"}
        assert deep_merge(base, override) == {"a": "replaced"}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"b": 2}
        deep_merge(base, override)
        assert base == {"a": 1}


class TestResolveEnvVars:
    def test_resolves_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        assert resolve_env_vars("${MY_KEY}") == "secret123"

    def test_resolves_in_nested_dict(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "abc")
        data = {"server": {"env": {"key": "${API_KEY}"}}}
        result = resolve_env_vars(data)
        assert result["server"]["env"]["key"] == "abc"

    def test_resolves_in_list(self, monkeypatch):
        monkeypatch.setenv("VAL", "x")
        assert resolve_env_vars(["${VAL}", "literal"]) == ["x", "literal"]

    def test_raises_on_missing_env_var(self):
        with pytest.raises(ConfigEnvVarError, match="MY_MISSING_VAR"):
            resolve_env_vars({"key": "${MY_MISSING_VAR}"})

    def test_leaves_non_strings_unchanged(self):
        assert resolve_env_vars(42) == 42
        assert resolve_env_vars(None) is None
        assert resolve_env_vars(True) is True

    def test_partial_interpolation(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        assert resolve_env_vars("http://${HOST}:8080") == "http://localhost:8080"


class TestGetNested:
    def test_get_top_level(self):
        assert get_nested({"a": 1}, "a") == 1

    def test_get_deep(self):
        data = {"a": {"b": {"c": 42}}}
        assert get_nested(data, "a.b.c") == 42

    def test_get_missing_raises(self):
        with pytest.raises(ConfigMissingKeyError):
            get_nested({"a": 1}, "b")


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert isinstance(config, FixbotConfig)
        assert "test-service" in config.repositories
        assert len(config.log_routing) == 1
        assert config.log_routing[0].key == "service"
        assert config.log_routing[0].value == "test-svc"
        assert config.log_routing[0].repo == "test-service"

    def test_merges_with_defaults(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.orchestrator.model == "claude-sonnet-4-6"
        assert config.orchestrator.max_turns == 100
        assert config.bug_fixer.max_budget_usd == 3.0

    def test_missing_file_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config("/nonexistent/path/fixbot.json")

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "fixbot.json"
        bad.write_text("not json {{{")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(bad)

    def test_no_repositories_raises(self, tmp_path):
        config = tmp_path / "fixbot.json"
        config.write_text(json.dumps({"version": 1}))
        with pytest.raises(ConfigMissingKeyError, match="repositories"):
            load_config(config)

    def test_user_overrides_agent_config(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "org/repo",
                }
            },
            "orchestrator": {"model": "claude-opus-4-20250514", "max_turns": 50},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))

        config = load_config(config_path)
        assert config.orchestrator.model == "claude-opus-4-20250514"
        assert config.orchestrator.max_turns == 50
        assert config.orchestrator.max_code_fixes_per_run == 3  # kept from default

    def test_skip_env_resolution(self, tmp_config):
        config = load_config(tmp_config, resolve_env=False)
        assert isinstance(config, FixbotConfig)

    def test_invalid_log_routing_repo_raises(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "org/repo",
                }
            },
            "log_routing": [
                {"key": "service", "value": "my-tag", "repo": "nonexistent-repo"},
            ],
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        with pytest.raises(ConfigError, match="not a known repository"):
            load_config(config_path)

    def test_filter_instructions_loaded(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "org/repo",
                }
            },
            "orchestrator": {
                "filter_instructions": "Ignore DeprecationWarning patterns.",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.orchestrator.filter_instructions == "Ignore DeprecationWarning patterns."

    def test_filter_instructions_default_none(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.orchestrator.filter_instructions is None

    def test_code_host_type_defaults_to_github(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.code_host_type == "github"

    def test_code_host_type_gitlab(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path, resolve_env=False)
        assert config.code_host_type == "gitlab"

    def test_code_host_type_bitbucket(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {
                "svc": {"code_host_repo": "workspace/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path, resolve_env=False)
        assert config.code_host_type == "bitbucket"

    def test_invalid_code_host_type_raises(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "sourcehut",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        with pytest.raises(ConfigError, match="sourcehut"):
            load_config(config_path, resolve_env=False)

    def test_issue_tracker_type_defaults_to_linear(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.issue_tracker_type == "linear"

    def test_issue_tracker_type_github(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path, resolve_env=False)
        assert config.issue_tracker_type == "github"

    def test_issue_tracker_type_jira(self, tmp_path, jira_env_vars):
        config_data = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.issue_tracker_type == "jira"

    def test_invalid_issue_tracker_type_raises(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "issue_tracker_type": "asana",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        with pytest.raises(ConfigError, match="asana"):
            load_config(config_path, resolve_env=False)

    def test_observability_type_defaults_to_datadog(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.observability_type == "datadog"

    def test_observability_type_grafana(self, tmp_path, grafana_env_vars):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.observability_type == "grafana"

    def test_grafana_default_log_query(self, tmp_path, grafana_env_vars):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.orchestrator.log_query == '{level=~"error|warn"}'

    def test_datadog_default_log_query(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.orchestrator.log_query == "status:(error OR warn) env:production"

    def test_custom_log_query_preserved_with_grafana(self, tmp_path, grafana_env_vars):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
            "orchestrator": {
                "log_query": '{app="my-app", level="error"}',
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.orchestrator.log_query == '{app="my-app", level="error"}'

    def test_invalid_observability_type_raises(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "observability_type": "splunk",
            "repositories": {
                "svc": {"code_host_repo": "org/repo"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        with pytest.raises(ConfigError, match="splunk"):
            load_config(config_path, resolve_env=False)

    def test_fix_enabled_defaults_true(self, tmp_config, env_vars):
        config = load_config(tmp_config)
        assert config.fix_enabled is True

    def test_triage_allows_no_repositories(self, tmp_path, env_vars):
        config_data = {"version": 1, "fix_enabled": False}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.fix_enabled is False
        assert config.repositories == {}

    def test_triage_allows_repo_without_code_host_repo(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "fix_enabled": False,
            "repositories": {"my-api": {}},
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert "my-api" in config.repositories
        assert config.repositories["my-api"].code_host_repo == ""

    def test_fix_mode_still_requires_code_host_repo(self, tmp_path, env_vars):
        config_data = {"version": 1, "repositories": {"my-api": {}}}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        with pytest.raises(ConfigMissingKeyError, match="code_host_repo"):
            load_config(config_path)

    def test_triage_allows_unset_code_host_type(self, tmp_path, env_vars):
        config_data = {"version": 1, "fix_enabled": False, "code_host_type": "sourcehut"}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        # No raise: code_host_type is ignored entirely in triage mode.
        config = load_config(config_path, resolve_env=False)
        assert config.fix_enabled is False

    def test_env_var_in_worktree_dir(self, tmp_path, monkeypatch, env_vars):
        monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "tmp"))
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "repo_path": str(tmp_path),
                    "code_host_repo": "org/repo",
                }
            },
            "worktree_dir": "${RUNNER_TEMP}/.worktrees",
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path)
        assert config.worktree_dir == str(tmp_path / "tmp" / ".worktrees")


GRAFANA_SERVER = {
    "type": "stdio",
    "command": "mcp-grafana",
    "args": ["stdio"],
    "env": {"GRAFANA_URL": "${GRAFANA_URL}", "GRAFANA_API_KEY": "${GRAFANA_API_KEY}"},
}
DATADOG_SERVER = {
    "type": "http",
    "url": "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp",
    "headers": {"DD_API_KEY": "${DD_API_KEY}", "DD_APPLICATION_KEY": "${DD_APP_KEY}"},
}
GITHUB_SERVER = {
    "type": "http",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"},
}
GITLAB_SERVER = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-gitlab"],
    "env": {"GITLAB_PERSONAL_ACCESS_TOKEN": "${GITLAB_TOKEN}"},
}
LINEAR_SERVER = {
    "type": "http",
    "url": "https://mcp.linear.app/mcp",
    "headers": {"Authorization": "Bearer ${LINEAR_API_KEY}"},
}
JIRA_SERVER = {
    "type": "http",
    "url": "${JIRA_MCP_URL}",
    "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"},
}


def _warnings(obs="datadog", it="linear", ch="github", servers=None):
    return mcp_server_mismatch_warnings(obs, it, ch, servers or {})


class TestMcpServerMismatchWarnings:
    def test_no_overrides_no_warnings(self):
        assert _warnings() == []

    def test_all_matching_no_warnings(self):
        servers = {
            "observability": DATADOG_SERVER,
            "issue_tracker": LINEAR_SERVER,
            "code_host": GITHUB_SERVER,
        }
        assert _warnings(servers=servers) == []

    # --- observability role ---
    def test_observability_mismatch(self):
        msgs = _warnings(obs="datadog", servers={"observability": GRAFANA_SERVER})
        assert len(msgs) == 1
        assert "observability_type is 'datadog'" in msgs[0] and "grafana" in msgs[0]

    def test_observability_detected_by_env_keys_only(self):
        # url gives no hint; env keys identify it as Grafana.
        server = {
            "type": "http",
            "url": "https://obs.example.com/mcp",
            "env": {"GRAFANA_API_KEY": "${GRAFANA_API_KEY}"},
        }
        msgs = _warnings(obs="datadog", servers={"observability": server})
        assert len(msgs) == 1 and "grafana" in msgs[0]

    # --- issue_tracker role ---
    def test_issue_tracker_mismatch_linear_vs_jira(self):
        msgs = _warnings(it="linear", servers={"issue_tracker": JIRA_SERVER})
        assert len(msgs) == 1
        assert "issue_tracker_type is 'linear'" in msgs[0] and "jira" in msgs[0]

    def test_issue_tracker_github_matches_github_type(self):
        # GitHub server in the issue_tracker slot under issue_tracker_type=github
        # is correct, not a mismatch (GitHub is dual-role).
        assert _warnings(it="github", servers={"issue_tracker": GITHUB_SERVER}) == []

    def test_issue_tracker_github_override_under_linear_warns(self):
        msgs = _warnings(it="linear", servers={"issue_tracker": GITHUB_SERVER})
        assert len(msgs) == 1 and "github" in msgs[0]

    # --- code_host role ---
    def test_code_host_mismatch_github_vs_gitlab(self):
        msgs = _warnings(ch="github", servers={"code_host": GITLAB_SERVER})
        assert len(msgs) == 1
        assert "code_host_type is 'github'" in msgs[0] and "gitlab" in msgs[0]

    def test_code_host_github_matches_github_type(self):
        assert _warnings(ch="github", servers={"code_host": GITHUB_SERVER}) == []

    # --- general ---
    def test_custom_unrecognized_override_no_warning(self):
        custom = {"type": "http", "url": "https://obs.internal.example.com/mcp"}
        assert _warnings(obs="datadog", servers={"observability": custom}) == []

    def test_code_host_mismatch_ignored_in_triage(self):
        # In triage mode the code host is never launched, so an override that
        # looks like a different provider is not flagged.
        msgs = mcp_server_mismatch_warnings(
            "datadog", "linear", "github", {"code_host": GITLAB_SERVER}, fix_enabled=False
        )
        assert msgs == []

    def test_observability_mismatch_still_flagged_in_triage(self):
        msgs = mcp_server_mismatch_warnings(
            "datadog", "linear", "github", {"observability": GRAFANA_SERVER}, fix_enabled=False
        )
        assert len(msgs) == 1 and "grafana" in msgs[0]

    def test_multiple_mismatches_reported_together(self):
        servers = {
            "observability": GRAFANA_SERVER,
            "code_host": GITLAB_SERVER,
        }
        msgs = _warnings(obs="datadog", ch="github", servers=servers)
        assert len(msgs) == 2
        joined = " ".join(msgs)
        assert "observability_type" in joined and "code_host_type" in joined
