---
name: mira-nina-troubleshoot
description: Diagnose NINA Advanced API / Seestar S30 Pro connection problems — the full catalog of hard-won gotchas (ports, prefix, slew units, NoState, no-WCS, filter wheel). Use when NINA is unreachable, captures look wrong, or slews misbehave.
when_to_use: NINA not connecting, captures are wrong or stale, slew goes to the wrong place, API 404, filter or plate-solve issues
allowed-tools: [Bash, Read]
shell: powershell
---

# Mira NINA / Seestar troubleshooting catalog

Every item below is a real bug that cost time on this project. Check in
order.

## Connection
- **Port:** the Advanced API plugin listens on **1888**, sometimes
  **1889**. Probe both. `mira doctor` does this automatically.
- **URL prefix is `/v2/api`** (ninaAPI v2.x), NOT `/api/v2`. Wrong
  prefix = every call 404s. Base URL e.g. `http://localhost:1888`,
  client adds `/v2/api`.
- **Seestar app vs NINA:** opening the Seestar phone app can grab the
  device and drop NINA's connection. Keep the app closed during NINA
  sessions.

## Captures look wrong
- **`camera_state == "NoState"`** = degraded connection. It has returned
  **byte-identical "captures"** (stale image-history) — two exposures
  with identical Mean to 13 decimals is the tell. Reconnect the camera
  in NINA; do not trust frames until it reports a normal state. The
  capture/flats code already checks frame freshness (Filename must
  change) for this reason.
- **No WCS in saved FITS:** NINA API/snapshot captures save no celestial
  WCS even when image-history reports a solve. Photometry fails. Fix per
  frame, offline:
  `& "C:\Program Files\astap\astap_cli.exe" -f <file> -ra <RA_hours>
  -spd <Dec+90> -fov 0 -r 20 -z 2 -update`  (`-fov 0` essential).

## Slew goes to the wrong place
- **Slew RA/Dec are J2000 DEGREES.** But NINA mount/info *reports* RA in
  HOURS. Mixing them sends the scope ~15x off. Convert hours->deg (x15)
  for any slew input.
- **Center loop:** NINA's iterative plate-solve "Center" loops forever
  on this mount. Use blind slews (`center=False`). `mira capture`
  already does.

## Plate solve / scale
- **FocalLength = NaN:** the Seestar driver reports NaN focal length, so
  NINA can't compute plate-solve scale. Fix: NINA Options > Equipment >
  set Focal Length **150**, Ratio **5**.
- ASTAP needs a star database beside `astap_cli.exe` (D50/H18) or solves
  fail "No solution". `mira doctor` checks this.

## Filter wheel
- Positions on the S30 Pro wheel: **Dark** (opaque/blocking — not a flat
  target, auto-skipped by `mira flats`), **IR**, **LP** (the
  light-pollution filter; now API-visible, unlike older firmware).
- `mira capture --filter` / `mira tune --filter` confirm the wheel
  before shooting and abort if unconfirmed — trust that abort.

## First move when NINA seems broken
Run `mira doctor`. It encodes the port probe, NoState detection, filter
wheel, ASTAP, and darkness checks and prints the specific fix.
