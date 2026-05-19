"""Tests for the Siril driver and orchestration.

siril-cli is never invoked here — script generation is pure and the
runner is mocked. The WCS safety gate is exercised with synthetic FITS,
including the silent-flip failure mode it exists to catch.
"""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from mira.siril import (
    SirilError,
    SirilNotFound,
    _q,
    _should_debayer,
    build_calibrate_script,
    build_stack_script,
    discover_frames,
    find_siril_cli,
    run_siril,
)
from mira.siril_pipeline import verify_wcs_preserved


def _wcs_header(shape=(256, 256)) -> fits.Header:
    w = WCS(naxis=2)
    w.wcs.crpix = [shape[1] / 2, shape[0] / 2]
    w.wcs.crval = [180.0, 45.0]
    w.wcs.cdelt = [-0.0005, 0.0005]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w.to_header()


def _make_fits(path: Path, flip: bool = False) -> None:
    rng = np.random.default_rng(7)
    image = (100 + rng.normal(0, 3, (256, 256))).astype(float)
    yy, xx = np.mgrid[0:256, 0:256]
    # Bright star off-center so a vertical flip is unambiguous.
    image += 4000 * np.exp(-((xx - 170) ** 2 + (yy - 70) ** 2) / (2 * 2.0**2))
    if flip:
        image = np.flipud(image)  # pixels move; header WCS stays stale
    hdr = fits.Header()
    hdr.update(_wcs_header())
    fits.PrimaryHDU(data=image, header=hdr).writeto(path, overwrite=True)


class TestDiscovery(TestCase):
    def test_discover_filters_and_sorts(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "b.fits").touch()
            (root / "a.fits").touch()
            (root / "notes.txt").touch()
            (root / "c.jpg").touch()
            found = discover_frames(root)
            self.assertEqual([p.name for p in found], ["a.fits", "b.fits", "c.jpg"])

    def test_should_debayer_auto(self) -> None:
        jpgs = [Path("x.jpg"), Path("y.JPEG")]
        fitsf = [Path("x.fits"), Path("y.cr2")]
        self.assertFalse(_should_debayer(jpgs, None))
        self.assertTrue(_should_debayer(fitsf, None))
        # Explicit override wins.
        self.assertTrue(_should_debayer(jpgs, True))
        self.assertFalse(_should_debayer(fitsf, False))


class TestFindCli(TestCase):
    def test_env_override_missing_raises(self) -> None:
        with patch.dict(os.environ, {"MIRA_SIRIL_CLI": r"C:\nope\siril-cli.exe"}):
            with self.assertRaises(SirilNotFound):
                find_siril_cli()

    def test_env_override_used(self) -> None:
        with TemporaryDirectory() as d:
            fake = Path(d) / "siril-cli.exe"
            fake.write_text("")
            with patch.dict(os.environ, {"MIRA_SIRIL_CLI": str(fake)}):
                self.assertEqual(find_siril_cli(), fake)


