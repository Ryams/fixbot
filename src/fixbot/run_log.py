from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PatternRecord:
    pattern_text: str
    status: str
    count: int
    service: str
    action: str
    ticket_id: str | None = None
    fixer_result: str | None = None
    pr_url: str | None = None


@dataclass
class RunLog:
    version: int = 1
    trigger: str = "cli"
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    patterns_processed: list[PatternRecord] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


class RunLogger:
    def __init__(self, log_dir: str | Path):
        self.log_dir = Path(log_dir)
        self.log = RunLog()
        self._start_time: datetime | None = None

    def start(self, config_snapshot: dict[str, Any], trigger: str = "cli") -> None:
        self._start_time = datetime.now(timezone.utc)
        self.log.started_at = self._start_time.isoformat()
        self.log.trigger = trigger
        self.log.config_snapshot = config_snapshot

    def add_pattern(self, record: PatternRecord) -> None:
        self.log.patterns_processed.append(record)

    def update_last_pattern(self, **kwargs: Any) -> None:
        if not self.log.patterns_processed:
            return
        record = self.log.patterns_processed[-1]
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)

    def finish(
        self,
        cost: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        usage: dict[str, Any] | None = None,
    ) -> Path:
        now = datetime.now(timezone.utc)
        self.log.finished_at = now.isoformat()
        if duration_ms is not None:
            self.log.duration_ms = duration_ms
        elif self._start_time:
            self.log.duration_ms = int((now - self._start_time).total_seconds() * 1000)

        self.log.summary = self._compute_summary()
        if cost:
            self.log.cost = cost
        if usage:
            self.log.usage = usage

        date_dir = self.log_dir / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        time_stamp = now.strftime("%H%M%SZ")
        log_path = date_dir / f"fixbot-run-{time_stamp}.json"

        tmp_path = log_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(asdict(self.log), indent=2, default=str) + "\n")
        tmp_path.rename(log_path)

        return log_path

    def _compute_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for p in self.log.patterns_processed:
            summary[p.action] = summary.get(p.action, 0) + 1
        return summary


def get_recent_run_logs(log_dir: str | Path, n: int = 1) -> list[dict[str, Any]]:
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []

    logs = sorted(log_dir.glob("*/fixbot-run-*.json"), reverse=True)
    return [json.loads(p.read_text()) for p in logs[:n]]
