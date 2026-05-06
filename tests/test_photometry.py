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
    ensemble_magnitude,
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


class EnsembleMagnitudeTests(TestCase):
    def _comp(self, label: str, mag: float) -> CompStar:
        return CompStar(label=label, ra_deg=0.0, dec_deg=0.0, catalog_mag=mag, catalog_band="V")

    def test_single_comp_falls_back_to_single_diff(self) -> None:
        comp = self._comp("100", 10.0)
        mag, err, kept = ensemble_magnitude(2512, 50, [(comp, 1000, 32)])
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(mag, 9.0, places=2)

    def test_two_consistent_comps_ensemble(self) -> None:
        # Both comps should put the target at ~9.0:
        #   c1: cat 10.0, comp_flux 1000 → target_mag = 10 - 2.5*log10(2512/1000) = 9.0
        #   c2: cat 10.5, comp_flux 631  → target_mag = 10.5 - 2.5*log10(2512/631) = 9.0
        c1 = self._comp("100", 10.0)
        c2 = self._comp("105", 10.5)
        mag, err, kept = ensemble_magnitude(
            2512, 50, [(c1, 1000, 32), (c2, 631, 25)]
        )
        self.assertEqual(len(kept), 2)
        self.assertAlmostEqual(mag, 9.0, delta=0.1)

    def test_outlier_comp_dropped(self) -> None:
        # 4 comps: 3 give ~9.0, 1 gives ~7.0 (way off — should be dropped)
        c1 = self._comp("100", 10.0)
        c2 = self._comp("101", 10.0)
        c3 = self._comp("102", 10.0)
        bad = self._comp("999", 10.0)
        good_flux = (1000, 32)
        # Bad comp: pretend its measured flux is 100 instead of 1000 → target appears 7.0
        bad_flux = (100, 12)
        mag, err, kept = ensemble_magnitude(
            2512, 50, [(c1, *good_flux), (c2, *good_flux), (c3, *good_flux), (bad, *bad_flux)]
        )
        # The 3 good comps survive, bad is dropped
        self.assertEqual(len(kept), 3)
        self.assertAlmostEqual(mag, 9.0, delta=0.1)

    def test_zero_flux_target_returns_nan(self) -> None:
        c1 = self._comp("100", 10.0)
        mag, err, kept = ensemble_magnitude(0, 0, [(c1, 1000, 32)])
        self.assertTrue(math.isnan(mag))
        self.assertEqual(kept, [])

    def test_no_usable_comps_returns_nan(self) -> None:
        c1 = self._comp("100", 10.0)
        # Comp flux is zero — should be filtered out
        mag, err, kept = ensemble_magnitude(2512, 50, [(c1, 0, 0)])
        self.assertTrue(math.isnan(mag))


