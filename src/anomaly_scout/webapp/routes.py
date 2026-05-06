from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from .runs import RunRecord, RunRegistry


def register_routes(app: Flask) -> None:
    @app.route("/")
    def index():
        from .settings import load_settings

        runs: RunRegistry = current_app.config["RUNS"]
        latest_run = runs.latest("tonight")
        all_submit_runs = [r for r in runs.all() if r.kind.startswith("submit:")]
        latest_photometry = all_submit_runs[:5]
        schedule_path: Path = current_app.config["OUTPUT_DIR"] / "session_schedule.html"
        settings = load_settings(current_app.config.get("STATE_DIR"))

        # Lifetime stats: total photometry sessions completed, anomalies flagged, submitted to AAVSO.
        completed = [r for r in all_submit_runs if r.status == "done"]
        anomaly_runs = [r for r in completed if r.result and (r.result.get("anomaly") or {}).get("level") == "anomaly"]
        watch_runs = [r for r in completed if r.result and (r.result.get("anomaly") or {}).get("level") == "watch"]
        submitted_runs = [r for r in completed if r.result and r.result.get("submitted_at")]
        latest_anomaly = anomaly_runs[0] if anomaly_runs else None

        return render_template(
            "index.html",
            latest_run=latest_run,
            latest_photometry=latest_photometry,
            schedule_exists=schedule_path.exists(),
            output_dir=current_app.config["OUTPUT_DIR"],
            captures_root=current_app.config["CAPTURES_ROOT"],
            default_config=settings.get("default_config", "config/s30_pro_jc.yaml"),
            default_hours=settings.get("default_hours", 4),
            stat_completed=len(completed),
            stat_anomaly=len(anomaly_runs),
            stat_watch=len(watch_runs),
            stat_submitted=len(submitted_runs),
            latest_anomaly=latest_anomaly,
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
        overflow = _read_overflow_targets(output_dir / "session_overflow.csv")
        return render_template(
            "photometry_index.html",
            targets=targets,
            captures_root=captures_root,
            photometry_runs=photometry_runs,
            scheduled=scheduled,
            overflow=overflow,
        )

    @app.route("/photometry/<target_slug>")
    def photometry_target(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = _resolved_session_date(target_dir)
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug, resolved_date))
        from .settings import load_settings

        settings = load_settings(current_app.config.get("STATE_DIR"))
        target_root = captures_root / target_slug
        sessions = _list_capture_sessions(target_root) if target_root.is_dir() else []
        return render_template(
            "photometry_target.html",
            target_slug=target_slug,
            target_dir=target_dir,
            target_name=_dir_to_target_name(target_root if target_root.is_dir() else target_dir),
            run=record,
            comp_star_default=_default_comp_stars_path(target_dir),
            saved_observer_code=settings.get("observer_code", ""),
            session_date=resolved_date,
            sessions=sessions,
        )

    @app.route("/photometry/<target_slug>/run", methods=["POST"])
    def trigger_photometry(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = _resolved_session_date(target_dir)

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
                    session_date=resolved_date,
                    sessions=[],
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
                session_date=resolved_date,
                sessions=[],
            ), 400

        runs: RunRegistry = current_app.config["RUNS"]
        from .settings import update_setting

        update_setting(current_app.config.get("STATE_DIR"), "observer_code", observer_code)
        session_store = current_app.config.get("SESSION_STORE")

        runs.submit(
            kind=_submit_kind(target_slug, resolved_date),
            label=f"submit: {target_name}" + (f" [{resolved_date}]" if resolved_date else ""),
            target_callable=lambda rec: _execute_submit(
                rec,
                target_dir=target_dir,
                target_name=target_name,
                comp_path=comp_path,
                observer_code=observer_code,
                chart_id=chart_id,
                target_slug=target_slug,
                session_date=resolved_date,
                runs=runs,
                session_store=session_store,
            ),
        )
        return redirect(url_for("photometry_target", target_slug=target_slug, date=resolved_date))

    @app.route("/photometry/<target_slug>/partial")
    def photometry_target_partial(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        resolved_date = _resolved_session_date(target_dir) if target_dir else date
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug, resolved_date))
        if record is None:
            return render_template(
                "photometry_partial.html", run=None, target_slug=target_slug, session_date=resolved_date
            )
        return render_template(
            "photometry_partial.html", run=record, target_slug=target_slug, session_date=resolved_date
        )

    @app.route("/photometry/<target_slug>/lightcurve.png")
    def photometry_lightcurve(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None or not (target_dir / "lightcurve.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve.png")

    @app.route("/photometry/<target_slug>/lightcurve_folded.png")
    def photometry_lightcurve_folded(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None or not (target_dir / "lightcurve_folded.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve_folded.png")

    @app.route("/photometry/<target_slug>/mark-submitted", methods=["POST"])
    def photometry_mark_submitted(target_slug):
        from datetime import datetime, timezone

        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        resolved_date = _resolved_session_date(target_dir) if target_dir else date

        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug, resolved_date))
        if record is None or record.status != "done":
            abort(404)
        if record.result is None:
            record.result = {}
        record.result["submitted_at"] = datetime.now(timezone.utc).isoformat()
        record.log("Marked as submitted to AAVSO WebObs.")
        runs.persist(record)
        # Also flush submission to SQLite if available (Batch V).
        store = current_app.config.get("SESSION_STORE")
        if store is not None:
            store.mark_submitted(record.run_id, record.result["submitted_at"])
        return redirect(url_for("photometry_target", target_slug=target_slug, date=resolved_date))

    @app.route("/photometry/<target_slug>/download-with-selection", methods=["POST"])
    def photometry_download_selected(target_slug):
        from ..photometry import Observation, write_aavso_extended_file

        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = _resolved_session_date(target_dir)
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(_submit_kind(target_slug, resolved_date))
        if record is None or record.status != "done" or not record.result:
            abort(404)

        included = set(request.form.getlist("include"))
        observations: list[Observation] = []
        for entry in record.result.get("observations", []):
            if entry.get("filename") not in included:
                continue
            observations.append(
                Observation(
                    target_name=entry["target_name"],
                    julian_date=entry["julian_date"],
                    magnitude=entry["magnitude"],
                    magnitude_error=entry["magnitude_error"],
                    band=entry.get("band", "TG"),
                    comp_star_label=entry.get("comp_star_label", ""),
                    comp_star_mag=entry.get("comp_star_mag", 0.0),
                    chart_id=entry.get("chart_id", "na"),
                )
            )
        if not observations:
            abort(400, description="At least one frame must be included.")

        target_name = record.result.get("target_name", target_slug)
        observer_code = record.result.get("observer_code", "")
        chart_id = record.result.get("chart_id", "na")
        upload_path = target_dir / f"aavso_{target_name.replace(' ', '_').replace('/', '_')}.txt"
        write_aavso_extended_file(
            observations,
            upload_path,
            observer_code=observer_code,
            chart_id=chart_id,
        )
        record.log(f"Re-wrote AAVSO file with {len(observations)} of {len(record.result.get('observations', []))} frames.")
        record.result["aavso_preview"] = _read_aavso_preview(upload_path, max_rows=5)
        runs.persist(record)
        return send_from_directory(str(target_dir), upload_path.name, as_attachment=True)

    @app.route("/photometry/<target_slug>/upload")
    def photometry_upload(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = _request_date()
        target_dir = _resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        target_root = captures_root / target_slug
        target_name = _dir_to_target_name(target_root if target_root.is_dir() else target_dir)
        upload_path = target_dir / f"aavso_{target_name.replace(' ', '_')}.txt"
        if not upload_path.exists():
            abort(404)
        return send_from_directory(str(target_dir), upload_path.name, as_attachment=True)

    @app.route("/runs")
    def run_history():
        runs: RunRegistry = current_app.config["RUNS"]
        return render_template("runs.html", runs=runs.all())

    @app.route("/first-light")
    def first_light():
        """Walkthrough page that pulls together status from settings, NINA,
        schedule, captures, photometry runs into a single checkbox view."""
        from .settings import load_settings

        runs: RunRegistry = current_app.config["RUNS"]
        nina = current_app.config["NINA"]
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        output_dir: Path = current_app.config["OUTPUT_DIR"]
        state_dir: Path | None = current_app.config.get("STATE_DIR")

        settings = load_settings(state_dir)
        observer_code_set = bool((settings.get("observer_code") or "").strip())

        schedule_csv = output_dir / "session_schedule.csv"
        schedule_exists = schedule_csv.exists()
        runs_by_kind = {r.kind: r for r in runs.all() if r.kind.startswith("submit:")}
        scheduled = _build_schedule_status(schedule_csv, captures_root, runs_by_kind)
        scheduled_total = len(scheduled)
        scheduled_captured = sum(1 for s in scheduled if s["fits_count"] > 0)
        scheduled_processed = sum(1 for s in scheduled if s["stage"] in ("processed", "submitted"))
        scheduled_submitted = sum(1 for s in scheduled if s["stage"] == "submitted")

        try:
            nina_status = nina.status()
        except Exception:
            nina_status = None

        latest_tonight = runs.latest("tonight")

        return render_template(
            "first_light.html",
            observer_code_set=observer_code_set,
            schedule_exists=schedule_exists,
            scheduled=scheduled,
            scheduled_total=scheduled_total,
            scheduled_captured=scheduled_captured,
            scheduled_processed=scheduled_processed,
            scheduled_submitted=scheduled_submitted,
            nina_status=nina_status,
            latest_tonight=latest_tonight,
        )

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        from .settings import load_settings, save_settings

        state_dir: Path | None = current_app.config.get("STATE_DIR")
        saved = False
        if request.method == "POST":
            current = load_settings(state_dir)
            current["observer_code"] = request.form.get("observer_code", "").strip()
            current["default_config"] = request.form.get("default_config", "").strip() or "config/s30_pro_jc.yaml"
            try:
                hours = float(request.form.get("default_hours", "4"))
            except ValueError:
                hours = 4.0
            current["default_hours"] = max(0.5, min(14.0, hours))
            save_settings(state_dir, current)
            saved = True
        settings = load_settings(state_dir)
        return render_template("settings.html", settings=settings, saved=saved)

    @app.route("/data")
    @app.route("/data/sessions")
    def data_sessions():
        store = current_app.config.get("SESSION_STORE")
        if store is None:
            return render_template("data_sessions.html", sessions=[], target_filter=None, anomaly_only=False)
        target_filter = (request.args.get("target") or "").strip() or None
        anomaly_only = request.args.get("anomaly") == "1"
        sessions = store.list_sessions(target_slug=target_filter, anomaly_only=anomaly_only, limit=500)
        if request.args.get("format") == "csv":
            from io import StringIO
            import csv as _csv

            buf = StringIO()
            fields = ["run_id", "target_name", "target_slug", "session_date", "observer_code",
                      "chart_id", "observation_count", "median_mag", "anomaly_level",
                      "submitted_at", "created_at"]
            writer = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for s in sessions:
                writer.writerow(s)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=sessions.csv"},
            )
        return render_template(
            "data_sessions.html",
            sessions=sessions,
            target_filter=target_filter,
            anomaly_only=anomaly_only,
        )

    @app.route("/data/anomalies")
    def data_anomalies():
        store = current_app.config.get("SESSION_STORE")
        sessions = store.list_sessions(anomaly_only=True, limit=200) if store else []
        return render_template(
            "data_sessions.html",
            sessions=sessions,
            target_filter=None,
            anomaly_only=True,
            heading="Flagged anomalies",
        )

    @app.route("/data/target/<target_slug>")
    def data_target(target_slug):
        store = current_app.config.get("SESSION_STORE")
        if store is None:
            abort(404)
        sessions = store.list_sessions(target_slug=target_slug)
        observations = store.get_observations(target_slug)
        history_chart_url = url_for("data_target_history_chart", target_slug=target_slug) if observations else None
        return render_template(
            "data_target.html",
            target_slug=target_slug,
            target_name=target_slug.replace("_", " "),
            sessions=sessions,
            observations=observations,
            history_chart_url=history_chart_url,
        )

    @app.route("/data/target/<target_slug>/history.png")
    def data_target_history_chart(target_slug):
        store = current_app.config.get("SESSION_STORE")
        if store is None:
            abort(404)
        observations = store.get_observations(target_slug)
        if not observations:
            abort(404)
        from ..lightcurve import plot_history

        state_dir: Path = current_app.config.get("STATE_DIR")
        cache_dir = state_dir / "history-charts"
        cache_dir.mkdir(parents=True, exist_ok=True)
        chart_path = cache_dir / f"{target_slug}.png"
        # Always regenerate — sessions evolve. (At single-user volumes this is fine.)
        points = [
            (
                float(o["julian_date"]) if o["julian_date"] is not None else 0.0,
                float(o["magnitude"]) if o["magnitude"] is not None else float("nan"),
                float(o["magnitude_error"]) if o["magnitude_error"] is not None else None,
                o.get("session_date"),
            )
            for o in observations
            if o["julian_date"] is not None and o["magnitude"] is not None
        ]
        if not points:
            abort(404)
        plot_history(target_slug.replace("_", " "), points, chart_path)
        return send_from_directory(str(cache_dir), f"{target_slug}.png")

    @app.route("/archive")
    def archive_index():
        archive_root = current_app.config["OUTPUT_DIR"].parent / "archive"
        sessions: list[dict] = []
        if archive_root.is_dir():
            for entry in sorted(archive_root.iterdir(), reverse=True):
                if not entry.is_dir() or not _looks_like_date(entry.name):
                    continue
                schedule_csv = entry / "session_schedule.csv"
                target_count = 0
                if schedule_csv.exists():
                    try:
                        with schedule_csv.open(encoding="utf-8") as h:
                            target_count = sum(1 for _ in h) - 1  # minus header
                    except OSError:
                        target_count = 0
                sessions.append(
                    {
                        "date": entry.name,
                        "target_count": max(0, target_count),
                        "has_html": (entry / "session_schedule.html").exists(),
                    }
                )
        return render_template("archive.html", sessions=sessions)

    @app.route("/archive/<date>")
    def archive_session(date):
        if not _looks_like_date(date):
            abort(404)
        archive_root = current_app.config["OUTPUT_DIR"].parent / "archive"
        archive_dir = archive_root / date
        if not archive_dir.is_dir():
            abort(404)
        schedule_html = archive_dir / "session_schedule.html"
        if not schedule_html.exists():
            abort(404)
        return send_from_directory(str(archive_dir), "session_schedule.html")

    # --- Layer 3: NINA monitor ---

    @app.route("/nina")
    def nina_dashboard():
        nina_targets_path = current_app.config["OUTPUT_DIR"] / "nina_targets.csv"
        return render_template(
            "nina.html",
            base_url=current_app.config["NINA"].base_url,
            nina_targets_exists=nina_targets_path.exists(),
            nina_targets_path=str(nina_targets_path),
            nina_push_result=request.args.get("push_result"),
        )

    @app.route("/nina/partial")
    def nina_partial():
        nina = current_app.config["NINA"]
        status = nina.status()
        return render_template("nina_partial.html", status=status, base_url=nina.base_url)

    @app.route("/nina/push-schedule", methods=["POST"])
    def nina_push_schedule():
        nina = current_app.config["NINA"]
        csv_path = current_app.config["OUTPUT_DIR"] / "nina_targets.csv"
        if not csv_path.exists():
            return redirect(url_for("nina_dashboard", push_result="no-schedule"))
        result = nina.push_schedule(str(csv_path))
        outcome = "ok" if result.get("ok") else "failed"
        return redirect(url_for("nina_dashboard", push_result=outcome))


