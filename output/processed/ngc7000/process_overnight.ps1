# NGC 7000 (North America) — unattended overnight reduction.
# Launched 2026-06-13 ~00:50 EDT. Waits for the live `mira capture` session to
# stop (S30 self-terminates at dawn, sun > -15 deg), then runs the verified
# pipeline: solve -> cull -> stack (OSC debayer + LP_g80 auto-flat) ->
# finish(emission HOO preset). Self-contained; all logs land in this folder.
$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$repo    = 'C:\mira'
$dest    = Join-Path $repo 'captures\ngc7000_20260613'
$outdir  = Join-Path $repo 'output\processed\ngc7000'
$astap   = 'C:\Program Files\astap\astap_cli.exe'
$starnet = 'C:\Users\david\tools\StarNet2\starnet2_win_2.5.1-0205_ORT_x64_cli\starnet2.exe'
$stack   = Join-Path $outdir 'NGC7000_stack_20260613.fit'
$keeper  = Join-Path $outdir 'NGC7000_emission_20260613.png'
$log     = Join-Path $outdir 'PROCESSING_LOG_ngc7000_20260613.md'

New-Item -ItemType Directory -Force -Path $outdir | Out-Null
Set-Location $repo

function Log($m) {
  $ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
  Add-Content -Path $log -Value "- $ts UTC -- $m"
}

"# NGC 7000 (North America) -- overnight processing log`n" | Set-Content $log -Encoding utf8
Log ("watcher started; mira at " + (Get-Command mira -ErrorAction SilentlyContinue).Source)

# --- Phase 1: wait for capture to finish (no new FITS for 6 min) ---------------
$deadline = (Get-Date).AddHours(9)   # absolute backstop
while ($true) {
  $frames = @(Get-ChildItem $dest -Filter *.fit* -ErrorAction SilentlyContinue)
  if ($frames.Count -ge 20) {
    $newest = ($frames | Sort-Object LastWriteTime | Select-Object -Last 1).LastWriteTime
    $quiet  = ((Get-Date) - $newest).TotalMinutes
    if ($quiet -ge 6) { Log ("capture done: {0} frames, last frame {1} min ago" -f $frames.Count, [int]$quiet); break }
  }
  if ((Get-Date) -gt $deadline) { Log ("backstop deadline hit; proceeding with {0} frames" -f $frames.Count); break }
  Start-Sleep -Seconds 60
}

$n0 = @(Get-ChildItem $dest -Filter *.fit*).Count
Log "=== begin reduction: $n0 light frames ==="

# --- Phase 2: plate-solve in place (so cull can reject failed-solve frames) -----
Log "solve: start"
& mira solve --lights $dest --config 'config\s30_pro_jc.yaml' --astap-cli $astap 2>&1 |
  Out-File (Join-Path $outdir 'solve.log') -Encoding utf8
Log "solve: exit $LASTEXITCODE"

# --- Phase 3: cull (FITS mode: failed-solve + HFR/stars/sky/roundness gates) ----
Log "cull: start"
& mira cull --lights $dest --from-fits 2>&1 |
  Out-File (Join-Path $outdir 'cull.log') -Encoding utf8
Log "cull: exit $LASTEXITCODE"
$kept = @(Get-ChildItem $dest -Filter *.fit*).Count
$rej  = @(Get-ChildItem (Join-Path $dest '_rejected') -Filter *.fit* -ErrorAction SilentlyContinue).Count
Log "cull: $kept kept / $rej rejected"

# --- Phase 4: stack (OSC debayer + auto-resolve LP_g80 master flat) -------------
Log "stack: start -> $stack"
& mira stack --lights $dest --out $stack --auto-flats --debayer 2>&1 |
  Out-File (Join-Path $outdir 'stack.log') -Encoding utf8
Log "stack: exit $LASTEXITCODE"
if (Test-Path $stack) { Log ("stack OK ({0} MB)" -f [int]((Get-Item $stack).Length/1MB)) }
else { Log "stack: NO OUTPUT -- see stack.log" }

# --- Phase 5: finish (verified emission HOO preset; GraXpert bg-extract on) ------
if (Test-Path $stack) {
  Log "finish(emission): start -> $keeper"
  & mira finish --input $stack --out $keeper --preset emission --starnet-exe $starnet --starnet-fallback 2>&1 |
    Out-File (Join-Path $outdir 'finish.log') -Encoding utf8
  Log "finish: exit $LASTEXITCODE"
  if (Test-Path $keeper) { Log "finish OK -> $keeper" } else { Log "finish: NO OUTPUT -- see finish.log" }
} else {
  Log "finish: SKIPPED (no stack)"
}

Log "=== DONE ==="
