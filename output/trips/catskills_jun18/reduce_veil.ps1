# Veil 2-panel mosaic reduction — SHELVED (plan v2 moved the S30 to IC 1396;
# see reduce_trip.ps1). Kept runnable in case the Veil mosaic is revived.
# Run from the repo root (C:\mira) after the trip. Each block is independent;
# run top to bottom. Heavy steps (solve/stack/GraXpert) take minutes.

$ErrorActionPreference = "Stop"
$work = "output/trips/catskills_jun18"

# ---- 1. Per-panel: solve -> cull -> stack (debayer, LP_g80 auto-flats) ----
foreach ($p in @("veil_p1_west","veil_p2_east")) {
    mira solve --lights "captures/$p" --workers 6
    mira cull  --lights "captures/$p" --from-fits          # drops solve-failed + bad subs
    mira stack --lights "captures/$p" --debayer --auto-flats `
               --out "$work/${p}_stack.fit"                # LP_g80 master matches
}

# ---- 2. Mosaic the two panels into one WCS frame (reproject + coadd) ----
python "$work/mosaic_veil.py"                              # -> $work/veil_mosaic.fit

# ---- 3. GraXpert on the mosaic (bare-stem -output writes next to input) ----
#   first run downloads models. background-extraction then denoising.
graxpert -cmd background-extraction "$work/veil_mosaic.fit" -output veil_bg  -gpu false -cli
graxpert -cmd denoising            "$work/veil_bg.fits"     -output veil_dn  -gpu false -cli
#   (deconv usually unnecessary for the wide diffuse Veil; skip unless wanted.)

# ---- 4. Color-calibrate (PCC) in Siril ----
#   Needs the VizieR catalog server (was 503 on 2026-06-06; retry, or skip and
#   hand-balance in the stretch with --rgb). Center = Veil mosaic center.
$siril = "C:\Program Files\Siril\bin\siril-cli.exe"
@"
requires 1.2.0
load veil_dn.fits
platesolve 312.78,31.0 -focal=163 -pixelsize=2.9
pcc
save veil_cc
"@ | Set-Content -Encoding utf8 "$work/cc.ssf"
& $siril -d (Resolve-Path $work) -s (Resolve-Path "$work/cc.ssf")
#   If PCC fails -> use veil_dn.fits as the stretch input and add --rgb 1.0,0.85,1.05.

# ---- 5. Stretch (emission: asinh, hold the bright Eastern-Veil knots) ----
#   stretch_m27.py target coords only affect the SNR stat readout; fine as-is,
#   or copy + edit to the Veil center. White point 99.97+ so bright filament
#   knots don't clip (the M82 lesson).
Copy-Item output/processed/m27/stretch_m27.py "$work/stretch_veil.py" -Force
python "$work/stretch_veil.py" --in "$work/veil_cc.fit" `
  --out "$work/Veil_mosaic_20260618.png" --mode asinh --param 0.08 `
  --black 35 --white 99.97 --sat 1.7 --tiff
#   (if no veil_cc.fit, point --in at $work/veil_dn.fits and add: --rgb 1.0,0.85,1.05)

Write-Host "Done -> $work/Veil_mosaic_20260618.png/.tiff"
