"""Webapp finish view: launch validation + monitoring of CLI-started runs.

The 'monitor CLI-started runs too' requirement is the key thing tested:
the detail/partial routes read the shared progress JSON, NOT the
in-memory RunRegistry, so a run written by a separate process renders.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.finish_progress import FinishProgress
from mira.webapp import create_app


class WebappFinishTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        base = Path(self.tmp.name)
        self.finish_dir = base / "finish_progress"
        self.app = create_app(
            output_dir=base / "out",
            captures_root=base / "captures",
            state_dir=base / "runs",
            finish_progress_dir=self.finish_dir,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_nav_and_index_render(self) -> None:
        # url_for('finish_index') must resolve in base.html, and the page renders.
        self.assertEqual(self.client.get("/").status_code, 200)
        r = self.client.get("/finish")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Siril finishing", r.data)
        self.assertIn(b"No finish runs yet", r.data)

    def test_launch_rejects_missing_input(self) -> None:
        r = self.client.post("/finish/run", data={"input": "C:/nope/x.tif"})
        self.assertEqual(r.status_code, 400)
        self.assertIn(b"Input not found", r.data)

    def test_monitors_cli_started_run(self) -> None:
        # Simulate a `mira finish` run from the terminal: another process
        # wrote this JSON into the shared dir.
        fp = FinishProgress.create(
            label="finish: m51_hi.tif -> m51.png",
            input_path="m51_hi.tif",
            phase_ids=["background-extraction", "denoising", "stretch", "crop"],
            progress_dir=self.finish_dir,
        )
        fp.make_on_step()("bg")  # phase 0 running

        # It appears in the list...
        idx = self.client.get("/finish")
        self.assertIn(b"m51_hi.tif", idx.data)

        # ...and the detail + partial render its phases from the JSON.
        detail = self.client.get(f"/finish/{fp.run_id}")
        self.assertEqual(detail.status_code, 200)
        partial = self.client.get(f"/finish/{fp.run_id}/partial")
        self.assertEqual(partial.status_code, 200)
        self.assertIn(b"GraXpert background extraction", partial.data)
        self.assertIn(b"GraXpert AI denoise", partial.data)
        self.assertIn(b"running", partial.data)

        # Completing it (as the CLI process would) is reflected on next poll.
        fp.complete("m51.png")
        partial2 = self.client.get(f"/finish/{fp.run_id}/partial")
        self.assertIn(b"status-done", partial2.data)
        self.assertIn(b"m51.png", partial2.data)

    def test_unknown_run_404(self) -> None:
        self.assertEqual(self.client.get("/finish/deadbeef").status_code, 404)
        self.assertEqual(self.client.get("/finish/deadbeef/partial").status_code, 404)
