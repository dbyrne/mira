"""Tests for the cross-process finish-progress sink."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.finish_progress import (
    FinishProgress,
    default_progress_dir,
    load,
    load_all,
    plan_phases,
)


class TestPlanPhases(TestCase):
    def test_all_flags_full_order(self) -> None:
        self.assertEqual(
            plan_phases(do_bg=True, do_denoise=True, do_deconv=True),
            ["background-extraction", "denoising", "deconv-obj", "stretch", "crop"],
        )

    def test_flags_off_subset_but_stretch_crop_always(self) -> None:
        self.assertEqual(
            plan_phases(do_bg=False, do_denoise=False, do_deconv=False),
            ["stretch", "crop"],
        )
        self.assertEqual(
            plan_phases(do_bg=True, do_denoise=False, do_deconv=True),
            ["background-extraction", "deconv-obj", "stretch", "crop"],
        )

    def test_default_dir_shared_name(self) -> None:
        self.assertEqual(default_progress_dir("X").name, "finish_progress")


class TestAdvance(TestCase):
    def _fp(self, d: str) -> FinishProgress:
        return FinishProgress.create(
            label="finish: m.tif -> m.png",
            input_path="m.tif",
            phase_ids=["background-extraction", "stretch", "crop"],
            progress_dir=Path(d),
        )

    def test_advance_marks_prev_done_next_running(self) -> None:
        with TemporaryDirectory() as d:
            fp = self._fp(d)
            self.assertTrue(all(p["status"] == "pending" for p in fp.phases))
            cb = fp.make_on_step()
            cb("GraXpert background-extraction…")
            self.assertEqual(fp.phases[0]["status"], "running")
            cb("Siril autostretch…")
            self.assertEqual(fp.phases[0]["status"], "done")
            self.assertEqual(fp.phases[1]["status"], "running")
            self.assertAlmostEqual(fp.progress, 1 / 3)

    def test_complete_closes_all(self) -> None:
        with TemporaryDirectory() as d:
            fp = self._fp(d)
            fp.make_on_step()("x")
            fp.complete("out.png")
            self.assertEqual(fp.status, "done")
            self.assertTrue(all(p["status"] == "done" for p in fp.phases))
            self.assertEqual(fp.progress, 1.0)
            self.assertEqual(load(Path(d), fp.run_id)["output_path"], "out.png")

    def test_fail_marks_running_failed(self) -> None:
        with TemporaryDirectory() as d:
            fp = self._fp(d)
            fp.make_on_step()("x")  # phase 0 running
            fp.fail("boom")
            self.assertEqual(fp.status, "failed")
            self.assertEqual(fp.phases[0]["status"], "failed")
            snap = load(Path(d), fp.run_id)
            self.assertEqual(snap["status"], "failed")
            self.assertEqual(snap["error"], "boom")


class TestPersistence(TestCase):
    def test_write_load_roundtrip_and_ordering(self) -> None:
        with TemporaryDirectory() as d:
            a = FinishProgress.create(label="a", input_path="a.tif",
                                      phase_ids=["stretch", "crop"], progress_dir=Path(d))
            a.created_at = "2026-05-18T00:00:00+00:00"
            a.write()
            b = FinishProgress.create(label="b", input_path="b.tif",
                                      phase_ids=["stretch", "crop"], progress_dir=Path(d))
            b.created_at = "2026-05-18T01:00:00+00:00"
            b.write()
            (Path(d) / "garbage.json").write_text("{ not json", encoding="utf-8")
            allruns = load_all(Path(d))
            self.assertEqual([r["label"] for r in allruns], ["b", "a"])  # newest first
            self.assertIsNone(load(Path(d), "nope"))

    def test_load_all_missing_dir_is_empty(self) -> None:
        with TemporaryDirectory() as d:
            self.assertEqual(load_all(Path(d) / "nope"), [])
