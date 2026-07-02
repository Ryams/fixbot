import json

import pytest

from fixbot.config import load_config
from fixbot.prompts import bug_fixer, orchestrator


@pytest.fixture
def sample_config(tmp_path):
    config_data = {
        "version": 1,
        "repositories": {
            "my-api": {
                "code_host_repo": "myorg/my-api",
            },
            "my-worker": {
                "code_host_repo": "myorg/my-worker",
            },
        },
        "log_routing": [
            {"key": "service", "value": "api-service", "repo": "my-api"},
            {"key": "service", "value": "api", "repo": "my-api"},
            {"key": "service", "value": "worker", "repo": "my-worker"},
        ],
        "worktree_dir": str(tmp_path / ".worktrees"),
        "orchestrator": {
            "log_query": "status:(error OR warn) env:staging",
            "log_window_hours": 12,
            "max_code_fixes_per_run": 5,
            "max_patterns_to_process": 30,
        },
        "issue_tracker_settings": {
            "team": "Platform",
            "project": "Auto Bugs",
            "branch_prefix": "alice",
            "ticket_prefix": "PLAT",
            "error_priority": 1,
            "warn_priority": 2,
        },
        "read_only_repos": ["/shared/utils"],
    }
    config_path = tmp_path / "fixbot.json"
    config_path.write_text(json.dumps(config_data))
    return load_config(config_path, resolve_env=False)


