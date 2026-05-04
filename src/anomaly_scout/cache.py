from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

CACHE_ROOT = Path("data/cache")


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
) -> requests.Response | CachedResponse:
    cache_path = _cache_path(url, params or {}, namespace)
    if cache_path.exists():
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
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return response


def _cache_path(url: str, params: dict[str, str], namespace: str) -> Path:
    cache_key = urlencode(sorted(params.items()))
    digest = hashlib.sha256(f"{url}?{cache_key}".encode("utf-8")).hexdigest()
    return CACHE_ROOT / namespace / f"{digest}.json"
