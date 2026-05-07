"""Background task tracking for pipeline runs and photometry sessions.

Each run gets an id, a status (queued/running/done/failed), a list of log
lines, and a result payload. UI polls the run by id to display progress.
"""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal


RunStatus = Literal["queued", "running", "done", "failed"]


def _deep_snapshot(value: Any) -> Any:
    """Return a copy that won't share mutable state with the source. Used by
    ``RunRecord.to_dict()`` so a serialized snapshot doesn't observe writes
    that land between the snapshot start and its consumption (e.g.
    ``json.dumps`` iterating a list mid-append)."""
    if isinstance(value, dict):
        return {key: _deep_snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_snapshot(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_deep_snapshot(item) for item in value)
    return value


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

    def update_result(self, mutator: Callable[[Any], Any]) -> None:
        """Atomically mutate ``self.result`` under the lock. Use this from
        background tasks instead of manipulating ``record.result`` directly,
        so that concurrent ``to_dict()`` snapshots don't see a torn state."""
        with self._lock:
            self.result = mutator(self.result)

    def to_dict(self) -> dict[str, Any]:
        # Snapshot every mutable field under the lock so ``_persist()`` can't
        # serialize a half-updated state while a background thread mutates
        # log_lines / result / progress.
        with self._lock:
            log_snapshot = list(self.log_lines)
            result_snapshot = _deep_snapshot(self.result)
            progress = self.progress
            status = self.status
            error = self.error
            created = self.created_at
            started = self.started_at
            finished = self.finished_at
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "label": self.label,
            "status": status,
            "progress": progress,
            "log_lines": log_snapshot,
            "result": result_snapshot,
            "error": error,
            "created_at": created.isoformat() if created else None,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        def _parse_dt(value: str | None) -> datetime | None:
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None

        return cls(
            run_id=data["run_id"],
            kind=data["kind"],
            label=data.get("label", ""),
            status=data.get("status", "failed"),  # type: ignore[arg-type]
            progress=float(data.get("progress", 0.0)),
            log_lines=list(data.get("log_lines", [])),
            result=data.get("result"),
            error=data.get("error", ""),
            created_at=_parse_dt(data.get("created_at")) or datetime.now(timezone.utc),
            started_at=_parse_dt(data.get("started_at")),
            finished_at=_parse_dt(data.get("finished_at")),
        )


class RunRegistry:
    """Tracks all pipeline / photometry tasks. Optionally persists records
    to a state directory so they survive server restarts."""

    def __init__(self, max_workers: int = 2, state_dir: Path | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mira")
        self._records: dict[str, RunRecord] = {}
        self._futures: dict[str, Future] = {}
        self._latest_by_kind: dict[str, str] = {}
        self._lock = threading.Lock()
        self._state_dir = state_dir
        if self._state_dir is not None:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._load_existing()

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
        self._persist(record)

        def _runner():
            record.status = "running"
            record.started_at = datetime.now(timezone.utc)
            record.log(f"Started: {label}")
            self._persist(record)
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
                self._persist(record)

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

    # --- Persistence ---

    def persist(self, record: RunRecord) -> None:
        """Public accessor to write a record to disk after external mutation
        (e.g., the photometry route marking a run as submitted)."""
        self._persist(record)

    def _persist(self, record: RunRecord) -> None:
        if self._state_dir is None:
            return
        path = self._state_dir / f"{record.run_id}.json"
        try:
            payload = json.dumps(record.to_dict(), indent=2, default=str)
            path.write_text(payload, encoding="utf-8")
        except OSError:
            pass

    def _load_existing(self) -> None:
        if self._state_dir is None or not self._state_dir.exists():
            return
        for path in sorted(self._state_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                record = RunRecord.from_dict(data)
            except (OSError, ValueError, KeyError):
                continue
            # Any in-flight runs were lost when the server died.
            if record.status in ("queued", "running"):
                record.status = "failed"
                record.error = (record.error + "; lost on server restart").strip("; ")
                record.log("[restart] Run was in flight when the server restarted; marked failed.")
                self._persist(record)
            self._records[record.run_id] = record
            existing = self._latest_by_kind.get(record.kind)
            existing_record = self._records.get(existing) if existing else None
            if (
                existing_record is None
                or (record.created_at and existing_record.created_at and record.created_at > existing_record.created_at)
            ):
                self._latest_by_kind[record.kind] = record.run_id
