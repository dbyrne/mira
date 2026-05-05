"""HTML rendering of the session schedule.

Produces a single, self-contained session_schedule.html file:
- Mobile-first responsive layout
- Red-light dark mode by default (night-vision friendly)
- One-click day mode toggle
- Collapsible per-target details (native HTML <details>/<summary>)
- Big tappable AAVSO chart buttons
- Sticky session header
- No external CSS, no fonts, no JS frameworks - one file you can AirDrop to your phone
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .scheduler import ScheduledTarget, ScheduleResult
from .session_plan import (
    MagnitudeSummary,
    dec_to_dms,
    expected_magnitude_summary,
    ra_to_hms,
    recommended_exposure_plan,
    vsp_chart_url,
)


CSS = """
:root {
  --bg: #0a0000;
  --fg: #ff4d4d;
  --fg-dim: #b03030;
  --accent: #ff8888;
  --card-bg: #160404;
  --card-border: #5a1010;
  --link: #ff9966;
  --button-bg: #401010;
  --button-fg: #ffaaaa;
  --table-stripe: #1a0606;
  --code-bg: #200808;
}
body.day-mode {
  --bg: #f7f5f0;
  --fg: #1f1f1f;
  --fg-dim: #555;
  --accent: #b8462a;
  --card-bg: #ffffff;
  --card-border: #d8cfc4;
  --link: #2664c8;
  --button-bg: #1f2a44;
  --button-fg: #ffffff;
  --table-stripe: #efebe2;
  --code-bg: #efeae0;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 16px;
  line-height: 1.5;
}
header.session-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--card-border);
  padding: 0.75rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
