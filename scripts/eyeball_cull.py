"""Ground-truth `mira cull --from-fits` on real M51 data: sample 5
random frames from each bucket (kept / metric-rejected / solve-failed),
autostretch each into a thumbnail, and tile into one montage so we can
actually look at whether the thresholds make sense.

Buckets are derived from the dir state post-cull:
  kept            = lights_dir/*.fit   (the 1042 survivors)
  rejected        = lights_dir/_rejected/*.fit
    solve-failed  -> rejected files that lack a WCS in the header
    metric-only   -> rejected files that DO have a WCS (solve passed,
                     but a pixel-metric threshold fired) — the more
                     informative bucket for threshold validation."""
from __future__ import annotations

import random
import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import FITSFixedWarning
from PIL import Image, ImageDraw

warnings.filterwarnings("ignore", category=FITSFixedWarning)

LIGHTS = Path(r"C:\mira\captures\m51_20260517")
REJ = LIGHTS / "_rejected"
OUT = Path(r"C:\mira\output\m51_culled")
OUT.mkdir(parents=True, exist_ok=True)
THUMB = (480, 320)
N_PER_ROW = 5
PAD = 6
LABEL_H = 22


def to_mono(p: Path) -> np.ndarray:
    a = fits.getdata(p).astype(np.float32)
    if a.ndim == 3:
        a = a.mean(axis=0 if a.shape[0] <= 4 else 2)
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    a = a[:h, :w]
    return (a[0::2, 0::2] + a[0::2, 1::2] + a[1::2, 0::2] + a[1::2, 1::2]) / 4.0


def has_wcs(p: Path) -> bool:
    with fits.open(p, memmap=False) as h:
        return "CTYPE1" in h[0].header


def render(p: Path) -> Image.Image:
    img = to_mono(p)
    _m, med, sig = sigma_clipped_stats(img, sigma=3.0)
    if sig <= 0:
        sig = 1.0
    lo, hi = med - sig, med + 18 * sig
    x = np.clip((img - lo) / (hi - lo), 0, 1)
    pil = Image.fromarray((x * 255).astype(np.uint8))
    pil.thumbnail(THUMB, Image.LANCZOS)
    return pil


def row(paths: list[Path], label: str) -> Image.Image:
    if not paths:
        return Image.new("L", (10, 10), 30)
    thumbs = [render(p) for p in paths]
    cell_w = max(t.width for t in thumbs)
    cell_h = max(t.height for t in thumbs)
    w = N_PER_ROW * cell_w + (N_PER_ROW + 1) * PAD
    h = cell_h + LABEL_H + 2 * PAD
    canvas = Image.new("L", (w, h), 20)
    d = ImageDraw.Draw(canvas)
    d.text((PAD, PAD), label, fill=240)
    x = PAD
    for t, p in zip(thumbs, paths):
        canvas.paste(t, (x, LABEL_H + PAD))
        d.text((x + 2, LABEL_H + PAD + cell_h - 14),
               p.name.split("__")[0][-8:], fill=255)
        x += cell_w + PAD
    return canvas


def main() -> int:
    if not REJ.exists():
        print("no _rejected/ dir — has cull run yet (without --dry-run)?")
        return 1

    kept = sorted(p for p in LIGHTS.iterdir()
                  if p.is_file() and p.suffix.lower().startswith(".fit"))
    rej = sorted(p for p in REJ.iterdir()
                 if p.is_file() and p.suffix.lower().startswith(".fit"))
    if not kept or not rej:
        print(f"empty bucket(s): kept={len(kept)} rej={len(rej)}")
        return 1

    solve_failed = [p for p in rej if not has_wcs(p)]
    metric_only = [p for p in rej if has_wcs(p)]
    print(f"buckets: kept={len(kept)} metric_only={len(metric_only)} "
          f"solve_failed={len(solve_failed)}")

    rng = random.Random(0)                                # reproducible sample
    s_kept = rng.sample(kept, min(N_PER_ROW, len(kept)))
    s_metric = rng.sample(metric_only, min(N_PER_ROW, len(metric_only)))
    s_solve = rng.sample(solve_failed, min(N_PER_ROW, len(solve_failed)))

    rows = [
        row(s_kept,   f"KEPT   (5 of {len(kept)})"),
        row(s_metric, f"METRIC-REJECTED  (5 of {len(metric_only)})  "
                     f"-- did solve, but failed a pixel-metric threshold"),
        row(s_solve,  f"SOLVE-FAILED  (5 of {len(solve_failed)})  "
                     f"-- no WCS"),
    ]
    W = max(r.width for r in rows)
    H = sum(r.height for r in rows) + 2 * PAD
    canvas = Image.new("L", (W, H), 0)
    y = 0
    for r in rows:
        canvas.paste(r, (0, y))
        y += r.height
    out = OUT / "cull_eyeball.png"
    canvas.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
