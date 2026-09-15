import io

import pytest
import requests

from job_finder.indra_fetcher import IndraFetcher


class FakeResponse:
    def __init__(self, text="<html>ok</html>", error=None, url=None):
        self.text = text
        self.error = error
        if url is not None:
            self.url = url
        self.raise_for_status_calls = 0

    def raise_for_status(self):
        self.raise_for_status_calls += 1
        if self.error:
            raise self.error


def test_fetch_list_uses_blank_search_params_and_timeout(monkeypatch):
    response = FakeResponse("área de empleo")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("job_finder.indra_fetcher.requests.get", fake_get)
    fetcher = IndraFetcher(timeout=7, locale="es_ES")

    assert fetcher.fetch_list() == "área de empleo"
    assert calls == [
        (
            fetcher.SEARCH_URL,
            {"headers": fetcher.headers, "params": {"q": "", "locale": "es_ES"}, "timeout": 7},
        )
    ]
    assert response.raise_for_status_calls == 1


def test_fetch_search_passes_query_verbatim_to_http_params(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse("<html>ok</html>"),
    )

    fetcher = IndraFetcher()
    assert fetcher.fetch_search('"Artificial Intelligence" + C++') == "<html>ok</html>"
    assert calls[0][1]["params"] == {
        "q": '"Artificial Intelligence" + C++',
        "locale": "es_ES",
    }


def test_fetch_page_and_detail_resolve_official_relative_urls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda url, **kwargs: calls.append((url, kwargs)) or FakeResponse("<html>detail</html>"),
    )

    fetcher = IndraFetcher(timeout=9)
    assert fetcher.fetch_page("/search/?q=&startrow=25") == "<html>detail</html>"
    assert fetcher.fetch_detail("/job/example/123/") == "<html>detail</html>"
    assert calls[0][0] == "https://careers.indragroup.com/search/?q=&startrow=25"
    assert calls[1][0] == "https://careers.indragroup.com/job/example/123/"
    assert all(call[1]["timeout"] == 9 for call in calls)


@pytest.mark.parametrize("error", [requests.Timeout("timed out"), requests.HTTPError("503")])
def test_fetch_list_wraps_expected_request_errors_with_context(monkeypatch, error):
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(error=error),
    )

    with pytest.raises(RuntimeError, match="Indra") as raised:
        IndraFetcher().fetch_list()
    assert raised.value.__cause__ is error


def test_fetch_list_does_not_wrap_unexpected_errors(monkeypatch):
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("programming error")),
    )

    with pytest.raises(ValueError, match="programming error"):
        IndraFetcher().fetch_list()


def test_fetch_detail_rejects_official_host_bypass():
    with pytest.raises(ValueError, match="official Indra host"):
        IndraFetcher().fetch_detail("https://example.invalid/job/example/123/")


def test_fetch_rejects_a_redirect_away_from_the_official_host(monkeypatch):
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(url="https://example.invalid/login"),
    )

    with pytest.raises(RuntimeError, match="redirected away"):
        IndraFetcher().fetch_detail("/job/example/123/")


def test_fetch_detail_rejects_a_redirect_to_a_different_official_job(monkeypatch):
    monkeypatch.setattr(
        "job_finder.indra_fetcher.requests.get",
        lambda *args, **kwargs: FakeResponse(
            url="https://careers.indragroup.com/job/other/999/"
        ),
    )

    with pytest.raises(RuntimeError, match="different job"):
        IndraFetcher().fetch_detail("/job/example/123/")
