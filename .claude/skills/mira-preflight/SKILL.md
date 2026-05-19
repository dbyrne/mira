---
name: mira-preflight
description: Run and interpret `mira doctor` before an observing session — explains every PASS/WARN/FAIL and the exact fix. Use before capturing or whenever something seems off with the rig.
when_to_use: before a session, is the rig ready, run doctor, troubleshooting environment or deps or NINA reachability
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira preflight (`mira doctor`)

Run it:
```
mira doctor --config config/s30_pro_jc.yaml
```
`--nina-url` (also probes :1889), `--captures-root` to point at the
capture drive. Exit code is non-zero only on a hard **FAIL** (WARN does
not fail the exit, so bootstrap can proceed past optional-tool warnings).

## Reading the report

- **Python / Core dependencies** FAIL -> the venv is wrong. Re-run
  `scripts\bootstrap.ps1`, or `pip install -r requirements-lock.txt`.
- **numpy GraXpert-compatible** WARN -> numpy>=2.3. Capture/photometry
  are fine; only `mira finish` breaks. `pip install numpy==2.2.6`.
- **Siril** WARN (version != 1.4.3) -> script generation is verified
  against 1.4.3; stacking may still work, pin 1.4.3 if it fails.
- **ASTAP** WARN -> no `astap_cli` or no star DB. Photometry/submit need
  it for WCS (NINA captures save no WCS). Install ASTAP + a star DB;
  set `MIRA_ASTAP_CLI` or PATH.
- **NINA Advanced API** WARN -> NINA not running / plugin off / wrong
  port. Start NINA, enable Advanced API, connect equipment. doctor
  probes 1888 then 1889. If it says `camera_state=NoState` that is a
  *degraded connection* (has produced stale, byte-identical frames) —
  reconnect the camera in NINA before trusting any capture.
- **Filter wheel** WARN -> connect the S30 Pro wheel if you want
  per-filter flats / `mira capture --filter`.
- **Darkness tonight** FAIL -> no astronomical darkness in 24h at the
  site (high-latitude season, e.g. Fairbanks May–Aug). Change site/date.
- **Capture disk space** WARN -> a deep dithered run is ~19 GB. Free
  space or point `--captures-root` elsewhere.

## Rule
Do not start a multi-hour capture with any FAIL. NINA-related WARNs are
the only ones acceptable to proceed past (resolve by starting NINA).
