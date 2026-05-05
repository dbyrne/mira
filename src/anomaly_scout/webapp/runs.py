"""Background task tracking for pipeline runs and photometry sessions.

Each run gets an id, a status (queued/running/done/failed), a list of log
lines, and a result payload. UI polls the run by id to display progress.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal


RunStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class RunRecord:
    run_id: str
    kind: str  # "tonight" | "submit" | etc.
    label: str  # human-readable
    status: RunStatus = "queued"
    progress: float = 0.0  # 0.0–1.0
    log_lines: list[str] = field(default_factory=list)
    result: Any = None
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, message: str) -> None:
        with self._lock:
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.log_lines.append(f"[{timestamp}] {message}")
            # Cap at 500 lines
            if len(self.log_lines) > 500:
                self.log_lines = self.log_lines[-500:]

    def set_progress(self, fraction: float) -> None:
        with self._lock:
            self.progress = max(0.0, min(1.0, fraction))


class RunRegistry:
    """Tracks all pipeline / photometry tasks."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="anomaly-scout")
        self._records: dict[str, RunRecord] = {}
        self._futures: dict[str, Future] = {}
        self._latest_by_kind: dict[str, str] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        label: str,
        target_callable: Callable[[RunRecord], Any],
    ) -> RunRecord:
        run_id = uuid.uuid4().hex[:12]
        record = RunRecord(run_id=run_id, kind=kind, label=label)
        with self._lock:
            self._records[run_id] = record
            self._latest_by_kind[kind] = run_id

        def _runner():
            record.status = "running"
            record.started_at = datetime.now(timezone.utc)
            record.log(f"Started: {label}")
            try:
                result = target_callable(record)
                record.result = result
                record.status = "done"
                record.set_progress(1.0)
                record.log("Finished.")
            except Exception as exc:
                record.status = "failed"
                record.error = str(exc)
                record.log(f"FAILED: {exc}")
            finally:
                record.finished_at = datetime.now(timezone.utc)

        future = self._executor.submit(_runner)
        with self._lock:
            self._futures[run_id] = future
        return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._records.get(run_id)

    def latest(self, kind: str) -> RunRecord | None:
        with self._lock:
            run_id = self._latest_by_kind.get(kind)
            return self._records.get(run_id) if run_id else None

    def all(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)
