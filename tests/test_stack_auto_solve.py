"""Verify `mira stack --auto-solve` runs solve only when needed, and
aborts if any frame fails to solve. Mocks subprocess (astap_cli) and
run_siril_stack so no external binaries are touched."""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from astropy.io import fits

from mira import cli


def _write_fits(p: Path, *, with_wcs: bool = False) -> None:
    hdu = fits.PrimaryHDU(data=[[0, 0], [0, 0]])
    if with_wcs:
        hdu.header["CTYPE1"] = "RA---TAN"
        hdu.header["CTYPE2"] = "DEC--TAN"
        hdu.header["CRVAL1"] = 200.0
        hdu.header["CRVAL2"] = 40.0
    hdu.writeto(p, overwrite=True)


def _stack_args(lights: Path, out: Path, *, auto_solve: bool = False,
                cull_low_quality: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        lights=str(lights), out=str(out),
        darks=None, flats=None, flats_root="data/flats", biases=None,
        auto_flats=False, auto_solve=auto_solve,
        cull_low_quality=cull_low_quality,
        debayer=None, stretch=False,
    )


def _astap_runner(*, fail: bool = False):
    """Fake astap_cli: succeeds and injects WCS into the -f target, unless
    fail=True (returncode=1, no WCS injection)."""
    calls: list[list[str]] = []

    def _runner(args, **kw):
        calls.append(list(args))
        if not fail and "-update" in args:
            f_idx = args.index("-f")
            target = Path(args[f_idx + 1])
            if target.exists():
                _write_fits(target, with_wcs=True)
        return subprocess.CompletedProcess(
            args=args, returncode=1 if fail else 0,
            stdout="", stderr="no solution" if fail else "",
        )

    _runner.calls = calls  # type: ignore[attr-defined]
    return _runner


class TestStackAutoSolve(TestCase):
    def test_no_auto_solve_skips_solve_step_entirely(self) -> None:
        """Default behavior (no --auto-solve) hits run_siril_stack directly
        without touching astap_cli, even when frames lack WCS."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "frame_0001.fit", with_wcs=False)

            with patch("mira.solve.subprocess.run") as fake_subproc, \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                fake_stack.return_value = type("R", (), {
                    "n_input_frames": 1, "output_path": Path("x.fit"),
                    "preview_path": None,
                })()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          auto_solve=False))
            self.assertEqual(fake_subproc.call_count, 0)  # never solved
            self.assertEqual(fake_stack.call_count, 1)

    def test_auto_solve_runs_solve_then_stacks(self) -> None:
        """All-unsolved frames trigger ASTAP, then the stack runs."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "a.fit", with_wcs=False)
            _write_fits(lights / "b.fit", with_wcs=False)

            runner = _astap_runner()
            with patch("mira.solve.subprocess.run", side_effect=runner), \
                 patch("mira.solve.find_astap_cli", return_value="astap"), \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                fake_stack.return_value = type("R", (), {
                    "n_input_frames": 2, "output_path": Path("x.fit"),
                    "preview_path": None,
                })()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          auto_solve=True))
                output = buf.getvalue()
            self.assertEqual(len(runner.calls), 2)        # both frames solved
            self.assertEqual(fake_stack.call_count, 1)    # then stacked
            self.assertIn("2/2 frames missing WCS", output)

    def test_auto_solve_skips_when_all_already_solved(self) -> None:
        """A re-run after a previous solve costs zero ASTAP invocations."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "a.fit", with_wcs=True)
            _write_fits(lights / "b.fit", with_wcs=True)

            runner = _astap_runner()
            with patch("mira.solve.subprocess.run", side_effect=runner), \
                 patch("mira.solve.find_astap_cli", return_value="astap"), \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                fake_stack.return_value = type("R", (), {
                    "n_input_frames": 2, "output_path": Path("x.fit"),
                    "preview_path": None,
                })()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          auto_solve=True))
                output = buf.getvalue()
            self.assertEqual(len(runner.calls), 0)        # no ASTAP needed
            self.assertEqual(fake_stack.call_count, 1)
            self.assertIn("already have WCS", output)

    def test_cull_low_quality_runs_before_stack(self) -> None:
        """--cull-low-quality moves low-star frames to _rejected/ before
        Siril runs, so the stack only sees the kept frames."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "good_1.fit", with_wcs=True)
            _write_fits(lights / "good_2.fit", with_wcs=True)
            _write_fits(lights / "bad.fit", with_wcs=True)

            # Mock NINA history: good frames at 100 stars, bad at 10 -> rejected.
            fake_history = [
                {"Filename": "x/good_1.fit", "Stars": 100, "HFR": 2.0},
                {"Filename": "x/good_2.fit", "Stars": 110, "HFR": 2.0},
                {"Filename": "x/bad.fit",    "Stars":  10, "HFR": 2.0},
            ]

            with patch("mira.webapp.nina_client.NinaClient.image_history",
                       return_value=fake_history), \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                fake_stack.return_value = type("R", (), {
                    "n_input_frames": 2, "output_path": Path("x.fit"),
                    "preview_path": None,
                })()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          cull_low_quality=True))
                output = buf.getvalue()
            self.assertTrue((lights / "_rejected" / "bad.fit").exists())
            self.assertFalse((lights / "bad.fit").exists())
            self.assertTrue((lights / "good_1.fit").exists())
            self.assertIn("1 rejected", output)
            self.assertEqual(fake_stack.call_count, 1)

    def test_cull_failure_is_fail_soft(self) -> None:
        """If cull blows up (NINA down, etc.), stack still runs with
        all frames — a connectivity blip shouldn't lose the session."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "a.fit", with_wcs=True)
            with patch("mira.webapp.nina_client.NinaClient.image_history",
                       side_effect=ConnectionError("NINA unreachable")), \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                fake_stack.return_value = type("R", (), {
                    "n_input_frames": 1, "output_path": Path("x.fit"),
                    "preview_path": None,
                })()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          cull_low_quality=True))
                output = buf.getvalue()
            self.assertEqual(fake_stack.call_count, 1)   # stack still ran
            self.assertIn("NINA unreachable", output)
            self.assertIn("continuing", output)

    def test_auto_solve_aborts_stack_on_solve_failure(self) -> None:
        """If ASTAP fails on any frame, the stack is NOT invoked — better
        to bail than produce a WCS-less FITS that submit will reject."""
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _write_fits(lights / "a.fit", with_wcs=False)

            runner = _astap_runner(fail=True)
            with patch("mira.solve.subprocess.run", side_effect=runner), \
                 patch("mira.solve.find_astap_cli", return_value="astap"), \
                 patch("mira.siril_pipeline.run_siril_stack") as fake_stack:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli.stack(_stack_args(lights, Path(d) / "out.fit",
                                          auto_solve=True))
                output = buf.getvalue()
            self.assertEqual(fake_stack.call_count, 0)    # stack was skipped
            self.assertIn("aborting stack", output)
