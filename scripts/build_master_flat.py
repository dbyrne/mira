"""Build a standalone, viewable master flat from the 26 captured flats so
its structure (vignette + dust) can be eyeballed. Same recipe Siril uses
inside `mira stack --flats` (convert -> stack rej -norm=mul), just saved
out as a linear TIF + stretched PNG."""
from __future__ import annotations

import shutil
from pathlib import Path

from mira.siril import _outarg, _q, run_siril

FLATS = Path(r"C:\mira\captures\flats_g120_1s_20260519")
WORK = Path(r"C:\mira\.fltmp")
OUTDIR = Path(r"C:\mira\output\m51_ab")

WORK.mkdir(parents=True, exist_ok=True)
OUTDIR.mkdir(parents=True, exist_ok=True)

script = "\n".join([
    "requires 1.2.0",
    "setext fit",
    f"cd {_q(FLATS)}",
    f"convert flat -out={_outarg(WORK)}",
    f"cd {_q(WORK)}",
    "stack flat rej 3 3 -norm=mul -out=flat_stacked",
    "load flat_stacked",
    f"savetif32 {_q(Path('master_flat'))} -astro",
    "autostretch",
    f"savepng {_q(Path('master_flat_preview'))}",
    "close",
]) + "\n"

print("Building master flat from", len(list(FLATS.glob("*.fit*"))), "frames...")
log = run_siril(script, work_dir=WORK, timeout_s=600.0)
for name in ("master_flat.tif", "master_flat_preview.png"):
    src = WORK / name
    if src.exists():
        shutil.move(str(src), str(OUTDIR / name))
        print("wrote", OUTDIR / name)
    else:
        print("MISSING (siril did not produce):", name)
        print(log[-1500:])
