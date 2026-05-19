---
name: mira-field-setup
description: First-run setup of Mira on a clean Windows laptop for an observing trip — runs the bootstrap, walks the NINA/ASCOM/Seestar install, and verifies the rig with mira doctor. Use when setting up a new/blank machine for the S30 Pro.
when_to_use: new laptop, set up Mira, productionize, before a trip, clean install, nothing installed yet
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira field setup (clean Windows laptop -> ready to capture)

Goal: bare laptop -> verified rig. The full prose runbook is
`docs/FIELD_GUIDE.md`; this skill is the operator checklist.

## Hard truth first
NINA / ASCOM / the Seestar driver are **Windows GUI installs with no
headless or Docker path**. The bootstrap script installs only the native
Mira processing stack. NINA is always a manual, interactive step.

## Steps

1. **Clone the repo** and open it in Claude Code. Confirm
   `requirements-lock.txt` and `scripts/bootstrap.ps1` exist.

2. **Run the bootstrap** (installs Python venv + pinned deps, verifies
   Siril/ASTAP, optional GraXpert, ends with `mira doctor`):
   ```
   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
   ```
   Add `-WithFinishing` only if you want `mira finish` AI steps (heavy ML
   deps; it re-pins numpy==2.2.6 afterward — required, GraXpert breaks on
   numpy>=2.3). Re-runnable; every step is presence-checked.

3. **Install NINA stack manually** (do at home, needs internet + GUI):
   - ASCOM Platform 7+  https://ascom-standards.org/
   - NINA 3.x  https://nighttime-imaging.eu/
   - NINA plugins: **Advanced API** (port 1888) and **Target Scheduler**
   - Pair the S30 Pro over station-mode WiFi via ASCOM Alpaca
   - Fix the driver quirk: NINA Options > Equipment > set Focal Length
     **150** / Ratio **5** (Seestar reports FocalLength=NaN, which breaks
     plate-solve scale)
   - Create the OSC exposure template + a Mira Target Scheduler project
   - Detail: `docs/nina_setup.md`

4. **ASTAP star database** (large — download at home): ASTAP + a DB
   (D50/H18) from https://www.hnsky.org/astap.htm into the ASTAP folder.
   Without it offline solves fail "No solution". `mira doctor` checks
   this.

5. **Verify**: run the `mira-preflight` skill (or `mira doctor`). NINA
   warnings are expected until NINA is running with equipment connected.

6. **Dry run at home** (warms the HTTP cache, sanity-checks the queue
   path while you still have good internet):
   `mira tonight --config config/s30_pro_jc.yaml --hours 4`

## Done when
`mira doctor` is all PASS except NINA-related WARNs (resolved once NINA
is up), you've completed one end-to-end dry run at home, and the ASTAP
star DB is present. Then it's safe to leave.
