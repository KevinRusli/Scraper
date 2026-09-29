"""Optional: find e-mail addresses on a lead's website (homepage + contact page)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

import requests

from .http import new_session
from .models import Lead

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
CONTACT_LINK_RE = re.compile(
    r"""href=["']([^"'#]*(?:contact|kontak|hubungi|about|tentang)[^"'#]*)["']""", re.I
)
JUNK_EMAIL_PARTS = ("example.", "sentry", "wixpress", "domain.com", "email.com", "yourname", "@2x", "godaddy")
JUNK_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


def _clean_emails(html: str) -> List[str]:
    found = []
    for raw in EMAIL_RE.findall(html):
        email = raw.lower().strip(".")
        if email.endswith(JUNK_EMAIL_SUFFIXES) or any(p in email for p in JUNK_EMAIL_PARTS):
            continue
        if email not in found:
            found.append(email)
    return found


def _pick(emails: List[str], website: str) -> Optional[str]:
    """Prefer an address on the company's own domain."""
    if not emails:
        return None
    host = (urlsplit(website if "://" in website else "http://" + website).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for email in emails:
        if host and email.endswith("@" + host):
            return email
    return emails[0]


def find_email(website: str, session: Optional[requests.Session] = None, timeout: float = 10) -> Optional[str]:
    if not website:
        return None
    session = session or new_session()
    url = website if "://" in website else "http://" + website
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    html = resp.text[:2_000_000]
    emails = _clean_emails(html)
    if not emails:
        match = CONTACT_LINK_RE.search(html)
        if match:
            try:
                contact = session.get(urljoin(resp.url, match.group(1)), timeout=timeout)
                if contact.ok:
                    emails = _clean_emails(contact.text[:2_000_000])
            except requests.RequestException:
                pass
    return _pick(emails, website)


def enrich_emails(leads: List[Lead], workers: int = 8) -> int:
    """Fill `email` for leads that have a website but no e-mail. Returns #found."""
    targets = [lead for lead in leads if lead.website and not lead.email]
    if not targets:
        return 0
    session = new_session()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda lead: find_email(lead.website, session), targets))
    found = 0
    for lead, email in zip(targets, results):
        if email:
            lead.email = email
            found += 1
    return found
