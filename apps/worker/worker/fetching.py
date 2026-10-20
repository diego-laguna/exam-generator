"""Safe page fetching for ingestion. Only allowlisted https hosts, bounded size and redirects."""

from collections.abc import Callable
from urllib.parse import urljoin

import httpx2
from exam_core.config import get_settings
from exam_core.errors import IngestionError
from exam_core.urls import UrlNotAllowed, validate_source_url

Fetcher = Callable[[str], str]


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
