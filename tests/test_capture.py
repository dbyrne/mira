"""Tests for the dithering deep-capture loop. No NINA — injected fake
client. The properties that matter (and that the M94 disaster came from
lacking): dither is bounded, NON-cumulative (relative to fixed nominal,
so it also re-centers), and every reposition slew is center=False (no
NINA Center loop)."""
from __future__ import annotations

import json
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
    def __init__(self, fail_slew_on=(), fail_filter=False, fail_autofocus=False):
        self.slews: list[tuple] = []  # (ra,dec,center)
        self.captures: list[dict] = []
        self.filters: list[str] = []
        self.autofocus_calls: list[str] = []  # records each AF trigger
        self._fail = set(fail_slew_on)
        self._fail_filter = fail_filter
        self._fail_autofocus = fail_autofocus
        self._n = 0
        self.nina_root: Path | None = None
        self.exp_tag = ""

    def set_filter(self, filter_ref, *, wait=True, timeout_s=60.0):
        if self._fail_filter:
            return False
        self.filters.append(str(filter_ref))
        return True

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

    def run_autofocus(self, *, timeout_s=600.0, poll_s=5.0):
        self.autofocus_calls.append(f"af#{len(self.autofocus_calls) + 1}")
        if self._fail_autofocus:
            raise RuntimeError("AF boom")
        return {"Response": {"HFR": 2.4}}


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
        # Existing tests pre-date verify-pointing and rely on platesolve
        # being a single slew(center=True). Default verify to 0 here so
        # they aren't perturbed by ASTAP-availability-dependent behavior;
        # the dedicated TestVerifyPointing tests override.
        kw.setdefault("verify_pointing_deg", 0)
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

    def test_filter_selected_and_confirmed_before_capture(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=3, dither_arcsec=0.0, filter_name="IR")
            self.assertEqual(c.filters, ["IR"])      # wheel was driven
            self.assertEqual(res.filter_name, "IR")
            self.assertEqual(res.captured, 3)        # then it ran normally

    def test_unconfirmed_filter_aborts_before_any_capture(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=5, dither_arcsec=10.0,
                               filter_name="LP",
                               client_kw={"fail_filter": True})
            self.assertEqual(res.captured, 0)        # refused to shoot
            self.assertEqual(len(c.captures), 0)
            self.assertEqual(len(c.slews), 0)        # didn't even slew
            self.assertIn("LP", res.stopped_reason)
            self.assertIn("not confirmed", res.stopped_reason)

    def test_capture_writes_filter_sidecar_for_auto_flats(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=2, dither_arcsec=0.0, filter_name="IR")
            sidecar = Path(d) / "dest" / "mira_capture.json"
            self.assertTrue(sidecar.exists())        # stack --auto-flats reads this
            meta = json.loads(sidecar.read_text())
            self.assertEqual(meta["filter"], "IR")
            self.assertEqual(meta["gain"], 120)

    def test_platesolve_center_runs_once_before_loop_and_is_centered(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=2, dither_arcsec=10.0,
                                platesolve_center=True)
            # First slew is the plate-solve center call: center=True, on
            # exact nominal coords. All subsequent slews are blind dithers.
            self.assertGreaterEqual(len(c.slews), 1)
            ra0, dec0, center0 = c.slews[0]
            self.assertEqual((ra0, dec0, center0), (200.0, 40.0, True))
            for _, _, center in c.slews[1:]:
                self.assertFalse(center)  # dithers stay blind
            self.assertTrue(res.platesolve_centered)
            self.assertEqual(res.captured, 2)

    def test_platesolve_failure_does_not_abort_run(self) -> None:
        with TemporaryDirectory() as d:
            # First slew is the plate-solve center; force it to fail.
            c, res = self._run(d, n_max=2, dither_arcsec=10.0,
                                platesolve_center=True,
                                client_kw={"fail_slew_on": (1,)})
            self.assertFalse(res.platesolve_centered)
            self.assertEqual(res.captured, 2)       # loop continued anyway

    def test_autofocus_fires_pre_loop_when_enabled(self) -> None:
        with TemporaryDirectory() as d:
            # Big interval -> only the pre-loop AF should fire in a 3-sub run.
            c, res = self._run(d, n_max=3, dither_arcsec=0.0,
                                autofocus_every_min=60)
            self.assertEqual(len(c.autofocus_calls), 1)
            self.assertEqual(res.autofocus_runs, 1)

    def test_autofocus_disabled_when_zero(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=3, dither_arcsec=0.0,
                                autofocus_every_min=0)
            self.assertEqual(len(c.autofocus_calls), 0)
            self.assertEqual(res.autofocus_runs, 0)

    def test_sidecar_records_effective_config_and_result(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(
                d, n_max=3, dither_arcsec=20.0,
                filter_name="LP", platesolve_center=True,
                autofocus_every_min=60,
                sidecar_audit={"lat_deg": 40.72, "alt_floor_deg": 30.0},
            )
            sidecar = json.loads(
                (Path(d) / "dest" / "mira_capture.json").read_text())
            # Backward-compat fields stay at the top level (resolve_master_for_lights
            # keys off these).
            self.assertEqual(sidecar["filter"], "LP")
            self.assertEqual(sidecar["gain"], 120)
            # Effective config — both run_capture params and CLI-injected audit.
            cfg = sidecar["config"]
            self.assertEqual(cfg["dither_arcsec"], 20.0)
            self.assertTrue(cfg["platesolve_center"])
            self.assertEqual(cfg["autofocus_every_min"], 60)
            self.assertEqual(cfg["lat_deg"], 40.72)         # from sidecar_audit
            self.assertIn("mira_version", cfg)               # injected automatically
            # Result block reflects what actually happened.
            self.assertEqual(sidecar["result"]["captured"], 3)
            self.assertEqual(sidecar["result"]["autofocus_runs"], 1)
            self.assertTrue(sidecar["result"]["platesolve_centered"])
            self.assertIn("started_utc", sidecar["result"])
            self.assertIn("ended_utc", sidecar["result"])

    def test_autofocus_failure_does_not_kill_run(self) -> None:
        with TemporaryDirectory() as d:
            c, res = self._run(d, n_max=2, dither_arcsec=0.0,
                                autofocus_every_min=60,
                                client_kw={"fail_autofocus": True})
            self.assertEqual(len(c.autofocus_calls), 1)   # attempted
            self.assertEqual(res.autofocus_runs, 0)       # but didn't count
            self.assertEqual(res.captured, 2)             # loop continued


class TestVerifyPointing(TestCase):
    """Patch the verify_pointing helper directly. Real `_verify_pointing`
    is exercised against fake astap_cli + fake FITS in test_solve.py;
    here we care about the *integration* with run_capture — does the loop
    abort vs. proceed based on the verifier's verdict?"""

    def _run_with_verifier(self, d, *, verifier, **kw):
        from unittest.mock import patch

        c = FakeClient()
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        c.exp_tag = f"{float(kw.get('exposure_s', 45.0)):.2f}s"
        with patch("mira.capture._verify_pointing", side_effect=verifier):
            res = run_capture(
                c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                dest_dir=Path(d) / "dest", nina_root=nina,
                rng=random.Random(7), settle_s=0.0,
                platesolve_center=True, verify_pointing_deg=1.0,
                **kw,
            )
        return c, res

    def test_verification_pass_proceeds_to_loop(self) -> None:
        def verifier(*a, **kw):
            return True, 0.05, "verified 0.050deg from nominal"
        with TemporaryDirectory() as d:
            c, res = self._run_with_verifier(
                d, verifier=verifier, n_max=2, dither_arcsec=10.0,
            )
            self.assertTrue(res.pointing_verified)
            self.assertEqual(res.pointing_offset_deg, 0.05)
            self.assertEqual(res.captured, 2)         # loop ran

    def test_verification_fail_aborts_before_loop(self) -> None:
        def verifier(*a, **kw):
            return False, 2.81, ("pointing verification FAILED: solved center "
                                  "is 2.81deg from nominal")
        with TemporaryDirectory() as d:
            c, res = self._run_with_verifier(
                d, verifier=verifier, n_max=10, dither_arcsec=10.0,
            )
            self.assertFalse(res.pointing_verified)
            self.assertEqual(res.pointing_offset_deg, 2.81)
            self.assertIn("FAILED", res.stopped_reason)
            self.assertIn("2.81", res.stopped_reason)
            self.assertEqual(res.captured, 0)         # loop never ran

    def test_verification_zero_tolerance_disables_check(self) -> None:
        """verify_pointing_deg=0 skips verification entirely — the
        verifier callable is never invoked. Used by tests + by users
        opting out of the extra pre-loop sub."""
        from unittest.mock import patch
        c = FakeClient()
        with TemporaryDirectory() as d:
            nina = Path(d) / "nina"
            nina.mkdir()
            c.nina_root = nina
            c.exp_tag = "45.00s"
            calls = []
            def verifier(*a, **kw):
                calls.append(1)
                return True, 0.0, ""
            with patch("mira.capture._verify_pointing", side_effect=verifier):
                res = run_capture(
                    c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                    dest_dir=Path(d) / "dest", nina_root=nina,
                    n_max=1, dither_arcsec=0.0, settle_s=0.0,
                    platesolve_center=True, verify_pointing_deg=0,
                )
            self.assertEqual(calls, [])               # verifier not called
            self.assertFalse(res.pointing_verified)
            self.assertEqual(res.captured, 1)

    def test_failed_verification_persists_sidecar(self) -> None:
        """On abort, the sidecar still captures the failure for audit —
        no silent drop of a session worth of intent."""
        def verifier(*a, **kw):
            return False, 5.0, "pointing verification FAILED: 5.00deg off"
        with TemporaryDirectory() as d:
            c, res = self._run_with_verifier(
                d, verifier=verifier, n_max=10, dither_arcsec=0.0,
            )
            sidecar = Path(d) / "dest" / "mira_capture.json"
            self.assertTrue(sidecar.exists())
            meta = json.loads(sidecar.read_text())
            self.assertFalse(meta["result"]["pointing_verified"])
            self.assertEqual(meta["result"]["pointing_offset_deg"], 5.0)
            self.assertIn("FAILED", meta["result"]["stopped_reason"])


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