# --- Background-task implementations ---

class _RecordReporter:
    """Adapt RunRecord.log/set_progress onto the tonight_pipeline.Reporter
    protocol so the webapp can use the shared pipeline."""

    def __init__(self, record: RunRecord) -> None:
        self._record = record

    def log(self, message: str) -> None:
        self._record.log(message)

    def progress(self, fraction: float) -> None:
        self._record.set_progress(fraction)


def _execute_tonight(record: RunRecord, config_path: str, hours: float, mode: str | None, output_dir: Path) -> dict:
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
    result = run_tonight_pipeline(opts, _RecordReporter(record))
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


def _execute_submit(
    record: RunRecord,
    target_dir: Path,
    target_name: str,
    comp_path: Path | None,
    observer_code: str,
    chart_id: str,
    target_slug: str | None = None,
    session_date: str | None = None,
    runs: RunRegistry | None = None,
    session_store=None,  # webapp.db.SessionStore
) -> dict:
    from ..photometry import write_aavso_extended_file
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
            target_max_mag=vsx_target.max_mag,
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
    # `observations` stores the full per-frame data needed to regenerate an
    # AAVSO file when the user deselects frames before download.
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
        obs_dict = None
        if not is_failure:
            from ..photometry import Observation
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
            del Observation  # silence unused import warning while keeping the block tidy

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

    # The pipeline already flagged outliers on its FrameRecord list. Mirror
    # those flags onto the dict copies the template renders.
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
    upload_path = target_dir / f"aavso_{target_name.replace(' ', '_').replace('/', '_')}.txt"
    write_aavso_extended_file(
        result.observations,
        upload_path,
        observer_code=observer_code,
        chart_id=chart_id,
    )
    observations = result.observations

    record.log(f"Median mag {median_mag:.3f}; wrote {upload_path.name}")
    record.result["aavso_preview"] = _read_aavso_preview(upload_path, max_rows=5)

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

    prior_sessions = _collect_prior_session_observations(runs, target_slug, record.run_id)
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


