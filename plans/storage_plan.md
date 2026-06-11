# Storage plan — capacity, redundancy, and the future-proof NAS

*Written 2026-06-11. Status: plan saved; nothing purchased yet. Decisions
already made by David: yes to a NAS, and **skip the 2-bay — buy bays to grow
into** (future-proof). Prices below were sane as of 2026-06; verify at
purchase.*

## The survey that prompted this (2026-06-11)

- Host disk: **1.01 TB free of 1.86 TB**.
- `captures/` **86.5 GB** (16 sessions, ~3.5 weeks of imaging) + `output/`
  **65.6 GB** (the gitignored `work/` processing intermediates rival the raw
  data) + `data/` 0.9 GB. Total data layer ≈ **153 GB**.
- Growth is lumpy: typical DSO night 1–5 GB, but one planetary-video session
  was 27 GB and one short-sub night 18 GB. With the Esprit era ramping
  (52 MB/frame on the ASI2600MM, dual-rig trip nights): plan on
  **100–200 GB/month while active** → runway ≈ **5–10 months**.
- **The bigger finding: zero redundancy.** The repo (~1 GB committed) is on
  GitHub; every raw sub, linear master, and work product exists ONLY on this
  one laptop disk. Priority #1 is a second copy, not more space.
- **Repo-health side-finding:** `docs/output_organization.md` claims keeper
  TIFFs are committed "via LFS" — **no `.gitattributes` exists; LFS was never
  configured.** Harmless so far (committed content ≈ 1 GB), addressed in
  Phase 1 below.

## Data tiers + retention rules

| Tier | What | Policy |
|---|---|---|
| **Distillate** | PNG keepers, PROCESSING logs, recipe scripts, `mira_capture.json` sidecars, catalogs/plans | In git forever (small, diffable provenance). Also the only tier worth cloud backup. |
| **Masters** | Linear stacks (`*_stack.fit`), per-filter masters, master flats | Keep hot until target is "done", then archive. Never delete — these are the reprocessing seeds (PixInsight trial, future tools). |
| **Raw lights** | `captures/<session>/` FITS | Cold gold: archive after the target's master is validated. Keep — re-stackable with better tools later (drizzle, BlurX). |
| **Rejected/intermediates** | `_rejected/` subdirs, `work/` iteration dumps, contact sheets, bakeoff variants | **Deletable after the keeper ships.** Rule: when PROCESSING_LOG records the final, `_rejected/` goes and `work/` keeps only masters. |
| **Video** | Planetary AVIs (27 GB Venus/Jupiter…) | Archive raw immediately after processing; keep derived stills/stacks hot. |
| **Husks** | 0-frame failed-session dirs | Delete on sight (`mira inventory` surfaces them). |

## Target architecture (3-2-1)

```
laptop SSD (copy 1)        — HOT: current targets' captures + active work/
   │  Syncthing / scheduled robocopy
   ▼
NAS, 4-bay mirrored (copy 2) — WARM/COLD: captures archive, masters, work
   │  scheduled USB job on the NAS          distillate only
   ▼                                            ▼
rotating external HDD (copy 3, offsite-ish)   Backblaze B2 (~$1/mo)
```

The MeLE also syncs into the NAS (always-on Syncthing node), so trip/session
captures archive themselves even when the laptop sleeps.

## Phases

### Phase 0 — retention pass ($0, this week)
Using `output/inventory/captures_inventory.md`:
1. Delete the 0-frame husks (`ic1396_20260608`, `ngc7000_20260605`).
2. Delete `_rejected/` dirs of validated-and-shipped sessions (**6.8 GB**).
3. Archive-or-delete decision on the Venus/Jupiter video (**27 GB**) once
   processed.
4. Prune `work/` intermediates of finished targets to masters-only
   (~30–40 GB across m51/m81/m13/m97/ngc6888 bakeoffs).
~**60–80 GB reclaimed**; retention rules above become the standing policy.
(All deletions are David's, per the house rule — `mira inventory` is the
shopping list.)

### Phase 1 — one external HDD as bridge + future offsite leg (~$150–230, this month)
One **12–20 TB external USB HDD**, nightly `robocopy /MIR` job for
`captures/` + masters. This kills the single-copy risk *now*, buys runway,
and is **not throwaway**: when the NAS lands, this same drive becomes the
rotating copy-3 (plugged into the NAS for scheduled USB backups, stored
away between rotations).

