"""Terminal renderer for a MonitorSnapshot — what `mira status` prints.

Pure: snapshot -> string. Colour is optional (the CLI enables it on a TTY).
Kept separate from the builders so it can render a disk snapshot now and a
NINA-overlaid one later without change.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .snapshot import MonitorSnapshot

_C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "amber": "\033[33m", "green": "\033[32m",
    "cyan": "\033[36m",
}


def _paint(s: str, key: str, color: bool) -> str:
    return f"{_C[key]}{s}{_C['reset']}" if color else s


def _fmt(v, spec: str = "", dash: str = "--"):
    if v is None:
        return dash
    try:
        return format(v, spec) if spec else str(v)
    except (TypeError, ValueError):
        return str(v)


def _hms(minutes: float | None) -> str:
    if minutes is None:
        return "--"
    m = int(round(minutes))
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def _cadence_s(frames) -> float | None:
    ts = [f.timestamp_utc for f in frames if f.timestamp_utc is not None]
    if len(ts) < 2:
        return None
    ts = sorted(ts)
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    return statistics.median(gaps) if gaps else None


def render_status(snap: MonitorSnapshot, *, color: bool = False) -> str:
    now = snap.generated_utc
    s = snap.session
    frames = list(snap.recent_frames)  # newest-first
    exp = frames[0].exposure_s if frames else 0.0
    L: list[str] = []

    def head(t):
        L.append(_paint(t, "cyan", color))

    # --- header ---
    tgt = s.current_target or "(no target_name in sidecar)"
    gain = _fmt(frames[0].gain) if frames else "--"
    _last_ts = frames[0].timestamp_utc if frames else None
    elapsed = ((_last_ts - s.started_utc).total_seconds() / 60
               if (_last_ts and s.started_utc) else None)
    mode = {"disk": "frames-on-disk", "live": "live NINA",
            "stale": "stale"}.get(snap.mode, snap.mode)
    L.append(_paint(f"{tgt}", "bold", color)
             + f"  ·  {s.current_filter or '?'}/g{gain}/{exp:.0f}s"
             + f"  ·  elapsed {_hms(elapsed)}  "
             + _paint(f"[{mode}]", "dim", color))

    # --- capture ---
    head("- Capture -")
    integ = s.frame_in_filter * exp / 60.0
    cad = _cadence_s(frames)
    eff = (exp / cad * 100) if (cad and cad > 0) else None
    dither = f"every {s.dither_every}" if s.dither_every else "--"
    L.append(f"  frames {s.frame_in_filter}   integration {integ:.0f}m   "
             f"cadence {_fmt(cad, '.0f')}s ({_fmt(eff, '.0f')}% eff)   "
             f"dither {dither}")

    # --- quality (recent) ---
    head(f"- Quality (last {len(frames)}) -")
    hfrs = [f.hfr for f in frames if f.hfr is not None]
    stars = [f.stars for f in frames if f.stars is not None]
    rnds = [f.roundness for f in frames if f.roundness is not None]
    skies = [f.median for f in frames if f.median is not None]
    if hfrs:
        L.append(f"  HFR    {statistics.median(hfrs):.2f}   "
                 f"(best {min(hfrs):.2f})")
    if stars:
        L.append(f"  stars  {int(statistics.median(stars))}    "
                 f"(range {min(stars)}-{max(stars)})")
    if skies:
        L.append(f"  sky bg {statistics.median(skies):.0f}")
    if rnds:
        L.append(f"  round  {statistics.median(rnds):.2f}")
    if not frames:
        L.append(_paint("  no frames yet", "dim", color))

    # --- flags (the headline: transparency-gated assessment) ---
    if snap.anomalies:
        head("- Flags -")
        for a in snap.anomalies:
            key = "red" if a.severity == "red" else "amber"
            L.append("  " + _paint(f"⚠ {a.message}", key, color)
                     + _paint(f"  — {a.detail}", "dim", color))
    elif frames:
        head("- Flags -")
        L.append("  " + _paint("✓ no quality flags", "green", color))

    # --- sky ---
    if snap.sky is not None:
        sk = snap.sky
        head("- Sky -")
        clear = ""
        if sk.clear_of_obstruction is False:
            clear = _paint("  ⚠ behind horizon obstruction", "amber", color)
        elif sk.clear_of_obstruction is True:
            clear = " (clear of obstruction)"
        moon = ""
        if sk.moon_alt_deg is not None:
            up = sk.moon_alt_deg > 0
            moon = (f"   moon {(sk.moon_illum_frac or 0)*100:.0f}% "
                    f"{'up' if up else 'down'}")
        L.append(f"  alt {_fmt(sk.altitude_deg, '.0f')}deg "
                 f"az {_fmt(sk.azimuth_deg, '.0f')}{clear}")
        sets_txt = ("below floor" if sk.sets_in_min == 0
                    else f"sets in {_hms(sk.sets_in_min)}")
        L.append(f"  {sets_txt}   dawn in {_hms(sk.dawn_in_min)}{moon}")

    # --- devices (live NINA overlay, Phase 2) ---
    if snap.nina_reachable:
        head("- Devices -")
        cam, mt, fo, gu, fw = (snap.camera, snap.mount, snap.focuser,
                               snap.guider, snap.filter_wheel)
        ctemp = f"  {cam.temp_c:.1f}C" if cam.temp_c is not None else ""
        L.append(f"  camera {cam.state or '?'}{ctemp}")
        mstate = ("slewing" if mt.slewing else "tracking" if mt.tracking
                  else "parked" if mt.at_park else "stopped")
        pier = f"   pier {mt.pier_side}" if mt.pier_side else ""
        L.append(f"  mount  {mstate}{pier}")
        if fo.connected:
            af = ""
            if fo.last_af_hfr_before is not None and fo.last_af_hfr_after is not None:
                af = (f"   last AF {fo.last_af_hfr_before:.2f} -> "
                      f"{fo.last_af_hfr_after:.2f}")
            L.append(f"  focus  pos {_fmt(fo.position)}{af}")
        if fw.connected and fw.selected_name:
            L.append(f"  wheel  {fw.selected_name}")
        if gu.connected and gu.rms_total_arcsec is not None:
            L.append(f"  guide  RMS {gu.rms_total_arcsec:.2f}\"")
    elif snap.nina_error:
        head("- Devices -")
        L.append("  " + _paint(f"NINA: {snap.nina_error}", "dim", color))

    # --- health ---
    head("- Health -")
    last = frames[0].timestamp_utc if frames else None
    age = (now - last).total_seconds() if last else None
    if s.sequence_running:
        L.append("  " + _paint(f"capturing — last frame {_fmt(age, '.0f')}s ago",
                               "green", color))
    else:
        L.append("  " + _paint(
            f"idle / done — last frame {_hms((age or 0)/60)} ago", "dim", color))

    ts = now.astimezone().strftime("%H:%M:%S")
    L.append(_paint(f"  as of {ts}", "dim", color))
    return "\n".join(L)


def snapshot_to_json(snap: MonitorSnapshot, *, indent: int | None = None) -> str:
    """Serialize a MonitorSnapshot to JSON (datetimes -> ISO). Lets scripting
    and the webapp /monitor consume the same engine that feeds the terminal."""
    import dataclasses
    import json
    from datetime import datetime

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    return json.dumps(dataclasses.asdict(snap), default=_default, indent=indent)
