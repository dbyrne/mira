#!/usr/bin/env python
"""Manual stretch / curve engine for the M51 finishing experiments.

Operates on a (background-flat) linear FITS — apply GraXpert bg-extraction
FIRST so the per-channel black point is meaningful. Full manual control:
per-channel black point, white point, stretch function (asinh/log/power/
mtf), color balance, S-curve contrast, gamma, saturation, optional crop.
Writes a PNG to eyeball + re-tune. Also prints quality stats (bg noise,
M51 SNR, faint-bridge SNR, corner flatness) for the statistical judging.
"""
import argparse, numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from PIL import Image

# M51 core + NGC 5195 companion (J2000) — for locating regions via WCS.
M51_RA, M51_DEC = 202.4696, 47.1952
N5195_RA, N5195_DEC = 202.4983, 47.2656


def load_rgb(path):
    hd = fits.open(path)[0]
    d = np.asarray(hd.data, dtype=np.float64)
    if d.ndim == 2:
        rgb = np.stack([d] * 3, -1)
    elif d.shape[0] == 3:
        rgb = np.moveaxis(d, 0, -1)
    elif d.shape[-1] == 3:
        rgb = d
    else:
        rgb = np.stack([d.mean(0)] * 3, -1)
    return rgb, hd.header


def px(header, shape, ra, dec):
    try:
        w = WCS(header).celestial
        x, y = w.world_to_pixel_values(ra, dec)
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        return shape[1] // 2, shape[0] // 2


def mtf(x, m):
    """PixInsight midtone transfer function — classic astro stretch."""
    return ((m - 1.0) * x) / ((2.0 * m - 1.0) * x - m)


def main(a):
    rgb, hdr = load_rgb(a.inp)
    H, W, _ = rgb.shape
    # per-channel black point (subtract percentile, the sky)
    for c in range(3):
        bp = np.percentile(rgb[..., c], a.black)
        rgb[..., c] = np.clip(rgb[..., c] - bp, 0, None)
    # white point normalize
    wp = np.percentile(rgb, a.white)
    rgb = np.clip(rgb / (wp + 1e-12), 0, 1)
    # color balance
    if a.rgb:
        for c, g in enumerate(float(x) for x in a.rgb.split(",")):
            rgb[..., c] *= g
        rgb = np.clip(rgb, 0, 1)
    # stretch
    if a.mode == "asinh":
        rgb = np.arcsinh(rgb / a.param) / np.arcsinh(1.0 / a.param)
    elif a.mode == "log":
        rgb = np.log1p(rgb * a.param) / np.log1p(a.param)
    elif a.mode == "power":
        rgb = rgb ** a.param
    elif a.mode == "mtf":
        rgb = mtf(rgb, a.param)
    rgb = np.clip(rgb, 0, 1)
    # S-curve contrast around 0.5 (strength a.scurve)
    if a.scurve:
        rgb = np.clip(rgb + a.scurve * np.sin(2 * np.pi * (rgb - 0.5)) * -0.5
                      if False else
                      0.5 + (1 + a.scurve) * (rgb - 0.5) - a.scurve * (2 * (rgb - 0.5)) ** 3 / 2, 0, 1)
    # gamma
    if a.gamma != 1.0:
        rgb = np.clip(rgb, 0, 1) ** (1.0 / a.gamma)
    # saturation (chroma scaling about luminance)
    if a.sat != 1.0:
        lum = rgb.mean(-1, keepdims=True)
        rgb = np.clip(lum + (rgb - lum) * a.sat, 0, 1)
    # asymmetric trim (T,B,L,R fractions per edge) — wide-field edge cleanup
    if a.trim:
        t, b, l, r = (float(x) for x in a.trim.split(","))
        rgb = rgb[int(H * t):H - int(H * b), int(W * l):W - int(W * r)]
        H, W, _ = rgb.shape
    # crop fraction per side
    if a.crop > 0:
        cx, cy = int(W * a.crop), int(H * a.crop)
        rgb = rgb[cy:H - cy, cx:W - cx]
        H, W, _ = rgb.shape
    out = (rgb * 255 + 0.5).astype(np.uint8)
    Image.fromarray(out, "RGB").save(a.out)
    if a.tiff:
        import tifffile
        tifffile.imwrite(a.out.rsplit(".", 1)[0] + ".tiff",
                         (np.clip(rgb, 0, 1) * 65535 + 0.5).astype(np.uint16))

    # --- stats (on the pre-stretch luminance for honest SNR) ---
    lum0, _ = load_rgb(a.inp)
    lum0 = lum0.mean(-1)
    mx, my = px(hdr, lum0.shape, M51_RA, M51_DEC)
    nx, ny = px(hdr, lum0.shape, N5195_RA, N5195_DEC)
    def boxv(im, x, y, r):
        return im[max(0, y - r):y + r, max(0, x - r):x + r]
    bg = lum0[int(H * 0.04):int(H * 0.14), int(W * 0.04):int(W * 0.14)] if a.crop == 0 else None
    Hl, Wl = lum0.shape
    bgc = lum0[int(Hl*0.04):int(Hl*0.14), int(Wl*0.04):int(Wl*0.14)]
    _, bmed, bstd = sigma_clipped_stats(bgc)
    m51pk = float(np.percentile(boxv(lum0, mx, my, 50), 99.5))
    # bridge: midpoint between M51 and companion
    brx, bry = (mx + nx) // 2, (my + ny) // 2
    br = float(np.median(boxv(lum0, brx, bry, 12)))
    # corner flatness (linear): 4 corners / center
    corn = [float(np.median(lum0[0:120, 0:120])), float(np.median(lum0[0:120, -120:])),
            float(np.median(lum0[-120:, 0:120])), float(np.median(lum0[-120:, -120:]))]
    cen = float(np.median(boxv(lum0, Wl // 2, Hl // 2, 200)))
    print(f"WROTE {a.out} ({W}x{H})")
    print(f"  STATS  bg_noise={bstd:.4g}  M51_SNR={(m51pk-bmed)/bstd:.1f}  "
          f"bridge_SNR={(br-bmed)/bstd:.2f}  corner/center={[round(c/cen,2) for c in corn]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--black", type=float, default=35.0, help="black-point percentile")
    p.add_argument("--white", type=float, default=99.92, help="white-point percentile")
    p.add_argument("--mode", default="asinh", choices=["asinh", "log", "power", "mtf"])
    p.add_argument("--param", type=float, default=0.04, help="stretch intensity (asinh a / log scale / power exp / mtf midtone)")
    p.add_argument("--scurve", type=float, default=0.0, help="S-curve contrast strength (0-0.5)")
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--sat", type=float, default=1.0)
    p.add_argument("--rgb", default=None, help="per-channel gains 'R,G,B' e.g. 1.0,0.95,1.1")
    p.add_argument("--crop", type=float, default=0.0, help="fraction cropped per side")
    p.add_argument("--trim", default=None, help="asymmetric trim 'T,B,L,R' fractions per edge (wide-field)")
    p.add_argument("--tiff", action="store_true", help="also write a 16-bit lossless TIFF next to the PNG (use for keepers/finals)")
    main(p.parse_args())
