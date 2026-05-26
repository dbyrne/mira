# Monitoring console for the Esprit 120 — design plan

**Status:** plan only, not built. Drafted 2026-05-25, after the DSO Phase
2 ledger and the MeLE setup tooling shipped, before the rig's first real
session.

## TL;DR

A phone-friendly web view at `/monitor` that turns the existing
`/nina` dashboard into a real session console — current sub progress,
frame-quality timeline, guide RMS, temperature, ledger snapshot for the
active target, and explicit anomaly badges. LAN-first with a
Syncthing-mirrored snapshot fallback for the dark-site case. Anomaly
rules are configurable hard thresholds with a degrading-trend layer on
top; no ML. Built in 5 phases, each independently shippable.

## Goal

> You start a 6-hour Ha session, walk inside, and want to know — from
> the couch, the bed, or a hotel room — whether the rig is still
> producing usable frames, when the target will set, and whether
> anything has quietly broken.

The console answers that question on a single screen, updated every few
seconds, without needing to RDP to the MeLE or open Siril.

## Non-goals (explicit)

- **Not a NINA replacement.** NINA still runs the actual capture loop.
  Anything that needs to *control* the rig (abort, dither, slew, AF)
  stays in NINA. The console is read-only by design — same risk-surface
  reasoning we applied to the Hermes deployment question.
- **Not a real-time stack viewer.** Siril Live Stack already does that;
  it complements but isn't subsumed.
- **Not a multi-rig orchestrator.** Single rig, single session, single
  user. The S30 Pro path keeps using the existing `/nina` view as-is.
- **Not a photometry tool.** `/photometry` already covers the
  variable-star branch. The monitoring console is for *narrowband DSO
  sessions* where there are no comp stars and the question is "is the
  session healthy?", not "what's the magnitude?"

## The user, on a typical narrowband night

1. Run `mira dso plan` at homebase, pick the target, set up NINA's
   Target Scheduler with the canonical filter rotation.
2. Walk out to the pier, start the session in NINA, come back inside.
3. Open `https://mira-rig.local/monitor` (or whatever the MeLE's
   address is) on phone or laptop.
4. Every 5–10 seconds the screen tells you: which target + filter is
   being shot, sub N of M, HFR trend, guide RMS, camera temp delta,
   minutes of dark sky remaining on this target, ledger progress
   toward this target's budget.
5. If anything turns red, the screen tells you *what* and (where
   possible) *the most likely cause*.
6. Optionally: at session end, the page archives the night's stats
   as a small JSON next to the captures dir for offline review.

## Data sources

These already exist or are cheap to add — the console aggregates, it
doesn't generate new state.

| Source | Endpoint / path | What we read | Cadence |
|---|---|---|---|
| NINA Advanced API | `/sequence/state` | Sequence running, current target name | 5 s |
| NINA | `/equipment/camera/info` | CameraState, Temperature, SetPoint, CCDTemperature | 5 s |
| NINA | `/equipment/mount/info` | RA/Dec, AtPark, Slewing, Tracking, PierSide | 5 s |
| NINA | `/equipment/filterwheel/info` | SelectedFilter, IsMoving, AvailableFilters | 5 s |
| NINA | `/equipment/focuser/info` | Position, Temperature, IsMoving | 10 s |
| NINA | `/equipment/focuser/last-af` | Last AF time, HFR before/after, position | 30 s |
| NINA | `/image-history?all=true` | per-frame Stars/HFR/Max/Mean/Median/ExposureTime/Filter/Filename | 5 s |
| PHD2 (via bridge) | NINA `/equipment/guider/info` | Connected, IsGuiding, RMSError, LastError | 5 s |
| Pegasus PPB Gen2 | Via NINA Pegasus plugin or local serial | Voltages, dew heater duty cycles, current draw | 30 s |
| FITS sidecar | `<captures>/<session>/mira_capture.json` | Target name, filter, gain, exposure | once per session start |
| New FITS files | `<captures>/<session>/*.fit*` | header WCS (post plate-solve), DATE-OBS | each frame |
| DSO ledger | computed live by `ledger.walk_sidecars(captures_root)` | per-target / per-filter captured minutes | recomputed per request |
| DSO catalog | `data/dso_catalog/sho_targets.yaml` | target metadata + budget | once per process |
| Observability | `evaluate_observability_at_coords(ra, dec, site)` | minutes until target sets below floor tonight | per request |

