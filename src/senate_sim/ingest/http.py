"""HTTP helper with retries and an on-disk cache.

Cache keys are derived from the URL and query parameters with secret
parameters (api_key) removed, so keys never end up in file names.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from senate_sim import config

SECRET_PARAMS = {"api_key", "key"}


def _session() -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = config.user_agent()
    return session


def _cache_path(url: str, params: dict, cache_dir: Path) -> Path:
    public = {k: v for k, v in params.items() if k not in SECRET_PARAMS}
    raw = f"{url}?{urlencode(sorted(public.items()))}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return cache_dir / f"{digest}.bin"


def cached_get(
    url: str,
    params: dict | None = None,
    cache_dir: Path = config.RAW_DIR,
    refresh: bool = False,
    timeout: int = 60,
    is_usable: Callable[[bytes], bool] | None = None,
) -> bytes:
    """Return the response body for a GET request, using the disk cache when present.

    `is_usable` decides whether a body is worth caching. A cached body that
    fails the check is ignored and re-fetched, and an unusable fresh body is
    returned but not written, so an empty answer never sticks in the cache.
    """
    params = dict(params or {})
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url, params, cache_dir)
    if path.exists() and not refresh:
        body = path.read_bytes()
        if is_usable is None or is_usable(body):
            return body
        path.unlink()

    response = _session().get(url, params=params, timeout=timeout)
    if not response.ok:
        # Never echo API keys: requests puts them in the URL of its error message.
        safe = re.sub(r"(api_key|key)=[^&]+", r"\1=REDACTED", response.url)
        raise requests.HTTPError(f"{response.status_code} {response.reason} for url: {safe}",
                                 response=response)
    if is_usable is None or is_usable(response.content):
        path.write_bytes(response.content)
    return response.content
