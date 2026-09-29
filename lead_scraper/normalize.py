"""Normalisation helpers used to build deduplication keys.

A lead is considered a duplicate of a previously returned lead when *any* of
its keys matches a stored key. Keys are built from:

* the provider id (``osm:node/123``, ``google:ChIJ...``)
* the phone number (last 9 digits, so ``+62 21 555 1234`` == ``021-5551234``)
* the e-mail address
* the website (host + path, ignoring scheme, ``www.``, query and trailing slash)
* the business name + location rounded to ~100 m

Social-media / link-in-bio hosts are ignored as website keys because many
unrelated businesses share them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional
from urllib.parse import urlsplit

from .models import Lead

# Hosts that are shared by many unrelated businesses: never use them as a key.
GENERIC_HOSTS = {
    "facebook.com",
    "m.facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "linktr.ee",
    "wa.me",
    "api.whatsapp.com",
    "whatsapp.com",
    "google.com",
    "maps.google.com",
    "goo.gl",
    "g.page",
    "business.site",
    "youtube.com",
    "linkedin.com",
    "tokopedia.com",
    "shopee.co.id",
    "gofood.co.id",
    "grab.com",
    "tripadvisor.com",
    "booking.com",
}

_MIN_PHONE_DIGITS = 7
_PHONE_KEY_DIGITS = 9


def normalize_text(value: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^\w\s]", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def normalize_phone(phone: str) -> str:
    """Return the last 9 digits of a phone number, or "" if it is too short."""
    if not phone:
        return ""
    # Only take the first number when several are listed ("021 123; 0812 456").
    first = re.split(r"[;,/]| or ", phone)[0]
    digits = re.sub(r"\D", "", first)
    if len(digits) < _MIN_PHONE_DIGITS:
        return ""
    return digits[-_PHONE_KEY_DIGITS:]


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if email.startswith("mailto:"):
        email = email[len("mailto:"):]
    email = email.split("?")[0]
    return email if "@" in email else ""


def normalize_website(url: str) -> str:
    """Return ``host/path`` without scheme, ``www.``, query or trailing slash."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return ""
    if host in GENERIC_HOSTS or any(host.endswith("." + g) for g in GENERIC_HOSTS):
        return ""
    path = parts.path.rstrip("/").lower()
    if path in ("/index.html", "/index.php", "/home"):
        path = ""
    return host + path


def _location_key(lead: Lead) -> Optional[str]:
    name = normalize_text(lead.name)
    if not name:
        return None
    if lead.latitude is not None and lead.longitude is not None:
        return f"{name}@{lead.latitude:.3f},{lead.longitude:.3f}"
    address = normalize_text(lead.address)
    if address:
        return f"{name}@{address}"
    return None


def dedup_keys(lead: Lead) -> List[str]:
    """All keys that identify this lead. Order: strongest first."""
    keys: List[str] = [f"id:{lead.uid}"]
    phone = normalize_phone(lead.phone)
    if phone:
        keys.append(f"phone:{phone}")
    email = normalize_email(lead.email)
    if email:
        keys.append(f"email:{email}")
    site = normalize_website(lead.website)
    if site:
        keys.append(f"web:{site}")
    loc = _location_key(lead)
    if loc:
        keys.append(f"loc:{loc}")
    return _unique(keys)


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
