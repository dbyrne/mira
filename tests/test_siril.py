"""Tests for the Siril driver and orchestration.

siril-cli is never invoked here — script generation is pure and the
runner is mocked. The WCS safety gate is exercised with synthetic FITS,
including the silent-flip failure mode it exists to catch.
"""
from __future__ import annotations

import os
import shutil
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
from mira.siril_pipeline import (
    run_siril_calibrate_for_photometry,
    run_siril_stack,
    verify_wcs_preserved,
)


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


def _make_two_star_fits(path: Path, swap_brightness: bool = False,
                        flip: bool = False) -> None:
    """Two well-separated near-equal stars. `swap_brightness` mimics a
    calibration that legitimately reorders which star measures brightest."""
    rng = np.random.default_rng(11)
    image = (100 + rng.normal(0, 3, (256, 256))).astype(float)
    yy, xx = np.mgrid[0:256, 0:256]
    amp_a, amp_b = (4000.0, 2600.0)
    if swap_brightness:
        amp_a, amp_b = amp_b, amp_a
    image += amp_a * np.exp(-((xx - 170) ** 2 + (yy - 70) ** 2) / (2 * 2.0**2))
    image += amp_b * np.exp(-((xx - 60) ** 2 + (yy - 180) ** 2) / (2 * 2.0**2))
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
        # Linear stack saves as FITS so the WCS header from the reference
        # frame survives — TIFF can't carry FITS keywords, and photometry
        # downstream needs the WCS.
        self.assertNotIn("savetif32", s)
        self.assertIn('save "result"', s)  # bare `save` writes FITS
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

    def test_flat_master_with_space_raises_early(self) -> None:
        # flat_master rides a `-flat=` option arg, which Siril can't quote.
        # A space must fail at script-build time with an actionable message,
        # not as a cryptic mid-script Siril error.
        with self.assertRaises(SirilError) as ctx:
            build_stack_script(
                work_dir=Path("/w"), lights_dir=Path("/lights"),
                result_stem=Path("/out/r"), preview_path=None,
                flat_master=Path("/data/my flats/master_flat.fit"),
                debayer=False, stretch=False,
            )
        self.assertIn("space", str(ctx.exception))
        self.assertIn("-flat=", str(ctx.exception))

    def test_flats_dir_with_space_is_fine(self) -> None:
        # Directory inputs are used only via quoted positional `cd` args,
        # which handle spaces — they must NOT trip the flat_master guard.
        s = build_stack_script(
            work_dir=Path("/w"), lights_dir=Path("/lights"),
            result_stem=Path("/out/r"), preview_path=None,
            flats_dir=Path("/my flats"),
            debayer=False, stretch=False,
        )
        self.assertIn('cd "/my flats"', s)

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

    def test_subprocess_decoding_is_utf8_replace(self) -> None:
        # text=True without encoding= decodes with the locale codec (cp1252
        # on Windows) in STRICT mode — a stray byte in Siril's log would
        # raise UnicodeDecodeError mid-run.
        captured: dict = {}

        class _Proc:
            returncode = 0
            stdout = "log: ok\n"
            stderr = ""

        def _run(args, **kw):
            captured.update(kw)
            return _Proc()

        with TemporaryDirectory() as d, patch("mira.siril.find_siril_cli",
                                              return_value=Path("siril-cli")):
            with patch("mira.siril.subprocess.run", side_effect=_run):
                run_siril("requires 1.2.0\n", work_dir=Path(d))
        self.assertTrue(captured.get("text"))
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")


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

    def test_brightness_reorder_between_stars_passes(self) -> None:
        # Calibration can legitimately reorder which of two near-equal stars
        # measures brightest. The gate must match the NEAREST detected star
        # to the WCS prediction — the old brightest-vs-brightest comparison
        # false-aborted on this case (the two stars are ~155 px apart).
        with TemporaryDirectory() as d:
            orig = Path(d) / "orig.fits"
            cal = Path(d) / "cal.fits"
            _make_two_star_fits(orig, swap_brightness=False)
            _make_two_star_fits(cal, swap_brightness=True)
            verify_wcs_preserved(orig, cal)  # must not raise

    def test_flip_still_caught_with_multiple_stars(self) -> None:
        # The nearest-star gate must not soften the real failure: with a
        # flip, no detected star sits anywhere near the predicted position
        # (the nearest one is still ~110 px away here).
        with TemporaryDirectory() as d:
            orig = Path(d) / "orig.fits"
            cal = Path(d) / "cal.fits"
            _make_two_star_fits(orig)
            _make_two_star_fits(cal, flip=True)
            with self.assertRaises(SirilError) as ctx:
                verify_wcs_preserved(orig, cal)
        self.assertIn("WCS safety gate FAILED", str(ctx.exception))


class TestRunSirilStack(TestCase):
    def test_multidot_out_name_finds_produced_fit(self) -> None:
        # `mira stack --out M51.lrgb.tif`: Siril saves stem "M51.lrgb" +
        # ".fit". The produced-file check must APPEND ".fit" — with_suffix
        # replaced ".lrgb" and looked for M51.fit, yielding a false
        # "no FITS was written" on a run that succeeded.
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            (lights / "a.fits").touch()
            out = Path(d) / "M51.lrgb.tif"

            def _fake_run(script, *, work_dir, cli_path=None):
                # what Siril actually writes for `save "M51.lrgb"`
                (out.resolve().parent / "M51.lrgb.fit").write_text("x")
                return "log: ok"

            with patch("mira.siril_pipeline.run_siril", side_effect=_fake_run):
                res = run_siril_stack(lights_dir=lights, out_path=out, stretch=False)
            self.assertEqual(res.output_path.name, "M51.lrgb.fit")
            self.assertTrue(res.output_path.exists())


class TestCalibrateForPhotometry(TestCase):
    def test_non_fits_contamination_raises(self) -> None:
        # Siril `convert` ingests every readable image; the frame-index
        # pairing assumes FITS-only. A stray JPG must abort with the file
        # named, never silently shift indices.
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            (lights / "a.fits").touch()
            (lights / "stray.jpg").touch()
            (lights / "notes.txt").touch()  # not Siril-readable: ignored
            with self.assertRaises(SirilError) as ctx:
                run_siril_calibrate_for_photometry(lights_dir=lights)
        msg = str(ctx.exception)
        self.assertIn("stray.jpg", msg)
        self.assertNotIn("notes.txt", msg)

    def test_fits_only_lights_calibrate_succeeds(self) -> None:
        # FITS-only dirs must not trip the contamination guard, and the
        # calibrated frames land in the sibling _siril_cal dir.
        with TemporaryDirectory() as d:
            lights = Path(d) / "lights"
            lights.mkdir()
            _make_fits(lights / "frame1.fits")

            def _fake_run(script, *, work_dir, cli_path=None):
                shutil.copy(lights / "frame1.fits", work_dir / "pp_light_00001.fit")
                return "log: ok"

            with patch("mira.siril_pipeline.run_siril", side_effect=_fake_run):
                out_dir = run_siril_calibrate_for_photometry(lights_dir=lights)
            self.assertTrue((out_dir / "pp_light_00001.fit").exists())
