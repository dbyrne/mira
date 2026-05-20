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
DEFAULT_MAX_SKY_FRAC = 2.0          # sky_median > 2x session median => clouds/moon
DEFAULT_MAX_ROUND_FRAC = 2.0        # |roundness| > 2x median => trailing
DEFAULT_CENTRAL_FRAC = 0.3          # central 30% box when no WCS
REJECTED_SUBDIR = "_rejected"


@dataclass
class FrameStat:
    path: Path
    stars: float | None
    hfr: float | None
    note: str = ""
    # Optional FITS-pixel-derived metrics (filled by run_cull(from_fits=True);
    # left None on the NINA-history path — existing callers don't see them).
    sky_median: float | None = None
    sky_sigma: float | None = None
    roundness: float | None = None
    has_wcs: bool | None = None


@dataclass
class CullResult:
    kept: list[FrameStat] = field(default_factory=list)
    rejected: list[FrameStat] = field(default_factory=list)
    unscored: list[FrameStat] = field(default_factory=list)
    median_stars: float | None = None
    median_hfr: float | None = None
    star_floor: float | None = None
    hfr_ceiling: float | None = None
    # FITS-mode-only summary fields (None on NINA path).
    median_sky: float | None = None
    median_round: float | None = None
    sky_ceiling: float | None = None
    round_ceiling: float | None = None
    solve_failed: list[FrameStat] = field(default_factory=list)
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
    max_sky_frac: float = DEFAULT_MAX_SKY_FRAC,
    max_round_frac: float = DEFAULT_MAX_ROUND_FRAC,
    from_fits: bool = False,
    target_ra: float | None = None,
    target_dec: float | None = None,
    central_frac: float = DEFAULT_CENTRAL_FRAC,
    dry_run: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> CullResult:
    """Cull cloud-affected / low-quality frames in `lights_dir`.

    Two modes:

    * **NINA-history (default):** pass `history` directly or
      `history_fetcher` (typically `client.image_history`). Uses NINA's
      in-memory Stars + HFR per frame. Fast, but requires NINA still
      running with this session loaded.
    * **FITS-pixel (`from_fits=True`):** read FITS pixels directly via
      astropy + photutils. No NINA dependency; works offline / on
      historical data / across machines. Adds two metrics NINA does not
      provide — *target-region sky_median* (WCS-based when present,
      central-box otherwise) and star *roundness* (trailing detection).
      If some frames in the dir carry a WCS and some don't (a solve pass
      was clearly run), the unsolved ones go to `solve_failed` — a
      strong quality signal in its own right.

    Rejected frames move to `<lights_dir>/_rejected/` unless `dry_run`.
    """
    def emit(m: str) -> None:
        if on_step is not None:
            on_step(m)

    if from_fits:
        return _run_cull_fits(
            Path(lights_dir),
            min_stars_frac=min_stars_frac, max_hfr_frac=max_hfr_frac,
            max_sky_frac=max_sky_frac, max_round_frac=max_round_frac,
            target_ra=target_ra, target_dec=target_dec,
            central_frac=central_frac, dry_run=dry_run, emit=emit,
        )

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