The new code is small: read NINA endpoints we don't already poll
(focuser/last-af, guider/info, filterwheel/info), aggregate with the
ledger and catalog, render.

## UI sketch (mobile-first)

```
┌─ Esprit 120 // NGC 6888 // Ha 12/40 ─────────────┐
│                                                    │
│  [OK]   capturing                                  │
│         exp 300s  next in 2:14                     │
│         filter Ha            slot 6/7              │
│                                                    │
│  ─── frame quality (last 20 frames) ───            │
│  HFR  ▁▂▂▁▁▂▂▃▂▃▄▄▅▃ (trend ↑ 12%)               │
│  Stars 412…378 ✓                                   │
│  Mean ADU 1340 ✓                                   │
│                                                    │
│  ─── guiding ───                                   │
│  RMS  0.46" ✓     last dither 0:18 ago             │
│                                                    │
│  ─── camera ───                                    │
│  -10.0°C → -10.0°C ✓     cooler 41%                │
│                                                    │
│  ─── tonight ───                                   │
│  target sets in 2h 47m above 40°                   │
│  Ha 60/600m   OIII 0/900m   SII 0/540m             │
│  ETA budget complete (Ha): 4h 30m at current pace  │
│                                                    │
│  ─── events ───                                    │
│  21:18  AF run     HFR 3.1 → 2.4                   │
│  20:55  centered   Δ 0.4'                          │
│  20:50  filter Ha  confirmed                       │
│                                                    │
└────────────────────────────────────────────────────┘
```

Key principles for the layout:

- **Top line is the answer.** Target, filter, sub N of M, status badge.
  Whatever the user sees first, they can act on first.
- **No charts library.** Inline sparklines via Unicode block chars
  (`▁▂▃▄▅▆▇█`) or tiny SVGs. Saves a JS dep, renders on every device,
  copy-pastes into Slack/text if the user wants to share status.
- **Sections collapse on small screens.** The base.html flex column
  works on iPhone-width without horizontal scroll.
- **One color per state.** Green = healthy, amber = degrading, red =
  broken. Match the red-light dark-mode CSS the existing templates use
  so the page is observatory-friendly.

### Drill-downs (separate URLs, navigable from top)

- `/monitor/frames` — full image-history table, sortable, with quick
  filters (last 50 / last filter / last target).
- `/monitor/guiding` — guide RMS over the whole session, dither marks,
  calibration timestamp.
- `/monitor/temp` — camera and ambient temp curves; cooler-duty curve.
- `/monitor/events` — autofocus runs (with HFR before/after), dither
  events, plate-solves, errors. Replaces the small "events" footer.
- `/monitor/ledger` — DSO ledger view filtered to the active target's
  budget. (Effectively `mira dso status "NGC 6888"` rendered to HTML.)

## Architecture

Three runtime configurations, ranked by preference. The console code is
the same in all three; only the data source changes.

### Mode A: LAN-direct (preferred at home)

Homebase webapp polls the MeLE's NINA Advanced API over the LAN at
`http://mira-rig.local:1888`. This is how the existing `/nina` route
already works when you set `--nina-url` to a remote MeLE rather than
localhost. Sub-second latency to fresh state.

```
homebase webapp ──HTTP──> MeLE:1888 (NINA Advanced API)
       │
       └──reads──> Syncthing-mirrored captures dir (for ledger + FITS headers)
```

This is the default and what Phase 1 ships.

### Mode B: On-rig only (when you're physically at the pier)

