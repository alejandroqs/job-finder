import io

import pytest
import requests

from job_finder.gsc_fetcher import GSCFetcher


class FakeResponse:
    def __init__(self, text="<html>ok</html>", error=None):
        self.text = text
        self.error = error
        self.raise_for_status_calls = 0

    def raise_for_status(self):
        self.raise_for_status_calls += 1
        if self.error:
            raise self.error


def test_fetch_list_uses_one_get_timeout_and_http_status(monkeypatch):
    response = FakeResponse("<html>selección</html>")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.gsc_fetcher.requests.get", fake_get)
    fetcher = GSCFetcher(timeout=7)

    assert fetcher.fetch_list() == "<html>selección</html>"
    assert calls == [(fetcher.LIST_URL, {"headers": fetcher.headers, "timeout": 7})]
    assert response.raise_for_status_calls == 1


def test_fetch_wraps_utf8_list_html_in_bytesio_and_ignores_target_date(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse("Gestión y selección")

    monkeypatch.setattr("job_finder.gsc_fetcher.requests.get", fake_get)

    result = GSCFetcher().fetch(None)

    assert isinstance(result, io.BytesIO)
    assert result.getvalue() == "Gestión y selección".encode("utf-8")
    assert len(calls) == 1


@pytest.mark.parametrize("error", [requests.Timeout("timed out"), requests.HTTPError("503")])
def test_fetch_list_wraps_request_failures_with_gsc_context(monkeypatch, error):
    monkeypatch.setattr(
        "job_finder.gsc_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(error=error),
    )

    with pytest.raises(RuntimeError, match="GSC") as raised:
        GSCFetcher().fetch_list()

    assert raised.value.__cause__ is error


def test_fetch_list_wraps_timeout_raised_by_requests(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("job_finder.gsc_fetcher.requests.get", fake_get)

    with pytest.raises(RuntimeError, match="GSC") as raised:
        GSCFetcher().fetch_list()

    assert isinstance(raised.value.__cause__, requests.Timeout)


def test_fetch_list_does_not_wrap_unexpected_errors(monkeypatch):
    def fake_get(*args, **kwargs):
        raise ValueError("unexpected test failure")

    monkeypatch.setattr("job_finder.gsc_fetcher.requests.get", fake_get)

    with pytest.raises(ValueError, match="unexpected test failure"):
        GSCFetcher().fetch_list()
