"""Tests for the dithering deep-capture loop. No NINA — injected fake
client. The properties that matter (and that the M94 disaster came from
lacking): dither is bounded, NON-cumulative (relative to fixed nominal,
so it also re-centers), and every reposition slew is center=False (no
NINA Center loop)."""
from __future__ import annotations

import math
import random
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.capture import (
    _target_alt_deg,
    altitude_sun_guard,
    random_dither_deg,
    run_capture,
)


class FakeClient:
    def __init__(self, fail_slew_on=()):
        self.slews: list[tuple] = []  # (ra,dec,center)
        self.captures: list[dict] = []
        self._fail = set(fail_slew_on)
        self._n = 0
        self.nina_root: Path | None = None
        self.exp_tag = ""

    def slew(self, ra_deg, dec_deg, *, center=True, wait=True, timeout=180.0):
        self.slews.append((ra_deg, dec_deg, center))
        if len(self.slews) in self._fail:
            raise RuntimeError("slew boom")
        return {"Response": "Slew finished"}

    def wait_camera_idle(self, timeout_s=90.0, poll_s=1.0):
        return True

    def capture(self, *, duration, gain=None, save=True, solve=False,
                target_name="", timeout_s=120.0):
        self.captures.append({"duration": duration, "gain": gain, "save": save})
        if self.nina_root is not None:
            self._n += 1
            d = self.nina_root / "SNAPSHOT"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"2026_{self.exp_tag}_{self._n:04d}.fits").write_text("x")
        return {"Response": "Capture started"}


class TestDitherMath(TestCase):
    def test_zero_when_disabled(self) -> None:
        self.assertEqual(random_dither_deg(0, 45.0, random.Random(1)), (0.0, 0.0))

    def test_bounded_and_ra_scaled_by_cosdec(self) -> None:
        rng = random.Random(42)
        dec = 60.0
        for _ in range(200):
            dra, ddec = random_dither_deg(30.0, dec, rng)
            self.assertLessEqual(abs(ddec) * 3600.0, 30.0 + 1e-9)
            # RA offset is /cos(dec); at dec=60 that's ~2x the dec bound
            self.assertLessEqual(abs(dra) * 3600.0, 30.0 / math.cos(math.radians(dec)) + 1e-6)

    def test_target_alt_known(self) -> None:
        from datetime import datetime, timezone
        # object at observer's zenith: dec=lat, on the meridian -> ~90 deg
        # just sanity that it returns a plausible degree value
        a = _target_alt_deg(180.0, 40.0, 40.0, 0.0,
                             datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
        self.assertTrue(-90.0 <= a <= 90.0)


class TestRunCaptureDither(TestCase):
    def _run(self, d, **kw):
        c = FakeClient(**kw.pop("client_kw", {}))
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        c.exp_tag = f"{float(kw.get('exposure_s', 45.0)):.2f}s"
        res = run_capture(
            c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
            dest_dir=Path(d) / "dest", nina_root=nina,
            rng=random.Random(7), settle_s=0.0, **kw,
        )
        return c, res

    def test_dither_every_sub_noncumulative_and_blind(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=5, dither_arcsec=30.0, dither_every=1)
            self.assertEqual(len(c.slews), 5)             # one dither per sub
            for ra, dec, center in c.slews:
                self.assertFalse(center)                  # blind, no Center loop
                # within the dither box of the FIXED nominal (NOT drifting)
                self.assertLess(abs(dec - 40.0) * 3600.0, 30.1)
                self.assertLess(abs(ra - 200.0) * 3600.0,
                                30.0 / math.cos(math.radians(40.0)) + 1)
            self.assertEqual(len(c.captures), 5)
            self.assertEqual(res.captured, 5)
            self.assertEqual(res.copied, 5)               # incremental copy
            self.assertEqual(res.dithers, 5)

    def test_dither_every_2(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=4, dither_arcsec=20.0, dither_every=2)
            self.assertEqual(res.dithers, 2)              # subs 1 and 3
            self.assertEqual(len(c.slews), 2)

    def test_recenter_when_not_dithering(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=4, dither_arcsec=0.0, recenter_every=2)
            self.assertEqual(res.dithers, 0)
            self.assertEqual(res.recenters, 2)            # subs 1,3
            for ra, dec, center in c.slews:
                self.assertEqual((ra, dec, center), (200.0, 40.0, False))  # exact nominal, blind

    def test_slew_failure_does_not_kill_run(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=3, dither_arcsec=15.0,
                                client_kw={"fail_slew_on": (2,)})
            self.assertEqual(res.captured, 3)             # still captured all 3
            self.assertEqual(res.dithers, 2)              # one slew failed

    def test_guard_stops_loop(self) -> None:
        with TemporaryDirectory() as d:
            stop = {"i": 3}
            c, res = self._run(
                d, n_max=99, dither_arcsec=10.0,
                should_continue=lambda i: "twilight" if i >= stop["i"] else None,
            )
            self.assertEqual(res.captured, 2)             # stopped before i=3
            self.assertIn("twilight", res.stopped_reason)

    def test_nmax_reason(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=2, dither_arcsec=0.0)
            self.assertEqual(res.captured, 2)
            self.assertIn("n_max=2", res.stopped_reason)


class TestGuard(TestCase):
    def test_floor_branch_deterministic(self) -> None:
        # impossible altitude floor -> always stops with target-below reason
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=200.0, sun_max_deg=-90.0)
        self.assertIn("altitude", g(1))

    def test_sun_branch_deterministic(self) -> None:
        # floor passes (alt always > -90); sun always > -90 -> sun reason
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=-90.0, sun_max_deg=-90.0)
        self.assertIn("sun", g(1))
