"""Safe page fetching for ingestion. Only allowlisted https hosts, bounded size and redirects."""

from collections.abc import Callable
from typing import Annotated
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx2
from fastapi import Depends

from app.config import get_settings


class IngestionError(Exception):
    """A failure whose message is safe to show to users."""


class UrlNotAllowed(ValueError):
    pass


Fetcher = Callable[[str], str]


def validate_source_url(url: str) -> str:
    """Returns the normalized URL, or raises UrlNotAllowed. This is the SSRF guard."""
    if url != url.strip() or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UrlNotAllowed("URL contains whitespace or control characters")
    parts = urlsplit(url)
    allowed = {h.lower() for h in get_settings().ingestion_allowed_hosts}
    if parts.scheme != "https":
        raise UrlNotAllowed("URL must use https")
    if parts.username is not None or parts.password is not None or "\\" in parts.netloc:
        raise UrlNotAllowed("URL must not contain credentials")
    if parts.port not in (None, 443):
        raise UrlNotAllowed("URL must use the default https port")
    host = (parts.hostname or "").lower()
    if host not in allowed:
        raise UrlNotAllowed(f"Host '{host}' is not allowed; allowed hosts: {sorted(allowed)}")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def fetch_html(url: str, transport: httpx2.BaseTransport | None = None) -> str:
    """GETs an allowlisted page. Redirects are followed manually and re-validated each hop."""
    settings = get_settings()
    current = validate_source_url(url)
    headers = {"User-Agent": "exam-generator-ingestion/0.1", "Accept": "text/html"}
    try:
        with httpx2.Client(
            transport=transport,
            timeout=settings.fetch_timeout_seconds,
            follow_redirects=False,
            headers=headers,
        ) as client:
            for _ in range(settings.fetch_max_redirects + 1):
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise IngestionError("Redirect without a location")
                        try:
                            current = validate_source_url(urljoin(current, location))
                        except UrlNotAllowed as exc:
                            raise IngestionError(f"Redirected to a disallowed URL: {exc}") from exc
                        continue
                    if response.status_code != 200:
                        raise IngestionError(f"The page returned HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "")
                    if not content_type.lower().startswith(("text/html", "application/xhtml")):
                        raise IngestionError("The page is not HTML")
                    body = bytearray()
                    for part in response.iter_bytes():
                        body.extend(part)
                        if len(body) > settings.fetch_max_bytes:
                            raise IngestionError("The page is too large")
                    return body.decode(response.encoding or "utf-8", errors="replace")
    except httpx2.HTTPError as exc:
        raise IngestionError("Could not fetch the page") from exc
    raise IngestionError("Too many redirects")


def get_fetcher() -> Fetcher:
    return fetch_html


FetcherDep = Annotated[Fetcher, Depends(get_fetcher)]
