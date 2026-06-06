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
- **Capture runs but copies 0 frames (watch folder stays empty):**
  `nina_root` must match NINA's *actual current* save path. `mira capture`
  exposes/dithers fine (NINA saves somewhere) but globs `nina_root` for
  `*<exp>s*.fit*` to copy into `--dest`; a wrong root copies nothing,
  **silently**, while the loop still logs "captured" and the sidecar shows
  `captured:0/copied:0`. Verify-pointing + dither also skip (same wrong
  glob). Tell: exposure logs look normal but `--dest` (and your Siril live
  stack) stay empty. Two real save locations seen: `Documents` is
  OneDrive-redirected (Known Folder Move) so the path is
  `C:\Users\david\OneDrive\Documents\N.I.N.A` — NOT plain `Documents`; but
  the save path can also **drift to the run's cwd base** (`C:\mira\captures`
  observed 2026-06-01 after a TPPA/Target-Scheduler thrash). **The builtin
  default is NOT always right** — match NINA's real dir whichever way it
  points. Fix: `--nina-root "<NINA's real save dir>"` (or set
  `capture_defaults.nina_root`).
- **Frames named `Snapshot_<date>(N).fits` piling up in NINA's save dir:**
  these are the orphaned subs from the bug above — the API-capture path
  names frames `Snapshot_<date>` when `target_name` is blank (and
  `verify_pointing_<date>.fits` for the verify shot). They're real,
  dithered, on-target subs (each plate-solves; no in-header WCS, as usual).
  **Salvage without re-shooting:** copy them into a capture folder (renaming
  is unnecessary — solve/stack glob `*.fits`), then `mira solve` → `mira
  cull` → stack. Move them out *before* the next run, or NINA keeps
  appending `Snapshot(N+1)...` into the same dir and intermixes batches.

## Slew goes to the wrong place
- **Slew RA/Dec are J2000 DEGREES.** But NINA mount/info *reports* RA in
  HOURS. Mixing them sends the scope ~15x off. Convert hours->deg (x15)
  for any slew input.
- **Center loop:** NINA's iterative plate-solve "Center" loops forever
  on this mount. Use blind slews (`center=False`). `mira capture`
  already does.
- **Mis-points ~degrees after polar align (model not synced):** a blind
  slew can be ~4° off if the mount doesn't know its absolute pointing yet.
  **Do NOT fix it with a plate-solve sync** — the Seestar EQ sync is
  *additive*: syncing to the true position then slewing lands ~the same
  error the other way (verified 2026-05-30, M57). **Fix via the Seestar
  APP's reposition/align** (native plate-solve align); afterward a blind
  slew nails it (was 0.01° on M57). The app may grab the device and drop
  NINA's link — reconnect after.
- **Verify pointing by capturing 1 frame + ASTAP-solving it.** `mira
  capture --verify-pointing-deg` is coupled to `--platesolve-center`, so it
  is *skipped* under `--no-platesolve-center`; solve a frame yourself and
  compare CRVAL1/2 to nominal.

## Polar alignment (TPPA)
- **Three Point Polar Alignment crashes NINA → forces an S30 restart.**
  TPPA rotates the mount between points with ASCOM **`MoveAxis`** ("Moving
  axis by 3 ... until distance 10° traveled"). The Seestar driver wedges on
  ~the third move; afterward every property read (`Tracking`, `DeviceState`,
  `CCDTemperature`) throws `Dynamic client timeout` every ~20s forever, the
  UI thread blocks on the synchronous timeouts and NINA dies, and the device
  session is locked → only an S30 power-cycle clears it. (Same wedge as a
  hung `Connected`: Alpaca *reads* still return 200 fast; the *control*
  method blocks the full timeout.) **Fix:** don't let NINA `MoveAxis` the
  S30 — use the **Seestar app's native align**, or **TPPA Manual Mode** (you
  rotate between points, NINA only solves + computes). Connect scope **+
  both cameras first** or the log fills with `GET_USER_LOCATION fail:
  TELEPHOTO not connected`. Raising the ASCOM timeout does not help.

## Dithering
- **Target Scheduler dither silently no-ops** on the S30: TS logs `adding
  dither` per sub, but execution fails `Item: Dither - Guider not connected`
  every frame (no guide camera) → consecutive subs on the same pixels →
  walking noise. **Fix:** NINA → Equipment → **Guider → "Direct Guider" →
  Connect** (dithers by nudging the mount, no hardware). Watch the first few
  complete — Direct-Guider dither issues mount moves and this driver can
  wedge (see TPPA above). `mira capture` is unaffected: it dithers by
  **slewing the mount itself**, not via a guider — that's the dither path
  that always works.

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
