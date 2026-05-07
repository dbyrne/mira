# Troubleshooting

Common things that go wrong and how to fix them. Organized by where in
the workflow the problem surfaces.

---

## Install / setup

### Tests fail after install

Symptom: `python -m unittest discover -s tests` reports failures or
import errors right after `pip install -e .`.

Likely causes:

- **Python too old**. Need 3.11+. Check with `python --version`.
- **Missing optional dependency**. `astropy` and `photutils` need to be
  importable; `pip install -e .` should pull them but a partial install
  can leave them missing. Try `python -m pip install --force-reinstall -e .`.
- **You're running from the wrong directory**. Tests must be discovered
  from the repo root (where `pyproject.toml` lives).

### `anomaly-scout: command not found`

The `pip install -e .` step didn't add the entry point to your PATH.
Try:

```powershell
python -m anomaly_scout webapp     # equivalent to "anomaly-scout webapp"
```

If that works but the bare `anomaly-scout` command doesn't, your
Python `Scripts/` directory isn't on PATH. Either fix your PATH
(typically `%APPDATA%\Python\Python311\Scripts`) or always invoke
via `python -m anomaly_scout`.

---

## Configuration

### "Could not resolve 'XYZ' in VSX"

Symptom: when you run `anomaly-scout target "XYZ"` or
`anomaly-scout submit --target "XYZ"`, the system says the name
doesn't match VSX or VizieR was unreachable.

Causes & fixes:

- **Name has typo or unusual format**. VSX accepts most common formats
  (`RR Lyr`, `Mira`, `Gaia DR3 1234567890123456789`, `ASASSN-V J123456+...`)
  but only one canonical form per target. Check
  <https://vsx.aavso.org/index.php?view=search.top> for the right
  spelling, then use that exact string.
- **Network was flaky**. The system retries 3× with backoff; if all
  three fail, it surfaces this error. Wait 30 seconds and retry.
- **VizieR is genuinely down**. Check
  <https://vizier.cds.unistra.fr/>. Their service occasionally has
  multi-hour outages.

### Site config: "no targets passed site filters"

Symptom: `anomaly-scout run` says you have hundreds of VSX targets but
zero pass the site filters.

Likely causes:

- **`min_altitude_deg` too high**. Drop it from 45° to 30° and see how
  many more targets qualify. Some configs ship with 45° because that's
  appropriate for urban skies; lower for darker locations.
- **`min_galactic_latitude_abs_deg` too strict**. The default 12°
  excludes a lot of Milky Way targets. Drop to 5° or 0° to relax.
- **`prefer_max_mag` is too bright**. The Seestar S30 Pro reaches
  ~12 in urban skies; if you set `prefer_max_mag: 10`, you cut out
  most of the catalog.
- **Date/time mismatch**. If your timezone isn't right, the system
  thinks it's daytime when you're observing. Double-check the IANA
  `timezone:` field — `America/Los_Angeles`, not `PST`.

---

## Schedule generation

### "Nothing observable in the next N hours"

Symptom: `anomaly-scout tonight --hours 4` says nothing is observable.

Causes & fixes:

- **Sun is still up**. The system requires `sun_alt < -12°` (nautical
  twilight) by default. Wait until full astronomical dark, or set
  `max_sun_altitude_deg: 0` in your window config.
- **Moon is bright and high**. Same idea. The illumination + altitude
  + separation gates can combine to reject everything if the moon is
  unfortunately placed. Check tonight's moon phase.
