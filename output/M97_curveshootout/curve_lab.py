#!/usr/bin/env python
"""curve_lab.py -- pluggable-curve stretch shootout harness (the process-finish tool).

Fixed pipeline so variants differ ONLY in the tone curve:
  load linear FITS -> per-channel sky-median black -> global white-pct normalize to [0,1]
  -> [pluggable curve: curves/<name>.py :: apply(x, **p)] -> saturation -> PNG/preview + stats.

A tone curve cannot change linear SNR (the data sets that), so EVERY ranking stat is
display-space. Two metric MODES for the two regimes validated on M51 (galaxy) and M57 (planetary):

  --mode faint   faint-dominated galaxies. Metric = faint-feature contrast/detect above a
                 corner sky, + core/frame clipping. (M51: asinh already sits on the frontier;
                 global curves don't beat it -- the win is local-contrast + integration.)
  --mode chroma  bright planetaries. Metric = rim CHROMA (color retention) + chrominance sky-noise
                 (the M51 metric was blind to color mottle). (M57: curves DO beat asinh, but the
                 chroma metric over-credits single-hue saturation -- judge multi-hue by eye.)

IMPORTANT (learned the hard way, twice): the metric is a SERVANT. faint_detect is gameable by
shrinking the sky-noise denominator; rim_chroma credits saturating the dominant hue as "more
color". Always corroborate the winner with the eye + an adversarial pass. See the mira-finish skill.

Region geometry is parameterized by WCS coords + radii so this works for any target, not just
M51/M57. Curve plugin contract -- curves/<name>.py:
  DEFAULTS = {...}; SWEEP = [ {...}, ... ]
  def apply(x, **params):   # x: float ndarray (H,W,3) in [0,1]; return same shape in [0,1]
"""
import argparse, json, importlib.util, warnings, os, sys
warnings.filterwarnings("ignore")
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


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


