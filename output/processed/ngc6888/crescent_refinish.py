#!/usr/bin/env python
"""NGC 6888 refinish — 2026-06-09. Starnet-decouple with the M81-validated
noise-floor toe + deeper starless dig, composed with the June-2 keeper's wins.

vs the 2026-06-02 primary: that recipe stretched once (asinh 0.05 / wp 99.6),
decomposed, then boosted color — the starless layer never got a re-linearized
faint dig, so the outer OIII envelope and field nebulosity sit at the single
global stretch's depth. This script:

  load ngc6888_cc.fit (PCC'd linear)
  -> per-channel sky black + wp 99.6 normalize     (curve_lab pipeline)
  -> highlight rolloff k=0.62                      (June-2 Ha-blowout fix #1)
  -> prestretch asinh(a)  ->  StarNet2 decompose   (cached npz, plugin code)
  starless: re-linearize -> toe -> asinh(b) dig    (M81 shootout winner move)
            -> teal-weighted, brightness-rolloff saturation  (fix #2)
            -> gated chroma BLUR (speckle out, broad field tint kept)
  stars:    sg scale + per-star tone lum^gamma * scale ("light" = 1.7/0.95)
  screen recombine -> pedestal -> PNG + 16-bit TIFF + dual-hue metrics.
"""
import argparse
import importlib.util
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS
from PIL import Image

try:
    import cv2
    def gauss(im, sigma):
        k = int(sigma * 6) | 1
        return cv2.GaussianBlur(im, (k, k), sigma)
except ImportError:
    from scipy.ndimage import gaussian_filter
    def gauss(im, sigma):
        return np.stack([gaussian_filter(im[..., c], sigma) for c in range(3)], -1) if im.ndim == 3 else gaussian_filter(im, sigma)

PLUGIN = r"C:\mira\output\M81_curveshootout\curves\starnet-decouple.py"
RA, DEC = 303.0, 38.35


def load_plugin():
    spec = importlib.util.spec_from_file_location("sd", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0, 1)
    return t * t * (3 - 2 * t)


def annulus(shape, cx, cy, r0, r1):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    r = np.hypot(xx - cx, yy - cy)
    return (r >= r0) & (r < r1)


def dual_hue_report(rgb, cx, cy, label):
    L = rgb.mean(-1)
    rim = annulus(L.shape, cx, cy, 40, 170)
    halo = annulus(L.shape, cx, cy, 170, 300)
    skyb = annulus(L.shape, cx, cy, 420, 560)
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    red = (R - np.maximum(G, B))      # Ha redness
    teal = (np.minimum(G, B) - R)     # OIII tealness
    redfrac = float((red[rim] > 0.04).mean())
    tealfrac_rim = float((teal[rim] > 0.03).mean())
    tealfrac_halo = float((teal[halo] > 0.03).mean())
    pure_red_clip = float(((R >= 0.99) & (G < 0.5) & (B < 0.5))[rim].mean())
    ch = rgb[skyb]
    bg_chroma = float(np.mean([np.std(ch[:, 0] - ch[:, 1]), np.std(ch[:, 2] - ch[:, 1])]))
    hp = rgb - gauss(rgb, 4.0)
    hps = hp[skyb]
    bg_speckle = float(np.mean([np.std(hps[:, 0] - hps[:, 1]), np.std(hps[:, 2] - hps[:, 1])]))
    starm = L > 0.5
    star_sat = float((rgb.max(-1) - rgb.min(-1))[starm].mean()) if starm.any() else 0.0
    print(f"  [{label}] rim: red%={redfrac*100:.1f} teal%={tealfrac_rim*100:.1f} "
          f"| halo teal%={tealfrac_halo*100:.1f} | pure-red-clip={pure_red_clip*100:.3f}% "
          f"| bg chroma={bg_chroma:.4f} speckle={bg_speckle:.4f} | star_sat={star_sat:.3f} "
          f"| midtone={float(np.median(L)):.4f}")


