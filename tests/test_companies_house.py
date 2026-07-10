from __future__ import annotations

import pytest
import requests

import companies_house as ch


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload=None,
        *,
        headers: dict[str, str] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def candidate(
    title: str,
    number: str,
    *,
    status: str = "active",
    locality: str = "",
) -> dict:
    return {
        "title": title,
        "company_number": number,
        "company_status": status,
        "address": {"locality": locality} if locality else {},
    }


def test_select_best_candidate_does_not_trust_search_order() -> None:
    items = [
        candidate("Acme Healthcare Services Limited", "00000001"),
        candidate("Acme Healthcare Limited", "00000002"),
    ]

    decision = ch.select_best_candidate(items, "ACME HEALTHCARE LTD")

    assert decision.status == "matched"
    assert decision.candidate is not None
    assert decision.candidate["company_number"] == "00000002"


def test_select_best_candidate_uses_location_to_disambiguate_exact_names() -> None:
    items = [
        candidate("Northwind Limited", "00000001", locality="Manchester"),
        candidate("Northwind Limited", "00000002", locality="London"),
    ]

    decision = ch.select_best_candidate(items, "Northwind Ltd", "London")

    assert decision.status == "matched"
    assert decision.candidate is not None
    assert decision.candidate["company_number"] == "00000002"
    assert "location matched" in decision.reason


def test_select_best_candidate_flags_indistinguishable_exact_names() -> None:
    items = [
        candidate("Northwind Limited", "00000001", locality="Manchester"),
        candidate("Northwind Limited", "00000002", locality="London"),
    ]

    decision = ch.select_best_candidate(items, "Northwind Ltd")

    assert decision.status == "ambiguous"
    assert decision.candidate is None


def test_select_best_candidate_rejects_low_confidence_result() -> None:
    decision = ch.select_best_candidate(
        [candidate("Completely Different Business Limited", "00000001")],
        "Northwind Data",
    )

    assert decision.status == "low_confidence"
    assert decision.candidate is None


def test_select_best_candidate_prefers_active_exact_match() -> None:
    items = [
        candidate("Northwind Limited", "00000001", status="dissolved"),
        candidate("Northwind Limited", "00000002", status="active"),
    ]

    decision = ch.select_best_candidate(items, "Northwind Ltd")

    assert decision.status == "matched"
    assert decision.candidate is not None
    assert decision.candidate["company_number"] == "00000002"


def test_call_api_honours_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200, {"items": []}),
        ]
    )
    monkeypatch.setattr(ch.requests, "get", lambda *args, **kwargs: next(responses))
    sleeps: list[float] = []

    result = ch.call_api(
        ch.SEARCH_URL,
        "secret-key",
        {"q": "Northwind"},
        max_attempts=2,
        rate_limiter=None,
        sleep=sleeps.append,
    )

    assert result == {"items": []}
    assert sleeps == [7.0]


def test_call_api_retries_transport_errors_then_raises_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args, **kwargs):
        raise requests.exceptions.Timeout("network unavailable")

    monkeypatch.setattr(ch.requests, "get", timeout)
    sleeps: list[float] = []

    with pytest.raises(ch.CompaniesHouseUnavailableError) as error:
        ch.call_api(
            ch.SEARCH_URL,
            "do-not-leak-this-key",
            max_attempts=3,
            rate_limiter=None,
            sleep=sleeps.append,
        )

    assert error.value.retryable is True
    assert "do-not-leak-this-key" not in str(error.value)
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [401, 403])
def test_call_api_rejects_bad_credentials_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        ch.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(status_code),
    )

    with pytest.raises(ch.CompaniesHouseAuthenticationError) as error:
        ch.call_api(
            ch.SEARCH_URL,
            "do-not-leak-this-key",
            rate_limiter=None,
        )

    assert "do-not-leak-this-key" not in str(error.value)


def test_call_api_distinguishes_404_from_retryable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ch.requests, "get", lambda *args, **kwargs: FakeResponse(404))

    assert ch.call_api(ch.SEARCH_URL, "secret", rate_limiter=None) is None


