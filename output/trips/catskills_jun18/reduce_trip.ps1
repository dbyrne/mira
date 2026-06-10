# Catskills trip reduction (plan v2) — IC 1396 on the S30 + Iris LRGB on the
# Esprit 80. Run from the repo root (C:\mira) after the trip. Each block is
# independent; run top to bottom. Date stamps assume Sat Jun 13 — rename if the
# trip shifts. (The shelved Veil mosaic flow lives in reduce_veil.ps1.)

$ErrorActionPreference = "Stop"
$work = "output/trips/catskills_jun18"
$siril = "C:\Program Files\Siril\bin\siril-cli.exe"

# ============ A. S30 Pro — IC 1396 Elephant Trunk (single frame, LP) ============

# ---- A1. solve -> cull -> stack (debayer, LP_g80 auto-flats) ----
mira solve --lights "captures/ic1396_20260613" --workers 6
mira cull  --lights "captures/ic1396_20260613" --from-fits      # drops solve-failed + bad subs
mira stack --lights "captures/ic1396_20260613" --debayer --auto-flats `
           --out "$work/ic1396_stack.fit"

# ---- A2. PCC in Siril (bg-extract comes AFTER color cal — the ngc6888 lesson;
#          `mira finish` does the bg-extract internally) ----
#   Needs the VizieR catalog server; if it 503s, retry later or skip PCC and
#   hand-balance during finishing.
@"
requires 1.2.0
load ic1396_stack.fit
platesolve 324.78,57.5 -focal=163 -pixelsize=2.9
pcc
save ic1396_cc
"@ | Set-Content -Encoding utf8 "$work/cc_ic1396.ssf"
& $siril -d (Resolve-Path $work) -s (Resolve-Path "$work/cc_ic1396.ssf")

# ---- A3. Finish with the verified emission preset (contact-sheet crop on the
#          Trunk itself) ----
mira finish --input "$work/ic1396_cc.fit" `
  --out "$work/IC1396_elephant_trunk_20260613.png" --preset emission `
  --ra 324.05 --dec 57.49
#   If PCC was skipped: --input "$work/ic1396_stack.fit" and expect to hand-tune.

# ============ B. Esprit 80 ED — NGC 7023 Iris + vdB 141 (LRGB, mono) ============

# ---- B1. per-filter: solve -> cull -> stack (NO --debayer; auto-flats resolve
#          the on-site paper-mode masters via each dir's mira_capture.json /
#          the L_g100/R_g100/... masters from the dawn `mira flats` run) ----
foreach ($f in @("L","R","G","B")) {
    mira solve --lights "captures/iris_$f" --workers 6
    mira cull  --lights "captures/iris_$f" --from-fits
    mira stack --lights "captures/iris_$f" --auto-flats `
               --out "$work/iris_${f}_stack.fit"
}

# ---- B2. WCS-register R/G/B onto the L grid -> RGB cube ----
python "$work/combine_lrgb.py"                       # -> $work/iris_RGB.fit

# ---- B3. PCC the RGB cube (Esprit 80: 400mm, 3.76um) ----
@"
requires 1.2.0
load iris_RGB.fit
platesolve 317.25,68.20 -focal=400 -pixelsize=3.76
pcc
save iris_cc
"@ | Set-Content -Encoding utf8 "$work/cc_iris.ssf"
& $siril -d (Resolve-Path $work) -s (Resolve-Path "$work/cc_iris.ssf")

# ---- B4. Finish. First LRGB target through the preset pipeline -> pick the
#          render by EYE off the contact sheet (reflection nebula + dust is
#          probably faint-galaxy-deep territory, but don't assume). ----
mira finish --input "$work/iris_cc.fit" --out "$work/iris_sheet.png" `
  --contact-sheet --ra 315.40 --dec 68.163
#   then, e.g.:
# mira finish --input "$work/iris_cc.fit" `
#   --out "$work/Iris_Ghost_LRGB_20260613.png" --preset faint-galaxy-deep `
#   --ra 315.40 --dec 68.163

# ---- B5. Luminance blend (manual, the M51 all-lum pattern) ----
#   Blend iris_L_stack.fit as L over the finished RGB — follow
#   output/processed/m51/refinish_m51.py (stretch L with the same preset
#   machinery, then L-over-RGB in Lab/luminance space). First mono LRGB
#   through this kit; expect to iterate.

Write-Host "Done -> $work (IC1396 + Iris keepers)"
