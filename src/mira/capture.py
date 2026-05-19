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


@dataclass
class CaptureResult:
    captured: int = 0
    copied: int = 0
    dithers: int = 0
    recenters: int = 0
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

    # Provenance sidecar so `mira stack --auto-flats` can later match the
    # right per-filter master (the NINA FITS carry no FILTER keyword).
    from .flats import write_capture_sidecar

    write_capture_sidecar(
        dest_dir, filter=res.filter_name, gain=gain, exposure_s=exposure_s,
        ra_deg=ra_deg, dec_deg=dec_deg, target_name=target_name,
    )

    exp_tag = f"{float(exposure_s):.2f}s"
    seen = set(glob.glob(os.path.join(str(nina_root), "**", f"*{exp_tag}*.fit*"),
                         recursive=True))

    for i in range(1, n_max + 1):
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
    return res
