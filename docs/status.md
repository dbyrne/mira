# `mira status` — live night-progress

`mira status` answers **"how is *tonight* going, right now?"** for a single
active capture session — the live equivalent of the checks you'd otherwise
hand-run while babysitting a run. It reads the frames on disk (plus the
capture sidecar) and renders a one-screen health/progress dashboard.

```powershell
mira status --dest captures/ngc7000_20260614                    # one-shot, frames-on-disk
mira status --dest captures/ngc7000_20260614 --watch 30         # refresh in place (top-like)
mira status --dest captures/x --nina-url http://localhost:1888  # + LIVE device state
mira status --dest captures/x --json                            # machine-readable (one-shot)
```

It is **zero-config**: site geometry (lat/lon, altitude floor, dawn cap) and
the dither cadence are read from the capture's `mira_capture.json` sidecar.
`--config` / `--horizon` are optional and only add the local
horizon-obstruction check.

## ⚠️ Not the same as `mira dso status`

This is the single most important thing to keep straight:

| | `mira status` | `mira dso/emission/galaxies status` |
|---|---|---|
| **Question** | "How is the session running *now*?" | "What have we *imaged*, across all nights?" |
| **Scope** | One active capture dir, this session | The whole `captures/` ledger, all sessions |
| **Source** | Frames on disk + sidecar (+ NINA later) | `mira_capture.json` sidecars under `captures/` |
| **Time** | Live / in-flight | Cumulative history |
| **Answers** | focus, clouds, cadence, dawn clock, stalls | per-target / per-filter integration vs budget |

They are deliberately separate commands. `mira status` is a **monitor**;
the path-namespaced `... status` commands are the **integration ledger**.

## What it shows

- **Capture** — frames, integration (min), cadence + efficiency, dither cadence.
- **Quality** (last N frames) — HFR, star count + range, sky background, roundness.
- **Flags** — the headline: a **transparency-gated** read of the recent frames:
  - **clouds** — if the star count is *swinging* frame-to-frame, the sky is the
    variable, not the focuser. Flagged as "transparency varying," and crucially
    it **suppresses the focus flag** (see below).
  - **soft focus** — HFR elevated *and the sky is steady* (so it's really focus).
  - **trailing** — stars consistently elongated (dither-settle / tracking).
- **Sky** — current altitude/azimuth, clear of the horizon obstruction, minutes
  until it sets (drops below the floor) and until dawn, moon alt/illumination.
- **Health** — capturing vs idle/done, age of the last frame (stall detection).

### The transparency gate (why it exists)

On 2026-06-14 a cloudy NGC 7000 run *looked* exactly like a defocus — soft HFR,
crashed star count, autofocus that wouldn't converge — and an hour was wasted
chasing focus. It was clouds. `mira status` encodes the discriminator: **a
swinging star count means transparency, not focus**, so it flags clouds and
explicitly does *not* cry defocus. (See the `seestar-clouds-vs-focus` note and
`plans/focus_strategy.md` once written — the same gate informs autofocus
scheduling: don't AF into clouds.)

## Phasing

- **Phase 1 (done)** — frames-on-disk. Works on any capture dir, live or
  post-hoc, with no rig connection. Built on `fits_stats.compute_frame_quality`
  (the same per-frame metrics `mira cull --from-fits` uses) + `observability`
  for the sky clock.
- **Phase 2 (done)** — `--nina-url` overlays **live device-state** (camera
  state/temp, mount tracking/slew/pier, focuser position + last-AF, guider RMS,
  filter wheel) onto the disk snapshot via `merge_nina_devices`. The disk path
  keeps ownership of frame quality / sky (measured from the FITS — better than
  NINA's image-history HFR); NINA contributes the devices + event log.
  Fail-soft: an unreachable NINA leaves the disk snapshot intact (mode stays
  `disk`, with the error noted). `--json` emits the snapshot (datetimes → ISO)
  for scripting and to feed the webapp `/monitor` from the same engine.

## Implementation

`src/mira/monitor/disk_snapshot.py` (`build_snapshot_from_disk`) builds a
`MonitorSnapshot` (the same frozen aggregate the webapp `/monitor` uses) from
disk; `src/mira/monitor/render.py` (`render_status`) renders it to the
terminal. Frame timestamps come from the FITS `DATE-OBS` header (robust to file
mtime being clobbered by in-place solving), so cadence stays accurate post-hoc.
