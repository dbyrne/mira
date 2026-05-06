"""SQLite session database for queryable run history.

Tables:
- sessions: one row per (target, date) photometry session, with summary fields.
- observations: one row per FITS frame measurement, linked to a session.

The DB is the *queryable index* over run records. The canonical record stays
in state_dir/<run_id>.json (so the JSON is the source of truth and the DB
can be rebuilt at any time by walking the JSON files).
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY,
        run_id TEXT UNIQUE NOT NULL,
        target_name TEXT NOT NULL,
        target_slug TEXT NOT NULL,
        session_date TEXT,
        observer_code TEXT,
        chart_id TEXT,
        observation_count INTEGER,
        median_mag REAL,
        anomaly_level TEXT,
        submitted_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        julian_date REAL,
        magnitude REAL,
        magnitude_error REAL,
        band TEXT,
        comp_star_label TEXT,
        comp_star_mag REAL,
        flag TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_target ON sessions(target_slug)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(session_date)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_anomaly ON sessions(anomaly_level)",
    "CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id)",
]


class SessionStore:
    """Thread-safe wrapper around sqlite3 for session queries.

    Each method takes its own connection (sqlite3 connections are not safe
    to share across threads by default). For the webapp's modest write
    volume this is fine."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """sqlite3.Connection as a context manager that *closes* on exit
        (the stdlib's ``with conn:`` only commits/rolls back). Closing
        matters on Windows so temp dirs in tests can be cleaned up."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            for ddl in SCHEMA:
                conn.execute(ddl)

    def upsert_session(
        self,
        run_id: str,
        target_name: str,
        target_slug: str,
        session_date: str | None,
        observer_code: str | None,
        chart_id: str | None,
        observation_count: int | None,
        median_mag: float | None,
        anomaly_level: str | None,
        submitted_at: str | None,
        created_at: str,
        observations: Iterable[dict[str, Any]],
    ) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    run_id, target_name, target_slug, session_date, observer_code,
                    chart_id, observation_count, median_mag, anomaly_level,
                    submitted_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    target_name=excluded.target_name,
                    target_slug=excluded.target_slug,
                    session_date=excluded.session_date,
                    observer_code=excluded.observer_code,
                    chart_id=excluded.chart_id,
                    observation_count=excluded.observation_count,
                    median_mag=excluded.median_mag,
                    anomaly_level=excluded.anomaly_level,
                    submitted_at=excluded.submitted_at
                """,
                (
                    run_id, target_name, target_slug, session_date, observer_code,
                    chart_id, observation_count, median_mag, anomaly_level,
                    submitted_at, created_at,
                ),
            )
            # `lastrowid` reflects the INSERT path's new row id; on the UPDATE
            # branch of ON CONFLICT it can be 0 or stale, so always re-resolve
            # from the canonical `run_id` lookup. Raise rather than silently
            # writing observations to session_id=0 (orphan rows).
            row = conn.execute("SELECT id FROM sessions WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise RuntimeError(f"upsert_session: failed to resolve session id for run {run_id!r}")
            session_id = int(row["id"])

            # Replace observations for this session (simpler than diffing).
            conn.execute("DELETE FROM observations WHERE session_id = ?", (session_id,))
            for obs in observations:
                conn.execute(
                    """
                    INSERT INTO observations (
                        session_id, filename, julian_date, magnitude, magnitude_error,
                        band, comp_star_label, comp_star_mag, flag
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        obs.get("filename", ""),
                        obs.get("julian_date"),
                        obs.get("magnitude"),
                        obs.get("magnitude_error"),
                        obs.get("band"),
                        obs.get("comp_star_label"),
                        obs.get("comp_star_mag"),
                        obs.get("flag"),
                    ),
                )
            return session_id

    def mark_submitted(self, run_id: str, submitted_at: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET submitted_at = ? WHERE run_id = ?",
                (submitted_at, run_id),
            )

    def list_sessions(
        self,
        target_slug: str | None = None,
        anomaly_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM sessions"
        clauses: list[str] = []
        params: list[Any] = []
        if target_slug:
            clauses.append("target_slug = ?")
            params.append(target_slug)
        if anomaly_only:
            clauses.append("anomaly_level = 'anomaly'")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY session_date DESC, created_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_observations(self, target_slug: str) -> list[dict[str, Any]]:
        sql = """
            SELECT s.session_date, s.run_id, o.*
            FROM observations o
            JOIN sessions s ON s.id = o.session_id
            WHERE s.target_slug = ?
            ORDER BY o.julian_date ASC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (target_slug,)).fetchall()
        return [dict(row) for row in rows]

    def session_count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
        return int(row["n"])


def from_run_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a serialized RunRecord (or its result dict) into the kwargs
    needed by `upsert_session`. Returns None if the record isn't a finished
    photometry submit."""
    if not record:
        return None
    if record.get("status") != "done":
        return None
    if not record.get("kind", "").startswith("submit:"):
        return None
    result = record.get("result") or {}
    if not isinstance(result, dict):
        return None
    target_slug = result.get("target_slug")
    if not target_slug:
        # Old records: derive from kind="submit:<slug>[:date]"
        kind = record.get("kind", "")
        rest = kind.split(":", 1)[1] if ":" in kind else ""
        target_slug = rest.split(":", 1)[0] if rest else "unknown"
    session_date = result.get("session_date")
    if session_date is None:
        # Try parsing kind suffix
        kind_parts = record.get("kind", "").split(":")
        if len(kind_parts) >= 3 and len(kind_parts[2]) == 10:
            session_date = kind_parts[2]
    return {
        "run_id": record.get("run_id", ""),
        "target_name": result.get("target_name") or target_slug.replace("_", " "),
        "target_slug": target_slug,
        "session_date": session_date,
        "observer_code": result.get("observer_code"),
        "chart_id": result.get("chart_id"),
        "observation_count": result.get("observation_count"),
        "median_mag": result.get("median_mag"),
        "anomaly_level": (result.get("anomaly") or {}).get("level") if result.get("anomaly") else None,
        "submitted_at": result.get("submitted_at"),
        "created_at": record.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "observations": result.get("observations") or [],
    }
