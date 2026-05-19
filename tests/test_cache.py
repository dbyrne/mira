"""cached_get hardening: a missing/zero timeout must never become
requests' infinite wait (a flaky-field-internet hang). Mocks requests at
the cache module boundary; CACHE_ROOT is redirected to a tmp dir so the
real disk cache is untouched."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from mira import cache
from mira.cache import DEFAULT_TIMEOUT_SECONDS, cached_get


def _resp() -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.text = "ok"
    r.url = "http://x"
    r.headers = {}
    return r


class CachedGetTimeoutTests(TestCase):
    def _call(self, **kw):
        with TemporaryDirectory() as d:
            with patch.object(cache, "CACHE_ROOT", Path(d)):
                with patch.object(cache.requests, "get",
                                   return_value=_resp()) as g:
                    cached_get("http://x", namespace="t", **kw)
            return g

    def test_none_timeout_coerced_to_default(self) -> None:
        g = self._call(timeout=None)
        self.assertEqual(g.call_args.kwargs["timeout"], DEFAULT_TIMEOUT_SECONDS)

    def test_zero_timeout_coerced_to_default(self) -> None:
        g = self._call(timeout=0)
        self.assertEqual(g.call_args.kwargs["timeout"], DEFAULT_TIMEOUT_SECONDS)

    def test_explicit_timeout_passes_through(self) -> None:
        g = self._call(timeout=7)
        self.assertEqual(g.call_args.kwargs["timeout"], 7)

    def test_default_is_finite(self) -> None:
        self.assertIsInstance(DEFAULT_TIMEOUT_SECONDS, (int, float))
        self.assertGreater(DEFAULT_TIMEOUT_SECONDS, 0)
