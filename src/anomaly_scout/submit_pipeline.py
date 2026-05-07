"""Shared photometry orchestration: resolve comps → preflight FITS →
process each frame → flag outliers. Both `anomaly-scout submit` (CLI)
and the webapp's photometry route call into this module so the math
and the I/O contract are identical.

What's *not* in here:
- VSX target lookup (the caller already has ra/dec).
- Anomaly assessment, plot generation, DB persistence — those are
  webapp concerns layered on top.
- AAVSO Extended File writing — `photometry.write_aavso_extended_file`
  is fine where it is.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .photometry import CompStar, Observation, process_capture, read_fits_with_wcs


@dataclass
class CompResolution:
    """Outcome of choosing comp stars for a session.

    `source` is one of "vsp" (auto-fetched), "json" (loaded from a path),
    or "vsp-fallback" (VSP returned comps but none within ±2 mag of the
    target, so we kept the brightest 6). `chart_total` is the unfiltered
    VSP comp count when `source` starts with "vsp", else the same as
    len(comps).
    """
    comps: list[CompStar]
    chart_id: str
    source: str
    chart_total: int


@dataclass
class FrameRecord:
    """Per-frame outcome surfaced both in CLI output and the live UI."""
    filename: str
    julian_date: float | None = None
    magnitude: float | None = None
    magnitude_error: float | None = None
    band: str = ""
    comp_label: str = ""
    comp_mag: float | None = None
    chart_id: str = ""
    flag: str = "pending"  # "ok" | "outlier" | "failed" | "no-signal" | "pending"
    note: str = ""
    skipped_comps: tuple[str, ...] = ()


@dataclass
class PhotometryRunResult:
    """End-of-loop outcome. Frames is one entry per FITS (including
    failures); observations is the subset that produced an Observation."""
    frames: list[FrameRecord] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    median_mag: float | None = None
    failures: list[tuple[str, str]] = field(default_factory=list)


def resolve_comps(
    target_name: str,
    target_bright_mag: float | None,
    comp_path: Path | None,
    chart_id_override: str = "na",
) -> CompResolution:
    """Either load a hand-curated comp JSON from `comp_path`, or auto-fetch
    from AAVSO VSP for the target name. Raises RuntimeError if VSP is
    unreachable and no JSON path was given."""
    if comp_path is not None:
        with comp_path.open(encoding="utf-8") as handle:
            comp_data = _json.load(handle)
        comps = [
            CompStar(
                label=str(item["label"]),
                ra_deg=float(item["ra_deg"]),
                dec_deg=float(item["dec_deg"]),
                catalog_mag=float(item["catalog_mag"]),
                catalog_band=str(item.get("catalog_band", "V")),
            )
            for item in comp_data
        ]
        return CompResolution(
            comps=comps,
            chart_id=chart_id_override or "na",
            source="json",
            chart_total=len(comps),
        )

    # Auto-fetch path. Imported lazily to keep CLI startup snappy when a
    # JSON path is provided.
    from .vsp import fetch_vsp_chart, filter_comps_for_target

    chart = fetch_vsp_chart(target_name)
    selected = filter_comps_for_target(chart.comps, target_bright_mag)
    if selected:
        source = "vsp"
        comps = selected
    else:
        source = "vsp-fallback"
        comps = chart.comps[:6]
    chart_id = chart.chart_id if (not chart_id_override or chart_id_override == "na") else chart_id_override
    return CompResolution(
        comps=comps,
        chart_id=chart_id,
        source=source,
        chart_total=len(chart.comps),
    )


def preflight_fits_dir(target_dir: Path) -> list[Path]:
    """Discover FITS files in `target_dir` and verify the first frame has
    a celestial WCS. Raises ValueError if there are no FITS files or the
    first frame fails the WCS check (caller's error message preferred,
    so we re-raise the read_fits_with_wcs message verbatim)."""
    fits_files = sorted(list(target_dir.glob("*.fits")) + list(target_dir.glob("*.fit")))
    if not fits_files:
        raise ValueError(f"No FITS files found in {target_dir}")
    # Will raise ValueError with a clear message if the first frame is
    # missing a WCS. Cheaper than running the photometry loop just to fail
    # on every frame for the same reason.
    read_fits_with_wcs(fits_files[0])
    return fits_files


def run_photometry_loop(
    target_name: str,
    target_ra_deg: float,
    target_dec_deg: float,
    fits_files: list[Path],
    comps: list[CompStar],
    chart_id: str,
    *,
    aperture_arcsec: float = 6.0,
    on_frame: Callable[[FrameRecord], None] | None = None,
) -> PhotometryRunResult:
    """Run process_capture for each FITS, build FrameRecord/Observation
    outputs, flag MAD-based outliers. `on_frame` is called after every
    FITS, including failures, so callers can stream updates."""
    result = PhotometryRunResult()
    for path in fits_files:
        skipped: list[str] = []

        def _capture_skip(comp, reason: str, _skipped=skipped) -> None:
            _skipped.append(f"{comp.label}: {reason}")

        try:
            obs = process_capture(
                path,
                target_name,
                target_ra_deg,
                target_dec_deg,
                comps,
                aperture_radius_arcsec=aperture_arcsec,
                on_comp_skipped=_capture_skip,
            )
        except Exception as exc:
            result.failures.append((path.name, str(exc)))
            frame = FrameRecord(
                filename=path.name,
                flag="failed",
                note=str(exc),
                skipped_comps=tuple(skipped),
            )
            result.frames.append(frame)
            if on_frame is not None:
                on_frame(frame)
            continue

        if obs is None:
            result.failures.append((path.name, "no usable signal"))
            frame = FrameRecord(
                filename=path.name,
                flag="no-signal",
                note="no usable signal",
                skipped_comps=tuple(skipped),
            )
            result.frames.append(frame)
            if on_frame is not None:
                on_frame(frame)
            continue

        obs.chart_id = chart_id
        result.observations.append(obs)
        frame = FrameRecord(
            filename=path.name,
            julian_date=obs.julian_date,
            magnitude=obs.magnitude,
            magnitude_error=obs.magnitude_error,
            band=obs.band,
            comp_label=obs.comp_star_label,
            comp_mag=obs.comp_star_mag,
            chart_id=chart_id,
            flag="pending",  # filled to ok/outlier after the loop
            skipped_comps=tuple(skipped),
        )
        result.frames.append(frame)
        if on_frame is not None:
            on_frame(frame)

    flag_outliers(result)
    if result.observations:
        mags = sorted(o.magnitude for o in result.observations)
        result.median_mag = mags[len(mags) // 2]
    return result


def flag_outliers(result: PhotometryRunResult) -> None:
    """Mutate `result.frames` so any pending frame whose magnitude is more
    than 3*1.4826*MAD from the median is flagged as an outlier; the rest
    become 'ok'. With fewer than 5 observations, MAD isn't meaningful, so
    everything pending becomes 'ok'."""
    # Materialize as (frame, magnitude) so mypy can see the magnitude is
    # narrowed to float (not float | None) for the math below.
    pending: list[tuple[FrameRecord, float]] = [
        (f, f.magnitude)
        for f in result.frames
        if f.flag == "pending" and f.magnitude is not None
    ]
    if not pending:
        return
    mags = sorted(m for _, m in pending)
    median = mags[len(mags) // 2]
    if len(mags) < 5:
        for f, _ in pending:
            f.flag = "ok"
        return
    deviations = sorted(abs(m - median) for m in mags)
    mad = deviations[len(deviations) // 2]
    sigma = mad * 1.4826
    for f, mag in pending:
        if sigma > 0 and abs(mag - median) > 3 * sigma:
            f.flag = "outlier"
        else:
            f.flag = "ok"


def frame_to_dict(frame: FrameRecord) -> dict:
    """JSON-serializable view of a FrameRecord. Used when frames need to
    live inside `RunRecord.result` (which is dict-typed)."""
    return {
        "filename": frame.filename,
        "jd": frame.julian_date,
        "magnitude": frame.magnitude,
        "magnitude_error": frame.magnitude_error,
        "comp_label": frame.comp_label,
        "flag": frame.flag,
        "note": frame.note,
    }


def observation_to_dict(obs: Observation, chart_id: str) -> dict:
    """JSON-serializable view used by run records and the SQLite store."""
    return {
        "filename": "",  # caller fills in from the FrameRecord
        "target_name": obs.target_name,
        "julian_date": obs.julian_date,
        "magnitude": obs.magnitude,
        "magnitude_error": obs.magnitude_error,
        "band": obs.band,
        "comp_star_label": obs.comp_star_label,
        "comp_star_mag": obs.comp_star_mag,
        "chart_id": chart_id,
    }


