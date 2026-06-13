"""Tests for per-filter flat calibration. No NINA — an injected FakeClient
simulates a sensor: median = clip(bias + k*exposure, 0, SAT), per filter.
The properties that matter (and that the 2026-05-19 session proved we
need): convergence to target ADU, opaque-position auto-skip, the
repeatability gate, and stale/sky-frame rejection."""
from __future__ import annotations

import random
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.flats import (
    CAPTURE_SIDECAR,
    SAT_ADU,
    _find_capture_file,
    bracket_filter,
    build_master,
    capture_series,
    resolve_master_for_lights,
    run_flats,
    solve_exposure,
    write_capture_sidecar,
)


class FakeClient:
    """Filters map name -> response(exp, call_n) -> median ADU. `mode`
    tweaks pathologies: 'stale' never advances history, 'sky' reports
    stars. `flat_device` (None | dict) simulates a Cover Calibrator —
    None means no panel (paper-mode default)."""

    def __init__(self, nina_root: Path, responses: dict, mode: str = "",
                 flat_device: dict | None = None, fail_close: bool = False,
                 fail_brightness: bool = False, fail_light_on: bool = False):
        self.nina_root = Path(nina_root)
        self.responses = responses
        self.mode = mode
        self.cur = next(iter(responses))
        self._n = 0
        self.hist: list[dict] = []
        self.set_calls: list[str] = []
        # Flat-device state. The dict keys mirror what NinaClient returns.
        # fail_* knobs simulate a half-dead panel: the command is issued
        # (recorded in panel_calls) but never confirms.
        self._flat = dict(flat_device) if flat_device is not None else None
        self._fail_close = fail_close
        self._fail_brightness = fail_brightness
        self._fail_light_on = fail_light_on
        self.panel_calls: list[tuple[str, object]] = []

    # filter wheel
    def available_filters(self):
        return [{"Name": n, "Id": i} for i, n in enumerate(self.responses)]

    def current_filter(self):
        return {"Name": self.cur, "Id": list(self.responses).index(self.cur)}

    def set_filter(self, filter_ref, *, wait=True, timeout_s=60.0):
        for i, n in enumerate(self.responses):
            if str(filter_ref) in (str(i), n):
                self.cur = n
                self.set_calls.append(n)
                return True
        return False

    # camera
    def wait_camera_idle(self, timeout_s=60.0, poll_s=1.0):
        return True

    def capture(self, *, duration, gain=None, save=True, solve=False,
                target_name="", timeout_s=120.0):
        self._n += 1
        med = self.responses[self.cur](duration, self._n)
        med = max(0.0, min(med, SAT_ADU))
        if self.mode != "stale":
            d = self.nina_root / "SNAPSHOT"
            d.mkdir(parents=True, exist_ok=True)
            fn = f"flat_{self._n:04d}.fits"
            (d / fn).write_text("x")
            self.hist.append({
                "Filename": fn,
                "Median": med,
                "Stars": 500 if self.mode == "sky" else 0,
            })
        return {"Response": "ok"}

    def image_history(self, all_images=True):
        return list(self.hist)

    # flat device (Cover Calibrator). When _flat is None, every method
    # returns the "no panel" answer — that's the S30 / paper-mode path.
    def flat_device_info(self):
        return dict(self._flat) if self._flat is not None else {}

    def open_cover(self, *, wait=True, timeout_s=60.0):
        self.panel_calls.append(("open_cover", None))
        if self._flat is None:
            return False
        self._flat["CoverState"] = "Open"
        return True

    def close_cover(self, *, wait=True, timeout_s=60.0):
        self.panel_calls.append(("close_cover", None))
        if self._flat is None or self._fail_close:
            return False
        self._flat["CoverState"] = "Closed"
        return True

    def set_calibrator_on(self, on, *, wait=True, timeout_s=10.0):
        self.panel_calls.append(("set_calibrator_on", bool(on)))
        if self._flat is None or (self._fail_light_on and on):
            return False
        self._flat["LightOn"] = bool(on)
        return True

    def set_calibrator_brightness(self, brightness, *, wait=True, timeout_s=10.0):
        self.panel_calls.append(("set_calibrator_brightness", int(brightness)))
        if self._flat is None or self._fail_brightness:
            return False
        self._flat["Brightness"] = int(brightness)
        return True


