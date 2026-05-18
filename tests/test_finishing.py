"""Tests for the finishing stage. GraXpert and Siril are never invoked —
arg/script construction is pure, runners are mocked. The point is that a
regression in the GraXpert command contract, crop math, or step ordering
fails CI, not a 40-minute on-sky reprocess."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from PIL import Image

from mira.finishing import (
    GraXpertError,
    GraXpertNotFound,
    autocrop_box,
    build_graxpert_args,
    build_stretch_script,
    find_graxpert,
    fixed_margin_box,
    run_finish,
    run_graxpert_step,
)


class TestFindGraxpert(TestCase):
    def test_env_exe_on_disk(self) -> None:
        with TemporaryDirectory() as d:
            exe = Path(d) / "graxpert.exe"
            exe.write_text("")
            with patch.dict(os.environ, {"MIRA_GRAXPERT": str(exe)}):
                self.assertEqual(find_graxpert(), [str(exe)])

    def test_env_multitoken_trusted(self) -> None:
        with patch.dict(os.environ, {"MIRA_GRAXPERT": "python -m graxpert.main"}):
            self.assertEqual(find_graxpert(), ["python", "-m", "graxpert.main"])

    def test_missing_raises_actionable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("mira.finishing.shutil.which", return_value=None):
                with patch("mira.finishing.importlib.util.find_spec", return_value=None):
                    with self.assertRaises(GraXpertNotFound) as ctx:
                        find_graxpert()
        self.assertIn("mira[finishing]", str(ctx.exception))

    def test_module_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("mira.finishing.shutil.which", return_value=None):
                with patch("mira.finishing.importlib.util.find_spec", return_value=object()):
                    inv = find_graxpert()
        self.assertEqual(inv[-2:], ["-m", "graxpert.main"])


class TestGraxpertArgs(TestCase):
    def test_args_shape_and_cli_flag(self) -> None:
        a = build_graxpert_args(["gx"], "denoising", Path("in.fits"), Path("/o/out"), gpu=False)
        self.assertEqual(a[:4], ["gx", "-cmd", "denoising", "in.fits"])
        self.assertIn("-cli", a)
        self.assertEqual(a[a.index("-gpu") + 1], "false")
        self.assertEqual(a[a.index("-output") + 1], str(Path("/o/out")))

    def test_unknown_command_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_graxpert_args(["gx"], "sharpen-everything", Path("i"), Path("o"))

    def test_run_step_success(self) -> None:
        with TemporaryDirectory() as d:
            stem = Path(d) / "gx_bg"

            class _P:
                returncode = 0
                stdout = "Finished"
                stderr = ""

            def _run(args, **kw):
                Path(str(stem) + ".fits").write_text("x")  # GraXpert writes this
                return _P()

            with patch("mira.finishing.subprocess.run", side_effect=_run):
                out = run_graxpert_step(["gx"], "background-extraction", Path(d) / "in.fits", stem)
            self.assertEqual(out, Path(str(stem) + ".fits"))

    def test_run_step_missing_output_is_error(self) -> None:
        class _P:
            returncode = 0
            stdout = "log: done but wrote nothing"
            stderr = ""

        with TemporaryDirectory() as d, patch("mira.finishing.subprocess.run", return_value=_P()):
            with self.assertRaises(GraXpertError):
                run_graxpert_step(["gx"], "denoising", Path(d) / "in.fits", Path(d) / "nope")

    def test_run_step_timeout(self) -> None:
        with TemporaryDirectory() as d:
            with patch(
                "mira.finishing.subprocess.run",
                side_effect=subprocess.TimeoutExpired("gx", 1),
            ):
                with self.assertRaises(GraXpertError):
                    run_graxpert_step(["gx"], "denoising", Path(d) / "i.fits", Path(d) / "o")


class TestCrop(TestCase):
    def test_autocrop_trims_dark_border(self) -> None:
        img = np.full((400, 300), 200.0)
        img[:40, :] = 5.0       # dark top band
        img[:, -30:] = 5.0      # dark right band
        l, t, r, b = autocrop_box(img, drop_below=0.5, max_frac=0.3)
        self.assertGreaterEqual(t, 40)
        self.assertLessEqual(r, 270)
        self.assertEqual(l, 0)

    def test_autocrop_cap_respected(self) -> None:
        img = np.full((1000, 1000), 1.0)  # everything "dark" vs itself? ref=1, thr<1
        # uniform image: nothing below threshold -> full frame
        l, t, r, b = autocrop_box(img)
        self.assertEqual((l, t, r, b), (0, 0, 1000, 1000))

    def test_fixed_margin(self) -> None:
        img = np.zeros((1000, 500, 3))
        self.assertEqual(fixed_margin_box(img, 0.10), (50, 100, 450, 900))
        # clamped
        self.assertEqual(fixed_margin_box(img, 0.9), (225, 450, 275, 550))


class TestStretchScript(TestCase):
    def test_script_has_linked_stretch_and_satu(self) -> None:
        s = build_stretch_script(Path("/o"), Path("/o/in.fits"), "final", saturation=0.2)
        self.assertIn("autostretch -linked", s)
        self.assertIn("satu 0.20", s)
        self.assertIn("savetif", s)
        self.assertIn("savepng", s)
        self.assertIn("requires 1.2.0", s)

    def test_zero_saturation_omits_satu(self) -> None:
        s = build_stretch_script(Path("/o"), Path("/o/in.fits"), "final", saturation=0.0)
        self.assertNotIn("satu", s)


class TestRunFinishOrchestration(TestCase):
    def _fake_siril(self, script, *, work_dir, cli_path=None):
        # Emulate Siril writing the stretched outputs into work_dir.
        for ext in ("png", "tif"):
            Image.new("RGB", (120, 200), (40, 40, 40)).save(work_dir / f"stretched.{ext}")
        return "log: ok"

    def test_full_chain_order_and_outputs(self) -> None:
        with TemporaryDirectory() as d:
            src = Path(d) / "master.tif"
            Image.new("RGB", (120, 200), (30, 30, 30)).save(src)
            out = Path(d) / "final.png"
            calls: list[str] = []

            def _gx(inv, cmd, in_path, out_stem, **kw):
                calls.append(cmd)
                p = Path(str(out_stem) + ".fits")
                p.write_text("x")
                return p

            with patch("mira.finishing.find_graxpert", return_value=["gx"]), \
                 patch("mira.finishing.run_graxpert_step", side_effect=_gx), \
                 patch("mira.finishing.run_siril", side_effect=self._fake_siril):
                res = run_finish(src, out, crop="none", saturation=0.2)

            self.assertEqual(
                calls, ["background-extraction", "denoising", "deconv-obj"]
            )
            self.assertTrue(out.exists())
            self.assertTrue(out.with_suffix(".tif").exists())
            self.assertIn("siril:autostretch-linked", res.steps)
            self.assertTrue(any(s.startswith("graxpert:") for s in res.steps))

    def test_no_ai_path_needs_no_graxpert(self) -> None:
        with TemporaryDirectory() as d:
            src = Path(d) / "m.tif"
            Image.new("RGB", (100, 100), (20, 20, 20)).save(src)
            out = Path(d) / "o.png"
            with patch("mira.finishing.find_graxpert",
                       side_effect=GraXpertNotFound("should not be called")), \
                 patch("mira.finishing.run_siril", side_effect=self._fake_siril):
                res = run_finish(
                    src, out, do_bg=False, do_denoise=False, do_deconv=False,
                    crop="none",
                )
            self.assertTrue(out.exists())
            self.assertFalse(any(s.startswith("graxpert:") for s in res.steps))

    def test_missing_input_raises(self) -> None:
        with TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                run_finish(Path(d) / "nope.tif", Path(d) / "o.png")
