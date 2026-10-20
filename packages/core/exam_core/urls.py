"""The SSRF guard: which URLs the system may ever fetch."""

from urllib.parse import urlsplit, urlunsplit

from exam_core.config import get_settings


class UrlNotAllowed(ValueError):
    pass


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
