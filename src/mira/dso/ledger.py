"""Multi-night integration ledger.

Aggregates ``mira_capture.json`` sidecars under a captures root into
per-target / per-filter totals so the DSO planner can rank by deficit
("which target is farthest from its budget") rather than just by
observability ("what's high in the sky tonight").

The ledger is purely derived state — recomputed from disk on every
invocation, never cached. The sidecars *are* the database: no separate
file to keep in sync, no cache-invalidation bugs.

Matching rule (per user decision): canonical catalog names only. A
session whose ``target_name`` doesn't match any ``DsoCatalog.by_name(...)``
entry is bucketed into ``Ledger.orphan_target_names`` so typos surface
in ``mira dso status``.

Edge cases handled:
- Sidecar with no ``result`` block (capture killed before shutdown) →
  fall back to globbing ``*.fit*`` files in the dir for the frame count.
- Sidecar with empty ``filter`` field → variable-star capture, skipped.
- Sidecar with malformed JSON → logged-warning level skip, walk continues.
- Multiple sessions for same (target, filter) → summed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .catalog import DsoCatalog, DsoTarget


# Filename of the capture sidecar. Duplicated from flats.py / solve.py /
# photometry.py — same as the rest of the codebase, kept inline to avoid
# pulling those modules into this one. If you ever rename, grep the repo.
CAPTURE_SIDECAR = "mira_capture.json"


@dataclass(frozen=True)
class SessionRecord:
    """One parsed sidecar — a single capture session's contribution."""
    sidecar_path: Path
    target_name: str
    filter_name: str
    gain: int | None
    exposure_s: float
    frames_copied: int
    started_utc: datetime | None
    ended_utc: datetime | None
    stopped_reason: str
    frame_count_source: str   # "result.copied" | "globbed" | "fallback_zero"

    @property
    def integration_minutes(self) -> float:
        return (self.frames_copied * self.exposure_s) / 60.0


@dataclass(frozen=True)
class FilterTotal:
    """All sessions for one (target, filter) pair, with aggregates."""
    target_name: str
    filter_name: str
    sessions: tuple[SessionRecord, ...]

    @property
    def total_minutes(self) -> float:
        return sum(s.integration_minutes for s in self.sessions)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    @property
    def last_capture(self) -> datetime | None:
        ends = [s.ended_utc for s in self.sessions if s.ended_utc is not None]
        return max(ends) if ends else None


@dataclass(frozen=True)
class Ledger:
    """Walked-and-aggregated view of all DSO sessions under a captures root.

    ``by_target`` is the canonical lookup: catalog target_name → filter_name
    → FilterTotal. ``orphan_target_names`` lists target_names from sidecars
    that have no catalog match (typos or one-off non-catalog targets).
    """
    sessions: tuple[SessionRecord, ...]
    by_target: dict[str, dict[str, FilterTotal]]
    orphan_target_names: tuple[str, ...]

    def get(self, target_name: str, filter_name: str) -> FilterTotal | None:
        return self.by_target.get(target_name, {}).get(filter_name)

    def minutes(self, target_name: str, filter_name: str) -> float:
        """Convenience: total captured minutes, 0.0 if no sessions."""
        ft = self.get(target_name, filter_name)
        return ft.total_minutes if ft else 0.0


def walk_sidecars(captures_root: Path) -> list[SessionRecord]:
    """Walk ``<captures_root>/**/mira_capture.json`` recursively (sessions
    nest as ``<target>/<rig>_<filter>_<date>/``; underscore-prefixed dirs are
    skipped). Returns parsed SessionRecords.

    Skipped:
    - Sidecars without a filter (VSX-side variable-star captures don't set
      one — those aren't DSO ledger data).
    - Sidecars without a target_name (defensive — shouldn't happen in
      practice but ``mira_capture.json`` is hand-editable).
    - Malformed JSON (best-effort: skip with no aborts so one bad
      sidecar can't tank the whole ledger).

    Frame count resolution order:
    1. ``result.copied`` if the sidecar has a result block.
    2. Glob count of ``*.fit*`` files in the sidecar's directory (rescue
       path for sessions killed before the result block was written).
    3. Zero (sidecar dir is empty or unreadable).
    """
    root = Path(captures_root)
    if not root.is_dir():
        return []
    records: list[SessionRecord] = []
    # Recursive: sessions nest as captures/<target>/<rig>_<filter>_<date>/.
    # Skip any path with an underscore-prefixed component — non-target / derived
    # dirs (_calibration, _planetary, _combined_*, _rejected) whose frames must
    # NOT count (a _combined dir is hardlinks of already-counted sessions, so
    # counting it double-counts the integration).
    for sidecar_path in sorted(root.glob(f"**/{CAPTURE_SIDECAR}")):
        if any(p.startswith("_") for p in sidecar_path.relative_to(root).parts):
            continue
        record = _parse_sidecar(sidecar_path)
        if record is not None:
            records.append(record)
    return records


