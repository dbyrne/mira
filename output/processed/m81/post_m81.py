#!/usr/bin/env python
"""Post-pass for the M81-group keeper (2026-06-09 shootout winner render).

Input: the full-frame 16-bit TIFF from curve_lab starnet-decouple
(a=0.025, b=0.014, toe=0.003, sg=1.0 — conservative dig, no star dimming).
The render's tonality is shootout-verified; this pass only fixes what the
adversarial verifier flagged and what tone curves cannot: the data-borne
yellow-green cast and chroma speckle. Ops (all chroma-side, luminance
essentially untouched so the verified faint-structure win survives):

  1. SCNR green suppression (stars + disk green excess)
  2. background hue neutralization by per-channel offset (no level change)
  3. gated chroma denoise (faint-zone color mottle; lum gate, blur+attenuate)

Prints structure-preservation proof: same-mask luminance detail before vs
after must be ~unchanged; bg chroma noise should drop.
"""
import argparse
import numpy as np
import tifffile
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

M81_XY, M82_XY, SKY_XY = (1304, 1840), (1261, 1237), (475, 691)


def box(im, xy, r):
    x, y = xy
    return im[max(0, y - r):y + r, max(0, x - r):x + r]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0, 1)
    return t * t * (3 - 2 * t)


def report(rgb, label):
    lum = rgb.mean(-1)
    sky = box(rgb, SKY_XY, 100)
    chroma_noise = float(np.mean([np.std(sky[..., 0] - sky[..., 1]),
                                  np.std(sky[..., 2] - sky[..., 1])]))
    sig = box(lum, M81_XY, 160) > 0.06
    detail = float(np.mean(np.hypot(*np.gradient(box(lum, M81_XY, 160)))[sig]))
    zeros = float((lum <= 1 / 255).mean())
    bgc = [float(np.median(sky[..., c])) for c in range(3)]
    print(f"  [{label}] bg_rgb=({bgc[0]:.4f},{bgc[1]:.4f},{bgc[2]:.4f}) "
          f"bg_chroma_noise={chroma_noise:.4f} m81_detail({int(sig.sum())}px)={detail:.5f} "
          f"frame_zeros={zeros*100:.1f}%")
    return detail


def main(a):
    rgb = tifffile.imread(a.inp).astype(np.float64) / 65535.0
    d0 = report(rgb, "pre ")

    # 1. SCNR (luminance-preserving: cast removed as COLOR, kept as light,
    #    so the shootout-verified faint-structure gradients survive intact)
    if a.scnr > 0:
        L0 = rgb.mean(-1, keepdims=True)
        neutral = 0.5 * (rgb[..., 0] + rgb[..., 2])
        g = rgb[..., 1]
        rgb[..., 1] = g * (1 - a.scnr) + np.minimum(g, neutral) * a.scnr
        rgb = np.clip(rgb + (L0 - rgb.mean(-1, keepdims=True)), 0, 1)

    # 2. background hue neutralization (offset; target = channel mean, so no level change)
    lum = rgb.mean(-1)
    bgmask = lum < np.percentile(lum, 55.0)
    bg_c = [float(np.median(rgb[..., c][bgmask])) for c in range(3)]
    tgt = float(np.mean(bg_c))
    for c in range(3):
        rgb[..., c] = np.clip(rgb[..., c] - (bg_c[c] - tgt), 0, 1)

    # 3. gated chroma denoise
    if a.chroma_sigma > 0:
        lum = rgb.mean(-1, keepdims=True)
        chroma = rgb - lum
        m = smoothstep(a.gate_hi, a.gate_lo, lum[..., 0])[..., None]
        rgb = np.clip(lum + (1 - m) * chroma + m * gauss(chroma, a.chroma_sigma) * a.chroma_keep, 0, 1)

    if a.sat != 1.0:
        lum = rgb.mean(-1, keepdims=True)
        rgb = np.clip(lum + (rgb - lum) * a.sat, 0, 1)

    # display pedestal: lift the toe-crushed floor to a natural sky level
    # (pure levels move — separation preserved, nothing new clips)
    if a.pedestal > 0:
        rgb = np.clip(a.pedestal + rgb * (1 - a.pedestal), 0, 1)

    d1 = report(rgb, "post")
    print(f"  detail preservation: {d1 / d0 * 100:.1f}% (luminance ops would show here; chroma ops ~100%)")

    Image.fromarray((rgb * 255 + 0.5).astype(np.uint8), "RGB").save(a.out)
    tifffile.imwrite(a.out.rsplit(".", 1)[0] + ".tiff", (rgb * 65535 + 0.5).astype(np.uint16))
    print(f"WROTE {a.out} (+.tiff)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--scnr", type=float, default=0.7)
    p.add_argument("--gate-lo", type=float, default=0.05, help="full chroma-denoise below")
    p.add_argument("--gate-hi", type=float, default=0.15, help="untouched above")
    p.add_argument("--chroma-sigma", type=float, default=5.0)
    p.add_argument("--chroma-keep", type=float, default=0.3)
    p.add_argument("--sat", type=float, default=1.0)
    p.add_argument("--pedestal", type=float, default=0.0)
    main(p.parse_args())