def linear(k, bias=300.0):
    return lambda exp, n: bias + k * exp


# IR ~ target at 1.0s; LP dimmer (~target at 3s); DARK opaque (flat, low);
# BRIGHT saturates even at the 5ms floor.
IR = linear(30000.0)
LP = linear(10000.0)
DARK = lambda exp, n: 1100.0
BRIGHT = linear(2.0e7)


class TestSolveExposure(TestCase):
    def test_two_point_inverts_line_with_bias(self):
        # median = 300 + 30000*exp ; want 30000 -> exp ~= 0.99
        s = [(0.1, 3300.0), (1.0, 30300.0)]
        e = solve_exposure(s, 30000.0, min_exp=0.005, max_exp=30.0)
        self.assertAlmostEqual(e, 0.99, places=2)

    def test_clamped_to_bounds(self):
        s = [(0.1, 300.0), (1.0, 600.0)]  # very dim -> wants huge exp
        e = solve_exposure(s, 30000.0, min_exp=0.005, max_exp=30.0)
        self.assertEqual(e, 30.0)

    def test_single_sample_proportional(self):
        e = solve_exposure([(1.0, 15000.0)], 30000.0, min_exp=0.005, max_exp=30.0)
        self.assertAlmostEqual(e, 2.0, places=3)


class TestBracket(TestCase):
    def _bracket(self, resp):
        with TemporaryDirectory() as d:
            c = FakeClient(Path(d), {"X": resp})
            return bracket_filter(
                c, gain=120, target_adu=30000.0, nina_root=Path(d),
                min_exp=0.005, max_exp=30.0, emit=lambda m: None)

    def test_converges_to_target(self):
        status, exp, med = self._bracket(IR)
        self.assertEqual(status, "ok")
        self.assertLess(abs(med - 30000.0) / 30000.0, 0.08)
        self.assertGreater(exp, 0.0)

    def test_opaque_is_skipped(self):
        status, exp, med = self._bracket(DARK)
        self.assertEqual(status, "skipped_opaque")

    def test_too_bright_when_saturated_at_floor(self):
        status, exp, med = self._bracket(BRIGHT)
        self.assertEqual(status, "too_bright")

    def test_unstable_fails_repeatability(self):
        # converges within 8% tol but consecutive calls swing +-4% -> the
        # two confirm shots differ ~8% > REPEAT_SPREAD(5%) -> unstable.
        flaky = lambda exp, n: (300.0 + 30000.0 * exp) * (0.96 if n % 2 else 1.04)
        status, exp, med = self._bracket(flaky)
        self.assertEqual(status, "unstable")


class TestCaptureSeries(TestCase):
    def test_captures_validated_and_idempotent(self):
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            dest = Path(d) / "dest"
            c = FakeClient(root, {"X": IR})
            g, r = capture_series(
                c, exposure_s=1.0, gain=120, target_adu=30000.0,
                frames=10, dest_dir=dest, nina_root=root, emit=lambda m: None)
            self.assertEqual(g, 10)
            self.assertEqual(r, 0)
            self.assertEqual(len(list(dest.glob("*.fit*"))), 10)
            # idempotent: a second pass copies no duplicates (new frames,
            # but the count of *good* keeps climbing from disk baseline)
            g2, _ = capture_series(
                c, exposure_s=1.0, gain=120, target_adu=30000.0,
                frames=5, dest_dir=dest, nina_root=root, emit=lambda m: None)
            self.assertEqual(g2, 15)

    def test_sky_frames_rejected(self):
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(root, {"X": IR}, mode="sky")
            g, r = capture_series(
                c, exposure_s=1.0, gain=120, target_adu=30000.0,
                frames=6, dest_dir=Path(d) / "dest", nina_root=root,
                emit=lambda m: None)
            self.assertEqual(g, 0)       # all have stars -> not flats
            self.assertEqual(r, 6)

    def test_stale_frames_rejected(self):
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(root, {"X": IR}, mode="stale")
            g, r = capture_series(
                c, exposure_s=1.0, gain=120, target_adu=30000.0,
                frames=4, dest_dir=Path(d) / "dest", nina_root=root,
                emit=lambda m: None)
            self.assertEqual(g, 0)       # history never advances -> not fresh
            self.assertEqual(r, 4)


