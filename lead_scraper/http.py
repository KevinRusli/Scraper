"""Small HTTP helper with a proper User-Agent and retry/backoff."""

from __future__ import annotations

import os
import time
from typing import Iterable, Optional, Tuple

import requests

from . import __version__

RETRY_STATUSES = {429, 500, 502, 503, 504}


def user_agent() -> str:
    # OpenStreetMap services require an identifying User-Agent. Set
    # LEAD_SCRAPER_CONTACT (e-mail or URL) so they can reach you if needed.
    contact = os.environ.get("LEAD_SCRAPER_CONTACT", "https://github.com/KevinRusli/Scraper")
    return f"lead-scraper/{__version__} (+{contact})"


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = user_agent()
    return session


def request_with_retry(
    session: requests.Session,
    method: str,
    urls: Iterable[str] | str,
    *,
    attempts: int = 3,
    backoff: float = 2.0,
    timeout: float | Tuple[float, float] = 60,
    sleep=time.sleep,
    **kwargs,
) -> requests.Response:
    """Send a request, retrying on transient errors and rotating over `urls`."""
    url_list = [urls] if isinstance(urls, str) else list(urls)
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        for url in url_list:
            try:
                resp = session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                continue
            if resp.status_code in RETRY_STATUSES:
                last_error = requests.HTTPError(
                    f"{resp.status_code} from {url}: {resp.text[:200]}", response=resp
                )
                continue
            resp.raise_for_status()
            return resp
        if attempt < attempts - 1:
            sleep(backoff * (2 ** attempt))
    assert last_error is not None
    raise last_error
