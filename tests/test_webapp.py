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
