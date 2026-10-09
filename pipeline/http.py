"""Minimal read-only HTTP client with retries, exponential backoff and polite rate limiting.

Only GET requests are ever issued. No credentials are used or accepted.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

from . import log


class HttpError(Exception):
    def __init__(self, url: str, status: int | None, detail: str):
        super().__init__(f"{status} {url}: {detail}")
        self.url, self.status, self.detail = url, status, detail


class Client:
    RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, settings: dict, sleep=time.sleep):
        h = settings["http"]
        self.timeout = h["timeout_seconds"]
        self.max_retries = h["max_retries"]
        self.backoff = h["backoff_base_seconds"]
        self.min_interval = h["min_interval_seconds"]
        self.ua = h["user_agent"]
        self._last = 0.0
        self._sleep = sleep
        self.requests = 0
        self.failures = 0

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    def get_json(self, base: str, path: str, params: dict | None = None):
        qs = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            qs = "?" + urllib.parse.urlencode(clean, doseq=True)
        url = base.rstrip("/") + path + qs
        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as e:
                status = e.code
                detail = e.read()[:300].decode("utf-8", "replace") if hasattr(e, "read") else str(e)
                retry_after = None
                try:
                    retry_after = float(e.headers.get("Retry-After")) if e.headers else None
                except (TypeError, ValueError):
                    pass
                if status not in self.RETRYABLE or attempt > self.max_retries:
                    self.failures += 1
                    raise HttpError(url, status, detail) from None
                delay = retry_after or self.backoff ** attempt + random.uniform(0, 0.5)
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                if attempt > self.max_retries:
                    self.failures += 1
                    raise HttpError(url, None, repr(e)) from None
                delay = self.backoff ** attempt + random.uniform(0, 0.5)
            log.warn("http_retry", url=url, attempt=attempt, delay=round(delay, 2))
            self._sleep(delay)
