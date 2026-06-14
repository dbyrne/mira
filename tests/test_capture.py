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
from unittest.mock import patch

from mira.capture import (
    _target_alt_deg,
    altitude_sun_guard,
    random_dither_deg,
    run_capture,
    safe_park,
)


class FakeClient:
    def __init__(self, fail_slew_on=(), fail_filter=False, fail_autofocus=False,
                 fail_park=False):
        self.slews: list[tuple] = []  # (ra,dec,center)
        self.captures: list[dict] = []
        self.filters: list[str] = []
        self.autofocus_calls: list[str] = []  # records each AF trigger
        self._fail = set(fail_slew_on)
        self._fail_filter = fail_filter
        self._fail_autofocus = fail_autofocus
        self._fail_park = fail_park
        self.parked = False
        self.aborts = 0
        self._n = 0
        self.nina_root: Path | None = None

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
            # Mimic a REAL, user-configured NINA filename. Deliberately carries
            # NO parseable science-exposure token (a valid pattern, e.g.
            # DATEMINUS12_TIME_FILTER_SENSORTEMP_FRAMENR) so these tests fail if
            # the copy logic ever regresses to filename-substring matching (the
            # 2026-06-03 `*60.00s*` bug). New-frame detection must be by
            # snapshot diff, pattern-independent.
            (d / f"2026-06-03_21-35-37_IR_26.50_{self._n:04d}.fits").write_text("x")
        return {"Response": "Capture started"}

    def run_autofocus(self, *, timeout_s=600.0, poll_s=5.0):
        self.autofocus_calls.append(f"af#{len(self.autofocus_calls) + 1}")
        if self._fail_autofocus:
            raise RuntimeError("AF boom")
        return {"Response": {"HFR": 2.4}}

    def park(self, timeout=60.0):
        if self._fail_park:
            raise RuntimeError("park boom")
        self.parked = True
        return {"Response": "Parked"}

    def abort_capture(self):
        self.aborts += 1
        return {"Response": "Aborted"}


class PierClient(FakeClient):
    """FakeClient + a scripted pier side per poll (the last value repeats
    once the script is exhausted). Base FakeClient deliberately has NO
    pier_side method — that's the legacy/Seestar shape every other test
    exercises against the flip watch."""

    def __init__(self, pier_script, **kw):
        super().__init__(**kw)
        self._pier_script = list(pier_script)
        self.pier_polls = 0

    def pier_side(self):
        i = min(self.pier_polls, len(self._pier_script) - 1)
        self.pier_polls += 1
        return self._pier_script[i]


class RunCaptureTestBase(TestCase):
    """Base for tests that drive run_capture: zero the end-of-run sweep
    settle so unit tests don't sleep 2s per run. The sweep's COPY
    behavior itself is pinned in TestCopyLoop."""

    def setUp(self) -> None:
        p = patch("mira.capture.FINAL_SWEEP_SETTLE_S", 0.0)
        p.start()
        self.addCleanup(p.stop)