class TestRunFlatsEndToEnd(TestCase):
    def test_multi_filter_skips_opaque_and_builds_masters(self):
        captured = {}

        def fake_siril(script, *, work_dir, timeout_s=600.0):
            # emulate Siril producing the master artifacts
            (Path(work_dir) / "master_flat.tif").write_text("MASTER")
            (Path(work_dir) / "master_flat_preview.png").write_text("PNG")
            captured["ran"] = captured.get("ran", 0) + 1
            return "log: ok"

        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            out = Path(d) / "flats"
            c = FakeClient(root, {"Dark": DARK, "IR": IR, "LP": LP})
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=5,
                out_root=out, nina_root=root, min_exp=0.005, max_exp=30.0,
                on_step=lambda m: None, siril_runner=fake_siril)

            by = {r.filter_name: r for r in res.results}
            self.assertEqual(by["Dark"].status, "skipped_opaque")
            self.assertEqual(by["IR"].status, "ok")
            self.assertEqual(by["LP"].status, "ok")
            self.assertTrue(by["IR"].master_path.endswith("master_flat.tif"))
            self.assertEqual(captured["ran"], 2)            # only IR + LP
            # metadata + master landed in per-filter dirs; Dark made none
            self.assertTrue(any(p.name == "metadata.json"
                                for p in out.rglob("metadata.json")))
            self.assertFalse(any("Dark" in p.name for p in out.iterdir()))
            self.assertEqual(c.set_calls, ["Dark", "IR", "LP"])

    def test_explicit_filter_subset_only(self):
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(root, {"Dark": DARK, "IR": IR, "LP": LP})
            res = run_flats(
                c, filters=["LP"], gain=None, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                siril_runner=lambda *a, **k: (
                    (Path(k["work_dir"]) / "master_flat.tif").write_text("M")
                    or "ok"),
            )
        self.assertEqual([r.filter_name for r in res.results], ["LP"])
        self.assertEqual(c.set_calls, ["LP"])
        self.assertEqual(res.results[0].status, "ok")


