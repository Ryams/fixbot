import json

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Create a minimal valid fixbot config in a temp directory."""
    config = {
        "version": 1,
        "repositories": {
            "test-service": {
                "code_host_repo": "org/test-repo",
            }
        },
        "log_routing": [
            {"key": "service", "value": "test-svc", "repo": "test-service"},
        ],
        "worktree_dir": str(tmp_path / ".worktrees"),
        "run_log_dir": str(tmp_path / "logs"),
    }
    config_path = tmp_path / "fixbot.json"
    config_path.write_text(json.dumps(config))

    return config_path


@pytest.fixture
def env_vars(monkeypatch):
    """Set common env vars used in MCP server configs."""
    monkeypatch.setenv("DD_API_KEY", "test-dd-api-key")
    monkeypatch.setenv("DD_APP_KEY", "test-dd-app-key")
    monkeypatch.setenv("LINEAR_API_KEY", "test-linear-api-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")


@pytest.fixture
def gitlab_env_vars(monkeypatch):
    """Set common env vars used in GitLab MCP server configs."""
    monkeypatch.setenv("DD_API_KEY", "test-dd-api-key")
    monkeypatch.setenv("DD_APP_KEY", "test-dd-app-key")
    monkeypatch.setenv("LINEAR_API_KEY", "test-linear-api-key")
    monkeypatch.setenv("GITLAB_TOKEN", "test-gl-token")


@pytest.fixture
def bitbucket_env_vars(monkeypatch):
    """Set common env vars used in Bitbucket MCP server configs."""
    monkeypatch.setenv("DD_API_KEY", "test-dd-api-key")
    monkeypatch.setenv("DD_APP_KEY", "test-dd-app-key")
    monkeypatch.setenv("LINEAR_API_KEY", "test-linear-api-key")
    monkeypatch.setenv("BITBUCKET_TOKEN", "test-bb-token")


@pytest.fixture
def github_issues_env_vars(monkeypatch):
    """Set common env vars for GitHub Issues as issue tracker."""
    monkeypatch.setenv("DD_API_KEY", "test-dd-api-key")
    monkeypatch.setenv("DD_APP_KEY", "test-dd-app-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")


@pytest.fixture
def jira_env_vars(monkeypatch):
    """Set common env vars for Jira as issue tracker."""
    monkeypatch.setenv("DD_API_KEY", "test-dd-api-key")
    monkeypatch.setenv("DD_APP_KEY", "test-dd-app-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")
    monkeypatch.setenv("JIRA_MCP_URL", "https://jira-mcp.example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-jira-token")


@pytest.fixture
def grafana_env_vars(monkeypatch):
    """Set common env vars for Grafana as observability platform."""
    monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
    monkeypatch.setenv("GRAFANA_API_KEY", "test-grafana-key")
    monkeypatch.setenv("LINEAR_API_KEY", "test-linear-api-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")
