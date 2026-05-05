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
        self.app = create_app(
            output_dir=self.output_dir,
            captures_root=self.captures_root,
            nina_base_url="http://localhost:1888",
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
        self.assertIn(b"No FITS-containing", response.data)

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
