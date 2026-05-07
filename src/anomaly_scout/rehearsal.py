"""Dress-rehearsal: generate synthetic FITS frames for a real target and
run them through the full submit pipeline.

The point is to exercise the entire workflow before the gear arrives:
- VSX lookup hits the real network and produces real ra/dec
- VSP fetch hits the real network and produces real comp-star coordinates
- Synthetic FITS are generated with planted target + comps at the
  correct sky positions (via a tangent-projection WCS centered on the
  target), with small magnitude variations frame-to-frame
- submit_pipeline reads the FITS, resolves the same comps, runs
  photometry, writes an AAVSO Extended File
- We compare recovered magnitudes to the planted "truth" magnitudes
  and flag any drift > 0.4 mag

This catches: VSX format drift, VSP format drift, FITS header
parsing edge cases, AAVSO file column drift, and pipeline integration
bugs that unit tests miss.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from .photometry import CompStar


@dataclass
class RehearsalReport:
    target_name: str
    target_ra_deg: float
    target_dec_deg: float
    planted_target_mag: float
    chart_id: str
    n_frames: int
    n_comps_used: int
    comp_band: str
    output_dir: Path
    recovered_median_mag: float | None
    recovered_min_mag: float | None
    recovered_max_mag: float | None
    aavso_path: Path | None
    issues: list[str]

    @property
    def magnitude_residual(self) -> float | None:
        if self.recovered_median_mag is None:
            return None
        return self.recovered_median_mag - self.planted_target_mag


def synthesize_frames(
    target_ra_deg: float,
    target_dec_deg: float,
    target_mag: float,
    comps: list[CompStar],
    output_dir: Path,
    *,
    n_frames: int = 20,
    # Frame must be large enough to contain the VSP-fetched comps, which
    # spread up to ~30 arcmin from the target at default fov_arcmin=60.
    # 1024×1024 at 4"/pix = 68 arcmin FOV, plenty of room.
    image_shape: tuple[int, int] = (1024, 1024),
    pixel_scale_arcsec: float = 4.0,
    sky_level: float = 100.0,
    sky_noise: float = 5.0,
    star_sigma_pix: float = 2.0,
    frame_jitter_mag: float = 0.05,
    frame_cadence_seconds: float = 30.0,
    start_jd: float = 2461165.5,
    seed: int = 1,
) -> list[Path]:
    """Generate `n_frames` synthetic FITS files in `output_dir` with the
    target planted at the image center and each comp planted at its
    correct relative sky position. The WCS is tangent-projected at the
    target's RA/Dec so plate-solve-style code can recover the same
    sky-to-pixel mapping the pipeline expects.

    Comps that fall outside the image are skipped silently. The frame
    cadence drives the JD timestamp so produced lightcurves span a
    realistic short interval."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    height, width = image_shape

    # Tangent-projection WCS centered on the target.
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [width / 2.0 + 0.5, height / 2.0 + 0.5]
    wcs.wcs.crval = [target_ra_deg, target_dec_deg]
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    # Convert each comp's sky position into pixel coordinates.
    def _to_pixel(ra_deg: float, dec_deg: float) -> tuple[float, float] | None:
        from astropy.coordinates import SkyCoord
        import astropy.units as u
        coord = SkyCoord(ra_deg * u.deg, dec_deg * u.deg, frame="icrs")
        try:
            x, y = wcs.world_to_pixel(coord)
        except Exception:
            return None
        if not (0 <= x < width and 0 <= y < height):
            return None
        return float(x), float(y)

    target_xy = _to_pixel(target_ra_deg, target_dec_deg)
    if target_xy is None:
        raise RuntimeError("Target fell outside the synthetic frame center somehow")

    # Comp pixel positions + a flux scaling factor that puts them at the
    # right relative brightness vs. the target. The target gets reference
    # amplitude `target_amplitude_ref`; a comp 1 mag brighter is 2.512x.
    target_amplitude_ref = 800.0
    comp_pixels: list[tuple[CompStar, tuple[float, float], float]] = []
    for comp in comps:
        pix = _to_pixel(comp.ra_deg, comp.dec_deg)
        if pix is None:
            continue  # off-frame comps just don't contribute
        # flux_ratio = 10^(0.4 * (target_mag - comp_mag)); a comp 1 mag
        # brighter than the target has 2.512x the flux of the target.
        flux_ratio = 10 ** (0.4 * (target_mag - comp.catalog_mag))
        comp_pixels.append((comp, pix, target_amplitude_ref * flux_ratio))

    paths: list[Path] = []
    for frame_idx in range(n_frames):
        jitter = rng.normal(0.0, frame_jitter_mag)
        target_amp = target_amplitude_ref * 10 ** (-0.4 * jitter)

        image = sky_level + rng.normal(0, sky_noise, image_shape).astype(float)
        yy, xx = np.mgrid[0:height, 0:width]

        # Plant target at center
        gx, gy = target_xy
        image += target_amp * np.exp(
            -((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * star_sigma_pix ** 2)
        )
        # Plant comps
        for _comp, (cx, cy), comp_amp in comp_pixels:
            image += comp_amp * np.exp(
                -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * star_sigma_pix ** 2)
            )

        header = wcs.to_header()
        jd = start_jd + frame_idx * frame_cadence_seconds / 86400.0
        header["JD"] = jd
        header["EXPTIME"] = float(frame_cadence_seconds)
        header["NAXIS"] = 2
        header["NAXIS1"] = width
        header["NAXIS2"] = height

        path = output_dir / f"rehearsal_{frame_idx:03d}.fits"
        fits.PrimaryHDU(image.astype(np.float32), header=header).writeto(path, overwrite=True)
        paths.append(path)
    return paths