**Git/TIFF policy change at this point:** stop committing keeper TIFFs
(they live on the archive; regenerable from masters). PNGs + logs + scripts
stay in git. Fix the LFS claim in `docs/output_organization.md` — decision
is "no LFS needed" once TIFFs stop entering git.

### Phase 2 — the future-proof NAS (~$1,150–1,400 initial; when ready, no later than ~3 months before runway exhausts)

**Form factor decided: 4-bay minimum** (the 2-bay was rejected — replacing a
full mirror to grow is exactly the forklift we're avoiding).

Selection criteria, in priority order:
1. **Drive-agnostic** (the NINA-over-ASIAIR philosophy applies to storage).
   Note: Synology's 2025 drive-lock was *reversed* in DSM 7.3, so they're
   back on the menu — but the episode is a data point about the vendor.
2. **≥2.5GbE networking, 10GbE preferred** — reprocessing 50 GB of subs over
   1GbE is a 7-minute wait; over 10GbE it's seconds-to-a-minute territory.
3. **Container support** (Docker) — the NAS runs Syncthing as the always-on
   node; later maybe rclone→B2, maybe more.
4. Checksum-scrubbing filesystem (btrfs/ZFS) — bit-rot protection for FITS
   we intend to reprocess years from now.

Candidates (verify current models/prices at purchase):
- **UGREEN NASync DXP4800 Plus (~$700)** — front-runner: native **10GbE**,
  Intel Pentium Gold 8505 + 8 GB DDR5, drive-agnostic, Docker. Younger
  software ecosystem than Synology (fine for our use: SMB + Syncthing +
  scheduled backups).
- **Synology DS925+ (~$640)** — the polished-software alternative; weaker
  hardware, **no 10GbE path** (no PCIe). Choose only if appliance-grade
  software matters more than networking headroom.
- **DIY TrueNAS box** — maximum control/ZFS; costs build time. Fallback if
  neither appliance satisfies.

**Drive strategy (the actual future-proofing):** start **2× 16–20 TB
NAS-grade drives mirrored** (~$250–350 each → 16–20 TB usable ≈ several
years at projected rates), leave 2 bays empty. Grow later by adding a second
mirrored pair (or migrating to RAID5/SHR-equivalent). Buying 4 drives up
front buys capacity we won't touch for years at today's $/TB — don't.

Supporting bits: small **UPS** for the NAS (~$70); 2.5/10GbE USB adapter for
the laptop if/when transfer speed chafes (~$30–90).

### Phase 3 — cloud distillate (~$1/mo, after Phase 2)
Backblaze B2 (or equivalent) holding **masters + keepers + sidecars only**
(~50–100 GB): the irreplaceable distillate, synced from the NAS (rclone
container or native cloud-sync app). Bulk raws deliberately stay OFF the
cloud: days of home-upload, ~$72+/TB/yr forever, egress to restore — the
rotating external IS the raws' offsite story.

## mira integration (future tooling, post-Phase 2)

- `mira archive <session>` — move a captures session to the archive root,
  leave a stub (sidecar copy + pointer) behind.
- `mira inventory --archive-root <path>` — walk both roots so archived data
  stays queryable (the inventory tool was built for this extension).
- Ledger note: sidecar stubs must keep ledger aggregation honest (archived
  integration still counts toward budgets).

## Decision gates

| Trigger | Action |
|---|---|
| Now | Phase 0 cull + order Phase 1 drive |
| Phase 1 drive in service | Stop committing TIFFs; fix output_organization.md |
| Free space < 500 GB **or** dual-rig cadence sustained | Execute Phase 2 NAS purchase |
| NAS in service | Repoint Syncthing topology; Phase 3 B2; build `mira archive` |
| Yearly | Re-run the survey numbers; rotate copy-3 drive; restore-test one session from each copy |

**Budget summary:** Phase 1 ≈ $150–230 → Phase 2 ≈ $1,150–1,400 (chassis +
2 drives + UPS) → Phase 3 ≈ $12/yr. Total to fully built: ~$1,400–1,650
spread over the triggers.
