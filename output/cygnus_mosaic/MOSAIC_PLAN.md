# Cygnus mosaic plan — Crescent → IC 1318 (Sadr/Butterfly)

S30 Pro frame: 2.20°(RA) × 3.91°(Dec), LP dual-band, gain 80, 60s, EQ mode (fixed PA, N-up).

## Layout — best single-frame Butterfly + bridge (focused 3-panel)
Each **anchor centered** (best standalone, and no seam through a subject); the **bridge** ties them and its seams fall in empty Hα.

| panel | center RA | center Dec | status | overlap |
|---|---|---|---|---|
| 1 — Crescent | 302.98 | 38.35 | HAVE (~4.6h) | — |
| 2 — Butterfly / Sadr (best single frame) | **305.5** | **40.3** | **TONIGHT** | (gap to P1) |
| 3 — bridge | 304.2 | 39.3 | later | 45% to P1, 41% to P2 |

P1 and P2 don't touch (~0.4° gap); the bridge fills it. Butterfly frame (Sadr 53% across / 49% up) captures the bright central wings + LDN 889 dark lane; outer wingtips spill into the bridge (W) and a future E panel. **Extend later** (optional): a panel E of Sadr (~306.8) and/or toward the Tulip (~301.7, 299.9) — but the core showpiece is these 3.

## Tonight's command sequence

```powershell
# 0) Preflight
mira doctor --config config/s30_pro_jc.yaml

# 1) FLATS — fixes the ~12% vignetting (paper over aperture, ~few min). Sealed S30 =>
#    this one flat applies to panel 1's existing subs AND every future mosaic panel.
mira flats --filters LP --gain 80 --config config/s30_pro_jc.yaml

# 2) RE-STACK panel 1 with the flat (retroactive edge fix — no re-shooting lights)
mira stack --lights captures/ngc6888_combined --out output/ngc6888/ngc6888_stack.fit --debayer --auto-flats
#    (then re-run the finish pipeline — hand back to processing)

# 3) CAPTURE the Butterfly — best single frame, Sadr-centered (clears house ~00:30)
mira capture --ra 305.5 --dec 40.3 --exposure 60 --gain 80 --filter LP `
  --dest captures/ic1318_butterfly_20260602 --dither-every 2 `
  --alt-floor 30 --sun-max -12 --platesolve-center `
  --nina-root "C:\mira\captures" --park-at-end

# 4) PROCESS the Butterfly (flat auto-resolves via the LP/g80 sidecar)
mira solve --lights captures/ic1318_butterfly_20260602 --workers 8 --radius 10
mira cull  --lights captures/ic1318_butterfly_20260602 --from-fits
mira stack --lights captures/ic1318_butterfly_20260602 --out output/cygnus_mosaic/ic1318_butterfly_stack.fit --debayer --auto-flats
```

## Notes
- Keep the SAME orientation between panels (EQ mode holds PA — don't re-home/flip) so they register.
- Frames may orphan as `Snapshot_*` in base `captures/` again (NINA filename pattern) — same salvage path.
- Depth-match: bring panel 2 toward panel 1's ~4.6h over subsequent nights so the seam doesn't show a noise step.
- Stitching (later): per-panel bg-extract → register/blend across the overlap (Siril mosaic or APP).
