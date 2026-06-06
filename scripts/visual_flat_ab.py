"""Apples-to-apples visual: M51 no-flat vs with-flat, IDENTICAL stretch.

Both are the same 1170 subs; only the flat differs. Stretch params are
derived ONCE from the control and applied to BOTH, so any visible change
is the flat's real effect, not a stretch artifact. No background
extraction (that would subtract gradients and mask the flat). A signed
difference map shows precisely what the flat redistributed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

CTRL = Path(r"C:\mira\output\m51\m51_final.tif")        # no flat
TEST = Path(r"C:\mira\output\m51_ir_ab\m51_ir_flat.tif")  # with IR master flat
OUT = Path(r"C:\mira\output\m51_ir_ab")


def load(p: Path) -> np.ndarray:
    a = tifffile.imread(str(p)).astype(np.float64)
    return a[..., :3] if a.ndim == 3 else np.stack([a] * 3, -1)


c = load(CTRL)
t = load(TEST)

# Match overall level (Siril stack norm differs run-to-run) so we compare
# STRUCTURE, not absolute scaling.
t *= np.median(c) / np.median(t)

# One asinh stretch, params from the control, applied to both.
lo = np.percentile(c, 30.0)
hi = np.percentile(c, 99.5)
beta = 0.02


def stretch(a: np.ndarray) -> Image.Image:
    x = np.clip((a - lo) / (hi - lo), 0, 1)
    x = np.arcsinh(x / beta) / np.arcsinh(1.0 / beta)
    return Image.fromarray((np.clip(x, 0, 1) * 255).astype(np.uint8))


ci, ti = stretch(c), stretch(t)
ci.save(OUT / "m51_noflat_match.png")
ti.save(OUT / "m51_flat_match.png")

# Side-by-side for direct eyeballing.
sbs = Image.new("RGB", (ci.width * 2 + 12, ci.height), "black")
sbs.paste(ci, (0, 0))
sbs.paste(ti, (ci.width + 12, 0))
sbs.save(OUT / "m51_ab_sidebyside.png")

# Signed difference (what the flat changed): luminance, gray=no change.
dl = c[..., :3].mean(-1) - t[..., :3].mean(-1)
s = np.percentile(np.abs(dl), 99.0) or 1.0
d = ((np.clip(dl / s, -1, 1) * 0.5 + 0.5) * 255).astype(np.uint8)
Image.fromarray(d).save(OUT / "m51_flat_diff.png")

print("wrote:")
for n in ("m51_ab_sidebyside.png", "m51_noflat_match.png",
          "m51_flat_match.png", "m51_flat_diff.png"):
    print(" ", OUT / n)
print(f"\nmatched levels: ctrl_med={np.median(c):.6g} test_med~={np.median(t):.6g}")
print(f"stretch: lo(p30)={lo:.6g} hi(p99.5)={hi:.6g} asinh beta={beta}")
print(f"diff scale (p99 abs-dlum)={s:.6g}  -> mid-gray = no change, "
      "bright/dark = flat raised/lowered that region")
