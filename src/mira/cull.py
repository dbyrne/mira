"""Cull cloud-affected / low-quality subs from a captures dir.

Reads NINA's `/image-history` for per-frame **HFR** and **Stars** stats,
computes per-session medians, and flags frames where stars fall below
`min_stars_frac * median(stars)` or HFR exceeds `max_hfr_frac * median(HFR)`.
Flagged frames move to `<lights_dir>/_rejected/` so they're out of the
way of `mira stack` but recoverable.

Why median-relative thresholds instead of absolute cutoffs: per-night
star counts vary wildly with target field (M51's region has dense
background vs. a high-galactic-latitude field), filter, and gain. A
fraction of the session's own median adapts automatically. An absolute
cutoff (e.g., "stars < 30") would either be too lax for a star-rich
field or wrongly cull a sparse field's perfectly-good frames.

Limitation: NINA's image-history is in-memory and lost on NINA restart.
Run cull while NINA is still up (typically end-of-session, before
`mira stack`). For offline / historical culling we'd need a FITS-based
fallback (compute stars + HFR via photutils); not implemented yet.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Callable

DEFAULT_MIN_STARS_FRAC = 0.5
DEFAULT_MAX_HFR_FRAC = 1.5
REJECTED_SUBDIR = "_rejected"


@dataclass
class FrameStat:
    path: Path
    stars: float | None
    hfr: float | None
    note: str = ""


@dataclass
class CullResult:
    kept: list[FrameStat] = field(default_factory=list)
    rejected: list[FrameStat] = field(default_factory=list)
    unscored: list[FrameStat] = field(default_factory=list)
    median_stars: float | None = None
    median_hfr: float | None = None
    star_floor: float | None = None
    hfr_ceiling: float | None = None
    dry_run: bool = False

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.rejected) + len(self.unscored)


def _index_history_by_filename(history: list[dict]) -> dict[str, dict]:
    """NINA returns Filename as a full path; mira copies the file so the
    full path differs but the basename matches. Key by basename."""
    out: dict[str, dict] = {}
    for entry in history:
        fn = entry.get("Filename") or ""
        if fn:
            out[Path(fn).name] = entry
    return out


def stat_frames(lights_dir: Path, history: list[dict]) -> list[FrameStat]:
    """For each FITS in lights_dir, look up the matching history entry by
    basename. Stars / HFR are None on no-history-match — caller treats
    those as `unscored` (preserved, not culled, since we can't judge
    them)."""
    by_name = _index_history_by_filename(history)
    frames = sorted(p for p in Path(lights_dir).glob("*.fit*") if p.is_file())
    out: list[FrameStat] = []
    for f in frames:
        entry = by_name.get(f.name)
        if entry is None:
            out.append(FrameStat(f, None, None, "no history entry"))
            continue
        stars = entry.get("Stars")
        hfr = entry.get("HFR")
        try:
            stars_f = float(stars) if stars is not None else None
        except (TypeError, ValueError):
            stars_f = None
        try:
            hfr_f = float(hfr) if hfr is not None else None
        except (TypeError, ValueError):
            hfr_f = None
        out.append(FrameStat(f, stars=stars_f, hfr=hfr_f))
    return out


def run_cull(
    lights_dir: Path,
    *,
    history: list[dict] | None = None,
    history_fetcher: Callable[[], list[dict]] | None = None,
    min_stars_frac: float = DEFAULT_MIN_STARS_FRAC,
    max_hfr_frac: float = DEFAULT_MAX_HFR_FRAC,
    dry_run: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> CullResult:
    """Cull cloud-affected / low-quality frames in `lights_dir`. Pass
    `history` directly, or a `history_fetcher` callable (typically
    `client.image_history`). Moves rejected frames to
    `<lights_dir>/_rejected/` unless `dry_run`."""
    def emit(m: str) -> None:
        if on_step is not None:
            on_step(m)

    if history is None:
        if history_fetcher is None:
            raise ValueError("must pass either `history` or `history_fetcher`")
        history = history_fetcher()

    lights_dir = Path(lights_dir)
    stats = stat_frames(lights_dir, history)
    result = CullResult(dry_run=dry_run)

    # Frames with both metrics available are scored; the rest stay put.
    scored = [s for s in stats if s.stars is not None and s.hfr is not None]
    if not scored:
        emit(f"no scorable frames in {lights_dir} "
             f"({len(stats)} FITS, 0 matched against NINA image-history). "
             "Is NINA still running? cull is a no-op.")
        result.unscored = stats
        return result

    med_stars = median(s.stars for s in scored)
    med_hfr = median(s.hfr for s in scored)
    star_floor = min_stars_frac * med_stars
    hfr_ceiling = max_hfr_frac * med_hfr
    result.median_stars = med_stars
    result.median_hfr = med_hfr
    result.star_floor = star_floor
    result.hfr_ceiling = hfr_ceiling

    emit(f"scored {len(scored)}/{len(stats)} frames; "
         f"median stars={med_stars:.0f}, median HFR={med_hfr:.2f}")
    emit(f"thresholds: keep stars >= {star_floor:.0f}, HFR <= {hfr_ceiling:.2f}")

    for s in stats:
        if s.stars is None or s.hfr is None:
            result.unscored.append(s)
            continue
        if s.stars < star_floor or s.hfr > hfr_ceiling:
            result.rejected.append(s)
        else:
            result.kept.append(s)

    if result.rejected and not dry_run:
        rejected_dir = lights_dir / REJECTED_SUBDIR
        rejected_dir.mkdir(exist_ok=True)
        for s in result.rejected:
            try:
                shutil.move(str(s.path), str(rejected_dir / s.path.name))
            except OSError as exc:
                emit(f"  failed to move {s.path.name}: {exc}")

    return result
