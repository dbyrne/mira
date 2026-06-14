"""Deep-capture loop with dithering + re-centering.

Replaces the ad-hoc inline capture scripts used all session. The M94
2026-05-18 run proved why this is needed: no dithering + uncorrected
multi-hour drift produced un-fixable walking-noise streaks (six
post-processing fixes all failed — see output/m94/EXPERIMENTS_REPORT.md).

The key design choice: **dither relative to the FIXED nominal target
coordinates, never cumulatively.** Each sub points at `(nominal +
small random offset)`. That simultaneously (a) decorrelates fixed-
pattern/walking noise (the offset lands the sensor pattern on different
sky pixels each sub) and (b) re-centers for free — drift can never
accumulate because every sub is repositioned near the nominal target.

All reposition slews use `center=False` — NO plate-solve Center. NINA's
iterative Center looped endlessly on this mount (2026-05-18); a blind
slew to nominal±offset is correct here and a wide field tolerates the
rough pointing.

Pure dither math + an injected client → unit-tested without NINA.
"""
from __future__ import annotations

import glob
import math
import os
import random
import shutil
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


# Settle before the end-of-run sweep: NINA can flush the last FITS to disk
# slightly after capture() returns, so the loop's final in-iteration glob
# can miss it. Module-level so tests can zero it.
FINAL_SWEEP_SETTLE_S = 2.0


class _Client(Protocol):
    def slew(self, ra_deg: float, dec_deg: float, *, center: bool = ...,
             wait: bool = ..., timeout: float = ...) -> dict: ...
    def wait_camera_idle(self, timeout_s: float = ..., poll_s: float = ...) -> bool: ...
    def capture(self, *, duration: float, gain: int | None = ..., save: bool = ...,
                solve: bool = ..., target_name: str = ..., timeout_s: float = ...) -> dict: ...
    def set_filter(self, filter_ref: str | int, *, wait: bool = ...,
                    timeout_s: float = ...) -> bool: ...
    def run_autofocus(self, *, timeout_s: float = ...,
                       poll_s: float = ...) -> dict: ...
    def park(self, timeout: float = ...) -> dict: ...


@dataclass
class CaptureResult:
    captured: int = 0
    copied: int = 0
    dithers: int = 0
    recenters: int = 0
    autofocus_runs: int = 0
    pier_flips: int = 0
    platesolve_centered: bool = False
    pointing_verified: bool = False
    pointing_offset_deg: float | None = None
    stopped_reason: str = ""
    dest_dir: str = ""
    filter_name: str = ""


def random_dither_deg(
    max_arcsec: float, dec_deg: float, rng: random.Random
) -> tuple[float, float]:
    """A uniform random offset within a ±`max_arcsec` square, returned as
    (d_ra_deg, d_dec_deg). RA is divided by cos(dec) so the *angular* dither
    is isotropic regardless of declination. Always relative to the caller's
    nominal coords — never chained — so it cannot accumulate into drift."""
    if max_arcsec <= 0:
        return 0.0, 0.0
    d_dec = rng.uniform(-max_arcsec, max_arcsec) / 3600.0
    cosd = max(math.cos(math.radians(dec_deg)), 1e-3)
    d_ra = (rng.uniform(-max_arcsec, max_arcsec) / 3600.0) / cosd
    return d_ra, d_dec


def _target_alt_deg(ra_deg: float, dec_deg: float, lat: float, lon: float,
                     when: datetime) -> float:
    jd = 2451545.0 + (when - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0)
    ha = math.radians(((gmst + lon) % 360.0 - ra_deg) % 360.0)
    d, l = math.radians(dec_deg), math.radians(lat)
    return math.degrees(math.asin(
        math.sin(d) * math.sin(l) + math.cos(d) * math.cos(l) * math.cos(ha)
    ))


