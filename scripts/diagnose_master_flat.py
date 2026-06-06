"""Is the master flat a clean (reusable) optical flat, or contaminated by
uneven illumination of the taped-paper source?

S30 Pro is a SEALED system -> the true optical flat (vignette + dust) is
session-to-session reusable. A genuine optical flat is ~radially symmetric
about the optical axis (corners symmetrically dimmer). An uneven-light
source instead imprints a LINEAR TILT (one side brighter). Decompose the
master flat into:
  radial term  = how much of the variance is explained by distance-from-center
  linear tilt  = best-fit plane slope (corner asymmetry)
If tilt >> radial asymmetry, the flat is illumination-contaminated (my
capture method), NOT proof that flats don't transfer between sessions.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

P = Path(r"C:\mira\output\m51_ab\master_flat.tif")


def _load(path: Path) -> np.ndarray:
    try:
        import tifffile
        a = tifffile.imread(str(path)).astype(np.float64)
    except Exception:
        import imageio.v3 as iio
        a = iio.imread(str(path)).astype(np.float64)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    return a


img = _load(P)
# The standalone master flat is NOT debayered -> the Bayer CFA mosaic is a
# huge pixel-to-pixel pattern that swamps the smooth shape. Median-bin into
# coarse superpixels so the CFA (and noise) average out and only the smooth
# illumination/vignette field remains. (Inside `mira stack --flats` Siril
# applies -equalize_cfa, so this only affects THIS standalone inspection.)
B = 48
hh, ww = img.shape
img = img[: hh // B * B, : ww // B * B]
img = np.nanmedian(
    img.reshape(img.shape[0] // B, B, img.shape[1] // B, B), axis=(1, 3)
)
img /= np.nanmedian(img)  # normalize to ~1
h, w = img.shape
yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
r = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)

flat = img.ravel()
ok = np.isfinite(flat)
fX, fY, fR, fV = xx.ravel()[ok], yy.ravel()[ok], r.ravel()[ok], flat[ok]
total_var = float(np.var(fV))

# 1) pure linear plane fit (illumination tilt signature)
A = np.c_[fX, fY, np.ones_like(fX)]
cf, *_ = np.linalg.lstsq(A, fV, rcond=None)
plane = A @ cf
tilt_frac = 1.0 - np.var(fV - plane) / total_var          # var explained by a TILT
# corner asymmetry from the plane: left-right & top-bottom % swing
lr = abs(cf[0] * w) / np.mean(fV) * 100.0
tb = abs(cf[1] * h) / np.mean(fV) * 100.0

# 2) radial-only model (true optical vignette signature): fit V ~ poly(r)
pr = np.polyfit(fR, fV, 2)
rad = np.polyval(pr, fR)
rad_frac = 1.0 - np.var(fV - rad) / total_var             # var explained by RADIUS
edge_drop = (np.polyval(pr, 0.0) - np.polyval(pr, 1.0)) / np.polyval(pr, 0.0) * 100.0

# 3) quadrant means (a clean vignette => 4 corners ~equal; tilt => opposed)
def qm(sx, sy):
    m = (np.sign(xx - cx) == sx) & (np.sign(yy - cy) == sy) & np.isfinite(img)
    return float(np.mean(img[m]))
ul, ur, ll, lr_ = qm(-1, -1), qm(1, -1), qm(-1, 1), qm(1, 1)

print(f"variance explained by LINEAR TILT  : {tilt_frac*100:5.1f}%")
print(f"variance explained by RADIUS (vig) : {rad_frac*100:5.1f}%")
print(f"plane tilt  left->right            : {lr:5.1f}%")
print(f"plane tilt  top->bottom            : {tb:5.1f}%")
print(f"radial edge drop center->corner    : {edge_drop:5.1f}%")
print(f"corner means  UL={ul:.3f} UR={ur:.3f} LL={ll:.3f} LR={lr_:.3f}")
print(f"  corner spread (max-min)/mean     : "
      f"{(max(ul,ur,ll,lr_)-min(ul,ur,ll,lr_))/np.mean([ul,ur,ll,lr_])*100:5.1f}%")
print()
if tilt_frac > rad_frac and max(lr, tb) > 8:
    print("DIAGNOSIS: dominated by a LINEAR TILT, not radial vignette ->")
    print("  the taped-paper source was unevenly lit. This is a CAPTURE-METHOD")
    print("  flaw, NOT proof flats don't transfer. A uniformly-lit flat (proper")
    print("  panel / sky / dim-screen at distance) on this SEALED S30 Pro WOULD")
    print("  be reusable session-to-session, as expected.")
elif rad_frac > 0.5 and max(lr, tb) < 5:
    print("DIAGNOSIS: clean ~radial vignette, low tilt -> this flat is a valid")
    print("  reusable optical flat. The M51 +grad must come from elsewhere.")
else:
    print("DIAGNOSIS: mixed; tilt and radial both present (see numbers above).")
