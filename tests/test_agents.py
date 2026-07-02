import json
from pathlib import Path
from unittest.mock import patch

import pytest
from claude_agent_sdk.types import (
    AgentDefinition,
    AssistantMessage,
    ResultMessage,
    TaskNotificationMessage,
    TextBlock,
    ToolUseBlock,
)

from fixbot.agents.bug_fixer import build_definition
from fixbot.agents.orchestrator import (
    RunResult,
    _build_mcp_servers,
    _build_options,
    _parse_fixer_prompt,
    _preflight_check,
    run_orchestrator,
)
from fixbot.config import load_config
from fixbot.exceptions import AgentBudgetExceeded, AgentError, MCPServerError


@pytest.fixture
def sample_config(tmp_path, env_vars):
    config_data = {
        "version": 1,
        "repositories": {
            "my-api": {
                "code_host_repo": "myorg/my-api",
            },
        },
        "log_routing": [
            {"key": "service", "value": "api-service", "repo": "my-api"},
        ],
        "worktree_dir": str(tmp_path / ".worktrees"),
        "orchestrator": {
            "model": "claude-sonnet-4-6",
            "max_turns": 50,
            "max_budget_usd": 2.0,
            "effort": "high",
        },
        "bug_fixer": {
            "model": "claude-sonnet-4-6",
            "max_turns": 100,
            "max_budget_usd": 1.5,
            "effort": "high",
        },
        "issue_tracker_settings": {
            "team": "Platform",
            "project": "Auto Bugs",
            "branch_prefix": "alice",
            "ticket_prefix": "PLAT",
        },
        "run_log_dir": str(tmp_path / "logs"),
    }
    config_path = tmp_path / "fixbot.json"
    config_path.write_text(json.dumps(config_data))
    return load_config(config_path)


class TestBugFixerDefinition:
    def test_returns_agent_definition(self, sample_config):
        defn = build_definition(sample_config)
        assert isinstance(defn, AgentDefinition)

    def test_has_correct_description(self, sample_config):
        defn = build_definition(sample_config)
        assert "production log pattern" in defn.description
        assert "PR" in defn.description

    def test_uses_bug_fixer_model(self, sample_config):
        defn = build_definition(sample_config)
        assert defn.model == "claude-sonnet-4-6"

    def test_uses_bug_fixer_max_turns(self, sample_config):
        defn = build_definition(sample_config)
        assert defn.maxTurns == 100

    def test_has_bypass_permissions(self, sample_config):
        defn = build_definition(sample_config)
        assert defn.permissionMode == "bypassPermissions"

    def test_includes_file_tools(self, sample_config):
        defn = build_definition(sample_config)
        for tool in ("Read", "Write", "Edit", "Grep", "Glob", "Bash"):
            assert tool in defn.tools

    def test_includes_mcp_tools(self, sample_config):
        defn = build_definition(sample_config)
        assert "mcp__observability__*" in defn.tools
        assert "mcp__issue_tracker__*" in defn.tools
        assert "mcp__code_host__*" in defn.tools

    def test_prompt_contains_service_info(self, sample_config):
        defn = build_definition(sample_config)
        assert "my-api" in defn.prompt
        assert "myorg/my-api" in defn.prompt

    def test_effort_propagated(self, sample_config):
        defn = build_definition(sample_config)
        assert defn.effort == "high"

    def test_mcp_servers_passed_through(self, sample_config):
        names = ["observability", "issue_tracker", "code_host"]
        defn = build_definition(sample_config, mcp_server_names=names)
        assert defn.mcpServers == names

    def test_mcp_servers_none_by_default(self, sample_config):
        defn = build_definition(sample_config)
        assert defn.mcpServers is None