def main(a):
    sd = load_plugin()
    hd = fits.open(a.inp)[0]
    rgb = np.moveaxis(np.asarray(hd.data, np.float64), 0, -1)
    w = WCS(hd.header, naxis=2)
    cx, cy = (int(round(float(v))) for v in w.world_to_pixel_values(RA, DEC))
    print(f"crescent center px=({cx},{cy})")

    # curve_lab normalize: per-channel sigma-clipped median black, global white pct
    x = rgb.copy()
    for c in range(3):
        _, med, _ = sigma_clipped_stats(rgb[..., c])
        x[..., c] = rgb[..., c] - med
    white = float(np.percentile(x, a.white_pct))
    x = np.clip(x / (white + 1e-12), 0, 1)
    skyb = annulus(x.shape[:2], cx, cy, 420, 560)
    _, smed, ssd = sigma_clipped_stats(x.mean(-1)[skyb])
    print(f"normalized: white={white:.5f} sky_med={smed:.5f} sky_sigma_lin={ssd:.5f} "
          f"(toe={a.toe} = {a.toe/ssd:.1f} sigma)")

    # June-2 highlight rolloff so bright Ha never clips into StarNet
    k = a.rolloff
    hi = x > k
    x[hi] = 1 - (1 - k) * np.exp(-(x[hi] - k) / (1 - k))

    # prestretch + cached StarNet decomposition (plugin internals)
    ka = np.arcsinh(1.0 / a.a)
    base = np.arcsinh(x / a.a) / ka
    starless, stars = sd._decompose(base, False)
    print("decomposed (cache hit or fresh StarNet run done)")

    # ---- starless: re-linearize -> toe -> linear color-equalize -> dig ----
    s_lin = a.a * np.sinh(np.clip(starless, 0, 1) * ka)
    if a.toe > 0:
        s_lin = (s_lin * s_lin / (s_lin + a.toe)) * (1 + a.toe)
    # equalize per-channel sky level in LINEAR domain so the dig amplifies a
    # neutral floor (fixes the PCC navy-cast the offset trim can't reach).
    # Skip on already-flattened inputs: with bg medians ~0 the scale ratios
    # are noise-driven and skew the channel balance.
    if a.lin_eq:
        Ls = s_lin.mean(-1)
        bgm = Ls < np.percentile(Ls, 55.0)
        meds = [float(sigma_clipped_stats(s_lin[..., c][bgm])[1]) for c in range(3)]
        mtgt = float(np.mean(meds))
        print(f"  lin-eq channel medians: {meds} -> {mtgt:.6f}")
        for c in range(3):
            if meds[c] > 1e-9:
                s_lin[..., c] = s_lin[..., c] * (mtgt / meds[c])
    neb = np.arcsinh(np.clip(s_lin, 0, None) / a.b) / np.arcsinh(1.0 / a.b)

    # background hue neutralization BEFORE saturation (offset — kills the
    # dug-up blue cast at the source; broad field structure survives as
    # spatial excursions above the neutral floor)
    Lneb = neb.mean(-1)
    bgmask = Lneb < np.percentile(Lneb, 55.0)
    bg_c = [float(np.median(neb[..., c][bgmask])) for c in range(3)]
    tgt = float(np.mean(bg_c))
    for c in range(3):
        neb[..., c] = np.clip(neb[..., c] - (bg_c[c] - tgt), 0, 1)

    # teal-weighted, brightness-rolloff saturation. The teal test alone also
    # matches blue sky noise — gate it by luminance so only real OIII
    # structure (not background) gets the boost.
    L = neb.mean(-1, keepdims=True)
    maxch = neb.max(-1)
    tealness = smoothstep(0.01, 0.10, (np.minimum(neb[..., 1], neb[..., 2]) - neb[..., 0]))
    tealness = tealness * smoothstep(a.teal_lum_lo, a.teal_lum_hi, L[..., 0])
    sat_map = a.sat_base + a.teal_extra * tealness
    bright_t = smoothstep(a.roll_lo, a.roll_hi, maxch)
    sat_eff = (sat_map * (1 - bright_t) + a.sat_bright * bright_t)[..., None]
    neb = np.clip(L + (neb - L) * sat_eff, 0, 1)

    # gated chroma BLUR (keep=1: speckle smoothed, broad field tint preserved)
    Ln = neb.mean(-1, keepdims=True)
    chroma = neb - Ln
    m = smoothstep(a.gate_hi, a.gate_lo, Ln[..., 0])[..., None]
    neb = np.clip(Ln + (1 - m) * chroma + m * gauss(chroma, a.chroma_sigma), 0, 1)

    # ---- stars: scale, per-star tone, slight desat ----
    st = np.clip(stars, 0, 1) * a.sg
    Ls = st.mean(-1, keepdims=True)
    tone = np.clip(Ls, 1e-6, 1) ** (a.star_gamma - 1.0) * a.star_scale
    st = np.clip(st * tone, 0, 1)
    st = np.clip(Ls * tone + (st - Ls * tone) * a.star_sat, 0, 1)

    out = 1 - (1 - neb) * (1 - st)
    if a.pedestal > 0:
        out = np.clip(a.pedestal + out * (1 - a.pedestal), 0, 1)
    out = np.clip(out, 0, 1)

    print("metrics:")
    dual_hue_report(out, cx, cy, "refinish")
    if a.compare and os.path.exists(a.compare):
        import tifffile
        old = tifffile.imread(a.compare).astype(np.float64)
        old = old / 65535.0 if old.max() > 1.5 else old
        oc = (old.shape[1] // 2, old.shape[0] // 2)  # June-2 crop is nebula-centered
        dual_hue_report(old, oc[0], oc[1], "20260602")

    Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB").save(a.out)
    if a.tiff:
        import tifffile
        tifffile.imwrite(a.out.rsplit(".", 1)[0] + ".tiff", (out * 65535 + 0.5).astype(np.uint16))
    # nebula-centered crop preview like the June-2 keeper framing
    half = a.crop_half
    crop = out[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    Image.fromarray((crop * 255 + 0.5).astype(np.uint8), "RGB").save(a.out.rsplit(".", 1)[0] + "_crop.png")
    print(f"WROTE {a.out} (+_crop.png{' +.tiff' if a.tiff else ''})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", default=r"C:\mira\output\ngc6888\ngc6888_cc.fit")
    p.add_argument("--out", required=True)
    p.add_argument("--white-pct", type=float, default=99.6, help="Crescent lesson: NOT 99.99")
    p.add_argument("--rolloff", type=float, default=0.62)
    p.add_argument("--lin-eq", action="store_true", help="linear-domain channel equalization (for un-flattened inputs)")
    p.add_argument("--a", type=float, default=0.05, help="prestretch / star-layer asinh")
    p.add_argument("--b", type=float, default=0.02, help="starless dig asinh (< a)")
    p.add_argument("--toe", type=float, default=0.002)
    p.add_argument("--sg", type=float, default=1.0)
    p.add_argument("--sat-base", type=float, default=2.2)
    p.add_argument("--teal-extra", type=float, default=0.9)
    p.add_argument("--teal-lum-lo", type=float, default=0.10)
    p.add_argument("--teal-lum-hi", type=float, default=0.22)
    p.add_argument("--sat-bright", type=float, default=1.15)
    p.add_argument("--roll-lo", type=float, default=0.45)
    p.add_argument("--roll-hi", type=float, default=0.80)
    p.add_argument("--gate-lo", type=float, default=0.07)
    p.add_argument("--gate-hi", type=float, default=0.18)
    p.add_argument("--chroma-sigma", type=float, default=4.0)
    p.add_argument("--star-gamma", type=float, default=1.7)
    p.add_argument("--star-scale", type=float, default=0.95)
    p.add_argument("--star-sat", type=float, default=0.95)
    p.add_argument("--pedestal", type=float, default=0.03)
    p.add_argument("--crop-half", type=int, default=620)
    p.add_argument("--compare", default=r"C:\mira\output\ngc6888\NGC6888_crescent_20260602.tiff")
    p.add_argument("--tiff", action="store_true")
    main(p.parse_args())