class TestRunFlatsPanel(TestCase):
    """Cover-Calibrator (Wanderer V4-EC) integration into run_flats."""

    def _siril_stub(self):
        return lambda *a, **k: (
            (Path(k["work_dir"]) / "master_flat.tif").write_text("M") or "ok"
        )

    def test_no_panel_means_paper_mode_no_panel_calls(self):
        """Default S30 / no-panel path: flat_device_info returns {} so the
        run never touches close_cover / set_calibrator_*; bracket loop is
        unchanged."""
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(root, {"IR": IR}, flat_device=None)
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
        self.assertFalse(res.panel_driven)
        self.assertIsNone(res.panel_brightness)
        self.assertEqual(c.panel_calls, [])
        self.assertEqual(res.results[0].status, "ok")

    def test_panel_drives_close_cover_and_light(self):
        """When a Cover Calibrator is connected, run_flats closes the
        cover, sets brightness, and turns the EL panel on at start; at
        the end the light goes off (cover stays closed as a dust cap)."""
        import json
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(
                root, {"IR": IR},
                flat_device={
                    "Connected": True, "CoverState": "Open",
                    "MaxBrightness": 200, "Brightness": 0, "LightOn": False,
                    "SupportsOpenClose": True,
                },
            )
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
            self.assertTrue(res.panel_driven)
            # 50% of MaxBrightness=200 -> 100
            self.assertEqual(res.panel_brightness, 100)
            actions = [p[0] for p in c.panel_calls]
            self.assertIn("close_cover", actions)
            self.assertIn("set_calibrator_brightness", actions)
            # light on before light off
            on_idx = next(i for i, p in enumerate(c.panel_calls)
                          if p == ("set_calibrator_on", True))
            off_idx = next(i for i, p in enumerate(c.panel_calls)
                           if p == ("set_calibrator_on", False))
            self.assertLess(on_idx, off_idx)
            # final cover state stays Closed (dust cap)
            self.assertEqual(c.flat_device_info().get("CoverState"), "Closed")
            self.assertFalse(c.flat_device_info().get("LightOn"))
            # per-filter sidecar metadata records the source — assertion
            # MUST run inside the `with` block; the tempdir is cleaned up
            # on exit and rglob would silently return an empty list.
            meta_files = list((Path(d) / "f").rglob("metadata.json"))
            self.assertEqual(len(meta_files), 1)
            meta = json.loads(meta_files[0].read_text(encoding="utf-8"))
            self.assertEqual(meta["flat_source"], "panel")
            self.assertEqual(meta["panel_brightness"], 100)

    def test_explicit_brightness_override(self):
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(
                root, {"IR": IR},
                flat_device={
                    "Connected": True, "CoverState": "Closed",
                    "MaxBrightness": 100, "Brightness": 0, "LightOn": False,
                    "SupportsOpenClose": True,
                },
            )
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                use_panel=True, panel_brightness=37,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
        self.assertEqual(res.panel_brightness, 37)
        # cover already Closed -> we skip the close_cover call
        actions = [c[0] for c in c.panel_calls]
        self.assertNotIn("close_cover", actions)
        self.assertIn(("set_calibrator_brightness", 37), c.panel_calls)

    def test_no_panel_flag_skips_device_even_when_present(self):
        """--no-panel: even with a working Cover Calibrator on the bus,
        the run uses paper mode and never calls any flat-device method."""
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(
                root, {"IR": IR},
                flat_device={
                    "Connected": True, "CoverState": "Open",
                    "MaxBrightness": 200, "Brightness": 0, "LightOn": False,
                    "SupportsOpenClose": True,
                },
            )
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                use_panel=False,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
        self.assertFalse(res.panel_driven)
        self.assertEqual(c.panel_calls, [])

    def test_panel_in_error_state_falls_back_to_paper(self):
        """If the panel reports CoverState=Error (driver loaded but
        hardware not responding), run_flats falls back to paper mode
        rather than aborting — the bracket loop still works on whatever
        ambient light makes it down the tube."""
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(
                root, {"IR": IR},
                flat_device={
                    "Connected": True, "CoverState": "Error",
                    "MaxBrightness": 100, "Brightness": 0, "LightOn": False,
                    "SupportsOpenClose": True,
                },
            )
            res = run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
        self.assertFalse(res.panel_driven)
        # No cover-close / light-on attempts after the Error read.
        self.assertEqual(c.panel_calls, [])

    def test_panel_teardown_runs_even_when_filter_loop_raises(self):
        """try/finally guarantee: a crash during the per-filter loop
        still kills the EL light. (Open lid is OK at teardown — the
        whole point is not leaving the panel burning.)"""
        with TemporaryDirectory() as d:
            root = Path(d) / "nina"
            c = FakeClient(
                root, {"IR": IR},
                flat_device={
                    "Connected": True, "CoverState": "Closed",
                    "MaxBrightness": 100, "Brightness": 0, "LightOn": False,
                    "SupportsOpenClose": True,
                },
            )

            def crashing_siril(*a, **k):
                raise RuntimeError("siril blew up mid-run")

            with self.assertRaises(RuntimeError):
                run_flats(
                    c, filters=None, gain=120, target_adu=30000.0, frames=4,
                    out_root=Path(d) / "f", nina_root=root,
                    min_exp=0.005, max_exp=30.0,
                    on_step=lambda m: None, siril_runner=crashing_siril,
                )
            # Light was turned on at setup; the final action must be off.
            self.assertEqual(
                c.panel_calls[-1], ("set_calibrator_on", False)
            )

    def _run_partial_failure(self, d, **client_kw):
        root = Path(d) / "nina"
        c = FakeClient(
            root, {"IR": IR},
            flat_device={
                "Connected": True, "CoverState": "Open",
                "MaxBrightness": 100, "Brightness": 0, "LightOn": False,
                "SupportsOpenClose": True,
            },
            **client_kw,
        )
        with self.assertRaises(RuntimeError) as cm:
            run_flats(
                c, filters=None, gain=120, target_adu=30000.0, frames=4,
                out_root=Path(d) / "f", nina_root=root,
                min_exp=0.005, max_exp=30.0,
                on_step=lambda m: None, siril_runner=self._siril_stub(),
            )
        return c, str(cm.exception)

    def test_brightness_failure_after_close_aborts_run(self):
        """Partial failure AFTER the cover closed must ABORT — not proceed
        in 'paper mode' against a shut lid (every filter would bracket as
        opaque) — and must best-effort kill the light on the way out."""
        with TemporaryDirectory() as d:
            c, msg = self._run_partial_failure(d, fail_brightness=True)
            self.assertIn("half-configured", msg)
            self.assertIn("--no-panel", msg)
            # The cover DID close, then the abort tried a light-off.
            self.assertIn(("close_cover", None), c.panel_calls)
            self.assertEqual(c.panel_calls[-1], ("set_calibrator_on", False))
            self.assertEqual(c.hist, [])          # no captures attempted

    def test_light_on_failure_aborts_with_light_off_attempt(self):
        with TemporaryDirectory() as d:
            c, msg = self._run_partial_failure(d, fail_light_on=True)
            self.assertIn("half-configured", msg)
            # The failed ON attempt came first; the abort then tried OFF.
            self.assertIn(("set_calibrator_on", True), c.panel_calls)
            self.assertEqual(c.panel_calls[-1], ("set_calibrator_on", False))
            self.assertEqual(c.hist, [])

    def test_close_cover_failure_aborts_not_paper(self):
        """A close-cover that doesn't confirm leaves the lid state unknown:
        paper mode would be a guess, so the run aborts."""
        with TemporaryDirectory() as d:
            c, msg = self._run_partial_failure(d, fail_close=True)
            self.assertIn("half-configured", msg)
            self.assertIn("cover state unknown", msg)
            self.assertEqual(c.hist, [])


