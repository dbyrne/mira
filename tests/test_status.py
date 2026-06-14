"""Tests for `mira status` (live night-progress, frames-on-disk path).

The load-bearing behavior is the **transparency-gated** assessment: a soft
HFR + crashed star count must read as CLOUDS (don't cry defocus) when the
star count is swinging, and as a real focus problem only when the sky is
steady. That's the 2026-06-14 lesson, pinned here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from astropy.io import fits

from mira.monitor.disk_snapshot import assess_quality, build_snapshot_from_disk
from mira.monitor.render import render_status
from mira.monitor.snapshot import FrameStat

NOW = datetime(2026, 6, 14, 5, 0, tzinfo=timezone.utc)


def _fs(stars, hfr=1.0, roundness=0.2):
    return FrameStat(
        filename="x.fits", timestamp_utc=NOW, exposure_s=60.0, gain=80,
        filter_name="LP", stars=stars, hfr=hfr, mean=2000.0, median=2000.0,
        roundness=roundness,
    )


class TestAssessQuality(TestCase):
    def _msgs(self, frames):
        return " ".join(a.message for a in assess_quality(frames, NOW))

    def test_transparency_flag_on_swinging_stars(self):
        # Star count lurching frame-to-frame = clouds, not focus.
        msgs = self._msgs([_fs(s) for s in (3, 20, 1, 18, 2, 21)])
        self.assertIn("transparency", msgs)

    def test_focus_gated_by_transparency(self):
        # HFR high AND stars swinging -> flag clouds, NOT focus.
        msgs = self._msgs([_fs(s, hfr=1.6) for s in (2, 20, 1, 19, 3, 21)])
        self.assertIn("transparency", msgs)
        self.assertNotIn("soft", msgs)

    def test_focus_flag_only_when_sky_steady(self):
        # HFR high, stars STEADY -> a real focus problem, no transparency flag.
        msgs = self._msgs([_fs(s, hfr=1.6) for s in (40, 42, 41, 39, 43, 40)])
        self.assertIn("soft", msgs)
        self.assertNotIn("transparency", msgs)

    def test_no_flags_when_sharp_and_steady(self):
        self.assertEqual(assess_quality([_fs(s, hfr=1.0) for s in
                                         (40, 41, 42, 40, 39, 41)], NOW), [])

    def test_tracking_flag_on_elongation(self):
        msgs = self._msgs([_fs(40, hfr=1.0, roundness=0.8) for _ in range(5)])
        self.assertIn("elongated", msgs)


def _write_star_fits(path: Path, when: datetime, n_stars=30, sigma=3.0):
    rng = np.random.default_rng(7)
    img = np.full((200, 200), 1000.0, dtype=np.float32)
    img += rng.normal(0, 4, img.shape).astype(np.float32)
    yy, xx = np.mgrid[0:200, 0:200]
    for _ in range(n_stars):
        x = rng.integers(12, 188); y = rng.integers(12, 188)
        img += (9000.0 * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2)
                                  / (2 * sigma ** 2)))).astype(np.float32)
    h = fits.Header()
    h["DATE-OBS"] = when.strftime("%Y-%m-%dT%H:%M:%S")
    fits.writeto(path, img, h, overwrite=True)


class TestBuildFromDisk(TestCase):
    def test_end_to_end(self):
        with TemporaryDirectory() as d:
            dd = Path(d)
            base = datetime(2026, 6, 14, 5, 0, tzinfo=timezone.utc)
            for i in range(4):
                _write_star_fits(dd / f"f{i:03d}.fits",
                                 base + timedelta(seconds=75 * i))
            (dd / "mira_capture.json").write_text(json.dumps({
                "filter": "LP", "gain": 80, "exposure_s": 60.0,
                "ra_deg": 314.696, "dec_deg": 44.33, "target_name": "NGC 7000",
                "config": {"lat_deg": 40.7178, "lon_deg": -74.0431,
                           "alt_floor_deg": 30.0, "sun_max_deg": -15.0,
                           "dither_every": 3},
            }))
            snap = build_snapshot_from_disk(
                dd, now_utc=base + timedelta(minutes=5), recent_n=10)

        self.assertEqual(snap.session.current_target, "NGC 7000")
        self.assertEqual(snap.session.frame_in_filter, 4)
        self.assertEqual(snap.session.dither_every, 3)
        self.assertEqual(len(snap.recent_frames), 4)
        # site geometry came from the sidecar -> sky computed
        self.assertIsNotNone(snap.sky)
        # DATE-OBS drives timestamps -> a real ~75s cadence, not 0
        txt = render_status(snap, color=False)
        self.assertIn("NGC 7000", txt)
        self.assertIn("Capture", txt)
        self.assertIn("Sky", txt)

    def test_empty_dir_is_graceful(self):
        with TemporaryDirectory() as d:
            snap = build_snapshot_from_disk(Path(d), now_utc=NOW)
        self.assertEqual(snap.session.frame_in_filter, 0)
        self.assertEqual(snap.recent_frames, ())
        # renders without raising even with nothing to show
        render_status(snap, color=False)
