import io

import pytest
import requests

from job_finder.fulp_fetcher import FulpBudgetExceeded, FulpFetchError, FulpFetcher


class FakeResponse:
    def __init__(self, text="<html>ok</html>", *, status_code=200, headers=None, url=None, error=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.content = text.encode("utf-8") if isinstance(text, str) else text
        self.text = text.decode("utf-8") if isinstance(text, bytes) else text
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_public_url_validation_upgrades_http_and_removes_only_known_tracking():
    assert (
        FulpFetcher.normalise_public_url(
            "http://WWW.FULP.ES:80/ofertas/108550/example?utm_source=x&lang=es#top",
            expected="detail",
        )
        == "https://www.fulp.es/ofertas/108550/example?lang=es"
    )
    assert (
        FulpFetcher.normalise_public_url(
            "https://www.fulp.es/ofertas?unknown=1&utm_medium=x",
            expected="list",
        )
        == "https://www.fulp.es/ofertas?unknown=1"
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://fulp.es/ofertas", "public host"),
        ("https://evil.www.fulp.es/ofertas", "public host"),
        ("https://www.fulp.es:8443/ofertas", "port"),
        ("ftp://www.fulp.es/ofertas", "HTTP"),
        ("https://user:pass@www.fulp.es/ofertas", "credentials"),
        ("https://www.fulp.es/private/secret", "supported"),
        ("https://www.fulp.es/ofertas/123", "detail path"),
        ("https://www.fulp.es/ofertas/123/example\\bad", "backslash"),
    ],
)
def test_public_url_validation_rejects_unsafe_or_unsupported_paths(value, expected):
    with pytest.raises(ValueError, match=expected):
        FulpFetcher.normalise_public_url(value)


def test_fetch_list_uses_manual_redirects_and_explicit_timeout():
    calls = []
    responses = iter(
        [
            FakeResponse(status_code=302, headers={"Location": "/ofertas/"}),
            FakeResponse("área de ofertas"),
        ]
    )

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    fetcher = FulpFetcher(request_get=fake_get)
    assert fetcher.fetch_list() == "área de ofertas"
    assert [call[0] for call in calls] == [fetcher.LIST_URL, fetcher.LIST_URL]
    assert all(call[1]["allow_redirects"] is False for call in calls)
    assert all(call[1]["timeout"] == (5.0, 10.0) for call in calls)
    assert fetcher.attempts == 2


def test_redirect_target_is_validated_before_a_forbidden_request():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=302, headers={"Location": "https://areaprivada.fulp.es/login"})

    with pytest.raises(FulpFetchError, match="rejected redirect target"):
        FulpFetcher(request_get=fake_get).fetch_detail(
            "/ofertas/108550/example"
        )
    assert len(calls) == 1


def test_detail_redirect_must_retain_requested_id():
    calls = []
    responses = iter(
        [
            FakeResponse(status_code=302, headers={"Location": "/ofertas/999/other"}),
        ]
    )

    def fake_get(url, **kwargs):
        calls.append(url)
        return next(responses)

    with pytest.raises(FulpFetchError, match="rejected redirect target"):
        FulpFetcher(request_get=fake_get).fetch_detail("/ofertas/123/example")
    assert calls == ["https://www.fulp.es/ofertas/123/example"]


def test_redirect_loop_and_hop_limit_are_bounded():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=302, headers={"Location": url})

    with pytest.raises(FulpFetchError, match="redirect limit"):
        FulpFetcher(request_get=fake_get, max_redirects=3).fetch_detail("/ofertas/123/example")
    assert len(calls) == 4


def test_attempt_budget_includes_redirects_and_preserves_no_retry_policy():
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=302, headers={"Location": "/ofertas/123/other"})

    fetcher = FulpFetcher(request_get=fake_get, max_attempts=1)
    with pytest.raises(FulpBudgetExceeded):
        fetcher.fetch_detail("/ofertas/123/example")
    assert len(calls) == 1


def test_scheduling_budget_shortens_timeout_and_stops_new_requests():
    now = [0.0]
    calls = []

    def clock():
        return now[0]

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["timeout"]))
        now[0] = 1.0
        return FakeResponse("ok")

    fetcher = FulpFetcher(
        request_get=fake_get,
        clock=clock,
        scheduling_budget_seconds=1.0,
    )
    assert fetcher.fetch_list() == "ok"
    assert calls == [(fetcher.LIST_URL, (1.0, 1.0))]
    with pytest.raises(FulpBudgetExceeded):
        fetcher.fetch_detail("/ofertas/123/example")
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["/ofertas", "/ofertas/123"])
def test_fetch_detail_rejects_non_detail_paths_without_http(url):
    calls = []
    fetcher = FulpFetcher(request_get=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError):
        fetcher.fetch_detail(url)
    assert calls == []


def test_fetch_wraps_expected_requests_errors_but_does_not_retry():
    error = requests.Timeout("timed out")
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        raise error

    with pytest.raises(FulpFetchError, match="FULP offers listing") as raised:
        FulpFetcher(request_get=fake_get).fetch_list()
    assert raised.value.__cause__ is error
    assert len(calls) == 1
