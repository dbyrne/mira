"""Verified finishing presets — the 2026-06-09 reprocessing session, baked.

Three presets, each the exact recipe that beat the prior keeper for its
regime (provenance in the per-target PROCESSING_LOG/NOTES files):

  faint-galaxy       M51 all-lum refinish: asinh + soft black point +
                     bg-neutralize + SCNR + gated chroma denoise + gated
                     local contrast. No StarNet needed.
  faint-galaxy-deep  M81 group keeper: starnet-decouple (M81 shootout winner,
                     adversarially verified) — starless re-linearize → noise-
                     floor toe → deeper asinh dig, stars screened back at
                     sg=1.0 — then lum-preserving SCNR, gated chroma denoise,
                     display pedestal.
  emission           NGC 6888 refinish: highlight rolloff before StarNet,
                     toe+dig starless, luminance-gated teal boost with
                     brightness-rolloff saturation (knots only), gated chroma
                     BLUR (broad field tint preserved), star-layer tone.

Doctrine encoded here (curve-shootout finding, 5 targets):
  * the headroom on faint targets is GATED LOCAL chroma ops, not the curve;
  * background-extract AFTER color calibration (PCC leaves a spatial color
    gradient that any deep dig surfaces — feed these presets a *flattened*
    linear, or let `mira finish --preset` run the bg step first);
  * the noise-floor toe is sized in measured sky sigmas (auto), never a
    fixed constant — fixed toes were either no-ops or envelope-eaters.

All ops are pure numpy on (H, W, 3) float64 in [0, 1]. StarNet2 is an
optional external CLI: $MIRA_STARNET, then `starnet2` on PATH. Its
decomposition is cached under data/starnet_cache/ keyed by the exact
prestretched frame, so re-renders and parameter sweeps are cheap.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

warnings.filterwarnings("ignore")

DEFAULT_CACHE_DIR = Path("data") / "starnet_cache"


class StarNetNotFound(RuntimeError):
    """StarNet2 CLI could not be located (and fallback was not allowed)."""


# --------------------------------------------------------------------------
# small math helpers
# --------------------------------------------------------------------------

def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0 + 1e-12), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _gauss(im: np.ndarray, sigma: float) -> np.ndarray:
    try:
        import cv2
        k = int(sigma * 6) | 1
        return cv2.GaussianBlur(im, (k, k), sigma)
    except ImportError:
        from scipy.ndimage import gaussian_filter
        if im.ndim == 3:
            return np.stack([gaussian_filter(im[..., c], sigma) for c in range(im.shape[-1])], -1)
        return gaussian_filter(im, sigma)


def robust_sky_sigma(lum: np.ndarray) -> float:
    """Global robust sigma of the (sky-dominated) luminance plane."""
    from astropy.stats import sigma_clipped_stats
    _, _, sd = sigma_clipped_stats(lum)
    return float(sd)


# --------------------------------------------------------------------------
# ops library (each op = one verified move from the keeper recipes)
# --------------------------------------------------------------------------

def load_linear_rgb(path: Path) -> tuple[np.ndarray, object]:
    from astropy.io import fits
    hd = fits.open(str(path))[0]
    d = np.asarray(hd.data, dtype=np.float64)
    if d.ndim == 2:
        d = np.stack([d] * 3, -1)
    elif d.ndim == 3 and d.shape[0] == 3:
        d = np.moveaxis(d, 0, -1)
    return d, hd.header


def normalize(rgb: np.ndarray, white_pct: float) -> np.ndarray:
    """curve_lab pipeline: per-channel sigma-clipped-median black, global
    white percentile. The Crescent lesson is encoded in the caller's
    white_pct: 99.99 crushes faint emission — emission uses 99.6."""
    from astropy.stats import sigma_clipped_stats
    x = rgb.astype(np.float64).copy()
    for c in range(3):
        _, med, _ = sigma_clipped_stats(rgb[..., c])
        x[..., c] = rgb[..., c] - med
    white = float(np.percentile(x, white_pct))
    return np.clip(x / (white + 1e-12), 0.0, 1.0)


def soft_black_point(rgb: np.ndarray, pct: float, nsig: float, sigma: float) -> np.ndarray:
    """Per-channel black at (percentile − nsig·sigma): relocates the floor
    without crushing the noise tail (hard black points read crunchy)."""
    out = rgb.copy()
    for c in range(3):
        bp = np.percentile(out[..., c], pct) - nsig * sigma
        out[..., c] = np.clip(out[..., c] - bp, 0.0, None)
    wp = np.percentile(out, 99.95)
    return np.clip(out / (wp + 1e-12), 0.0, 1.0)


def asinh_stretch(x: np.ndarray, a: float) -> np.ndarray:
    return np.clip(np.arcsinh(x / a) / np.arcsinh(1.0 / a), 0.0, 1.0)


def highlight_rolloff(x: np.ndarray, k: float) -> np.ndarray:
    """C1-continuous soft shoulder above k; caps ≈ 1−(1−k)/e. Applied to the
    StarNet input so bright emission never clips into the decomposition."""
    out = x.copy()
    hi = out > k
    out[hi] = 1.0 - (1.0 - k) * np.exp(-(out[hi] - k) / (1.0 - k))
    return out


def noise_toe(x: np.ndarray, toe: float) -> np.ndarray:
    """y²/(y+toe)·(1+toe): quadratic suppression below the toe, ~unity slope
    above, f(1)=1. Size toe in measured sky sigmas (1–2σ); past ~4σ is
    metric-gaming territory (M81 shootout verifier)."""
    if toe <= 0:
        return x
    return (x * x / (x + toe)) * (1.0 + toe)


def bg_neutralize_offset(rgb: np.ndarray, pct: float = 55.0,
                         target: float | None = None) -> np.ndarray:
    """Equalize per-channel background medians by OFFSET (never scale —
    offset kills the cast without shifting star/object color). target=None
    keeps the mean level (pure hue fix)."""
    lum = rgb.mean(-1)
    m = lum < np.percentile(lum, pct)
    meds = [float(np.median(rgb[..., c][m])) for c in range(3)]
    tgt = float(np.mean(meds)) if target is None else float(target)
    out = rgb.copy()
    for c in range(3):
        out[..., c] = np.clip(out[..., c] - (meds[c] - tgt), 0.0, 1.0)
    return out


def scnr_green(rgb: np.ndarray, amount: float, keep_lum: bool = True) -> np.ndarray:
    """SCNR average-neutral green suppression. keep_lum restores the
    luminance plane afterward so the cast is removed as COLOR but kept as
    light — verified to preserve faint-structure gradients exactly (M81:
    95.4% = pedestal-only scale; plain SCNR cost an extra ~5%)."""
    if amount <= 0:
        return rgb
    out = rgb.copy()
    L0 = out.mean(-1, keepdims=True)
    neutral = 0.5 * (out[..., 0] + out[..., 2])
    g = out[..., 1]
    out[..., 1] = g * (1.0 - amount) + np.minimum(g, neutral) * amount
    if keep_lum:
        out = np.clip(out + (L0 - out.mean(-1, keepdims=True)), 0.0, 1.0)
    return out


def gated_chroma_denoise(rgb: np.ndarray, gate_lo: float, gate_hi: float,
                         sigma: float, keep: float) -> np.ndarray:
    """THE local op (curve-shootout unifying finding): below the luminance
    gate, replace chroma with a blurred (and optionally attenuated) version.
    Luminance is untouched by construction. keep=1.0 → pure blur: speckle
    smoothed, broad real field tint fully preserved (the emission setting);
    keep<1 also dims residual bg color (the galaxy setting)."""
    if sigma <= 0:
        return rgb
    lum = rgb.mean(-1, keepdims=True)
    chroma = rgb - lum
    m = smoothstep(gate_hi, gate_lo, lum[..., 0])[..., None]
    smooth = _gauss(chroma, sigma) * keep
    return np.clip(lum + (1.0 - m) * chroma + m * smooth, 0.0, 1.0)


def gated_local_contrast(rgb: np.ndarray, amount: float, radius: float,
                         gate_lo: float, gate_hi: float) -> np.ndarray:
    """Unsharp-style luminance detail, gated to bright structure so the
    background never lifts."""
    if amount <= 0:
        return rgb
    L = rgb.mean(-1)
    detail = L - _gauss(L, radius)
    m = smoothstep(gate_lo, gate_hi, L)
    return np.clip(rgb + (m * amount * detail)[..., None], 0.0, 1.0)


def teal_boost_sat(rgb: np.ndarray, sat_base: float, teal_extra: float,
                   teal_lum_lo: float, teal_lum_hi: float,
                   roll_lo: float, roll_hi: float, sat_bright: float) -> np.ndarray:
    """Emission saturation: base boost, extra on teal (OIII) — but the teal
    test alone matches blue NOISE, so it is luminance-gated; and brightness
    rolls saturation down to sat_bright on the brightest knots only
    (roll_lo ≈ 0.62 — lower desaturates the whole shell, the v2 mistake)."""
    L = rgb.mean(-1, keepdims=True)
    maxch = rgb.max(-1)
    tealness = smoothstep(0.01, 0.10, np.minimum(rgb[..., 1], rgb[..., 2]) - rgb[..., 0])
    tealness = tealness * smoothstep(teal_lum_lo, teal_lum_hi, L[..., 0])
    sat_map = sat_base + teal_extra * tealness
    t = smoothstep(roll_lo, roll_hi, maxch)
    sat_eff = (sat_map * (1.0 - t) + sat_bright * t)[..., None]
    return np.clip(L + (rgb - L) * sat_eff, 0.0, 1.0)


def star_tone(stars: np.ndarray, gamma: float, scale: float, sat: float) -> np.ndarray:
    """Per-star brightness curve lum^gamma·scale (gamma>1 thins the faint
    field more than bright stars) + gentle desaturation. The June-2 'light'
    setting (1.7/0.95) is the shipped default."""
    L = stars.mean(-1, keepdims=True)
    tone = np.clip(L, 1e-6, 1.0) ** (gamma - 1.0) * scale
    out = np.clip(stars * tone, 0.0, 1.0)
    Lt = L * tone
    return np.clip(Lt + (out - Lt) * sat, 0.0, 1.0)


def screen(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - (1.0 - a) * (1.0 - b), 0.0, 1.0)


def s_curve(rgb: np.ndarray, strength: float) -> np.ndarray:
    if not strength:
        return rgb
    return np.clip(0.5 + (1 + strength) * (rgb - 0.5) - strength * (2 * (rgb - 0.5)) ** 3 / 2, 0.0, 1.0)


def saturation(rgb: np.ndarray, sat: float) -> np.ndarray:
    if sat == 1.0:
        return rgb
    lum = rgb.mean(-1, keepdims=True)
    return np.clip(lum + (rgb - lum) * sat, 0.0, 1.0)


def gamma_adjust(rgb: np.ndarray, gamma: float) -> np.ndarray:
    if gamma == 1.0:
        return rgb
    return np.clip(rgb, 0.0, 1.0) ** (1.0 / gamma)


def pedestal(rgb: np.ndarray, p: float) -> np.ndarray:
    """Display floor lift (pure levels move: separation preserved, nothing
    new clips). Fixes the toe's inky 0-floor — M81 went 67%-zero without it."""
    if p <= 0:
        return rgb
    return np.clip(p + rgb * (1.0 - p), 0.0, 1.0)


