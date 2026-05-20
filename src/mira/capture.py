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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


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


@dataclass
class CaptureResult:
    captured: int = 0
    copied: int = 0
    dithers: int = 0
    recenters: int = 0
    autofocus_runs: int = 0
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
) -> Callable[[int], str | None]:
    """Returns a predicate(frame_index) -> stop-reason str or None. Stops
    when the target drops below `alt_floor_deg` or the Sun rises above
    `sun_max_deg` (astro-twilight). Imported lazily to avoid pulling
    ephemeris into module import."""
    from .observability import sun_position

    def _guard(_i: int) -> str | None:
        now = datetime.now(timezone.utc)
        if _target_alt_deg(ra_deg, dec_deg, lat, lon, now) < alt_floor_deg:
            return f"target below {alt_floor_deg:.0f} deg altitude"
        sra, sdec = sun_position(now)
        if _target_alt_deg(sra, sdec, lat, lon, now) > sun_max_deg:
            return f"sun above {sun_max_deg:.0f} deg (astro twilight)"
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
) -> tuple[bool, float | None, str]:
    """Take one test sub, ASTAP-solve it, compare solved center to nominal.

    Returns (ok, separation_deg, message). When ASTAP can't run at all
    (no astap_cli on PATH, no star DB), or solve fails for a non-pointing
    reason (clouds, no stars), we return ok=True with the message — better
    to capture an un-verified session than refuse a session over a
    cloudy test sub. The only `ok=False` is when ASTAP solved successfully
    *and* the solved center is more than `tolerance_deg` from nominal —
    a real mount-sync drift like the 2026-05-19 M51 disaster.
    """
    import glob
    import os

    from .solve import AstapNotFound, find_astap_cli, solve_one
    from .webapp.nina_client import angular_separation_deg

    try:
        astap = find_astap_cli()
    except AstapNotFound as exc:
        emit(f"  verify-pointing skipped: {exc}")
        return True, None, f"astap_cli not found: {exc}"

    exp_tag = f"{float(exposure_s):.2f}s"
    glob_pat = os.path.join(str(nina_root), "**", f"*{exp_tag}*.fit*")
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
        return True, None, f"test capture failed: {exc}"

    after = set(glob.glob(glob_pat, recursive=True))
    new_files = after - before
    if not new_files:
        emit("  verify-pointing skipped: couldn't find new FITS in nina_root")
        return True, None, "test FITS not found"

    test_frame = Path(max(new_files, key=os.path.getmtime))
    emit(f"  test frame: {test_frame.name}; ASTAP-solving with tight hint...")
    solve_res = solve_one(
        test_frame, astap_cli=astap,
        ra_hint_deg=ra_deg, dec_hint_deg=dec_deg,
        radius_deg=5.0,
    )
    if solve_res.status != "solved":
        emit(f"  verify-pointing skipped: ASTAP {solve_res.note}")
        return True, None, f"solve failed: {solve_res.note}"

    # solve_one used -update; the FITS now carries WCS.
    from astropy.io import fits
    try:
        hdr = fits.getheader(test_frame)
        solved_ra = float(hdr["CRVAL1"])
        solved_dec = float(hdr["CRVAL2"])
    except (KeyError, OSError, ValueError) as exc:
        emit(f"  verify-pointing skipped: couldn't read WCS: {exc}")
        return True, None, f"WCS read failed: {exc}"

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
        return False, sep, msg

    emit(f"  verify-pointing OK: solved center {sep:.3f}deg from nominal "
         f"(within {tolerance_deg:.2f}deg)")
    return True, sep, f"verified {sep:.3f}deg from nominal"


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
    sidecar_audit: dict[str, Any] | None = None,
    should_continue: Callable[[int], str | None] | None = None,
    on_step: Callable[[str], None] | None = None,
    rng: random.Random | None = None,
) -> CaptureResult:
    """Capture loop. Per sub: reposition (dither around nominal, or explicit
    re-center) → wait idle → expose+save → incrementally copy the new frame
    to `dest_dir`. Stops at `n_max`, or when `should_continue(i)` returns a
    reason. Reposition slews are always `center=False`.

    `nina_root` is scanned for new `*<exposure>s*.fit*` files to copy out
    (NINA saves there; the loop owns the stable copy in `dest_dir`)."""
    rng = rng or random.Random()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    res = CaptureResult(dest_dir=str(dest_dir))

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
        "autofocus_every_min": autofocus_every_min,
        "autofocus_timeout_s": autofocus_timeout_s,
        "nina_root": str(nina_root),
        "mira_version": _mira_version,
        **(sidecar_audit or {}),
    }
    started_utc = datetime.now(timezone.utc).isoformat()

    def _persist_sidecar() -> None:
        write_capture_sidecar(
            dest_dir,
            filter=res.filter_name, gain=gain, exposure_s=exposure_s,
            ra_deg=ra_deg, dec_deg=dec_deg, target_name=target_name,
            config=effective_config,
            result={
                "captured": res.captured,
                "copied": res.copied,
                "dithers": res.dithers,
                "recenters": res.recenters,
                "autofocus_runs": res.autofocus_runs,
                "platesolve_centered": res.platesolve_centered,
                "pointing_verified": res.pointing_verified,
                "pointing_offset_deg": res.pointing_offset_deg,
                "stopped_reason": res.stopped_reason,
                "started_utc": started_utc,
                "ended_utc": datetime.now(timezone.utc).isoformat(),
            },
        )

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
        ok, sep, msg = _verify_pointing(
            client, ra_deg=ra_deg, dec_deg=dec_deg,
            exposure_s=exposure_s, gain=gain, nina_root=nina_root,
            tolerance_deg=verify_pointing_deg, emit=_emit,
        )
        res.pointing_offset_deg = sep
        if ok:
            res.pointing_verified = True
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
    # the persisted res.platesolve_centered, res.pointing_verified,
    # res.autofocus_runs reflect actual pre-loop state — not pre-pre-loop
    # zeros. The post-loop write at the end overwrites this with final
    # tallies.
    _persist_sidecar()

    exp_tag = f"{float(exposure_s):.2f}s"
    seen = set(glob.glob(os.path.join(str(nina_root), "**", f"*{exp_tag}*.fit*"),
                         recursive=True))

    for i in range(1, n_max + 1):
        # Periodic AF (wall-clock). Skipped on i==1 because pre-loop already
        # fired one moments ago; from i=2 onward we just check elapsed time.
        if af_interval_s > 0 and i > 1 and time.monotonic() >= next_af_at:
            _try_autofocus(f"+{autofocus_every_min}min")
        if should_continue is not None:
            reason = should_continue(i)
            if reason:
                res.stopped_reason = reason
                _emit(f"stop: {reason} (after {res.captured} subs)")
                break

        # Reposition. Dither (every `dither_every` subs) is relative to the
        # FIXED nominal coords -> also re-centers. Explicit re-center only
        # matters when not dithering or dithering sparsely.
        do_dither = dither_arcsec > 0 and ((i - 1) % max(dither_every, 1) == 0)
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

        for p in glob.glob(os.path.join(str(nina_root), "**", f"*{exp_tag}*.fit*"),
                           recursive=True):
            if p not in seen:
                seen.add(p)
                try:
                    shutil.copy2(p, dest_dir)
                    res.copied += 1
                except OSError:
                    pass

        if i == 1 or i % 15 == 0:
            _emit(f"  {i}/{n_max}: captured={res.captured} copied={res.copied} "
                  f"dithers={res.dithers}")

    if not res.stopped_reason:
        res.stopped_reason = f"reached n_max={n_max}"
    _persist_sidecar()
    return res
