"""Bright-transient source: Rochester Astronomy's "Latest Supernovae" page.

Rochester maintains an HTML table of every active supernova brighter than
mag 17 — already curated to the amateur-observable set, with magnitude,
type, host, and (inside each row's wikisky link) decimal J2000 coordinates.
We scrape that one table. No API key, no registration.

This is a scrape of a hand-maintained page, so the parser is deliberately
defensive: a row it can't make sense of is skipped, never fatal. If
Rochester changes the layout, `parse_active_supernovae` returns fewer (or
zero) rows and the CLI reports that honestly instead of crashing.

A representative row (verbatim from the page):

    <tr><td><a href="#2026fov" target="_self">2026fov</a></td><td>14.0</td>
    <td>II</td><td><a href="http://www.wikisky.org/?ra=22.474234&de=30.298462
    &zoom=10&show_box=1&box_width=50">NGC 7292</a></td></tr>

Stale rows mark the magnitude with a trailing ``*`` (last obs > 1 month
old); hostless rows still carry coordinates (host label "none"/"anonymous").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..cache import cached_get

ROCHESTER_URL = "https://www.rochesterastronomy.org/supernova.html"

# Text that anchors the one table we parse (there are many tables on the
# 3 MB page — per-object detail blocks, novae, etc.; we want only this one).
_TABLE_MARKER = "All active supernova over mag"

# One data row: name-cell <a>, mag cell, type cell, host cell (raw, holds
# the wikisky link with coords). The header row uses <th> so it never
# matches (this requires <td><a>).
_ROW_RE = re.compile(
    r"<tr>\s*<td>\s*<a\b[^>]*>([^<]+)</a>\s*</td>"   # 1: name
    r"\s*<td>([^<]*)</td>"                            # 2: mag cell (e.g. 14.0 / 15.4*)
    r"\s*<td>([^<]*)</td>"                            # 3: type
    r"\s*<td>(.*?)</td>\s*</tr>",                     # 4: host cell (has the coord link)
    re.IGNORECASE | re.DOTALL,
)
_COORD_RE = re.compile(r"[?&]ra=(-?[\d.]+)&de=(-?[\d.]+)", re.IGNORECASE)
_HOST_RE = re.compile(r"<a\b[^>]*>([^<]+)</a>", re.IGNORECASE)
_MAG_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Transient:
    """One row from the active-supernovae table.

    ``magnitude`` is Rochester's current/brightest figure; ``mag_stale`` is
    True when the page flagged the last observation as over a month old
    (the ``*`` marker) — the single most important freshness signal, since
    a transient a year past peak (e.g. SN 2025mvn) has long faded.
    """
    name: str            # designation, e.g. "2026fov" / "AT2026nma"
    magnitude: float     # current/brightest magnitude from the table
    mag_stale: bool      # last observation > 1 month old (Rochester's *)
    sn_type: str         # "Ia", "II", "Ic", "unk", ...
    host: str            # host label; "none"/"anonymous" when unknown
    ra_deg: float
    dec_deg: float


def parse_active_supernovae(html: str) -> list[Transient]:
    """Parse the 'active supernovae over mag 17' table out of the page HTML.
    Returns [] if the marker/table can't be found (layout drift) — the
    caller treats that as 'source unavailable', not a crash."""
    marker = html.find(_TABLE_MARKER)
    if marker == -1:
        return []
    tstart = html.find("<table", marker)
    if tstart == -1:
        return []
    tend = html.find("</table>", tstart)
    table = html[tstart: tend if tend != -1 else len(html)]

    out: list[Transient] = []
    for match in _ROW_RE.finditer(table):
        transient = _parse_row(*match.groups())
        if transient is not None:
            out.append(transient)
    return out


def fetch_active_supernovae(
    *, timeout: float = 20.0, max_age_days: float = 0.25,
) -> list[Transient]:
    """Fetch + parse the live page. Cached briefly (default ~6 h) so repeat
    runs in one session don't re-hit the server, but a transient's
    magnitude is volatile so the TTL is short. Raises on HTTP >= 400."""
    response = cached_get(
        ROCHESTER_URL, timeout=timeout, namespace="transients",
        max_age_days=max_age_days,
    )
    response.raise_for_status()
    return parse_active_supernovae(response.text)


def _parse_row(
    name_raw: str, mag_cell: str, type_cell: str, host_cell: str,
) -> Transient | None:
    name = _clean(name_raw)
    if not name:
        return None
    mag_match = _MAG_RE.search(mag_cell or "")
    if not mag_match:
        return None  # no parseable magnitude → can't rank, skip
    try:
        magnitude = float(mag_match.group(0))
    except ValueError:
        return None
    coord = _COORD_RE.search(host_cell or "")
    if not coord:
        return None  # no coordinates → can't compute observability, skip
    try:
        # wikisky's ?ra= is in decimal HOURS (de= is decimal degrees) —
        # e.g. NGC 7292 is ra=22.474234 (= 22h28m = 337.1°). Convert to
        # degrees here so the rest of Mira gets consistent J2000 degrees.
        ra_deg = float(coord.group(1)) * 15.0
        dec_deg = float(coord.group(2))
    except ValueError:
        return None
    if not (0.0 <= ra_deg <= 360.0 and -90.0 <= dec_deg <= 90.0):
        return None
    host_match = _HOST_RE.search(host_cell or "")
    host = _clean(host_match.group(1)) if host_match else ""
    return Transient(
        name=name,
        magnitude=magnitude,
        mag_stale="*" in (mag_cell or ""),
        sn_type=_clean(type_cell) or "?",
        host=host or "?",
        ra_deg=ra_deg,
        dec_deg=dec_deg,
    )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()
