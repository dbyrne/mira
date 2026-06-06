"""Honest A/B: does the master flat flatten M51's background gradient?

Control  = output/m51/m51_final.tif      (all 1170 subs, NO flat, linear)
Test     = output/m51_ab/m51_flat.tif    (same 1170 subs, WITH master flat)

The defect a flat is supposed to fix on this urban data is the large-scale
vignette / light-pollution gradient. So the metric is the *relative*
background gradient (normalized by the image's own level, because Siril
stack normalization differs run-to-run — absolute ADU is not comparable).

Method: luminance, robustly mask stars/galaxy (keep pixels below the
per-image 60th percentile), tile into an 8x8 grid, take each tile's
sigma-clipped median, report:
  grad_ptp   = (max tile - min tile) / mean tile      (lower = flatter)
  grad_rms   = RMS of tile deviations / mean tile
  corner/ctr = mean of 4 corner tiles / 4 center tiles (1.0 = no vignette)
Also a plane-fit residual as a second view. Verdict is comparative and
states better/neutral/worse explicitly — no spin.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


def _load_lum(path: Path) -> np.ndarray:
    arr = None
    try:
        import tifffile
        arr = tifffile.imread(str(path)).astype(np.float64)
    except Exception:
        try:
            import imageio.v3 as iio
            arr = iio.imread(str(path)).astype(np.float64)
        except Exception:
            from PIL import Image
            arr = np.asarray(Image.open(path)).astype(np.float64)
    if arr.ndim == 3:
        arr = arr[..., :3].mean(axis=2)  # luminance
    return arr


def _sigclip_median(v: np.ndarray, n: int = 3, k: float = 3.0) -> float:
    v = v[np.isfinite(v)]
    for _ in range(n):
        if v.size < 8:
            break
        m, s = np.median(v), np.std(v)
        v = v[np.abs(v - m) <= k * s]
    return float(np.median(v)) if v.size else float("nan")


def metrics(path: Path) -> dict:
    img = _load_lum(path)
    finite = img[np.isfinite(img)]
    thr = np.percentile(finite, 60.0)  # drop galaxy/stars; keep background
    G = 8
    h, w = img.shape
    tiles = np.full((G, G), np.nan)
    for i in range(G):
        for j in range(G):
            cell = img[i * h // G:(i + 1) * h // G, j * w // G:(j + 1) * w // G]
            bg = cell[(cell < thr) & np.isfinite(cell)]
            if bg.size > 64:
                tiles[i, j] = _sigclip_median(bg)
    t = tiles[np.isfinite(tiles)]
    mean = float(np.mean(t))
    grad_ptp = (t.max() - t.min()) / mean
    grad_rms = float(np.std(t)) / mean
    # Fit a plane to all finite *background* tiles. The galaxy hollows out
    # the center tiles (NaN), so estimate corner-vs-center vignette from the
    # fitted plane prediction, not raw center tiles.
    ys, xs = np.where(np.isfinite(tiles))
    A = np.c_[xs, ys, np.ones_like(xs)]
    coef, *_ = np.linalg.lstsq(A, tiles[ys, xs], rcond=None)
    resid = tiles[ys, xs] - A @ coef

    def _plane(px: float, py: float) -> float:
        return float(coef[0] * px + coef[1] * py + coef[2])

    corners = np.mean([_plane(0, 0), _plane(G - 1, 0),
                       _plane(0, G - 1), _plane(G - 1, G - 1)])
    ctr = _plane((G - 1) / 2.0, (G - 1) / 2.0)
    return {
        "grad_ptp": grad_ptp,
        "grad_rms": grad_rms,
        "corner_over_center": float(corners / ctr) if ctr else float("nan"),
        "plane_resid_rms": float(np.std(resid) / mean),
        "level": mean,
    }


def main() -> int:
    ctrl = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/m51/m51_final.tif")
    test = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output/m51_ab/m51_flat.tif")
    for p in (ctrl, test):
        if not p.exists():
            print(f"MISSING: {p}")
            return 1
    c, t = metrics(ctrl), metrics(test)
    print(f"{'metric':<20}{'control(noflat)':>18}{'test(flat)':>14}{'change':>12}")
    keys = ["grad_ptp", "grad_rms", "plane_resid_rms"]
    better = 0
    for k in keys:
        d = (t[k] - c[k]) / c[k] * 100.0
        tag = "better" if d < -5 else ("worse" if d > 5 else "~same")
        better += int(d < -5) - int(d > 5)
        print(f"{k:<20}{c[k]:>18.5f}{t[k]:>14.5f}{d:>+10.1f}%  {tag}")
    print()
    print("Reading: grad_ptp/grad_rms = total large-scale background gradient")
    print("         plane_resid_rms   = NON-planar structure (dust motes, vignette ring)")
    print()
    dr = (t["plane_resid_rms"] - c["plane_resid_rms"]) / c["plane_resid_rms"] * 100.0
    dg = (t["grad_rms"] - c["grad_rms"]) / c["grad_rms"] * 100.0
    if dr < -10 and dg > 10:
        print("VERDICT: MIXED. The flat removes dust/vignette STRUCTURE "
              f"(plane_resid {dr:+.0f}%) but a config mismatch vs the M51 lights "
              f"ADDS a large-scale gradient (grad_rms {dg:+.0f}%). Net: NOT a win "
              "for THIS M51 data — the flat is structurally valid but was shot in "
              "a different optical state. Use it only on lights captured under the "
              "same config.")
    elif better >= 2:
        print("VERDICT: the master flat MEASURABLY FLATTENS M51. Keep it.")
    elif better <= -2:
        print("VERDICT: the flat makes M51 WORSE overall. Do NOT use it on this data.")
    else:
        print("VERDICT: NEUTRAL — no meaningful net change; M51's residual is "
              "sky-limited (urban LP), not vignette the flat can fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
