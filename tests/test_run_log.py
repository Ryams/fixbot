import json
from pathlib import Path

import pytest

from fixbot.run_log import PatternRecord, RunLogger, get_recent_run_logs


class TestRunLogger:
    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = RunLogger(log_dir)
        logger.start({"model": "test"})
        path = logger.finish()
        assert log_dir.exists()
        assert path.parent.name.count("-") == 2  # date folder like 2026-06-17

    def test_writes_json_file(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({"model": "test"})
        path = logger.finish()
        assert path.exists()
        assert path.suffix == ".json"

    def test_log_file_name_format(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        path = logger.finish()
        assert path.name.startswith("fixbot-run-")
        assert path.name.endswith(".json")

    def test_log_contains_timestamps(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        path = logger.finish()
        data = json.loads(path.read_text())
        assert data["started_at"]
        assert data["finished_at"]
        assert data["duration_ms"] >= 0

    def test_log_contains_config_snapshot(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({"model": "claude-sonnet-4", "dry_run": False})
        path = logger.finish()
        data = json.loads(path.read_text())
        assert data["config_snapshot"]["model"] == "claude-sonnet-4"

    def test_add_pattern(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        logger.add_pattern(
            PatternRecord(
                pattern_text="NullPointerException in UserService",
                status="error",
                count=42,
                service="api-service",
                action="sent_to_fixer",
                ticket_id="ENG-100",
                fixer_result="CODE_CHANGE",
                pr_url="https://github.com/org/repo/pull/1",
            )
        )
        path = logger.finish()
        data = json.loads(path.read_text())
        assert len(data["patterns_processed"]) == 1
        p = data["patterns_processed"][0]
        assert p["pattern_text"] == "NullPointerException in UserService"
        assert p["count"] == 42
        assert p["pr_url"] == "https://github.com/org/repo/pull/1"

    def test_summary_computed(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        logger.add_pattern(PatternRecord("err1", "error", 10, "svc", "sent_to_fixer"))
        logger.add_pattern(PatternRecord("err2", "error", 5, "svc", "sent_to_fixer"))
        logger.add_pattern(PatternRecord("warn1", "warn", 3, "svc", "skipped_tracked"))
        path = logger.finish()
        data = json.loads(path.read_text())
        assert data["summary"]["sent_to_fixer"] == 2
        assert data["summary"]["skipped_tracked"] == 1

    def test_cost_recorded(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        path = logger.finish(cost={"total_usd": 2.47})
        data = json.loads(path.read_text())
        assert data["cost"]["total_usd"] == 2.47

    def test_no_tmp_file_left_behind(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        logger.finish()
        tmp_files = list(tmp_path.glob("**/*.tmp"))
        assert len(tmp_files) == 0

    def test_update_last_pattern(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        logger.add_pattern(PatternRecord("err", "error", 10, "svc", "spawned_fixer"))
        logger.update_last_pattern(
            fixer_result="CODE_CHANGE", pr_url="https://github.com/org/repo/pull/5"
        )
        path = logger.finish()
        data = json.loads(path.read_text())
        p = data["patterns_processed"][0]
        assert p["fixer_result"] == "CODE_CHANGE"
        assert p["pr_url"] == "https://github.com/org/repo/pull/5"

    def test_update_last_pattern_noop_when_empty(self, tmp_path):
        logger = RunLogger(tmp_path)
        logger.start({})
        logger.update_last_pattern(fixer_result="CODE_CHANGE")
        path = logger.finish()
        data = json.loads(path.read_text())
        assert len(data["patterns_processed"]) == 0


class TestGetRecentRunLogs:
    def test_returns_empty_when_no_dir(self, tmp_path):
        assert get_recent_run_logs(tmp_path / "nonexistent") == []

    def test_returns_empty_when_no_logs(self, tmp_path):
        assert get_recent_run_logs(tmp_path) == []

    def test_returns_n_most_recent(self, tmp_path):
        day = tmp_path / "2026-01-01"
        day.mkdir()
        for ts in ["100000Z", "110000Z", "120000Z"]:
            (day / f"fixbot-run-{ts}.json").write_text(json.dumps({"ts": ts}))
        results = get_recent_run_logs(tmp_path, n=2)
        assert len(results) == 2
        assert results[0]["ts"] == "120000Z"
        assert results[1]["ts"] == "110000Z"

    def test_returns_all_when_n_exceeds_count(self, tmp_path):
        day = tmp_path / "2026-01-01"
        day.mkdir()
        (day / "fixbot-run-100000Z.json").write_text(json.dumps({"ts": "1"}))
        results = get_recent_run_logs(tmp_path, n=5)
        assert len(results) == 1


class TestRunLogIntegrationWithOrchestrator:
    """Test that run_orchestrator writes a log file."""

    @pytest.fixture
    def sample_config(self, tmp_path, env_vars):
        import json as json_mod

        from fixbot.config import load_config

        config_data = {
            "version": 1,
            "repositories": {
                "svc": {
                    "code_host_repo": "org/repo",
                }
            },
            "worktree_dir": str(tmp_path / ".worktrees"),
            "run_log_dir": str(tmp_path / "logs"),
        }
        p = tmp_path / "fixbot.json"
        p.write_text(json_mod.dumps(config_data))
        return load_config(p)

    @pytest.mark.asyncio
    async def test_log_written_on_success(self, sample_config):
        from unittest.mock import patch

        from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock

        from fixbot.agents.orchestrator import run_orchestrator

        async def mock_query(**kwargs):
            yield AssistantMessage(
                content=[TextBlock(text="Done")],
                model="test",
            )
            yield ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=50,
                is_error=False,
                num_turns=1,
                session_id="s1",
                total_cost_usd=0.50,
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            result = await run_orchestrator(sample_config)

        assert result.run_log_path is not None
        log_data = json.loads(Path(result.run_log_path).read_text())
        assert log_data["cost"]["total_usd"] == 0.50
        assert log_data["config_snapshot"]["dry_run"] is False

    @pytest.mark.asyncio
    async def test_log_written_on_error(self, sample_config):
        from unittest.mock import patch

        from claude_agent_sdk.types import ResultMessage

        from fixbot.agents.orchestrator import run_orchestrator
        from fixbot.exceptions import AgentError

        async def mock_query(**kwargs):
            yield ResultMessage(
                subtype="result",
                duration_ms=100,
                duration_api_ms=50,
                is_error=True,
                num_turns=1,
                session_id="s2",
                stop_reason="error",
                errors=["fail"],
            )

        with patch("fixbot.agents.orchestrator.query", mock_query):
            with pytest.raises(AgentError):
                await run_orchestrator(sample_config)

        log_dir = Path(sample_config.run_log_dir)
        logs = list(log_dir.glob("*/fixbot-run-*.json"))
        assert len(logs) == 1
