# M81 deep co-stack: June 5 (m81_20260605, 147 kept) + June 13 night
# (m81_20260613) -> one frame-level integration -> faint-galaxy-deep finish.
# Both sessions are IR / gain-80 / 60s on the sealed S30, so they co-register.
# FLATLESS by design: no IR_g80 master exists and the June 5 keeper was made
# flatless (GraXpert bg-extraction in finish removes vignetting/gradient).
# Tonight's run had intermittent dither/settle trailing -> cull it on its OWN
# median first, then combine with the already-culled June 5 set.
$ErrorActionPreference='Continue'; $ProgressPreference='SilentlyContinue'
$repo='C:\mira'; Set-Location $repo
$astap='C:\Program Files\astap\astap_cli.exe'
$starnet='C:\Users\david\tools\StarNet2\starnet2_win_2.5.1-0205_ORT_x64_cli\starnet2.exe'
$tonight='C:\mira\captures\m81_20260613'
$june5='C:\mira\captures\m81_20260605'
$outdir='C:\mira\output\processed\m81'
$work='C:\mira\output\processed\m81\work\combined_20260613'
$stack="$outdir\M81_group_combined_20260613.fit"
$keeper="$outdir\M81_group_combined_20260613.png"
$log="$outdir\PROCESSING_LOG_combined_20260613.md"

function Log($m){ $ts=(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'); Add-Content $log "- $ts UTC -- $m" }
"# M81 deep co-stack (June 5 + June 13) -- processing log`n" | Set-Content $log -Encoding utf8
Log ("start; mira at " + (Get-Command mira -ErrorAction SilentlyContinue).Source)

# --- Phase 1: solve tonight in place (June 5 already carries WCS) -----------
Log "solve(tonight): start"
& mira solve --lights $tonight --config 'config\s30_pro_jc.yaml' --astap-cli $astap 2>&1 |
  Out-File "$outdir\combined_solve.log" -Encoding utf8
Log "solve(tonight): exit $LASTEXITCODE"

# --- Phase 2: cull tonight on its own median (catches the trailing) ---------
Log "cull(tonight): start"
& mira cull --lights $tonight --from-fits 2>&1 | Out-File "$outdir\combined_cull.log" -Encoding utf8
Log "cull(tonight): exit $LASTEXITCODE"
$t_kept=@(Get-ChildItem $tonight -Filter *.fit*).Count
$t_rej=@(Get-ChildItem "$tonight\_rejected" -Filter *.fit* -ErrorAction SilentlyContinue).Count
Log "cull(tonight): $t_kept kept / $t_rej rejected"

# --- Phase 3: build the combined lights dir (June 5 kept + tonight kept) ----
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $work | Out-Null
Copy-Item "$june5\*.fit*" $work
$j5=@(Get-ChildItem $june5 -Filter *.fit*).Count
Copy-Item "$tonight\*.fit*" $work
$total=@(Get-ChildItem $work -Filter *.fit*).Count
Log "combined: $j5 (June5) + $t_kept (tonight) = $total frames in work dir"

# --- Phase 4: stack flatless (OSC debayer; bg-extraction in finish) ---------
Log "stack: start -> $stack"
& mira stack --lights $work --out $stack --debayer 2>&1 | Out-File "$outdir\combined_stack.log" -Encoding utf8
Log "stack: exit $LASTEXITCODE"
if (Test-Path $stack) { Log ("stack OK ({0} MB)" -f [int]((Get-Item $stack).Length/1MB)) } else { Log "stack: NO OUTPUT -- see combined_stack.log" }

# --- Phase 5: finish (verified faint-galaxy-deep preset; bg-extract on) -----
if (Test-Path $stack) {
  Log "finish(faint-galaxy-deep): start -> $keeper"
  & mira finish --input $stack --out $keeper --preset faint-galaxy-deep --starnet-exe $starnet --starnet-fallback 2>&1 |
    Out-File "$outdir\combined_finish.log" -Encoding utf8
  Log "finish: exit $LASTEXITCODE"
  if (Test-Path $keeper) { Log "finish OK -> $keeper" } else { Log "finish: NO OUTPUT -- see combined_finish.log" }
} else { Log "finish: SKIPPED (no stack)" }
Log "=== DONE ==="
