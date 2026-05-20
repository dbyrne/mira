"""End-to-end FITS-mode cull tests — clouds, trailing, mixed-WCS
solve-failed bucket, never-solved legacy dir, dry-run. Uses the synthetic
FITS helper from test_fits_stats."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.cull import REJECTED_SUBDIR, run_cull
from tests.test_fits_stats import _synth_fits


class TestCullFromFits(TestCase):
    def test_rejects_cloudy_frame_by_sky_median(self) -> None:
        # Eight normal frames (bg=1000) + one cloudy (bg=4000 > 2x median).
        # 8 ref frames keeps the per-metric median stable against the
        # RNG jitter of the planted-star generator.
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(8):
                _synth_fits(lights / f"ok_{i}.fit", bg=1000.0, seed=i)
            _synth_fits(lights / "cloudy.fit", bg=4000.0, seed=100)
            res = run_cull(lights, from_fits=True, dry_run=True)
            rejected = {s.path.name for s in res.rejected}
            self.assertIn("cloudy.fit", rejected)
            # The reason cited must mention sky (not e.g. stars/HFR).
            cloudy = next(s for s in res.rejected if s.path.name == "cloudy.fit")
            self.assertIn("sky=", cloudy.note)

    def test_rejects_trailed_frame_by_roundness(self) -> None:
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(5):
                _synth_fits(lights / f"ok_{i}.fit", seed=i)
            _synth_fits(lights / "trail.fit", elongate=True, seed=99)
            res = run_cull(lights, from_fits=True, dry_run=True)
            self.assertIn("trail.fit", {s.path.name for s in res.rejected})

    def test_solve_failed_bucket_on_mixed_wcs_dir(self) -> None:
        # 4 frames with WCS, 2 without — the unsolved ones go to the
        # solve_failed bucket (a strong quality signal in its own right).
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(4):
                _synth_fits(lights / f"solved_{i}.fit", add_wcs=True, seed=i)
            for i in range(2):
                _synth_fits(lights / f"unsolved_{i}.fit", add_wcs=False, seed=10+i)
            res = run_cull(lights, from_fits=True, dry_run=True)
            sf_names = {s.path.name for s in res.solve_failed}
            self.assertEqual(sf_names, {"unsolved_0.fit", "unsolved_1.fit"})
            # solve-failed entries are also in rejected (they get moved).
            rejected_names = {s.path.name for s in res.rejected}
            self.assertTrue(sf_names.issubset(rejected_names))
            for s in res.solve_failed:
                self.assertIn("solve failed", s.note)

    def test_never_solved_dir_does_not_trigger_solve_failed_bucket(self) -> None:
        # Legacy: nothing has WCS, so "no WCS" carries no signal.
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(5):
                _synth_fits(lights / f"legacy_{i}.fit", add_wcs=False, seed=i)
            res = run_cull(lights, from_fits=True, dry_run=True)
            self.assertEqual(res.solve_failed, [])     # no false positive
            # And scoring still works on the rest.
            self.assertGreater(len(res.kept) + len(res.rejected), 0)

    def test_dry_run_does_not_move_files(self) -> None:
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(4):
                _synth_fits(lights / f"ok_{i}.fit", bg=1000, seed=i)
            _synth_fits(lights / "cloudy.fit", bg=4000, seed=99)
            res = run_cull(lights, from_fits=True, dry_run=True)
            self.assertTrue((lights / "cloudy.fit").exists())
            self.assertFalse((lights / REJECTED_SUBDIR).exists())
            self.assertTrue(any(s.path.name == "cloudy.fit"
                                for s in res.rejected))

    def test_real_move_lands_in_rejected_subdir(self) -> None:
        with TemporaryDirectory() as d:
            lights = Path(d)
            for i in range(4):
                _synth_fits(lights / f"ok_{i}.fit", bg=1000, seed=i)
            _synth_fits(lights / "cloudy.fit", bg=4000, seed=99)
            res = run_cull(lights, from_fits=True, dry_run=False)
            self.assertFalse((lights / "cloudy.fit").exists())
            self.assertTrue(
                (lights / REJECTED_SUBDIR / "cloudy.fit").exists())
            self.assertTrue((lights / "ok_0.fit").exists())

    def test_empty_dir_is_a_no_op(self) -> None:
        with TemporaryDirectory() as d:
            res = run_cull(Path(d), from_fits=True)
            self.assertEqual(res.kept, [])
            self.assertEqual(res.rejected, [])

    def test_wcs_targeted_sky_picks_up_target_region(self) -> None:
        # A bright corner blob + WCS: with target coords on the blob, the
        # frame's sky_median is much higher than a frame without the blob,
        # and crosses the cull's max_sky_frac threshold.
        with TemporaryDirectory() as d:
            lights = Path(d)
            # 5 reference frames: WCS, no blob.
            for i in range(5):
                _synth_fits(lights / f"clean_{i}.fit", add_wcs=True,
                            bg=1000, seed=i)
            # 1 frame with WCS and a bright blob at the corner.
            _synth_fits(lights / "blob.fit", add_wcs=True, bg=1000,
                        bright_patch=(0.85, 0.85, 4000), seed=99)
            # Target = corner pixel ~(170,170) in the un-binned 200x200
            # frame (see test_fits_stats for the math).
            res = run_cull(
                lights, from_fits=True, dry_run=True,
                target_ra=179.93, target_dec=0.07,
            )
            self.assertIn("blob.fit", {s.path.name for s in res.rejected})