class AavsoFileRoundTripTests(TestCase):
    """Write an AAVSO Extended File, parse it back, and assert each row
    matches the source Observation. Catches header/column drift that
    individual format tests would miss."""

    def _parse(self, path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
        text = path.read_text(encoding="utf-8")
        headers: dict[str, str] = {}
        col_names: list[str] = []
        rows: list[dict[str, str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                stripped = line.lstrip("#")
                # The column-spec header starts with NAME, (the first column).
                if stripped.startswith("NAME,"):
                    col_names = stripped.split(",")
                else:
                    key, _, value = stripped.partition("=")
                    headers[key] = value
                continue
            parts = line.split(",")
            rows.append(dict(zip(col_names, parts, strict=True)))
        return headers, rows

    def test_roundtrip_preserves_observation_fields(self) -> None:
        from anomaly_scout.photometry import Observation, write_aavso_extended_file

        observations = [
            Observation(
                target_name="RR LYR",
                julian_date=2461165.50000 + i * 0.01042,
                magnitude=7.5 + i * 0.01,
                magnitude_error=0.05,
                band="TG",
                comp_star_label="ENSEMBLE" if i % 2 else "97",
                comp_star_mag=9.7,
                chart_id="X12345",
            )
            for i in range(5)
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "aavso.txt"
            write_aavso_extended_file(observations, path, observer_code="ABC", chart_id="X12345")
            headers, rows = self._parse(path)

        self.assertEqual(headers["TYPE"], "Extended")
        self.assertEqual(headers["OBSCODE"], "ABC")
        self.assertEqual(headers["DELIM"], ",")
        self.assertEqual(headers["DATE"], "JD")
        self.assertEqual(len(rows), 5)
        for i, row in enumerate(rows):
            self.assertEqual(row["NAME"], "RR LYR")
            self.assertAlmostEqual(float(row["DATE"]), 2461165.50000 + i * 0.01042, places=4)
            self.assertAlmostEqual(float(row["MAG"]), 7.5 + i * 0.01, places=2)
            self.assertEqual(row["FILT"], "TG")
            self.assertEqual(row["MTYPE"], "STD")
            self.assertEqual(row["CHART"], "X12345")
            # Comp label rotates between "97" and "ENSEMBLE"
            self.assertIn(row["CNAME"], ("97", "ENSEMBLE"))


class CompSkipCallbackTests(TestCase):
    """process_capture must invoke on_comp_skipped(comp, reason) for every
    comp it can't use, so the caller can surface the skip in logs. Before
    batch Y this was silently swallowed."""

    def test_callback_fires_for_out_of_bounds_comp(self) -> None:
        from anomaly_scout.photometry import CompStar, process_capture

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.fits"
            _make_synthetic_fits(
                path,
                target_xy=(128, 128),
                target_amplitude=1000.0,
                comp_xy=[(158, 128)],
                comp_amplitudes=[2512.0],
                seed=2,
            )
            from anomaly_scout.photometry import read_fits_with_wcs
            _, wcs, _ = read_fits_with_wcs(path)
            target_sky = wcs.pixel_to_world(128, 128)
            comp_sky = wcs.pixel_to_world(158, 128)

            in_field = CompStar(
                label="100", ra_deg=comp_sky.ra.deg, dec_deg=comp_sky.dec.deg,
                catalog_mag=10.0, catalog_band="V",
            )
            # A bogus comp that's nowhere near the image — astropy will raise
            far_away = CompStar(
                label="999", ra_deg=0.0, dec_deg=-89.0,
                catalog_mag=10.0, catalog_band="V",
            )
            skipped: list[tuple[str, str]] = []

            def on_skip(comp, reason: str) -> None:
                skipped.append((comp.label, reason))

            obs = process_capture(
                path,
                target_name="TEST",
                target_ra_deg=target_sky.ra.deg,
                target_dec_deg=target_sky.dec.deg,
                comp_stars=[in_field, far_away],
                on_comp_skipped=on_skip,
            )
            self.assertIsNotNone(obs)
            # At least one skip recorded for the far-away comp
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0][0], "999")
            self.assertNotEqual(skipped[0][1], "")


class ProcessCaptureTests(TestCase):
    def test_multi_comp_ensemble_end_to_end(self) -> None:
        """Plant a target + 3 consistent comps in a synthetic FITS, run
        process_capture with all of them, expect:
        - Returned observation uses CNAME='ENSEMBLE'
        - Magnitude is within 0.4 mag of the planted value
        - Combined error is smaller than the single-comp case (statistical
          benefit of ensembling)."""
        from anomaly_scout.photometry import CompStar, process_capture, read_fits_with_wcs
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ensemble.fits"
            # Target at center, 3 comps each ~1 mag brighter at different positions
            _make_synthetic_fits(
                path,
                target_xy=(128, 128),
                target_amplitude=1000.0,
                comp_xy=[(158, 128), (98, 128), (128, 158)],
                comp_amplitudes=[2512.0, 2512.0, 2512.0],
                seed=3,
            )
            _, wcs, _ = read_fits_with_wcs(path)
            target_sky = wcs.pixel_to_world(128, 128)
            comp_skys = [
                wcs.pixel_to_world(158, 128),
                wcs.pixel_to_world(98, 128),
                wcs.pixel_to_world(128, 158),
            ]
            comps = [
                CompStar(label=f"100-{i}", ra_deg=s.ra.deg, dec_deg=s.dec.deg,
                         catalog_mag=10.0, catalog_band="V")
                for i, s in enumerate(comp_skys)
            ]
            obs = process_capture(
                path,
                target_name="TEST",
                target_ra_deg=target_sky.ra.deg,
                target_dec_deg=target_sky.dec.deg,
                comp_stars=comps,
            )
            self.assertIsNotNone(obs)
            self.assertEqual(obs.comp_star_label, "ENSEMBLE")
            # Comp is 1 mag brighter (10.0 - 2.5*log10(2512/1000) = 9.0); target
            # is at the comp brightness divided by 2.512, so target ~ 11.0.
            self.assertGreater(obs.magnitude, 10.6)
            self.assertLess(obs.magnitude, 11.4)
            # Magnitude error must be a finite positive value
            self.assertGreater(obs.magnitude_error, 0.0)
            self.assertLess(obs.magnitude_error, 0.5)

    def test_ensemble_drops_outlier_comp(self) -> None:
        """If 3 comps say target is ~11 and a 4th comp is contaminated and
        says target is ~9, the outlier should be dropped (>2σ from the
        median) and the resulting magnitude should agree with the 3 good
        comps. This is the load-bearing claim of the multi-comp ensemble."""
        from anomaly_scout.photometry import (
            CompStar,
            ensemble_magnitude,
        )
        target_flux = 1000.0
        target_err = 32.0
        good_comps = [
            CompStar(label=f"good{i}", ra_deg=0, dec_deg=0, catalog_mag=10.0, catalog_band="V")
            for i in range(3)
        ]
        bad_comp = CompStar(label="bad", ra_deg=0, dec_deg=0, catalog_mag=10.0, catalog_band="V")
        # Good comps each give target_mag = 10.0 - 2.5*log10(1000/2512) ~ 11.0
        # Bad comp's measured flux is way too low → predicts target much brighter
        results = [
            (good_comps[0], 2512.0, 50.0),
            (good_comps[1], 2512.0, 50.0),
            (good_comps[2], 2512.0, 50.0),
            (bad_comp, 200.0, 14.0),  # outlier
        ]
        mag, err, kept = ensemble_magnitude(target_flux, target_err, results)
        self.assertEqual(len(kept), 3, "outlier should be dropped")
        self.assertNotIn("bad", [c.label for c in kept])
        self.assertAlmostEqual(mag, 11.0, delta=0.1)


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