class TestOrchestratorPrompt:
    def test_contains_log_query(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "status:(error OR warn) env:staging" in prompt

    def test_contains_time_window(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "now-12h" in prompt

    def test_contains_max_fixes(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "5 bug-fixers produce code changes" in prompt

    def test_contains_issue_tracker_settings(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert '"Platform"' in prompt
        assert '"Auto Bugs"' in prompt

    def test_contains_priority_levels(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "**1**" in prompt  # error_priority
        assert "**2**" in prompt  # warn_priority

    def test_contains_max_patterns(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "top 30 patterns" in prompt

    def test_contains_headless_instruction(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "headless" in prompt
        assert "Never ask the user" in prompt

    def test_contains_terminal_formatting_instruction(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Plain text only" in prompt
        assert "No markdown syntax" in prompt

    def test_filter_instructions_omitted_when_none(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Additional Filtering Rules" not in prompt

    def test_filter_instructions_included_when_set(self, sample_config):
        sample_config.orchestrator.filter_instructions = "Ignore DeprecationWarning patterns."
        prompt = orchestrator.render(sample_config)
        assert "Additional Filtering Rules" in prompt
        assert "Ignore DeprecationWarning patterns." in prompt

    def test_service_scope_with_log_routing(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Log-to-Repository Routing" in prompt
        assert "`api-service`" in prompt
        assert "`worker`" in prompt
        assert "Skip any pattern that does not match a routing rule" in prompt

    def test_service_scope_without_log_routing(self, tmp_path):
        config_data = {
            "version": 1,
            "repositories": {
                "my-api": {
                    "code_host_repo": "myorg/my-api",
                },
            },
            "log_routing": [],
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(config_path, resolve_env=False)
        prompt = orchestrator.render(config)
        assert "In-Scope Services" in prompt
        assert "`my-api`" in prompt
        assert "Only process patterns for services that clearly correspond" in prompt

    def test_query_does_not_contain_service_filter(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "service:(" not in prompt

    def test_contains_filter_step_1c(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Step 1c: Filter Out-of-Scope Services" in prompt

    def test_out_of_scope_routed_to_skipped_list(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Skipped list" in prompt
        assert "out-of-scope service" in prompt

    def test_result_categories_present(self, sample_config):
        prompt = orchestrator.render(sample_config)
        assert "Fixed: <count>" in prompt
        assert "Already tracked: <count>" in prompt
        assert "Skipped: <count>" in prompt
        assert "Deferred to next run: <count>" in prompt
        assert "Patterns fetched: <count>" in prompt
        # No leftover legacy headers
        assert "TOTALS" not in prompt
        assert "BUG-FIXER RESULTS" not in prompt


class TestOrchestratorPromptTriage:
    @pytest.fixture
    def triage_config(self, tmp_path):
        config_data = {
            "version": 1,
            "fix_enabled": False,
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "log_routing": [
                {"key": "service", "value": "api-service", "repo": "my-api"},
            ],
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    @pytest.fixture
    def triage_no_repos_config(self, tmp_path):
        config_data = {"version": 1, "fix_enabled": False}
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_uses_triage_header(self, triage_config):
        prompt = orchestrator.render(triage_config)
        assert "Bug Triage Orchestrator" in prompt

    def test_ticketed_category(self, triage_config):
        prompt = orchestrator.render(triage_config)
        assert "Ticketed: <count>" in prompt
        assert "Already tracked: <count>" in prompt
        assert "Deferred to next run: <count>" in prompt

    def test_no_fix_or_pr_language(self, triage_config):
        prompt = orchestrator.render(triage_config)
        assert "Fixed: <count>" not in prompt
        assert "spawn a bug-fixer subagent" in prompt  # explicit prohibition
        assert "submit a PR" not in prompt

    def test_still_fetches_and_searches(self, triage_config):
        prompt = orchestrator.render(triage_config)
        assert "Step 2: Triage Each Pattern" in prompt
        assert "Search issue tracker for existing tickets" in prompt
        assert "Create issue tracker ticket" in prompt

    def test_scope_filter_step_present_with_routing(self, triage_config):
        prompt = orchestrator.render(triage_config)
        assert "Step 1c: Filter Out-of-Scope Services" in prompt

    def test_no_scope_filter_step_without_repos(self, triage_no_repos_config):
        prompt = orchestrator.render(triage_no_repos_config)
        assert "Step 1c" not in prompt
        assert "every fetched pattern is in scope" in prompt


class TestOrchestratorPromptGitLab:
    @pytest.fixture
    def gitlab_config(self, tmp_path):
        config_data = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_uses_mr_term(self, gitlab_config):
        prompt = orchestrator.render(gitlab_config)
        assert "MR link" in prompt
        assert "MR submitted" in prompt

    def test_uses_gitlab_url_hint(self, gitlab_config):
        prompt = orchestrator.render(gitlab_config)
        assert "gitlab.com/.../-/merge_requests/..." in prompt

    def test_no_github_references(self, gitlab_config):
        prompt = orchestrator.render(gitlab_config)
        assert "github.com" not in prompt
        assert "pull/..." not in prompt


class TestOrchestratorPromptBitbucket:
    @pytest.fixture
    def bitbucket_config(self, tmp_path):
        config_data = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {
                "my-api": {"code_host_repo": "myworkspace/my-api"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_uses_pr_term(self, bitbucket_config):
        prompt = orchestrator.render(bitbucket_config)
        assert "PR link" in prompt

    def test_uses_bitbucket_url_hint(self, bitbucket_config):
        prompt = orchestrator.render(bitbucket_config)
        assert "bitbucket.org/.../pull-requests/..." in prompt


class TestBugFixerPrompt:
    def test_contains_repo_names(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "my-api" in prompt
        assert "my-worker" in prompt

    def test_contains_worktree_dir(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert ".worktrees" in prompt

    def test_contains_branch_prefix(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "alice/" in prompt

    def test_contains_code_host_repos(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "myorg/my-api" in prompt
        assert "myorg/my-worker" in prompt

    def test_contains_status_reporting(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "STATUS: CODE_CHANGE" in prompt
        assert "STATUS: NO_CODE_CHANGE" in prompt

    def test_contains_read_only_repos(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "/shared/utils" in prompt

    def test_contains_worktree_instructions(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "git -C" in prompt
        assert "worktree add" in prompt
        assert "worktree remove" in prompt

    def test_contains_clone_instructions(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "git clone --bare" in prompt
        assert "repos/<repo-name>" in prompt

    def test_no_local_path_column(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "Local path" not in prompt
        assert "clone needed" not in prompt

    def test_pr_creation_uses_mcp(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "code host MCP tool" in prompt
        assert "gh pr create" not in prompt

    def test_contains_allowed_repos(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "Allowed repositories for code changes" in prompt
        assert "`myorg/my-api`" in prompt
        assert "`myorg/my-worker`" in prompt

    def test_repo_boundary_hard_limit(self, sample_config):
        prompt = bug_fixer.render(sample_config)
        assert "HARD LIMIT" in prompt
        assert "do NOT clone it, push to it, or open a PR" in prompt


class TestOrchestratorPromptGitHubIssues:
    @pytest.fixture
    def github_issues_config(self, tmp_path):
        config_data = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "issue_tracker_settings": {
                "error_label": "bug",
                "warn_label": "warning",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_no_linear_team_project(self, github_issues_config):
        prompt = orchestrator.render(github_issues_config)
        assert '"Engineering"' not in prompt
        assert '"fixbot"' not in prompt

    def test_uses_labels(self, github_issues_config):
        prompt = orchestrator.render(github_issues_config)
        assert '"bug"' in prompt
        assert '"warning"' in prompt

    def test_uses_open_closed_states(self, github_issues_config):
        prompt = orchestrator.render(github_issues_config)
        assert "open" in prompt.lower()
        assert "closed" in prompt

    def test_no_linear_states(self, github_issues_config):
        prompt = orchestrator.render(github_issues_config)
        assert "Review, Todo, Backlog" not in prompt


class TestOrchestratorPromptJira:
    @pytest.fixture
    def jira_config(self, tmp_path):
        config_data = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "issue_tracker_settings": {
                "jira_project_key": "PLAT",
                "jira_issue_type": "Bug",
                "jira_error_priority": "High",
                "jira_warn_priority": "Medium",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_no_linear_team_project(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert '"Engineering"' not in prompt
        assert '"fixbot"' not in prompt

    def test_uses_jira_project_key(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert '"PLAT"' in prompt

    def test_uses_jira_priorities(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert '"High"' in prompt
        assert '"Medium"' in prompt

    def test_uses_jira_issue_type(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert '"Bug"' in prompt

    def test_uses_jira_states(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert "Open, To Do, In Progress, Reopened" in prompt
        assert "Done, Closed, or Resolved" in prompt

    def test_no_linear_states(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert "Review, Todo, Backlog" not in prompt

    def test_uses_jql(self, jira_config):
        prompt = orchestrator.render(jira_config)
        assert "JQL" in prompt


class TestBugFixerPromptJira:
    @pytest.fixture
    def jira_config(self, tmp_path):
        config_data = {
            "version": 1,
            "issue_tracker_type": "jira",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "issue_tracker_settings": {
                "branch_prefix": "fixbot",
                "jira_project_key": "ENG",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_branch_uses_ticket_id(self, jira_config):
        prompt = bug_fixer.render(jira_config)
        assert "<ticket-id-lowercase>" in prompt

    def test_commit_ref_uses_ticket_id(self, jira_config):
        prompt = bug_fixer.render(jira_config)
        assert "Fixes <TICKET-ID>" in prompt

    def test_ticket_id_description_mentions_jira(self, jira_config):
        prompt = bug_fixer.render(jira_config)
        assert "Jira issue key" in prompt

    def test_branch_example(self, jira_config):
        prompt = bug_fixer.render(jira_config)
        assert "eng-42-model-error" in prompt

    def test_no_github_issue_number(self, jira_config):
        prompt = bug_fixer.render(jira_config)
        assert "Fixes #<issue-number>" not in prompt


class TestBugFixerPromptGitHubIssues:
    @pytest.fixture
    def github_issues_config(self, tmp_path):
        config_data = {
            "version": 1,
            "issue_tracker_type": "github",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "issue_tracker_settings": {
                "branch_prefix": "fixbot",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_branch_uses_issue_number(self, github_issues_config):
        prompt = bug_fixer.render(github_issues_config)
        assert "<issue-number>" in prompt

    def test_commit_ref_uses_hash(self, github_issues_config):
        prompt = bug_fixer.render(github_issues_config)
        assert "Fixes #<issue-number>" in prompt

    def test_no_linear_ticket_format(self, github_issues_config):
        prompt = bug_fixer.render(github_issues_config)
        assert "eng-892" not in prompt
        assert "ENG-892" not in prompt

    def test_branch_example(self, github_issues_config):
        prompt = bug_fixer.render(github_issues_config)
        assert "42-model-error" in prompt


class TestBugFixerPromptGitLab:
    @pytest.fixture
    def gitlab_config(self, tmp_path):
        config_data = {
            "version": 1,
            "code_host_type": "gitlab",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "issue_tracker_settings": {
                "branch_prefix": "fixbot",
                "ticket_prefix": "ENG",
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_clone_url_uses_gitlab(self, gitlab_config):
        prompt = bug_fixer.render(gitlab_config)
        assert "oauth2:${GITLAB_TOKEN}@gitlab.com" in prompt

    def test_no_github_clone_url(self, gitlab_config):
        prompt = bug_fixer.render(gitlab_config)
        assert "${GITHUB_TOKEN}@github.com" not in prompt

    def test_uses_mr_term(self, gitlab_config):
        prompt = bug_fixer.render(gitlab_config)
        assert "submit a MR with a fix" in prompt
        assert "Create MR" in prompt or "Create Branch, Fix, and MR" in prompt

    def test_status_reporting_uses_mr(self, gitlab_config):
        prompt = bug_fixer.render(gitlab_config)
        assert "STATUS: CODE_CHANGE — MR" in prompt

    def test_repo_boundary_uses_mr(self, gitlab_config):
        prompt = bug_fixer.render(gitlab_config)
        assert "open MRs" in prompt or "open a MR" in prompt


class TestOrchestratorPromptGrafana:
    @pytest.fixture
    def grafana_config(self, tmp_path):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_uses_loki_patterns_tool(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "query_loki_patterns" in prompt

    def test_uses_logql_syntax(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "LogQL" in prompt

    def test_default_log_query_is_logql(self, grafana_config):
        assert grafana_config.orchestrator.log_query == '{level=~"error|warn"}'

    def test_no_datadog_references(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "use_log_patterns" not in prompt
        assert "max_tokens: 5000" not in prompt

    def test_includes_datasource_discovery(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "list_datasources" in prompt
        assert "datasourceUid" in prompt

    def test_stream_selector_only(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "stream selector only" in prompt

    def test_contains_iso_timestamp_instructions(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "ISO 8601" in prompt

    def test_still_has_triage_steps(self, grafana_config):
        prompt = orchestrator.render(grafana_config)
        assert "Step 1c: Filter Out-of-Scope Services" in prompt
        assert "Step 2: Triage Each Pattern" in prompt
        assert "Step 3: Report Results" in prompt


class TestBugFixerPromptGrafana:
    @pytest.fixture
    def grafana_config(self, tmp_path):
        config_data = {
            "version": 1,
            "observability_type": "grafana",
            "repositories": {
                "my-api": {"code_host_repo": "myorg/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_uses_loki_tool(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "query_loki_logs" in prompt

    def test_no_datadog_references(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "use_log_patterns" not in prompt
        assert "extra_fields" not in prompt

    def test_contains_logql_query_example(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "level=~" in prompt

    def test_uses_logql_param_not_querystring(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "logql:" in prompt
        assert "queryString" not in prompt

    def test_discovers_datasource_uid(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "list_datasources" in prompt
        assert "datasourceUid" in prompt

    def test_still_has_remaining_phases(self, grafana_config):
        prompt = bug_fixer.render(grafana_config)
        assert "Phase 2: Set Up Worktree" in prompt
        assert "Phase 3: Research the Codebase" in prompt
        assert "Phase 4: Update Issue Ticket" in prompt
        assert "Phase 5: Create Branch, Fix, and PR" in prompt


class TestBugFixerPromptBitbucket:
    @pytest.fixture
    def bitbucket_config(self, tmp_path):
        config_data = {
            "version": 1,
            "code_host_type": "bitbucket",
            "repositories": {
                "my-api": {"code_host_repo": "myworkspace/my-api"},
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
        }
        config_path = tmp_path / "fixbot.json"
        config_path.write_text(json.dumps(config_data))
        return load_config(config_path, resolve_env=False)

    def test_clone_url_uses_bitbucket(self, bitbucket_config):
        prompt = bug_fixer.render(bitbucket_config)
        assert "x-token-auth:${BITBUCKET_TOKEN}@bitbucket.org" in prompt

    def test_no_github_clone_url(self, bitbucket_config):
        prompt = bug_fixer.render(bitbucket_config)
        assert "${GITHUB_TOKEN}@github.com" not in prompt
