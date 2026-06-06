"""One sustainable burst of flat captures (hand-held tablet flat source).

Why bursts: a hand-held tablet held flush over the S30 Pro aperture is a
*valid* flat source (proven 2026-05-19: 0.3s/gain120 -> ~28k ADU, 0 stars,
1-2% repeatable) but you cannot hold it steady for a continuous 25-frame
(~75s) series. So capture ~6 at a time, validate each, copy only good frames
into the flats dir, and accumulate across bursts. Idempotent: re-running
just adds more good frames (dedupe by NINA filename).

Usage:  python scripts/flat_burst.py [n]      (default n=6)
Stop when the printed running total reaches ~18-20.
"""
from __future__ import annotations

import glob
import os
import shutil
import sys
import time
from pathlib import Path

from mira.webapp.nina_client import NinaClient

NINA_ROOT = r"C:\Users\david\OneDrive\Documents\N.I.N.A"
DEST = Path(r"C:\mira\captures\flats_g120_1s_20260519")
EXP, GAIN = 1.0, 120
MED_LO, MED_HI, MAX_STARS = 20000.0, 40000.0, 3

def _newest_fits(after_mtime: float) -> str | None:
    cands = [
        p for p in glob.glob(os.path.join(NINA_ROOT, "**", "*.fit*"), recursive=True)
        if os.path.getmtime(p) > after_mtime
    ]
    return max(cands, key=os.path.getmtime) if cands else None

def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    DEST.mkdir(parents=True, exist_ok=True)
    c = NinaClient("http://localhost:1888")
    have = len(list(DEST.glob("*.fit*")))
    print(f"flats dir already holds {have} good frame(s). Capturing burst of {n}...",
          flush=True)
    good = 0
    for i in range(1, n + 1):
        t0 = time.time()
        h = c.image_history()
        before = h[-1].get("Filename") if h else None
        c.wait_camera_idle(20)
        c.capture(duration=EXP, gain=GAIN, save=True, solve=False,
                  target_name="FLAT", timeout_s=40)
        time.sleep(2.3)
        h2 = c.image_history()
        last = h2[-1] if h2 else {}
        fn = last.get("Filename")
        fresh = fn is not None and fn != before
        md, st = last.get("Median"), last.get("Stars")
        try:
            ok = fresh and MED_LO <= float(md) <= MED_HI and int(st) <= MAX_STARS
        except (TypeError, ValueError):
            ok = False
        copied = ""
        if ok:
            src = _newest_fits(t0 - 1.0)
            if src and not (DEST / os.path.basename(src)).exists():
                try:
                    shutil.copy2(src, DEST)
                    good += 1
                    copied = f" -> {os.path.basename(src)}"
                except OSError as e:
                    ok, copied = False, f" (copy failed: {e})"
            elif not src:
                ok, copied = False, " (no new FITS found on disk)"
        print(f"  {i}/{n}  fresh={fresh} Median={md} Stars={st}  "
              f"{'OK' if ok else 'REJECT'}{copied}", flush=True)
    total = len(list(DEST.glob("*.fit*")))
    print(f"BURST DONE: +{good} good this burst. flats dir total = {total}/~18 "
          f"({DEST})", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
