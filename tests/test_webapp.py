from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from anomaly_scout.webapp import create_app
from anomaly_scout.webapp.nina_client import NinaStatus


class WebappRoutesTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.output_dir = Path(self.tmp.name) / "out"
        self.output_dir.mkdir()
        self.captures_root = Path(self.tmp.name) / "captures"
        self.captures_root.mkdir()
        self.state_dir = Path(self.tmp.name) / "runs"
        self.app = create_app(
            output_dir=self.output_dir,
            captures_root=self.captures_root,
            nina_base_url="http://localhost:1888",
            state_dir=self.state_dir,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_index_renders(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Generate tonight", response.data)

    def test_schedule_missing(self) -> None:
        # No session_schedule.html generated yet
        response = self.client.get("/schedule")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"No schedule generated yet", response.data)

    def test_schedule_present(self) -> None:
        (self.output_dir / "session_schedule.html").write_text("<h1>hi</h1>", encoding="utf-8")
        response = self.client.get("/schedule")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<h1>hi</h1>", response.data)

    def test_photometry_index_empty(self) -> None:
        response = self.client.get("/photometry")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No captures found", response.data)

    def test_photometry_index_lists_target_dirs(self) -> None:
        target_dir = self.captures_root / "RR_LYR"
        target_dir.mkdir()
        (target_dir / "frame001.fits").write_bytes(b"\x00" * 100)
        response = self.client.get("/photometry")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"RR LYR", response.data)

    def test_photometry_target_unknown_404s(self) -> None:
        response = self.client.get("/photometry/unknown_target")
        self.assertEqual(response.status_code, 404)

    def test_photometry_target_renders(self) -> None:
        target_dir = self.captures_root / "AB_AUR"
        target_dir.mkdir()
        (target_dir / "frame001.fits").write_bytes(b"\x00" * 100)
        response = self.client.get("/photometry/AB_AUR")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"AB AUR", response.data)
        self.assertIn(b"Run photometry", response.data)

    def test_run_404_for_unknown_id(self) -> None:
        response = self.client.get("/run/zzz")
        self.assertEqual(response.status_code, 404)

    def test_nina_dashboard_renders(self) -> None:
        response = self.client.get("/nina")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NINA live status", response.data)

    def test_nina_partial_when_unreachable(self) -> None:
        nina = self.app.config["NINA"]
        with patch.object(nina, "status", return_value=NinaStatus(reachable=False, error="connection refused")):
            response = self.client.get("/nina/partial")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NINA not reachable", response.data)

    def test_run_record_persists_and_reloads_after_restart(self) -> None:
        from anomaly_scout.webapp.runs import RunRegistry

        state_dir = Path(self.tmp.name) / "persist-test"
        registry = RunRegistry(state_dir=state_dir)

        def quick_task(record):
            record.log("doing work")
            return {"answer": 42}

        record = registry.submit("test", "tiny task", quick_task)
        # Wait for completion
        import time
        for _ in range(50):
            if record.status in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(record.status, "done")
        self.assertEqual(record.result, {"answer": 42})

        # New registry sees the record
        registry2 = RunRegistry(state_dir=state_dir)
        loaded = registry2.get(record.run_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "done")
        self.assertEqual(loaded.label, "tiny task")
        self.assertEqual(loaded.result, {"answer": 42})

    def test_in_flight_run_marked_failed_on_restart(self) -> None:
        from anomaly_scout.webapp.runs import RunRecord, RunRegistry

        state_dir = Path(self.tmp.name) / "inflight-test"
        state_dir.mkdir()

        # Manually drop a "running" record JSON into the state dir, simulating a
        # process that died mid-task.
        from datetime import datetime, timezone
        import json
        running = RunRecord(
            run_id="ghost",
            kind="tonight",
            label="lost run",
            status="running",
            log_lines=["[12:00:00] Started: lost run"],
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        (state_dir / "ghost.json").write_text(json.dumps(running.to_dict()), encoding="utf-8")

        registry = RunRegistry(state_dir=state_dir)
        loaded = registry.get("ghost")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "failed")
        self.assertIn("lost on server restart", loaded.error)

    def test_photometry_index_shows_scheduled_status(self) -> None:
        # Drop a session_schedule.csv into output_dir so the index can pick it up
        schedule = (
            "order,start_local,end_local,name,ra_deg,dec_deg,max_mag,var_type,"
            "exposure_seconds,frame_count,integration_minutes,score,effective_score\n"
            "1,2026-05-05T20:00:00-04:00,2026-05-05T20:30:00-04:00,RR Lyr,291.366,42.785,7.06,RRAB,15,60,15,90.0,90.0\n"
            "2,2026-05-05T20:33:00-04:00,2026-05-05T21:03:00-04:00,RU Leo,163.289,24.358,10.30,LB,30,60,30,85.0,85.0\n"
        )
        (self.output_dir / "session_schedule.csv").write_text(schedule, encoding="utf-8")

        # RR Lyr has captures, RU Leo doesn't
        rr_lyr = self.captures_root / "RR_Lyr"
        rr_lyr.mkdir()
        (rr_lyr / "frame001.fits").write_bytes(b"\x00" * 100)

        response = self.client.get("/photometry")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        self.assertIn("Tonight's plan", body)
        self.assertIn("RR Lyr", body)
        self.assertIn("RU Leo", body)
        # RR Lyr captured but not processed → "ready for photometry"
        self.assertIn("ready for photometry", body)
        # RU Leo no captures → "awaiting capture"
        self.assertIn("awaiting capture", body)

    def test_mark_submitted_persists_timestamp(self) -> None:
        from anomaly_scout.webapp.runs import RunRegistry

        # Set up a target with captures and a "done" run record
        rr_lyr = self.captures_root / "RR_LYR"
        rr_lyr.mkdir()
        (rr_lyr / "frame001.fits").write_bytes(b"\x00" * 100)

        runs: RunRegistry = self.app.config["RUNS"]

        def _quick(record):
            record.log("done")
            return {"observation_count": 1, "median_mag": 7.5}

        record = runs.submit("submit:RR_LYR", "submit: RR LYR", _quick)
        # Wait for completion
        import time
        for _ in range(50):
            if record.status in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(record.status, "done")

        response = self.client.post("/photometry/RR_LYR/mark-submitted")
        self.assertIn(response.status_code, (302, 303))

        latest = runs.latest("submit:RR_LYR")
        self.assertIsNotNone(latest.result.get("submitted_at"))

    def test_run_history_renders(self) -> None:
        response = self.client.get("/runs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Run history", response.data)

    def test_observer_code_persists_across_visits(self) -> None:
        target_dir = self.captures_root / "RR_LYR"
        target_dir.mkdir()
        (target_dir / "frame001.fits").write_bytes(b"\x00" * 100)

        # Initial visit: no saved code
        response = self.client.get("/photometry/RR_LYR")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'value="MYABC"', response.data)

        # Drop a settings.json directly to simulate prior submit
        from anomaly_scout.webapp.settings import save_settings
        save_settings(self.state_dir, {"observer_code": "MYABC"})

        # Subsequent visit: the form should be pre-populated
        response = self.client.get("/photometry/RR_LYR")
        self.assertIn(b'value="MYABC"', response.data)

    def test_download_with_selection_filters_frames(self) -> None:
        from anomaly_scout.webapp.runs import RunRegistry

        target_dir = self.captures_root / "RR_LYR"
        target_dir.mkdir()
        (target_dir / "frame001.fits").write_bytes(b"\x00" * 100)

        runs: RunRegistry = self.app.config["RUNS"]

        def _quick(record):
            record.result = {
                "frames": [
                    {"filename": "f1.fits", "magnitude": 7.5, "flag": "ok"},
                    {"filename": "f2.fits", "magnitude": 7.6, "flag": "ok"},
                    {"filename": "f3.fits", "magnitude": 9.5, "flag": "outlier"},
                ],
                "observations": [
                    {"filename": "f1.fits", "target_name": "RR LYR", "julian_date": 2461165.5,
                     "magnitude": 7.5, "magnitude_error": 0.05, "band": "TG",
                     "comp_star_label": "97", "comp_star_mag": 9.7, "chart_id": "X12345"},
                    {"filename": "f2.fits", "target_name": "RR LYR", "julian_date": 2461165.6,
                     "magnitude": 7.6, "magnitude_error": 0.05, "band": "TG",
                     "comp_star_label": "97", "comp_star_mag": 9.7, "chart_id": "X12345"},
                    {"filename": "f3.fits", "target_name": "RR LYR", "julian_date": 2461165.7,
                     "magnitude": 9.5, "magnitude_error": 0.10, "band": "TG",
                     "comp_star_label": "97", "comp_star_mag": 9.7, "chart_id": "X12345"},
                ],
                "target_name": "RR LYR",
                "observer_code": "ABC",
                "chart_id": "X12345",
            }
            return record.result

        record = runs.submit("submit:RR_LYR", "submit: RR LYR", _quick)
        import time
        for _ in range(50):
            if record.status in ("done", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(record.status, "done")

        # Submit selection: only f1 and f2 (drop the outlier)
        from werkzeug.datastructures import MultiDict
        response = self.client.post(
            "/photometry/RR_LYR/download-with-selection",
            data=MultiDict([("include", "f1.fits"), ("include", "f2.fits")]),
        )
        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        # The AAVSO file must contain f1 + f2 rows but not f3 (the outlier)
        self.assertIn("RR LYR", body)
        self.assertIn("2461165.50000", body)
        self.assertIn("2461165.60000", body)
        self.assertNotIn("2461165.70000", body)

    def test_download_with_selection_rejects_empty(self) -> None:
        from anomaly_scout.webapp.runs import RunRegistry

        target_dir = self.captures_root / "RR_LYR"
        target_dir.mkdir()
        (target_dir / "frame001.fits").write_bytes(b"\x00" * 100)

        runs: RunRegistry = self.app.config["RUNS"]

        def _quick(record):
            record.result = {
                "frames": [],
                "observations": [
                    {"filename": "f1.fits", "target_name": "RR LYR", "julian_date": 2461165.5,
                     "magnitude": 7.5, "magnitude_error": 0.05, "band": "TG",
                     "comp_star_label": "97", "comp_star_mag": 9.7, "chart_id": "X12345"},
                ],
                "target_name": "RR LYR",
                "observer_code": "ABC",
                "chart_id": "X12345",
            }
            return record.result

        record = runs.submit("submit:RR_LYR", "submit: RR LYR", _quick)
        import time
        for _ in range(50):
            if record.status in ("done", "failed"):
                break
            time.sleep(0.05)

        # Submit no included frames
        response = self.client.post("/photometry/RR_LYR/download-with-selection", data={})
        self.assertEqual(response.status_code, 400)

    def test_settings_page_renders_and_saves(self) -> None:
        # Initial GET shows the form with empty values
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Settings", response.data)

        # POST persists
        response = self.client.post("/settings", data={
            "observer_code": "ABC123",
            "default_config": "config/multi_site.yaml",
            "default_hours": "6",
        })
        self.assertEqual(response.status_code, 200)

        from anomaly_scout.webapp.settings import load_settings
        settings = load_settings(self.state_dir)
        self.assertEqual(settings.get("observer_code"), "ABC123")
        self.assertEqual(settings.get("default_config"), "config/multi_site.yaml")
        self.assertAlmostEqual(settings.get("default_hours"), 6.0)

    def test_settings_clamp_hours_range(self) -> None:
        # Out-of-range hours get clamped
        self.client.post("/settings", data={
            "observer_code": "X",
            "default_config": "config/x.yaml",
            "default_hours": "0.1",
        })
        from anomaly_scout.webapp.settings import load_settings
        self.assertAlmostEqual(load_settings(self.state_dir).get("default_hours"), 0.5)

        self.client.post("/settings", data={
            "observer_code": "X",
            "default_config": "config/x.yaml",
            "default_hours": "99",
        })
        self.assertAlmostEqual(load_settings(self.state_dir).get("default_hours"), 14.0)

    def test_dashboard_uses_saved_defaults(self) -> None:
        from anomaly_scout.webapp.settings import save_settings
        save_settings(self.state_dir, {
            "default_config": "config/zerg.yaml",
            "default_hours": 7.5,
        })
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"config/zerg.yaml", response.data)
        self.assertIn(b'value="7.5"', response.data)

    def test_overflow_section_appears_on_photometry_index(self) -> None:
        overflow = (
            "name,ra_deg,dec_deg,max_mag,var_type,score,best_local_time\n"
            "FF Dra,180.0,55.0,8.67,LB,73.3,21:30\n"
            "VV Leo,170.0,30.0,9.30,SR,72.7,21:30\n"
        )
        (self.output_dir / "session_overflow.csv").write_text(overflow, encoding="utf-8")
        response = self.client.get("/photometry")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Deferred", response.data)
        self.assertIn(b"FF Dra", response.data)
        self.assertIn(b"VV Leo", response.data)

    def test_nina_push_returns_failed_when_unreachable(self) -> None:
        from anomaly_scout.webapp.nina_client import NinaClient
        from unittest.mock import patch

        # No schedule yet → no-schedule outcome
        response = self.client.post("/nina/push-schedule", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No schedule found", response.data)

        # With schedule but NINA unreachable → failed outcome
        (self.output_dir / "nina_targets.csv").write_text("Type,Name\nVariable Star,RR Lyr\n", encoding="utf-8")
        nina = self.app.config["NINA"]
        with patch.object(nina, "push_schedule", return_value={"ok": False, "status_code": None, "message": "down", "endpoint_tried": "/api/v2/sequence/load"}):
            response = self.client.post("/nina/push-schedule", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NINA rejected the push", response.data)

    def test_aavso_preview_helper_truncates_data_rows(self) -> None:
        from anomaly_scout.webapp.routes import _read_aavso_preview
        path = self.output_dir / "preview.txt"
        rows = ["#TYPE=Extended", "#OBSCODE=ABC", "#NAME,DATE,MAG,MERR,FILT"]
        for i in range(10):
            rows.append(f"RR LYR,2461165.{i:03d},7.{i:03d},0.05,TG,NO,STD,97,9.7,na,0.0,na,na,na,na")
        path.write_text("\n".join(rows), encoding="utf-8")
        preview = _read_aavso_preview(path, max_rows=3)
        # Preview must contain headers + 3 data rows + ellipsis
        self.assertIn("#TYPE=Extended", preview)
        self.assertIn("2461165.000", preview)
        self.assertIn("2461165.002", preview)
        self.assertNotIn("2461165.005", preview)  # truncated
        self.assertIn("more data rows", preview)

    def test_first_light_renders_with_no_state(self) -> None:
        # Empty state: no schedule, no settings, NINA unreachable
        from anomaly_scout.webapp.nina_client import NinaStatus
        from unittest.mock import patch

        nina = self.app.config["NINA"]
        with patch.object(nina, "status", return_value=NinaStatus(reachable=False, error="down")):
            response = self.client.get("/first-light")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"First-light walkthrough", response.data)
        # All steps default to todo state
        self.assertIn(b"walk-todo", response.data)

    def test_first_light_marks_steps_done(self) -> None:
        from anomaly_scout.webapp.nina_client import NinaStatus
        from anomaly_scout.webapp.settings import save_settings
        from unittest.mock import patch

        save_settings(self.state_dir, {"observer_code": "ABC"})
        # Drop a schedule
        schedule = (
            "order,start_local,end_local,name,ra_deg,dec_deg,max_mag,var_type,"
            "exposure_seconds,frame_count,integration_minutes,score,effective_score\n"
            "1,2026-05-05T20:00:00-04:00,2026-05-05T20:30:00-04:00,RR Lyr,291,42,7.06,RRAB,15,60,15,90,90\n"
        )
        (self.output_dir / "session_schedule.csv").write_text(schedule, encoding="utf-8")

        nina = self.app.config["NINA"]
        with patch.object(nina, "status", return_value=NinaStatus(reachable=True)):
            response = self.client.get("/first-light")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        # Three of the six steps should be done
        self.assertGreaterEqual(body.count("walk-done"), 3)

    def test_dashboard_lifetime_stats(self) -> None:
        from anomaly_scout.webapp.runs import RunRegistry

        runs: RunRegistry = self.app.config["RUNS"]

        def _ok(record):
            record.result = {"observation_count": 10, "median_mag": 7.5}
            return record.result

        def _anomaly(record):
            record.result = {
                "observation_count": 8,
                "median_mag": 9.5,
                "anomaly": {"level": "anomaly", "flags": ["1.5 mag fainter"]},
            }
            return record.result

        r1 = runs.submit("submit:RR_LYR", "submit: RR LYR", _ok)
        r2 = runs.submit("submit:AB_AUR", "submit: AB AUR", _anomaly)
        import time
        for _ in range(50):
            if r1.status == "done" and r2.status == "done":
                break
            time.sleep(0.05)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        self.assertIn("Lifetime stats", body)
        self.assertIn("Photometry sessions", body)
        # 1 anomaly run should surface in the callout
        self.assertIn("Most recent anomaly", body)
        self.assertIn("AB AUR", body)

    def test_nina_partial_when_connected(self) -> None:
        status = NinaStatus(
            reachable=True,
            sequence_running=True,
            current_target="RR Lyr",
            target_progress="23/60 frames",
            equipment={"Camera": "connected", "Telescope": "connected"},
        )
        nina = self.app.config["NINA"]
        with patch.object(nina, "status", return_value=status):
            response = self.client.get("/nina/partial")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"RR Lyr", response.data)
        self.assertIn(b"23/60 frames", response.data)
