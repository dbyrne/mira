from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from flask import Flask, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from .runs import RunRecord, RunRegistry


def register_routes(app: Flask) -> None:
    @app.route("/")
    def index():
        runs: RunRegistry = current_app.config["RUNS"]
        latest_run = runs.latest("tonight")
        latest_photometry = [r for r in runs.all() if r.kind == "submit"][:5]
        schedule_path: Path = current_app.config["OUTPUT_DIR"] / "session_schedule.html"
        return render_template(
            "index.html",
            latest_run=latest_run,
            latest_photometry=latest_photometry,
            schedule_exists=schedule_path.exists(),
            output_dir=current_app.config["OUTPUT_DIR"],
            captures_root=current_app.config["CAPTURES_ROOT"],
        )

    # --- Layer 1: kick off + view ---

    @app.route("/run", methods=["POST"])
    def trigger_run():
        runs: RunRegistry = current_app.config["RUNS"]
        config_path = request.form.get("config", "config/s30_pro_jc.yaml")
        hours = float(request.form.get("hours", "4"))
        mode = request.form.get("mode") or None
        output_dir: Path = current_app.config["OUTPUT_DIR"]

        record = runs.submit(
            kind="tonight",
            label=f"tonight: {config_path} hours={hours}" + (f" mode={mode}" if mode else ""),
            target_callable=lambda rec: _execute_tonight(rec, config_path, hours, mode, output_dir),
        )
        return redirect(url_for("run_status", run_id=record.run_id))

    @app.route("/run/<run_id>")
    def run_status(run_id):
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.get(run_id)
        if record is None:
            abort(404)
        return render_template("run_status.html", run=record)

    @app.route("/run/<run_id>/partial")
    def run_status_partial(run_id):
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.get(run_id)
        if record is None:
            abort(404)
        return render_template("run_status_partial.html", run=record)

    @app.route("/schedule")
    def schedule():
        output_dir: Path = current_app.config["OUTPUT_DIR"]
        path = output_dir / "session_schedule.html"
        if not path.exists():
            return render_template("schedule_missing.html", output_dir=output_dir), 404
        return send_from_directory(str(output_dir), "session_schedule.html")

    @app.route("/output/<path:filename>")
    def output_file(filename):
        """Serve any file from the output dir (for chart images, CSVs, etc)."""
        output_dir: Path = current_app.config["OUTPUT_DIR"]
        return send_from_directory(str(output_dir), filename)

    # --- Layer 2: photometry ---

    @app.route("/photometry")
    def photometry_index():
        runs: RunRegistry = current_app.config["RUNS"]
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        output_dir: Path = current_app.config["OUTPUT_DIR"]
        targets = _discover_capture_targets(captures_root)
        photometry_runs = {r.label: r for r in runs.all() if r.kind == "submit"}
        runs_by_kind = {r.kind: r for r in runs.all() if r.kind.startswith("submit:")}
        scheduled = _build_schedule_status(output_dir / "session_schedule.csv", captures_root, runs_by_kind)
        return render_template(
            "photometry_index.html",
            targets=targets,
            captures_root=captures_root,
            photometry_runs=photometry_runs,
            scheduled=scheduled,
        )

    @app.route("/photometry/<target_slug>")
    def photometry_target(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        target_dir = _resolve_target_dir(captures_root, target_slug)
        if target_dir is None:
            abort(404)
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug))
        return render_template(
            "photometry_target.html",
            target_slug=target_slug,
            target_dir=target_dir,
            target_name=_dir_to_target_name(target_dir),
            run=record,
            comp_star_default=_default_comp_stars_path(target_dir),
        )

    @app.route("/photometry/<target_slug>/run", methods=["POST"])
    def trigger_photometry(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        target_dir = _resolve_target_dir(captures_root, target_slug)
        if target_dir is None:
            abort(404)

        comp_stars_input = request.form.get("comp_stars", "").strip()
        comp_path: Path | None = None
        if comp_stars_input:
            candidate = Path(comp_stars_input).resolve()
            if not candidate.exists():
                return render_template(
                    "photometry_target.html",
                    target_slug=target_slug,
                    target_dir=target_dir,
                    target_name=request.form.get("target_name", "").strip()
                    or _dir_to_target_name(target_dir),
                    run=None,
                    error=f"Comp-stars JSON not found: {candidate}",
                    comp_star_default=_default_comp_stars_path(target_dir),
                ), 400
            comp_path = candidate

        observer_code = request.form.get("observer_code", "").strip()
        chart_id = request.form.get("chart_id", "").strip() or "na"
        target_name = request.form.get("target_name", "").strip() or _dir_to_target_name(target_dir)

        if not observer_code:
            return render_template(
                "photometry_target.html",
                target_slug=target_slug,
                target_dir=target_dir,
                target_name=target_name,
                run=None,
                error="Observer code is required.",
                comp_star_default=_default_comp_stars_path(target_dir),
            ), 400

        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.submit(
            kind=_submit_kind(target_slug),
            label=f"submit: {target_name}",
            target_callable=lambda rec: _execute_submit(
                rec,
                target_dir=target_dir,
                target_name=target_name,
                comp_path=comp_path,
                observer_code=observer_code,
                chart_id=chart_id,
            ),
        )
        return redirect(url_for("photometry_target", target_slug=target_slug))

    @app.route("/photometry/<target_slug>/partial")
    def photometry_target_partial(target_slug):
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug))
        if record is None:
            return render_template("photometry_partial.html", run=None, target_slug=target_slug)
        return render_template("photometry_partial.html", run=record, target_slug=target_slug)

    @app.route("/photometry/<target_slug>/lightcurve.png")
    def photometry_lightcurve(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        target_dir = _resolve_target_dir(captures_root, target_slug)
        if target_dir is None or not (target_dir / "lightcurve.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve.png")

    @app.route("/photometry/<target_slug>/lightcurve_folded.png")
    def photometry_lightcurve_folded(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        target_dir = _resolve_target_dir(captures_root, target_slug)
        if target_dir is None or not (target_dir / "lightcurve_folded.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve_folded.png")

    @app.route("/photometry/<target_slug>/mark-submitted", methods=["POST"])
    def photometry_mark_submitted(target_slug):
        from datetime import datetime, timezone

        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug))
        if record is None or record.status != "done":
            abort(404)
        if record.result is None:
            record.result = {}
        record.result["submitted_at"] = datetime.now(timezone.utc).isoformat()
        record.log("Marked as submitted to AAVSO WebObs.")
        runs.persist(record)
        return redirect(url_for("photometry_target", target_slug=target_slug))

    @app.route("/photometry/<target_slug>/upload")
    def photometry_upload(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        target_dir = _resolve_target_dir(captures_root, target_slug)
        if target_dir is None:
            abort(404)
        upload_path = target_dir / f"aavso_{_dir_to_target_name(target_dir).replace(' ', '_')}.txt"
        if not upload_path.exists():
            abort(404)
        return send_from_directory(str(target_dir), upload_path.name, as_attachment=True)

    # --- Layer 3: NINA monitor ---

    @app.route("/nina")
    def nina_dashboard():
        return render_template("nina.html", base_url=current_app.config["NINA"].base_url)

    @app.route("/nina/partial")
    def nina_partial():
        nina = current_app.config["NINA"]
        status = nina.status()
        return render_template("nina_partial.html", status=status, base_url=nina.base_url)


# --- Background-task implementations ---

def _execute_tonight(record: RunRecord, config_path: str, hours: float, mode: str | None, output_dir: Path) -> dict:
    """Run the same logic as anomaly-scout tonight, reporting progress on the record."""
    from dataclasses import replace as dc_replace
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from ..aavso import enrich_candidates_with_aavso
    from ..config import load_config
    from ..gaia import enrich_candidates_with_gaia
    from ..nightly_html import write_session_schedule_html
    from ..report import compute_packet_union_oids, write_outputs
    from ..scheduler import build_session_schedule
    from ..scoring import build_candidates, candidate_sort_key
    from ..session_plan import write_session_plan
    from ..session_schedule import write_session_schedule_outputs
    from ..simbad import enrich_candidates_with_simbad
    from ..vsx import fetch_vsx_targets

    record.set_progress(0.05)
    record.log(f"Loading config: {config_path}")
    config = load_config(config_path)

    # Apply mode if given
    if mode:
        from ..cli import _apply_mode
        config = _apply_mode(config, mode)
        record.log(f"Mode: {mode}")

    # Override sites to nights=1
    new_sites = tuple(
        dc_replace(site, observing_window=dc_replace(site.observing_window, nights=1))
        for site in config.sites
    )
    config = dc_replace(config, sites=new_sites)

    today = date.today()
    primary_tz = ZoneInfo(config.sites[0].observer.timezone)
    now_local = datetime.now(primary_tz)
    window_end = now_local + timedelta(hours=hours)

    record.log(f"Tonight = {today}; window = {now_local.strftime('%H:%M')} -> {window_end.strftime('%H:%M %Z')}")
    record.set_progress(0.1)

    record.log(f"Fetching up to {config.vsx_query.row_limit} VSX rows...")
    targets = fetch_vsx_targets(config.vsx_query)
    record.log(f"Fetched {len(targets)} catalog rows.")
    record.set_progress(0.25)

    candidates = build_candidates(targets, config, start_date=today)
    record.log(f"{len(candidates)} targets passed site filters.")

    earliest = now_local - timedelta(hours=1)
    candidates = [
        c for c in candidates
        if any(
            obs.best_local_time and earliest <= obs.best_local_time <= window_end
            for obs in c.observabilities
        )
    ]
    record.log(f"{len(candidates)} observable in the next {hours:g}h.")
    record.set_progress(0.35)

    if not candidates:
        record.log("Nothing observable; widen --hours or run later.")
        return {"scheduled": 0, "schedule_path": ""}

    site_names = [s.name for s in config.sites]
    top_packets = config.output.top_packets

    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)
    aavso_count = enrich_candidates_with_aavso(candidates, config, limit=config.aavso.enrich_top, extra_oids=union_oids)
    record.log(f"AAVSO enriched: {aavso_count}")
    record.set_progress(0.55)

    union_oids = compute_packet_union_oids(candidates, top_packets, site_names)
    simbad_count = enrich_candidates_with_simbad(candidates, config, limit=config.simbad.enrich_top, extra_oids=union_oids)
    record.log(f"SIMBAD enriched: {simbad_count}")
    record.set_progress(0.7)

    gaia_count = enrich_candidates_with_gaia(candidates, config, limit=config.gaia.enrich_top, extra_oids=union_oids)
    candidates.sort(key=candidate_sort_key)
    record.log(f"Gaia enriched: {gaia_count}")
    record.set_progress(0.85)

    metadata = {
        "config_path": config_path,
        "output_dir": str(output_dir),
        "start_date": today.isoformat(),
        "mode": mode or "(yaml defaults)",
        "vsx_row_limit": config.vsx_query.row_limit,
        "candidates_after_filters": len(candidates),
        "aavso_enriched": aavso_count,
        "simbad_enriched": simbad_count,
        "gaia_enriched": gaia_count,
        "ztf_enriched": 0,
        "top_packets_per_view": top_packets,
        "tonight_window_start": now_local.isoformat(),
        "tonight_window_end": window_end.isoformat(),
        "tonight_hours": hours,
    }

    packet_count = write_outputs(candidates, output_dir, top_packets, site_names=site_names, metadata=metadata)
    plan_targets = candidates[:top_packets]
    write_session_plan(plan_targets, output_dir, now_local, window_end, config)
    schedule = build_session_schedule(candidates, window_start=now_local, window_end=window_end)
    write_session_schedule_outputs(schedule, output_dir, config)
    write_session_schedule_html(schedule, output_dir, config, metadata=metadata)

    record.log(f"Scheduled {len(schedule.scheduled)} targets, {len(schedule.overflow)} overflow.")
    record.log(f"Packets: {packet_count}")
    record.set_progress(1.0)

    return {
        "scheduled": len(schedule.scheduled),
        "overflow": len(schedule.overflow),
        "packet_count": packet_count,
        "schedule_path": str(output_dir / "session_schedule.html"),
    }