def altitude_sun_guard(
    ra_deg: float, dec_deg: float, lat: float, lon: float, *,
    alt_floor_deg: float = 30.0, sun_max_deg: float = -15.0,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[int], str | None]:
    """Returns a predicate(frame_index) -> stop-reason str or None. Stops
    when the target drops below `alt_floor_deg`, or — only at DAWN — when
    the Sun rises above `sun_max_deg`.

    The Sun gate fires only while the Sun is *rising* (morning), so it acts
    as an end-of-night dawn shutdown but never blocks an evening start: the
    operator decides when dusk is dark enough to begin (per user request
    2026-06-05 — the evening gate kept killing legitimate twilight starts).
    A *descending* (dusk) Sun above the threshold is therefore ignored.
    `clock` is injectable for deterministic tests.

    Imported lazily to avoid pulling ephemeris into module import."""
    from .observability import sun_position
    _clock = clock or (lambda: datetime.now(timezone.utc))

    def _guard(_i: int) -> str | None:
        now = _clock()
        if _target_alt_deg(ra_deg, dec_deg, lat, lon, now) < alt_floor_deg:
            return f"target below {alt_floor_deg:.0f} deg altitude"
        sra, sdec = sun_position(now)
        sun_alt = _target_alt_deg(sra, sdec, lat, lon, now)
        if sun_alt > sun_max_deg:
            # Only stop at dawn (Sun rising). A dusk Sun above the gate is
            # the operator's call — they start when they judge it dark.
            later = now + timedelta(minutes=10)
            lra, ldec = sun_position(later)
            if _target_alt_deg(lra, ldec, lat, lon, later) > sun_alt:
                return f"sun above {sun_max_deg:.0f} deg (dawn)"
        return None

    return _guard


def _verify_pointing(
    client: _Client,
    *,
    ra_deg: float,
    dec_deg: float,
    exposure_s: float,
    gain: int | None,
    nina_root: Path,
    tolerance_deg: float,
    emit: Callable[[str], None],
    fov_deg: float | None = None,
) -> tuple[bool, float | None, str, Path | None]:
    """Take one test sub, ASTAP-solve it, compare solved center to nominal.

    `fov_deg` is the rig's frame height for ASTAP's -fov hint; None means
    "use the solver default" (the S30 value). Threading the real rig FOV
    matters: a 4x-wrong hint on the Esprit (1.07 vs ~4.6 deg) makes every
    solve fail and the check silently fail-open.

    Returns (ok, separation_deg, message, keeper_frame). `keeper_frame` is the
    solved test FITS — a real, on-target, science-exposure sub that already
    carries WCS (solve_one ran with -update) — returned ONLY on a clean pass so
    the caller can keep it instead of wasting a free frame. Every skip/fail path
    returns None for it: no frame was taken, or it's cloudy/unsolved/off-target.

    When ASTAP can't run at all
    (no astap_cli on PATH, no star DB), or solve fails for a non-pointing
    reason (clouds, no stars), we return ok=True with the message — better
    to capture an un-verified session than refuse a session over a
    cloudy test sub. The only `ok=False` is when ASTAP solved successfully
    *and* the solved center is more than `tolerance_deg` from nominal —
    a real mount-sync drift like the 2026-05-19 M51 disaster.
    """
    import glob
    import os

    from .solve import DEFAULT_FOV_DEG, AstapNotFound, find_astap_cli, solve_one
    from .webapp.nina_client import angular_separation_deg

    try:
        astap = find_astap_cli()
    except AstapNotFound as exc:
        emit(f"  verify-pointing skipped: {exc}")
        return True, None, f"astap_cli not found: {exc}", None

    # Detect the test sub by a before/after diff of ALL FITS, not by parsing
    # an exposure token out of the filename: NINA's image file pattern is
    # user-configurable, so any `*<token>*` glob is fragile (see the copy
    # loop's note re: the 2026-06-03 `*60.00s*` bug).
    glob_pat = os.path.join(str(nina_root), "**", "*.fit*")
    before = set(glob.glob(glob_pat, recursive=True))

    emit("verify-pointing: capturing test sub for plate-solve...")
    try:
        client.capture(
            duration=exposure_s, gain=gain, save=True,
            solve=False, target_name="verify_pointing",
            timeout_s=max(exposure_s * 2 + 60, 120),
        )
    except Exception as exc:
        emit(f"  verify-pointing skipped (capture failed): {exc}")
        return True, None, f"test capture failed: {exc}", None

    after = set(glob.glob(glob_pat, recursive=True))
    new_files = after - before
    if not new_files:
        emit("  verify-pointing skipped: couldn't find new FITS in nina_root")
        return True, None, "test FITS not found", None

    test_frame = Path(max(new_files, key=os.path.getmtime))
    emit(f"  test frame: {test_frame.name}; ASTAP-solving with tight hint...")
    solve_res = solve_one(
        test_frame, astap_cli=astap,
        ra_hint_deg=ra_deg, dec_hint_deg=dec_deg,
        fov_deg=DEFAULT_FOV_DEG if fov_deg is None else fov_deg,
        radius_deg=5.0,
    )
    if solve_res.status != "solved":
        emit(f"  verify-pointing skipped: ASTAP {solve_res.note}")
        return True, None, f"solve failed: {solve_res.note}", None

    # solve_one used -update; the FITS now carries WCS.
    from astropy.io import fits
    try:
        hdr = fits.getheader(test_frame)
        solved_ra = float(hdr["CRVAL1"])
        solved_dec = float(hdr["CRVAL2"])
    except (KeyError, OSError, ValueError) as exc:
        emit(f"  verify-pointing skipped: couldn't read WCS: {exc}")
        return True, None, f"WCS read failed: {exc}", None

    sep = angular_separation_deg(ra_deg, dec_deg, solved_ra, solved_dec)
    if sep > tolerance_deg:
        msg = (
            f"pointing verification FAILED: solved center "
            f"({solved_ra:.4f}, {solved_dec:.4f}) is {sep:.2f}deg from "
            f"nominal ({ra_deg:.4f}, {dec_deg:.4f}); exceeds "
            f"tolerance {tolerance_deg:.2f}deg. Test sub left at "
            f"{test_frame} for inspection."
        )
        emit(msg)
        return False, sep, msg, None

    emit(f"  verify-pointing OK: solved center {sep:.3f}deg from nominal "
         f"(within {tolerance_deg:.2f}deg)")
    return True, sep, f"verified {sep:.3f}deg from nominal", test_frame


