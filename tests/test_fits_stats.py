"""Per-FITS quality metric tests with synthetic FITS (planted stars +
known sky), so no real captures or NINA are needed."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from astropy.io import fits

from mira.fits_stats import compute_frame_quality


def _synth_fits(
    path: Path, *, shape: tuple[int, int] = (200, 200),
    bg: float = 1000.0, n_stars: int = 20,
    sigma: float = 4.0, elongate: bool = False,
    add_wcs: bool = False, wcs_ra: float = 180.0, wcs_dec: float = 0.0,
    bright_patch: tuple[float, float, float] | None = None,
    seed: int = 0,
) -> Path:
    """Render a 2-D FITS with `n_stars` Gaussians + uniform sky + noise.
    `elongate` stretches sigma_y to 3x for a trailing-star test.
    `bright_patch=(x_frac, y_frac, amp)` adds a broad bright blob (a
    fake galaxy-region) at that fractional position.
    """
    rng = np.random.default_rng(seed)
    h, w = shape
    img = np.full(shape, bg, dtype=np.float32)
    img += rng.normal(0, 30, shape).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    margin = max(20, int(4 * sigma))
    sx = sigma
    # 1.8x is the real-world trailing case DAO still detects but flags
    # via roundness1; >2x and DAO rejects them as not-stars (the count
    # drops instead — a different failure mode for cull).
    sy = sigma * 1.8 if elongate else sigma
    for _ in range(n_stars):
        x = rng.uniform(margin, w - margin)
        y = rng.uniform(margin, h - margin)
        amp = rng.uniform(5000, 15000)
        img += amp * np.exp(
            -(((xx - x) ** 2) / (2 * sx ** 2)
              + ((yy - y) ** 2) / (2 * sy ** 2))
        ).astype(np.float32)
    if bright_patch is not None:
        bx_frac, by_frac, amp = bright_patch
        cx, cy = bx_frac * w, by_frac * h
        broad = sigma * 6.0
        img += amp * np.exp(
            -(((xx - cx) ** 2) / (2 * broad ** 2)
              + ((yy - cy) ** 2) / (2 * broad ** 2))
        ).astype(np.float32)
    hdu = fits.PrimaryHDU(img)
    if add_wcs:
        hdr = hdu.header
        hdr["CTYPE1"] = "RA---TAN"
        hdr["CTYPE2"] = "DEC--TAN"
        hdr["CRPIX1"] = w / 2.0
        hdr["CRPIX2"] = h / 2.0
        hdr["CRVAL1"] = wcs_ra
        hdr["CRVAL2"] = wcs_dec
        hdr["CDELT1"] = -0.001    # degrees per pixel
        hdr["CDELT2"] = 0.001
    hdu.writeto(path, overwrite=True)
    return path


class TestComputeFrameQuality(TestCase):
    def test_detects_planted_stars_and_measures_hfr_roundness(self) -> None:
        with TemporaryDirectory() as d:
            p = _synth_fits(Path(d) / "ok.fit", n_stars=20)
            q = compute_frame_quality(p)
        self.assertIsNotNone(q.stars)
        self.assertGreaterEqual(q.stars, 8)     # most stars found post-2x2 bin
        self.assertIsNotNone(q.hfr)
        self.assertGreater(q.hfr, 0.5)          # plausible binned HFR
        self.assertLess(q.hfr, 8.0)
        self.assertIsNotNone(q.roundness)
        self.assertLess(q.roundness, 0.3)       # round stars

    def test_no_stars_yields_zero_count_and_sky_only(self) -> None:
        with TemporaryDirectory() as d:
            p = _synth_fits(Path(d) / "empty.fit", n_stars=0, bg=1500.0)
            q = compute_frame_quality(p)
        self.assertEqual(q.stars, 0)
        self.assertIsNone(q.hfr)                # no stars -> no HFR
        self.assertIsNotNone(q.sky_median)
        self.assertAlmostEqual(q.sky_median, 1500.0, delta=120.0)
        self.assertIn("no stars", q.note)

    def test_trailing_lifts_roundness(self) -> None:
        with TemporaryDirectory() as d:
            ok = _synth_fits(Path(d) / "ok.fit", n_stars=20, elongate=False)
            trail = _synth_fits(Path(d) / "trail.fit", n_stars=20, elongate=True)
            q_ok = compute_frame_quality(ok)
            q_trail = compute_frame_quality(trail)
        self.assertIsNotNone(q_trail.roundness)
        self.assertIsNotNone(q_ok.roundness)
        # |roundness1| should be much larger for elongated stars.
        self.assertGreater(q_trail.roundness, q_ok.roundness + 0.05)

    def test_has_wcs_flag(self) -> None:
        with TemporaryDirectory() as d:
            with_w = _synth_fits(Path(d) / "w.fit", add_wcs=True)
            no_w = _synth_fits(Path(d) / "now.fit", add_wcs=False)
            self.assertTrue(compute_frame_quality(with_w).has_wcs)
            self.assertFalse(compute_frame_quality(no_w).has_wcs)

    def test_target_region_uses_wcs_when_present(self) -> None:
        # Bright "galaxy" blob at the corner; without WCS the central-box
        # falls on dark sky; with WCS+target at the corner, sky_median
        # samples the blob and reports a much higher value.
        with TemporaryDirectory() as d:
            p = _synth_fits(
                Path(d) / "blob.fit", shape=(200, 200), n_stars=10,
                add_wcs=True, wcs_ra=180.0, wcs_dec=0.0,
                bright_patch=(0.85, 0.85, 3000),
            )
            q_central = compute_frame_quality(p)  # no target -> central box
            # Corner pixel ~ (170, 170); WCS @ CRPIX 100,100, CDELT
            # (-0.001, +0.001) -> RA = 180 - 70*(-0.001) actually let me
            # recompute: x_offset_pix = (RA-CRVAL)/CDELT1 + CRPIX1.
            # We want pixel (170, 170): so
            # RA = CRVAL1 + (170-CRPIX1)*CDELT1 = 180 + 70*(-0.001) = 179.93
            # Dec = CRVAL2 + (170-CRPIX2)*CDELT2 = 0 + 70*0.001 = 0.07
            q_blob = compute_frame_quality(
                p, target_ra=179.93, target_dec=0.07,
            )
        self.assertIsNotNone(q_central.sky_median)
        self.assertIsNotNone(q_blob.sky_median)
        # The blob region must be brighter than the central-box region.
        self.assertGreater(q_blob.sky_median, q_central.sky_median + 200)

    def test_bad_fits_does_not_raise(self) -> None:
        with TemporaryDirectory() as d:
            bad = Path(d) / "garbage.fit"
            bad.write_bytes(b"not a fits file")
            q = compute_frame_quality(bad)
            # Returns a FrameQuality with note explaining; never raises.
            self.assertIsNotNone(q.note)
            self.assertEqual(q.stars, None)
