"""Cull math + filesystem semantics. Synthetic histories — no NINA, no
real FITS data needed."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.cull import (
    DEFAULT_MAX_HFR_FRAC,
    DEFAULT_MIN_STARS_FRAC,
    REJECTED_SUBDIR,
    CullResult,
    run_cull,
    stat_frames,
)


def _touch(p: Path) -> Path:
    p.write_bytes(b"")  # FITS contents don't matter — we never open them
    return p


def _history(*entries: tuple[str, float, float]) -> list[dict]:
    """Build a fake NINA image-history list. Each entry is
    (filename, stars, hfr) — Filename is what NINA actually returns."""
    return [
        {"Filename": name, "Stars": stars, "HFR": hfr}
        for name, stars, hfr in entries
    ]


class TestStatFrames(TestCase):
    def test_matches_by_basename_not_full_path(self) -> None:
        """NINA returns a full save-path; mira's copy lives elsewhere.
        Index by basename."""
        with TemporaryDirectory() as d:
            lights = Path(d)
            _touch(lights / "a.fit")
            _touch(lights / "b.fit")
            history = _history(
                ("C:/path/from/nina/a.fit", 200, 2.0),
                ("C:/different/dir/b.fit", 150, 2.5),
            )
            stats = stat_frames(lights, history)
            self.assertEqual(len(stats), 2)
            stars_by_name = {s.path.name: s.stars for s in stats}
            self.assertEqual(stars_by_name, {"a.fit": 200, "b.fit": 150})

    def test_no_history_match_keeps_frame_unscored(self) -> None:
        with TemporaryDirectory() as d:
            lights = Path(d)
            _touch(lights / "orphan.fit")
            stats = stat_frames(lights, [])
            self.assertEqual(len(stats), 1)
            self.assertIsNone(stats[0].stars)
            self.assertIsNone(stats[0].hfr)
            self.assertIn("no history", stats[0].note)


class TestRunCull(TestCase):
    def _setup(self, d: Path, frames: list[tuple[str, float, float]]) -> Path:
        lights = d / "lights"
        lights.mkdir()
        for name, _, _ in frames:
            _touch(lights / name)
        return lights

    def test_median_relative_thresholds(self) -> None:
        """Median 100 stars across 5 good frames; floor at 0.5x = 50.
        Frame at 60 stars stays above floor (kept); cloud at 20 is below
        (rejected)."""
        frames = [
            ("good_1.fit", 100, 2.0),
            ("good_2.fit", 110, 2.1),
            ("good_3.fit",  90, 1.9),
            ("good_4.fit", 100, 2.0),
            ("good_5.fit", 105, 2.0),
            ("borderline.fit", 60, 2.0),  # above 50 floor -> kept
            ("cloud.fit",      20, 2.0),  # below 50 floor -> rejected
        ]
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), frames)
            history = _history(*[(f"x/{n}", s, h) for n, s, h in frames])
            res = run_cull(lights, history=history)
            # Median of [100,110,90,100,105,60,20] (sorted: 20,60,90,100,100,105,110)
            self.assertEqual(res.median_stars, 100)
            self.assertEqual(res.star_floor, 50.0)
            kept_names = {s.path.name for s in res.kept}
            rej_names = {s.path.name for s in res.rejected}
            self.assertEqual(rej_names, {"cloud.fit"})
            self.assertIn("borderline.fit", kept_names)
            self.assertNotIn("cloud.fit", kept_names)

    def test_hfr_ceiling_rejects_blurry_frames(self) -> None:
        frames = [
            ("sharp_1.fit", 100, 2.0),
            ("sharp_2.fit", 100, 2.1),
            ("sharp_3.fit", 100, 1.9),
            ("blur_1.fit",  100, 4.0),   # > 1.5x median (3.0) -> rejected
        ]
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), frames)
            history = _history(*[(f"x/{n}", s, h) for n, s, h in frames])
            res = run_cull(lights, history=history)
            rej_names = {s.path.name for s in res.rejected}
            self.assertEqual(rej_names, {"blur_1.fit"})

    def test_moves_rejected_to_subdir(self) -> None:
        frames = [
            ("good.fit",  100, 2.0),
            ("bad.fit",    10, 2.0),
        ]
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), frames)
            history = _history(*[(f"x/{n}", s, h) for n, s, h in frames])
            res = run_cull(lights, history=history)
            self.assertFalse((lights / "bad.fit").exists())
            self.assertTrue((lights / REJECTED_SUBDIR / "bad.fit").exists())
            self.assertTrue((lights / "good.fit").exists())

    def test_dry_run_does_not_move(self) -> None:
        frames = [
            ("good.fit",  100, 2.0),
            ("bad.fit",    10, 2.0),
        ]
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), frames)
            history = _history(*[(f"x/{n}", s, h) for n, s, h in frames])
            res = run_cull(lights, history=history, dry_run=True)
            self.assertEqual(len(res.rejected), 1)         # still flagged
            self.assertTrue((lights / "bad.fit").exists())  # but not moved
            self.assertFalse((lights / REJECTED_SUBDIR).exists())

    def test_empty_history_is_a_no_op_not_a_blanket_reject(self) -> None:
        """NINA restarted between capture and cull -> 0 history entries.
        Better to keep all frames than to nuke the session: rejected=0,
        unscored=all."""
        frames = [
            ("a.fit", 100, 2.0),
            ("b.fit",  20, 2.0),
        ]
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), frames)
            res = run_cull(lights, history=[])
            self.assertEqual(len(res.rejected), 0)
            self.assertEqual(len(res.unscored), 2)
            self.assertTrue((lights / "a.fit").exists())
            self.assertTrue((lights / "b.fit").exists())

    def test_history_fetcher_called_lazily(self) -> None:
        """`history` direct-pass beats history_fetcher; if both, direct wins."""
        called = {"n": 0}
        def fetcher():
            called["n"] += 1
            return _history(("x/a.fit", 100, 2.0))
        with TemporaryDirectory() as d:
            lights = self._setup(Path(d), [("a.fit", 100, 2.0)])
            run_cull(lights, history_fetcher=fetcher)
            self.assertEqual(called["n"], 1)

    def test_either_history_or_fetcher_required(self) -> None:
        with TemporaryDirectory() as d:
            lights = Path(d)
            with self.assertRaises(ValueError):
                run_cull(lights)        # no history, no fetcher