def run_rehearsal(
    target_name: str,
    output_dir: Path,
    n_frames: int = 20,
    observer_code: str = "TEST",
) -> RehearsalReport:
    """Drive the full rehearsal: VSX lookup, VSP comps, synthetic FITS,
    submit_pipeline, AAVSO file. Returns a structured report so the
    caller (the CLI) can print a clean summary."""
    from .photometry import write_aavso_extended_file
    from .submit_pipeline import (
        FrameRecord,
        preflight_fits_dir,
        resolve_comps,
        run_photometry_loop,
    )
    from .vsx import fetch_vsx_target_by_name

    issues: list[str] = []
    print(f"[rehearsal] Looking up '{target_name}' in VSX…")
    vsx_target = fetch_vsx_target_by_name(target_name)
    if vsx_target is None:
        raise RuntimeError(
            f"Could not resolve '{target_name}' in VSX. Check the spelling "
            "or your network."
        )
    planted_mag = vsx_target.bright_mag if vsx_target.bright_mag is not None else 10.0
    print(
        f"[rehearsal] Target: {vsx_target.name} at RA {vsx_target.ra_deg:.5f}, "
        f"Dec {vsx_target.dec_deg:.5f}; planting at mag {planted_mag:.2f}"
    )

    print("[rehearsal] Fetching comp stars from VSP…")
    resolution = resolve_comps(
        target_name=target_name,
        target_bright_mag=vsx_target.bright_mag,
        comp_path=None,
        chart_id_override="na",
    )
    print(f"[rehearsal] {len(resolution.comps)} comps from chart {resolution.chart_id}")

    output_dir = output_dir.resolve()
    print(f"[rehearsal] Generating {n_frames} synthetic FITS at {output_dir}…")
    fits_paths = synthesize_frames(
        target_ra_deg=vsx_target.ra_deg,
        target_dec_deg=vsx_target.dec_deg,
        target_mag=planted_mag,
        comps=resolution.comps,
        output_dir=output_dir,
        n_frames=n_frames,
    )
    if not fits_paths:
        raise RuntimeError("Frame generation produced zero files — should not happen.")

    print("[rehearsal] Running submit_pipeline on the synthetic frames…")
    try:
        files = preflight_fits_dir(output_dir)
    except ValueError as exc:
        raise RuntimeError(f"Preflight failed on synthetic frames: {exc}")

    def _on_frame(frame: FrameRecord) -> None:
        if frame.flag in ("failed", "no-signal"):
            issues.append(f"frame {frame.filename}: {frame.flag} ({frame.note})")
        # quiet — caller will see the summary

    result = run_photometry_loop(
        target_name=target_name,
        target_ra_deg=vsx_target.ra_deg,
        target_dec_deg=vsx_target.dec_deg,
        fits_files=files,
        comps=resolution.comps,
        chart_id=resolution.chart_id,
        on_frame=_on_frame,
    )

    aavso_path: Path | None = None
    recovered_min = recovered_max = None
    if result.observations:
        from .photometry import aavso_filename
        aavso_path = output_dir / aavso_filename(target_name)
        write_aavso_extended_file(
            result.observations,
            aavso_path,
            observer_code=observer_code,
            chart_id=resolution.chart_id,
        )
        mags = [o.magnitude for o in result.observations]
        recovered_min, recovered_max = min(mags), max(mags)
    else:
        issues.append("no observations recovered from any frame")

    comp_band = resolution.comps[0].catalog_band if resolution.comps else "?"

    report = RehearsalReport(
        target_name=vsx_target.name,
        target_ra_deg=vsx_target.ra_deg,
        target_dec_deg=vsx_target.dec_deg,
        planted_target_mag=planted_mag,
        chart_id=resolution.chart_id,
        n_frames=len(fits_paths),
        n_comps_used=len(resolution.comps),
        comp_band=comp_band,
        output_dir=output_dir,
        recovered_median_mag=result.median_mag,
        recovered_min_mag=recovered_min,
        recovered_max_mag=recovered_max,
        aavso_path=aavso_path,
        issues=issues,
    )

    if report.magnitude_residual is not None and abs(report.magnitude_residual) > 0.4:
        report.issues.append(
            f"recovered magnitude {report.recovered_median_mag:.2f} differs from "
            f"planted {planted_mag:.2f} by {report.magnitude_residual:+.2f} mag "
            "— investigate ensemble or comp-star math"
        )
    return report
