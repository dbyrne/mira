<#
.SYNOPSIS
  Mira trip-laptop bootstrap. Idempotent: re-run any time; every step is
  presence-checked before it acts.

.DESCRIPTION
  Installs the NATIVE Mira processing stack on a clean Windows laptop:
  Python 3.11 venv + pinned deps, Siril 1.4.3 (official installer; winget's
  Free-Astro.Siril is stuck at 1.2.6), ASTAP CLI (via SourceForge), optionally
  GraXpert and the D50 star DB, then runs `mira doctor`.

  It deliberately DOES NOT install NINA / ASCOM / the Seestar driver:
  those are interactive Windows GUI installs with plugins and pairing,
  and there is no headless/Docker path for them. The script prints the
  exact NINA checklist; docs/FIELD_GUIDE.md is the full runbook.

.PARAMETER WithFinishing
  Also install `mira[finishing]` (GraXpert). Heavy ML deps; only `mira
  finish` AI steps need it. numpy is re-pinned to 2.2.6 afterwards
  because GraXpert can drag in an incompatible numpy.

.PARAMETER WithStarDB
  Also download + install the ASTAP D50 star database (~870 MB). Without
  it ASTAP solves return "No solution". Skip on metered connections.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -WithFinishing
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -WithFinishing -WithStarDB
#>
[CmdletBinding()]
param(
    [switch]$WithFinishing,
    [switch]$WithStarDB
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot   # scripts/ -> repo root
Set-Location $repo

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [warn] $msg" -ForegroundColor Yellow }
function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Add-ToUserPath($dir) {
    # Idempotent: append $dir to the user PATH if it isn't already there. Affects
    # future shells only; the current process PATH is updated in-place too so the
    # rest of this script can invoke the binary by name.
    $cur = [Environment]::GetEnvironmentVariable("Path","User")
    if ($cur -notlike "*$dir*") {
        [Environment]::SetEnvironmentVariable("Path", "$cur;$dir", "User")
        Ok "added $dir to user PATH (new shells only)"
    }
    if ($env:Path -notlike "*$dir*") { $env:Path = "$env:Path;$dir" }
}

function Get-SourceForgeFile($projectPath, $outFile) {
    # SourceForge's /download URL serves an HTML interstitial with a meta-refresh
    # to a one-time mirror-token URL. Fetch the interstitial, extract the token,
    # download the real file. $projectPath is e.g. "windows_installer/astap_setup.exe".
    $interstitial = "https://sourceforge.net/projects/astap-program/files/$projectPath/download"
    $page = Invoke-WebRequest -Uri $interstitial -UseBasicParsing -UserAgent "Mozilla/5.0"
    if ($page.Content -notmatch 'content="\d+;\s*url=([^"]+)"') {
        throw "SourceForge interstitial parse failed for $projectPath"
    }
    $real = $matches[1] -replace '&amp;','&'
    Invoke-WebRequest -Uri $real -OutFile $outFile -UseBasicParsing -MaximumRedirection 10 -UserAgent "Mozilla/5.0"
    $bytes = [System.IO.File]::ReadAllBytes($outFile) | Select-Object -First 2
    if (-not ($bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A)) {
        throw "Downloaded $outFile is not a PE binary (got an HTML page?)"
    }
}

Say "Mira bootstrap (repo: $repo)"
Write-Host "    This installs the native Mira stack. It does NOT install" -ForegroundColor DarkGray
Write-Host "    NINA/ASCOM/Seestar driver (interactive GUI; see runbook)." -ForegroundColor DarkGray

# --- 1. Python 3.11+ ------------------------------------------------------
Say "Python 3.11+"
$python = $null
foreach ($cand in @("py -3.11", "python", "python3")) {
    $exe, $exeArgs = $cand.Split(" ", 2)
    if (Have $exe) {
        try {
            $v = & $exe $exeArgs --version 2>&1
            if ($v -match "Python 3\.(1[1-9]|[2-9]\d)") { $python = $cand; break }
        } catch { }
    }
}
if (-not $python) {
    if (Have "winget") {
        Say "installing Python 3.11 via winget"
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        $python = "py -3.11"
    } else {
        throw "Python 3.11+ not found and winget unavailable. Install from https://www.python.org/downloads/ (check 'Add to PATH'), then re-run."
    }
}
$pyExe, $pyArgs = $python.Split(" ", 2)
Ok "using '$python'"

# --- 2. venv --------------------------------------------------------------
Say ".venv"
$venv = Join-Path $repo ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $pyExe $pyArgs -m venv $venv
    Ok "created .venv"
} else {
    Ok ".venv already present"
}
$vpy = Join-Path $venv "Scripts\python.exe"

