import requests
import pytest

from job_finder.sodetegc_fetcher import SODETEGCFetchError, SODETEGCFetcher


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.chunks = list(chunks)
        self.closed = False

    def iter_content(self, chunk_size):
        assert chunk_size == 64 * 1024
        yield from self.chunks

    def close(self):
        self.closed = True


def test_fetch_uses_fixed_url_timeout_and_disables_automatic_redirects(monkeypatch):
    response = FakeResponse(chunks=["<html>Canarias</html>".encode("utf-8")])
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", fake_get)

    result = SODETEGCFetcher().fetch()

    assert result == "<html>Canarias</html>"
    assert calls[0][0] == SODETEGCFetcher.URL
    assert calls[0][1]["timeout"] == (5, 15)
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["stream"] is True
    assert response.closed


def test_fetch_preserves_utf8_spanish_text(monkeypatch):
    response = FakeResponse(chunks=["<p>Convocación para técnico</p>".encode("utf-8")])
    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", lambda *args, **kwargs: response)

    assert "Convocación para técnico" in SODETEGCFetcher().fetch()


def test_fetch_follows_only_valid_official_same_path_redirect(monkeypatch):
    redirect = FakeResponse(
        status=302,
        headers={"Location": "https://sodetegc.org/conocenos/informacion-administrativa/empleo"},
    )
    final = FakeResponse(chunks=[b"<html>valid</html>"])
    responses = iter([redirect, final])
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        return next(responses)

    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", fake_get)

    assert SODETEGCFetcher().fetch() == "<html>valid</html>"
    assert len(urls) == 2
    assert redirect.closed and final.closed


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/conocenos/informacion-administrativa/empleo/",
        "http://www.sodetegc.org/conocenos/informacion-administrativa/empleo/",
        "https://www.sodetegc.org:8443/conocenos/informacion-administrativa/empleo/",
        "https://user@www.sodetegc.org/conocenos/informacion-administrativa/empleo/",
        "https://www.sodetegc.org/wp-login.php",
        "https://www.sodetegc.org/conocenos/informacion-administrativa/empleo/?redirect=login",
    ],
)
def test_redirect_destinations_outside_official_employment_page_are_rejected(location):
    with pytest.raises(SODETEGCFetchError):
        SODETEGCFetcher._validated_redirect(SODETEGCFetcher.URL, location)


def test_fetch_stops_after_two_redirect_hops(monkeypatch):
    response = FakeResponse(
        status=302,
        headers={"Location": "/conocenos/informacion-administrativa/empleo/"},
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(
            status=302,
            headers={"Location": "/conocenos/informacion-administrativa/empleo/"},
        )

    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", fake_get)

    with pytest.raises(SODETEGCFetchError, match="redirect limit"):
        SODETEGCFetcher().fetch()
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (FakeResponse(status=503, chunks=[b"busy"]), "HTTP 503"),
        (FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=[b"pdf"]), "non-HTML"),
        (FakeResponse(headers={"Content-Type": "text/html", "Content-Length": "bad"}, chunks=[b"x"]), "Content-Length"),
        (FakeResponse(headers={"Content-Type": "text/html", "Content-Length": str(2 * 1024 * 1024 + 1)}), "2 MiB"),
        (FakeResponse(headers={"Content-Type": "text/html"}, chunks=[]), "empty"),
        (FakeResponse(headers={"Content-Type": "text/html"}, chunks=[b"\xff"]), "UTF-8"),
    ],
)
def test_http_body_failures_are_unverifiable_fetch_errors(monkeypatch, response, message):
    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", lambda *args, **kwargs: response)

    with pytest.raises(SODETEGCFetchError, match=message):
        SODETEGCFetcher().fetch()
    assert response.closed


def test_streamed_response_limit_is_enforced(monkeypatch):
    response = FakeResponse(
        headers={"Content-Type": "text/html"},
        chunks=[b"a" * (2 * 1024 * 1024), b"b"],
    )
    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", lambda *args, **kwargs: response)

    with pytest.raises(SODETEGCFetchError, match="2 MiB"):
        SODETEGCFetcher().fetch()
    assert response.closed


def test_request_timeout_is_reported_without_retry(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout("timed out")

    monkeypatch.setattr("job_finder.sodetegc_fetcher.requests.get", fake_get)

    with pytest.raises(SODETEGCFetchError, match="timed out"):
        SODETEGCFetcher().fetch()
    assert len(calls) == 1
