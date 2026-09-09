import io

import pytest
import requests

from job_finder.guaguas_fetcher import GuaguasFetcher


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
    response = FakeResponse("<html>Guaguas</html>")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.guaguas_fetcher.requests.get", fake_get)
    fetcher = GuaguasFetcher(timeout=7)

    assert fetcher.fetch_list() == "<html>Guaguas</html>"
    assert calls == [(fetcher.LIST_URL, {"headers": fetcher.headers, "timeout": 7})]
    assert response.raise_for_status_calls == 1


def test_fetch_wraps_list_html_in_bytesio(monkeypatch):
    monkeypatch.setattr(
        "job_finder.guaguas_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse("área de empleo"),
    )

    result = GuaguasFetcher().fetch(None)

    assert isinstance(result, io.BytesIO)
    assert result.getvalue() == "área de empleo".encode("utf-8")


def test_fetch_detail_resolves_relative_url_and_has_context(monkeypatch):
    response = FakeResponse("<html>detail</html>")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.guaguas_fetcher.requests.get", fake_get)
    fetcher = GuaguasFetcher(timeout=9)

    assert fetcher.fetch_detail("./ofertas_trabajo/bases.pdf") == "<html>detail</html>"
    assert calls[0][0] == "https://www.guaguas.com/ofertas_trabajo/bases.pdf"
    assert calls[0][1]["timeout"] == 9


@pytest.mark.parametrize("error", [requests.Timeout("timed out"), requests.HTTPError("503")])
def test_fetch_list_propagates_failures_with_guaguas_context(monkeypatch, error):
    monkeypatch.setattr(
        "job_finder.guaguas_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(error=error),
    )

    with pytest.raises(RuntimeError, match="Guaguas") as raised:
        GuaguasFetcher().fetch_list()
    assert raised.value.__cause__ is error


def test_fetch_list_wraps_request_timeout(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("job_finder.guaguas_fetcher.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="Guaguas") as raised:
        GuaguasFetcher().fetch_list()
    assert isinstance(raised.value.__cause__, requests.Timeout)


def test_fetch_list_does_not_wrap_unexpected_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise ValueError("unexpected test failure")

    monkeypatch.setattr("job_finder.guaguas_fetcher.requests.get", fake_get)

    with pytest.raises(ValueError, match="unexpected test failure"):
        GuaguasFetcher().fetch_list()
