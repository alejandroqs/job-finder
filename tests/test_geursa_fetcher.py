import io

import pytest
import requests

from job_finder.geursa_fetcher import GeursaFetcher


class FakeResponse:
    def __init__(self, text="<html>ok</html>", error=None):
        self.text = text
        self.error = error
        self.raise_for_status_calls = 0

    def raise_for_status(self):
        self.raise_for_status_calls += 1
        if self.error:
            raise self.error


def test_fetch_list_uses_timeout_and_checks_http_status(monkeypatch):
    response = FakeResponse("<html>GEURSA</html>")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.geursa_fetcher.requests.get", fake_get)
    fetcher = GeursaFetcher(timeout=7)

    assert fetcher.fetch_list() == "<html>GEURSA</html>"
    assert calls == [(fetcher.LIST_URL, {"headers": fetcher.headers, "timeout": 7})]
    assert response.raise_for_status_calls == 1


def test_fetch_wraps_utf8_list_html_in_bytesio_and_ignores_target_date(monkeypatch):
    monkeypatch.setattr(
        "job_finder.geursa_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse("selección de empleo"),
    )

    result = GeursaFetcher().fetch(None)

    assert isinstance(result, io.BytesIO)
    assert result.getvalue() == "selección de empleo".encode("utf-8")


def test_fetch_detail_resolves_relative_url_and_has_context(monkeypatch):
    response = FakeResponse("<html>detail</html>")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.geursa_fetcher.requests.get", fake_get)
    fetcher = GeursaFetcher(timeout=9)

    assert fetcher.fetch_detail("./documentos/bases.pdf") == "<html>detail</html>"
    assert calls[0][0] == "https://www.geursa.es/documentos/bases.pdf"
    assert calls[0][1]["timeout"] == 9
    assert response.raise_for_status_calls == 1


@pytest.mark.parametrize("error", [requests.Timeout("timed out"), requests.HTTPError("503")])
def test_fetch_list_wraps_request_failures_with_geursa_context(monkeypatch, error):
    monkeypatch.setattr(
        "job_finder.geursa_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(error=error),
    )

    with pytest.raises(RuntimeError, match="GEURSA") as raised:
        GeursaFetcher().fetch_list()
    assert raised.value.__cause__ is error


def test_fetch_list_wraps_request_timeout_raised_by_requests(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("job_finder.geursa_fetcher.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="GEURSA") as raised:
        GeursaFetcher().fetch_list()
    assert isinstance(raised.value.__cause__, requests.Timeout)


def test_fetch_list_does_not_wrap_unexpected_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise ValueError("unexpected test failure")

    monkeypatch.setattr("job_finder.geursa_fetcher.requests.get", fake_get)

    with pytest.raises(ValueError, match="unexpected test failure"):
        GeursaFetcher().fetch_list()
