"""Background-task implementations for the webapp.

Webapp-side wrappers around the shared `tonight_pipeline` and
`submit_pipeline` modules. The route handlers in routes.py kick these
off via RunRegistry; everything network-y, slow, or
plot-generating happens here so the route handlers stay HTTP-shaped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .runs import RunRecord, RunRegistry


class RecordReporter:
    """Adapt RunRecord.log/set_progress onto the *_pipeline.Reporter
    protocol so the webapp can drive the shared pipelines."""

    def __init__(self, record: RunRecord) -> None:
        self._record = record

    def log(self, message: str) -> None:
        self._record.log(message)

    def progress(self, fraction: float) -> None:
        self._record.set_progress(fraction)


def execute_tonight(
    record: RunRecord,
    config_path: str,
    hours: float,
    mode: str | None,
    output_dir: Path,
) -> dict:
    """Webapp wrapper around the shared tonight pipeline. `output_dir` is
    the *base* directory (e.g. ``output/s30_pro_jc/``); the pipeline writes
    to ``<base>/tonight/``."""
    from ..tonight_pipeline import TonightOptions, run_tonight_pipeline

    base_output = output_dir.parent if output_dir.name == "tonight" else output_dir
    opts = TonightOptions(
        config_path=config_path,
        hours=hours,
        mode=mode,
        output_dir=base_output,
        archive=True,
    )
    result = run_tonight_pipeline(opts, RecordReporter(record))
    if result is None:
        return {"scheduled": 0, "schedule_path": ""}
    return {
        "scheduled": result.scheduled,
        "overflow": result.overflow,
        "packet_count": result.packet_count,
        "schedule_path": str(result.schedule_html_path),
        "archive_path": str(result.archive_path) if result.archive_path else "",
        "session_date": result.session_date,
    }


def execute_submit(
    record: RunRecord,
    target_dir: Path,
    target_name: str,
    comp_path: Path | None,
    observer_code: str,
    chart_id: str,
    target_slug: str | None = None,
    session_date: str | None = None,
    runs: RunRegistry | None = None,
    session_store: Any = None,  # webapp.db.SessionStore
) -> dict:
    """Webapp wrapper around `submit_pipeline.run_photometry_loop` with the
    layered concerns the CLI doesn't have: live frame streaming onto
    ``record.result``, anomaly assessment, plot generation, and SQLite
    upsert into the session store."""
    from ..photometry import aavso_filename, write_aavso_extended_file
    from ..submit_pipeline import (
        FrameRecord,
        frame_to_dict,
        preflight_fits_dir,
        resolve_comps,
        run_photometry_loop,
    )
    from ..vsx import fetch_vsx_target_by_name

    record.log(f"Looking up '{target_name}' in VSX...")
    vsx_target = fetch_vsx_target_by_name(target_name)
    if vsx_target is None:
        raise RuntimeError(
            f"Could not resolve '{target_name}' — either the name doesn't match a VSX entry "
            "or VizieR was unreachable after 3 attempts. Check the spelling and your network."
        )
    record.log(f"Found: {vsx_target.name} at RA {vsx_target.ra_deg:.5f}, Dec {vsx_target.dec_deg:.5f}")

    try:
        resolution = resolve_comps(
            target_name=target_name,
            target_bright_mag=vsx_target.bright_mag,
            comp_path=comp_path,
            chart_id_override=chart_id,
        )
    except Exception as exc:
        raise RuntimeError(f"Comp-star resolution failed: {exc}. Provide a comp-stars JSON to retry.")
    chart_id = resolution.chart_id
    if resolution.source == "json" and comp_path is not None:
        record.log(f"Loaded {len(resolution.comps)} comparison stars from {comp_path.name}.")
    elif resolution.source == "vsp":
        mags = [c.catalog_mag for c in resolution.comps]
        record.log(
            f"VSP chart {resolution.chart_id}: {len(resolution.comps)} comps selected of "
            f"{resolution.chart_total} (mags {min(mags):.2f}–{max(mags):.2f})."
        )
    elif resolution.source == "vsp-fallback":
        record.log(
            f"VSP chart {resolution.chart_id} returned {resolution.chart_total} comps, "
            f"none within mag tolerance; using brightest {len(resolution.comps)}."
        )

    try:
        fits_files = preflight_fits_dir(target_dir)
    except ValueError as exc:
        msg = str(exc)
        if "celestial WCS" in msg:
            raise RuntimeError(
                f"{msg}. NINA must plate-solve before saving — re-run capture with "
                "plate-solve enabled or solve frames manually before retrying."
            )
        raise RuntimeError(msg)
    record.log(f"WCS pre-flight OK on {fits_files[0].name}.")
    if any(c.catalog_band == "V" for c in resolution.comps):
        record.log(
            "Note: V-band comps will be reported as TG band per AAVSO OSC convention "
            "(green channel ≈ V but counts as a separate band)."
        )
    record.log(f"Processing {len(fits_files)} FITS files...")

    # Live results dict: the photometry template polls record.result['frames']
    # to render a table that fills in as each frame is processed.
    record.result = {
        "frames": [],
        "observations": [],
        "observation_count": 0,
        "failures": 0,
        "median_mag": None,
        "upload_path": None,
        "target_name": target_name,
        "target_slug": target_slug,
        "session_date": session_date,
        "observer_code": observer_code,
        "chart_id": chart_id,
    }
    total_frames = len(fits_files)
    progress_state = {"index": 0}

    def _on_frame(frame: FrameRecord) -> None:
        progress_state["index"] += 1
        if frame.skipped_comps:
            record.log(
                f"  {frame.filename}: skipped {len(frame.skipped_comps)} comp(s) — "
                f"{'; '.join(frame.skipped_comps[:3])}"
            )
        if frame.flag == "failed":
            record.log(f"  {frame.filename}: failed ({frame.note})")
        elif frame.flag == "no-signal":
            record.log(f"  {frame.filename}: no usable signal")
        else:
            record.log(
                f"  {frame.filename}: mag {frame.magnitude:.3f} +/- "
                f"{frame.magnitude_error:.3f} via comp {frame.comp_label}"
            )
        # Stream the frame onto record.result["frames"] under the lock so
        # the polling UI partial sees a coherent prefix.
        frame_dict = frame_to_dict(frame)
        is_failure = frame.flag in ("failed", "no-signal")
        obs_dict: dict | None = None
        if not is_failure:
            obs_dict = {
                "filename": frame.filename,
                "target_name": target_name,
                "julian_date": frame.julian_date,
                "magnitude": frame.magnitude,
                "magnitude_error": frame.magnitude_error,
                "band": frame.band,
                "comp_star_label": frame.comp_label,
                "comp_star_mag": frame.comp_mag,
                "chart_id": chart_id,
            }

        def _mutate(current: dict, frame_dict=frame_dict, obs_dict=obs_dict) -> dict:
            new = {**current}
            new["frames"] = list(current["frames"]) + [frame_dict]
            if obs_dict is not None:
                new["observations"] = list(current["observations"]) + [obs_dict]
                new["observation_count"] = len(new["observations"])
            else:
                new["failures"] = current.get("failures", 0) + 1
            return new

        record.update_result(_mutate)
        record.set_progress(0.1 + 0.85 * progress_state["index"] / max(total_frames, 1))

    result = run_photometry_loop(
        target_name=target_name,
        target_ra_deg=vsx_target.ra_deg,
        target_dec_deg=vsx_target.dec_deg,
        fits_files=fits_files,
        comps=resolution.comps,
        chart_id=chart_id,
        on_frame=_on_frame,
    )

    if not result.observations:
        raise RuntimeError("No successful observations.")

    flag_by_filename = {f.filename: f.flag for f in result.frames}

    def _apply_flags(current: dict, flag_by_filename=flag_by_filename) -> dict:
        new = {**current, "frames": [{**f} for f in current["frames"]]}
        for f in new["frames"]:
            updated_flag = flag_by_filename.get(f["filename"])
            if updated_flag and f["flag"] == "pending":
                f["flag"] = updated_flag
        return new

    record.update_result(_apply_flags)

    median_mag = result.median_mag
    upload_path = target_dir / aavso_filename(target_name)
    write_aavso_extended_file(
        result.observations,
        upload_path,
        observer_code=observer_code,
        chart_id=chart_id,
    )
    observations = result.observations

    record.log(f"Median mag {median_mag:.3f}; wrote {upload_path.name}")
    record.result["aavso_preview"] = read_aavso_preview(upload_path, max_rows=5)

    # Pull recent AAVSO obs for context overlay; failure is non-fatal.
    aavso_recent = fetch_aavso_recent_samples(target_name)
    if aavso_recent:
        record.log(f"Fetched {len(aavso_recent)} recent AAVSO observations for overlay.")

    from ..anomaly import assess_session_anomaly

    assessment = assess_session_anomaly(observations, vsx_target, aavso_recent)
    record.result["anomaly"] = assessment.to_dict()
    if assessment.level == "anomaly":
        record.log("FLAG: " + " · ".join(assessment.flags))
    elif assessment.level == "watch":
        record.log("WATCH: " + " · ".join(assessment.flags))
    else:
        record.log(assessment.flags[0] if assessment.flags else "Consistent with expectations.")

    from ..lightcurve import plot_phase_folded, plot_session_light_curve

    prior_sessions = collect_prior_session_observations(runs, target_slug, record.run_id)
    if prior_sessions:
        record.log(f"Overlaying {len(prior_sessions)} observations from prior sessions of this target.")

    lightcurve_path = target_dir / "lightcurve.png"
    if plot_session_light_curve(observations, target_name, lightcurve_path, aavso_recent, prior_sessions=prior_sessions):
        record.result["lightcurve_path"] = str(lightcurve_path)
        record.log(f"Wrote light curve: {lightcurve_path.name}")

    if vsx_target.period_days and len(observations) >= 3:
        folded_path = target_dir / "lightcurve_folded.png"
        if plot_phase_folded(
            observations,
            target_name,
            vsx_target.period_days,
            folded_path,
            aavso_recent,
            prior_sessions=prior_sessions,
        ):
            record.result["folded_path"] = str(folded_path)
            record.log(f"Wrote phase-folded light curve: {folded_path.name}")

    record.set_progress(1.0)

    record.result["median_mag"] = median_mag
    record.result["upload_path"] = str(upload_path)

    # Index into the SQLite session store so /data routes can query history.
    if session_store is not None and target_slug:
        try:
            session_store.upsert_session(
                run_id=record.run_id,
                target_name=target_name,
                target_slug=target_slug,
                session_date=session_date,
                observer_code=observer_code,
                chart_id=chart_id,
                observation_count=len(observations),
                median_mag=median_mag,
                anomaly_level=record.result.get("anomaly", {}).get("level") if record.result.get("anomaly") else None,
                submitted_at=None,
                created_at=record.created_at.isoformat() if record.created_at else "",
                observations=record.result.get("observations") or [],
            )
        except Exception as exc:  # DB problems shouldn't fail the run
            record.log(f"Session DB upsert failed (non-fatal): {exc}")

    return record.result


def collect_prior_session_observations(
    runs: RunRegistry | None,
    target_slug: str | None,
    current_run_id: str,
) -> list[tuple[float, float, str]] | None:
    """Pull (jd, mag, band) tuples from prior `submit:<slug>` runs so the
    light curve can overlay the user's own multi-night history."""
    if runs is None or target_slug is None:
        return None
    kind = f"submit:{target_slug}"
    samples: list[tuple[float, float, str]] = []
    for prior in runs.all():
        if prior.kind != kind:
            continue
        if prior.run_id == current_run_id:
            continue
        if prior.status != "done" or not prior.result:
            continue
        for entry in prior.result.get("observations", []) or []:
            jd = entry.get("julian_date")
            mag = entry.get("magnitude")
            band = entry.get("band") or "TG"
            if jd is None or mag is None:
                continue
            samples.append((float(jd), float(mag), band))
    return samples or None


