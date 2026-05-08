"""Flask web app factory.

Layers:
- Layer 1 (run + view): kick off `tonight` from a button, monitor live progress,
  view the generated session_schedule.html.
- Layer 2 (photometry): run aperture photometry on a captures directory,
  watch results stream in, download AAVSO upload file.
- Layer 3 (NINA monitor): poll NINA's Advanced API plugin for sequence state,
  current target, frame count, equipment status.

Single user, single machine, no auth. Background tasks run in a
ThreadPoolExecutor; state is in-memory. Restarting the server cancels
in-flight work, which is fine for a personal observing tool.

Storage roots (see docs/architecture.md "Storage layout" for the full diagram):
  output_dir     ─ generated session artifacts (tonight/ + archive/<DATE>/)
  captures_root  ─ NINA-captured FITS, organized as <TARGET>/<DATE>/
  state_dir      ─ webapp persistence: <run_id>.json, sessions.db,
                   settings.json, history-charts/. Configurable so
                   tests can use a temp dir.
  data/cache/    ─ HTTP response cache (always relative to cwd, shared
                   between CLI and webapp)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask

from .nina_client import NinaClient
from .runs import RunRegistry


def create_app(
    output_dir: Path | None = None,
    captures_root: Path | None = None,
    nina_base_url: str = "http://localhost:1888",
    state_dir: Path | None = None,
) -> Flask:
    here = Path(__file__).parent
    app = Flask(
        __name__,
        template_folder=str(here / "templates"),
        static_folder=str(here / "static"),
    )

    output_dir = (output_dir or Path("output/s30_pro_jc/tonight")).resolve()
    captures_root = (captures_root or Path("captures")).resolve()
    state_dir = (state_dir or Path("data/webapp_runs")).resolve()

    runs = RunRegistry(max_workers=2, state_dir=state_dir)
    nina = NinaClient(base_url=nina_base_url)

    from .db import SessionStore
    session_store = SessionStore(state_dir / "sessions.db")

    app.config["OUTPUT_DIR"] = output_dir
    app.config["CAPTURES_ROOT"] = captures_root
    app.config["STATE_DIR"] = state_dir
    app.config["RUNS"] = runs
    app.config["NINA"] = nina
    app.config["SESSION_STORE"] = session_store

    app.jinja_env.filters["human_time"] = _human_time

    from .routes import register_routes
    register_routes(app)

    return app


def _human_time(value) -> str:
    """Render a Unix timestamp or datetime as 'X min ago' / 'YYYY-MM-DD HH:MM'.
    Accepts a float (Unix epoch) or a datetime instance."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        timestamp = value.timestamp()
    else:
        timestamp = float(value)
    now = datetime.now(timezone.utc).timestamp()
    delta = now - timestamp
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)} min ago"
    if delta < 86400:
        return f"{int(delta / 3600)} hr ago"
    if delta < 7 * 86400:
        return f"{int(delta / 86400)} d ago"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
