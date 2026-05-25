# Rig workflow: homebase ↔ MeLE

This doc covers the operational split when running Mira against the
Esprit 120 EDX rig with a MeLE Quieter mini PC mounted to the pier. The
S30 Pro single-machine workflow continues to work; that profile
(`config/s30_pro_jc.yaml`) doesn't need this doc.

## The split

| Concern | Homebase (laptop/desktop) | MeLE Quieter 4C (rig) |
|---|---|---|
| NINA + ASCOM + ASTAP + plate-solver | — | ✓ (the rig brain) |
| `mira tonight` / `mira run` / `mira target` | ✓ (heavy net + caches) | — |
| `mira capture` / `mira flats` / `mira tune` | — | ✓ (drives NINA on localhost) |
| `mira stack` (Siril) | ✓ (RAM/disk heavy) | — |
| `mira submit` (photometry → AAVSO) | ✓ | — |
| `mira webapp` | ✓ (post-session review) | optional (phone view during session) |
| Siril Live Stacking GUI | ✓ (progress preview during session) | — |
| `data/cache/` (VSX/AAVSO/SIMBAD/Gaia ETL) | ✓ | — |
| Captures (write) | read-only mirror | ✓ |
| Master flats (build) | read-only mirror | ✓ |

**Slogan:** MeLE is the rig brain — no internet required during a session.
Homebase plans, processes, and submits.

## Data flow

Three streams cross the split:

1. **Plans rig-ward (homebase → MeLE).** After `mira tonight`, the
   `output/.../tonight/nina_targets.csv` and packet markdown need to land
   on the MeLE so NINA's Target Scheduler can import the queue.
2. **Captures homebase-ward (MeLE → homebase).** Each NINA session
   writes `captures/<target>_YYYYMMDD/*.fits` plus the
   `mira_capture.json` sidecar; both go back to homebase for `mira stack`
   and (variable-star nights only) `mira submit`.
3. **Master flats both-ways (MeLE → homebase).** `mira flats` runs on
   the MeLE and writes `data/flats/<filter>_g<gain>_<date>/master_flat.fit`.
   That tree mirrors to homebase so `mira stack --auto-flats` resolves
   the right master.

## Sync via Syncthing

Mira is sync-agnostic — it just needs paths it can read on each side.
The recommended mechanism is Syncthing (free, peer-to-peer, no cloud
quota, handles 30 GB narrowband sessions over LAN at wire speed).

### Install

1. Download Syncthing for Windows from <https://syncthing.net/downloads/>
   and install on **both** homebase and MeLE.
2. On each machine, open the web UI at <http://localhost:8384>.
3. Add the other device:
   - On homebase: Actions → Show ID, copy. On MeLE: Add Remote Device,
     paste the homebase ID, give it a name (e.g., "homebase"). Accept on
     homebase when the device-add prompt appears.
   - Vice versa for the MeLE → homebase direction.

### Folders to share

Configure three shared folders. Folder paths are examples — match
whatever your local layout is. The directions matter; misconfiguring
"Send & Receive" risks the MeLE accidentally pulling a stale schedule
back over fresh captures.