class TestBugFixerDefinitionGitLab:
    @pytest.fixture
    def gitlab_config(self, tmp_path, gitlab_env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_description_uses_mr(self, gitlab_config):
        defn = build_definition(gitlab_config)
        assert "MR" in defn.description
        assert "PR" not in defn.description


class TestBugFixerDefinitionBitbucket:
    @pytest.fixture
    def bitbucket_config(self, tmp_path, bitbucket_env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {
                "my-api": {"code_host_repo": "myworkspace/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_description_uses_pr(self, bitbucket_config):
        defn = build_definition(bitbucket_config)
        assert "PR" in defn.description


class TestBuildMCPServersGrafana:
    @pytest.fixture
    def grafana_config(self, tmp_path, grafana_env_vars):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_observability_uses_grafana(self, grafana_config):
        servers = _build_mcp_servers(grafana_config)
        assert servers["observability"]["command"] == "mcp-grafana"

    def test_observability_has_grafana_env(self, grafana_config):
        servers = _build_mcp_servers(grafana_config)
        env = servers["observability"]["env"]
        assert "GRAFANA_URL" in env
        assert "GRAFANA_API_KEY" in env

    def test_still_has_other_servers(self, grafana_config):
        servers = _build_mcp_servers(grafana_config)
        assert "issue_tracker" in servers
        assert "code_host" in servers


class TestBuildMCPServersGitHubIssues:
    @pytest.fixture
    def github_issues_config(self, tmp_path, github_issues_env_vars):
        config_data = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_issue_tracker_uses_github(self, github_issues_config):
        servers = _build_mcp_servers(github_issues_config)
        assert "github" in servers["issue_tracker"]["url"]

    def test_issue_tracker_has_auth_header(self, github_issues_config):
        servers = _build_mcp_servers(github_issues_config)
        assert "Authorization" in servers["issue_tracker"]["headers"]


class TestBuildMCPServersJira:
    @pytest.fixture
    def jira_config(self, tmp_path, jira_env_vars):
        config_data = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_issue_tracker_uses_jira_url(self, jira_config):
        servers = _build_mcp_servers(jira_config)
        assert servers["issue_tracker"]["url"] == "https://jira-mcp.example.com"

    def test_issue_tracker_has_auth_header(self, jira_config):
        servers = _build_mcp_servers(jira_config)
        assert "Authorization" in servers["issue_tracker"]["headers"]


class TestBuildMCPServers:
    def test_uses_defaults_when_no_overrides(self, sample_config):
        servers = _build_mcp_servers(sample_config)
        assert "observability" in servers
        assert "issue_tracker" in servers
        assert "code_host" in servers

    def test_observability_default_is_datadog(self, sample_config):
        servers = _build_mcp_servers(sample_config)
        obs = servers["observability"]
        assert "datadoghq.com" in obs["url"]
        # Authenticates headlessly via API-key headers (resolved from env), not OAuth.
        assert obs["headers"]["DD_API_KEY"] == "test-dd-api-key"
        assert "DD_APPLICATION_KEY" in obs["headers"]

    def test_issue_tracker_default_is_linear(self, sample_config):
        servers = _build_mcp_servers(sample_config)
        assert "linear" in servers["issue_tracker"]["url"]

    def test_issue_tracker_default_has_auth_header(self, sample_config):
        servers = _build_mcp_servers(sample_config)
        assert "headers" in servers["issue_tracker"]
        assert "Authorization" in servers["issue_tracker"]["headers"]

    def test_code_host_default_is_github(self, sample_config):
        servers = _build_mcp_servers(sample_config)
        assert "github" in servers["code_host"]["url"]

    def test_user_override_replaces_default(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "o/r",
                }
            },
            "mcp_servers": {
                "observability": {
                    "type": "http",
                    "url": "https://custom-obs.example.com/mcp",
                }
            },
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)
        servers = _build_mcp_servers(config)
        assert servers["observability"]["url"] == "https://custom-obs.example.com/mcp"

    def test_code_host_gitlab_when_configured(self, tmp_path, gitlab_env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {
                "svc": {"code_host_repo": "o/r"},
            },
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)
        servers = _build_mcp_servers(config)
        assert servers["code_host"]["command"] == "npx"
        assert "@modelcontextprotocol/server-gitlab" in servers["code_host"]["args"]

    def test_code_host_bitbucket_when_configured(self, tmp_path, bitbucket_env_vars):
        config_data = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {
                "svc": {"code_host_repo": "ws/r"},
            },
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)
        servers = _build_mcp_servers(config)
        assert servers["code_host"]["command"] == "npx"
        assert "@modelcontextprotocol/server-bitbucket" in servers["code_host"]["args"]

    def test_extra_servers_passed_through(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "o/r",
                }
            },
            "mcp_servers": {
                "custom_tool": {
                    "type": "http",
                    "url": "https://custom.example.com/mcp",
                }
            },
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)
        servers = _build_mcp_servers(config)
        assert "custom_tool" in servers


