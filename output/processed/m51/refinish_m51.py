#!/usr/bin/env python
"""Refinish of the M51 all-lum bakeoff stack — v2 of M51_alllum_finish.

Diagnosis of the existing finish: stretched into the noise floor with no
chroma control — the background is a bright red/green mottle with residual
gradient, which reads as over-processed even though the galaxy itself is
fine. Fix per the curve-shootout finding: keep the asinh global stretch,
add a *gated local chroma op* (chroma-denoise restricted to faint
background), neutralize the background color, and use a soft black point
that doesn't crush the noise floor.

Input should be the GraXpert background-extracted linear (all_lum_bg.fits).
Prints honest metrics: linear-domain SNR (pre-stretch), output background
level + chroma noise, galaxy-region chroma std (color retention — should
stay HIGH) and gradient energy (detail retention — must not drop), so a
"win" can't come from smearing everything.
"""
import argparse
import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from PIL import Image

try:
    import cv2
    def gauss(im, sigma):
        k = int(sigma * 6) | 1
        return cv2.GaussianBlur(im, (k, k), sigma)
except ImportError:
    from scipy.ndimage import gaussian_filter
    def gauss(im, sigma):
        if im.ndim == 3:
            return np.stack([gaussian_filter(im[..., c], sigma) for c in range(im.shape[-1])], -1)
        return gaussian_filter(im, sigma)

# Region centers in PIXELS of the untrimmed 2160x3840 frame (from WCS probe).
M51_XY = (1105, 1911)
SKY_XY = (540, 844)
STAR_XY = (347, 121)


def load_rgb(path):
    hd = fits.open(path)[0]
    d = np.asarray(hd.data, dtype=np.float64)
    if d.ndim == 3 and d.shape[0] == 3:
        d = np.moveaxis(d, 0, -1)
    return d, hd.header


def box(im, xy, r):
    x, y = xy
    return im[max(0, y - r):y + r, max(0, x - r):x + r]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0, 1)
    return t * t * (3 - 2 * t)


def output_metrics(rgb, label, m51_xy=M51_XY, sky_xy=SKY_XY):
    lum = rgb.mean(-1)
    sky = box(rgb, sky_xy, 80)
    gal = box(rgb, m51_xy, 110)
    bg_lvl = float(np.median(sky))
    bg_lum_std = float(box(lum, sky_xy, 80).std())
    chroma_noise = float(np.mean([np.std(sky[..., 0] - sky[..., 1]),
                                  np.std(sky[..., 2] - sky[..., 1])]))
    gal_lum = box(lum, m51_xy, 110)
    gal_chroma = float(np.mean([np.std(gal[..., 0] - gal[..., 1]),
                                np.std(gal[..., 2] - gal[..., 1])]))
    gy, gx = np.gradient(gal_lum)
    detail = float(np.mean(np.hypot(gx, gy)))
    clip_hi = float((rgb >= 0.999).mean())
    clip_lo = float((rgb <= 0.001).mean())
    print(f"  [{label}] bg={bg_lvl:.4f} bg_lum_std={bg_lum_std:.4f} "
          f"bg_CHROMA_noise={chroma_noise:.4f} gal_chroma_std={gal_chroma:.4f} "
          f"gal_detail={detail:.5f} clip_hi={clip_hi*100:.3f}% clip_lo={clip_lo*100:.3f}%")
    return dict(bg=bg_lvl, bg_lum_std=bg_lum_std, chroma=chroma_noise,
                gal_chroma=gal_chroma, detail=detail)


