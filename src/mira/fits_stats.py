"""Per-frame quality from FITS pixels — the offline / no-NINA path.

Returns the metrics `mira cull --from-fits` uses to weed out clouds,
trailing, defocus, and frames where the solve quietly failed:

  whole-frame   : stars, hfr, roundness
  target region : sky_median, sky_sigma
  meta          : has_wcs

Target region selection:
  * WCS in header + target (RA, Dec) given  -> aperture at world->pixel
  * else                                    -> central N% box

Stays pure-Python (astropy + photutils) so cull can run on any FITS dir
anywhere (no NINA, no Siril required). HFR is measured via aperture-
growth on the brightest stars (find where cumulative flux is half the
plateau) — relative to the session median, the absolute value isn't
critical for cull, but absolute is also reasonable for sanity-checking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS, FITSFixedWarning
from photutils.detection import DAOStarFinder

# Suppress the chatty FITSFixedWarning that NINA / Seestar headers
# trigger on every open (non-standard keywords). It's not actionable for
# a quality pass — we still get the WCS if one is present.
import warnings  # noqa: E402

warnings.filterwarnings("ignore", category=FITSFixedWarning)

# 2x2 CFA-bin to mono. Module-level constant because both star detection
# (on the binned image) AND WCS->pixel lookup (header is calibrated for
# the UNBINNED grid, so we scale the result down) depend on it.
BIN_FACTOR = 2


@dataclass
class FrameQuality:
    path: Path
    stars: int | None = None
    hfr: float | None = None
    roundness: float | None = None
    sky_median: float | None = None
    sky_sigma: float | None = None
    has_wcs: bool = False
    note: str = ""


def _to_mono(data: np.ndarray) -> np.ndarray:
    """Reduce to a 2-D float array. NINA OSC raws are 2-D CFA (RGGB);
    a 3-channel FITS becomes a luminance mean. 2x2-binning a CFA mosaic
    averages the Bayer pattern into a clean mono image — perfect for
    a sensor-frame quality measurement (we are not photometering)."""
    a = np.asarray(data).astype(np.float32)
    if a.ndim == 3:
        # (3, H, W) or (H, W, 3)
        if a.shape[0] <= 4:
            a = a.mean(axis=0)
        else:
            a = a[..., :3].mean(axis=2)
    if a.ndim != 2:
        raise ValueError(f"unsupported FITS shape {a.shape}")
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w]
    return (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2]) / 4.0


def _target_xy(
    img_shape: tuple[int, int], wcs: WCS | None,
    target_ra: float | None, target_dec: float | None,
    central_frac: float,
) -> tuple[slice, slice, str]:
    """Return (row_slice, col_slice, reason) for the target-sky box.
    Uses WCS->pixel when WCS + target coords are both available;
    otherwise the central `central_frac` of the frame."""
    h, w = img_shape
    if wcs is not None and target_ra is not None and target_dec is not None:
        try:
            x, y = wcs.world_to_pixel_values(target_ra, target_dec)
            # The header's WCS is for the un-binned pixel grid; we
            # operate on the 2x2-binned mono image, so divide by the
            # bin factor to map into binned coords. (Forgetting this
            # silently put the slice off-frame and fell back to center.)
            cx = int(round(float(x) / BIN_FACTOR))
            cy = int(round(float(y) / BIN_FACTOR))
            half = int(round(min(h, w) * central_frac / 2))
            r0, r1 = max(0, cy - half), min(h, cy + half)
            c0, c1 = max(0, cx - half), min(w, cx + half)
            if r1 - r0 > 16 and c1 - c0 > 16:
                return slice(r0, r1), slice(c0, c1), "wcs"
        except Exception:
            pass
    half_r = int(h * central_frac / 2)
    half_c = int(w * central_frac / 2)
    cr, cc = h // 2, w // 2
    return (slice(cr - half_r, cr + half_r),
            slice(cc - half_c, cc + half_c),
            "central-box")


def _hfr_from_aperture_growth(
    img: np.ndarray, sources, max_stars: int = 30, max_r: int = 12,
) -> float | None:
    """Median HFR (radius enclosing half the plateau flux) over the top-N
    brightest sources. Aperture-growth is robust and needs no fit.
    Returns None if no usable sources fit."""
    if sources is None or len(sources) == 0:
        return None
    flux = np.asarray(sources["flux"])
    order = np.argsort(flux)[::-1][:max_stars]
    # photutils 3.0 renamed xcentroid/ycentroid -> x_centroid/y_centroid
    # (old names slated for removal in 4.0). Accept either.
    cols = sources.colnames
    xcol = "x_centroid" if "x_centroid" in cols else "xcentroid"
    ycol = "y_centroid" if "y_centroid" in cols else "ycentroid"
    xs = np.asarray(sources[xcol])[order]
    ys = np.asarray(sources[ycol])[order]
    h, w = img.shape
    yy, xx = np.indices((2 * max_r + 1, 2 * max_r + 1))
    rr = np.sqrt((xx - max_r) ** 2 + (yy - max_r) ** 2)
    radii = np.arange(0.5, max_r + 0.5)
    hfrs: list[float] = []
    for x, y in zip(xs, ys):
        xi, yi = int(round(x)), int(round(y))
        if xi - max_r < 0 or yi - max_r < 0 or xi + max_r >= w or yi + max_r >= h:
            continue
        box = img[yi - max_r:yi + max_r + 1, xi - max_r:xi + max_r + 1]
        cum = np.array([box[rr <= r].sum() for r in radii])
        plateau = cum[-1]
        if plateau <= 0:
            continue
        half = 0.5 * plateau
        # first radius where cumulative flux crosses half; linear interp
        ix = np.searchsorted(cum, half)
        if ix == 0:
            hfrs.append(float(radii[0]))
        elif ix >= len(cum):
            hfrs.append(float(radii[-1]))
        else:
            r0, r1 = radii[ix - 1], radii[ix]
            c0, c1 = cum[ix - 1], cum[ix]
            frac = (half - c0) / (c1 - c0) if c1 > c0 else 0.0
            hfrs.append(float(r0 + frac * (r1 - r0)))
    return float(np.median(hfrs)) if hfrs else None


def compute_frame_quality(
    path: Path,
    *,
    target_ra: float | None = None,
    target_dec: float | None = None,
    central_frac: float = 0.3,
    detect_fwhm: float = 4.0,
    detect_sigma: float = 5.0,
) -> FrameQuality:
    """Full per-frame quality dump. Never raises on a bad FITS — returns
    a partially-filled FrameQuality with `note` explaining what failed,
    so cull can carry on across a noisy directory."""
    p = Path(path)
    try:
        with fits.open(p, memmap=False) as hdul:
            hdu, header = None, None
            for h in hdul:
                if h.data is not None:
                    hdu, header = h, h.header
                    break
            if hdu is None or header is None:
                return FrameQuality(p, note="no data HDU")
            data = hdu.data
            try:
                wcs = WCS(header)
                has_wcs = bool(wcs.has_celestial) and wcs.pixel_n_dim >= 2
            except Exception:
                wcs, has_wcs = None, False
    except Exception as exc:
        return FrameQuality(p, note=f"FITS open failed: {exc}")

    try:
        img = _to_mono(data)
    except Exception as exc:
        return FrameQuality(p, has_wcs=has_wcs, note=f"shape error: {exc}")

    mean_g, med_g, sig_g = sigma_clipped_stats(img, sigma=3.0)
    finder = DAOStarFinder(fwhm=detect_fwhm, threshold=detect_sigma * sig_g)
    sources = finder(img - med_g)
    n_stars = 0 if sources is None else len(sources)
    if sources is None or n_stars == 0:
        # No stars detectable -> almost always a cloud / dome / cap.
        return FrameQuality(
            p, stars=0, hfr=None, roundness=None,
            sky_median=float(med_g), sky_sigma=float(sig_g),
            has_wcs=has_wcs, note="no stars detected",
        )

    round1 = np.asarray(sources["roundness1"])
    round_med = float(np.median(np.abs(round1)))
    hfr = _hfr_from_aperture_growth(img - med_g, sources)

    rs, cs, _reg = _target_xy(img.shape, wcs, target_ra, target_dec, central_frac)
    sub = img[rs, cs]
    if sub.size > 64:
        _m, sky_med, sky_sig = sigma_clipped_stats(sub, sigma=3.0)
    else:
        sky_med, sky_sig = float(med_g), float(sig_g)

    return FrameQuality(
        p, stars=int(n_stars), hfr=hfr, roundness=round_med,
        sky_median=float(sky_med), sky_sigma=float(sky_sig),
        has_wcs=has_wcs,
    )
