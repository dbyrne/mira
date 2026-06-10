#!/usr/bin/env python
"""M13 finishing v2 — warm-color pipeline with a pluggable highlight-protecting
curve (asinh or the faithful GHS port from curvelab). Combines stretch_m13.py's
known-good color handling (per-channel sky black + warm RGB gain + saturation +
crop) with GHS core-hold, so asinh vs GHS can be compared apples-to-apples.

  python stretch2.py --in m13_cc.fit --out x.png --curve ghs \
     --params D=2.0,b=1.5,SP=0.015,HP=0.20 --rgb 1.35,1.02,0.78 --sat 1.6 --crop 0.25
"""
import argparse, sys, numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from PIL import Image

sys.path.insert(0, ".claude/skills/mira-finish/curvelab/curves")
import ghs as ghs_curve  # noqa

M13_RA, M13_DEC = 250.4217, 36.4603


def load_rgb(path):
    hd = fits.open(path)[0]
    d = np.asarray(hd.data, np.float64)
    if d.ndim == 3 and d.shape[0] == 3:
        rgb = np.moveaxis(d, 0, -1)
    elif d.ndim == 3 and d.shape[-1] == 3:
        rgb = d
    else:
        rgb = np.stack([d] * 3, -1)
    return rgb, hd.header


def asinh_lum(lum, a):
    return np.arcsinh(lum / a) / np.arcsinh(1.0 / a)


def main(a):
    rgb, hdr = load_rgb(a.inp)
    # per-channel sky-median black point -> neutral background
    x = rgb.copy()
    for c in range(3):
        _, med, _ = sigma_clipped_stats(rgb[..., c])
        x[..., c] = rgb[..., c] - med
    # warm RGB gains (counter PCC over-blue)
    if a.rgb:
        g = [float(v) for v in a.rgb.split(",")]
        for c in range(3):
            x[..., c] *= g[c]
    x = np.clip(x, 0, None)
    white = float(np.percentile(x, a.white))
    x = np.clip(x / white, 0, 1)

    # apply the curve (color-preserving: stretch luminance, scale channels)
    params = {}
    if a.params:
        for kv in a.params.split(","):
            k, v = kv.split("="); params[k] = float(v)
    if a.curve == "ghs":
        y = ghs_curve.apply(x, **{**{"hd_lo": 1.0}, **params})  # hd_lo=1 keeps star color
    else:  # asinh
        av = params.get("a", 0.10)
        lum = x.mean(-1)
        ls = asinh_lum(lum, av)
        factor = np.where(lum > 1e-8, ls / np.maximum(lum, 1e-8), 0.0)
        y = np.clip(x * factor[..., None], 0, 1)

    # saturation
    if a.sat != 1.0:
        lum = y.mean(-1, keepdims=True)
        y = np.clip(lum + (y - lum) * a.sat, 0, 1)

    H, W = y.shape[:2]
    if a.crop > 0:
        ch, cw = int(H * a.crop), int(W * a.crop)
        y = y[ch:H - ch, cw:W - cw]

    Image.fromarray((np.clip(y, 0, 1) * 255 + 0.5).astype(np.uint8)).save(a.out)
    if a.tiff:
        import tifffile
        tifffile.imwrite(a.out.rsplit(".", 1)[0] + ".tiff",
                         (np.clip(y, 0, 1) * 65535 + 0.5).astype(np.uint16))

    # stats: core resolution proxy = std within core (more resolved -> more structure)
    lum0 = load_rgb(a.inp)[0].mean(-1)
    w = WCS(hdr).celestial
    cx, cy = [int(round(float(v))) for v in w.world_to_pixel_values(M13_RA, M13_DEC)]
    Hf, Wf = lum0.shape
    core = y.mean(-1)[max(0, (cy - int(Hf*a.crop) if a.crop>0 else cy) - 60):, :] if False else None
    # simpler: clip fraction in display core
    yl = y.mean(-1)
    Hc, Wc = yl.shape
    ccx, ccy = Wc // 2, Hc // 2
    cz = yl[ccy - 80:ccy + 80, ccx - 80:ccx + 80]
    clip = float(np.mean(cz > 0.95))
    print(f"WROTE {a.out} ({Wc}x{Hc})  core_clip_frac(>0.95)={clip:.4f}  core_med={np.median(cz):.3f} core_p99={np.percentile(cz,99):.3f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--curve", default="asinh", choices=["asinh", "ghs"])
    p.add_argument("--params", default=None)
    p.add_argument("--rgb", default="1.35,1.02,0.78")
    p.add_argument("--white", type=float, default=99.96)
    p.add_argument("--sat", type=float, default=1.6)
    p.add_argument("--crop", type=float, default=0.0)
    p.add_argument("--tiff", action="store_true")
    main(p.parse_args())
