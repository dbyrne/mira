"""Capture-data inventory (``mira inventory``).

Walks every session dir under a captures root (one level, same contract as
the DSO ledger) and answers the question the ledger can't: "what raw data do
we actually have, on every target, from every rig — and where did it end up?"

Read-only by design: legacy dirs without a ``mira_capture.json`` sidecar are
*reported* (facts recovered from FITS headers + the dir name), never
backfilled — a fabricated sidecar could feed ``--auto-flats`` a guessed
filter, which is exactly the silent-miscalibration class of bug the sidecar
system exists to prevent.

Outputs a Markdown report + CSV (default ``output/inventory/``) linking each
session to its ``output/processed/<target>/`` directory when one exists.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

CAPTURE_SIDECAR = "mira_capture.json"
REJECTED_SUBDIR = "_rejected"
_DATE_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)_(?P<date>\d{8})$")

# Sensor frame dimensions → rig. Either orientation; binned dims would not
# match and fall through to "?" (honest, not guessed).
_RIG_BY_DIMS = {
    (3840, 2160): "S30 Pro",
    (6248, 4176): "ASI2600MM (Esprit 80/120)",
}


@dataclass(frozen=True)
class SessionInventory:
    dir_name: str
    target: str                 # sidecar target_name, else dirname stem
    date: str                   # YYYYMMDD from dirname, else DATE-OBS, else ""
    rig: str                    # inferred from frame dims, "?" if unknown
    filter_name: str            # sidecar filter, "?" for legacy dirs
    gain: int | None
    exposure_s: float | None    # sidecar exposure_s, else median FITS EXPTIME
    frames: int                 # top-level *.fit* count
    rejected: int               # frames parked in _rejected/ by mira cull
    solved: int                 # frames carrying a WCS (CRVAL1)
    size_gb: float
    has_sidecar: bool
    processed: str              # output/processed/<slug> when it exists, else ""

    @property
    def total_minutes(self) -> float:
        if not self.exposure_s:
            return 0.0
        return self.frames * self.exposure_s / 60.0


def infer_rig(nx: int | None, ny: int | None) -> str:
    if not nx or not ny:
        return "?"
    return _RIG_BY_DIMS.get((nx, ny)) or _RIG_BY_DIMS.get((ny, nx)) or "?"


def target_slug(name: str) -> str:
    """'NGC 6888' -> 'ngc6888'; matches the processed/<target> convention."""
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", ""))


def split_dirname(dir_name: str) -> tuple[str, str]:
    """'m51_20260517' -> ('m51', '20260517'); no date suffix -> (name, '')."""
    m = _DATE_SUFFIX_RE.match(dir_name)
    if m:
        return m.group("stem"), m.group("date")
    return dir_name, ""


def _read_sidecar(session_dir: Path) -> dict:
    path = session_dir / CAPTURE_SIDECAR
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _scan_fits(session_dir: Path) -> tuple[int, int, list[float], str,
                                           tuple[int | None, int | None]]:
    """(frame count, solved count, exptimes, first DATE-OBS yyyymmdd, dims).

    Header-only reads; a corrupt FITS still counts as a frame (it exists on
    disk) but contributes nothing else.
    """
    from astropy.io import fits as afits

    frames = solved = 0
    exptimes: list[float] = []
    date_obs = ""
    dims: tuple[int | None, int | None] = (None, None)
    for f in sorted(session_dir.glob("*.fit*")):
        if not f.is_file():
            continue
        frames += 1
        try:
            hdr = afits.getheader(f, 0)
        except Exception:
            continue
        if "CRVAL1" in hdr:
            solved += 1
        try:
            exp = float(hdr.get("EXPTIME") or hdr.get("EXPOSURE") or 0.0)
            if exp > 0:
                exptimes.append(exp)
        except (TypeError, ValueError):
            pass
        if not date_obs and hdr.get("DATE-OBS"):
            date_obs = str(hdr["DATE-OBS"])[:10].replace("-", "")
        if dims == (None, None):
            try:
                dims = (int(hdr.get("NAXIS1") or 0) or None,
                        int(hdr.get("NAXIS2") or 0) or None)
            except (TypeError, ValueError):
                pass
    return frames, solved, exptimes, date_obs, dims


def inventory_session(session_dir: Path, processed_root: Path) -> SessionInventory:
    sidecar = _read_sidecar(session_dir)
    frames, solved, exptimes, date_obs, dims = _scan_fits(session_dir)

    stem, dir_date = split_dirname(session_dir.name)
    target = str(sidecar.get("target_name") or "").strip() or stem

    filter_name = str(sidecar.get("filter") or "").strip() or "?"
    try:
        gain: int | None = int(sidecar["gain"]) if sidecar.get("gain") is not None else None
    except (KeyError, TypeError, ValueError):
        gain = None

    exposure: float | None = None
    try:
        exposure = float(sidecar.get("exposure_s") or 0.0) or None
    except (TypeError, ValueError):
        exposure = None
    if exposure is None and exptimes:
        exposure = sorted(exptimes)[len(exptimes) // 2]   # median-ish

    rejected_dir = session_dir / REJECTED_SUBDIR
    rejected = (
        sum(1 for p in rejected_dir.glob("*.fit*") if p.is_file())
        if rejected_dir.is_dir() else 0
    )

    # Per-file guard: one dangling symlink or locked temp file (Syncthing
    # mid-transfer, OneDrive placeholder) must not abort the whole inventory.
    size_bytes = 0
    for p in session_dir.rglob("*"):
        try:
            if p.is_file():
                size_bytes += p.stat().st_size
        except OSError:
            continue

    slug = target_slug(target)
    processed = ""
    if slug and (processed_root / slug).is_dir():
        processed = str(processed_root / slug)

    return SessionInventory(
        dir_name=session_dir.name,
        target=target,
        date=dir_date or date_obs,
        rig=infer_rig(*dims),
        filter_name=filter_name,
        gain=gain,
        exposure_s=exposure,
        frames=frames,
        rejected=rejected,
        solved=solved,
        size_gb=round(size_bytes / 1024**3, 2),
        has_sidecar=bool(sidecar),
        processed=processed,
    )


def build_inventory(
    captures_root: Path,
    processed_root: Path = Path("output/processed"),
) -> list[SessionInventory]:
    root = Path(captures_root)
    if not root.is_dir():
        return []
    return [
        inventory_session(d, Path(processed_root))
        for d in sorted(root.iterdir())
        if d.is_dir()
    ]


def write_inventory(
    sessions: list[SessionInventory],
    out_dir: Path,
    captures_root: Path,
) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "captures_inventory.md"
    csv_path = out / "captures_inventory.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dir", "target", "date", "rig", "filter", "gain",
                    "exposure_s", "frames", "rejected", "solved",
                    "total_minutes", "size_gb", "sidecar", "processed"])
        for s in sessions:
            w.writerow([s.dir_name, s.target, s.date, s.rig, s.filter_name,
                        s.gain if s.gain is not None else "",
                        s.exposure_s if s.exposure_s is not None else "",
                        s.frames, s.rejected, s.solved,
                        round(s.total_minutes, 1), s.size_gb,
                        "yes" if s.has_sidecar else "",
                        s.processed])

    total_frames = sum(s.frames for s in sessions)
    total_gb = round(sum(s.size_gb for s in sessions), 1)
    total_min = round(sum(s.total_minutes for s in sessions))
    no_sidecar = [s for s in sessions if not s.has_sidecar]
    unprocessed = [s for s in sessions
                   if not s.processed and s.frames > 0]

    lines = [
        "# Captures inventory",
        "",
        f"Generated by `mira inventory` over `{captures_root}` — regenerate "
        "after capture sessions; this file is the committed answer to "
        "“what raw data do we have?”.",
        "",
        f"**{len(sessions)} session dirs · {total_frames} frames · "
        f"~{total_min} min integration · {total_gb} GB**",
        "",
        "| Session | Target | Rig | Filter | Gain | Exp | Frames (rej.) | Solved | Integration | GB | Processed |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sessions:
        exp = f"{s.exposure_s:g}s" if s.exposure_s else "?"
        rej = f" ({s.rejected})" if s.rejected else ""
        proc = f"`{Path(s.processed).name}`" if s.processed else "—"
        sidecar_mark = "" if s.has_sidecar else " ⚠"
        lines.append(
            f"| {s.dir_name}{sidecar_mark} | {s.target} | {s.rig} | "
            f"{s.filter_name} | {s.gain if s.gain is not None else '?'} | {exp} | "
            f"{s.frames}{rej} | {s.solved}/{s.frames} | "
            f"{round(s.total_minutes)}m | {s.size_gb} | {proc} |"
        )
    lines.append("")
    if no_sidecar:
        lines += [
            "## Sessions without a sidecar (⚠ legacy — filter unknowable from FITS)",
            "",
            *[f"- `{s.dir_name}` — facts above recovered from FITS headers/"
              "dirname; `--auto-flats` cannot resolve a master for these"
              for s in no_sidecar],
            "",
        ]
    if unprocessed:
        lines += [
            "## Captured but no processed/ output",
            "",
            *[f"- `{s.dir_name}` → no `output/processed/{target_slug(s.target)}/`"
              for s in unprocessed],
            "",
        ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, csv_path