class TestFindCaptureFile(TestCase):
    """Filename-basename matching is the documented invariant — NEVER
    newest-mtime: a concurrent writer in the same tree (Syncthing) would
    otherwise get its frame banked into a master."""

    def test_exact_basename_match_in_subdir(self):
        with TemporaryDirectory() as d:
            sub = Path(d) / "SNAPSHOT"
            sub.mkdir()
            target = sub / "flat_0007.fits"
            target.write_text("x")
            (sub / "flat_0008.fits").write_text("y")
            # History Filename can carry NINA's own path; match by basename.
            self.assertEqual(
                _find_capture_file(Path(d), "C:/nina/save/flat_0007.fits"),
                str(target))

    def test_basename_miss_returns_none_despite_newer_file(self):
        with TemporaryDirectory() as d:
            (Path(d) / "someone_elses.fits").write_text("x")  # newest by mtime
            self.assertIsNone(_find_capture_file(Path(d), "expected.fits"))

    def test_missing_filename_returns_none(self):
        with TemporaryDirectory() as d:
            (Path(d) / "whatever.fits").write_text("x")
            self.assertIsNone(_find_capture_file(Path(d), None))
            self.assertIsNone(_find_capture_file(Path(d), ""))


class TestBuildMaster(TestCase):
    def test_writes_master_and_metadata(self):
        with TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            raw.mkdir()
            (raw / "f1.fits").write_text("x")
            out = Path(d) / "IR_g120"

            def fake_siril(script, *, work_dir, timeout_s=600.0):
                self.assertIn("norm=mul", script)        # validated recipe
                self.assertIn("requires 1.2.0", script)  # header or Siril no-ops
                (Path(work_dir) / "master_flat.tif").write_text("M")
                return "ok"

            mp = build_master(raw, out, metadata={"filter": "IR"},
                              siril_runner=fake_siril)
            self.assertTrue(mp.endswith("master_flat.tif"))
            self.assertTrue((out / "metadata.json").exists())
            self.assertFalse((out / "_siril_work").exists())  # cleaned up

    def test_fit_master_is_canonical_when_present(self):
        with TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            raw.mkdir()
            (raw / "f1.fits").write_text("x")
            out = Path(d) / "IR_g120"

            def fake_siril(script, *, work_dir, timeout_s=600.0):
                self.assertIn("save ", script)            # writes the .fit
                (Path(work_dir) / "master_flat.fit").write_text("FIT")
                (Path(work_dir) / "master_flat.tif").write_text("TIF")
                return "ok"

            mp = build_master(raw, out, metadata={}, siril_runner=fake_siril)
            self.assertTrue(mp.endswith("master_flat.fit"))   # .fit preferred
            self.assertTrue((out / "master_flat.tif").exists())  # preview kept


