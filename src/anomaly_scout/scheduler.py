"""Greedy session scheduler.

Takes a list of viable Candidates and a time window, returns an ordered
list of ScheduledTarget records that fit. Each target is allocated its
recommended exposure plan worth of integration time plus a slew buffer.

Greedy strategy:
- Iterate through the night in chronological order.
- At each decision point, pick the candidate observable now whose
  effective score (base score + setting-soon urgency bonus) is highest.
- Schedule it for its full integration time, advance the clock.
- Drop targets whose remaining observable window can no longer fit their
  integration time; drop targets that won't fit before the night ends.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Candidate, Observability
from .session_plan import recommended_exposure_plan


SLEW_BUFFER_MINUTES_DEFAULT = 3.0
TIME_STEP_MINUTES_WHEN_IDLE = 10
URGENCY_HORIZON_MINUTES = 30  # how soon a target must set to get max urgency


@dataclass
class ScheduledTarget:
    candidate: Candidate
    observability: Observability
    start_local: datetime
    end_local: datetime
    integration_minutes: int
    slew_minutes: float
    effective_score: float


@dataclass
class ScheduleResult:
    scheduled: list[ScheduledTarget]
    overflow: list[Candidate]  # viable but didn't fit
    window_start: datetime
    window_end: datetime


def build_session_schedule(
    candidates: list[Candidate],
    window_start: datetime,
    window_end: datetime,
    slew_minutes: float = SLEW_BUFFER_MINUTES_DEFAULT,
    primary_site_name: str | None = None,
) -> ScheduleResult:
    if window_end <= window_start:
        return ScheduleResult(scheduled=[], overflow=list(candidates), window_start=window_start, window_end=window_end)

    available = list(candidates)
    scheduled: list[ScheduledTarget] = []
    current_time = window_start

    while current_time < window_end and available:
        best_pick: tuple[float, Candidate, Observability, datetime, datetime, int] | None = None

        for candidate in available:
            obs = _observability_for(candidate, primary_site_name)
            if obs is None or obs.best_local_time is None or obs.minutes_above_minimum <= 0:
                continue

            obs_start, obs_end = _observable_window(obs)

            integration_min = recommended_exposure_plan(candidate.target.bright_mag)["total_min"]
            integration_dt = timedelta(minutes=integration_min)

            slot_start = max(current_time, obs_start)
            slot_end = slot_start + integration_dt

            if slot_end > obs_end or slot_end > window_end:
                continue

            time_until_set_min = (obs_end - slot_end).total_seconds() / 60.0
            urgency_bonus = max(0.0, URGENCY_HORIZON_MINUTES - time_until_set_min)
            effective_score = candidate.score + urgency_bonus

            if best_pick is None or effective_score > best_pick[0]:
                best_pick = (effective_score, candidate, obs, slot_start, slot_end, integration_min)

        if best_pick is None:
            current_time += timedelta(minutes=TIME_STEP_MINUTES_WHEN_IDLE)
            continue

        effective_score, candidate, obs, slot_start, slot_end, integration_min = best_pick
        scheduled.append(
            ScheduledTarget(
                candidate=candidate,
                observability=obs,
                start_local=slot_start,
                end_local=slot_end,
                integration_minutes=integration_min,
                slew_minutes=slew_minutes,
                effective_score=effective_score,
            )
        )
        current_time = slot_end + timedelta(minutes=slew_minutes)
        available.remove(candidate)

    return ScheduleResult(
        scheduled=scheduled,
        overflow=available,
        window_start=window_start,
        window_end=window_end,
    )


def _observability_for(candidate: Candidate, site_name: str | None) -> Observability | None:
    if site_name is None:
        return candidate.best_observability
    for obs in candidate.observabilities:
        if obs.site_name == site_name:
            return obs
    return None


def _observable_window(obs: Observability) -> tuple[datetime, datetime]:
    """Approximate the contiguous observable window from best_local_time and
    minutes_above_minimum. The real per-sample altitude data isn't carried
    on Observability today; this approximation is good enough for the
    greedy scheduler. If the approximation undershoots, we lose a few
    minutes of margin; if it overshoots, the schedule may attempt a target
    a bit past its actual setting time. Acceptable for a first version.
    """
    if obs.best_local_time is None:
        # Should be guarded by caller, but be defensive.
        raise ValueError("best_local_time is None")
    half_window = timedelta(minutes=obs.minutes_above_minimum / 2.0)
    return obs.best_local_time - half_window, obs.best_local_time + half_window


