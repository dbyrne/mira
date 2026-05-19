"""Capture tuning: take test frames across an exposure x gain grid, read
back HFR / saturation, and recommend the longest non-saturating exposure
per gain (flagging probable trailing).

This codifies the empirical dial-in we'd otherwise do ad-hoc every
imaging night: shoot a ramp, eyeball Max for clipping and HFR for
trailing, pick the exposure. The orchestrator takes an injected client
(duck-typed: needs wait_camera_idle/capture/latest_image_stats) so it's
unit-testable without NINA.

Report output is intentionally ASCII-only — non-ASCII to a Windows
cp1252 console raised UnicodeEncodeError mid-command earlier in this
project; not repeating that.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# 16-bit sensor. Treat >= SAT_LIMIT as clipped (leave headroom below full
# well so a slightly brighter star next frame doesn't silently saturate).
FULL_WELL = 65535
SAT_LIMIT = 60000
# HFR growth multiple over the shortest-exposure baseline that we call
# "probable trailing". Heuristic, deliberately loose.
TRAIL_FACTOR = 1.4


class _Client(Protocol):
    def wait_camera_idle(self, timeout_s: float = ..., poll_s: float = ...) -> bool: ...
    def capture(self, *, duration: float, gain: int | None = ..., save: bool = ...,
                solve: bool = ..., target_name: str = ..., timeout_s: float = ...) -> dict: ...
    def latest_image_stats(self) -> dict[str, Any] | None: ...


@dataclass
class FrameStat:
    gain: int | None
    exposure_s: float
    stars: int | None = None
    hfr: float | None = None
    max_adu: int | None = None
    median: float | None = None
    filename: str = ""
    error: str = ""

    @property
    def saturated(self) -> bool:
        return self.max_adu is not None and self.max_adu >= SAT_LIMIT


def _stat_value(stats: dict[str, Any], key: str) -> Any:
    v = stats.get(key)
    return v


def run_tune(
    client: _Client,
    *,
    exposures: list[float],
    gains: list[int | None],
    target_name: str = "",
    idle_timeout_s: float = 90.0,
    capture_timeout_s: float = 180.0,
    on_step: Callable[[str], None] | None = None,
) -> list[FrameStat]:
    """One test frame per (gain, exposure). Per-combo failures are captured
    on the FrameStat.error (the ramp continues — a single bad frame must
    not abort the dial-in)."""

    def _emit(msg: str) -> None:
        if on_step is not None:
            on_step(msg)

    out: list[FrameStat] = []
    for gain in gains:
        for exp in exposures:
            gtag = "default" if gain is None else str(gain)
            fs = FrameStat(gain=gain, exposure_s=exp)
            try:
                client.wait_camera_idle(timeout_s=idle_timeout_s)
                _emit(f"capture gain={gtag} exp={exp}s ...")
                client.capture(
                    duration=exp, gain=gain, save=True, solve=False,
                    target_name=target_name, timeout_s=capture_timeout_s,
                )
                # Brief settle; the just-saved frame should be newest in
                # history. Retry the read a few times for history lag.
                stats: dict[str, Any] | None = None
                for _ in range(5):
                    stats = client.latest_image_stats()
                    if stats:
                        break
                    time.sleep(0.5)
                if not stats:
                    fs.error = "no image stats returned"
                else:
                    fs.stars = _to_int(_stat_value(stats, "Stars"))
                    fs.hfr = _to_float(_stat_value(stats, "HFR"))
                    fs.max_adu = _to_int(_stat_value(stats, "Max"))
                    fs.median = _to_float(_stat_value(stats, "Median"))
                    fs.filename = str(_stat_value(stats, "Filename") or "")
            except Exception as exc:  # transport/parse: record, keep going
                fs.error = str(exc)
            out.append(fs)
            _emit(
                f"  gain={gtag} exp={exp}s -> "
                + (fs.error if fs.error else
                   f"max={fs.max_adu} hfr={fs.hfr} stars={fs.stars}"
                   + (" SAT" if fs.saturated else ""))
            )
    return out


def recommend(results: list[FrameStat]) -> dict[Any, dict[str, Any]]:
    """Per gain: the longest exposure with Max < SAT_LIMIT, plus a probable-
    trailing flag (HFR grew > TRAIL_FACTOR x the shortest-exposure HFR).
    Honest heuristic — HFR can also grow from focus/seeing, not only
    tracking; it's a flag to inspect, not a verdict."""
    by_gain: dict[Any, list[FrameStat]] = {}
    for fs in results:
        by_gain.setdefault(fs.gain, []).append(fs)

    rec: dict[Any, dict[str, Any]] = {}
    for gain, frames in by_gain.items():
        usable = sorted(
            (f for f in frames if not f.error and f.max_adu is not None),
            key=lambda f: f.exposure_s,
        )
        if not usable:
            rec[gain] = {"best_exposure_s": None, "note": "no usable frames"}
            continue
        non_sat = [f for f in usable if not f.saturated]
        best = max(non_sat, key=lambda f: f.exposure_s) if non_sat else None
        baseline_hfr = next((f.hfr for f in usable if f.hfr), None)
        trailing_from: float | None = None
        if baseline_hfr:
            for f in usable:
                if f.hfr and f.hfr > TRAIL_FACTOR * baseline_hfr:
                    trailing_from = f.exposure_s
                    break
        if best is None:
            note = f"clips at every tested exposure (>= {SAT_LIMIT} ADU); go shorter"
        elif best is usable[-1]:
            note = "longest tested exposure still unsaturated; could try longer"
        else:
            note = f"longest unsaturated tested exposure"
        rec[gain] = {
            "best_exposure_s": best.exposure_s if best else None,
            "max_at_best": best.max_adu if best else None,
            "trailing_from_s": trailing_from,
            "note": note,
        }
    return rec


def format_report(results: list[FrameStat], rec: dict[Any, dict[str, Any]]) -> str:
    """ASCII-only table + per-gain recommendation."""
    lines: list[str] = []
    lines.append("gain    exp(s)  stars   HFR    Max    median  flag")
    lines.append("-" * 56)
    for fs in results:
        gtag = "def" if fs.gain is None else str(fs.gain)
        if fs.error:
            lines.append(f"{gtag:<6} {fs.exposure_s:>6}  ERROR: {fs.error[:34]}")
            continue
        flag = "SAT" if fs.saturated else ""
        lines.append(
            f"{gtag:<6} {fs.exposure_s:>6}  "
            f"{(fs.stars if fs.stars is not None else '-'):>5}  "
            f"{(f'{fs.hfr:.2f}' if fs.hfr is not None else '-'):>5}  "
            f"{(fs.max_adu if fs.max_adu is not None else '-'):>6}  "
            f"{(f'{fs.median:.0f}' if fs.median is not None else '-'):>6}  {flag}"
        )
    lines.append("")
    lines.append("Recommendation (longest non-saturating exposure per gain):")
    for gain, r in rec.items():
        gtag = "default" if gain is None else str(gain)
        be = r.get("best_exposure_s")
        msg = f"  gain {gtag}: " + (
            f"{be}s ({r.get('note')})" if be is not None else r.get("note", "n/a")
        )
        if r.get("trailing_from_s") is not None:
            msg += f"  [probable trailing from {r['trailing_from_s']}s -- inspect]"
        lines.append(msg)
    return "\n".join(lines)


def _to_int(v: Any) -> int | None:
    try:
        return int(round(float(v))) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
