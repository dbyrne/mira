from __future__ import annotations

import math
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from anomaly_scout.photometry import (
    CompStar,
    Observation,
    _datetime_to_jd,
    aperture_flux_at_radec,
    differential_magnitude,
    process_capture,
    read_fits_with_wcs,
    write_aavso_extended_file,
)


def _make_synthetic_fits(
    path: Path,
    target_xy: tuple[float, float],
    target_amplitude: float,
    comp_xy: list[tuple[float, float]],
    comp_amplitudes: list[float],
    image_shape: tuple[int, int] = (256, 256),
    sky_level: float = 100.0,
    sky_noise: float = 5.0,
    star_sigma: float = 2.0,
    seed: int = 42,
) -> None:
    """Write a synthetic FITS image with planted Gaussian stars and a linear WCS."""
    rng = np.random.default_rng(seed)
    image = sky_level + rng.normal(0, sky_noise, image_shape).astype(float)

    yy, xx = np.indices(image_shape)

    def add_star(x, y, amplitude):
        return amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * star_sigma**2))

    image += add_star(*target_xy, target_amplitude)
    for (cx, cy), amp in zip(comp_xy, comp_amplitudes):
        image += add_star(cx, cy, amp)

    # Build a simple gnomic WCS centered at (RA=180, Dec=20), 1 arcsec/pixel
    w = WCS(naxis=2)
    w.wcs.crpix = [image_shape[1] / 2, image_shape[0] / 2]
    w.wcs.crval = [180.0, 20.0]
    w.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]  # 1 arcsec/pixel, RA decreasing right
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    header = w.to_header()
    header["DATE-OBS"] = "2026-05-04T22:00:00"
    header["OBJECT"] = "TEST"

    fits.writeto(path, image, header, overwrite=True)


class FitsReadingTests(TestCase):
    def test_read_fits_with_wcs(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.fits"
            _make_synthetic_fits(path, (128, 128), 1000, [(150, 130)], [800])
            image, wcs, header = read_fits_with_wcs(path)
            self.assertEqual(image.shape, (256, 256))
            self.assertTrue(wcs.has_celestial)
            self.assertEqual(header["OBJECT"], "TEST")


class AperturePhotometryTests(TestCase):
    def test_recovers_planted_star_flux(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.fits"
            _make_synthetic_fits(path, (128, 128), 1000, [], [])
            image, wcs, _ = read_fits_with_wcs(path)
            # Pixel (128, 128) with our WCS = center of image = RA=180, Dec=20
            sky = wcs.pixel_to_world(128, 128)
            flux, err = aperture_flux_at_radec(
                image, wcs, sky.ra.deg, sky.dec.deg, aperture_radius_arcsec=10.0
            )
            # Flux should be roughly the integrated Gaussian: 2*pi*sigma^2 * amplitude
            # = 2 * pi * 4 * 1000 ~ 25000 ADU.
            self.assertGreater(flux, 15000)
            self.assertLess(flux, 35000)
            self.assertGreater(err, 0)


class DifferentialMagnitudeTests(TestCase):
    def test_equal_flux_means_equal_mag(self) -> None:
        target_mag, _ = differential_magnitude(1000, 32, 1000, 32, 10.0)
        self.assertAlmostEqual(target_mag, 10.0, places=3)

    def test_brighter_target_gives_lower_mag(self) -> None:
        # Target 2.512x brighter than comp -> 1 mag brighter
        target_mag, _ = differential_magnitude(2512, 50, 1000, 32, 10.0)
        self.assertAlmostEqual(target_mag, 9.0, places=2)

    def test_negative_flux_returns_nan(self) -> None:
        target_mag, target_err = differential_magnitude(-100, 10, 1000, 30, 10.0)
        self.assertTrue(math.isnan(target_mag))


class ProcessCaptureTests(TestCase):
    def test_end_to_end_synthetic(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.fits"
            # Target at center, comp 30 px to the right
            _make_synthetic_fits(
                path,
                target_xy=(128, 128),
                target_amplitude=1000.0,
                comp_xy=[(158, 128)],
                comp_amplitudes=[2512.0],  # ~1 mag brighter than target
                seed=1,
            )
            image, wcs, _ = read_fits_with_wcs(path)
            target_sky = wcs.pixel_to_world(128, 128)
            comp_sky = wcs.pixel_to_world(158, 128)
            comps = [
                CompStar(
                    label="100",
                    ra_deg=comp_sky.ra.deg,
                    dec_deg=comp_sky.dec.deg,
                    catalog_mag=10.0,
                    catalog_band="V",
                )
            ]
            obs = process_capture(
                path,
                target_name="TEST",
                target_ra_deg=target_sky.ra.deg,
                target_dec_deg=target_sky.dec.deg,
                comp_stars=comps,
            )
            self.assertIsNotNone(obs)
            # Comp star is 1 mag brighter, so target should be ~11.0
            self.assertGreater(obs.magnitude, 10.6)
            self.assertLess(obs.magnitude, 11.4)


class AavsoFileTests(TestCase):
    def test_extended_file_header_and_row(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            obs = Observation(
                target_name="RR LYR",
                julian_date=2461165.5,
                magnitude=8.234,
                magnitude_error=0.012,
                band="TG",
                comp_star_label="095",
                comp_star_mag=9.512,
                airmass=1.234,
                chart_id="X12345AAB",
            )
            write_aavso_extended_file([obs], path, observer_code="ABC")
            content = path.read_text()
            self.assertIn("#TYPE=Extended", content)
            self.assertIn("#OBSCODE=ABC", content)
            self.assertIn("#SOFTWARE=anomaly-scout", content)
            self.assertIn("RR LYR,2461165.50000,8.234,0.012,TG", content)
            self.assertIn("095,9.512", content)
            self.assertIn("X12345AAB", content)


class JulianDateTests(TestCase):
    def test_j2000_epoch(self) -> None:
        from datetime import datetime, timezone
        # J2000.0 = 2000-01-01 12:00 TT, JD = 2451545.0
        jd = _datetime_to_jd(datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc))
        self.assertAlmostEqual(jd, 2451545.0, places=3)
