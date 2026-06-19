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


def _gather_lights(dirs: list[Path]):
    """Return (effective_dir, cleanup_fn) for stacking `dirs`. A single dir is
    used in place (no-op cleanup). MULTIPLE dirs are CO-STACKED: every frame is
    gathered (hardlink — same-volume, instant, zero bytes; copy fallback across
    volumes) into a fresh temp dir, names prefixed by source-dir to avoid
    collisions. That temp dir is the ephemeral "combined" — it exists only for
    this stack, is never archived/backed-up, and cleanup_fn removes it. So
    co-stacks recompose on the fly instead of needing a persistent (and
    backup-doubling) `_combined` dir under captures/."""
    import os
    if len(dirs) == 1:
        return dirs[0], (lambda: None)
    gathered = Path(tempfile.mkdtemp(prefix="mira_stack_combine_"))
    for d in dirs:
        for f in discover_frames(d):
            dest = gathered / f"{d.name}__{f.name}"
            try:
                os.link(str(f), str(dest))           # hardlink (same volume)
            except OSError:
                shutil.copy2(f, dest)                # cross-volume fallback
    return gathered, (lambda: shutil.rmtree(gathered, ignore_errors=True))


def run_siril_stack(
    *,
    lights_dir,
    out_path: Path,
    darks_dir: Path | None = None,
    flats_dir: Path | None = None,
    flat_master: Path | None = None,
    biases_dir: Path | None = None,
    debayer: bool | None = None,
    stretch: bool = True,
    cli_path: Path | None = None,
    register_mode: str = "auto",
    weight: str = "noise",
) -> SirilResult:
    """Convert -> calibrate -> register -> rejection-stack into `out_path`.
    Writes the linear stack as FITS (preserving the WCS from the reference
    frame so the result is photometry-ready) and, when `stretch`, a stretched
    PNG preview. Returns a SirilResult.

    `lights_dir` may be a single dir OR a list of session dirs. Multiple dirs
    are CO-STACKED — their frames are gathered into an ephemeral temp dir for
    this run only (the recomposed "combined" never persists / never enters the
    backup; see `_gather_lights`).

    `register_mode`: "stars" = Siril Global Star Alignment only; "wcs" =
    register by plate-solved WCS + sigma-clip mean (`wcs_register_stack`,
    robust for emission-FILLED fields where star detection finds too few
    stars); "auto" (default) = try Siril GSA, fall back to WCS when it fails
    and the frames are solved."""
    from .siril import _should_debayer  # local: keep the heuristic in one place

    _dirs = [Path(d) for d in
             (lights_dir if isinstance(lights_dir, (list, tuple)) else [lights_dir])]
    lights_dir, _cleanup_gather = _gather_lights(_dirs)
    try:
        lights = discover_frames(lights_dir)
        if not lights:
            raise SirilError(
                "No Siril-readable frames in "
                + ", ".join(str(d) for d in _dirs)
            )
        do_debayer = _should_debayer(lights, debayer)

        out_path = out_path.resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result_stem = out_path.with_suffix("")
        preview = result_stem.with_name(result_stem.name + "_preview.png") if stretch else None

        if register_mode == "wcs":
            return wcs_register_stack(lights_dir, out_path, stretch=stretch)

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
                weight=weight,
            )
            log = run_siril(script, work_dir=work_dir, cli_path=cli_path)
            # Append, don't with_suffix: for a multi-dot out name (M51.lrgb.tif
            # -> stem M51.lrgb) with_suffix would REPLACE ".lrgb" and look for
            # M51.fit while Siril wrote M51.lrgb.fit.
            produced = result_stem.parent / (result_stem.name + ".fit")
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
        except SirilError as exc:
            if register_mode != "auto":
                raise
            # Siril star alignment failed (typically "not enough stars" on an
            # emission-filled field). If the frames are plate-solved, register
            # by WCS instead — that's the point of "auto". (NGC 7000 lesson: a
            # stack failure here was never a data-quality verdict.)
            print(
                "  Siril star-alignment stack failed "
                f"({str(exc).splitlines()[0][:160]}).\n"
                "  Falling back to WCS registration (needs plate-solved frames)..."
            )
            return wcs_register_stack(lights_dir, out_path, stretch=stretch)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    finally:
        _cleanup_gather()