class TestResolveMaster(TestCase):
    def _flats_root(self, d, *names):
        root = Path(d) / "flats"
        for n in names:
            (root / n).mkdir(parents=True)
            (root / n / "master_flat.fit").write_text("M")
        return root

    def test_matches_newest_by_date(self):
        with TemporaryDirectory() as d:
            root = self._flats_root(
                d, "IR_g120_20260101", "IR_g120_20260519", "LP_g120_20260519")
            lights = Path(d) / "lights"
            write_capture_sidecar(lights, filter="IR", gain=120)
            master, why = resolve_master_for_lights(lights, root)
            self.assertIsNotNone(master)
            self.assertIn("IR_g120_20260519", str(master))
            self.assertTrue(str(master).endswith("master_flat.fit"))

    def test_no_sidecar_is_unresolved(self):
        with TemporaryDirectory() as d:
            root = self._flats_root(d, "IR_g120_20260519")
            master, why = resolve_master_for_lights(Path(d) / "lights", root)
            self.assertIsNone(master)
            self.assertIn(CAPTURE_SIDECAR, why)

    def test_filter_recorded_but_no_master(self):
        with TemporaryDirectory() as d:
            root = self._flats_root(d, "LP_g120_20260519")
            lights = Path(d) / "lights"
            write_capture_sidecar(lights, filter="IR", gain=120)
            master, why = resolve_master_for_lights(lights, root)
            self.assertIsNone(master)
            self.assertIn("no master flat", why)

    def test_empty_filter_in_sidecar_is_unresolved(self):
        with TemporaryDirectory() as d:
            root = self._flats_root(d, "IR_g120_20260519")
            lights = Path(d) / "lights"
            write_capture_sidecar(lights, filter="", gain=120)
            master, why = resolve_master_for_lights(lights, root)
            self.assertIsNone(master)
            self.assertIn("no filter", why)

    def test_gain_default_tag(self):
        with TemporaryDirectory() as d:
            root = self._flats_root(d, "IR_gdefault_20260519")
            lights = Path(d) / "lights"
            write_capture_sidecar(lights, filter="IR", gain=None)
            master, why = resolve_master_for_lights(lights, root)
            self.assertIsNotNone(master)
            self.assertIn("IR_gdefault_20260519", why)