# --- 3. Mira + pinned deps ------------------------------------------------
Say "pinned dependencies"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $repo "requirements-lock.txt") --quiet
& $vpy -m pip install -e $repo --no-deps --quiet
Ok "mira + locked deps installed"

if ($WithFinishing) {
    Say "mira[finishing] (GraXpert)"
    & $vpy -m pip install "graxpert" --quiet
    # GraXpert can pull an incompatible numpy; re-pin (mira doctor enforces).
    & $vpy -m pip install "numpy==2.2.6" --quiet
    Ok "GraXpert installed; numpy re-pinned to 2.2.6"
}

# --- 4. Siril (stack/finish) ---------------------------------------------
# winget's `Free-Astro.Siril` is stuck on 1.2.6; mira generates scripts against
# 1.4.3, so install directly from the official installer instead.
Say "Siril 1.4.3 (needed for mira stack / finish)"
$siril = $null
if ($env:MIRA_SIRIL_CLI -and (Test-Path $env:MIRA_SIRIL_CLI)) { $siril = $env:MIRA_SIRIL_CLI }
elseif (Have "siril-cli") { $siril = (Get-Command siril-cli).Source }
elseif (Test-Path "C:\Program Files\Siril\bin\siril-cli.exe") { $siril = "C:\Program Files\Siril\bin\siril-cli.exe" }
if (-not $siril) {
    try {
        $url = "https://free-astro.org/download/siril-1.4.3-ucrt64-setup.exe"
        $tmp = Join-Path $env:TEMP "siril-1.4.3-setup.exe"
        Say "downloading Siril 1.4.3 (~100 MB)"
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
        $p = Start-Process -FilePath $tmp -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "Siril installer exited $($p.ExitCode)" }
    } catch { Warn "Siril auto-install failed: $_" }
    if (Test-Path "C:\Program Files\Siril\bin\siril-cli.exe") { $siril = "C:\Program Files\Siril\bin\siril-cli.exe" }
}
if ($siril) {
    Add-ToUserPath (Split-Path $siril)
    $sv = (& $siril -v 2>&1 | Out-String)
    if ($sv -match "1\.4\.3") { Ok "Siril 1.4.3 ($siril)" }
    else { Warn "Siril found ($siril) but not the tested 1.4.3 - stacking may still work. If it fails, install 1.4.3 from https://siril.org" }
} else {
    Warn "Siril not found. Install from https://siril.org and add bin\ to PATH, or set MIRA_SIRIL_CLI. Only mira stack/finish need it."
}