- **Hours window too short**. Try `--hours 6` or `--hours 8`.
- **Horizon profile too aggressive**. If you mapped a profile that
  blocks too much sky, it'll prune candidates harshly. Verify with the
  procedure in [Horizon profile § Verifying the profile](horizon_profile.md#verifying-the-profile).

### Schedule has no overlap with NINA's view

Symptom: NINA imports `nina_targets.csv` but the targets are below
the horizon when NINA tries to image them.

Cause: **Time-zone mismatch between the schedule and NINA**. The
schedule's `start_local`/`end_local` columns are in the site's
timezone (per the `timezone:` config field). If NINA is set to UTC or
your computer's local timezone differs, the timestamps will be
interpreted differently.

Fix: confirm your site config's `timezone:` matches what NINA reports
in the upper-right of its main window.

---

## NINA / capture

### NINA dashboard says "unreachable"

Symptom: the webapp's `/nina` page polls and shows "NINA not reachable"
when NINA is running.

Causes & fixes:

- **Advanced API plugin not installed**. Plugins → Available → search
  "Advanced API" → install. Restart NINA.
- **Plugin not enabled**. Settings → Advanced API → check the
  "Enabled" box. Default port 1888.
- **Different port**. If you changed the port, pass
  `--nina-url http://localhost:NNNN` to `anomaly-scout webapp`.
- **Firewall**. Windows Defender Firewall sometimes blocks localhost
  connections from Python. Allow Python through the firewall.
- **NINA is running as Administrator and the webapp is not** (or vice
  versa). Run both at the same privilege level.

### "First FITS is missing a celestial WCS"

Symptom: photometry pipeline aborts at preflight with this error.

Cause: NINA didn't plate-solve before saving the FITS, so there's no
RA/Dec → pixel transformation in the headers. The photometry math
needs that transform to find the target and comp stars.

Fixes:

- In NINA's Target Scheduler config, enable **Slew + Center on Target**
  before each capture series. This forces a plate-solve.
- Check that your **plate-solver is configured** (Settings → Plate
  Solving). ASTAP is the easiest free option; it ships with a star
  catalog and works offline.
- After the fact, you can plate-solve already-captured FITS using
  ASTAP CLI or astrometry.net, then re-run the photometry pipeline.

---

## Photometry

### "No observations recovered from any frame"

Symptom: photometry pipeline runs but the report shows zero successful
observations. Each frame logs "no usable signal."

Likely causes:

- **Comp stars off-frame**. AAVSO VSP may return comps spread over a
  wide field (default 60 arcmin). If your scope has a smaller FOV
  (e.g., the Seestar S30 Pro's ~10° wide field is fine; some narrower
  scopes are not), the comps may all fall outside your image. Check
  the FITS header's reported field size and reduce VSP's FOV if needed.
- **Target/comp positions are wrong**. If plate-solving was wrong (or
  there was a slight pointing offset), the WCS in the FITS doesn't
  actually point where it claims. The photometry tries to extract flux
  from blank sky.
- **Target is too dim for your gear**. Below the detection threshold,
  aperture photometry gives non-positive flux which the system
  interprets as "no signal."
- **Sky background dominates**. In very urban skies, the sky background
  can saturate the photometric aperture and the target signal drops
  below the noise.

Quick diagnosis: open one of the FITS files in a viewer (DS9, AstroImageJ,
or even the rehearsal-built ones in the project's `house_photos/`)
and verify by eye that the target is visible at the position the WCS
claims.

### Rehearsal residual too large

Symptom: `anomaly-scout rehearse --target X` reports
"recovered magnitude differs from planted by ±N mag" with N > 0.4.

Causes & fixes:

- **Comp star magnitudes drifted**. AAVSO occasionally re-publishes
  charts. Clear the VSP cache (`anomaly-scout cleanup --cache --apply`)
  and try again.
- **Planted vs recovered direction inverted**. If the residual is
  consistently +1 to +2 mag, you may have hit a flux-scaling bug in
  the synthesizer. Check that the rehearsal output mentions
  *"recovered median ... lower than planted"* (target appears fainter)
  vs *"recovered median ... higher"* (target appears brighter) — the
  sign tells you which direction to investigate.
- **VSP returned an empty chart**. Some obscure VSX targets don't have
  a published comp sequence. Try a well-known target like RR Lyr or
  AB Aur.

### Anomaly callout fires on every observation

Symptom: every photometry run flags a "watch" or "anomaly" status, even
on stable targets.

Likely cause: **systematic offset between your photometry and AAVSO
baseline**. Could be:

- You're submitting as TG band, but the AAVSO baseline is dominated
  by V-band observations. The two bands differ by 0.1-0.3 mag on red
  stars.
- Your aperture or sky annulus is too small/large, leading to consistent
  over- or under-counting.
- Your comp stars come from a different chart version than the AAVSO
  baseline does.

Diagnosis: look at the *direction* of the residual (always too bright
vs always too faint?) and the *magnitude* (always around the same
amount?). A consistent ~0.1 mag offset on red stars is just the V-vs-TG
band difference and is expected. A consistent ~0.5 mag offset across
multiple targets suggests an aperture or chart issue.

---

## Webapp

### Webapp won't start, port already in use

Symptom: `anomaly-scout webapp` errors with "Address already in use" on
port 8000.

Fixes:

- Another `anomaly-scout webapp` is already running. Stop it
  (`Ctrl-C` in its terminal, or kill the Python process).
- Something else is using port 8000. Run on a different port:
  `anomaly-scout webapp --port 8080`.

### Webapp loads but `/photometry` is empty

Symptom: page renders but says "No captures found."

Causes:

- **Captures root pointing wrong**. The default `captures/` is relative
  to the directory you ran `anomaly-scout webapp` from. Confirm with
  `--captures-root /full/absolute/path/to/captures`.
- **No FITS in captures yet**. The page only shows directories that
  contain `*.fits` or `*.fit` files. NINA's saving to a different
  location, or the date subdir convention isn't matching what's
  actually on disk.

### Live photometry results not updating

Symptom: you started a photometry run; the page shows "running" but
frames don't appear in real time.

Cause: **HTMX polling stopped working**. Most often:

- Browser is throttling background tabs. Bring the tab to the
  foreground.
- Page is being viewed via a stale URL. Hard-refresh
  (`Ctrl-Shift-R`).

The polling does deliberately stop when the run reaches a "done" or
"failed" state — that's by design, not a bug. The frame deselect form
needs polling to stop so your toggles aren't wiped every 2 seconds.

---

## Submission

### AAVSO rejected my upload

Symptom: <https://www.aavso.org/webobs/file> responds with a parse error.

Common causes:

- **Wrong observer code**. AAVSO's WebObs is strict about the
  `#OBSCODE=ABC` header. Confirm your code at
  <https://www.aavso.org/observer-code>.
- **Magnitude out of range**. AAVSO rejects observations with mag
  values that don't make physical sense (negative or >25).
- **Bad date format**. The `#DATE=JD` header tells AAVSO the date
  column is Julian Date. Confirm the dates look like ~2461000 (current
  era) and not Unix timestamps or ISO strings.
- **Missing required column**. AAVSO Extended Format requires every
  column present. The system writes "na" for unused fields, which is
  the correct sentinel.

If the error message mentions a specific row/column, open the
`aavso_*.txt` file in a text editor and inspect that row.

### "Mark as submitted" doesn't update the page

Symptom: you click "Mark as submitted" but the badge doesn't change.

Cause: stale browser tab. Refresh the page; the underlying SQLite
record was updated.

---

## Data management

### Run history grows huge

Symptom: `data/webapp_runs/` has hundreds of `<run_id>.json` files.

Fix: prune old non-submitted runs:

```powershell
# Dry-run first to see what would be removed
anomaly-scout cleanup --runs --older-than 90

# Apply it
anomaly-scout cleanup --runs --older-than 90 --apply
```

Submitted runs are protected by default. Cache entries can be cleaned
the same way:

```powershell
anomaly-scout cleanup --cache --older-than 30 --apply
```

### `data/webapp_runs/sessions.db` is out of sync

Symptom: the `/data/sessions` page shows stale or missing entries
relative to the actual run records on disk.

Fix: rebuild the SQLite index from the canonical JSON records:

```powershell
anomaly-scout migrate-runs
```

This is idempotent — safe to re-run any time.

---

## When all else fails

Open an issue on the [GitHub repo][repo] with:

- The exact command you ran
- The full error output
- Your Python version (`python --version`)
- Your OS (`uname -a` on Linux/Mac, `winver` on Windows)
- The relevant config file (with sensitive paths redacted)

[repo]: https://github.com/dbyrne/aavso-anomaly-scout/issues
