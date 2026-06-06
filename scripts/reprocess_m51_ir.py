"""One-off A/B: reprocess M51 (all 1170 subs) applying the prebuilt IR
master flat via the real flat_master code path (Siril `calibrate
-flat=<master>`, no re-stack). Control is the existing no-flat
output/m51/m51_final.tif. NOTE: this is a config-MISMATCHED flat (IR
2026-05-19 g120 vs M51 2026-05-17 g200, pre-filter-wheel) — a
measurement, not an expected improvement."""
from pathlib import Path

from mira.siril_pipeline import run_siril_stack

res = run_siril_stack(
    lights_dir=Path("captures/m51_20260517"),
    out_path=Path("output/m51_ir_ab/m51_ir_flat.tif"),
    flat_master=Path("data/flats/IR_g120_20260519/master_flat.fit"),
    debayer=True,
    stretch=True,
)
print(f"OK wrote {res.output_path} from {res.n_input_frames} subs")
print(res.log_tail)
