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
from typing import Callable, Iterable

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from photutils.aperture import (
    ApertureStats,
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
        image: np.ndarray | None = None
        wcs: WCS | None = None
        header: dict = {}
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


def ensemble_magnitude(
    target_flux: float,
    target_flux_error: float,
    comp_results: list[tuple["CompStar", float, float]],
) -> tuple[float, float, list["CompStar"]]:
    """Combine per-comp magnitude estimates into a robust ensemble.

    `comp_results` is a list of (comp, flux, flux_error) for comps whose
    aperture photometry succeeded. Returns (mag, error, comps_used). The
    algorithm:
      1. Compute a per-comp target-mag estimate via differential_magnitude.
      2. Drop estimates >2σ from the median (where σ is MAD-based; floor 0.05).
      3. Weighted mean weighted by 1/σ_i² of the per-comp magnitude error.

    If only one comp survives, falls back to that single estimate (matches
    the old single-best-comp behavior). Returns (nan, nan, []) if nothing
    is usable.
    """
    if target_flux <= 0:
        return float("nan"), float("nan"), []
    estimates: list[tuple["CompStar", float, float]] = []
    for comp, flux, err in comp_results:
        if flux <= 0:
            continue
        mag, mag_err = differential_magnitude(target_flux, target_flux_error, flux, err, comp.catalog_mag)
        if math.isnan(mag) or math.isnan(mag_err):
            continue
        estimates.append((comp, mag, max(mag_err, 0.001)))
    if not estimates:
        return float("nan"), float("nan"), []
    if len(estimates) == 1:
        comp, mag, err = estimates[0]
        return mag, err, [comp]
    mags = sorted(m for _, m, _ in estimates)
    median = mags[len(mags) // 2]
    deviations = sorted(abs(m - median) for m in mags)
    mad = deviations[len(deviations) // 2]
    sigma = max(mad * 1.4826, 0.05)  # floor at ~photometric noise level
    kept = [(c, m, e) for c, m, e in estimates if abs(m - median) <= 2.0 * sigma]
    if not kept:
        kept = estimates
    weights = [1.0 / (e**2) for _, _, e in kept]
    total_weight = sum(weights)
    weighted_mag = sum(m * w for (_, m, _), w in zip(kept, weights)) / total_weight
    combined_err = math.sqrt(1.0 / total_weight)
    return weighted_mag, combined_err, [c for c, _, _ in kept]


def process_capture(
    fits_path: Path,
    target_name: str,
    target_ra_deg: float,
    target_dec_deg: float,
    comp_stars: list[CompStar],
    aperture_radius_arcsec: float = 6.0,
    on_comp_skipped: Callable[[CompStar, str], None] | None = None,
) -> Observation | None:
    """Run photometry on one FITS file.

    Returns an Observation, or None if photometry failed (no WCS, no signal).
    Uses a multi-comp weighted ensemble (with MAD-based outlier rejection)
    when 2+ comps are usable; falls back to single-comp differential when
    only one survives.

    `on_comp_skipped(comp, reason)` is invoked when a comp star can't be
    used for this frame (out of bounds, exception, non-positive flux).
    Default is silent; callers should pass a logger so the user knows
    why the ensemble is smaller than they expected.
    """
    image, wcs, header = read_fits_with_wcs(fits_path)
    target_flux, target_err = aperture_flux_at_radec(
        image, wcs, target_ra_deg, target_dec_deg, aperture_radius_arcsec
    )
    if target_flux <= 0:
        return None

    comp_results: list[tuple[CompStar, float, float]] = []
    for comp in comp_stars:
        try:
            comp_flux, comp_err = aperture_flux_at_radec(
                image, wcs, comp.ra_deg, comp.dec_deg, aperture_radius_arcsec
            )
        except Exception as exc:
            if on_comp_skipped is not None:
                on_comp_skipped(comp, f"aperture failed: {exc}")
            continue
        if comp_flux <= 0:
            if on_comp_skipped is not None:
                on_comp_skipped(comp, f"non-positive flux ({comp_flux:.1f})")
            continue
        comp_results.append((comp, comp_flux, comp_err))

    if not comp_results:
        return None

    target_mag, target_mag_err, comps_used = ensemble_magnitude(
        target_flux, target_err, comp_results
    )
    if not comps_used or math.isnan(target_mag):
        return None

    julian_date = _header_julian_date(header)

    if len(comps_used) > 1:
        comp_label = "ENSEMBLE"
        comp_catalog_mag = sum(c.catalog_mag for c in comps_used) / len(comps_used)
        # Band: take the most-common band among kept comps (usually all V).
        bands = [c.catalog_band for c in comps_used]
        catalog_band = max(set(bands), key=bands.count)
    else:
        primary = comps_used[0]
        comp_label = primary.label
        comp_catalog_mag = primary.catalog_mag
        catalog_band = primary.catalog_band

    return Observation(
        target_name=target_name,
        julian_date=julian_date,
        magnitude=target_mag,
        magnitude_error=target_mag_err,
        band=catalog_band if catalog_band != "V" else "TG",
        comp_star_label=comp_label,
        comp_star_mag=comp_catalog_mag,
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


def aavso_filename(target_name: str) -> str:
    """File-system-safe filename for the per-target AAVSO upload file.
    Strips spaces, slashes, colons, asterisks, question marks, quotes,
    and pipe characters so the result is safe on Windows + POSIX. Used
    by both the CLI submit command and the webapp's photometry route."""
    forbidden = ' /\\:*?"<>|'
    safe = "".join("_" if ch in forbidden else ch for ch in target_name)
    return f"aavso_{safe}.txt"


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