class TestTriageMode:
    @pytest.fixture
    def triage_config(self, tmp_path, env_vars):
        config_data = {
            "version": 1,
            "fix_enabled": False,
            "issue_tracker_type": "linear",
            "run_log_dir": str(tmp_path / "logs"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path)

    def test_build_mcp_servers_excludes_code_host(self, triage_config):
        servers = _build_mcp_servers(triage_config)
        assert "observability" in servers
        assert "issue_tracker" in servers
        assert "code_host" not in servers

    def test_options_have_no_bug_fixer_agent(self, triage_config):
        servers = _build_mcp_servers(triage_config)
        options = _build_options(triage_config, dry_run=False, mcp_servers=servers)
        assert "bug-fixer" not in options.agents
        assert options.agents == {}

    def test_options_use_triage_prompt(self, triage_config):
        servers = _build_mcp_servers(triage_config)
        options = _build_options(triage_config, dry_run=False, mcp_servers=servers)
        assert "Bug Triage Orchestrator" in options.system_prompt
        assert "Ticketed: <count>" in options.system_prompt

    def test_preflight_does_not_require_github_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DD_API_KEY", "x")
        monkeypatch.setenv("DD_APP_KEY", "x")
        monkeypatch.setenv("LINEAR_API_KEY", "x")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        config_data = {"version": 1, "fix_enabled": False}
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)
        servers = _preflight_check(config)
        assert "code_host" not in servers