def aggregate_ledger(
    sessions: Iterable[SessionRecord],
    catalog: DsoCatalog | None = None,
) -> Ledger:
    """Group sessions by (target_name, filter_name). When a catalog is
    provided, target_name is normalized to the catalog's canonical form
    via ``DsoCatalog.by_name`` — sessions captured with a typo or with
    common-name variants go into ``orphan_target_names``."""
    sessions = tuple(sessions)
    grouped: dict[str, dict[str, list[SessionRecord]]] = {}
    orphans: set[str] = set()

    for session in sessions:
        canonical = session.target_name
        if catalog is not None:
            match = catalog.by_name(session.target_name)
            if match is None:
                orphans.add(session.target_name)
                continue
            canonical = match.name
        grouped.setdefault(canonical, {}).setdefault(session.filter_name, []).append(session)

    by_target: dict[str, dict[str, FilterTotal]] = {}
    for target_name, filters in grouped.items():
        by_target[target_name] = {
            f: FilterTotal(
                target_name=target_name,
                filter_name=f,
                sessions=tuple(sess),
            )
            for f, sess in filters.items()
        }

    return Ledger(
        sessions=sessions,
        by_target=by_target,
        orphan_target_names=tuple(sorted(orphans)),
    )


def target_deficit(
    ledger: Ledger, target: DsoTarget,
) -> dict[str, float]:
    """Per-filter remaining minutes for a target. Filters not in the
    target's budget are omitted. Captured > budget → 0 (no negative
    deficits; over-imaging doesn't bank credit toward other filters)."""
    deficits: dict[str, float] = {}
    for filter_name, budget in target.budget_minutes.items():
        captured = ledger.minutes(target.name, filter_name)
        deficits[filter_name] = max(0.0, float(budget) - captured)
    return deficits


def target_completion_fraction(
    ledger: Ledger, target: DsoTarget,
) -> float:
    """Fraction of the target's total budget already captured, clamped
    to [0, 1+]. Returns 0.0 for never-imaged targets, 1.0 when at budget,
    and may exceed 1.0 when over-imaged (caller's choice whether to clamp).

    Used by the planner's deficit-weighted scoring."""
    total_budget = float(target.total_budget_minutes)
    if total_budget <= 0:
        return 0.0
    captured = 0.0
    for filter_name, budget in target.budget_minutes.items():
        # Cap each filter's contribution at its budget so over-imaging Ha
        # doesn't make the target *appear* more complete than it is when
        # OIII / SII are still untouched.
        captured += min(
            float(budget),
            ledger.minutes(target.name, filter_name),
        )
    return captured / total_budget


def _parse_sidecar(path: Path) -> SessionRecord | None:
    """Read one mira_capture.json and return a SessionRecord, or None to
    skip. Tolerant: unreadable / malformed / non-DSO sidecars are skipped
    silently (best-effort aggregation)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    filter_name = str(raw.get("filter") or "").strip()
    if not filter_name:
        # Variable-star capture (no --filter passed). Not DSO data.
        return None

    target_name = str(raw.get("target_name") or "").strip()
    if not target_name:
        return None

    try:
        exposure_s = float(raw.get("exposure_s") or 0.0)
    except (TypeError, ValueError):
        exposure_s = 0.0
    if exposure_s <= 0:
        # Without exposure_s we can't compute integration minutes — skip
        # rather than booking a misleading 0-minute session.
        return None

    gain_raw = raw.get("gain")
    try:
        gain: int | None = int(gain_raw) if gain_raw is not None else None
    except (TypeError, ValueError):
        gain = None

    result = raw.get("result") or {}
    frames_copied, frame_source = _resolve_frame_count(result, path.parent)

    started_utc = _parse_iso(result.get("started_utc"))
    ended_utc = _parse_iso(result.get("ended_utc"))
    stopped_reason = str(result.get("stopped_reason") or "")

    return SessionRecord(
        sidecar_path=path,
        target_name=target_name,
        filter_name=filter_name,
        gain=gain,
        exposure_s=exposure_s,
        frames_copied=frames_copied,
        started_utc=started_utc,
        ended_utc=ended_utc,
        stopped_reason=stopped_reason,
        frame_count_source=frame_source,
    )


def _resolve_frame_count(
    result: dict, session_dir: Path,
) -> tuple[int, str]:
    """Frame count with three-step fallback. Source string is recorded on
    the SessionRecord so ``mira dso status`` can disclose when a count came
    from a glob rescue path rather than the sidecar's own bookkeeping."""
    if isinstance(result, dict) and "copied" in result:
        try:
            return int(result["copied"]), "result.copied"
        except (TypeError, ValueError):
            pass
    # Fall back to globbing the dir — the capture was probably killed
    # before its shutdown handler wrote the result block, but the FITS
    # files made it to disk.
    try:
        fits_files = [
            p for p in session_dir.glob("*.fit*") if p.is_file()
        ]
        if fits_files:
            return len(fits_files), "globbed"
    except OSError:
        pass
    return 0, "fallback_zero"


def _parse_iso(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        # fromisoformat handles the "+00:00" and "Z" suffix in 3.11+.
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
