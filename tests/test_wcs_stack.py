"""Tests for WCS-based registration stacking (`wcs_register_stack`).

The NGC 7000 lesson: Siril's star alignment can't register emission-FILLED
fields (too few detectable stars), but the frames are plate-solved — so we
register by WCS instead. These tests pin that the WCS shift actually aligns
frames whose same-sky star sits at *different pixels* (different CRPIX), and
that the no-WCS path fails loudly rather than silently misbehaving.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from mira.siril import SirilError
from mira.siril_pipeline import _gather_lights, run_siril_stack, wcs_register_stack

SIZE = 200
CRVAL = (10.0, 20.0)
SCALE = 0.001  # deg/px


def _solved_frame(path: Path, crpix, *, with_wcs=True):
    """A frame with a single bright star planted at the sky point CRVAL,
    which (by construction) lands at pixel crpix-1 (0-based). Varying crpix
    across frames = the same star at different pixels but the same sky."""
    rng = np.random.default_rng(1)
    img = rng.normal(100.0, 3.0, (SIZE, SIZE)).astype(np.float32)
    sx, sy = crpix[0] - 1, crpix[1] - 1  # 0-based pixel of CRVAL
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    img += (6000.0 * np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 2.0 ** 2)))
            ).astype(np.float32)
    if with_wcs:
        w = WCS(naxis=2)
        w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        w.wcs.crval = list(CRVAL)
        w.wcs.crpix = list(crpix)
        w.wcs.cdelt = [-SCALE, SCALE]
        hdr = w.to_header()
    else:
        hdr = fits.Header()
    fits.writeto(path, img, hdr, overwrite=True)
    return (sx, sy)


class TestWcsRegisterStack(TestCase):
    def test_registers_same_sky_star_to_one_peak(self):
        with TemporaryDirectory() as d:
            dd = Path(d)
            ref_xy = _solved_frame(dd / "f0.fits", (100, 100))   # ref star (99,99)
            _solved_frame(dd / "f1.fits", (112, 94))             # same sky, diff px
            _solved_frame(dd / "f2.fits", (88, 109))
            out = dd / "stack.fit"
            res = wcs_register_stack(dd, out, stretch=False)

            self.assertTrue(res.output_path.exists())
            data = np.asarray(fits.getdata(res.output_path), dtype=float)
            # WCS carried onto the result (photometry-ready)
            self.assertTrue(WCS(fits.getheader(res.output_path)).has_celestial)
            # One sharp peak, at the reference star's pixel (all frames aligned)
            py, px = np.unravel_index(int(np.argmax(data)), data.shape)
            self.assertLessEqual(abs(px - ref_xy[0]), 2)
            self.assertLessEqual(abs(py - ref_xy[1]), 2)
            # The OTHER frames' original star pixels are now background — proof
            # the shift happened (un-aligned, they'd each leave a peak).
            self.assertLess(data[93, 111], data[ref_xy[1], ref_xy[0]] * 0.5)
            self.assertLess(data[108, 87], data[ref_xy[1], ref_xy[0]] * 0.5)
            self.assertEqual(res.n_input_frames, 3)

    def test_no_wcs_raises(self):
        with TemporaryDirectory() as d:
            dd = Path(d)
            _solved_frame(dd / "a.fits", (100, 100), with_wcs=False)
            _solved_frame(dd / "b.fits", (105, 100), with_wcs=False)
            with self.assertRaises(SirilError):
                wcs_register_stack(dd, dd / "stack.fit", stretch=False)


class TestMultiDirCoStack(TestCase):
    """`mira stack --lights A B` co-stacks: frames are gathered into an
    ephemeral temp dir for the run (no persistent `_combined`)."""

    def test_gather_single_dir_is_noop(self):
        with TemporaryDirectory() as d:
            dd = Path(d)
            _solved_frame(dd / "a.fits", (100, 100))
            eff, cleanup = _gather_lights([dd])
            self.assertEqual(eff, dd)              # used in place, not copied
            cleanup()
            self.assertTrue((dd / "a.fits").exists())   # no-op cleanup

    def test_costack_two_dirs_recomposes_and_stacks(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "sess_a", root / "sess_b"
            a.mkdir(); b.mkdir()
            _solved_frame(a / "f0.fits", (100, 100))
            _solved_frame(a / "f1.fits", (102, 99))
            _solved_frame(b / "f0.fits", (98, 101))   # dup name -> prefixed on gather
            res = run_siril_stack(lights_dir=[a, b], out_path=root / "stack.fit",
                                  register_mode="wcs", stretch=False)
            self.assertTrue(res.output_path.exists())
            self.assertEqual(res.n_input_frames, 3)    # all 3 gathered + stacked