def read_aavso_preview(path: Path, max_rows: int = 5) -> str:
    """Return the AAVSO Extended File header lines plus the first few data
    rows, so the user can sanity-check the upload before downloading. Header
    lines start with '#' (TYPE/OBSCODE/SOFTWARE/DELIM/DATE/OBSTYPE/column
    spec); after that we keep up to `max_rows` data rows."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    total_data_rows = sum(1 for line in lines if line.strip() and not line.startswith("#"))
    data_rows_kept = 0
    for line in lines:
        if line.startswith("#"):
            out.append(line)
            continue
        if not line.strip():
            continue
        if data_rows_kept < max_rows:
            out.append(line)
            data_rows_kept += 1
        else:
            remaining = total_data_rows - data_rows_kept
            if remaining > 0:
                out.append(f"… ({remaining} more data rows)")
            break
    return "\n".join(out)


def fetch_aavso_recent_samples(target_name: str) -> list[tuple[float, float, str]] | None:
    """Pull recent AAVSO observations for overlay on the light-curve plot.
    Best-effort — returns None on any error."""
    try:
        from ..aavso import fetch_recent_observation_count
        from ..config import AavsoConfig

        cfg = AavsoConfig(
            enabled=True,
            enrich_top=1,
            recent_days=90,
            sparse_recent_threshold=10,
            timeout_seconds=30,
            bands=("V", "TG", "Vis."),
            period_min_peak_power=0.4,
        )
        stats = fetch_recent_observation_count(target_name, cfg)
        if stats and stats.recent_samples:
            return list(stats.recent_samples)
    except Exception:
        return None
    return None
