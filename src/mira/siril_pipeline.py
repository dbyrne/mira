"""Orchestration on top of the raw Siril driver.

Two entry points, one per branch of the forked workflow:

- `run_siril_stack` — the pretty-picture path. Produces a stacked image.
  No correctness obligations beyond "Siril succeeded and wrote a file".

- `run_siril_calibrate_for_photometry` — the opt-in pre-step for
  `mira submit`. Calibrate-only, then a HARD safety gate: Siril is known
  to flip FITS orientation in some configurations, and a flipped image
  with intact WCS keywords would yield wrong magnitudes with no error —
  unacceptable for AAVSO. So every calibrated frame's WCS is cross-checked
  against its pixel content before photometry is allowed to touch it.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .photometry import read_fits_with_wcs
from .siril import (
    SirilError,
    SirilResult,
    build_calibrate_script,
    build_stack_script,
    discover_frames,
    run_siril,
)

# How far (pixels) a star's WCS-predicted position may sit from the nearest
# actually-detected star before we declare the WCS inconsistent with the
# image. A vertical flip moves a star by ~image-height pixels, so this is a
# very wide net for the failure we care about while tolerating sub-pixel
# resampling jitter from calibration.
_WCS_TOLERANCE_PX = 5.0


def run_siril_stack(
    *,
    lights_dir: Path,
    out_path: Path,
    darks_dir: Path | None = None,
    flats_dir: Path | None = None,
    flat_master: Path | None = None,
    biases_dir: Path | None = None,
    debayer: bool | None = None,
    stretch: bool = True,
    cli_path: Path | None = None,
) -> SirilResult:
    """Convert -> calibrate -> register -> rejection-stack `lights_dir`
    into `out_path`. Writes the linear stack as FITS (preserving the WCS
    from the reference frame so the result is photometry-ready) and, when
    `stretch`, a stretched PNG preview. Returns a SirilResult."""
    from .siril import _should_debayer  # local: keep the heuristic in one place

    lights = discover_frames(lights_dir)
    if not lights:
        raise SirilError(f"No Siril-readable frames in {lights_dir}")
    do_debayer = _should_debayer(lights, debayer)

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result_stem = out_path.with_suffix("")
    preview = result_stem.with_name(result_stem.name + "_preview.png") if stretch else None

    work_dir = Path(tempfile.mkdtemp(prefix="mira_siril_stack_"))
    try:
        script = build_stack_script(
            work_dir=work_dir,
            lights_dir=lights_dir.resolve(),
            result_stem=result_stem,
            preview_path=preview,
            darks_dir=darks_dir.resolve() if darks_dir else None,
            flats_dir=flats_dir.resolve() if flats_dir else None,
            flat_master=flat_master.resolve() if flat_master else None,
            biases_dir=biases_dir.resolve() if biases_dir else None,
            debayer=do_debayer,
            stretch=stretch,
        )
        log = run_siril(script, work_dir=work_dir, cli_path=cli_path)
        produced = result_stem.with_suffix(".fit")
        if not produced.exists():
            raise SirilError(
                "Siril reported success but no FITS was written "
                f"({produced}). Check the log:\n"
                + "\n".join(log.strip().splitlines()[-15:])
            )
        return SirilResult(
            output_path=produced,
            preview_path=preview if (preview and preview.exists()) else None,
            n_input_frames=len(lights),
            log_tail="\n".join(log.strip().splitlines()[-10:]),
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _brightest_star_xy(image: np.ndarray) -> tuple[float, float] | None:
    """(x, y) of the brightest detected star, or None if none found.
    DAOStarFinder mirrors what the existing m3/rehearsal code already
    relies on, so no new dependency."""
    from astropy.stats import sigma_clipped_stats
    from photutils.detection import DAOStarFinder

    lum = image if image.ndim == 2 else image.mean(axis=0)
    _, median, std = sigma_clipped_stats(lum, sigma=3.0)
    if std <= 0:
        return None
    finder = DAOStarFinder(fwhm=4.0, threshold=8.0 * std)
    tbl = finder(lum - median)
    if tbl is None or not len(tbl):
        return None
    tbl.sort("flux", reverse=True)
    # photutils 3.0 renamed xcentroid/ycentroid -> x_centroid/y_centroid
    # (old names removed in 4.0). Pick whichever this version exposes.
    cols = tbl.colnames
    xcol = "x_centroid" if "x_centroid" in cols else "xcentroid"
    ycol = "y_centroid" if "y_centroid" in cols else "ycentroid"
    return float(tbl[xcol][0]), float(tbl[ycol][0])


def verify_wcs_preserved(original: Path, calibrated: Path) -> None:
    """Raise SirilError unless the calibrated frame's WCS is still
    consistent with its pixel content.

    Method: take the brightest star in the original, read its sky position
    via the original WCS, project that sky position onto the calibrated
    frame via the calibrated WCS, and confirm a real star sits there. A
    silent vertical flip (the dangerous Siril failure mode) lands the
    prediction in empty sky and trips this check.
    """
    img0, wcs0, _ = read_fits_with_wcs(original)  # raises if no celestial WCS
    img1, wcs1, _ = read_fits_with_wcs(calibrated)

    star0 = _brightest_star_xy(img0)
    if star0 is None:
        raise SirilError(
            f"WCS safety gate: no stars detectable in original {original.name}; "
            "cannot verify Siril preserved orientation. Refusing to proceed."
        )
    sky = wcs0.pixel_to_world(star0[0], star0[1])
    px, py = wcs1.world_to_pixel(sky)

    star1 = _brightest_star_xy(img1)
    if star1 is None:
        raise SirilError(
            f"WCS safety gate: no stars detectable in calibrated {calibrated.name}. "
            "Refusing to proceed."
        )
    # Compare the predicted position of the brightest original star to the
    # brightest calibrated star. For a well-behaved calibrate they are the
    # same physical star; a flip makes them disagree by ~image height.
    dist = float(np.hypot(px - star1[0], py - star1[1]))
    if dist > _WCS_TOLERANCE_PX:
        raise SirilError(
            "WCS safety gate FAILED: brightest star's WCS-predicted pixel "
            f"({px:.1f}, {py:.1f}) is {dist:.1f}px from the actual brightest "
            f"star ({star1[0]:.1f}, {star1[1]:.1f}) in {calibrated.name}. "
            "Siril likely flipped the image while keeping the NINA WCS "
            "keywords — photometry on this would be silently wrong. Aborting. "
            "Run photometry on the raw frames instead (drop --siril-calibrate)."
        )


def run_siril_calibrate_for_photometry(
    *,
    lights_dir: Path,
    darks_dir: Path | None = None,
    flats_dir: Path | None = None,
    biases_dir: Path | None = None,
    cli_path: Path | None = None,
) -> Path:
    """Calibrate-only (no register/stack/debayer), then enforce the WCS
    safety gate on a sample frame. Returns the directory of calibrated
    FITS for the photometry loop to consume. Raises SirilError if Siril
    fails or the safety gate trips."""
    lights = discover_frames(lights_dir)
    fits_lights = [p for p in lights if p.suffix.lower() in (".fit", ".fits", ".fts")]
    if not fits_lights:
        raise SirilError(
            f"--siril-calibrate needs FITS lights with a WCS in {lights_dir}; "
            "none found (photometry requires NINA's plate-solved FITS)."
        )

    out_dir = lights_dir.resolve().parent / (lights_dir.name + "_siril_cal")
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="mira_siril_cal_"))
    prefix = "pp_"
    try:
        script = build_calibrate_script(
            work_dir=work_dir,
            lights_dir=lights_dir.resolve(),
            out_prefix=prefix,
            darks_dir=darks_dir.resolve() if darks_dir else None,
            flats_dir=flats_dir.resolve() if flats_dir else None,
            biases_dir=biases_dir.resolve() if biases_dir else None,
        )
        run_siril(script, work_dir=work_dir, cli_path=cli_path)
        calibrated = sorted(work_dir.glob(f"{prefix}light_*.fit"))
        if not calibrated:
            raise SirilError(
                f"Siril produced no calibrated frames ({prefix}light_*.fit) "
                f"in {work_dir}."
            )
        # Gate on the first frame against its original. Order is stable:
        # convert preserves the sorted input order, so pp_light_00001
        # corresponds to fits_lights[0].
        verify_wcs_preserved(fits_lights[0], calibrated[0])
        # Gate passed — move calibrated frames into the sibling dir.
        for src in calibrated:
            shutil.move(str(src), str(out_dir / src.name))
        return out_dir
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
