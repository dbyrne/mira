"""Path / discovery / run-kind helpers shared across the webapp routes.

Conventions in one place so route handlers can stay focused on HTTP:
- A "session" is a (target_slug, YYYY-MM-DD) pair (or (slug, None) for
  the legacy flat layout where FITS live directly under <slug>/).
- The run-record kind for photometry is ``submit:<slug>[:<date>]``.
- ``_request_date()`` reads the current Flask request for a date marker
  (query string or form), so callers don't need to remember which.
"""
from __future__ import annotations

from pathlib import Path

from flask import request


def looks_like_date(name: str) -> bool:
    """YYYY-MM-DD format check for capture-session subdirectories."""
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    return name[:4].isdigit() and name[5:7].isdigit() and name[8:10].isdigit()


def request_date() -> str | None:
    """Pull a YYYY-MM-DD session marker from the current request (query
    string for GET, form for POST). Returns None if absent or malformed."""
    candidate = (request.args.get("date") or request.form.get("date") or "").strip()
    if candidate and looks_like_date(candidate):
        return candidate
    return None


def resolved_session_date(target_dir: Path | None) -> str | None:
    """Convert a captures dir to its YYYY-MM-DD session label, or None for
    flat layouts."""
    if target_dir is None:
        return None
    if looks_like_date(target_dir.name):
        return target_dir.name
    return None


def submit_kind(target_slug: str, date: str | None = None) -> str:
    """Run-record kind. Dated sessions get a separate kind so each
    (target, date) tuple has its own latest-run pointer."""
    if date:
        return f"submit:{target_slug}:{date}"
    return f"submit:{target_slug}"


def dir_to_target_name(target_dir: Path) -> str:
    """Convert a directory name like 'RR_LYR' into a VSX-style target name 'RR LYR'."""
    return target_dir.name.replace("_", " ")


def default_comp_stars_path(target_dir: Path) -> str:
    """Suggest the path where a comp-stars JSON would live."""
    return str(target_dir / "comp_stars.json")


def list_capture_sessions(target_dir: Path) -> list[dict]:
    """Return one entry per dated subdir of `target_dir` containing FITS,
    plus the flat layout (a single entry with date=None) if FITS sit
    directly in target_dir. Sorted oldest → newest."""
    sessions: list[dict] = []
    try:
        children = list(target_dir.iterdir())
    except OSError:
        return sessions
    has_dated = False
    for entry in sorted(children):
        if entry.is_dir() and looks_like_date(entry.name):
            fits = list(entry.glob("*.fits")) + list(entry.glob("*.fit"))
            if fits:
                has_dated = True
                sessions.append({
                    "date": entry.name,
                    "path": entry,
                    "fits_count": len(fits),
                    "modified": max(f.stat().st_mtime for f in fits),
                    "upload_exists": any(entry.glob("aavso_*.txt")),
                })
    if not has_dated:
        flat_fits = list(target_dir.glob("*.fits")) + list(target_dir.glob("*.fit"))
        if flat_fits:
            sessions.append({
                "date": None,
                "path": target_dir,
                "fits_count": len(flat_fits),
                "modified": max(f.stat().st_mtime for f in flat_fits),
                "upload_exists": any(target_dir.glob("aavso_*.txt")),
            })
    return sessions


def resolve_target_dir(captures_root: Path, slug: str, date: str | None = None) -> Path | None:
    """Map a URL slug + optional date to the captures dir we should process.

    - If `date` is given (YYYY-MM-DD), returns captures_root/<slug>/<date>/
      when that subdir exists, else None.
    - If `date` is None: when the target has dated subdirs, returns the
      most-recent one. When the layout is flat (FITS at <slug>/), returns
      the flat dir. Returns None if neither.

    Defensive against path traversal: only resolves children of
    captures_root."""
    if not captures_root.exists():
        return None
    candidate = captures_root / slug
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.is_dir():
        return None
    if captures_root.resolve() not in resolved.parents and resolved != captures_root.resolve():
        return None

    if date:
        if not looks_like_date(date):
            return None
        dated = resolved / date
        if not dated.is_dir():
            return None
        return dated

    sessions = list_capture_sessions(resolved)
    if not sessions:
        return resolved if resolved.is_dir() else None
    return sessions[-1]["path"]