def load_curve(name):
    spec = importlib.util.spec_from_file_location("curve_" + name, os.path.join(HERE, "curves", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def locate(header, shape, ra, dec):
    try:
        w = WCS(header, naxis=2)
        x, y = w.world_to_pixel_values(ra, dec)
        return int(round(float(x))), int(round(float(y)))
    except Exception:
        return shape[1] // 2, shape[0] // 2


def normalize(rgb, white_pct):
    x = rgb.astype(np.float64).copy()
    for c in range(3):
        _, med, _ = sigma_clipped_stats(rgb[..., c])
        x[..., c] = rgb[..., c] - med
    white = float(np.percentile(x, white_pct))
    return np.clip(x / (white + 1e-12), 0.0, 1.0), white


def saturate(rgb, sat):
    if sat == 1.0:
        return rgb
    lum = rgb.mean(-1, keepdims=True)
    return np.clip(lum + (rgb - lum) * sat, 0.0, 1.0)


def render(x01, curve, params, sat):
    y = curve.apply(x01.copy(), **params)
    y = np.clip(np.nan_to_num(y, nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    return saturate(y, sat)


def slug(p):
    return "_".join(f"{k}{v}" for k, v in sorted(p.items())) or "default"


def stats_faint(stretched, linear, hdr, a):
    H, W, _ = stretched.shape
    lum, lin = stretched.mean(-1), linear.mean(-1)
    fx, fy = locate(hdr, lum.shape, a.feat_ra if a.feat_ra is not None else a.ra,
                    a.feat_dec if a.feat_dec is not None else a.dec)
    mx, my = locate(hdr, lum.shape, a.ra, a.dec)
    box = lambda im, x, y, r: im[max(0, y - r):y + r, max(0, x - r):x + r]
    sky = lum[int(H * 0.04):int(H * 0.14), int(W * 0.04):int(W * 0.14)]
    sky_med, sky_noise = float(np.median(sky)), float(np.std(sky))
    feat = float(np.median(box(lum, fx, fy, 12)))
    contrast = feat - sky_med
    core = box(lum, mx, my, 20).ravel()
    skl = lin[int(H * 0.04):int(H * 0.14), int(W * 0.04):int(W * 0.14)]
    _, lmed, lsd = sigma_clipped_stats(skl)
    lin_feat_snr = (float(np.median(box(lin, fx, fy, 12))) - lmed) / (lsd + 1e-12)
    return dict(faint_contrast=round(contrast, 4), faint_detect=round(contrast / (sky_noise + 1 / 255), 2),
                sky_disp=round(sky_med, 4), sky_noise_disp=round(sky_noise, 4),
                core_clip=round(float((core >= 0.99).mean()) if core.size else 0.0, 4),
                frame_clip=round(float((lum >= 0.99).mean()), 5), midtone=round(float(np.median(lum)), 4),
                lin_feat_snr=round(float(lin_feat_snr), 2))


def stats_chroma(stretched, linear, hdr, a):
    H, W, _ = stretched.shape
    lum = stretched.mean(-1)
    chroma = stretched.max(-1) - stretched.min(-1)
    llin = linear.mean(-1)
    cx, cy = locate(hdr, lum.shape, a.ra, a.dec)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - cx, yy - cy)
    rim = (r >= a.rim[0]) & (r < a.rim[1])
    halo = (r >= a.halo[0]) & (r < a.halo[1])
    sky = (r >= a.sky[0]) & (r < a.sky[1])
    cen = r < a.rim[0]
    skp = stretched[sky]
    s_sky, s_sig = float(np.median(llin[sky])), float(np.std(llin[sky])) + 1e-12
    return dict(rim_chroma=round(float(chroma[rim].mean()), 4), rim_lum=round(float(lum[rim].mean()), 4),
                rim_clip=round(float((lum[rim] >= 0.99).mean()), 4), center_chroma=round(float(chroma[cen].mean()), 4),
                halo_contrast=round(float(np.median(lum[halo]) - np.median(lum[sky])), 5),
                halo_lum=round(float(np.median(lum[halo])), 4), sky_lum=round(float(np.median(lum[sky])), 4),
                sky_noise_lum=round(float(np.std(lum[sky])), 4),
                sky_noise_chroma=round(float((np.std(skp[:, 0] - skp[:, 1]) + np.std(skp[:, 2] - skp[:, 1])) / 2), 4),
                midtone=round(float(np.median(lum)), 4),
                lin_rim_snr=round((float(np.median(llin[rim])) - s_sky) / s_sig, 1),
                lin_halo_snr=round((float(np.median(llin[halo])) - s_sky) / s_sig, 2))


def write_images(rgb01, out_png, keep, crop):
    full8 = (rgb01 * 255 + 0.5).astype(np.uint8)
    if crop:
        cx, cy, h = crop
        H, W = full8.shape[:2]
        view = full8[max(0, cy - h):min(H, cy + h), max(0, cx - h):min(W, cx + h)]
    else:
        view = full8
    Image.fromarray(view, "RGB").save(out_png)
    prev = Image.fromarray(view, "RGB")
    prev = prev.resize((max(1, int(prev.width * 800.0 / prev.height)), 800), Image.LANCZOS)
    prev.save(out_png.rsplit(".", 1)[0] + "_prev.png")
    if keep:
        import tifffile
        tifffile.imwrite(out_png.rsplit(".", 1)[0] + ".tiff", (rgb01 * 65535 + 0.5).astype(np.uint16))


def selftest(curve, params):
    ramp = np.linspace(0, 1, 256)[None, :, None] * np.ones((4, 1, 3))
    y = curve.apply(ramp.copy(), **params)
    ok = np.all(np.isfinite(y)) and y.min() >= -1e-6 and y.max() <= 1 + 1e-3
    print(f"SELFTEST {'OK' if ok else 'FAIL'}  range=({float(y.min()):.3f},{float(y.max()):.3f})")
    return ok


def main(a):
    rgb, hdr = load_rgb(a.inp)
    x01, white = normalize(rgb, a.white_pct)
    curve = load_curve(a.curve)
    if a.selftest:
        sys.exit(0 if selftest(curve, getattr(curve, "DEFAULTS", {})) else 1)
    cx, cy = locate(hdr, rgb.shape[:2], a.ra, a.dec)
    crop = (cx, cy, a.crop_half) if a.crop_half > 0 else None
    statf = stats_chroma if a.mode == "chroma" else stats_faint
    out_dir = a.out_dir or os.path.join(HERE, "variants", a.curve)
    os.makedirs(out_dir, exist_ok=True)
    if a.params:
        sets = [{k: float(v) for k, v in (kv.split("=") for kv in a.params.split(","))}]
    elif a.sweep:
        sets = getattr(curve, "SWEEP", [getattr(curve, "DEFAULTS", {})])
    else:
        sets = [getattr(curve, "DEFAULTS", {})]
    manifest = []
    for params in sets:
        rgb01 = render(x01, curve, params, a.sat)
        st = statf(rgb01, rgb, hdr, a)
        png = os.path.join(out_dir, f"{a.curve}__{slug(params)}.png")
        write_images(rgb01, png, a.keep, crop)
        row = dict(curve=a.curve, params=params, png=png.replace("\\", "/"),
                   prev=(png.rsplit(".", 1)[0] + "_prev.png").replace("\\", "/"), stats=st)
        manifest.append(row)
        print(json.dumps(row))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


def _radii(s):
    return [float(v) for v in s.split(",")]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="pluggable-curve stretch shootout harness")
    p.add_argument("--in", dest="inp", required=True, help="linear FITS (post bg-extract/denoise/PCC)")
    p.add_argument("--curve", required=True, help="curves/<name>.py")
    p.add_argument("--mode", choices=["faint", "chroma"], default="faint")
    p.add_argument("--ra", type=float, required=True, help="target center RA (deg)")
    p.add_argument("--dec", type=float, required=True, help="target center Dec (deg)")
    p.add_argument("--feat-ra", dest="feat_ra", type=float, default=None, help="faint-mode feature RA (default=center)")
    p.add_argument("--feat-dec", dest="feat_dec", type=float, default=None, help="faint-mode feature Dec (default=center)")
    p.add_argument("--rim", type=_radii, default=[4, 11], help="chroma-mode rim annulus 'r0,r1' px")
    p.add_argument("--halo", type=_radii, default=[12, 20], help="chroma-mode halo annulus 'r0,r1' px")
    p.add_argument("--sky", type=_radii, default=[80, 200], help="chroma-mode sky annulus 'r0,r1' px")
    p.add_argument("--params", default=None, help="single override 'k=v,k=v'")
    p.add_argument("--sweep", action="store_true", help="run the curve's SWEEP")
    p.add_argument("--out-dir", dest="out_dir", default=None)
    p.add_argument("--white-pct", dest="white_pct", type=float, default=99.99)
    p.add_argument("--sat", type=float, default=1.6)
    p.add_argument("--crop-half", dest="crop_half", type=int, default=0, help="px half-box for PNG/preview (0=full frame)")
    p.add_argument("--keep", action="store_true", help="also write a 16-bit TIFF")
    p.add_argument("--selftest", action="store_true")
    main(p.parse_args())
