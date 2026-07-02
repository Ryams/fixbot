import io
import time

from fixbot.progress import ProgressDisplay, classify_tool, parse_fixer_result


class TestClassifyTool:
    def test_observability(self):
        assert classify_tool("mcp__observability__search_datadog_logs") == "fetching_logs"

    def test_issue_tracker(self):
        assert classify_tool("mcp__issue_tracker__list_issues") == "checking_tracker"

    def test_agent(self):
        assert classify_tool("Agent") == "spawning_fixer"

    def test_unknown(self):
        assert classify_tool("Bash") is None

    def test_partial_match(self):
        assert classify_tool("mcp__observability") is None


class TestProgressDisplay:
    def test_update_and_stop_non_tty(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Fetching logs")
        time.sleep(0.05)
        progress.stop()
        output = buf.getvalue()
        assert "Fetching logs..." in output
        assert "✓ Fetching logs" in output

    def test_multiple_phases_non_tty(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Fetching logs")
        time.sleep(0.05)
        progress.update("Checking tracker")
        time.sleep(0.05)
        progress.stop()
        output = buf.getvalue()
        assert "✓ Fetching logs" in output
        assert "✓ Checking tracker" in output

    def test_context_manager(self):
        buf = io.StringIO()
        with ProgressDisplay(file=buf) as progress:
            progress.update("Working")
            time.sleep(0.05)
        output = buf.getvalue()
        assert "✓ Working" in output

    def test_stop_without_update(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.stop()
        assert buf.getvalue() == ""

    def test_elapsed_time_shown(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Slow task")
        time.sleep(0.15)
        progress.stop()
        output = buf.getvalue()
        assert "✓ Slow task (" in output
        assert "s)" in output

    def test_annotate_shown_on_completion(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Spawning bug-fixer 1")
        progress.annotate("PR created")
        progress.stop()
        output = buf.getvalue()
        assert "✓ Spawning bug-fixer 1 → PR created" in output

    def test_annotate_cleared_on_next_update(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Fixer 1")
        progress.annotate("PR created")
        progress.update("Fixer 2")
        progress.stop()
        output = buf.getvalue()
        assert "✓ Fixer 1 → PR created" in output
        assert "→" not in output.split("Fixer 2")[1]

    def test_no_annotation_no_arrow(self):
        buf = io.StringIO()
        progress = ProgressDisplay(file=buf)
        progress.update("Fetching logs")
        progress.stop()
        assert "→" not in buf.getvalue()


class TestParseFixerResult:
    def test_code_change_with_pr(self):
        summary = "STATUS: CODE_CHANGE — PR https://github.com/org/repo/pull/42"
        assert parse_fixer_result(summary) == "PR created (https://github.com/org/repo/pull/42)"

    def test_code_change_no_url(self):
        assert parse_fixer_result("STATUS: CODE_CHANGE — PR submitted") == "PR created"

    def test_no_code_change(self):
        assert parse_fixer_result("STATUS: NO_CODE_CHANGE — already addressed") == "no fix needed"

    def test_empty_summary(self):
        assert parse_fixer_result("") == ""

    def test_unrecognized_summary(self):
        assert parse_fixer_result("some random output") == ""
