# NGC 7000 deep co-stack: last night's 51 sharp subs (20260613) + tonight's 70
# cloud-survivors (20260614, HFR ~7"). Both LP/gain-80/60s, same plate-solved
# pointing -> co-register. ~121 subs. LP_g80 master flat exists, so --auto-flats.
$ErrorActionPreference = 'Continue'; $ProgressPreference = 'SilentlyContinue'
Set-Location C:\mira
$lastnight = 'captures\ngc7000_20260613'
$tonight   = 'captures\ngc7000_20260614'
$work      = 'output\processed\ngc7000\work\combined_20260614'
$stack     = 'output\processed\ngc7000\NGC7000_combined_20260614.fit'
$keeper    = 'output\processed\ngc7000\NGC7000_combined_20260614.png'
$starnet   = 'C:\Users\david\tools\StarNet2\starnet2_win_2.5.1-0205_ORT_x64_cli\starnet2.exe'
$log       = 'output\processed\ngc7000\PROCESSING_LOG_combined_20260614.md'

function Log($m) { $ts = (Get-Date).ToUniversalTime().ToString('HH:mm:ss'); Add-Content $log "- $ts UTC -- $m" }
"# NGC 7000 deep co-stack (last night 51 + tonight 70) -- log`n" | Set-Content $log -Encoding utf8

if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $work | Out-Null
Copy-Item "$lastnight\*.fit*" $work
$a = @(Get-ChildItem $work -Filter *.fit*).Count
Copy-Item "$tonight\*.fit*" $work
$b = @(Get-ChildItem $work -Filter *.fit*).Count
Copy-Item "$tonight\mira_capture.json" $work   # for --auto-flats (LP_g80)
Log "combined: $a (last night) + $($b-$a) (tonight) = $b frames"

Log "stack: start (auto-flats LP_g80, debayer)"
& mira stack --lights $work --out $stack --auto-flats --debayer 2>&1 |
  Out-File output\processed\ngc7000\combined_stack.log -Encoding utf8
Log "stack: exit $LASTEXITCODE"
if (Test-Path $stack) { Log ("stack OK ({0} MB)" -f [int]((Get-Item $stack).Length/1MB)) } else { Log "stack: NO OUTPUT"; Log '=== DONE ==='; exit 1 }

Log "finish: start (denoised non-preset; 121 min is moderate depth)"
& mira finish --input $stack --out $keeper --no-deconv --starnet-exe $starnet --starnet-fallback 2>&1 |
  Out-File output\processed\ngc7000\combined_finish.log -Encoding utf8
Log "finish: exit $LASTEXITCODE"
if (Test-Path $keeper) { Log "finish OK -> $keeper" } else { Log "finish: NO OUTPUT" }
Log "=== DONE ==="