class TestGracefulStop(RunCaptureTestBase):
    """First Ctrl-C / stop_event = a CLEAN stop: finish the current frame,
    break between frames, leave the camera idle, and DO NOT abort it (a stray
    abort-exposure drops the Seestar's whole connection — 2026-06-14). The
    camera is aborted only on a hard interrupt / crash, where an exposure may
    actually be in flight."""

    def _client(self, d):
        c = FakeClient()
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        return c, nina

    def test_clean_stop_finishes_current_frame_no_abort(self) -> None:
        import threading
        ev = threading.Event()
        with TemporaryDirectory() as d:
            c, nina = self._client(d)
            # Ctrl-C lands during the 3rd exposure (event set mid-capture): the
            # frame still completes, the loop breaks at the top of iteration 4
            # (no 4th), and the idle camera is NOT aborted.
            orig = c.capture

            def capture_then_request_stop(**kw):
                r = orig(**kw)
                if len(c.captures) == 3:
                    ev.set()
                return r

            c.capture = capture_then_request_stop
            res = run_capture(
                c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                dest_dir=Path(d) / "dest", nina_root=nina,
                rng=random.Random(7), settle_s=0.0, n_max=100,
                dither_arcsec=0.0, verify_pointing_deg=0, stop_event=ev,
            )
        self.assertEqual(len(c.captures), 3)       # 3rd finished, no 4th
        self.assertEqual(res.captured, 3)
        self.assertIn("clean stop", res.stopped_reason)
        self.assertEqual(c.aborts, 0)              # idle camera -> NO abort

    def test_no_abort_on_normal_completion(self) -> None:
        with TemporaryDirectory() as d:
            c, nina = self._client(d)
            res = run_capture(
                c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                dest_dir=Path(d) / "dest", nina_root=nina,
                rng=random.Random(7), settle_s=0.0, n_max=2,
                dither_arcsec=0.0, verify_pointing_deg=0,
            )
        self.assertEqual(res.captured, 2)
        self.assertEqual(c.aborts, 0)              # n_max reached -> NO abort

    def test_hard_interrupt_aborts_camera(self) -> None:
        # A second Ctrl-C / crash mid-exposure DOES release the camera.
        with TemporaryDirectory() as d:
            c, nina = self._client(d)
            orig = c.capture

            def capture_then_raise(**kw):
                orig(**kw)
                if len(c.captures) == 2:
                    raise KeyboardInterrupt
                return {}

            c.capture = capture_then_raise
            with self.assertRaises(KeyboardInterrupt):
                run_capture(
                    c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                    dest_dir=Path(d) / "dest", nina_root=nina,
                    rng=random.Random(7), settle_s=0.0, n_max=100,
                    dither_arcsec=0.0, verify_pointing_deg=0,
                )
        self.assertGreaterEqual(c.aborts, 1)       # mid-exposure -> released

    def test_missing_abort_method_tolerated_on_interrupt(self) -> None:
        # A leaner client without abort_capture must not raise a secondary
        # error on the hard-stop path (getattr-None guard).
        class LeanClient(FakeClient):
            abort_capture = None  # mask the method

        with TemporaryDirectory() as d:
            c = LeanClient()
            nina = Path(d) / "nina"
            nina.mkdir()
            c.nina_root = nina
            orig = c.capture

            def capture_then_raise(**kw):
                orig(**kw)
                if len(c.captures) == 1:
                    raise KeyboardInterrupt
                return {}

            c.capture = capture_then_raise
            with self.assertRaises(KeyboardInterrupt):
                run_capture(
                    c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                    dest_dir=Path(d) / "dest", nina_root=nina,
                    rng=random.Random(7), settle_s=0.0, n_max=100,
                    dither_arcsec=0.0, verify_pointing_deg=0,
                )


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


class TestRunCaptureDither(RunCaptureTestBase):
    def _run(self, d, **kw):
        c = FakeClient(**kw.pop("client_kw", {}))
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
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