def run_capture(
    client: _Client,
    *,
    ra_deg: float,
    dec_deg: float,
    exposure_s: float,
    gain: int | None,
    dest_dir: Path,
    nina_root: Path,
    n_max: int = 1000,
    dither_arcsec: float = 30.0,
    dither_every: int = 1,
    recenter_every: int = 0,
    settle_s: float = 2.0,
    slew_timeout_s: float = 180.0,
    target_name: str = "",
    filter_name: str | None = None,
    platesolve_center: bool = False,
    autofocus_every_min: int = 0,
    autofocus_timeout_s: float = 600.0,
    verify_pointing_deg: float = 1.0,
    fov_deg: float | None = None,
    sidecar_audit: dict[str, Any] | None = None,
    should_continue: Callable[[int], str | None] | None = None,
    on_step: Callable[[str], None] | None = None,
    rng: random.Random | None = None,
    stop_event: "threading.Event | None" = None,
) -> CaptureResult:
    """Capture loop. Per sub: reposition (dither around nominal, or explicit
    re-center) → wait idle → expose+save → incrementally copy the new frame
    to `dest_dir`. Stops at `n_max`, or when `should_continue(i)` returns a
    reason. Reposition slews are always `center=False`.

    `nina_root` is scanned (snapshot diff) for new `*.fit*` files to copy
    out (NINA saves there; the loop owns the stable copy in `dest_dir`).

    A single Ctrl-C (or setting `stop_event`) requests a *clean* stop: the
    current frame finishes and the loop breaks between frames, leaving the
    camera Idle so the next session's plate-solve isn't stranded mid-exposure.
    A second Ctrl-C hard-aborts. The camera is released (best-effort) on every
    exit path."""
    rng = rng or random.Random()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    res = CaptureResult(dest_dir=str(dest_dir))
    # Clean-stop signal: set by the SIGINT handler installed below (or by an
    # external caller such as the webapp). Checked at the top of the loop so
    # the current frame always finishes and the camera is left Idle.
    stop_event = stop_event if stop_event is not None else threading.Event()

    def _emit(m: str) -> None:
        if on_step is not None:
            on_step(m)

    # Filter preflight. Selecting + CONFIRMING the wheel before a multi-hour
    # stack is a hard gate: shooting the whole run through the wrong (or a
    # blocking) filter silently invalidates calibration against the
    # per-filter master flat. Refuse to start rather than waste the night.
    if filter_name:
        _emit(f"selecting filter '{filter_name}'...")
        if not client.set_filter(filter_name, wait=True):
            res.stopped_reason = (
                f"filter '{filter_name}' not confirmed by the wheel; aborting "
                "before capture (refusing to shoot through the wrong/no filter)"
            )
            _emit(res.stopped_reason)
            return res
        res.filter_name = filter_name
        _emit(f"filter '{filter_name}' confirmed")

    # Provenance sidecar. Two purposes:
    #  - `mira stack --auto-flats` keys off filter/gain at the top level
    #    (existing contract — don't move those).
    #  - Full effective config goes under `config` for post-run audit. The
    #    same file is rewritten on shutdown with a `result` block so a
    #    single artifact answers both "what was the intent?" and "what
    #    happened?". `sidecar_audit` lets the CLI inject site-level fields
    #    (lat/lon/alt_floor/sun_max/mira_version) that run_capture itself
    #    doesn't see — they're baked into the should_continue closure.
    from .flats import write_capture_sidecar
    from . import __version__ as _mira_version

    effective_config = {
        "exposure_s": exposure_s,
        "gain": gain,
        "ra_deg": ra_deg,
        "dec_deg": dec_deg,
        "filter": res.filter_name or None,
        "target_name": target_name,
        "dither_arcsec": dither_arcsec,
        "dither_every": dither_every,
        "recenter_every": recenter_every,
        "n_max": n_max,
        "settle_s": settle_s,
        "slew_timeout_s": slew_timeout_s,
        "platesolve_center": platesolve_center,
        "verify_pointing_deg": verify_pointing_deg,
        "fov_deg": fov_deg,
        "autofocus_every_min": autofocus_every_min,
        "autofocus_timeout_s": autofocus_timeout_s,
        "nina_root": str(nina_root),
        "mira_version": _mira_version,
        **(sidecar_audit or {}),
    }
    started_utc = datetime.now(timezone.utc).isoformat()

    def _persist_sidecar(*, with_result: bool = True) -> None:
        fields: dict[str, Any] = dict(
            filter=res.filter_name, gain=gain, exposure_s=exposure_s,
            ra_deg=ra_deg, dec_deg=dec_deg, target_name=target_name,
            config=effective_config,
        )
        # The pre-loop snapshot OMITS the `result` key entirely: the
        # integration ledger trusts result["copied"] whenever the key is
        # present, so a provisional copied=0 would defeat its documented
        # glob-rescue and book an interrupted session as zero minutes.
        # No result key == run in progress; the ledger counts *.fit* on
        # disk instead.
        if with_result:
            fields["result"] = {
                "captured": res.captured,
                "copied": res.copied,
                "dithers": res.dithers,
                "recenters": res.recenters,
                "autofocus_runs": res.autofocus_runs,
                "pier_flips": res.pier_flips,
                "platesolve_centered": res.platesolve_centered,
                "pointing_verified": res.pointing_verified,
                "pointing_offset_deg": res.pointing_offset_deg,
                "stopped_reason": res.stopped_reason,
                "started_utc": started_utc,
                "ended_utc": datetime.now(timezone.utc).isoformat(),
            }
        write_capture_sidecar(dest_dir, **fields)

    # Pre-loop plate-solve-center. The in-loop slews are all blind
    # (center=False) by design — that's correct for *staying* on target
    # (anchored dither prevents drift) but does nothing to verify we got
    # *to* the target in the first place. One synchronous Center here pins
    # the mount to the actual nominal coords, which is also what subsequent
    # nights need to re-acquire identical framing in a multi-night run.
    if platesolve_center:
        _emit("plate-solve centering on nominal coords...")
        try:
            client.slew(ra_deg, dec_deg, center=True, wait=True,
                        timeout=max(slew_timeout_s, 300.0))
            res.platesolve_centered = True
            _emit("  plate-solve center done")
        except Exception as exc:
            _emit(f"  plate-solve center FAILED (continuing with blind slews): {exc}")

    # Pre-loop pointing verification. Even when slew(center=True) returned
    # success, the only ground truth is plate-solving an actual captured
    # frame: NINA's slew endpoint returns just "Slew finished" with no
    # solved position, and the mount can self-report a wrong location
    # (2026-05-19: Seestar reported being on M51 while actually 2.8 deg
    # east — six hours of imaging lost). Take one test sub, ASTAP-solve
    # it, abort if solved center is too far from nominal.
    if platesolve_center and verify_pointing_deg > 0:
        ok, sep, msg, keeper = _verify_pointing(
            client, ra_deg=ra_deg, dec_deg=dec_deg,
            exposure_s=exposure_s, gain=gain, nina_root=nina_root,
            tolerance_deg=verify_pointing_deg, emit=_emit,
            fov_deg=fov_deg,
        )
        res.pointing_offset_deg = sep
        if ok:
            res.pointing_verified = True
            # The verify sub is a real, on-target, science-exposure frame that
            # ASTAP already solved (carries WCS) — keep it rather than waste a
            # free sub. `keeper` is non-None only on a clean pass; skip/fail
            # paths return None (no frame, or cloudy/off-target). It's copied
            # explicitly here; the loop's `seen` snapshot (taken just below)
            # includes its source in nina_root, so the loop won't re-copy it.
            if keeper is not None:
                try:
                    shutil.copy2(keeper, dest_dir)
                    res.captured += 1
                    res.copied += 1
                    _emit(f"  kept verify sub as a light frame: {keeper.name}")
                except OSError as exc:
                    _emit(f"  (could not keep verify sub: {exc})")
        else:
            res.stopped_reason = msg
            _persist_sidecar()
            return res

    # Autofocus schedule. Wall-clock based (NOT sub-count) because the loop
    # stop time is dynamic — alt-floor / sun-rise guards can cut a planned
    # 3-hour session to 90 minutes. A sub-count "every N frames" or quartile
    # schedule would land the last 2-3 AF runs after we've already stopped.
    af_interval_s = max(0, int(autofocus_every_min)) * 60.0
    next_af_at = 0.0  # 0 == "fire now (pre-loop)"; only meaningful if af_interval_s > 0

    def _try_autofocus(reason: str) -> None:
        nonlocal next_af_at
        _emit(f"autofocus run ({reason})...")
        try:
            client.run_autofocus(timeout_s=autofocus_timeout_s)
            res.autofocus_runs += 1
            _emit("  autofocus done")
        except Exception as exc:  # noqa: BLE001 — fail-soft
            _emit(f"  autofocus FAILED (continuing with last-known focus): {exc}")
        # Schedule next AF from "now" even on failure, so a transient
        # cloud-induced AF abort doesn't trigger immediate retry storms.
        next_af_at = time.monotonic() + af_interval_s

    if af_interval_s > 0:
        _try_autofocus("pre-loop")

    # Pre-loop sidecar snapshot. Written AFTER platesolve/verify/AF so
    # the persisted config reflects actual pre-loop state — not
    # pre-pre-loop zeros — and WITHOUT a result block (see
    # _persist_sidecar). The finally-write at the end records final
    # tallies even on Ctrl-C / crash.
    _persist_sidecar(with_result=False)

    # New-frame detection is by snapshot diff, NOT filename parsing. NINA's
    # image file pattern is user-configurable (e.g.
    # $$DATEMINUS12$$_$$TIME$$_$$FILTER$$_$$SENSORTEMP$$_$$EXPOSURETIME$$_$$FRAMENR$$),
    # so a token-matching glob is fragile: the original `*{exp:.2f}s*` glob
    # appended an 's' that $$EXPOSURETIME$$ never emits and copied 0/70 real
    # frames (2026-06-03). `seen` is snapshotted here AFTER verify-pointing +
    # pre-loop autofocus, so any FITS that appears during the loop is a new
    # science sub. Reposition slews use center=False (no mid-loop solve
    # frames), and NINA does not write autofocus exposures into the light dir.
    seen = set(glob.glob(os.path.join(str(nina_root), "**", "*.fit*"),
                         recursive=True))

    def _copy_new_frames() -> None:
        # A frame joins `seen` only AFTER a successful copy: a locked or
        # still-flushing file (OneDrive nina_root) raises OSError now but
        # usually copies fine on a later pass — marking it seen first
        # would drop the frame permanently and silently.
        for p in glob.glob(os.path.join(str(nina_root), "**", "*.fit*"),
                           recursive=True):
            if p in seen:
                continue
            try:
                shutil.copy2(p, dest_dir)
            except OSError as exc:
                _emit(f"  copy failed (will retry): "
                      f"{os.path.basename(p)} ({exc})")
                continue
            seen.add(p)
            res.copied += 1

    # Meridian-flip watch. Mount firmware can flip pier side during an
    # anchored GOTO; the field then rotates 180 deg and the blind dither
    # slews would keep shooting the rotated frame unverified. Poll the
    # mount's pier side once per sub and, on a change, re-center (only
    # when the session runs with platesolve_center — same call as the
    # pre-loop center). A client/mount that doesn't report a side
    # (Seestar) reads "" and the watch is a silent no-op; the method is
    # resolved via getattr so older/leaner clients still work.
    def _poll_pier_side() -> str:
        getter = getattr(client, "pier_side", None)
        if getter is None:
            return ""
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001 — a poll hiccup must not kill the run
            return ""

    last_pier_side = _poll_pier_side()

    # Best-effort camera release. A hard stop (second Ctrl-C) or a crash can
    # strand the Seestar mid-exposure, which then fails the NEXT session's
    # plate-solve (device reports not-ready). Aborting on every exit path
    # returns it to Idle. Optional on the client (getattr) + fail-soft, so a
    # leaner client or a normal clean stop (camera already idle) is a no-op.
    def _abort_camera() -> None:
        aborter = getattr(client, "abort_capture", None)
        if aborter is None:
            return
        try:
            aborter()
        except Exception:  # noqa: BLE001 — cleanup must never raise
            pass

    # Graceful Ctrl-C. First interrupt -> request a clean stop: the blocking
    # capture() is NOT interrupted (PEP 475 retries it), so the current frame
    # finishes and the loop breaks at the next top with the camera Idle, ready
    # for the next session's solve. Second interrupt -> restore the prior
    # handler and re-raise for an immediate hard abort. signal.signal only
    # works on the main thread, so a non-main caller (e.g. a webapp worker)
    # silently keeps the old raise-on-Ctrl-C behavior and can still drive a
    # clean stop by supplying its own `stop_event`.
    _prev_sigint = None
    _sigint_installed = False

    def _on_sigint(signum, frame):  # pragma: no cover - delivered via signal
        if stop_event.is_set():
            if _prev_sigint is not None:
                signal.signal(signal.SIGINT, _prev_sigint)
            raise KeyboardInterrupt
        stop_event.set()
        _emit("Ctrl-C: clean stop requested — finishing the current frame, "
              "then exiting with the camera idle. Ctrl-C again to abort now.")

    try:
        _prev_sigint = signal.signal(signal.SIGINT, _on_sigint)
        _sigint_installed = True
    except (ValueError, OSError):  # not the main thread (e.g. webapp worker)
        _sigint_installed = False

    try:
        for i in range(1, n_max + 1):
            if stop_event.is_set():
                res.stopped_reason = (
                    "interrupted (clean stop after current frame)"
                )
                _emit(f"clean stop: {res.captured} sub(s) captured, camera idle")
                break
            # Periodic AF (wall-clock). Skipped on i==1 because pre-loop
            # already fired one moments ago; from i=2 onward we just check
            # elapsed time.
            if af_interval_s > 0 and i > 1 and time.monotonic() >= next_af_at:
                _try_autofocus(f"+{autofocus_every_min}min")
            if should_continue is not None:
                reason = should_continue(i)
                if reason:
                    res.stopped_reason = reason
                    _emit(f"stop: {reason} (after {res.captured} subs)")
                    break

            cur_pier_side = _poll_pier_side()
            if (cur_pier_side and last_pier_side
                    and cur_pier_side != last_pier_side):
                res.pier_flips += 1
                if platesolve_center:
                    _emit(f"pier flip detected ({last_pier_side}->"
                          f"{cur_pier_side}): re-centering")
                    try:
                        client.slew(ra_deg, dec_deg, center=True, wait=True,
                                    timeout=max(slew_timeout_s, 300.0))
                        _emit("  post-flip plate-solve center done")
                    except Exception as exc:
                        _emit("  post-flip center FAILED (continuing with "
                              f"blind slews): {exc}")
                else:
                    _emit(f"pier flip detected ({last_pier_side}->"
                          f"{cur_pier_side})")
            if cur_pier_side:
                last_pier_side = cur_pier_side

            # Reposition. Dither (every `dither_every` subs) is relative to
            # the FIXED nominal coords -> also re-centers. Explicit
            # re-center only matters when not dithering or dithering
            # sparsely.
            do_dither = (dither_arcsec > 0
                         and (i - 1) % max(dither_every, 1) == 0)
            do_recenter = (not do_dither and recenter_every > 0
                           and (i - 1) % recenter_every == 0)
            if do_dither:
                d_ra, d_dec = random_dither_deg(dither_arcsec, dec_deg, rng)
                try:
                    client.slew(ra_deg + d_ra, dec_deg + d_dec,
                                center=False, wait=True, timeout=slew_timeout_s)
                    res.dithers += 1
                    time.sleep(settle_s)
                except Exception as exc:  # a failed nudge must not kill the run
                    _emit(f"  dither slew failed (continuing): {exc}")
            elif do_recenter:
                try:
                    client.slew(ra_deg, dec_deg, center=False, wait=True,
                                timeout=slew_timeout_s)
                    res.recenters += 1
                    time.sleep(settle_s)
                except Exception as exc:
                    _emit(f"  re-center slew failed (continuing): {exc}")

            client.wait_camera_idle(timeout_s=90.0)
            try:
                client.capture(duration=exposure_s, gain=gain, save=True,
                                solve=False, target_name=target_name,
                                timeout_s=max(exposure_s * 2 + 60, 120))
                res.captured += 1
            except Exception as exc:
                _emit(f"  capture {i} failed: {exc}")

            _copy_new_frames()

            if i == 1 or i % 15 == 0:
                _emit(f"  {i}/{n_max}: captured={res.captured} "
                      f"copied={res.copied} dithers={res.dithers}")

        # One final settle + sweep: the last sub of a run races the loop —
        # NINA can write its FITS after the last in-iteration glob ran, so
        # without this pass the frame is stranded in nina_root. Also
        # retries any copy that failed (locked file) during the loop.
        if FINAL_SWEEP_SETTLE_S > 0:
            time.sleep(FINAL_SWEEP_SETTLE_S)
        _copy_new_frames()

        if not res.stopped_reason:
            res.stopped_reason = f"reached n_max={n_max}"
    except BaseException as exc:  # noqa: BLE001 — record, then re-raise
        # Ctrl-C / crash mid-session: record what actually happened so the
        # finally-persist below books the true tallies (an interrupted
        # 3-hour run with 150 FITS on disk must not read as 0 copied).
        if not res.stopped_reason:
            res.stopped_reason = (
                "interrupted" if isinstance(exc, KeyboardInterrupt)
                else f"crashed: {exc}"
            )
        raise
    finally:
        if _sigint_installed and _prev_sigint is not None:
            try:
                signal.signal(signal.SIGINT, _prev_sigint)
            except (ValueError, OSError):
                pass
        _abort_camera()
        _persist_sidecar()
    return res


