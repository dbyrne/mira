# Nightly mirror of the irreplaceable data to the archive drive (storage
# plan Phase 1: IronWolf 16TB in the dual-bay dock).
#
# One-time setup (after formatting the drive, e.g. as E:):
#   powershell -File scripts\backup_mirror.ps1 -Setup -ArchiveRoot E:\
# creates the safety marker + registers a daily 10:00 scheduled task.
#
# Manual run:
#   powershell -File scripts\backup_mirror.ps1 -ArchiveRoot E:\
#
# Mirrors captures/, output/, data/ (minus data/cache) to
# <ArchiveRoot>\mira\<name> with robocopy /MIR. Two guards make /MIR safe:
#   1. The destination root must carry the .mira_archive marker (created by
#      -Setup) - we never /MIR onto some random disk.
#   2. A source that looks empty/missing is skipped - an unmounted or wiped
#      source can never delete the backup copy.
param(
    [Parameter(Mandatory = $true)][string]$ArchiveRoot,
    [switch]$Setup
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot          # repo root (scripts\..)
$dest = Join-Path $ArchiveRoot "mira"
$marker = Join-Path $dest ".mira_archive"
$logDir = Join-Path $dest "_logs"

if ($Setup) {
    New-Item -ItemType Directory -Force $dest | Out-Null
    New-Item -ItemType Directory -Force $logDir | Out-Null
    "mira archive root - created $(Get-Date -Format s). Do not remove this marker; backup_mirror.ps1 refuses to run without it." |
        Set-Content -Encoding utf8 $marker
    $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\backup_mirror.ps1`" -ArchiveRoot `"$ArchiveRoot`""
    schtasks /create /tn "Mira nightly archive mirror" /tr $cmd /sc daily /st 10:00 /f | Out-Null
    Write-Host "Setup complete: marker written, daily 10:00 task registered."
    Write-Host "Running the first mirror now (the initial ~150 GB takes a while)..."
}

if (-not (Test-Path $marker)) {
    Write-Error "No .mira_archive marker at $dest - is the archive drive mounted as $ArchiveRoot? Run -Setup once on the correct drive. Refusing to mirror."
    exit 1
}

$roots = @(
    @{ name = "captures"; src = Join-Path $repo "captures"; minItems = 5 },
    @{ name = "output";   src = Join-Path $repo "output";   minItems = 5 },
    @{ name = "data";     src = Join-Path $repo "data";     minItems = 1 }
)

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$failed = 0
foreach ($r in $roots) {
    if (-not (Test-Path $r.src) -or
        (Get-ChildItem $r.src -Force | Measure-Object).Count -lt $r.minItems) {
        Write-Warning "$($r.name): source missing or suspiciously empty - SKIPPED (backup copy preserved)."
        $failed++
        continue
    }
    $target = Join-Path $dest $r.name
    $log = Join-Path $logDir "$stamp`_$($r.name).log"
    $xd = @()
    if ($r.name -eq "data") { $xd = @("/XD", (Join-Path $r.src "cache")) }
    robocopy $r.src $target /MIR /R:2 /W:5 /NP /NDL /TEE /LOG:$log @xd | Out-Null
    # robocopy exit codes: 0-7 = success variants; >=8 = failure
    if ($LASTEXITCODE -ge 8) {
        Write-Warning "$($r.name): robocopy reported errors (exit $LASTEXITCODE) - see $log"
        $failed++
    } else {
        Write-Host "$($r.name): mirrored OK (exit $LASTEXITCODE, log $log)"
    }
}

# Keep the last 60 logs
Get-ChildItem $logDir -Filter *.log | Sort-Object Name -Descending |
    Select-Object -Skip 60 | Remove-Item -Force -ErrorAction SilentlyContinue

if ($failed -gt 0) { exit 1 }
Write-Host "Mirror complete $(Get-Date -Format s)"