class TestBuildOptions:
    @pytest.fixture
    def servers(self, sample_config):
        return _build_mcp_servers(sample_config)

    def test_returns_claude_agent_options(self, sample_config, servers):
        from claude_agent_sdk.types import ClaudeAgentOptions

        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert isinstance(options, ClaudeAgentOptions)

    def test_model_from_config(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.model == "claude-sonnet-4-6"

    def test_max_turns_from_config(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.max_turns == 50

    def test_max_budget_from_config(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.max_budget_usd == 2.0

    def test_bypass_permissions(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.permission_mode == "bypassPermissions"

    def test_strict_mcp_config(self, sample_config, servers):
        # Pin MCP servers to our config so host .mcp.json / settings / plugin
        # servers can't shadow or supplement the API-key servers we built.
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.strict_mcp_config is True

    def test_has_bug_fixer_agent(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert "bug-fixer" in options.agents
        assert isinstance(options.agents["bug-fixer"], AgentDefinition)

    def test_bug_fixer_receives_mcp_servers(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        bug_fixer = options.agents["bug-fixer"]
        assert bug_fixer.mcpServers == list(servers.keys())

    def test_no_session_wide_tools_restriction(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.tools is None
        assert not options.disallowed_tools

    def test_dry_run_appends_to_prompt(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=True, mcp_servers=servers)
        assert "DRY RUN MODE" in options.system_prompt

    def test_normal_mode_no_dry_run_text(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert "DRY RUN MODE" not in options.system_prompt

    def test_effort_from_config(self, sample_config, servers):
        options = _build_options(sample_config, dry_run=False, mcp_servers=servers)
        assert options.effort == "high"


class TestPreflightCheck:
    def test_passes_with_valid_config(self, sample_config):
        servers = _preflight_check(sample_config)
        assert "observability" in servers
        assert "issue_tracker" in servers
        assert "code_host" in servers

    def test_fails_on_missing_env_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DD_API_KEY", raising=False)
        monkeypatch.setenv("DD_APP_KEY", "test")
        monkeypatch.setenv("LINEAR_API_KEY", "test")
        monkeypatch.setenv("GITHUB_TOKEN", "test")

        config_data = {
            "version": 1,
            "repositories": {"svc": {"code_host_repo": "o/r"}},
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)

        with pytest.raises(MCPServerError, match="DD_API_KEY"):
            _preflight_check(config)

    def test_suggests_check_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        monkeypatch.setenv("DD_API_KEY", "test")
        monkeypatch.setenv("DD_APP_KEY", "test")
        monkeypatch.setenv("GITHUB_TOKEN", "test")

        config_data = {
            "version": 1,
            "repositories": {"svc": {"code_host_repo": "o/r"}},
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json.dumps(config_data))
        config = load_config(p)

        with pytest.raises(MCPServerError, match="check-env"):
            _preflight_check(config)


class TestParseFixerPrompt:
    def test_parses_standard_prompt(self):
        tool_input = {
            "prompt": (
                "## Bug Fix Request\n\n"
                "**Log Pattern:**\n"
                "NullPointerException in UserService.getUser\n\n"
                "**Pattern Count (last 24h):** 142\n\n"
                "**Log Status:** error\n\n"
                "**Service:** api-service\n\n"
                "**Issue Ticket:** ENG-892\n\n"
                "Please investigate this error."
            ),
        }
        record = _parse_fixer_prompt(tool_input)
        assert record is not None
        assert record.pattern_text == "NullPointerException in UserService.getUser"
        assert record.count == 142
        assert record.status == "error"
        assert record.service == "api-service"
        assert record.ticket_id == "ENG-892"
        assert record.action == "spawned_fixer"

    def test_handles_comma_in_count(self):
        tool_input = {
            "prompt": (
                "**Log Pattern:**\nSome error\n\n"
                "**Pattern Count (last 6h):** 1,234\n\n"
                "**Log Status:** warn\n\n"
                "**Service:** web\n\n"
                "**Issue Ticket:** ML-100\n\n"
            ),
        }
        record = _parse_fixer_prompt(tool_input)
        assert record is not None
        assert record.count == 1234

    def test_returns_none_for_empty_input(self):
        assert _parse_fixer_prompt({}) is None
        assert _parse_fixer_prompt({"prompt": ""}) is None

    def test_returns_none_for_unrelated_prompt(self):
        assert _parse_fixer_prompt({"prompt": "Hello world"}) is None

    def test_multiline_pattern(self):
        tool_input = {
            "prompt": (
                "**Log Pattern:**\n"
                "Error processing request for /api/v1/users\n"
                "caused by: TimeoutException\n\n"
                "**Pattern Count (last 24h):** 50\n\n"
                "**Log Status:** error\n\n"
                "**Service:** gateway\n\n"
                "**Issue Ticket:** ENG-500\n\n"
            ),
        }
        record = _parse_fixer_prompt(tool_input)
        assert record is not None
        assert "TimeoutException" in record.pattern_text


class TestRunOrchestrator:
    @pytest.fixture
    def mock_messages(self):
        """Create a sequence of mock messages simulating a successful run."""
        assistant = AssistantMessage(
            content=[
                TextBlock(text="Found 3 patterns. Processing..."),
                ToolUseBlock(
                    id="tu_1",
                    name="mcp__observability__search_datadog_logs",
                    input={"query": "test"},
                ),
            ],
            model="claude-sonnet-4-6",
        )
        summary = AssistantMessage(
            content=[TextBlock(text="| Pattern | Status |\n|---|---|\n| error X | Fixed |")],
            model="claude-sonnet-4-6",
        )
        result = ResultMessage(
            subtype="result",
            duration_ms=5000,
            duration_api_ms=4000,
            is_error=False,
            num_turns=10,
            session_id="sess_123",
            total_cost_usd=1.25,
            usage={"input_tokens": 1000, "output_tokens": 500},
        )
        return [assistant, summary, result]

    @pytest.mark.asyncio
    async def test_successful_run(self, sample_config, mock_messages):
        async def mock_query(**kwargs):
            for msg in mock_messages:
                yield msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert isinstance(result, RunResult)
        assert result.cost_usd == 1.25
        assert result.duration_ms == 5000
        assert result.num_turns == 10
        assert result.session_id == "sess_123"

    @pytest.mark.asyncio
    async def test_captures_text_blocks(self, sample_config, mock_messages):
        async def mock_query(**kwargs):
            for msg in mock_messages:
                yield msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert len(result.text_blocks) == 2
        assert "Found 3 patterns" in result.text_blocks[0]

    @pytest.mark.asyncio
    async def test_captures_tool_uses(self, sample_config, mock_messages):
        async def mock_query(**kwargs):
            for msg in mock_messages:
                yield msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert len(result.tool_uses) == 1
        assert result.tool_uses[0]["name"] == "mcp__observability__search_datadog_logs"

    @pytest.mark.asyncio
    async def test_summary_is_last_text_block(self, sample_config, mock_messages):
        async def mock_query(**kwargs):
            for msg in mock_messages:
                yield msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert "Pattern" in result.summary_text

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self, sample_config):
        result_msg = ResultMessage(
            subtype="result",
            duration_ms=5000,
            duration_api_ms=4000,
            is_error=True,
            num_turns=50,
            session_id="sess_456",
            stop_reason="budget_exceeded",
            errors=["Budget limit reached"],
        )

        async def mock_query(**kwargs):
            yield result_msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            with pytest.raises(AgentBudgetExceeded):
                await run_orchestrator(sample_config)

    @pytest.mark.asyncio
    async def test_agent_error_raises(self, sample_config):
        result_msg = ResultMessage(
            subtype="result",
            duration_ms=1000,
            duration_api_ms=500,
            is_error=True,
            num_turns=1,
            session_id="sess_789",
            stop_reason="error",
            errors=["MCP server connection failed"],
        )

        async def mock_query(**kwargs):
            yield result_msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            with pytest.raises(AgentError):
                await run_orchestrator(sample_config)

    @pytest.mark.asyncio
    async def test_empty_run_returns_fallback_summary(self, sample_config):
        result_msg = ResultMessage(
            subtype="result",
            duration_ms=500,
            duration_api_ms=200,
            is_error=False,
            num_turns=1,
            session_id="sess_empty",
        )

        async def mock_query(**kwargs):
            yield result_msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert result.summary_text == "No output from orchestrator."

    @pytest.mark.asyncio
    async def test_stop_sequence_no_errors_succeeds(self, sample_config):
        assistant = AssistantMessage(
            content=[TextBlock(text="Done.")],
            model="claude-sonnet-4-6",
        )
        result_msg = ResultMessage(
            subtype="result",
            duration_ms=2000,
            duration_api_ms=1500,
            is_error=True,
            num_turns=5,
            session_id="sess_stop",
            stop_reason="stop_sequence",
            errors=[],
        )

        async def mock_query(**kwargs):
            yield assistant
            yield result_msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert result.summary_text == "Done."
        assert result.num_turns == 5

    @pytest.mark.asyncio
    async def test_post_result_sdk_exception_ignored(self, sample_config):
        """SDK may raise after yielding ResultMessage (e.g. CLI exit code 1).
        When we already have a successful result, the exception is ignored."""
        assistant = AssistantMessage(
            content=[TextBlock(text="All done.")],
            model="claude-sonnet-4-6",
        )
        result_msg = ResultMessage(
            subtype="success",
            duration_ms=3000,
            duration_api_ms=2500,
            is_error=True,
            num_turns=8,
            session_id="sess_post",
            stop_reason="stop_sequence",
            errors=[],
        )

        async def mock_query(**kwargs):
            yield assistant
            yield result_msg
            raise Exception("Claude Code returned an error result: success")

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert result.summary_text == "All done."
        assert result.num_turns == 8

    @pytest.mark.asyncio
    async def test_api_error_status_raises(self, sample_config):
        """An error result carrying an api_error_status (e.g. 401 from an invalid
        ANTHROPIC_API_KEY, 429, or 5xx) did no real work and must surface, even
        though it looks like the benign stop_sequence quirk (is_error + empty
        errors + subtype 'success')."""
        result_msg = ResultMessage(
            subtype="success",
            duration_ms=500,
            duration_api_ms=200,
            is_error=True,
            num_turns=1,
            session_id="sess_401",
            stop_reason="stop_sequence",
            errors=[],
            api_error_status=401,
        )

        async def mock_query(**kwargs):
            yield result_msg

        with patch("fixbot.agents.orchestrator.query", mock_query):
            with pytest.raises(AgentError, match="401"):
                await run_orchestrator(sample_config)

    @pytest.mark.asyncio
    async def test_pre_result_exception_raises(self, sample_config):
        """If the SDK raises before any ResultMessage, it should propagate."""

        async def mock_query(**kwargs):
            raise Exception("Connection refused")
            yield  # make this an async generator

        with patch("fixbot.agents.orchestrator.query", mock_query):
            with pytest.raises(AgentError, match="Connection refused"):
                await run_orchestrator(sample_config)

    @pytest.mark.asyncio
    async def test_dry_run_prompt_differs(self, sample_config):
        captured_kwargs = {}

        async def mock_query(**kwargs):
            captured_kwargs.update(kwargs)
            yield ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=50,
                is_error=False,
                num_turns=1,
                session_id="sess_dry",
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            await run_orchestrator(sample_config, dry_run=True)

        assert "dry-run" in captured_kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_run_log_captures_fixer_patterns(self, sample_config):
        fixer_prompt = (
            "## Bug Fix Request\n\n"
            "**Log Pattern:**\n"
            "NullPointerException in UserService.getUser\n\n"
            "**Pattern Count (last 24h):** 42\n\n"
            "**Log Status:** error\n\n"
            "**Service:** api-service\n\n"
            "**Issue Ticket:** ENG-100\n\n"
            "Please investigate this error."
        )

        async def mock_query(**kwargs):
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tu_1",
                        name="Agent",
                        input={"prompt": fixer_prompt, "subagent_type": "bug-fixer"},
                    ),
                ],
                model="claude-sonnet-4-6",
            )
            yield TaskNotificationMessage(
                subtype="task_notification",
                data={},
                task_id="task_1",
                status="completed",
                output_file="",
                summary="STATUS: CODE_CHANGE — PR https://github.com/org/repo/pull/7",
                uuid="uuid-1",
                session_id="sess_1",
            )
            yield AssistantMessage(
                content=[TextBlock(text="Done.")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="result",
                duration_ms=5000,
                duration_api_ms=4000,
                is_error=False,
                num_turns=5,
                session_id="sess_1",
                total_cost_usd=1.50,
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        log_data = json.loads(Path(result.run_log_path).read_text())
        assert len(log_data["patterns_processed"]) == 1
        p = log_data["patterns_processed"][0]
        assert p["pattern_text"] == "NullPointerException in UserService.getUser"
        assert p["count"] == 42
        assert p["status"] == "error"
        assert p["service"] == "api-service"
        assert p["ticket_id"] == "ENG-100"
        assert p["action"] == "spawned_fixer"
        assert p["fixer_result"] == "CODE_CHANGE"
        assert p["pr_url"] == "https://github.com/org/repo/pull/7"
        assert log_data["summary"]["spawned_fixer"] == 1

    @pytest.mark.asyncio
    async def test_run_log_captures_gitlab_mr_url(self, sample_config):
        fixer_prompt = (
            "## Bug Fix Request\n\n"
            "**Log Pattern:**\n"
            "TimeoutError in PaymentService\n\n"
            "**Pattern Count (last 6h):** 30\n\n"
            "**Log Status:** error\n\n"
            "**Service:** payments\n\n"
            "**Issue Ticket:** ENG-200\n\n"
        )

        async def mock_query(**kwargs):
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tu_1",
                        name="Agent",
                        input={"prompt": fixer_prompt, "subagent_type": "bug-fixer"},
                    ),
                ],
                model="claude-sonnet-4-6",
            )
            yield TaskNotificationMessage(
                subtype="task_notification",
                data={},
                task_id="task_1",
                status="completed",
                output_file="",
                summary="STATUS: CODE_CHANGE — PR https://gitlab.com/org/repo/-/merge_requests/42",
                uuid="uuid-1",
                session_id="sess_1",
            )
            yield AssistantMessage(
                content=[TextBlock(text="Done.")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="result",
                duration_ms=5000,
                duration_api_ms=4000,
                is_error=False,
                num_turns=5,
                session_id="sess_1",
                total_cost_usd=1.50,
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        log_data = json.loads(Path(result.run_log_path).read_text())
        p = log_data["patterns_processed"][0]
        assert p["pr_url"] == "https://gitlab.com/org/repo/-/merge_requests/42"

    @pytest.mark.asyncio
    async def test_run_log_captures_bitbucket_pr_url(self, sample_config):
        fixer_prompt = (
            "## Bug Fix Request\n\n"
            "**Log Pattern:**\n"
            "ConnectionError in QueueWorker\n\n"
            "**Pattern Count (last 6h):** 15\n\n"
            "**Log Status:** error\n\n"
            "**Service:** worker\n\n"
            "**Issue Ticket:** ENG-300\n\n"
        )

        async def mock_query(**kwargs):
            yield AssistantMessage(
                content=[
                    ToolUseBlock(
                        id="tu_1",
                        name="Agent",
                        input={"prompt": fixer_prompt, "subagent_type": "bug-fixer"},
                    ),
                ],
                model="claude-sonnet-4-6",
            )
            yield TaskNotificationMessage(
                subtype="task_notification",
                data={},
                task_id="task_1",
                status="completed",
                output_file="",
                summary="STATUS: CODE_CHANGE — PR https://bitbucket.org/ws/repo/pull-requests/19",
                uuid="uuid-1",
                session_id="sess_1",
            )
            yield AssistantMessage(
                content=[TextBlock(text="Done.")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="result",
                duration_ms=5000,
                duration_api_ms=4000,
                is_error=False,
                num_turns=5,
                session_id="sess_1",
                total_cost_usd=1.50,
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        log_data = json.loads(Path(result.run_log_path).read_text())
        p = log_data["patterns_processed"][0]
        assert p["pr_url"] == "https://bitbucket.org/ws/repo/pull-requests/19"

    @pytest.mark.asyncio
    async def test_run_log_no_code_change(self, sample_config):
        fixer_prompt = (
            "**Log Pattern:**\nSome warning\n\n"
            "**Pattern Count (last 6h):** 100\n\n"
            "**Log Status:** warn\n\n"
            "**Service:** web\n\n"
            "**Issue Ticket:** ML-200\n\n"
        )

        async def mock_query(**kwargs):
            yield AssistantMessage(
                content=[
                    ToolUseBlock(id="tu_1", name="Agent", input={"prompt": fixer_prompt}),
                ],
                model="claude-sonnet-4-6",
            )
            yield TaskNotificationMessage(
                subtype="task_notification",
                data={},
                task_id="task_1",
                status="completed",
                output_file="",
                summary="STATUS: NO_CODE_CHANGE — already addressed in config",
                uuid="uuid-1",
                session_id="sess_1",
            )
            yield AssistantMessage(
                content=[TextBlock(text="Done.")],
                model="claude-sonnet-4-6",
            )
            yield ResultMessage(
                subtype="result",
                duration_ms=3000,
                duration_api_ms=2000,
                is_error=False,
                num_turns=3,
                session_id="sess_1",
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        log_data = json.loads(Path(result.run_log_path).read_text())
        p = log_data["patterns_processed"][0]
        assert p["fixer_result"] == "NO_CODE_CHANGE"
        assert p["pr_url"] is None