def safe_park(
    client: _Client,
    *,
    shield_filter: str | None = "Dark",
    emit: Callable[[str], None] | None = None,
) -> dict[str, bool]:
    """End-of-session safing: shield the sensor (rotate the wheel to an opaque
    position) and park the mount (stops tracking + slews home). BOTH steps are
    fail-soft — safing must never raise or mask the run result. Mirrors the
    flats panel teardown; call it from a try/finally around the capture so it
    fires on a normal guard-stop AND on a crash/Ctrl-C. Returns
    {'shielded', 'parked'} for logging/tests.

    The S30 has no mechanical shutter (HasShutter=false), so the only way to
    keep daylight off the sensor is the opaque wheel position ('Dark'); park
    also points the OTA away from the risen sun and halts tracking so the
    mount can't drive into a limit after dawn.
    """
    def _e(m: str) -> None:
        if emit is not None:
            emit(m)

    out = {"shielded": False, "parked": False}
    if shield_filter:
        try:
            if client.set_filter(shield_filter, wait=True):
                out["shielded"] = True
                _e(f"  safing: sensor shielded ('{shield_filter}' filter)")
            else:
                _e(f"  safing: '{shield_filter}' filter not confirmed — sensor "
                   "shield skipped (no opaque position on this wheel?)")
        except Exception as exc:  # noqa: BLE001 — fail-soft
            _e(f"  safing: sensor shield failed (continuing): {exc}")
    try:
        client.park()
        out["parked"] = True
        _e("  safing: mount parked (tracking stopped)")
    except Exception as exc:  # noqa: BLE001 — fail-soft
        _e(f"  safing: mount park failed (continuing): {exc}")
    return out