class TestVerifyPointing(RunCaptureTestBase):
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
            # keeper=None: this mock doesn't simulate a kept verify frame, so
            # captured reflects loop subs only (see test_verify_sub_is_kept).
            return True, 0.05, "verified 0.050deg from nominal", None
        with TemporaryDirectory() as d:
            c, res = self._run_with_verifier(
                d, verifier=verifier, n_max=2, dither_arcsec=10.0,
            )
            self.assertTrue(res.pointing_verified)
            self.assertEqual(res.pointing_offset_deg, 0.05)
            self.assertEqual(res.captured, 2)         # loop ran

    def test_verify_sub_is_kept_as_light_frame(self) -> None:
        """A passing verify sub is a real, on-target, already-solved frame at
        the science exposure — it must be copied into dest and counted, not
        wasted. (keeper non-None == the clean-pass path of the real helper.)"""
        from unittest.mock import patch
        with TemporaryDirectory() as d:
            nina = Path(d) / "nina"
            nina.mkdir()
            c = FakeClient()
            c.nina_root = nina
            # The solved test sub the real helper leaves in nina_root + returns.
            keeper = nina / "2026-06-04_00-00-00_IR_26.50_9999.fits"
            keeper.write_text("solved-test-sub")

            def verifier(*a, **kw):
                return True, 0.05, "verified 0.050deg from nominal", keeper
            with patch("mira.capture._verify_pointing", side_effect=verifier):
                res = run_capture(
                    c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
                    dest_dir=Path(d) / "dest", nina_root=nina,
                    rng=random.Random(7), settle_s=0.0,
                    platesolve_center=True, verify_pointing_deg=1.0,
                    n_max=2, dither_arcsec=10.0,
                )
            # 2 loop subs + the kept verify sub == 3, and it's not double-copied
            self.assertEqual(res.captured, 3)
            self.assertEqual(res.copied, 3)
            self.assertTrue((Path(d) / "dest" / keeper.name).exists())

    def test_verification_fail_aborts_before_loop(self) -> None:
        def verifier(*a, **kw):
            return False, 2.81, ("pointing verification FAILED: solved center "
                                  "is 2.81deg from nominal"), None
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
            calls = []
            def verifier(*a, **kw):
                calls.append(1)
                return True, 0.0, "", None
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
            return False, 5.0, "pointing verification FAILED: 5.00deg off", None
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

    def test_fov_deg_threaded_from_run_capture_to_verifier(self) -> None:
        """run_capture must hand its rig FOV to the verifier (the Esprit
        bug: the S30 default FOV made every Esprit solve fail and the
        check fail-open)."""
        got = {}

        def verifier(client, **kw):
            got.update(kw)
            return True, 0.1, "verified", None

        with TemporaryDirectory() as d:
            self._run_with_verifier(d, verifier=verifier, n_max=1,
                                    dither_arcsec=0.0, fov_deg=1.07)
            meta = json.loads(
                (Path(d) / "dest" / "mira_capture.json").read_text())
            self.assertEqual(meta["config"]["fov_deg"], 1.07)  # audited
        self.assertEqual(got.get("fov_deg"), 1.07)

    def _run_real_verifier(self, fov_deg):
        """Drive the REAL _verify_pointing with solve_one mocked; returns
        the kwargs solve_one was called with."""
        from types import SimpleNamespace

        from mira.capture import _verify_pointing

        with TemporaryDirectory() as d:
            nina = Path(d) / "nina"
            nina.mkdir()
            c = FakeClient()
            c.nina_root = nina
            seen_kwargs = []

            def fake_solve_one(path, **kw):
                seen_kwargs.append(kw)
                return SimpleNamespace(status="failed", note="mock")

            with patch("mira.solve.find_astap_cli", return_value="astap_cli"), \
                 patch("mira.solve.solve_one", side_effect=fake_solve_one):
                ok, _, _, keeper = _verify_pointing(
                    c, ra_deg=83.8, dec_deg=-5.4, exposure_s=30.0,
                    gain=100, nina_root=nina, tolerance_deg=1.0,
                    emit=lambda m: None, fov_deg=fov_deg,
                )
            self.assertTrue(ok)          # solve-failed -> fail-open skip
            self.assertIsNone(keeper)
            return seen_kwargs[0]

    def test_real_verifier_passes_fov_to_solve_one(self) -> None:
        self.assertEqual(self._run_real_verifier(1.07)["fov_deg"], 1.07)

    def test_real_verifier_none_fov_uses_solver_default(self) -> None:
        from mira.solve import DEFAULT_FOV_DEG
        self.assertEqual(self._run_real_verifier(None)["fov_deg"],
                         DEFAULT_FOV_DEG)