def main(a):
    rgb, hdr = load_rgb(a.inp)
    H, W, _ = rgb.shape

    # --- linear-domain SNR (honest, pre-stretch) ---
    lum0 = rgb.mean(-1)
    _, bmed, bstd = sigma_clipped_stats(box(lum0, SKY_XY, 80))
    m51pk = float(np.percentile(box(lum0, M51_XY, 60), 99.5))
    print(f"linear: bg_med={bmed:.5f} bg_std={bstd:.6f} M51_SNR={(m51pk - bmed) / bstd:.1f}")

    # --- soft black point: percentile minus nsig*std, so noise floor survives ---
    for c in range(3):
        ch = rgb[..., c]
        bp = np.percentile(ch, a.black) - a.bp_soft * bstd
        rgb[..., c] = np.clip(ch - bp, 0, None)
    wp = np.percentile(rgb, a.white)
    rgb = np.clip(rgb / (wp + 1e-12), 0, 1)

    # --- global asinh stretch ---
    rgb = np.arcsinh(rgb / a.param) / np.arcsinh(1.0 / a.param)
    rgb = np.clip(rgb, 0, 1)

    # --- background neutralization (offset, preserves star/galaxy color) ---
    lum = rgb.mean(-1)
    bgmask = lum < np.percentile(lum, a.bg_pct)
    bg_c = [float(sigma_clipped_stats(rgb[..., c][bgmask])[1]) for c in range(3)]
    tgt = a.bg_target if a.bg_target > 0 else float(np.mean(bg_c))
    for c in range(3):
        rgb[..., c] = np.clip(rgb[..., c] - (bg_c[c] - tgt), 0, 1)

    # --- channel gains + SCNR green suppression (before chroma ops) ---
    if a.rgb:
        for c, g in enumerate(float(x) for x in a.rgb.split(",")):
            rgb[..., c] = np.clip(rgb[..., c] * g, 0, 1)
    if a.scnr > 0:
        neutral = 0.5 * (rgb[..., 0] + rgb[..., 2])
        g_ch = rgb[..., 1]
        rgb[..., 1] = g_ch * (1 - a.scnr) + np.minimum(g_ch, neutral) * a.scnr

    # --- gated chroma denoise (the local op: background only) ---
    if a.chroma_sigma > 0:
        lum = rgb.mean(-1, keepdims=True)
        chroma = rgb - lum
        m = smoothstep(a.gate_hi, a.gate_lo, lum[..., 0])[..., None]  # 1 in faint bg
        chroma_s = gauss(chroma, a.chroma_sigma) * a.chroma_keep
        rgb = np.clip(lum + (1 - m) * chroma + m * chroma_s, 0, 1)

    # --- gentle gated luminance NR in deep background (keep grain, kill blotch) ---
    if a.lum_nr > 0:
        lum = rgb.mean(-1, keepdims=True)
        m = smoothstep(a.gate_hi, a.gate_lo, lum[..., 0])[..., None]
        rgb = np.clip(rgb * (1 - m * a.lum_nr) + gauss(rgb, 3.0) * (m * a.lum_nr), 0, 1)

    # --- gated local contrast (galaxy-side: lifts arm presence, not the bg) ---
    if a.lc_amount > 0:
        L = rgb.mean(-1)
        detail = L - gauss(L, a.lc_radius)
        m = smoothstep(a.lc_gate_lo, a.lc_gate_hi, L)  # 1 on bright structure
        rgb = np.clip(rgb + (m * a.lc_amount * detail)[..., None], 0, 1)

    # --- S-curve, saturation, gamma ---
    if a.scurve:
        rgb = np.clip(0.5 + (1 + a.scurve) * (rgb - 0.5) - a.scurve * (2 * (rgb - 0.5)) ** 3 / 2, 0, 1)
    if a.sat != 1.0:
        lum = rgb.mean(-1, keepdims=True)
        rgb = np.clip(lum + (rgb - lum) * a.sat, 0, 1)
    if a.gamma != 1.0:
        rgb = np.clip(rgb, 0, 1) ** (1.0 / a.gamma)

    print("metrics (full frame coords):")
    mets = output_metrics(rgb, "refinish")

    # --- trim AFTER metrics so regions stay valid ---
    if a.trim:
        t, b, l, r = (float(x) for x in a.trim.split(","))
        rgb = rgb[int(H * t):H - int(H * b), int(W * l):W - int(W * r)]

    out8 = (rgb * 255 + 0.5).astype(np.uint8)
    Image.fromarray(out8, "RGB").save(a.out)
    print(f"WROTE {a.out} ({rgb.shape[1]}x{rgb.shape[0]})")
    if a.tiff:
        import tifffile
        tifffile.imwrite(a.out.rsplit(".", 1)[0] + ".tiff",
                         (np.clip(rgb, 0, 1) * 65535 + 0.5).astype(np.uint16))

    # --- baseline comparison on the shipped finish PNG, same metric defs ---
    if a.compare:
        base = np.asarray(Image.open(a.compare), dtype=np.float64) / 255.0
        bh, bw, _ = base.shape
        sx, sy = bw / W, bh / H
        m51 = (int(M51_XY[0] * sx), int(M51_XY[1] * sy))
        sky = (int(SKY_XY[0] * sx), int(SKY_XY[1] * sy))
        print("baseline (scaled coords, approximate if baseline was trimmed):")
        output_metrics(base, "shipped", m51_xy=m51, sky_xy=sky)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--black", type=float, default=25.0, help="black-point percentile")
    p.add_argument("--bp-soft", type=float, default=2.5, help="keep bp this many bg sigmas below the percentile")
    p.add_argument("--white", type=float, default=99.93)
    p.add_argument("--param", type=float, default=0.035, help="asinh softness (smaller = stronger)")
    p.add_argument("--bg-pct", type=float, default=60.0, help="percentile of lum treated as background for neutralization")
    p.add_argument("--bg-target", type=float, default=0.065, help="neutral background level (0 = mean of channels)")
    p.add_argument("--gate-lo", type=float, default=0.10, help="lum below this = full chroma denoise")
    p.add_argument("--gate-hi", type=float, default=0.22, help="lum above this = untouched")
    p.add_argument("--chroma-sigma", type=float, default=6.0)
    p.add_argument("--chroma-keep", type=float, default=0.25, help="fraction of (blurred) bg chroma kept")
    p.add_argument("--lum-nr", type=float, default=0.0, help="0-1 gated luminance NR blend")
    p.add_argument("--rgb", default=None, help="per-channel gains 'R,G,B' (post-stretch)")
    p.add_argument("--scnr", type=float, default=0.0, help="0-1 SCNR green suppression amount")
    p.add_argument("--lc-amount", type=float, default=0.0, help="gated local-contrast strength")
    p.add_argument("--lc-radius", type=float, default=30.0)
    p.add_argument("--lc-gate-lo", type=float, default=0.12)
    p.add_argument("--lc-gate-hi", type=float, default=0.25)
    p.add_argument("--scurve", type=float, default=0.06)
    p.add_argument("--sat", type=float, default=1.25)
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--trim", default=None, help="T,B,L,R edge-trim fractions")
    p.add_argument("--tiff", action="store_true")
    p.add_argument("--compare", default=None, help="shipped finish PNG for same-metric baseline readout")
    main(p.parse_args())