header.session-header h1 {
  font-size: 1.1rem;
  margin: 0;
  font-weight: 600;
}
header.session-header .meta {
  font-size: 0.85rem;
  color: var(--fg-dim);
}
.theme-toggle {
  background: var(--button-bg);
  color: var(--button-fg);
  border: 1px solid var(--card-border);
  padding: 0.4rem 0.8rem;
  border-radius: 999px;
  font-size: 0.85rem;
  cursor: pointer;
}
main { padding: 1rem; max-width: 900px; margin: 0 auto; }
section.quick-glance {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 1.5rem;
  overflow-x: auto;
}
section.quick-glance h2 {
  font-size: 1rem;
  margin: 0 0 0.5rem 0;
  color: var(--fg-dim);
}
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { padding: 0.4rem 0.5rem; text-align: left; }
tr:nth-child(even) { background: var(--table-stripe); }
th { color: var(--fg-dim); font-weight: 600; border-bottom: 1px solid var(--card-border); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
article.target-card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 12px;
  margin-bottom: 1.25rem;
  padding: 1rem;
  scroll-margin-top: 64px;
}
article.target-card > header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  align-items: baseline;
  border-bottom: 1px dashed var(--card-border);
  padding-bottom: 0.6rem;
  margin-bottom: 0.75rem;
}
article.target-card .time {
  font-weight: 700;
  font-size: 1.15rem;
  color: var(--accent);
}
article.target-card h2 {
  margin: 0;
  font-size: 1.15rem;
  flex: 1 1 auto;
}
article.target-card .quick-stats {
  display: flex;
  gap: 0.75rem;
  font-size: 0.95rem;
  color: var(--fg-dim);
}
.headline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.4rem 1rem;
  margin: 0.5rem 0 0.75rem;
}
.headline-grid div { font-size: 0.95rem; }
.headline-grid strong { color: var(--accent); }
.sparkline-line {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 1rem;
  letter-spacing: 1px;
}
.comp-bracket {
  background: var(--button-bg);
  color: var(--button-fg);
  display: inline-block;
  padding: 0.45rem 0.7rem;
  border-radius: 6px;
  font-size: 0.95rem;
  margin: 0.4rem 0;
}
.action-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.6rem 0; }
.btn {
  display: inline-block;
  background: var(--button-bg);
  color: var(--button-fg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  padding: 0.65rem 1rem;
  font-size: 0.95rem;
  text-decoration: none;
  font-weight: 600;
  min-height: 44px;
  line-height: 1.3;
}
.btn:hover { text-decoration: underline; }
details { margin: 0.5rem 0; }
details > summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--fg-dim);
  padding: 0.4rem 0;
  list-style: none;
}
details > summary::before { content: "▸ "; color: var(--accent); }
details[open] > summary::before { content: "▾ "; }
details > summary:hover { color: var(--fg); }
details > div, details > p, details > ul, details > table {
  margin: 0.4rem 0 0.6rem 0;
  padding-left: 1rem;
}
ul { padding-left: 1.2rem; }
li { margin: 0.2rem 0; }
code { background: var(--code-bg); padding: 0.05rem 0.3rem; border-radius: 3px; font-size: 0.9em; }
.reasons li { font-size: 0.9rem; }
.history-table { font-size: 0.85rem; }
section.overflow {
  margin-top: 2rem;
  padding-top: 1rem;
  border-top: 1px solid var(--card-border);
}
section.overflow h2 { font-size: 1rem; color: var(--fg-dim); }
section.overflow ul { font-size: 0.9rem; }
footer.workflow {
  margin-top: 2rem;
  padding: 1rem;
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 8px;
  font-size: 0.9rem;
}
footer.workflow h2 { font-size: 1rem; margin: 0 0 0.5rem 0; color: var(--fg-dim); }
.flag-anomaly {
  background: var(--button-bg);
  color: var(--button-fg);
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 600;
  margin-left: 0.4rem;
}
@media (max-width: 600px) {
  header.session-header h1 { font-size: 1rem; }
  article.target-card .time { font-size: 1rem; }
  article.target-card h2 { font-size: 1rem; }
}
"""

THEME_TOGGLE_JS = """
(function(){
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', function(){
    document.body.classList.toggle('day-mode');
    btn.textContent = document.body.classList.contains('day-mode') ? '🌙 Night' : '☀ Day';
  });
})();
"""


def write_session_schedule_html(
    schedule: ScheduleResult,
    output_dir: Path,
    config: Any,
    metadata: dict | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "session_schedule.html"

    site = config.sites[0]
    duration = (schedule.window_end - schedule.window_start).total_seconds() / 3600.0
    total_integration = sum(t.integration_minutes for t in schedule.scheduled)
    total_slew = sum(t.slew_minutes for t in schedule.scheduled[:-1]) if len(schedule.scheduled) > 1 else 0.0
    metadata = metadata or {}

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=2">',
        f"<title>{html.escape(schedule.window_start.strftime('%Y-%m-%d'))} session</title>",
        "<style>",
        CSS,
        "</style>",
        "</head>",
        "<body>",
        '<header class="session-header">',
        "<div>",
        f'<h1>{html.escape(schedule.window_start.strftime("%a %b %d, %Y"))} from {html.escape(site.name)}</h1>',
        f'<div class="meta">'
        f'{html.escape(schedule.window_start.strftime("%H:%M"))}–'
        f'{html.escape(schedule.window_end.strftime("%H:%M %Z"))} '
        f'· {len(schedule.scheduled)} targets · {duration:.1f}h window '
        f'· {total_integration} min integration</div>',
        "</div>",
        '<div style="display:flex;gap:0.5rem;align-items:center;">',
        '<a href="/" class="theme-toggle" title="Back to dashboard (when served via webapp)">← Dashboard</a>',
        '<button id="theme-toggle" class="theme-toggle">☀ Day</button>',
        '</div>',
        "</header>",
        "<main>",
    ]

    parts.append(render_schedule_main_html(schedule))

    parts.extend(
        [
            "</main>",
            f"<script>{THEME_TOGGLE_JS}</script>",
            "</body>",
            "</html>",
        ]
    )
    html_path.write_text("\n".join(parts), encoding="utf-8")
    return html_path


def render_schedule_main_html(schedule: ScheduleResult) -> str:
    """Return the HTML for the schedule body content (inside <main>).
    Used by the standalone HTML writer AND the Flask /schedule route, which
    embeds the same content inside the webapp base layout."""
    parts: list[str] = []
    if schedule.scheduled:
        parts.append(_render_quick_glance(schedule))
        for index, scheduled in enumerate(schedule.scheduled, start=1):
            parts.append(_render_target_card(index, scheduled))
    else:
        parts.append('<section class="quick-glance"><p>No targets scheduled in this window.</p></section>')

    if schedule.overflow:
        parts.append(_render_overflow(schedule))

    parts.append(_render_footer())
    return "\n".join(parts)


def render_schedule_summary_html(schedule: ScheduleResult, site_name: str) -> str:
    """One-line summary HTML for embedding above the schedule content (used
    by /schedule when the page is wrapped in webapp chrome that doesn't
    duplicate the session header)."""
    duration = (schedule.window_end - schedule.window_start).total_seconds() / 3600.0
    total_integration = sum(t.integration_minutes for t in schedule.scheduled)
    return (
        '<section class="card">'
        f'<h2>{html.escape(schedule.window_start.strftime("%a %b %d, %Y"))} from {html.escape(site_name)}</h2>'
        f'<p class="meta">'
        f'{html.escape(schedule.window_start.strftime("%H:%M"))}–'
        f'{html.escape(schedule.window_end.strftime("%H:%M %Z"))} '
        f'· {len(schedule.scheduled)} targets · {duration:.1f}h window '
        f'· {total_integration} min integration'
        '</p>'
        '</section>'
    )


def _render_quick_glance(schedule: ScheduleResult) -> str:
    rows = []
    for index, scheduled in enumerate(schedule.scheduled, start=1):
        target = scheduled.candidate.target
        plan = recommended_exposure_plan(target.bright_mag)
        slot = (
            f"{scheduled.start_local.strftime('%H:%M')}–"
            f"{scheduled.end_local.strftime('%H:%M')}"
        )
        mag_text = f"{target.bright_mag:.2f}" if target.bright_mag is not None else "n/a"
        rows.append(
            f"<tr>"
            f"<td>{html.escape(slot)}</td>"
            f'<td><a href="#t{index}">{html.escape(target.name)}</a></td>'
            f"<td>{html.escape(mag_text)}</td>"
            f"<td>{html.escape(target.var_type or 'blank')}</td>"
            f"<td>{plan['frames']}×{plan['exposure_s']}s</td>"
            f"</tr>"
        )
    return (
        '<section class="quick-glance">'
        "<h2>Schedule</h2>"
        "<table>"
        "<thead><tr><th>Time</th><th>Target</th><th>Mag</th><th>Type</th><th>Plan</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table>"
        "</section>"
    )


def _render_target_card(index: int, scheduled: ScheduledTarget) -> str:
    candidate = scheduled.candidate
    target = candidate.target
    obs = scheduled.observability
    plan = recommended_exposure_plan(target.bright_mag)
    slot = (
        f"{scheduled.start_local.strftime('%H:%M')}–"
        f"{scheduled.end_local.strftime('%H:%M')}"
    )

    aavso = candidate.aavso
    mag_summary = expected_magnitude_summary(target, aavso)

    bits = [
        f'<article class="target-card" id="t{index}">',
        "<header>",
        f'<span class="time">{html.escape(slot)}</span>',
        f"<h2>{index}. {html.escape(target.name)}</h2>",
        '<span class="quick-stats">',
        f"Score {candidate.score:.1f}",
        " · ",
        f"{plan['frames']}×{plan['exposure_s']}s",
        f" = {plan['total_min']} min",
        "</span>",
        "</header>",
        '<div class="headline-grid">',
    ]

    expected_text = (
        f"~{mag_summary.expected_mag:.2f}" if mag_summary.expected_mag is not None else "n/a"
    )
    range_text = ""
    if mag_summary.range_min is not None and mag_summary.range_max is not None:
        range_text = (
            f" <span style='color:var(--fg-dim)'>({mag_summary.range_min:.2f}–{mag_summary.range_max:.2f})</span>"
        )
    bits.append(f"<div><strong>Expected mag:</strong> {expected_text}{range_text}</div>")
    bits.append(f"<div><strong>Type:</strong> {html.escape(target.var_type or 'blank')}</div>")
    if target.period_days is not None:
        bits.append(f"<div><strong>Period:</strong> {target.period_days:.3f} d</div>")
    bits.append(f"<div><strong>Max alt tonight:</strong> {obs.max_altitude_deg:.1f}°</div>")
    bits.append(f"<div><strong>Best moment:</strong> {obs.best_local_time.strftime('%H:%M') if obs.best_local_time else 'n/a'}</div>")
    bits.append(f"<div><strong>RA / Dec:</strong> <code>{html.escape(ra_to_hms(target.ra_deg))}</code> / <code>{html.escape(dec_to_dms(target.dec_deg))}</code></div>")
    bits.append("</div>")

    if mag_summary.sparkline:
        bits.append(
            f'<div class="sparkline-line"><span style="color:var(--fg-dim)">brighter</span> '
            f"{html.escape(mag_summary.sparkline)} "
            f'<span style="color:var(--fg-dim)">fainter</span></div>'
        )
    if mag_summary.comp_low_label and mag_summary.comp_high_label:
        bits.append(
            f'<div class="comp-bracket">At the chart, bracket your estimate against '
            f"comps near mag {mag_summary.comp_low_label} and mag {mag_summary.comp_high_label}.</div>"
        )

    bits.append('<div class="action-row">')
    bits.append(
        f'<a class="btn" href="{html.escape(vsp_chart_url(target.name))}" target="_blank" rel="noopener">📊 AAVSO chart</a>'
    )
    bits.append(
        f'<a class="btn" href="{html.escape(target.vsx_url)}" target="_blank" rel="noopener">VSX details</a>'
    )
    if candidate.simbad and candidate.simbad.status == "ok" and candidate.simbad.url:
        bits.append(
            f'<a class="btn" href="{html.escape(candidate.simbad.url)}" target="_blank" rel="noopener">SIMBAD</a>'
        )
    bits.append("</div>")

    bits.append("<details><summary>Catalog</summary><div>")
    bits.append("<ul>")
    bits.append(f"<li>VSX type: <code>{html.escape(target.var_type or 'blank')}</code></li>")
    bits.append(
        f"<li>Catalog photometry range: <code>{_fmt(target.max_mag)}</code> to "
        f"<code>{_fmt(target.min_mag)}</code> mag</li>"
    )
    bits.append(f"<li>Catalog amplitude: <code>{_fmt(target.catalog_amplitude)}</code> mag</li>")
    bits.append(f"<li>Spectral type: <code>{html.escape(target.spectral_type or 'blank')}</code></li>")
    bits.append(f"<li>Galactic latitude: <code>{obs.galactic_latitude_deg:.1f}°</code></li>")
    bits.append("</ul>")
    bits.append("</div></details>")

    if candidate.reasons:
        bits.append("<details><summary>Why on the queue</summary>")
        bits.append('<ul class="reasons">')
        for reason in candidate.reasons:
            bits.append(f"<li>{html.escape(reason)}</li>")
        bits.append("</ul></details>")

    if aavso is not None:
        bits.append(_render_aavso_section(aavso))
    if candidate.simbad is not None:
        bits.append(_render_simbad_section(candidate.simbad))
    if candidate.gaia is not None:
        bits.append(_render_gaia_section(candidate.gaia))
    if candidate.ztf is not None:
        bits.append(_render_ztf_section(candidate.ztf))

    bits.append("</article>")
    return "\n".join(bits)


def _render_aavso_section(aavso) -> str:
    if aavso.status not in ("ok", "ok-cached"):
        return (
            "<details><summary>AAVSO recent coverage</summary>"
            f"<p>Status: <code>{html.escape(aavso.status)}</code></p>"
            f"<p>{html.escape(aavso.note or 'No data available.')}</p>"
            "</details>"
        )
    parts = [
        "<details open><summary>AAVSO recent coverage</summary><div>",
        f"<p>Recent observations: <strong>{aavso.recent_observations}</strong>",
    ]
    if aavso.recent_median_mag is not None:
        rng = ""
        if aavso.recent_min_mag is not None and aavso.recent_max_mag is not None:
            rng = f" (range {aavso.recent_min_mag:.2f}–{aavso.recent_max_mag:.2f})"
        parts.append(f" · median <strong>{aavso.recent_median_mag:.2f}</strong>{rng}")
    parts.append("</p>")

    if aavso.last_observation_jd is not None:
        last_iso = _jd_to_iso(aavso.last_observation_jd) or ""
        if last_iso:
            parts.append(f"<p>Last observed: <code>{html.escape(last_iso)}</code></p>")

    if aavso.derived_period_days is not None:
        parts.append(
            f"<p>AAVSO Lomb-Scargle period: <code>{aavso.derived_period_days:.4f}</code> d "
            f"(power {_fmt(aavso.period_power, 3)})"
        )
        if aavso.period_disagrees is True:
            parts.append('<span class="flag-anomaly">disagrees with catalog</span>')
        elif aavso.period_disagrees is False:
            parts.append(" — agrees with catalog within tolerance")
        elif aavso.period_note:
            parts.append(f" — not assessable ({html.escape(aavso.period_note)})")
        parts.append("</p>")

    if aavso.recent_samples:
        parts.append('<table class="history-table">')
        parts.append("<thead><tr><th>Date</th><th>JD</th><th>Mag</th><th>Band</th></tr></thead>")
        parts.append("<tbody>")
        for jd, mag, band in aavso.recent_samples:
            iso = _jd_to_iso(jd) or ""
            parts.append(
                f"<tr><td>{html.escape(iso)}</td><td>{jd:.4f}</td>"
                f"<td>{mag:.2f}</td><td>{html.escape(band or 'V')}</td></tr>"
            )
        parts.append("</tbody></table>")
    parts.append("</div></details>")
    return "\n".join(parts)


def _render_simbad_section(simbad) -> str:
    if simbad.status != "ok":
        return (
            "<details><summary>SIMBAD context</summary>"
            f"<p>Status: <code>{html.escape(simbad.status)}</code></p>"
            "</details>"
        )
    bits = [
        "<details><summary>SIMBAD context</summary><div><ul>",
        f"<li>Main ID: <code>{html.escape(simbad.main_id or 'n/a')}</code></li>",
        f"<li>Object type: <code>{html.escape(simbad.object_type or 'n/a')}</code></li>",
        f"<li>Match separation: <code>{_fmt(simbad.separation_arcsec)}</code> arcsec</li>",
    ]
    if simbad.identifiers:
        bits.append("<li>Other IDs: " + ", ".join(f"<code>{html.escape(i)}</code>" for i in simbad.identifiers) + "</li>")
    bits.append("</ul></div></details>")
    return "\n".join(bits)


def _render_gaia_section(gaia) -> str:
    if gaia.status != "ok":
        return (
            "<details><summary>Gaia DR3 context</summary>"
            f"<p>Status: <code>{html.escape(gaia.status)}</code></p>"
            "</details>"
        )
    bits = [
        "<details><summary>Gaia DR3 context</summary><div><ul>",
        f"<li>Source ID: <code>{html.escape(gaia.source_id or 'n/a')}</code></li>",
        f"<li>G mag: <code>{_fmt(gaia.g_mag)}</code> · BP-RP: <code>{_fmt(gaia.bp_rp)}</code></li>",
        f"<li>Parallax: <code>{_fmt(gaia.parallax_mas)}</code> mas · RUWE: <code>{_fmt(gaia.ruwe)}</code></li>",
    ]
    if gaia.ipd_frac_multi_peak is not None:
        flag = ""
        if gaia.ipd_frac_multi_peak > 0.1:
            flag = ' <span class="flag-anomaly">PSF blended</span>'
        bits.append(f"<li>IPD multi-peak: <code>{gaia.ipd_frac_multi_peak:.3f}</code>{flag}</li>")
    if gaia.color_anomaly:
        bits.append(f'<li><span class="flag-anomaly">Color anomaly</span> {html.escape(gaia.color_anomaly)}</li>')
    bits.append("</ul></div></details>")
    return "\n".join(bits)


def _render_ztf_section(ztf) -> str:
    if ztf.status not in ("ok", "ok-cached"):
        return (
            "<details><summary>ZTF light curve</summary>"
            f"<p>Status: <code>{html.escape(ztf.status)}</code></p>"
            "</details>"
        )
    bits = [
        "<details><summary>ZTF light curve</summary><div><ul>",
        f"<li>Observations: <code>{ztf.observations}</code></li>",
        f"<li>Median mag: <code>{_fmt(ztf.median_mag)}</code> · "
        f"5–95 percentile amp: <code>{_fmt(ztf.amplitude_mag)}</code> mag</li>",
    ]
    if ztf.derived_period_days is not None:
        flag = ""
        if ztf.period_disagrees is True:
            flag = ' <span class="flag-anomaly">disagrees with catalog</span>'
        bits.append(
            f"<li>Lomb-Scargle period: <code>{ztf.derived_period_days:.4f}</code> d "
            f"(power {_fmt(ztf.period_power, 3)}){flag}</li>"
        )
    bits.append("</ul></div></details>")
    return "\n".join(bits)


def _render_overflow(schedule: ScheduleResult) -> str:
    items = []
    for candidate in schedule.overflow:
        target = candidate.target
        obs = candidate.best_observability
        best_time = obs.best_local_time.strftime("%H:%M") if obs.best_local_time else "n/a"
        mag = f"{target.bright_mag:.2f}" if target.bright_mag is not None else "n/a"
        items.append(
            f"<li><strong>{html.escape(target.name)}</strong> "
            f"(score {candidate.score:.1f}, type {html.escape(target.var_type or 'blank')}, "
            f"mag {mag}, peaks {best_time})</li>"
        )
    return (
        '<section class="overflow">'
        f"<h2>Overflow ({len(schedule.overflow)} candidates not in tonight's plan)</h2>"
        f"<ul>{''.join(items)}</ul>"
        "</section>"
    )


def _render_footer() -> str:
    return (
        '<footer class="workflow">'
        "<h2>Workflow reminder</h2>"
        "<ol>"
        "<li>Polar-align the wedge using the Seestar app's PA routine.</li>"
        "<li>Import <code>nina_targets.csv</code> into NINA Target Scheduler (rows already in execution order).</li>"
        "<li>Run the sequence; per-target slew → plate-solve → exposure plan.</li>"
        "<li>Morning: <code>anomaly-scout submit</code> per target with comp-star JSON to produce AAVSO upload file.</li>"
        '<li>Inspect, then upload at <a href="https://www.aavso.org/webobs/file" target="_blank" rel="noopener">aavso.org/webobs/file</a>.</li>'
        "</ol>"
        "</footer>"
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _jd_to_iso(jd: float | None) -> str | None:
    if jd is None:
        return None
    from datetime import datetime, timezone

    unix_secs = (jd - 2440587.5) * 86400
    try:
        return datetime.fromtimestamp(unix_secs, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None