def resolve_scheduled_target_dir(captures_root: Path, target_name: str) -> Path | None:
    """Case-insensitive directory match for a scheduled target. Tries
    `target_name.replace(" ", "_")` against each subdir of captures_root,
    matching either case."""
    if not captures_root.exists():
        return None
    needle = target_name.replace(" ", "_").lower()
    try:
        for entry in captures_root.iterdir():
            if entry.is_dir() and entry.name.lower() == needle:
                return entry
    except OSError:
        return None
    return None


def resolve_stage(fits_count: int, run) -> str:
    """Stage rolls up to one of: awaiting / captured / running / processed /
    submitted / failed."""
    if fits_count == 0:
        return "awaiting"
    if run is None:
        return "captured"
    if run.status == "running":
        return "running"
    if run.status == "failed":
        return "failed"
    if run.status == "done":
        if run.result and run.result.get("submitted_at"):
            return "submitted"
        return "processed"
    return "captured"


def discover_capture_targets(captures_root: Path) -> list[dict]:
    """One entry per (target, date) capture session. Walks both layouts:

    - Dated:  captures/<TARGET>/<YYYY-MM-DD>/*.fits
    - Flat:   captures/<TARGET>/*.fits          (date=None)

    A target with multiple dated subdirs becomes multiple rows. Sorted
    most-recent first by mtime."""
    if not captures_root.exists():
        return []
    targets = []
    for entry in sorted(captures_root.iterdir()):
        if not entry.is_dir():
            continue
        sessions = list_capture_sessions(entry)
        for session in sessions:
            targets.append(
                {
                    "slug": entry.name,
                    "date": session["date"],
                    "name": dir_to_target_name(entry),
                    "fits_count": session["fits_count"],
                    "path": session["path"],
                    "modified": session["modified"],
                    "upload_exists": session["upload_exists"],
                }
            )
    targets.sort(key=lambda d: d["modified"], reverse=True)
    return targets


def build_schedule_status(
    schedule_csv: Path,
    captures_root: Path,
    runs_by_kind: dict,
) -> list[dict]:
    """Read tonight's schedule CSV and join it with on-disk captures + run
    records so the photometry index can show "what tonight's plan called for
    and where each target stands." Returns [] if no schedule has been
    generated yet."""
    if not schedule_csv.exists():
        return []
    import csv as _csv

    out: list[dict] = []
    with schedule_csv.open(encoding="utf-8") as handle:
        reader = _csv.DictReader(handle)
        for row in reader:
            target_name = row.get("name", "").strip()
            if not target_name:
                continue
            target_root = resolve_scheduled_target_dir(captures_root, target_name)
            slug = target_root.name if target_root else target_name.replace(" ", "_")

            session_date: str | None = None
            fits_count = 0
            if target_root:
                sessions = list_capture_sessions(target_root)
                if sessions:
                    latest = sessions[-1]
                    session_date = latest["date"]
                    fits_count = latest["fits_count"]

            run = runs_by_kind.get(submit_kind(slug, session_date))
            stage = resolve_stage(fits_count, run)
            anomaly_level = None
            observation_count = None
            if run and run.result:
                anomaly_level = (run.result.get("anomaly") or {}).get("level")
                observation_count = run.result.get("observation_count")
            out.append(
                {
                    "order": int(row.get("order") or 0),
                    "start_local": row.get("start_local", ""),
                    "end_local": row.get("end_local", ""),
                    "name": target_name,
                    "slug": slug,
                    "session_date": session_date,
                    "has_dir": target_root is not None,
                    "fits_count": fits_count,
                    "frames_planned": int(row.get("frame_count") or 0),
                    "exposure_seconds": int(row.get("exposure_seconds") or 0),
                    "stage": stage,
                    "anomaly_level": anomaly_level,
                    "observation_count": observation_count,
                }
            )
    out.sort(key=lambda r: r["order"])
    return out


def read_overflow_targets(overflow_csv: Path) -> list[dict]:
    """Read the overflow CSV (deferred candidates) for the photometry index.
    Returns [] if the file doesn't exist yet (no schedule run, or no overflow)."""
    if not overflow_csv.exists():
        return []
    import csv as _csv

    out: list[dict] = []
    try:
        with overflow_csv.open(encoding="utf-8") as handle:
            for row in _csv.DictReader(handle):
                name = row.get("name", "").strip()
                if not name:
                    continue
                out.append(
                    {
                        "name": name,
                        "var_type": row.get("var_type", "") or "—",
                        "bright_mag": row.get("bright_mag", "") or "—",
                        "best_local_time": row.get("best_local_time", "") or "—",
                        "score": row.get("score", "") or "—",
                    }
                )
    except OSError:
        return []
    return out