class TestSidecarLifecycle(RunCaptureTestBase):
    """The interrupted-session-books-0-minutes bug: the pre-loop sidecar
    persist must OMIT the result block entirely (the ledger trusts
    result['copied'] whenever the key exists, which defeats its
    glob-rescue), and the final result-bearing persist must fire from a
    finally so Ctrl-C / crash still records the true tallies."""

    def _setup(self, d):
        c = FakeClient()
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        return c, nina, Path(d) / "dest" / "mira_capture.json"

    def _run(self, c, nina, d, **kw):
        return run_capture(
            c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
            dest_dir=Path(d) / "dest", nina_root=nina,
            rng=random.Random(7), settle_s=0.0, dither_arcsec=0.0,
            verify_pointing_deg=0, **kw,
        )

    def test_preloop_sidecar_has_no_result_block(self) -> None:
        with TemporaryDirectory() as d:
            c, nina, sidecar = self._setup(d)
            mid_run = {}

            def guard(i):
                if i == 1:                 # pre-loop persist already happened
                    mid_run.update(json.loads(sidecar.read_text()))
                return None

            self._run(c, nina, d, n_max=2, should_continue=guard)
            self.assertIn("config", mid_run)       # intent IS persisted
            self.assertNotIn("result", mid_run)    # but no provisional result
            # Normal exit still writes the full result block.
            final = json.loads(sidecar.read_text())
            self.assertEqual(final["result"]["copied"], 2)
            self.assertIn("n_max=2", final["result"]["stopped_reason"])

    def test_interrupt_persists_accurate_result(self) -> None:
        with TemporaryDirectory() as d:
            c, nina, sidecar = self._setup(d)

            def guard(i):
                if i >= 3:
                    raise KeyboardInterrupt
                return None

            with self.assertRaises(KeyboardInterrupt):
                self._run(c, nina, d, n_max=99, should_continue=guard)
            meta = json.loads(sidecar.read_text())
            self.assertEqual(meta["result"]["copied"], 2)   # true tally, not 0
            self.assertEqual(meta["result"]["captured"], 2)
            self.assertEqual(meta["result"]["stopped_reason"], "interrupted")

    def test_crash_persists_result_with_reason(self) -> None:
        with TemporaryDirectory() as d:
            c, nina, sidecar = self._setup(d)

            def guard(i):
                if i >= 2:
                    raise RuntimeError("NINA went away")
                return None

            with self.assertRaises(RuntimeError):
                self._run(c, nina, d, n_max=99, should_continue=guard)
            meta = json.loads(sidecar.read_text())
            self.assertEqual(meta["result"]["copied"], 1)
            self.assertIn("NINA went away", meta["result"]["stopped_reason"])


class TestCopyLoop(RunCaptureTestBase):
    """Frames must survive a transiently-locked nina_root (OneDrive) and
    the last-sub race: a frame joins `seen` only after a successful copy
    (so a failed copy retries), failures warn with the filename, and a
    final settle+sweep runs after the loop."""

    def _run(self, d, c, **kw):
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        msgs: list[str] = []
        kw.setdefault("verify_pointing_deg", 0)
        res = run_capture(
            c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
            dest_dir=Path(d) / "dest", nina_root=nina,
            rng=random.Random(7), settle_s=0.0, on_step=msgs.append, **kw,
        )
        return res, msgs

    def test_locked_frame_is_retried_not_lost(self) -> None:
        import shutil as _shutil
        real_copy2 = _shutil.copy2
        failed: list[str] = []

        def flaky_copy2(src, dst, **kw):
            # First attempt on frame 0001 fails (locked); later passes work.
            if "0001" in str(src) and not failed:
                failed.append(str(src))
                raise OSError("locked by another process")
            return real_copy2(src, dst, **kw)

        with TemporaryDirectory() as d:
            c = FakeClient()
            with patch("mira.capture.shutil.copy2", side_effect=flaky_copy2):
                res, msgs = self._run(d, c, n_max=3, dither_arcsec=0.0)
            self.assertEqual(res.copied, 3)               # nothing lost
            self.assertEqual(
                len(list((Path(d) / "dest").glob("*.fits"))), 3)
            warns = [m for m in msgs if "copy failed" in m]
            self.assertEqual(len(warns), 1)
            self.assertIn("0001", warns[0])               # names the frame

    def test_final_sweep_copies_late_landing_frame(self) -> None:
        with TemporaryDirectory() as d:
            c = FakeClient()

            def guard(i):
                if i >= 3:
                    # A frame NINA flushes after the loop's last copy pass —
                    # no in-loop glob ever sees it.
                    p = c.nina_root / "SNAPSHOT" / "late_flush.fits"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text("late")
                    return "stop"
                return None

            res, _ = self._run(d, c, n_max=99, dither_arcsec=0.0,
                               should_continue=guard)
            self.assertEqual(res.captured, 2)
            # 2 loop frames + the late-flushed one, swept post-loop.
            self.assertEqual(res.copied, 3)
            self.assertTrue((Path(d) / "dest" / "late_flush.fits").exists())