def _run_cull_fits(
    lights_dir: Path, *,
    min_stars_frac: float, max_hfr_frac: float,
    max_sky_frac: float, max_round_frac: float,
    target_ra: float | None, target_dec: float | None,
    central_frac: float, dry_run: bool,
    emit: Callable[[str], None],
) -> CullResult:
    """FITS-pixel cull (no NINA). See run_cull docstring."""
    from .fits_stats import compute_frame_quality  # lazy: astropy + photutils

    frames = sorted(p for p in lights_dir.glob("*.fit*") if p.is_file())
    result = CullResult(dry_run=dry_run)
    if not frames:
        emit(f"no FITS files in {lights_dir}; cull is a no-op.")
        return result

    emit(f"scoring {len(frames)} frames from FITS pixels...")
    stats: list[FrameStat] = []
    for i, p in enumerate(frames, 1):
        q = compute_frame_quality(
            p, target_ra=target_ra, target_dec=target_dec,
            central_frac=central_frac,
        )
        stats.append(FrameStat(
            path=p, stars=q.stars, hfr=q.hfr, note=q.note,
            sky_median=q.sky_median, sky_sigma=q.sky_sigma,
            roundness=q.roundness, has_wcs=q.has_wcs,
        ))
        if i == 1 or i % 50 == 0 or i == len(frames):
            emit(f"  {i}/{len(frames)} scored")

    # Mixed-WCS: a solve pass clearly ran in this dir if SOME frames have
    # a WCS. The ones that don't almost certainly failed to solve (clouds
    # / trailing / defocus / no stars) — a hard-fail signal that costs
    # nothing to detect.
    any_wcs = any(s.has_wcs for s in stats)
    if any_wcs:
        for s in stats:
            if not s.has_wcs:
                s.note = (s.note + "; " if s.note else "") + "no WCS (solve failed)"
                result.solve_failed.append(s)
                result.rejected.append(s)
        emit(f"  solve-failed bucket: {len(result.solve_failed)} frame(s) "
             f"have no WCS in a mostly-solved dir")

    # Score the survivors of the WCS gate (or all frames if the dir was
    # never solved). Need stars and hfr to be defined — frames with "no
    # stars detected" land in unscored (and we have already rejected the
    # no-WCS ones; if not solved at all, no-stars is unscored=preserve,
    # matching the existing no-history semantics).
    scoreable = [
        s for s in stats
        if s not in result.solve_failed
        and s.stars is not None and s.hfr is not None
    ]
    if not scoreable:
        for s in stats:
            if s not in result.solve_failed:
                result.unscored.append(s)
        emit("no scorable frames (all unsolvable / starless); cull preserves them.")
        return result

    med_stars = median(s.stars for s in scoreable)
    med_hfr = median(s.hfr for s in scoreable)
    sky_vals = [s.sky_median for s in scoreable if s.sky_median is not None]
    round_vals = [s.roundness for s in scoreable if s.roundness is not None]
    med_sky = median(sky_vals) if sky_vals else None
    med_round = median(round_vals) if round_vals else None

    star_floor = min_stars_frac * med_stars
    hfr_ceiling = max_hfr_frac * med_hfr
    sky_ceiling = max_sky_frac * med_sky if med_sky is not None else None
    round_ceiling = max_round_frac * med_round if med_round is not None else None
    result.median_stars = med_stars
    result.median_hfr = med_hfr
    result.median_sky = med_sky
    result.median_round = med_round
    result.star_floor = star_floor
    result.hfr_ceiling = hfr_ceiling
    result.sky_ceiling = sky_ceiling
    result.round_ceiling = round_ceiling

    emit(f"medians: stars={med_stars:.0f} HFR={med_hfr:.2f}"
         + (f" sky={med_sky:.0f}" if med_sky is not None else "")
         + (f" round={med_round:.3f}" if med_round is not None else ""))
    emit(f"keep if: stars >= {star_floor:.0f}, HFR <= {hfr_ceiling:.2f}"
         + (f", sky <= {sky_ceiling:.0f}" if sky_ceiling is not None else "")
         + (f", round <= {round_ceiling:.3f}" if round_ceiling is not None else ""))

    for s in stats:
        if s in result.solve_failed:
            continue
        if s.stars is None or s.hfr is None:
            result.unscored.append(s)
            continue
        reasons: list[str] = []
        if s.stars < star_floor:
            reasons.append(f"stars={s.stars:.0f}<{star_floor:.0f}")
        if s.hfr > hfr_ceiling:
            reasons.append(f"HFR={s.hfr:.2f}>{hfr_ceiling:.2f}")
        if (sky_ceiling is not None and s.sky_median is not None
                and s.sky_median > sky_ceiling):
            reasons.append(f"sky={s.sky_median:.0f}>{sky_ceiling:.0f}")
        if (round_ceiling is not None and s.roundness is not None
                and s.roundness > round_ceiling):
            reasons.append(f"round={s.roundness:.3f}>{round_ceiling:.3f}")
        if reasons:
            s.note = (s.note + "; " if s.note else "") + ", ".join(reasons)
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