def wcs_register_stack(
    lights_dir: Path,
    out_path: Path,
    *,
    stretch: bool = True,
    sigma_low: float = 3.0,
    sigma_high: float = 3.0,
) -> SirilResult:
    """Register plate-solved frames by their WCS (translation) and combine
    with a sigma-clipped mean. The robust path for emission-FILLED fields
    where Siril's Global Star Alignment can't find enough point sources (the
    bright nebula defeats default star detection — the NGC 7000 case).

    Each light must carry a celestial WCS (run `mira solve` first). Alignment
    is translation-only: the equatorial rigs have negligible field rotation
    over a night, and the dither/drift we correct is pure shift; for rotated
    sets use Siril GSA. No flat/dark calibration is applied here — calibrate
    via the Siril path (`--register stars`) if you need it. The reference
    frame's WCS header is carried onto the result, so the FITS stays
    photometry-ready, exactly like the Siril path.
    """
    from astropy.io import fits
    from astropy.stats import sigma_clip
    from scipy.ndimage import shift as nd_shift

    lights = discover_frames(lights_dir)
    if not lights:
        raise SirilError(f"No Siril-readable frames in {lights_dir}")

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result_stem = out_path.with_suffix("")
    produced = result_stem.parent / (result_stem.name + ".fit")
    preview = (result_stem.with_name(result_stem.name + "_preview.png")
               if stretch else None)

    ref_wcs = ref_path = ref_center = None
    H = W = None
    aligned: list = []
    skipped: list[str] = []
    for p in lights:
        try:
            img, wcs, _hdr = read_fits_with_wcs(p)  # raises without celestial WCS
        except Exception:
            skipped.append(p.name)
            continue
        if img.ndim == 3:
            img = img.mean(axis=0)              # collapse to mono for registration
        img = np.asarray(img, dtype=np.float32)
        if ref_wcs is None:
            ref_wcs, ref_path = wcs, p
            H, W = img.shape
            ref_center = ref_wcs.pixel_to_world(W / 2.0, H / 2.0)
            aligned.append(img)
        else:
            if img.shape != (H, W):
                skipped.append(p.name)
                continue
            x, y = wcs.world_to_pixel(ref_center)   # where ref-center sits here
            dy, dx = (H / 2.0 - float(y)), (W / 2.0 - float(x))
            aligned.append(
                nd_shift(img, (dy, dx), order=1, mode="constant", cval=np.nan)
            )

    if not aligned:
        raise SirilError(
            "WCS registration needs plate-solved frames (a celestial WCS in "
            f"the FITS header); none found in {lights_dir}. Run `mira solve` "
            "first, or use --register stars."
        )

    # Sigma-clipped mean coadd, row-banded to bound memory. masked_invalid
    # drops the NaN shift-borders so edges aren't biased toward zero.
    result = np.empty((H, W), np.float32)
    band = 256
    for r0 in range(0, H, band):
        r1 = min(H, r0 + band)
        block = np.ma.masked_invalid(
            np.stack([a[r0:r1, :] for a in aligned], axis=0)
        )
        clipped = sigma_clip(
            block, sigma_lower=sigma_low, sigma_upper=sigma_high,
            axis=0, masked=True,
        )
        result[r0:r1, :] = np.ma.filled(clipped.mean(axis=0), np.nan)
    if np.isnan(result).any():               # fully-masked border (non-overlap)
        # Fill with a dark-sky value (p1), NOT the median: an emission-filled
        # frame's median is bright, so a median border ring both reads wrong
        # and defeats any black-point-from-percentile autostretch downstream.
        result = np.nan_to_num(result, nan=float(np.nanpercentile(result, 1)))

    # Carry the reference frame's real header (WCS + FILTER/GAIN/DATE-OBS/...)
    # onto the result so it stays photometry-ready, like the Siril path. Re-read
    # it as a fits.Header — read_fits_with_wcs returns a plain dict, not one.
    hdr_out = fits.getheader(ref_path)
    fits.writeto(produced, result, hdr_out, overwrite=True)

    preview_written = None
    if preview is not None:
        _write_stretched_preview(result, preview)
        preview_written = preview if preview.exists() else None

    note = f"WCS-registered {len(aligned)} frame(s) (translation + sigma-clip mean)"
    if skipped:
        note += f"; skipped {len(skipped)} without a WCS"
    return SirilResult(
        output_path=produced,
        preview_path=preview_written,
        n_input_frames=len(aligned),
        log_tail=note,
    )


