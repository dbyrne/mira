# Mira Field Guide — bare laptop to capturing

The end-to-end runbook for taking Mira on a trip with the Seestar S30
Pro. Read it once at home; the only steps that need internet + a GUI are
done before you leave.

> **Reality check.** NINA, ASCOM, and the Seestar driver are Windows GUI
> software with **no headless or Docker path**. There is no "one image
> with everything." This guide installs the native Mira stack via a
> script and walks the NINA install by hand. That is the only thing that
> actually works — accept it and the rest is smooth.

---

## 0. At home, before you leave (needs internet + a GUI)

Do all of this while you still have good WiFi and time to fix problems.

1. **Clone the repo**, open it in Claude Code, trust the workspace.
   (Skills in `.claude/skills/` load only after you trust it — review
   their `allowed-tools` first; the two hardware skills are
   user-invoked-only by design.)
2. **Bootstrap the Mira stack:**
   ```
   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
   ```
   Add `-WithFinishing` only if you want `mira finish` AI steps.
   Idempotent — safe to re-run. It ends by running `mira doctor`.
3. **Install the NINA stack** (Section 1 — interactive, one time).
4. **Download the ASTAP star database** (large): ASTAP + a DB (D50/H18)
   from <https://www.hnsky.org/astap.htm> into the ASTAP folder.
   Without it, offline plate solves fail "No solution".
5. **Pair the Seestar** in NINA once (Section 1) and confirm a test
   slew/exposure works.
6. **Green-light check:** `mira doctor` — everything PASS except
   NINA-warnings-when-NINA-is-closed. Fix every FAIL now.
7. **One full dry run** with the rig connected:
   `mira tonight --config config/s30_pro_jc.yaml --hours 4`, import to
   NINA, run a few frames, `mira submit` them. This warms the HTTP
   cache and proves the whole chain.
8. **Pack:** laptop + charger, Seestar + tripod + **wedge** (EQ
   tracking is assumed), power bank, the paper/flat-panel for flats,
   dew control, storage headroom (a deep run is ~19 GB).

There is **no offline mode**. A site with no signal = no `mira tonight`
that night. Your mitigation is a phone tether or Starlink. Decide that
before you commit to a remote site.

---

## 1. NINA / ASCOM / Seestar (one-time, manual)

Full detail: [`docs/nina_setup.md`](nina_setup.md). Summary:

1. **ASCOM Platform 7+** — <https://ascom-standards.org/>
2. **NINA 3.x** — <https://nighttime-imaging.eu/>
3. NINA plugins: **Advanced API** (listens on port **1888**, sometimes
   1889) and **Target Scheduler**.
4. Pair the **S30 Pro** over station-mode WiFi via ASCOM Alpaca
   (Telescope + Camera; Filter Wheel if you have it).
5. **Fix the FocalLength=NaN quirk:** NINA Options > Equipment > set
   Focal Length **150**, Ratio **5**. The Seestar driver reports NaN,
   which breaks plate-solve scale until you set this.
6. Create the OSC exposure template and a Target Scheduler project
   named **Mira**.
7. Plate solver: **ASTAP** with its star database.

Keep the Seestar phone app **closed** during NINA sessions — it can
grab the device and drop NINA's connection.

---

## 2. Each observing night

Ask Claude Code to run these skills, or run the commands directly.

1. **Preflight** — skill `mira-preflight`, or:
   ```
   mira doctor --config config/s30_pro_jc.yaml
   ```
   Do not start a multi-hour capture with any **FAIL**. NINA WARNs are
   acceptable only until you start NINA + connect equipment.

2. **Plan the night** — skill `mira-nightly-run`, or:
   ```
   mira tonight --config config/s30_pro_jc.yaml --hours 4
   ```
   Read `output/s30_pro_jc/tonight/session_schedule.md` on your phone.
   Import `nina_targets.csv` into NINA's Target Scheduler (project
   "Mira", OSC template). Run the NINA sequence.

3. **Flats** (optional, any time) — skill `mira-take-flats`. Tape an
   evenly, steadily lit sheet of paper flush over the aperture (NOT a
   hand-held tablet — proven non-repeatable):
   ```
   mira flats --gain 120 --frames 25
   ```
   Match `--gain` to your lights. Masters land in
   `data/flats/<filter>_g<gain>_<date>/` and are reusable session to
   session (sealed scope) until focus/optics change.

4. **Deep single-target capture** — skill `mira-deep-capture`:
   ```
   mira capture --ra <J2000_deg> --dec <J2000_deg> --exposure 45 \
     --gain 120 --filter LP --dest captures/<t>_<date> --dither-arcsec 30
   ```
   **RA/Dec are J2000 DEGREES** (NINA reports RA in *hours* — the
   classic trap; multiply by 15). `--filter` confirms the wheel and
   aborts if it can't (won't burn hours through the wrong filter).
   Dithering is mandatory — un-dithered multi-hour drift is
   unrecoverable. **Eyeball where the scope actually points** — at one
   site the house blocked a target with a "good" computed altitude.

5. **Photometry / light curve** — skill `mira-photometry-submit`:
   ```
   mira submit --captures "captures/<dir>/" --target "<NAME>" \
     --observer-code ABC
   ```
   Then stack pretty pictures with the matching flat auto-applied:
   ```
   mira stack --lights captures/<dir> --out output/<t>.tif --auto-flats
   ```

6. **Trouble** — skill `mira-nina-troubleshoot` (full gotcha catalog).
   First move is always `mira doctor`.

---

## 3. Honest limitations (so you're not surprised in the field)

- **AAVSO submission is NOT production-ready.** The photometry has no
  color-term / transformation correction. Light curves are useful for
  *your own* analysis; the `aavso_*.txt` file is **not**
  publication-grade without transformation work that does not exist
  yet. Do not present it as submission-ready.
- **Flats fix vignette/dust, not light pollution.** An urban LP sky
  gradient is additive and a flat can't remove it (a ~4%-deep flat
  measurably *worsened* M51's gradient by fighting the LP). Dark skies,
  not flats, fix LP.
- **No offline mode.** `mira tonight` needs VSX; a dead connection
  fails *loudly* (by design) instead of writing an empty schedule —
  but it still fails. Tether/Starlink is a hard dependency.
- **Siril is version-pinned.** Script generation is verified against
  **1.4.3**. An OS auto-update of Siril can break stacking until
  re-pinned; `mira doctor` warns on a mismatch.
- **Single user, single machine, no backup.** Captures on the trip are
  unbacked until you get home. Plan storage and copy off when you can.
- **Hardware skills are user-invoked only.** Claude will not auto-slew
  or auto-capture; you explicitly run `/mira-deep-capture` /
  `/mira-take-flats`. This is intentional.

---

## 4. One-screen cheat sheet

```
setup (once):   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
every night:    mira doctor                         # or skill mira-preflight
                mira tonight --config config/s30_pro_jc.yaml --hours 4
                # import nina_targets.csv -> NINA Target Scheduler -> Run
flats:          mira flats --gain 120 --frames 25   # skill mira-take-flats
deep target:    mira capture --ra DEG --dec DEG --exposure 45 --gain 120 \
                  --filter LP --dest captures/x --dither-arcsec 30
reduce:         mira submit --captures captures/x --target NAME --observer-code ABC
stack:          mira stack --lights captures/x --out output/x.tif --auto-flats
broken?:        mira doctor   (then skill mira-nina-troubleshoot)
```