# --- 5. ASTAP (offline plate solve) --------------------------------------
# Binary is small (~6 MB) and standalone - safe to auto-install. The star DB
# (D50, ~870 MB) is gated behind -WithStarDB because of size.
Say "ASTAP (offline WCS for NINA captures -> photometry/submit)"
$astap = $null
if ($env:MIRA_ASTAP_CLI -and (Test-Path $env:MIRA_ASTAP_CLI)) { $astap = $env:MIRA_ASTAP_CLI }
elseif (Have "astap_cli") { $astap = (Get-Command astap_cli).Source }
elseif (Test-Path "C:\Program Files\astap\astap_cli.exe") { $astap = "C:\Program Files\astap\astap_cli.exe" }
if (-not $astap) {
    try {
        $tmp = Join-Path $env:TEMP "astap_setup.exe"
        Say "downloading ASTAP installer"
        Get-SourceForgeFile "windows_installer/astap_setup.exe" $tmp
        $p = Start-Process -FilePath $tmp -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "ASTAP installer exited $($p.ExitCode)" }
    } catch { Warn "ASTAP auto-install failed: $_" }
    if (Test-Path "C:\Program Files\astap\astap_cli.exe") { $astap = "C:\Program Files\astap\astap_cli.exe" }
}
if ($astap) {
    Add-ToUserPath (Split-Path $astap)
    $astapDir = Split-Path $astap
    $db = @(Get-ChildItem -Path $astapDir -Filter "*.290" -ErrorAction SilentlyContinue) +
          @(Get-ChildItem -Path $astapDir -Filter "*.1476" -ErrorAction SilentlyContinue)
    if ($db.Count -eq 0 -and $WithStarDB) {
        try {
            $tmp = Join-Path $env:TEMP "d50_star_database.exe"
            Say "downloading D50 star database (~870 MB - go get coffee)"
            Get-SourceForgeFile "star_databases/d50_star_database.exe" $tmp
            $p = Start-Process -FilePath $tmp -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
            if ($p.ExitCode -ne 0) { throw "D50 installer exited $($p.ExitCode)" }
            $db = @(Get-ChildItem -Path $astapDir -Filter "*.290" -ErrorAction SilentlyContinue) +
                  @(Get-ChildItem -Path $astapDir -Filter "*.1476" -ErrorAction SilentlyContinue)
        } catch { Warn "D50 auto-install failed: $_" }
    }
    if ($db.Count -gt 0) { Ok "ASTAP + star DB ($astap)" }
    else { Warn "ASTAP found but NO star database beside it. Re-run with -WithStarDB, or grab D50/H18 from https://www.hnsky.org/astap.htm - solves fail 'No solution' without it." }
} else {
    Warn "ASTAP not found. Install + a star database (D50/H18) from https://www.hnsky.org/astap.htm ; set MIRA_ASTAP_CLI or add to PATH. Required for WCS on NINA captures (submit)."
}

# --- 6. NINA / ASCOM (NOT automated - interactive) -----------------------
Say "NINA / ASCOM / Seestar (manual - no headless/Docker path exists)"
@(
  "  These are interactive Windows GUI installs. Do them once, at home:",
  "   1. ASCOM Platform 7+        https://ascom-standards.org/",
  "   2. NINA 3.x                 https://nighttime-imaging.eu/",
  "   3. NINA plugins: 'Advanced API' (port 1888) + 'Target Scheduler'",
  "   4. Pair Seestar S30 Pro (station-mode WiFi) in NINA via ASCOM Alpaca",
  "   5. Fix the FocalLength=NaN driver quirk: NINA Options > Equipment >",
  "      set Focal Length 150 / Ratio 5 so plate-solve scale is sane",
  "   6. Create the OSC exposure template + Mira project (see runbook)",
  "  Full step-by-step: docs/FIELD_GUIDE.md and docs/nina_setup.md"
) | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }

# --- 7. mira doctor -------------------------------------------------------
Say "running 'mira doctor' (preflight)"
Write-Host ""
& $vpy -m mira doctor --config (Join-Path $repo "config\s30_pro_jc.yaml")
$doctorExit = $LASTEXITCODE

Write-Host ""
Say "bootstrap complete"
Write-Host "    Activate the venv for future commands:" -ForegroundColor DarkGray
Write-Host "      .\.venv\Scripts\Activate.ps1" -ForegroundColor DarkGray
Write-Host "    Then:  mira doctor   (re-run any time before a session)" -ForegroundColor DarkGray
if ($doctorExit -ne 0) {
    Warn "doctor reported hard failures above - resolve them before the trip."
} else {
    Ok "doctor: rig usable (NINA warnings are expected until NINA is running)"
}
exit $doctorExit