def test_call_api_retries_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            FakeResponse(200, json_error=ValueError("not json")),
            FakeResponse(200, {"items": []}),
        ]
    )
    monkeypatch.setattr(ch.requests, "get", lambda *args, **kwargs: next(responses))
    sleeps: list[float] = []

    assert ch.call_api(
        ch.SEARCH_URL,
        "secret",
        max_attempts=2,
        rate_limiter=None,
        sleep=sleeps.append,
    ) == {"items": []}
    assert sleeps == [1.0]


def test_look_up_company_returns_cacheable_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ch, "call_api", lambda *args, **kwargs: {"items": []})

    record = ch.look_up_company("Missing Sponsor", "secret")

    assert record["lookup_status"] == "not_found"
    assert record["cacheable"] is True
    assert record["company_number"] == ""
    assert record["matched_company_name"] == ""
    assert record["matched_location"] == ""
    assert record["matching_policy"] == "v2-name-status-location"


def test_look_up_company_returns_non_cacheable_ambiguous_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = {
        "items": [
            candidate("Northwind Limited", "00000001", locality="Manchester"),
            candidate("Northwind Limited", "00000002", locality="London"),
        ]
    }
    calls = 0

    def fake_call_api(*args, **kwargs):
        nonlocal calls
        calls += 1
        return search

    monkeypatch.setattr(ch, "call_api", fake_call_api)

    record = ch.look_up_company("Northwind Ltd", "secret")

    assert calls == 1
    assert record["lookup_status"] == "ambiguous"
    assert record["cacheable"] is False
    assert record["matched_company_name"] == "Northwind Limited"
    assert record["matched_location"] in {"Manchester", "London"}
    assert record["matching_policy"] == ch.MATCHING_POLICY


def test_look_up_company_fetches_profile_for_location_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            {
                "items": [
                    candidate("Northwind Limited", "00000001", locality="Manchester"),
                    candidate("Northwind Limited", "00000002", locality="London"),
                ]
            },
            {"company_status": "active", "sic_codes": ["62012", "62020"]},
        ]
    )
    monkeypatch.setattr(ch, "call_api", lambda *args, **kwargs: next(responses))

    record = ch.look_up_company("Northwind Ltd", "secret", sponsor_town="London")

    assert record["lookup_status"] == "matched"
    assert record["cacheable"] is True
    assert record["company_number"] == "00000002"
    assert record["sic_codes"] == "62012, 62020"
    assert record["sic_section"] == "J"
    assert record["matched_company_name"] == "Northwind Limited"
    assert record["matched_location"] == "London"
    assert record["match_confidence"] == 1.0
    assert record["match_reason"] == "company name matched; active company; location matched."
    assert record["matching_policy"] == ch.MATCHING_POLICY


def test_low_confidence_record_retains_candidate_audit_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ch,
        "call_api",
        lambda *args, **kwargs: {
            "items": [
                candidate(
                    "Completely Different Business Limited",
                    "00000001",
                    locality="Glasgow",
                )
            ]
        },
    )

    record = ch.look_up_company("Northwind Data", "secret", sponsor_town="London")

    assert record["lookup_status"] == "low_confidence"
    assert record["cacheable"] is False
    assert record["matched_company_name"] == "Completely Different Business Limited"
    assert record["matched_location"] == "Glasgow"
    assert record["matching_policy"] == ch.MATCHING_POLICY


def test_look_up_company_propagates_retryable_profile_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_call_api(url: str, *args, **kwargs):
        calls.append(url)
        if url == ch.SEARCH_URL:
            return {"items": [candidate("Northwind Limited", "00000001")]}
        raise ch.CompaniesHouseUnavailableError("temporary outage")

    monkeypatch.setattr(ch, "call_api", fake_call_api)

    with pytest.raises(ch.CompaniesHouseUnavailableError):
        ch.look_up_company("Northwind Ltd", "secret")

    assert calls == [ch.SEARCH_URL, ch.PROFILE_URL.format("00000001")]


def test_rate_limiter_spaces_requests() -> None:
    now = [10.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = ch.RateLimiter(0.55, clock=lambda: now[0], sleeper=sleep)
    limiter.wait()
    limiter.wait()

    assert sleeps == pytest.approx([0.55])