class TestScriptGeneration(TestCase):
    def test_stack_script_no_masters(self) -> None:
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/result"), preview_path=Path("/out/result_preview.png"),
            debayer=False, stretch=True,
        )
        self.assertIn("requires 1.2.0", s)
        self.assertIn("convert light", s)
        self.assertIn("register light", s)
        self.assertIn("stack r_light rej 3 3", s)
        self.assertIn("savetif32", s)
        self.assertIn("autostretch", s)
        self.assertNotIn("calibrate", s)
        # Regression: -fitseq corrupts NINA 16-bit FITS ("bitpix set as
        # 20"); the lights must be converted exactly once (a second
        # convert into the same sequence also corrupts it).
        self.assertNotIn("-fitseq", s)
        self.assertEqual(s.count("convert light"), 1)

    def test_no_masters_debayer_single_convert(self) -> None:
        # The bug: no-masters + CFA did `convert light` then a second
        # `convert light -debayer`, corrupting the FITSEQ. Must be one
        # convert, debayered, no -fitseq.
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/result"), preview_path=None,
            debayer=True, stretch=False,
        )
        self.assertEqual(s.count("convert light"), 1)
        self.assertIn("convert light -debayer", s)
        self.assertNotIn("-fitseq", s)
        self.assertNotIn("calibrate", s)

    def test_stack_script_with_masters_calibrates(self) -> None:
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/result"), preview_path=None,
            darks_dir=Path("/d"), flats_dir=Path("/f"), biases_dir=Path("/b"),
            debayer=True, stretch=False,
        )
        self.assertIn("stack bias rej 3 3 -nonorm -out=bias_stacked", s)
        self.assertIn("calibrate flat -bias=bias_stacked", s)
        self.assertIn("-dark=dark_stacked -cc=dark", s)
        self.assertIn("-flat=pp_flat_stacked", s)
        self.assertIn("-debayer", s)
        self.assertIn("register pp_light", s)
        self.assertNotIn("autostretch", s)  # stretch=False

    def test_prebuilt_flat_master_skips_restack(self) -> None:
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/result"), preview_path=None,
            flat_master=Path("/data/flats/IR_g120_20260519/master_flat.fit"),
            debayer=True, stretch=False,
        )
        self.assertIn(
            "-flat=/data/flats/IR_g120_20260519/master_flat.fit", s)
        self.assertNotIn("convert flat", s)            # no re-convert
        self.assertNotIn("stack flat", s)              # no re-stack
        self.assertIn("calibrate light", s)

    def test_flat_master_takes_precedence_over_flats_dir(self) -> None:
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/r"), preview_path=None,
            flats_dir=Path("/f"), flat_master=Path("/m/master_flat.fit"),
            debayer=False, stretch=False,
        )
        self.assertIn("-flat=/m/master_flat.fit", s)
        self.assertNotIn("stack flat", s)

    def test_calibrate_script_has_no_register_or_stack_of_lights(self) -> None:
        s = build_calibrate_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            out_prefix="pp_", darks_dir=Path("/d"),
        )
        self.assertIn("calibrate light -dark=dark_stacked -cc=dark -prefix=pp_", s)
        self.assertNotIn("register light", s)
        self.assertNotIn("stack r_", s)
        self.assertNotIn("debayer", s)  # photometry must keep CFA geometry
        self.assertNotIn("-fitseq", s)  # same NINA-FITS corruption applies here


class TestPathSafety(TestCase):
    def test_q_rejects_quote_and_newline(self) -> None:
        # A `"` or newline would inject extra Siril script commands.
        self.assertEqual(_q(Path("/ok/path.fits")), '"/ok/path.fits"')
        for bad in ('/x/a"b.fits', "/x/a\nclose\nrm.fits", "/x/a\r.fits"):
            with self.assertRaises(SirilError):
                _q(Path(bad))

    def test_run_siril_rejects_spaced_workdir(self) -> None:
        with patch("mira.siril.find_siril_cli", return_value=Path("siril-cli")):
            with self.assertRaises(SirilError) as ctx:
                run_siril("requires 1.2.0\n", work_dir=Path("/tmp/with space"))
        self.assertIn("space", str(ctx.exception))


class TestRunSiril(TestCase):
    def test_nonzero_exit_raises_with_log_tail(self) -> None:
        class _Proc:
            returncode = 1
            stdout = "log: starting\nlog: boom: bad command\n"
            stderr = ""

        with TemporaryDirectory() as d, patch("mira.siril.find_siril_cli",
                                              return_value=Path("siril-cli")):
            with patch("mira.siril.subprocess.run", return_value=_Proc()):
                with self.assertRaises(SirilError) as ctx:
                    run_siril("requires 1.2.0\n", work_dir=Path(d))
        self.assertIn("exited 1", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))

    def test_success_returns_log(self) -> None:
        class _Proc:
            returncode = 0
            stdout = "log: ok\n"
            stderr = ""

        with TemporaryDirectory() as d, patch("mira.siril.find_siril_cli",
                                              return_value=Path("siril-cli")):
            with patch("mira.siril.subprocess.run", return_value=_Proc()):
                log = run_siril("requires 1.2.0\n", work_dir=Path(d))
        self.assertIn("ok", log)


class TestWcsSafetyGate(TestCase):
    def test_unflipped_passes(self) -> None:
        with TemporaryDirectory() as d:
            orig = Path(d) / "orig.fits"
            cal = Path(d) / "cal.fits"
            _make_fits(orig, flip=False)
            _make_fits(cal, flip=False)
            verify_wcs_preserved(orig, cal)  # must not raise

    def test_silent_flip_is_caught(self) -> None:
        with TemporaryDirectory() as d:
            orig = Path(d) / "orig.fits"
            cal = Path(d) / "cal.fits"
            _make_fits(orig, flip=False)
            _make_fits(cal, flip=True)  # flipped pixels, stale WCS
            with self.assertRaises(SirilError) as ctx:
                verify_wcs_preserved(orig, cal)
        self.assertIn("WCS safety gate FAILED", str(ctx.exception))