| Folder | MeLE role | Homebase role | Folder type |
|---|---|---|---|
| Captures (e.g. `C:\mira\captures\`) | Send only | Receive only | one-way: rig writes, homebase reads |
| Master flats (e.g. `C:\mira\data\flats\`) | Send only | Receive only | one-way: rig builds, homebase consumes |
| Plans (e.g. `C:\mira\output\esprit120_jc\tonight\`) | Receive only | Send only | one-way: homebase plans, rig imports |

Set folder type via Syncthing Web UI → Edit Folder → Folder Type. "Send
only" / "Receive only" prevents accidental mutation in the wrong
direction — closes a class of foot-guns.

### Verify the sync

After pairing, drop a marker file on one side and watch it appear on
the other within a few seconds (LAN) to a minute (over WAN). If it
doesn't, check the Syncthing web UI on both sides for unaccepted folder
shares or firewall warnings.

## Siril Live Stack on homebase

Siril's Live Stacking panel watches a directory and integrates each new
FITS as it appears. With Syncthing replicating the MeLE's captures dir
to homebase, you get a live preview indoors while the rig is capturing.

Lag is honest: a 50 MB FITS file mirrors over a typical home LAN in
~5–10 seconds, so the preview trails real-time by a frame or two. That's
fine for a *progress tracker* — Siril Live Stacking isn't your final
processing step; `mira stack` re-stacks the full set with proper
calibration at end-of-session.

### Setup

1. **Start `mira capture` on the MeLE.** It prints two paths at session
   start:
   ```
   Siril Live Stack (homebase):
     watch folder : C:\mira\captures\rrlyr_20260601
     master flat  : C:\mira\data\flats\V_g100_20260530\master_flat.fit  (matched V_g100_20260530)
   ```
2. **On homebase, open Siril** and choose `Image Processing → Live
   Stacking…` (the Siril menu path may shift across versions; the panel
   is labelled "Live Stacking").
3. **Paste the watch folder** (the Syncthing-mirrored homebase path
   that corresponds to that capture dir — same relative path under your
   shared folder root).
4. **Optional but recommended: paste the master flat** in the calibration
   section so the preview is flat-corrected.
5. **Start.** As Syncthing mirrors each FITS, Siril picks it up,
   registers, and integrates. SNR climbs in near real-time.

### What Siril Live Stack does NOT replace

- It's a *preview*; it doesn't replace `mira stack` at session end.
  `mira stack --auto-flats` runs Siril non-interactively against the full
  set with the same master flat resolution.
- It doesn't drive captures or modify NINA's behavior; it's read-only on
  the watch dir.
- For variable-star photometry, the source of truth is the
  per-frame `mira submit` photometry — not the integrated stack.

## Narrowband nights (out of Mira's queue)

Mira plans *variable stars*, not nebulae. Narrowband SHO sessions on
this rig don't go through `mira tonight` / `mira run`:

- Build a target list outside Mira (Telescopius, hand-curated NGC/IC/Sh2,
  imaging-target catalogs).
- Import directly into NINA's Target Scheduler on the MeLE.
- Use `mira capture --filter Ha` / `mira capture --filter OIII` / etc.
  to drive the actual integration once a target's selected. The
  `mira_capture.json` sidecar still gets written, but `mira submit` is
  skipped (narrowband isn't AAVSO-standard).
- `mira stack` still works for the final integration; Siril Live Stacking
  still works for the in-session preview.

The Esprit profile (`config/esprit120_jc.yaml`) is *only* for the
variable-star photometry use case. There's no equivalent "narrowband
plan" profile because there's no narrowband planning code in Mira today —
that may come later but is not on the immediate roadmap.

## Single-machine fallback (if Syncthing is down)

If sync is broken and you need to run a session anyway:

1. **Capture on the MeLE** as usual; FITS stay local.
2. After the session, copy `captures/<target>_<date>/` and any new
   `data/flats/<filter>_g<gain>_<date>/` to homebase via an external
   SSD or `scp`.
3. **Run `mira stack` / `mira submit` on homebase** against the local
   copy.

The capture sidecar (`mira_capture.json`) travels with the FITS dir, so
filter/gain resolution still works after a manual copy.

## See also

- `docs/nina_setup_esprit.md` — Esprit rig NINA configuration on the
  MeLE: equipment, plate-solver, plugins, filter-wheel canonical names.
- `docs/nina_setup.md` — Seestar S30 Pro NINA configuration (the
  single-machine setup).
- `docs/photometry.md` — `mira submit` end-to-end (runs on homebase).
- `CLAUDE.md` — the Rigs section near the top, for which profile to use
  for which night.
