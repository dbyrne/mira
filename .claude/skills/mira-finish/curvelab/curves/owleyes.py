"""owleyes -- hand-tuned M97 curve: GHS eye/disk knee + gated speckle denoise + teal.

The user's favourite for M97 is the "arctan" curve, which actually runs the GHS
(generalised-hyperbolic) branch: an odd-reflected knee centred at pivot~0.05 that
pushes the dark eye-cavities (x<pivot) down the suppressed lower branch while the
disk rim (x~pivot) rides the steepest max-contrast part -- this is what makes the
two owl "eyes" read.  Hand-tuning the knee harder (higher gain/b) brightens the
disk so the eyes pop more, but it equally amplifies the per-pixel speckle of this
faint, aggressively-stretched disk, which fights the eye-cavity edges.

So this curve adds the one lever the stock GHS curve lacks: a LIGHT, region-gated
luminance denoise applied AFTER the knee.  A small gaussian (~2 px) smooths the
sub-few-px speckle while leaving the ~15 px eye cavities intact, so the eyes read
as clean dark holes instead of noisy mottle.  The smoothing is hue-preserving
(applied as a luminance ratio) and gated to the disk (region mask 0 over sky), so
the background stays exactly at the curve's output -- no sky smoothing, no halo
manipulation.  A mild gated chroma boost keeps the OIII teal.

  gain/pivot/b/shadow -- the GHS eye/disk knee (see arctan.py for the math).
  denoise   -- gaussian sigma (px) for the disk speckle smooth; 0 = no-op.
  dn_lo/hi  -- region-mask ramp (blurred-luminance units): disk -> 1, sky -> 0.
  cgain     -- gated hue-preserving chroma gain (teal); 1.0 = no-op.
"""
import numpy as np
from scipy.ndimage import gaussian_filter


def _ghs_base(u, D, b):
    if abs(b) < 1e-6:
        return 1.0 - np.exp(-D * u)
    return 1.0 - np.power(1.0 + b * D * u, -1.0 / b)


def _shadow_toe(x, s):
    if s <= 0.0:
        return x
    return np.clip((x * x) / (x + s) * (1.0 / (1.0 + s)), 0.0, 1.0)


def _smoothstep(x, lo, hi):
    if hi <= lo:
        return (x >= hi).astype(np.asarray(x).dtype)
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def apply(x, gain=3.0, pivot=0.045, b=2.0, shadow=0.006,
          denoise=2.0, cdenoise=5.0, dn_lo=0.04, dn_hi=0.12, cgain=1.3):
    x = np.clip(x, 0.0, 1.0)
    H, W = x.shape[0], x.shape[1]

    # --- shadow toe (kill sky mottle below the halo scale) then GHS eye/disk knee ---
    x = _shadow_toe(x, float(max(shadow, 0.0)))
    D = np.expm1(gain)
    sp = float(np.clip(pivot, 0.0, 0.999))

    def raw(t):
        t = np.asarray(t, dtype=np.float64)
        out = np.empty_like(t)
        up = t >= sp
        out[up] = _ghs_base(t[up] - sp, D, b)
        out[~up] = -_ghs_base(sp - t[~up], D, b)
        return out

    lo = float(raw(np.array([0.0]))[0])
    hi = float(raw(np.array([1.0]))[0])
    y = np.clip((raw(x) - lo) / (hi - lo + 1e-12), 0.0, 1.0)   # (H,W,3) stretched

    # selftest / tiny input: skip spatial ops, return the pure knee (monotone, in-range)
    if H < 8 or W < 8:
        return np.clip(y, 0.0, 1.0)

    ref = float(min(H, W))
    # region mask: lit-disk only, 0 over sky (built from a disk-scale blur)
    Lo = gaussian_filter(y.mean(-1), max(0.01 * ref, 1.0), mode="nearest")
    m = _smoothstep(Lo, dn_lo, dn_hi)

    # --- gated speckle denoise: LIGHT on luminance (keep the ~15px eye structure sharp),
    #     HEAVY on chroma (kill the green/blue per-pixel colour mottle that the aggressive
    #     stretch + saturation amplify -- the eye tolerates low colour resolution).  Both
    #     gated to the disk so sky stays untouched. ---
    if (denoise and denoise > 0.0) or (cdenoise and cdenoise > 0.0):
        L = y.mean(-1)
        C = y - L[..., None]                        # colour residual (sums to 0 over channels)
        if denoise and denoise > 0.0:
            Lb = gaussian_filter(L, float(max(denoise, 0.3)), mode="nearest")
            L = L + (Lb - L) * m
        if cdenoise and cdenoise > 0.0:
            sc = float(max(cdenoise, 0.3))
            Cb = np.stack([gaussian_filter(C[..., k], sc, mode="nearest") for k in range(C.shape[-1])], -1)
            C = C + (Cb - C) * m[..., None]
        y = np.clip(L[..., None] + C, 0.0, 1.0)

    # --- mild gated teal chroma boost ---
    if cgain != 1.0:
        lum = y.mean(-1, keepdims=True)
        boost = 1.0 + (float(cgain) - 1.0) * m[..., None]
        y = np.clip(lum + (y - lum) * boost, 0.0, 1.0)

    return np.clip(y, 0.0, 1.0)


# Hand-tuned M97 winner (beats arctan/GHS on eye distinctness by killing the chroma
# speckle that obscured the cavities): vivid teal, sharp ~15px eyes, clean sky.
DEFAULTS = {"gain": 3.2, "pivot": 0.045, "b": 2.1, "shadow": 0.006,
            "denoise": 1.5, "cdenoise": 6.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.6}

# Sweep the three live levers: the eye-contrast knee (gain/b), the chroma cleanup
# (cdenoise -- the lever that made the eyes read), and the teal boost (cgain).
# DEFAULTS row first.  On a new target the agent re-tunes: pivot to the disk-rim
# brightness, dn_lo/dn_hi to the object's stretched-luminance scale, and the two
# denoise sigmas to the speckle-vs-feature scale; set denoise=cdenoise=0 to fall
# back to a pure GHS knee (the arctan-style behaviour) on clean/bright targets.
SWEEP = [
    {"gain": 3.2, "pivot": 0.045, "b": 2.1, "shadow": 0.006, "denoise": 1.5, "cdenoise": 6.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.6},
    {"gain": 2.8, "pivot": 0.045, "b": 2.0, "shadow": 0.006, "denoise": 1.5, "cdenoise": 6.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.5},
    {"gain": 3.6, "pivot": 0.045, "b": 2.2, "shadow": 0.006, "denoise": 1.3, "cdenoise": 6.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.6},
    {"gain": 3.2, "pivot": 0.045, "b": 2.1, "shadow": 0.006, "denoise": 1.2, "cdenoise": 4.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.6},
    {"gain": 3.2, "pivot": 0.045, "b": 2.1, "shadow": 0.006, "denoise": 1.8, "cdenoise": 9.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.7},
    {"gain": 3.2, "pivot": 0.045, "b": 2.1, "shadow": 0.006, "denoise": 1.5, "cdenoise": 6.0, "dn_lo": 0.04, "dn_hi": 0.12, "cgain": 1.9},
]
