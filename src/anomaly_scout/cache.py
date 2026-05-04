from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

CACHE_ROOT = Path("data/cache")
DEFAULT_MAX_AGE_DAYS = 30


class CachedResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.text = str(payload["text"])
        self.status_code = int(payload.get("status_code", 200))
        self.headers = payload.get("headers", {})
        self.url = str(payload.get("url", ""))

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"cached HTTP {self.status_code}: {self.url}")


def cached_get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    timeout: int | float | None = None,
    namespace: str,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> requests.Response | CachedResponse:
    cache_path = _cache_path(url, params or {}, namespace)
    if cache_path.exists() and _is_fresh(cache_path, max_age_days):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return CachedResponse(payload)
        except (OSError, ValueError, KeyError):
            pass

    response = requests.get(url, params=params, timeout=timeout)
    if response.status_code < 400:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": response.url,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "text": response.text,
            "fetched_at": time.time(),
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return response


def _is_fresh(cache_path: Path, max_age_days: float) -> bool:
    if max_age_days <= 0:
        return True  # negative/zero means "no expiry"
    try:
        mtime = cache_path.stat().st_mtime
    except OSError:
        return False
    age_seconds = time.time() - mtime
    return age_seconds < max_age_days * 86400


def _cache_path(url: str, params: dict[str, str], namespace: str) -> Path:
    cache_key = urlencode(sorted(params.items()))
    digest = hashlib.sha256(f"{url}?{cache_key}".encode("utf-8")).hexdigest()
    return CACHE_ROOT / namespace / f"{digest}.json"