def _collect_prior_session_observations(
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


def _read_aavso_preview(path: Path, max_rows: int = 5) -> str:
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
            target_root = _resolve_scheduled_target_dir(captures_root, target_name)
            slug = target_root.name if target_root else target_name.replace(" ", "_")

            # Pick the most-recent capture session (dated subdir) or the flat
            # layout if no dated subdirs exist.
            session_date: str | None = None
            fits_count = 0
            if target_root:
                sessions = _list_capture_sessions(target_root)
                if sessions:
                    latest = sessions[-1]
                    session_date = latest["date"]
                    fits_count = latest["fits_count"]

            run = runs_by_kind.get(_submit_kind(slug, session_date))
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


def _read_overflow_targets(overflow_csv: Path) -> list[dict]:
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
                        "max_mag": row.get("max_mag", "") or "—",
                        "best_local_time": row.get("best_local_time", "") or "—",
                        "score": row.get("score", "") or "—",
                    }
                )
    except OSError:
        return []
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
        sessions = _list_capture_sessions(entry)
        for session in sessions:
            targets.append(
                {
                    "slug": entry.name,
                    "date": session["date"],
                    "name": _dir_to_target_name(entry),
                    "fits_count": session["fits_count"],
                    "path": session["path"],
                    "modified": session["modified"],
                    "upload_exists": session["upload_exists"],
                }
            )
    targets.sort(key=lambda d: d["modified"], reverse=True)
    return targets