def _write_stretched_preview(arr: np.ndarray, path: Path) -> None:
    """Midtone-transfer (STF-style) autostretch -> 8-bit PNG preview (parity
    with the Siril path's *_preview.png). Maps the image median to a dark
    background (~0.25) so it doesn't wash out on emission-FILLED frames where
    a naive percentile+asinh would (the median is bright). Best-effort: a
    failure here never aborts a stack."""
    try:
        import cv2
        a = np.asarray(arr, dtype=np.float64)
        med = float(np.median(a))
        sigma = 1.4826 * float(np.median(np.abs(a - med))) or float(a.std()) or 1.0
        lo = med - 2.8 * sigma                 # shadow clip
        hi = float(np.percentile(a, 99.9))
        x = np.clip((a - lo) / (hi - lo + 1e-9), 0.0, 1.0)
        m0 = min(max((med - lo) / (hi - lo + 1e-9), 1e-4), 0.9)
        target = 0.25                          # background brightness target
        # midtones balance b solving MTF(m0, b) = target (closed form)
        b = m0 * (target - 1.0) / (2.0 * target * m0 - target - m0)
        b = min(max(b, 1e-3), 1.0 - 1e-3)
        x = ((b - 1.0) * x) / ((2.0 * b - 1.0) * x - b)
        cv2.imwrite(str(path), (np.clip(x, 0.0, 1.0) * 255).astype(np.uint8))
    except Exception:
        pass


def _detected_stars_xy(image: np.ndarray) -> np.ndarray | None:
    """(N, 2) array of (x, y) for every detected star, brightest first, or
    None if none found. DAOStarFinder mirrors what the existing
    m3/rehearsal code already relies on, so no new dependency."""
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
    return np.column_stack(
        [np.asarray(tbl[xcol], dtype=float), np.asarray(tbl[ycol], dtype=float)]
    )


def _brightest_star_xy(image: np.ndarray) -> tuple[float, float] | None:
    """(x, y) of the brightest detected star, or None if none found."""
    stars = _detected_stars_xy(image)
    if stars is None:
        return None
    return float(stars[0, 0]), float(stars[0, 1])


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

    stars1 = _detected_stars_xy(img1)
    if stars1 is None:
        raise SirilError(
            f"WCS safety gate: no stars detectable in calibrated {calibrated.name}. "
            "Refusing to proceed."
        )
    # Compare the predicted position of the brightest original star to the
    # NEAREST detected star in the calibrated frame — not the brightest:
    # calibration can legitimately reorder brightness between near-equal
    # stars, which would make a brightest-vs-brightest comparison a false
    # "flipped" abort. For a well-behaved calibrate a real star still sits
    # at the prediction; a flip leaves the prediction in empty sky (the
    # nearest detection lands ~image-height away).
    nearest = stars1[int(np.argmin(np.hypot(stars1[:, 0] - px, stars1[:, 1] - py)))]
    dist = float(np.hypot(px - nearest[0], py - nearest[1]))
    if dist > _WCS_TOLERANCE_PX:
        raise SirilError(
            "WCS safety gate FAILED: the brightest original star's "
            f"WCS-predicted pixel ({px:.1f}, {py:.1f}) is {dist:.1f}px from "
            f"the nearest detected star ({nearest[0]:.1f}, {nearest[1]:.1f}) "
            f"in {calibrated.name}. "
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
    # Siril's `convert` ingests EVERY readable image in the directory, while
    # the original↔calibrated pairing below assumes FITS-only (sorted index
    # N ↔ pp_light_NNNNN). One stray JPG would silently shift the indices
    # and the WCS gate would compare the wrong frames — refuse instead.
    non_fits = [p for p in lights if p.suffix.lower() not in (".fit", ".fits", ".fts")]
    if non_fits:
        names = ", ".join(p.name for p in non_fits[:8])
        more = f" (+{len(non_fits) - 8} more)" if len(non_fits) > 8 else ""
        raise SirilError(
            f"--siril-calibrate: {lights_dir} contains non-FITS image files "
            f"Siril would also convert ({names}{more}), which would shift the "
            "original<->calibrated frame pairing. Move them out of the "
            "lights directory and retry."
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