class TestPierFlip(RunCaptureTestBase):
    """Meridian-flip awareness: pier side is polled once per sub; a change
    re-centers (platesolve_center sessions), is reported, and is counted
    in the result/sidecar. Mounts that don't report a side (Seestar) make
    the whole feature a silent no-op."""

    def _run(self, d, c, **kw):
        nina = Path(d) / "nina"
        nina.mkdir()
        c.nina_root = nina
        msgs: list[str] = []
        kw.setdefault("verify_pointing_deg", 0)
        res = run_capture(
            c, ra_deg=200.0, dec_deg=40.0, exposure_s=45.0, gain=120,
            dest_dir=Path(d) / "dest", nina_root=nina,
            rng=random.Random(7), settle_s=0.0, on_step=msgs.append, **kw,
        )
        return res, msgs

    def test_flip_recenters_when_platesolve_center(self) -> None:
        with TemporaryDirectory() as d:
            # Polls: pre-loop, then one per sub -> the flip lands on sub 3.
            c = PierClient(["East", "East", "East", "West"])
            res, msgs = self._run(d, c, n_max=4, dither_arcsec=0.0,
                                  platesolve_center=True)
            self.assertEqual(res.pier_flips, 1)
            self.assertTrue(any(
                "pier flip detected (East->West): re-centering" in m
                for m in msgs))
            # Exactly two center=True slews, both on exact nominal coords:
            # the pre-loop platesolve center and the post-flip re-center.
            centers = [s for s in c.slews if s[2]]
            self.assertEqual(centers, [(200.0, 40.0, True),
                                       (200.0, 40.0, True)])
            self.assertEqual(res.captured, 4)             # loop unaffected

    def test_flip_without_platesolve_center_reports_but_no_slew(self) -> None:
        with TemporaryDirectory() as d:
            c = PierClient(["East", "West"])
            res, msgs = self._run(d, c, n_max=3, dither_arcsec=0.0)
            self.assertEqual(res.pier_flips, 1)
            self.assertTrue(any("pier flip detected (East->West)" in m
                                for m in msgs))
            self.assertFalse(any("re-centering" in m for m in msgs))
            self.assertEqual([s for s in c.slews if s[2]], [])  # no Center

    def test_failed_postflip_center_does_not_kill_run(self) -> None:
        with TemporaryDirectory() as d:
            # Slew #1 is the pre-loop center; #2 is the post-flip center.
            c = PierClient(["East", "West"], fail_slew_on=(2,))
            res, msgs = self._run(d, c, n_max=3, dither_arcsec=0.0,
                                  platesolve_center=True)
            self.assertEqual(res.pier_flips, 1)
            self.assertTrue(any("post-flip center FAILED" in m for m in msgs))
            self.assertEqual(res.captured, 3)             # loop continued

    def test_empty_pier_side_is_silent_noop(self) -> None:
        with TemporaryDirectory() as d:
            c = PierClient([""])                  # Seestar-style: no side
            res, msgs = self._run(d, c, n_max=3, dither_arcsec=10.0)
            self.assertEqual(res.pier_flips, 0)
            self.assertFalse(any("pier flip" in m for m in msgs))
            self.assertEqual(res.captured, 3)

    def test_client_without_pier_side_method_is_silent_noop(self) -> None:
        with TemporaryDirectory() as d:
            c = FakeClient()                      # no pier_side at all
            res, msgs = self._run(d, c, n_max=2, dither_arcsec=10.0)
            self.assertEqual(res.pier_flips, 0)
            self.assertFalse(any("pier flip" in m for m in msgs))

    def test_side_becoming_available_midrun_is_not_a_flip(self) -> None:
        with TemporaryDirectory() as d:
            # "" -> "West": the first non-empty read seeds the baseline.
            c = PierClient(["", "West", "West", "West"])
            res, msgs = self._run(d, c, n_max=3, dither_arcsec=0.0)
            self.assertEqual(res.pier_flips, 0)
            self.assertFalse(any("pier flip" in m for m in msgs))

    def test_flip_count_lands_in_sidecar_result(self) -> None:
        with TemporaryDirectory() as d:
            c = PierClient(["East", "West"])
            res, _ = self._run(d, c, n_max=2, dither_arcsec=0.0)
            self.assertEqual(res.pier_flips, 1)
            meta = json.loads(
                (Path(d) / "dest" / "mira_capture.json").read_text())
            self.assertEqual(meta["result"]["pier_flips"], 1)


