from __future__ import annotations

import re
import sys
import threading
import time
from typing import TextIO

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ProgressDisplay:
    """Animated spinner for terminal progress feedback."""

    def __init__(self, file: TextIO | None = None):
        self._file: TextIO = file or sys.stderr
        self._is_tty = hasattr(self._file, "isatty") and self._file.isatty()
        self._message = ""
        self._annotation = ""
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float = 0

    def __enter__(self) -> ProgressDisplay:
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()

    def annotate(self, text: str) -> None:
        """Set annotation shown when the current step completes."""
        self._annotation = text

    def update(self, message: str) -> None:
        self._finish_current()
        self._message = message
        self._annotation = ""
        self._started_at = time.monotonic()
        if self._is_tty:
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self._file.write(f"  {message}...\n")
            self._file.flush()

    def stop(self) -> None:
        self._finish_current()
        self._message = ""

    def _finish_current(self) -> None:
        if not self._message:
            return
        self._halt_spinner()
        elapsed = time.monotonic() - self._started_at
        suffix = f" → {self._annotation}" if self._annotation else ""
        if self._is_tty:
            self._file.write(f"\r\033[K✓ {self._message}{suffix} ({elapsed:.1f}s)\n")
        else:
            self._file.write(f"  ✓ {self._message}{suffix} ({elapsed:.1f}s)\n")
        self._file.flush()

    def _halt_spinner(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            frame = SPINNER_FRAMES[idx % len(SPINNER_FRAMES)]
            self._file.write(f"\r\033[K{frame} {self._message}...")
            self._file.flush()
            idx += 1
            self._stop_event.wait(0.08)


def classify_tool(name: str) -> str | None:
    if name.startswith("mcp__observability__"):
        return "fetching_logs"
    if name.startswith("mcp__issue_tracker__"):
        return "checking_tracker"
    if name == "Agent":
        return "spawning_fixer"
    return None


_PR_URL_RE = re.compile(r"https?://\S+pull/\d+\S*")


def parse_fixer_result(summary: str) -> str:
    """Extract a short annotation from a bug-fixer's STATUS line."""
    if "CODE_CHANGE" in summary and "NO_CODE_CHANGE" not in summary:
        m = _PR_URL_RE.search(summary)
        return f"PR created ({m.group(0)})" if m else "PR created"
    if "NO_CODE_CHANGE" in summary:
        return "no fix needed"
    return ""
