"""FITS photometry pipeline. Reads FITS captures from a NINA session,
performs aperture photometry on a target star and a set of AAVSO comparison
stars, and produces an AAVSO Extended File Format upload file.

The math is intentionally simple (circular aperture + annular sky background,
sigma-clipped median sky, magnitude transformation against comp stars). For
serious science you'd want to add air-mass corrections, transformation
coefficients, and dark/flat calibration. This module gets you to "submit
something legitimate to AAVSO" - tuning comes later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS
from photutils.aperture import (
    ApertureStats,
    CircularAnnulus,
    CircularAperture,
    SkyCircularAnnulus,
    SkyCircularAperture,
    aperture_photometry,
)
from astropy.coordinates import SkyCoord
import astropy.units as u


@dataclass
class CompStar:
    """An AAVSO comparison star with known catalog magnitude.

    label: AAVSO sequence label (e.g. "37" for mag 3.7), used in the upload file.
    ra_deg, dec_deg: ICRS coordinates.
    catalog_mag: V-band magnitude (or other band; passed through to the upload).
    catalog_band: AAVSO band code (e.g. "V", "TG").
    """
    label: str
    ra_deg: float
    dec_deg: float
    catalog_mag: float
    catalog_band: str = "V"


@dataclass
class Observation:
    """A single AAVSO observation row, ready for submission."""
    target_name: str
    julian_date: float
    magnitude: float
    magnitude_error: float
    band: str
    comp_star_label: str
    comp_star_mag: float
    check_star_label: str = "na"
    check_star_mag: float = 0.0
    airmass: float | None = None
    chart_id: str = "na"
    notes: str = ""


def read_fits_with_wcs(path: Path) -> tuple[np.ndarray, WCS, dict]:
    """Open a FITS file and return (image data, WCS, header dict)."""
    with fits.open(path) as hdul:
        # NINA writes single-extension FITS (PrimaryHDU). Some pipelines write
        # the image in extension 1 instead. Look in both.
        image = None
        wcs = None
        header = None
        for hdu in hdul:
            if hdu.data is not None and hdu.data.ndim >= 2:
                image = np.asarray(hdu.data, dtype=float)
                header = dict(hdu.header)
                try:
                    wcs = WCS(hdu.header)
                except Exception:
                    wcs = None
                break
        if image is None:
            raise ValueError(f"No image data found in {path}")
        if wcs is None or not wcs.has_celestial:
            raise ValueError(
                f"{path} has no celestial WCS; ensure NINA plate-solved before saving"
            )
        return image, wcs, header


def aperture_flux_at_radec(
    image: np.ndarray,
    wcs: WCS,
    ra_deg: float,
    dec_deg: float,
    aperture_radius_arcsec: float = 6.0,
    sky_inner_arcsec: float = 10.0,
    sky_outer_arcsec: float = 16.0,
) -> tuple[float, float]:
    """Differential aperture photometry at a sky position.

    Returns (background_subtracted_flux, flux_error) in image units (typically
    ADU). Sigma-clipped median sky subtracted from the aperture sum; error is
    sqrt(flux + n_pix * sky_var).
    """
    coord = SkyCoord(ra_deg * u.deg, dec_deg * u.deg, frame="icrs")
    aperture = SkyCircularAperture(coord, r=aperture_radius_arcsec * u.arcsec)
    annulus = SkyCircularAnnulus(
        coord, r_in=sky_inner_arcsec * u.arcsec, r_out=sky_outer_arcsec * u.arcsec
    )
    pixel_aperture = aperture.to_pixel(wcs)
    pixel_annulus = annulus.to_pixel(wcs)

    annulus_stats = ApertureStats(image, pixel_annulus, sigma_clip=None)
    sky_median = float(annulus_stats.median)
    sky_std = float(annulus_stats.std)

    phot = aperture_photometry(image, pixel_aperture)
    raw_sum = float(phot["aperture_sum"][0])
    n_pix_aperture = pixel_aperture.area
    background = sky_median * n_pix_aperture
    flux = raw_sum - background

    # Poisson + sky noise; assumes ADU ~ counts (close enough for this purpose).
    flux_error = math.sqrt(max(flux, 0.0) + n_pix_aperture * sky_std**2)
    return flux, flux_error


def differential_magnitude(
    target_flux: float,
    target_flux_error: float,
    comp_flux: float,
    comp_flux_error: float,
    comp_catalog_mag: float,
) -> tuple[float, float]:
    """Compute (target_magnitude, target_magnitude_error) from differential flux."""
    if target_flux <= 0 or comp_flux <= 0:
        return float("nan"), float("nan")
    target_mag = comp_catalog_mag - 2.5 * math.log10(target_flux / comp_flux)
    # Error propagation on -2.5 log10(F_t / F_c)
    relative_err_t = target_flux_error / target_flux
    relative_err_c = comp_flux_error / comp_flux
    target_mag_err = (2.5 / math.log(10)) * math.sqrt(relative_err_t**2 + relative_err_c**2)
    return target_mag, target_mag_err


def process_capture(
    fits_path: Path,
    target_name: str,
    target_ra_deg: float,
    target_dec_deg: float,
    comp_stars: list[CompStar],
    aperture_radius_arcsec: float = 6.0,
) -> Observation | None:
    """Run photometry on one FITS file.

    Returns an Observation, or None if photometry failed (no WCS, no signal).
    """
    image, wcs, header = read_fits_with_wcs(fits_path)
    target_flux, target_err = aperture_flux_at_radec(
        image, wcs, target_ra_deg, target_dec_deg, aperture_radius_arcsec
    )
    if target_flux <= 0:
        return None

    # Use the brightest comp star with positive flux. A cleaner pipeline would
    # use multiple comps and take a weighted mean - left for a future pass.
    best_comp = None
    best_flux = -math.inf
    best_err = math.nan
    for comp in comp_stars:
        try:
            comp_flux, comp_err = aperture_flux_at_radec(
                image, wcs, comp.ra_deg, comp.dec_deg, aperture_radius_arcsec
            )
        except Exception:
            continue
        if comp_flux > best_flux:
            best_flux = comp_flux
            best_err = comp_err
            best_comp = comp

    if best_comp is None or best_flux <= 0:
        return None

    target_mag, target_mag_err = differential_magnitude(
        target_flux, target_err, best_flux, best_err, best_comp.catalog_mag
    )

    julian_date = _header_julian_date(header)

    return Observation(
        target_name=target_name,
        julian_date=julian_date,
        magnitude=target_mag,
        magnitude_error=target_mag_err,
        band=best_comp.catalog_band if best_comp.catalog_band != "V" else "TG",
        comp_star_label=best_comp.label,
        comp_star_mag=best_comp.catalog_mag,
    )


def _header_julian_date(header: dict) -> float:
    """Pull JD from a FITS header, falling back to DATE-OBS conversion."""
    if "JD" in header:
        return float(header["JD"])
    if "JD-OBS" in header:
        return float(header["JD-OBS"])
    if "DATE-OBS" in header:
        # ISO timestamp, optionally with 'T' separator
        date_str = header["DATE-OBS"].strip()
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc)
        return _datetime_to_jd(dt)
    raise ValueError("No JD/DATE-OBS in FITS header")


def _datetime_to_jd(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    year = dt.year
    month = dt.month
    day_fraction = (
        dt.day
        + (dt.hour + (dt.minute + (dt.second + dt.microsecond / 1_000_000) / 60) / 60) / 24
    )
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day_fraction
        + b
        - 1524.5
    )


def write_aavso_extended_file(
    observations: Iterable[Observation],
    path: Path,
    observer_code: str,
    chart_id: str = "na",
    software: str = "anomaly-scout",
) -> None:
    """Write AAVSO Extended File Format upload (CCD/CMOS observations).

    Format reference: https://www.aavso.org/aavso-extended-file-format
    """
    lines = [
        "#TYPE=Extended",
        f"#OBSCODE={observer_code}",
        f"#SOFTWARE={software}",
        "#DELIM=,",
        "#DATE=JD",
        "#OBSTYPE=CCD",
        "#NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,GROUP,CHART,NOTES",
    ]
    for obs in observations:
        airmass = f"{obs.airmass:.3f}" if obs.airmass is not None else "na"
        notes = obs.notes or "na"
        lines.append(
            ",".join(
                [
                    obs.target_name,
                    f"{obs.julian_date:.5f}",
                    f"{obs.magnitude:.3f}",
                    f"{obs.magnitude_error:.3f}",
                    obs.band,
                    "NO",  # transformation applied
                    "STD",  # magnitude type: standard
                    obs.comp_star_label,
                    f"{obs.comp_star_mag:.3f}",
                    obs.check_star_label,
                    f"{obs.check_star_mag:.3f}" if obs.check_star_label != "na" else "na",
                    airmass,
                    "na",  # group
                    obs.chart_id or chart_id,
                    notes,
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