Same code, point browser at `http://localhost:1888` via local webapp on
the MeLE. Useful for testing during setup; not the primary deployment.

### Mode C: Snapshot fallback (dark-site, no LAN)

When homebase can't reach the MeLE — different network, hotel Wi-Fi,
captive portal — the MeLE writes a `monitor_snapshot.json` to a
Syncthing-mirrored path every N seconds. Homebase reads it. Lag becomes
the Syncthing lag (5–30 s on a typical LAN, longer over WAN), which is
fine for a monitoring view, not for a guide-RMS spike alert.

```
MeLE NINA poller ──writes──> captures/_monitor/snapshot.json
                                       │
                               (Syncthing mirrors)
                                       │
                                       v
                            homebase reads snapshot.json
```

The snapshot writer is a small `mira monitor-snapshot` daemon
process — same shape as a watchdog you'd write anyway. Reuses the
existing NinaClient code; it's just running on the MeLE side instead
of the homebase side.

### Mode selection logic

The `/monitor` route tries Mode A first (HTTP to configured NINA URL,
timeout 2 s). On failure, it falls back to Mode C (read the latest
snapshot.json, display its `generated_utc` so the user knows the data
isn't live). The UI is honest about which mode it's in — a small
"snapshot 23 s ago" badge at the top.

## Anomaly detection

Two layers, both simple. No ML, no learned baselines beyond the current
session's first N frames.

### Hard thresholds (configurable)

| Signal | Default trigger | Severity |
|---|---|---|
| HFR > 1.5× session baseline (median of first 10 frames) | sustained 3 frames | amber |
| HFR > 2.0× session baseline | sustained 3 frames | red |
| Star count drop > 50% from baseline | sustained 3 frames | amber |
| Star count drop > 80% from baseline | 1 frame | red |
| Guide RMS > 1.5″ | sustained 30 s | amber |
| Guide RMS > 3.0″ | 1 sample | red |
| Camera temp deviation from setpoint > 2 °C | sustained 60 s | amber |
| No new frame in `2 × exposure_s + 60s` | 1 occurrence | red ("session stalled") |
| Filter wheel reports a non-canonical name mid-session | 1 occurrence | red |
| Plate solve failure | 3 consecutive | amber |
| Target within 20 minutes of setting below floor | continuous | amber ("plan filter switch") |
| Target below floor | continuous | red ("rig is shooting through worse air") |

These live in a small `monitor_config.py` so the user can edit
thresholds without touching code logic. Default values are the
"alert before things actually go wrong" sweet spot — they should rarely
false-positive on a good night.

### Trend layer

For HFR specifically: compute a linear slope over the last 20 frames.
If slope is monotonic-up and projects > 1.5× baseline within 10 more
frames, flag amber even before the hard threshold trips. Same for star
count slope, but inverted (monotonic-down).

This catches the dew-on-objective / focus-drift / cloud-band-coming
failure modes earlier than the hard threshold would. Doesn't replace
the hard threshold — both fire independently.

### Anti-flap

Each anomaly has a 5-frame hysteresis to clear: a flag that fires must
stay clear for 5 frames before un-firing. Prevents the badge from
strobing red-green-red-green on borderline conditions.

## Code layout (new and changed)

```
src/mira/webapp/
├── routes.py            existing — add @app.route("/monitor"),
│                        @app.route("/monitor/partial"),
│                        @app.route("/monitor/frames"), ...
├── nina_client.py       existing — add focuser_info(), last_af(),
│                        guider_info() methods (small additions to
│                        the existing pattern; tolerate-and-degrade)
└── templates/
    ├── monitor.html         new — base + the polled section
    ├── monitor_partial.html  new — what HTMX swaps in every 5 s
    ├── monitor_frames.html  new — drill-down
    ├── monitor_guiding.html new — drill-down
    └── monitor_events.html  new — drill-down

src/mira/monitor/             new package, mirrors src/mira/dso/
├── __init__.py
├── snapshot.py             pure aggregator: NinaClient + ledger + catalog → Snapshot dataclass
├── anomaly.py              pure functions: detect_anomalies(snapshot, history, config) → list[Anomaly]
└── snapshot_writer.py      Mode C daemon: writes snapshot.json to disk

src/mira/cli.py             new subcommand `mira monitor-snapshot --captures-root ... [--interval 5]`
                            for Mode C deployment on the MeLE

tests/test_monitor_snapshot.py  unit tests with mocked NinaClient
tests/test_monitor_anomaly.py   pure logic, lots of cases
```

Total estimate: ~600 LOC of code + ~400 LOC of templates + ~500 LOC of
tests across the whole project. Each phase below is a fraction.

## Phases (each independently shippable)

### Phase 1 — Read-only `/monitor` (LAN, basic)

Smallest useful slice. Reuses existing NinaClient.status() + adds three
new client methods (focuser/last-af, guider/info, filterwheel/info
detail). Renders the top-card view (target, filter, frame N/M, last
HFR, guide RMS, camera temp, equipment connect states). HTMX partial
every 5 s.

No anomaly logic. No drill-downs. No ledger integration yet. Just turns
the current `/nina` page into the new `/monitor` view with more state
exposed.

About 200 LOC. One sitting.

### Phase 2 — Frame quality timeline + sparklines

Add the per-frame HFR / stars / mean-ADU sparkline section. Render
inline Unicode sparklines (no JS library). Add `/monitor/frames`
drill-down that lists the last 50 frames with their stats and the
filename so the user can pop them open in DS9 if needed.

Adds `src/mira/monitor/snapshot.py` as the pure aggregator so the
template doesn't reach into NinaClient directly.

About 250 LOC.

### Phase 3 — DSO ledger integration

Tie the active target's NINA-reported `target_name` to the catalog and
show live "captured / budget / ETA-to-budget" for the current filter
plus the other filters in the same session. Same ledger logic as
`mira dso status`, just rendered live every 5 s.

Adds "target sets in HH:MM" derived from
`evaluate_observability_at_coords` applied to *now* until the
configured site's altitude floor.

About 150 LOC.

### Phase 4 — Anomaly detection + badges

Wire the hard thresholds + trend layer + hysteresis. Anomalies render
as colored badges next to the relevant section and as a top-of-page
summary. No notifications yet — visual only.

About 200 LOC, mostly the anomaly rules table and tests.

### Phase 5 — Mode C snapshot fallback

`mira monitor-snapshot` daemon on the MeLE writes
`<captures_root>/_monitor/snapshot.json` every N seconds. The
`/monitor` route falls back to reading the snapshot when the NINA HTTP
endpoint is unreachable, with a visible "snapshot 23 s ago" banner.

About 200 LOC. This is the dark-site enabler — without it the console
is home-LAN only.

### Phase 6 (stretch) — Push notifications

A small notifier with a pluggable backend: e-mail (smtplib), webhook
(POST to a URL — works for Slack/Discord incoming-webhooks/ntfy.sh),
or just printf to the webapp's `_webapp.log` for now. Triggered by
red-severity anomalies. Default off; opt-in via config.

About 150 LOC.

## Tests strategy

Pure functions first — anomaly detection has the most interesting
logic. Mocked NinaClient for snapshot aggregation. Synthetic
image-history dicts for trend detection. Webapp routes get smoke tests
that hit the partial with a mocked client and assert structural
content (no flask test-client over a real NINA).

About 25 tests total across the phases. Each phase's PR adds its own
tests.

## Risks and unknowns

1. **PHD2 → NINA bridge state freshness.** NINA's `/equipment/guider/info`
   shape may vary across plugin versions. Worth grep-checking against
   what the live plugin returns on first connect. Fallback: poll PHD2's
   own JSON event server on port 4400 directly if NINA's bridge is
   noisy.
2. **Sparkline accessibility.** Unicode blocks (`▁▂▃▄▅▆▇█`) render
   differently across phone fonts. May need to fall back to tiny inline
   SVGs if iPhone Safari munges them. Test on actual phone before
   committing to the format.
3. **Snapshot file contention.** If the MeLE writer process crashes
   mid-write, homebase could read a half-written JSON. Mitigation:
   write to `snapshot.json.tmp` then `os.replace` atomically. Standard
   pattern.
4. **NINA "current target name" is sometimes blank** when the sequence
   is between targets / paused / running an autofocus interlude. The
   UI should show "between targets" rather than rendering an empty
   header — would feel broken otherwise.
5. **HTMX polling cost on the MeLE.** Every 5 s × (5 endpoint hits per
   refresh) = 60 reqs/minute against NINA. Should be fine but worth
   confirming the plugin doesn't bottleneck on its own request loop.
   Phase 1 should log request latency for the first session to
   establish a baseline.
6. **"Tonight" semantics for a multi-night target.** If the user is
   shooting NGC 6888 across multiple nights, the ledger correctly
   accumulates — but the "ETA to budget complete" at the current pace
   only makes sense within tonight's window. Cap the ETA display at
   "tonight's remaining dark sky" with a "+N hr next night" suffix
   when the budget exceeds tonight.

## Open questions worth deferring (not blocking Phase 1)

- **Multi-target session view.** If a Target Scheduler sequence cycles
  through 3 targets in one night (less common for narrowband but
  possible), should the console show a queue of upcoming targets?
  Probably yes, but Phase 1 ships with single-active-target only.
- **Historic session replay.** Could the console render a past session
  from the captures dir + ledger as if it were live? Useful for
  after-action review. Out of scope for phases 1–5; would be Phase 7.
- **Mosaic progress.** A mosaic target captured in 4 panels needs
  per-panel progress, not a single bar. Out of scope; deal with when
  the user actually starts a mosaic.

## What to build first (Phase 1 scope, concrete)

If I were starting tomorrow, in order:

1. Add `focuser_info()`, `last_af()`, `guider_info()` methods to
   `NinaClient` — small additions following the same try/degrade
   pattern as the existing methods. Add tests with synthetic responses.
2. Create `src/mira/monitor/snapshot.py` with a `MonitorSnapshot`
   dataclass and a `build_snapshot(nina_client, catalog, ledger)`
   function that aggregates everything. Pure; no I/O of its own beyond
   the client calls.
3. Add `/monitor` and `/monitor/partial` routes to `webapp/routes.py`.
   `/monitor` renders `monitor.html` (base + HTMX-polled section);
   `/monitor/partial` renders `monitor_partial.html` with the
   snapshot data.
4. Write `monitor.html` + `monitor_partial.html`. Reuse the red-light
   dark-mode CSS from base.html. No charts, no JS beyond HTMX.
5. Run on the actual MeLE during the first real session. Iterate on
   what's missing.

The "iterate on what's missing" step is the important one — this whole
plan is ahead of any real session data. Some of the anomaly thresholds
and the exact sparkline metrics will probably move once we see a real
session's noise floor.

## How this fits the existing architecture

- Reuses `webapp/nina_client.py` (already the canonical NINA gateway).
- Reuses `dso/ledger.py` (already aggregating sidecars).
- Reuses `dso/catalog.py` (already the canonical target list).
- Reuses `observability.evaluate_observability_at_coords` for the
  "target sets in" calculation.
- Reuses Flask + HTMX patterns from existing `/nina`, `/photometry`,
  `/finish` routes.

Nothing about this plan requires new infrastructure. It's gluing
existing pieces into one screen the user can read at 3 a.m.

## See also

- `docs/rig_workflow.md` — homebase↔MeLE split this plan is consistent with.
- `docs/dso_planner.md` — the ledger this plan integrates with.
- `docs/nina_setup_esprit.md` — equipment + Advanced API plugin that
  this plan reads.