def _execute_submit(
    record: RunRecord,
    target_dir: Path,
    target_name: str,
    comp_path: Path | None,
    observer_code: str,
    chart_id: str,
) -> dict:
    from ..photometry import CompStar, process_capture, write_aavso_extended_file
    from ..vsx import fetch_vsx_target_by_name

    record.log(f"Looking up '{target_name}' in VSX...")
    vsx_target = fetch_vsx_target_by_name(target_name)
    if vsx_target is None:
        raise RuntimeError(
            f"Could not resolve '{target_name}' — either the name doesn't match a VSX entry "
            "or VizieR was unreachable after 3 attempts. Check the spelling and your network."
        )
    record.log(f"Found: {vsx_target.name} at RA {vsx_target.ra_deg:.5f}, Dec {vsx_target.dec_deg:.5f}")

    if comp_path is not None:
        with comp_path.open(encoding="utf-8") as handle:
            comp_data = json.load(handle)
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
        record.log(f"Loaded {len(comps)} comparison stars from {comp_path.name}.")
    else:
        from ..vsp import fetch_vsp_chart, filter_comps_for_target

        record.log("Auto-fetching comp stars from AAVSO VSP...")
        try:
            chart = fetch_vsp_chart(target_name)
        except Exception as exc:
            raise RuntimeError(f"VSP fetch failed: {exc}. Provide a comp-stars JSON to retry.")
        target_mag = vsx_target.max_mag
        comps = filter_comps_for_target(chart.comps, target_mag)
        if not comps:
            comps = chart.comps[:6]
        if not chart_id or chart_id == "na":
            chart_id = chart.chart_id
        record.log(
            f"VSP chart {chart.chart_id}: {len(comps)} comps selected of {len(chart.comps)} "
            f"(mags {min(c.catalog_mag for c in comps):.2f}–{max(c.catalog_mag for c in comps):.2f})."
        )

    fits_files = sorted(list(target_dir.glob("*.fits")) + list(target_dir.glob("*.fit")))
    if not fits_files:
        raise RuntimeError(f"No FITS files found in {target_dir}")

    # Pre-flight: peek at the first FITS to fail fast on missing WCS rather
    # than churning through every frame just to report the same error.
    from ..photometry import read_fits_with_wcs

    try:
        read_fits_with_wcs(fits_files[0])
    except ValueError as exc:
        raise RuntimeError(
            f"First FITS ({fits_files[0].name}) is missing a celestial WCS: {exc}. "
            "NINA must plate-solve before saving — re-run capture with plate-solve enabled "
            "or solve frames manually before retrying."
        )
    record.log(f"WCS pre-flight OK on {fits_files[0].name}.")
    if any(c.catalog_band == "V" for c in comps):
        record.log(
            "Note: V-band comps will be reported as TG band per AAVSO OSC convention "
            "(green channel ≈ V but counts as a separate band)."
        )
    record.log(f"Processing {len(fits_files)} FITS files...")

    # Live results dict: the photometry template polls record.result['frames']
    # to render a table that fills in as each frame is processed.
    record.result = {
        "frames": [],
        "observation_count": 0,
        "failures": 0,
        "median_mag": None,
        "upload_path": None,
    }
    observations = []
    failures = []
    for index, path in enumerate(fits_files):
        try:
            obs = process_capture(
                path,
                target_name,
                vsx_target.ra_deg,
                vsx_target.dec_deg,
                comps,
            )
        except Exception as exc:
            failures.append((path.name, str(exc)))
            record.log(f"  {path.name}: failed ({exc})")
            record.result["frames"].append(
                {"filename": path.name, "magnitude": None, "magnitude_error": None,
                 "comp_label": "", "flag": "failed", "note": str(exc)}
            )
            record.result["failures"] = len(failures)
            continue
        if obs is None:
            failures.append((path.name, "no usable signal"))
            record.log(f"  {path.name}: no usable signal")
            record.result["frames"].append(
                {"filename": path.name, "magnitude": None, "magnitude_error": None,
                 "comp_label": "", "flag": "no-signal", "note": "no usable signal"}
            )
            record.result["failures"] = len(failures)
            continue
        obs.chart_id = chart_id
        observations.append(obs)
        record.result["frames"].append(
            {
                "filename": path.name,
                "jd": obs.julian_date,
                "magnitude": obs.magnitude,
                "magnitude_error": obs.magnitude_error,
                "comp_label": obs.comp_star_label,
                "flag": "pending",  # filled with "ok"/"outlier" after the loop
                "note": "",
            }
        )
        record.result["observation_count"] = len(observations)
        record.log(f"  {path.name}: mag {obs.magnitude:.3f} +/- {obs.magnitude_error:.3f} via comp {obs.comp_star_label}")
        record.set_progress(0.1 + 0.85 * (index + 1) / len(fits_files))

    if not observations:
        raise RuntimeError("No successful observations.")

    # Flag outliers: |mag - median| > 3 * 1.4826 * MAD (robust sigma estimate).
    mags = [o.magnitude for o in observations]
    median_mag = sorted(mags)[len(mags) // 2]
    if len(mags) >= 5:
        deviations = sorted(abs(m - median_mag) for m in mags)
        mad = deviations[len(deviations) // 2]
        sigma = mad * 1.4826
        for frame in record.result["frames"]:
            if frame["flag"] == "pending":
                if sigma > 0 and abs(frame["magnitude"] - median_mag) > 3 * sigma:
                    frame["flag"] = "outlier"
                else:
                    frame["flag"] = "ok"
    else:
        # Too few frames to meaningfully flag outliers.
        for frame in record.result["frames"]:
            if frame["flag"] == "pending":
                frame["flag"] = "ok"

    upload_path = target_dir / f"aavso_{target_name.replace(' ', '_').replace('/', '_')}.txt"
    write_aavso_extended_file(
        observations,
        upload_path,
        observer_code=observer_code,
        chart_id=chart_id,
    )

    record.log(f"Median mag {median_mag:.3f}; wrote {upload_path.name}")

    # Pull recent AAVSO obs for context overlay; failure is non-fatal.
    aavso_recent = _fetch_aavso_recent_samples(target_name)
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

    lightcurve_path = target_dir / "lightcurve.png"
    if plot_session_light_curve(observations, target_name, lightcurve_path, aavso_recent):
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
        ):
            record.result["folded_path"] = str(folded_path)
            record.log(f"Wrote phase-folded light curve: {folded_path.name}")

    record.set_progress(1.0)

    record.result["median_mag"] = median_mag
    record.result["upload_path"] = str(upload_path)
    return record.result


def _fetch_aavso_recent_samples(target_name: str) -> list[tuple[float, float, str]] | None:
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


# --- helpers ---

def _build_schedule_status(
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
            target_dir = _resolve_scheduled_target_dir(captures_root, target_name)
            slug = target_dir.name if target_dir else target_name.replace(" ", "_")
            fits_count = 0
            if target_dir:
                fits_count = len(list(target_dir.glob("*.fits")) + list(target_dir.glob("*.fit")))
            run = runs_by_kind.get(f"submit:{slug}")
            stage = _resolve_stage(fits_count, run)
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
                    "has_dir": target_dir is not None,
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


def _resolve_scheduled_target_dir(captures_root: Path, target_name: str) -> Path | None:
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


def _resolve_stage(fits_count: int, run) -> str:
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


def _discover_capture_targets(captures_root: Path) -> list[dict]:
    """Each immediate subdirectory of captures_root that contains FITS files
    is treated as a target."""
    if not captures_root.exists():
        return []
    targets = []
    for entry in sorted(captures_root.iterdir()):
        if not entry.is_dir():
            continue
        fits_files = list(entry.glob("*.fits")) + list(entry.glob("*.fit"))
        if not fits_files:
            continue
        targets.append(
            {
                "slug": entry.name,
                "name": _dir_to_target_name(entry),
                "fits_count": len(fits_files),
                "path": entry,
                "modified": max(f.stat().st_mtime for f in fits_files),
                "upload_exists": any(entry.glob("aavso_*.txt")),
            }
        )
    targets.sort(key=lambda d: d["modified"], reverse=True)
    return targets


def _resolve_target_dir(captures_root: Path, slug: str) -> Path | None:
    """Map a URL slug back to a captures subdirectory. Defensive against
    path traversal: only allow direct children of captures_root."""
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
    return resolved


def _dir_to_target_name(target_dir: Path) -> str:
    """Convert a directory name like 'RR_LYR' into a VSX-style target name 'RR LYR'."""
    return target_dir.name.replace("_", " ")


def _default_comp_stars_path(target_dir: Path) -> str:
    """Suggest the path where a comp-stars JSON would live."""
    return str(target_dir / "comp_stars.json")


def _submit_kind(target_slug: str) -> str:
    return f"submit:{target_slug}"
