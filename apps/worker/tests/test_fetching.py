import httpx2
import pytest

from exam_core.errors import IngestionError
from exam_core.urls import UrlNotAllowed, validate_source_url
from worker.fetching import fetch_html

OK = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html"


@pytest.mark.parametrize(
    "url",
    [
        OK,
        "https://aws.amazon.com/s3/faqs/",
        "https://DOCS.AWS.AMAZON.COM/x",
        "https://docs.aws.amazon.com:443/x",
    ],
)
def test_allowed_urls(url):
    assert validate_source_url(url).startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.aws.amazon.com/x",  # not https
        "https://evil.com/",
        "https://docs.aws.amazon.com.evil.com/",  # look-alike suffix
        "https://evil.com/docs.aws.amazon.com",
        "https://docs.aws.amazon.com@evil.com/",  # userinfo trick
        "https://evil.com@docs.aws.amazon.com/",
        "https://docs.aws.amazon.com\\@evil.com/",
        "https://docs.aws.amazon.com:8443/",
        "https://sub.docs.aws.amazon.com/",  # exact match only
        "https://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ftp://docs.aws.amazon.com/",
        " https://docs.aws.amazon.com/",
        "https://docs.aws.amazon.com/a b",
        "",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(ValueError):
        validate_source_url(url)


def test_rejection_is_a_value_error_subclass():
    assert issubclass(UrlNotAllowed, ValueError)


def transport(handler):
    return httpx2.MockTransport(handler)


def html_response(body="<html>hi</html>", **kw):
    return httpx2.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=body, **kw)


def test_fetch_ok():
    assert fetch_html(OK, transport(lambda r: html_response("<p>hello</p>"))) == "<p>hello</p>"


def test_fetch_follows_redirect_to_allowed_host():
    def handler(request):
        if request.url.host == "docs.aws.amazon.com":
            return httpx2.Response(302, headers={"location": "https://aws.amazon.com/final"})
        return html_response("<p>final</p>")

    assert fetch_html(OK, transport(handler)) == "<p>final</p>"


def test_fetch_rejects_redirect_to_disallowed_host():
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx2.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(IngestionError, match="disallowed"):
        fetch_html(OK, transport(handler))
    assert seen == ["docs.aws.amazon.com"]  # the second hop was never requested


def test_fetch_limits_redirects():
    handler = lambda r: httpx2.Response(302, headers={"location": OK})
    with pytest.raises(IngestionError, match="Too many redirects"):
        fetch_html(OK, transport(handler))


def test_fetch_rejects_non_200():
    with pytest.raises(IngestionError, match="404"):
        fetch_html(OK, transport(lambda r: httpx2.Response(404)))


def test_fetch_rejects_non_html():
    handler = lambda r: httpx2.Response(200, headers={"content-type": "application/pdf"}, content=b"x")
    with pytest.raises(IngestionError, match="not HTML"):
        fetch_html(OK, transport(handler))


def test_fetch_rejects_oversized_body(monkeypatch):
    from exam_core.config import get_settings

    monkeypatch.setattr(get_settings(), "fetch_max_bytes", 100)
    with pytest.raises(IngestionError, match="too large"):
        fetch_html(OK, transport(lambda r: html_response("x" * 1000)))


def test_fetch_wraps_network_errors():
    def handler(request):
        raise httpx2.ConnectError("boom")

    with pytest.raises(IngestionError, match="Could not fetch"):
        fetch_html(OK, transport(handler))


def test_fetch_validates_the_initial_url():
    with pytest.raises(UrlNotAllowed):
        fetch_html("https://evil.com/", transport(lambda r: html_response()))