class TestSafePark(TestCase):
    """End-of-session safing (mira capture --park-at-end). Both steps
    fail-soft so safing can never mask the run result or raise."""

    def test_shields_sensor_and_parks(self) -> None:
        c = FakeClient()
        out = safe_park(c)
        self.assertEqual(c.filters, ["Dark"])      # rotated to opaque position
        self.assertTrue(c.parked)                  # mount parked
        self.assertEqual(out, {"shielded": True, "parked": True})

    def test_filter_shield_failure_is_soft_still_parks(self) -> None:
        c = FakeClient(fail_filter=True)           # wheel can't confirm 'Dark'
        out = safe_park(c)                          # must not raise
        self.assertFalse(out["shielded"])
        self.assertTrue(out["parked"])             # park still happens
        self.assertTrue(c.parked)

    def test_park_failure_is_soft(self) -> None:
        c = FakeClient(fail_park=True)
        out = safe_park(c)                          # must not raise
        self.assertTrue(out["shielded"])           # shield still happened
        self.assertFalse(out["parked"])
        self.assertFalse(c.parked)

    def test_no_shield_filter_skips_wheel(self) -> None:
        c = FakeClient()
        out = safe_park(c, shield_filter=None)
        self.assertEqual(c.filters, [])            # wheel untouched
        self.assertTrue(c.parked)
        self.assertFalse(out["shielded"])


class TestGuard(TestCase):
    def test_floor_branch_deterministic(self) -> None:
        # impossible altitude floor -> always stops with target-below reason
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=200.0, sun_max_deg=-90.0)
        self.assertIn("altitude", g(1))

    def test_sun_branch_fires_at_dawn(self) -> None:
        # floor passes (alt always > -90); sun always > -90. At a RISING-sun
        # (morning) clock the dawn gate fires. ~10:00 UTC at lon -74 is after
        # solar midnight (~04:56 UTC) and before solar noon (~16:56) -> rising.
        from datetime import datetime, timezone
        morning = datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=-90.0, sun_max_deg=-90.0,
                                clock=lambda: morning)
        reason = g(1)
        self.assertIsNotNone(reason)
        self.assertIn("sun", reason)
        self.assertIn("dawn", reason)

    def test_sun_branch_silent_at_dusk(self) -> None:
        # Same impossible gate, but a SETTING-sun (evening) clock must NOT
        # stop: the operator controls the dusk start. ~23:00 UTC at lon -74
        # is after solar noon (~16:56) -> descending.
        from datetime import datetime, timezone
        evening = datetime(2026, 6, 6, 23, 0, tzinfo=timezone.utc)
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=-90.0, sun_max_deg=-90.0,
                                clock=lambda: evening)
        self.assertIsNone(g(1))

    def test_floor_beats_sun_at_dusk(self) -> None:
        # The altitude floor still stops any time, dusk included.
        from datetime import datetime, timezone
        evening = datetime(2026, 6, 6, 23, 0, tzinfo=timezone.utc)
        g = altitude_sun_guard(200.0, 40.0, 40.7, -74.0,
                                alt_floor_deg=200.0, sun_max_deg=-90.0,
                                clock=lambda: evening)
        self.assertIn("altitude", g(1))
