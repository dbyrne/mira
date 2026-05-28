# Esprit 120 EDX preflight (no OTA yet)

Components are arriving piecemeal; the OTA is the long pole. Everything
in this checklist can ship *without* the Esprit 120 itself, so first-light
night is plug-and-play instead of a 6-hour driver-install scramble.

Track progress by ticking the boxes. Sections are roughly ordered by
dependency, but Phase 4 (dark library) can run overnight in parallel
with everything else.

Cross-refs: [`nina_setup_esprit.md`](nina_setup_esprit.md) is the
authoritative setup doc; this is the time-boxed preflight subset. Rig
↔ homebase split lives in [`rig_workflow.md`](rig_workflow.md).

## Inventory you should have

- [ ] MeLE Quieter 4C (rig brain)
- [ ] ZWO AM7 mount + tripod
- [ ] ZWO ASI2600MM Pro main cam
- [ ] ZWO EFW 7×36mm filter wheel
- [ ] Antlia LRGB-V + Antlia 3nm Ha/OIII/SII filters
- [ ] ZWO 30mm f/5 guidescope + ASI220MM Mini guide cam
- [ ] Pegasus FocusCube 3 + PocketPowerbox Gen2
- [ ] WandererAstro Cover V4-EC 190mm flat panel
- [ ] Esprit 120 EDX OTA — **NOT YET** (this is what we're waiting on)

## Phase 1: MeLE software bootstrap (~½ day)

The biggest pre-OTA landmine. Do this once, on the MeLE, while you're
sitting at your desk.

- [ ] Power up the MeLE, connect to homebase WiFi
- [ ] Enable Remote Desktop on the MeLE; verify you can drive it from
      homebase
- [ ] `git clone` Mira on the MeLE; run `scripts\bootstrap.ps1 -Rig esprit`
- [ ] Install ASCOM Platform 7+ — <https://ascom-standards.org/>
- [ ] Install NINA 3.x — <https://nighttime-imaging.eu/>
- [ ] NINA plugins (Plugins → Available): Advanced API, Target Scheduler,
      Three Point Polar Alignment, Touch'N'Stars
- [ ] ZWO ASCOM drivers (camera + AM5/AM3 driver covers the AM7 + EFW)
- [ ] Pegasus Unity (FocusCube 3 + PocketPowerbox Gen2)
- [ ] **WandererAstro ASCOM driver** for the Cover V4-EC —
      <https://www.wandererastro.com/en/col.jsp?id=104>
- [ ] `mira doctor --config config\esprit120_jc.yaml`
      — expect PASS on Python/deps/Siril/ASTAP, WARN on NINA reachable
      until NINA is open. After Phase 2, almost everything should PASS
      except `Darkness tonight` (depends on time).

## Phase 2: Bench-connect every device (~2 days, spread out)

Each device sits on your desk, powered up, with USB to the MeLE. The
test is *"does NINA's Equipment tab show connected state and read back
sensible values?"* — no OTA needed.

### Mount (AM7)

- [ ] Power the AM7, USB to MeLE
- [ ] NINA → Telescope → ZWO AM5/AM3 ASCOM Driver → Connect
- [ ] Test a small dummy slew (e.g. +5° in RA) — driver should report
      "Slewing" then settle. No need to actually point at anything.
- [ ] Park / Unpark cycle, verify `AtPark` flips correctly
- [ ] Set tracking sidereal → Stopped → sidereal again

### Camera (ASI2600MM Pro)

- [ ] Cap the camera nose (the same cover you'll use for darks)
- [ ] NINA → Camera → ZWO ASI Camera → Connect
- [ ] Set cooling target **−10 °C** (summer JC) or **−15 °C** (cooler).
      Wait for actual temp to settle within 1 °C of target — confirms
      the TEC + Peltier are healthy.
- [ ] Run a 1 s test exposure; verify `IsExposing` cycles and a FITS
      lands in the configured Image File Path.

### Filter wheel (EFW 7×36mm)

- [ ] Load all 7 filters (or as many as you have). Keep one slot blank
      / opaque if you want a darks-only position; label it `Dark`.
- [ ] NINA → Filter Wheel → ZWO EFW ASCOM Driver → Connect
- [ ] **Critical:** Rename every position EXACTLY to the canonical set
      `Ha`, `OIII`, `SII`, `L`, `R`, `G`, `B`, `V`. Case matters. `Dark`
      is tolerated as the opaque slot.
- [ ] Cycle through positions; verify each one reports the correct
      `SelectedFilter.Name`.
- [ ] `mira doctor --config config\esprit120_jc.yaml` → Filter wheel
      check should PASS canonical.

### Focuser (Pegasus FocusCube 3)

- [ ] Pair with Pegasus Unity, then NINA → Focuser → PegasusAstro
      FocusCube → Connect
- [ ] Move ±500 steps; verify position read-back matches command.
      *Can't validate steps/mm without the OTA — that comes later.*

### Power box (PocketPowerbox Gen2)

- [ ] USB to MeLE; NINA → Switch → Pegasus PocketPowerbox → Connect
- [ ] Toggle each DC output; verify the LED on the box responds
- [ ] Run the dew heater output at 50% for 30 s, feel for warmth

### Guider (ZWO 30mm + ASI220MM Mini)

- [ ] Connect the ASI220MM to the MeLE
- [ ] PHD2 → New profile "Esprit guider" (camera ASI220MM Mini, focal
      length 150 mm, pixel size 4.0 µm, mount ASCOM → AM7 driver)
- [ ] Take a 5 s exposure in PHD2 — should see read-noise floor (no
      stars indoors, that's fine; we're verifying the I/O path)
- [ ] NINA → Guider → PHD2 → Connect; verify NINA sees PHD2's status

### Flat panel (Wanderer Cover V4-EC 190mm)

This is the gear we shipped support for last week. Validate it works
standalone before the OTA ever shows up.

- [ ] USB-C to MeLE; NINA → Flat Device → ASCOM Cover Calibrator
      (WandererAstro) → Connect
- [ ] In NINA's Flat Device tab: push brightness 0 → 50 → 100, watch
      the EL film visibly dim/brighten. If `CoverState` stays `Unknown`,
      reseat the USB-C cable and reconnect.
- [ ] Click Open Cover → lid retracts; Close Cover → lid shuts.
      Confirm `CoverState` reads back `Open`/`Closed`.
- [ ] `mira doctor` → Flat device check should PASS with non-Error
      `CoverState` and a sensible `MaxBrightness`.

## Phase 3: Syncthing + remote access (~½ day)

Per [`rig_workflow.md`](rig_workflow.md).

- [ ] Install Syncthing on homebase if not already there
- [ ] Pair MeLE ↔ homebase
- [ ] Folder `captures/`: rig = send-only, home = receive-only
- [ ] Folder `data/flats/`: rig = send-only, home = receive-only
- [ ] Drop a placeholder file in each on the rig side; confirm it
      appears on homebase within a few seconds
- [ ] Confirm Remote Desktop from homebase to MeLE is stable for at
      least 15 min — you'll be driving NINA over RDP during sessions

## Phase 4: Bank a dark / bias library (overnight, nights 5–15)

**Highest-ROI prep.** The cooled camera + cap is all you need; the
library is reusable for months until temperature or gain changes. Burn
nights you'd otherwise sleep through; arrive at first-light with
calibration frames already in the bag.

- [ ] **Bias frames** — minimum exposure (0.005 s) at gain 100, cooled
      to your imaging temperature. 100 frames. ~15 minutes of wall time.
- [ ] **Dark frames @ 60 s** (LRGB-V photometry exposure) — 50 frames.
      ~1 hour.
- [ ] **Dark frames @ 180 s** (LRGB stretch + light narrowband) — 50
      frames. ~3 hours.
- [ ] **Dark frames @ 300 s** (3nm SHO narrowband baseline) — 50
      frames. ~5 hours.
- [ ] Repeat the dark sets at any *other* gain you plan to use (e.g.
      gain 0 for high-dynamic-range)

Store under `data/calibration/darks/g100_<exp>s_<temp>C_<YYYYMMDD>/`
so the `mira stack` calibration-resolver picks them up cleanly later.

Practical pattern: set NINA's sequencer for a `Take Dark` block of 50
frames, kick it off before bed, the cooler holds temp through the
night and the dark library populates while you sleep.

## Phase 5: Mira end-to-end software paths (~1 day)

These all run with just the MeLE + camera + EFW connected — no OTA
optical path needed. The point is to catch any plumbing bug while the
fix cost is "edit code on homebase" not "lose a clear-sky window."

- [ ] `mira tonight --config config\esprit120_jc.yaml --hours 4` —
      writes a session plan to `output/esprit120_jc/tonight/`. Read
      `session_schedule.md` on your phone, sanity-check it.
- [ ] `mira dso plan --config config\esprit120_jc.yaml --top 10` —
      writes a DSO queue to `output/esprit120_jc/dso/`. Confirm the
      catalog loads and ranking looks sane.
- [ ] `mira dso status --config config\esprit120_jc.yaml` — empty
      ledger expected (nothing imaged yet), should print cleanly
- [ ] `mira capture --config config\esprit120_jc.yaml --ra 250 --dec 36 `
      `--exposure 5 --gain 100 --filter V --dest captures\bench_test`
      — drives NINA to take one 5 s frame with V selected. Verify a
      FITS + `mira_capture.json` sidecar both land in the dest dir.
      (Image is black; not the point.)
- [ ] `mira flats --config config\esprit120_jc.yaml --panel `
      `--filters V --frames 3` — exercises the full close-cover → set
      brightness → light on → bracket → light off path through the
      Wanderer panel. Camera+EFW pressed face-to-face against the
      panel in a dark bag is the cleanest indoor setup; the "flats" are
      meaningless optically but you'll catch any plumbing issue now
      instead of on first-light night.
- [ ] Touch'N'Stars from your phone — confirm it sees NINA's equipment
      state. This is how you'll monitor the session from inside the
      house once captures start.

## Phase 6: OTA-arrival day readiness

When the Esprit 120 actually shows up, you want to be 30 minutes away
from first light, not 8. Pre-stage these so the unboxing-to-imaging
gap is short.

- [ ] Cable management: dry-fit how the AM7 saddle, PowerBox, USB hub,
      and dew heater will route. Build a mock harness on a wooden
      dummy if you can; lengths matter.
- [ ] Confirm the Wanderer Cover V4-EC's 190 mm OD fits the Esprit's
      dewshield OD. (190 mm should match; verify with the spec sheet.)
- [ ] Print or save offline: NINA equipment-connect sequence,
      first-light checklist from [`nina_setup_esprit.md`](nina_setup_esprit.md).
- [ ] Identify a bright alignment star you'll use for the first slew
      (Vega or Deneb in late June from JC).
- [ ] Pre-fill any T-ring / spacer measurements once you know the
      Esprit's back-focus spec (typically 55 mm to sensor).

## Skip until the OTA arrives

These all require the OTA's optical path or precise mechanical setup.
Don't waste cycles on them now:

- Polar alignment (TPPA + plate-solve)
- Plate solving on sky (ASTAP needs stars)
- Focuser steps/mm calibration
- Per-filter autofocus offset measurement
- PHD2 calibration on a real star field
- Real flats (the bench-mode `mira flats --panel` test above is
  *plumbing-only*; real flats need the OTA)
- Final cooling-temp choice (depends on ambient at the pier on the
  night)
