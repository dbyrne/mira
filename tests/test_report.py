"""Report-writer tests.

The packet's per-site "(best)" heading must follow the canonical score-best
site (candidate.best_site_name — the same site the unified CSV's
primary_site column reflects), not the list-order/geometric best.
CLAUDE.md explicitly forbids divergent "best" semantics in display.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mira.models import Candidate, Observability, VsxTarget
from mira.report import write_candidate_packet


def _target() -> VsxTarget:
    return VsxTarget(
        oid=1, name="RR Lyr", var_type="RRAB", bright_mag=7.06, faint_mag=8.12,
        bright_band="V", faint_band="V", faint_is_amplitude=False,
        period_days=0.5668, spectral_type="A-F", ra_deg=291.366, dec_deg=42.785,
    )


def _obs(site: str, max_alt: float, minutes: int) -> Observability:
    return Observability(
        site_name=site, max_altitude_deg=max_alt, minutes_above_minimum=minutes,
        best_local_time=datetime(2026, 6, 12, 23, 0),
        best_night_date=date(2026, 6, 12),
        galactic_latitude_deg=12.3,
    )


class PacketBestSiteHeadingTests(TestCase):
    def test_best_suffix_follows_score_best_site_not_list_order(self) -> None:
        # observabilities[0] is the geometric best (most minutes / highest
        # altitude), but the canonical best site is by SCORE: best_site_name.
        # The packet heading must tag the latter.
        candidate = Candidate(
            target=_target(),
            observabilities=[
                _obs("Fairbanks", 80.0, 300),   # geometric best, NOT score-best
                _obs("Jersey City", 60.0, 120),
            ],
            score=25.0,
            reasons=["test reason"],
            best_site_name="Jersey City",
            site_scores={"Fairbanks": 20.0, "Jersey City": 25.0},
            site_reasons={"Fairbanks": [], "Jersey City": []},
        )
        with TemporaryDirectory() as tmp:
            path = write_candidate_packet(candidate, Path(tmp))
            text = path.read_text(encoding="utf-8")
        self.assertIn("## Observability from Jersey City (best)", text)
        self.assertNotIn("## Observability from Fairbanks (best)", text)
        # Fairbanks still gets its own (untagged) section.
        self.assertIn("## Observability from Fairbanks\n", text)

    def test_single_site_without_best_site_name_still_tagged(self) -> None:
        # best_site_name unset (manually-built candidates): fall back to the
        # best_observability property's resolution — observabilities[0].
        candidate = Candidate(
            target=_target(),
            observabilities=[_obs("Solo Site", 70.0, 200)],
            score=10.0,
            reasons=[],
        )
        with TemporaryDirectory() as tmp:
            path = write_candidate_packet(candidate, Path(tmp))
            text = path.read_text(encoding="utf-8")
        self.assertIn("## Observability from Solo Site (best)", text)
