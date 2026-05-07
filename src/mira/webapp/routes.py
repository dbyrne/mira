"""HTTP route registration for the webapp.

Route handlers stay focused on parsing requests, rendering templates,
and returning responses. The substantive work happens elsewhere:
- ``webapp._paths`` — capture-disk discovery, session date helpers,
  schedule-CSV parsing, run-kind formatting.
- ``webapp._runner`` — long-running pipeline drivers (tonight + submit)
  that run in the RunRegistry's ThreadPoolExecutor.
- ``submit_pipeline`` and ``tonight_pipeline`` — pure orchestration
  shared with the CLI.
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from ._paths import (
    build_schedule_status,
    default_comp_stars_path,
    dir_to_target_name,
    discover_capture_targets,
    list_capture_sessions,
    looks_like_date,
    read_overflow_targets,
    request_date,
    resolve_target_dir,
    resolved_session_date,
    submit_kind,
)
from ._runner import execute_submit, execute_tonight, read_aavso_preview
from .runs import RunRegistry


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
            target_callable=lambda rec: execute_tonight(rec, config_path, hours, mode, output_dir),
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
        targets = discover_capture_targets(captures_root)
        runs_by_kind = {r.kind: r for r in runs.all() if r.kind.startswith("submit:")}
        scheduled = build_schedule_status(output_dir / "session_schedule.csv", captures_root, runs_by_kind)
        overflow = read_overflow_targets(output_dir / "session_overflow.csv")
        return render_template(
            "photometry_index.html",
            targets=targets,
            captures_root=captures_root,
            scheduled=scheduled,
            overflow=overflow,
        )

    @app.route("/photometry/<target_slug>")
    def photometry_target(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = resolved_session_date(target_dir)
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(submit_kind(target_slug, resolved_date))
        from .settings import load_settings

        settings = load_settings(current_app.config.get("STATE_DIR"))
        target_root = captures_root / target_slug
        sessions = list_capture_sessions(target_root) if target_root.is_dir() else []
        return render_template(
            "photometry_target.html",
            target_slug=target_slug,
            target_dir=target_dir,
            target_name=dir_to_target_name(target_root if target_root.is_dir() else target_dir),
            run=record,
            comp_star_default=default_comp_stars_path(target_dir),
            saved_observer_code=settings.get("observer_code", ""),
            session_date=resolved_date,
            sessions=sessions,
        )

    @app.route("/photometry/<target_slug>/run", methods=["POST"])
    def trigger_photometry(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = resolved_session_date(target_dir)

        comp_stars_input = request.form.get("comp_stars", "").strip()
        comp_path: Path | None = None
        if comp_stars_input:
            candidate = Path(comp_stars_input).resolve()
            if not candidate.exists():
                # Don't echo the resolved path back: probing for which
                # files exist on the server is exactly the kind of
                # information leak we don't want from a form input.
                return render_template(
                    "photometry_target.html",
                    target_slug=target_slug,
                    target_dir=target_dir,
                    target_name=request.form.get("target_name", "").strip()
                    or dir_to_target_name(target_dir),
                    run=None,
                    error="Comp-stars JSON not found at the path you provided.",
                    comp_star_default=default_comp_stars_path(target_dir),
                    session_date=resolved_date,
                    sessions=[],
                ), 400
            comp_path = candidate

        observer_code = request.form.get("observer_code", "").strip()
        chart_id = request.form.get("chart_id", "").strip() or "na"
        target_name = request.form.get("target_name", "").strip() or dir_to_target_name(target_dir)

        if not observer_code:
            return render_template(
                "photometry_target.html",
                target_slug=target_slug,
                target_dir=target_dir,
                target_name=target_name,
                run=None,
                error="Observer code is required.",
                comp_star_default=default_comp_stars_path(target_dir),
                session_date=resolved_date,
                sessions=[],
            ), 400

        runs: RunRegistry = current_app.config["RUNS"]
        from .settings import update_setting

        update_setting(current_app.config.get("STATE_DIR"), "observer_code", observer_code)
        session_store = current_app.config.get("SESSION_STORE")

        runs.submit(
            kind=submit_kind(target_slug, resolved_date),
            label=f"submit: {target_name}" + (f" [{resolved_date}]" if resolved_date else ""),
            target_callable=lambda rec: execute_submit(
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
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        resolved_date = resolved_session_date(target_dir) if target_dir else date
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(submit_kind(target_slug, resolved_date))
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
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None or not (target_dir / "lightcurve.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve.png")

    @app.route("/photometry/<target_slug>/lightcurve_folded.png")
    def photometry_lightcurve_folded(target_slug):
        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None or not (target_dir / "lightcurve_folded.png").exists():
            abort(404)
        return send_from_directory(str(target_dir), "lightcurve_folded.png")

    @app.route("/photometry/<target_slug>/mark-submitted", methods=["POST"])
    def photometry_mark_submitted(target_slug):
        from datetime import datetime, timezone

        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        resolved_date = resolved_session_date(target_dir) if target_dir else date

        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(submit_kind(target_slug, resolved_date))
        if record is None or record.status != "done":
            abort(404)
        if record.result is None:
            record.result = {}
        record.result["submitted_at"] = datetime.now(timezone.utc).isoformat()
        record.log("Marked as submitted to AAVSO WebObs.")
        runs.persist(record)
        # Also flush submission to SQLite if available.
        store = current_app.config.get("SESSION_STORE")
        if store is not None:
            store.mark_submitted(record.run_id, record.result["submitted_at"])
        return redirect(url_for("photometry_target", target_slug=target_slug, date=resolved_date))

    @app.route("/photometry/<target_slug>/download-with-selection", methods=["POST"])
    def photometry_download_selected(target_slug):
        from ..photometry import Observation, aavso_filename, write_aavso_extended_file

        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        resolved_date = resolved_session_date(target_dir)
        runs: RunRegistry = current_app.config["RUNS"]
        record = runs.latest(submit_kind(target_slug, resolved_date))
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
        upload_path = target_dir / aavso_filename(target_name)
        write_aavso_extended_file(
            observations,
            upload_path,
            observer_code=observer_code,
            chart_id=chart_id,
        )
        record.log(f"Re-wrote AAVSO file with {len(observations)} of {len(record.result.get('observations', []))} frames.")
        record.result["aavso_preview"] = read_aavso_preview(upload_path, max_rows=5)
        runs.persist(record)
        return send_from_directory(str(target_dir), upload_path.name, as_attachment=True)

    @app.route("/photometry/<target_slug>/upload")
    def photometry_upload(target_slug):
        from ..photometry import aavso_filename

        captures_root: Path = current_app.config["CAPTURES_ROOT"]
        date = request_date()
        target_dir = resolve_target_dir(captures_root, target_slug, date)
        if target_dir is None:
            abort(404)
        target_root = captures_root / target_slug
        target_name = dir_to_target_name(target_root if target_root.is_dir() else target_dir)
        upload_path = target_dir / aavso_filename(target_name)
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
        scheduled = build_schedule_status(schedule_csv, captures_root, runs_by_kind)
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
                if not entry.is_dir() or not looks_like_date(entry.name):
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
        if not looks_like_date(date):
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
