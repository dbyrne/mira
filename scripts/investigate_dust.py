"""Are the spots the IR flat removes real sensor/optics dust, or
artifacts (stars baked into the flat / injected features)?

Decisive triangulation, ALL in sensor frame (no registration, so fixed-
position dust is comparable):

  A. IR master flat   vs  LP master flat   -- two INDEPENDENT taped-paper
     captures. Paper flats contain no sky/stars; the only thing that
     repeats at identical (x,y) across two independent flat series is
     real dust/sensor structure. High correlation => dust, not stars.
  B. IR master flat   vs  unregistered median of raw M51 subs -- if the
     flat's spots coincide with dark donuts in M51's OWN raw data, the
     flat removes real shadows rather than injecting them.

Everything is reduced to a mono sensor frame by 2x2 CFA binning (the
flats and the Seestar raws are RGGB CFA), then a small-scale residual
r = img / gaussian(img, big sigma) isolates dust (~tens of px) from the
vignette (large scale). Output: correlations + a hard-stretch montage so
donut-vs-point morphology is visible.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image
from scipy.ndimage import gaussian_filter

IR = Path(r"C:\mira\data\flats\IR_g120_20260519\master_flat.fit")
LP = Path(r"C:\mira\data\flats\LP_g120_20260519\master_flat.fit")
M51_DIR = Path(r"C:\mira\captures\m51_20260517")
OUT = Path(r"C:\mira\output\m51_ir_ab")
N_RAW = 25


def _mono(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.float64)
    if a.ndim == 3:                       # (3,H,W) or (H,W,3)
        a = a.mean(axis=0 if a.shape[0] <= 4 else 2)
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w]
    return (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2]) / 4.0


def load_fits_mono(p: Path) -> np.ndarray:
    with fits.open(p) as h:
        for hdu in h:
            if hdu.data is not None:
                return _mono(np.asarray(hdu.data))
    raise SystemExit(f"no data in {p}")


def residual(img: np.ndarray, sigma: float = 40.0) -> np.ndarray:
    base = gaussian_filter(img, sigma)
    base[base == 0] = np.nan
    r = img / base
    return np.clip(r, 0.85, 1.15)


def crop_to(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    return a[: shape[0], : shape[1]]


def stretch_png(r: np.ndarray, path: Path) -> None:
    lo, hi = np.nanpercentile(r, 1), np.nanpercentile(r, 99)
    x = np.clip((r - lo) / (hi - lo + 1e-9), 0, 1)
    Image.fromarray((x * 255).astype(np.uint8)).save(path)


print("loading IR / LP masters...")
ir = residual(load_fits_mono(IR))
lp = residual(load_fits_mono(LP))

raws = sorted(glob.glob(str(M51_DIR / "**" / "*.fit*"), recursive=True))
step = max(1, len(raws) // N_RAW)
sel = raws[::step][:N_RAW]
print(f"median-stacking {len(sel)} raw M51 subs (NO registration)...")
stack = np.median([load_fits_mono(Path(p)) for p in sel], axis=0)
m51 = residual(stack)

# common shape
H = min(ir.shape[0], lp.shape[0], m51.shape[0])
W = min(ir.shape[1], lp.shape[1], m51.shape[1])
ir, lp, m51 = crop_to(ir, (H, W)), crop_to(lp, (H, W)), crop_to(m51, (H, W))

def corr(a, b):
    a, b = a.ravel(), b.ravel()
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1])

# Deviation from flat (|r-1|); dust = where IR deviates. Correlate the
# deviation maps: shared dust => positive correlation at the SAME pixels.
dir_, dlp, dm51 = np.abs(ir - 1), np.abs(lp - 1), np.abs(m51 - 1)
c_ir_lp = corr(dir_, dlp)
c_ir_m51 = corr(dir_, dm51)
# Control: correlate IR deviation against a 180-rotated LP (destroys
# real spatial coincidence). Should collapse to ~0 if c_ir_lp is real.
c_ir_lp_rot = corr(dir_, np.rot90(dlp, 2))

# Depth at the deepest IR spots vs the rest (how dark the motes are).
thr = np.nanpercentile(dir_, 99.5)
spot = dir_ >= thr
print()
print(f"IR vs LP   spot-map correlation : {c_ir_lp:+.3f}")
print(f"IR vs LP   (LP rotated 180, ctrl): {c_ir_lp_rot:+.3f}")
print(f"IR vs M51  spot-map correlation : {c_ir_m51:+.3f}")
print(f"at IR mote pixels: LP mean|dev|={np.nanmean(dlp[spot]):.4f} "
      f"(field {np.nanmean(dlp):.4f}); "
      f"M51 mean|dev|={np.nanmean(dm51[spot]):.4f} "
      f"(field {np.nanmean(dm51):.4f})")
print(f"IR mote depth: median {np.nanmedian(ir[spot]):.3f}, "
      f"min {np.nanmin(ir):.3f} (1.0 = no mote; <1 = dark shadow)")

OUT.mkdir(parents=True, exist_ok=True)
for name, r in (("dust_ir", ir), ("dust_lp", lp), ("dust_m51raw", m51)):
    stretch_png(r, OUT / f"{name}.png")
# side-by-side montage for morphology eyeballing
trio = np.concatenate([
    np.clip((np.abs(x - 1) / np.nanpercentile(np.abs(x - 1), 99.7)), 0, 1)
    for x in (ir, lp, m51)], axis=1)
Image.fromarray((trio * 255).astype(np.uint8)).save(OUT / "dust_montage.png")
print(f"\nwrote {OUT}\\dust_montage.png (IR | LP | raw-M51, hard-stretched)")
print("VERDICT key: c(IR,LP) high & c(IR,LP-rot) ~0  => fixed sensor dust "
      "(not stars: paper flats have none, two independent captures can't "
      "share a star field). c(IR,M51) > 0 => flat targets dust that is "
      "really in M51 (removing, not injecting).")