# --------------------------------------------------------------------------
# StarNet2 decomposition (cached)
# --------------------------------------------------------------------------

def find_starnet(override: str | None = None) -> str:
    cand = override or os.environ.get("MIRA_STARNET")
    if cand and Path(cand).exists():
        return cand
    exe = shutil.which("starnet2") or shutil.which("starnet2.exe")
    if exe:
        return exe
    raise StarNetNotFound(
        "StarNet2 CLI not found. Set $MIRA_STARNET to starnet2.exe (or put it "
        "on PATH), or pass --starnet-exe. The 'faint-galaxy' preset needs no "
        "StarNet; deep/emission presets can degrade with allow_fallback "
        "(morphological star split — visibly worse, fine for previews)."
    )


def _morphological_decompose(base: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    starless = np.empty_like(base)
    for c in range(3):
        starless[..., c] = cv2.morphologyEx(base[..., c].astype(np.float32), cv2.MORPH_OPEN, kernel)
    starless = np.minimum(starless, base)
    return starless, base - starless


def starnet_decompose(base: np.ndarray, exe: str | None = None,
                      cache_dir: Path = DEFAULT_CACHE_DIR,
                      allow_fallback: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """StarNet2 split of a display-stretched frame; disk-cached by frame
    hash. GOTCHAS (hard-won): StarNet wants a stretched uint16 TIFF, writes
    LZW TIFFs that must be read with cv2 (not tifffile), and its weights
    must sit beside the exe (run with cwd=exe dir)."""
    import cv2
    q = (np.clip(base, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    key = hashlib.sha1(q.tobytes() + b"|up0").hexdigest()[:16]
    # absolute: StarNet runs with cwd=exe dir (weights live there), so any
    # relative path here silently resolves against the WRONG directory
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    npz = cache_dir / f"decomp_{key}.npz"
    if npz.exists():
        z = np.load(npz)
        return z["starless"].astype(np.float64) / 65535.0, z["stars"].astype(np.float64) / 65535.0

    if min(base.shape[:2]) < 512:
        return _morphological_decompose(base)
    try:
        exe_path = find_starnet(exe)
    except StarNetNotFound:
        if allow_fallback:
            print("finish-presets: StarNet missing — morphological fallback (preview quality)", file=sys.stderr)
            return _morphological_decompose(base)
        raise

    tif_in = cache_dir / f"in_{key}.tif"
    tif_sl = cache_dir / f"starless_{key}.tif"
    tif_st = cache_dir / f"stars_{key}.tif"
    cv2.imwrite(str(tif_in), q[..., ::-1])
    cmd = [exe_path, "--input", str(tif_in), "--output", str(tif_sl),
           "--unscreen", str(tif_st), "--quiet"]
    subprocess.run(cmd, cwd=str(Path(exe_path).parent), check=True, capture_output=True)
    sl = cv2.imread(str(tif_sl), cv2.IMREAD_UNCHANGED)
    st = cv2.imread(str(tif_st), cv2.IMREAD_UNCHANGED)
    if sl is None or st is None:
        raise RuntimeError(f"StarNet output unreadable: {tif_sl} / {tif_st}")
    sl = sl[..., ::-1].astype(np.uint16)
    st = st[..., ::-1].astype(np.uint16)
    np.savez_compressed(npz, starless=sl, stars=st)
    return sl.astype(np.float64) / 65535.0, st.astype(np.float64) / 65535.0


# --------------------------------------------------------------------------
# the presets
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    needs_starnet: bool
    params: dict = field(default_factory=dict)
    fn: Callable = None  # (rgb_linear, params, starnet_kwargs) -> rgb display


def _render_faint_galaxy(rgb: np.ndarray, p: dict, sn: dict) -> np.ndarray:
    lum = rgb.mean(-1)
    sigma = robust_sky_sigma(lum)
    x = soft_black_point(rgb, p["black_pct"], p["bp_soft_sigma"], sigma)
    x = asinh_stretch(x, p["asinh_a"])
    x = bg_neutralize_offset(x, pct=p["bg_pct"], target=p["bg_target"])
    x = scnr_green(x, p["scnr"], keep_lum=True)
    x = gated_chroma_denoise(x, p["gate_lo"], p["gate_hi"], p["chroma_sigma"], p["chroma_keep"])
    x = gated_local_contrast(x, p["lc_amount"], p["lc_radius"], p["lc_gate_lo"], p["lc_gate_hi"])
    x = s_curve(x, p["scurve"])
    x = saturation(x, p["sat"])
    return gamma_adjust(x, p["gamma"])


def _render_faint_galaxy_deep(rgb: np.ndarray, p: dict, sn: dict) -> np.ndarray:
    x = normalize(rgb, p["white_pct"])
    sigma_lin = robust_sky_sigma(x.mean(-1))
    ka = np.arcsinh(1.0 / p["asinh_a"])
    base = np.arcsinh(x / p["asinh_a"]) / ka
    starless, stars = starnet_decompose(base, **sn)
    s_lin = p["asinh_a"] * np.sinh(np.clip(starless, 0, 1) * ka)
    s_lin = noise_toe(s_lin, p["toe_sigma"] * sigma_lin)
    neb = asinh_stretch(np.clip(s_lin, 0, None), p["dig_b"])
    out = screen(neb, np.clip(stars, 0, 1) * p["star_gain"])
    out = scnr_green(out, p["scnr"], keep_lum=True)
    out = bg_neutralize_offset(out, pct=p["bg_pct"], target=None)
    out = gated_chroma_denoise(out, p["gate_lo"], p["gate_hi"], p["chroma_sigma"], p["chroma_keep"])
    return pedestal(out, p["pedestal"])


def _render_emission(rgb: np.ndarray, p: dict, sn: dict) -> np.ndarray:
    x = normalize(rgb, p["white_pct"])
    sigma_lin = robust_sky_sigma(x.mean(-1))
    x = highlight_rolloff(x, p["rolloff_k"])
    ka = np.arcsinh(1.0 / p["asinh_a"])
    base = np.arcsinh(x / p["asinh_a"]) / ka
    starless, stars = starnet_decompose(base, **sn)
    s_lin = p["asinh_a"] * np.sinh(np.clip(starless, 0, 1) * ka)
    s_lin = noise_toe(s_lin, p["toe_sigma"] * sigma_lin)
    neb = asinh_stretch(np.clip(s_lin, 0, None), p["dig_b"])
    neb = bg_neutralize_offset(neb, pct=p["bg_pct"], target=None)
    neb = teal_boost_sat(neb, p["sat_base"], p["teal_extra"],
                         p["teal_lum_lo"], p["teal_lum_hi"],
                         p["roll_lo"], p["roll_hi"], p["sat_bright"])
    neb = gated_chroma_denoise(neb, p["gate_lo"], p["gate_hi"], p["chroma_sigma"], 1.0)
    st = star_tone(np.clip(stars, 0, 1) * p["star_gain"],
                   p["star_gamma"], p["star_scale"], p["star_sat"])
    out = screen(neb, st)
    return pedestal(out, p["pedestal"])


PRESETS: dict[str, Preset] = {
    "faint-galaxy": Preset(
        "faint-galaxy",
        "Broadband faint galaxy (M51 all-lum refinish, 2026-06-09). No StarNet.",
        needs_starnet=False,
        params=dict(black_pct=25.0, bp_soft_sigma=4.0, asinh_a=0.030,
                    bg_pct=60.0, bg_target=0.075, scnr=0.7,
                    gate_lo=0.10, gate_hi=0.22, chroma_sigma=6.0, chroma_keep=0.25,
                    lc_amount=0.12, lc_radius=30.0, lc_gate_lo=0.12, lc_gate_hi=0.25,
                    scurve=0.08, sat=1.40, gamma=1.04),
        fn=_render_faint_galaxy,
    ),
    "faint-galaxy-deep": Preset(
        "faint-galaxy-deep",
        "Faint galaxy, starnet-decouple toe+dig (M81 shootout winner, verified).",
        needs_starnet=True,
        params=dict(white_pct=99.99, asinh_a=0.025, dig_b=0.014, toe_sigma=1.5,
                    star_gain=1.0, scnr=0.7, bg_pct=55.0,
                    gate_lo=0.05, gate_hi=0.15, chroma_sigma=5.0, chroma_keep=0.3,
                    pedestal=0.045),
        fn=_render_faint_galaxy_deep,
    ),
    "emission": Preset(
        "emission",
        "Emission nebula on dual-band OSC (NGC 6888 refinish, 2026-06-09).",
        needs_starnet=True,
        params=dict(white_pct=99.6, rolloff_k=0.62, asinh_a=0.05, dig_b=0.03,
                    toe_sigma=1.5, bg_pct=55.0,
                    sat_base=2.3, teal_extra=0.9, teal_lum_lo=0.06, teal_lum_hi=0.16,
                    roll_lo=0.62, roll_hi=0.95, sat_bright=1.15,
                    gate_lo=0.07, gate_hi=0.18, chroma_sigma=4.0,
                    star_gain=1.0, star_gamma=1.7, star_scale=0.95, star_sat=0.95,
                    pedestal=0.03),
        fn=_render_emission,
    ),
}


def render_preset(rgb_linear: np.ndarray, preset_name: str,
                  overrides: dict | None = None,
                  starnet_exe: str | None = None,
                  cache_dir: Path = DEFAULT_CACHE_DIR,
                  allow_fallback: bool = False) -> np.ndarray:
    preset = PRESETS[preset_name]
    params = dict(preset.params)
    if overrides:
        unknown = set(overrides) - set(params)
        if unknown:
            raise KeyError(f"unknown param(s) for preset {preset_name}: {sorted(unknown)}; "
                           f"valid: {sorted(params)}")
        params.update(overrides)
    sn = dict(exe=starnet_exe, cache_dir=cache_dir, allow_fallback=allow_fallback)
    return preset.fn(rgb_linear, params, sn)


def write_outputs(rgb: np.ndarray, out_path: Path, also_tiff: bool = True) -> None:
    from PIL import Image
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").save(str(out_path))
    if also_tiff:
        import tifffile
        tifffile.imwrite(str(out_path.with_suffix(".tiff")),
                         (np.clip(rgb, 0, 1) * 65535 + 0.5).astype(np.uint16))


def contact_sheet(rgb_linear: np.ndarray, header, out_path: Path,
                  ra: float | None = None, dec: float | None = None,
                  crop_half: int = 800, starnet_exe: str | None = None,
                  cache_dir: Path = DEFAULT_CACHE_DIR,
                  allow_fallback: bool = True) -> Path:
    """Render every preset on a centered crop, side by side, for eye-judging
    — the shootout's own conclusion: metrics propose, the EYE disposes.
    Percentile-based ops see crop statistics here, so the full-frame render
    of the chosen preset will differ slightly; this is a chooser, not a
    keeper. StarNet runs per-crop (fast); falls back morphological by
    default so the sheet never blocks on a missing exe."""
    from PIL import Image, ImageDraw
    H, W, _ = rgb_linear.shape
    cx, cy = W // 2, H // 2
    if ra is not None and dec is not None and header is not None:
        try:
            from astropy.wcs import WCS
            w = WCS(header, naxis=2)
            px, py = w.world_to_pixel_values(ra, dec)
            cx, cy = int(round(float(px))), int(round(float(py)))
        except Exception:
            pass
    half = min(crop_half, cx, cy, W - cx, H - cy)
    crop = rgb_linear[cy - half:cy + half, cx - half:cx + half]

    panels, labels = [], []
    for name in PRESETS:
        rendered = render_preset(crop, name, starnet_exe=starnet_exe,
                                 cache_dir=cache_dir, allow_fallback=allow_fallback)
        panels.append((np.clip(rendered, 0, 1) * 255 + 0.5).astype(np.uint8))
        labels.append(name)
    h = min(720, panels[0].shape[0])
    resized = []
    for p in panels:
        im = Image.fromarray(p)
        im = im.resize((int(im.width * h / im.height), h), Image.LANCZOS)
        resized.append(np.asarray(im))
    gap = np.full((h, 8, 3), 64, np.uint8)
    sheet = resized[0]
    for r in resized[1:]:
        sheet = np.hstack([sheet, gap, r])
    img = Image.fromarray(sheet)
    d = ImageDraw.Draw(img)
    xoff = 6
    for p, label in zip(resized, labels):
        d.text((xoff, 6), label, fill=(255, 255, 0))
        xoff += p.shape[1] + 8
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path))
    return out_path
