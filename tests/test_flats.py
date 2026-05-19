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
    stars."""

    def __init__(self, nina_root: Path, responses: dict, mode: str = ""):
        self.nina_root = Path(nina_root)
        self.responses = responses
        self.mode = mode
        self.cur = next(iter(responses))
        self._n = 0
        self.hist: list[dict] = []
        self.set_calls: list[str] = []

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