def _request_date() -> str | None:
    """Pull a YYYY-MM-DD session marker from the current request (query
    string for GET, form for POST). Returns None if absent or malformed."""
    candidate = (request.args.get("date") or request.form.get("date") or "").strip()
    if candidate and _looks_like_date(candidate):
        return candidate
    return None


def _resolved_session_date(target_dir: Path | None) -> str | None:
    """Convert a captures dir to its YYYY-MM-DD session label, or None for
    flat layouts."""
    if target_dir is None:
        return None
    if _looks_like_date(target_dir.name):
        return target_dir.name
    return None


def _looks_like_date(name: str) -> bool:
    """YYYY-MM-DD format check for capture-session subdirectories."""
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    return name[:4].isdigit() and name[5:7].isdigit() and name[8:10].isdigit()


def _list_capture_sessions(target_dir: Path) -> list[dict]:
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
        if entry.is_dir() and _looks_like_date(entry.name):
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


def _resolve_target_dir(captures_root: Path, slug: str, date: str | None = None) -> Path | None:
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
        if not _looks_like_date(date):
            return None
        dated = resolved / date
        if not dated.is_dir():
            return None
        return dated

    sessions = _list_capture_sessions(resolved)
    if not sessions:
        return resolved if resolved.is_dir() else None
    return sessions[-1]["path"]


def _dir_to_target_name(target_dir: Path) -> str:
    """Convert a directory name like 'RR_LYR' into a VSX-style target name 'RR LYR'."""
    return target_dir.name.replace("_", " ")


def _default_comp_stars_path(target_dir: Path) -> str:
    """Suggest the path where a comp-stars JSON would live."""
    return str(target_dir / "comp_stars.json")


def _submit_kind(target_slug: str, date: str | None = None) -> str:
    """Run-record kind. Dated sessions get a separate kind so each
    (target, date) tuple has its own latest-run pointer."""
    if date:
        return f"submit:{target_slug}:{date}"
    return f"submit:{target_slug}"
