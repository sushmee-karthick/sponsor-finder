"""Reliable Companies House lookup helpers.

The public :func:`look_up_company` function is used by both the Streamlit app
and the batch sector-cache builder.  It intentionally keeps the original
two-argument call compatible while allowing a sponsor town to be supplied for
safer result matching.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any

import requests

import sponsor_filter as sf

SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
PROFILE_URL = "https://api.company-information.service.gov.uk/company/{}"
MATCHING_POLICY = "v2-name-status-location"

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_INACTIVE_STATUSES = {
    "administration",
    "converted-closed",
    "dissolved",
    "insolvency-proceedings",
    "liquidation",
    "receivership",
    "removed",
    "voluntary-arrangement",
}
_LEGAL_SUFFIXES = {
    "co",
    "company",
    "inc",
    "incorporated",
    "limited",
    "llp",
    "lp",
    "ltd",
    "plc",
}
_LOCATION_NOISE = {
    "britain",
    "england",
    "great",
    "ireland",
    "kingdom",
    "northern",
    "scotland",
    "uk",
    "united",
    "wales",
}


class CompaniesHouseError(RuntimeError):
    """Base class for safe-to-display Companies House failures."""

    retryable = False


class CompaniesHouseAuthenticationError(CompaniesHouseError):
    """The configured API key was missing or rejected."""


class CompaniesHouseUnavailableError(CompaniesHouseError):
    """A retryable failure remained after bounded retries."""

    retryable = True


class CompaniesHouseResponseError(CompaniesHouseError):
    """Companies House returned a non-retryable invalid response."""


class RateLimiter:
    """Thread-safe minimum spacing between outgoing API requests."""

    def __init__(
        self,
        minimum_interval: float = 0.55,
        *,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self.minimum_interval = max(0.0, float(minimum_interval))
        self._clock = clock
        self._sleep = sleeper
        self._next_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            delay = self._next_request_at - now
            if delay > 0:
                self._sleep(delay)
                now = self._clock()
            self._next_request_at = max(now, self._next_request_at) + self.minimum_interval


_RATE_LIMITER = RateLimiter()


@dataclass(frozen=True)
class MatchDecision:
    """The result of ranking Companies House search candidates."""

    candidate: Mapping[str, Any] | None
    status: str
    confidence: float
    reason: str
    best_candidate_name: str = ""
    best_candidate_location: str = ""


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: Mapping[str, Any]
    score: float
    name_similarity: float
    exact_name: bool
    location_match: bool


def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
    """Return a bounded delay, preferring the server's Retry-After value."""

    value = response.headers.get("Retry-After", "").strip()
    if value:
        try:
            return min(max(float(value), 0.0), 300.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at - datetime.now(UTC)).total_seconds()
                return min(max(delay, 0.0), 300.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(float(2**attempt), 30.0)


def call_api(
    url: str,
    api_key: str,
    params: Mapping[str, Any] | None = None,
    *,
    max_attempts: int = 4,
    timeout: float = 20,
    rate_limiter: RateLimiter | None = _RATE_LIMITER,
    sleep=time.sleep,
) -> dict[str, Any] | None:
    """Call Companies House with bounded, rate-aware retries.

    A 404 is the only response represented by ``None``.  Retryable transport,
    rate-limit, server, or malformed-response failures raise
    :class:`CompaniesHouseUnavailableError`; callers can therefore avoid
    persisting them as permanent "no match" results.
    """

    if not str(api_key).strip():
        raise CompaniesHouseAuthenticationError("A Companies House API key is required.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(max_attempts):
        if rate_limiter is not None:
            rate_limiter.wait()
        try:
            response = requests.get(
                url,
                params=dict(params) if params is not None else None,
                auth=(api_key, ""),
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            if attempt + 1 == max_attempts:
                raise CompaniesHouseUnavailableError(
                    "Companies House could not be reached after several attempts."
                ) from exc
            sleep(min(float(2**attempt), 30.0))
            continue

        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise CompaniesHouseAuthenticationError(
                "Companies House rejected the configured API key."
            )
        if response.status_code in _RETRYABLE_STATUS_CODES:
            if attempt + 1 == max_attempts:
                raise CompaniesHouseUnavailableError(
                    f"Companies House remained unavailable (HTTP {response.status_code})."
                )
            sleep(_retry_after_seconds(response, attempt))
            continue
        if not 200 <= response.status_code < 300:
            raise CompaniesHouseResponseError(
                f"Companies House returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            if attempt + 1 == max_attempts:
                raise CompaniesHouseUnavailableError(
                    "Companies House repeatedly returned an unreadable response."
                ) from exc
            sleep(min(float(2**attempt), 30.0))
            continue
        if not isinstance(payload, dict):
            if attempt + 1 == max_attempts:
                raise CompaniesHouseUnavailableError(
                    "Companies House repeatedly returned an unexpected response."
                )
            sleep(min(float(2**attempt), 30.0))
            continue
        return payload

    # The loop either returns or raises.  This guard keeps type checkers honest.
    raise CompaniesHouseUnavailableError("Companies House remained unavailable.")


def _normalise_company_name(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = text.casefold().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", text)
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _normalise_location(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if isinstance(value, Mapping):
        value = " ".join(str(part) for part in value.values() if part)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = " ".join(str(part) for part in value if part)
    words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return " ".join(word for word in words if word not in _LOCATION_NOISE)


def _name_similarity(expected: str, actual: str) -> float:
    if not expected or not actual:
        return 0.0
    if expected == actual:
        return 1.0

    sequence_score = SequenceMatcher(None, expected, actual).ratio()
    expected_words = set(expected.split())
    actual_words = set(actual.split())
    overlap = 2 * len(expected_words & actual_words) / (len(expected_words) + len(actual_words))
    similarity = max(sequence_score, overlap)

    # Very short company names should not fuzzy-match an unrelated near-spelling.
    if len(expected) <= 4:
        similarity = min(similarity, 0.6)
    return similarity


def _candidate_location(candidate: Mapping[str, Any]) -> str:
    values: list[Any] = [candidate.get("address_snippet", "")]
    address = candidate.get("address")
    if isinstance(address, Mapping):
        values.extend(address.values())
    return _normalise_location(values)


def _candidate_location_display(candidate: Mapping[str, Any]) -> str:
    """Return a stable, human-readable address for lookup audit records."""

    snippet = " ".join(str(candidate.get("address_snippet", "")).split())
    if snippet:
        return snippet
    address = candidate.get("address")
    if not isinstance(address, Mapping):
        return ""
    fields = (
        "premises",
        "address_line_1",
        "address_line_2",
        "locality",
        "region",
        "postal_code",
        "country",
    )
    parts: list[str] = []
    for field in fields:
        value = " ".join(str(address.get(field, "")).split())
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts)


def _location_matches(expected_location: str, candidate_location: str) -> bool:
    expected_words = set(expected_location.split())
    actual_words = set(candidate_location.split())
    return bool(expected_words) and expected_words <= actual_words


def _score_candidate(
    candidate: Mapping[str, Any],
    expected_name: str,
    expected_location: str,
) -> _ScoredCandidate:
    candidate_name = _normalise_company_name(candidate.get("title", ""))
    similarity = _name_similarity(expected_name, candidate_name)
    exact_name = bool(expected_name) and candidate_name == expected_name
    score = similarity * 70.0 + (15.0 if exact_name else 0.0)

    status = str(candidate.get("company_status", "")).casefold()
    if status == "active":
        score += 10.0
    elif status in _INACTIVE_STATUSES:
        score -= 15.0

    candidate_location = _candidate_location(candidate)
    location_match = _location_matches(expected_location, candidate_location)
    if expected_location:
        if location_match:
            score += 15.0
        elif candidate_location:
            score -= 8.0

    return _ScoredCandidate(
        candidate=candidate,
        score=score,
        name_similarity=similarity,
        exact_name=exact_name,
        location_match=location_match,
    )


def select_best_candidate(
    items: Sequence[Mapping[str, Any]],
    org_name: str,
    sponsor_location: Any = None,
) -> MatchDecision:
    """Rank search results and reject weak or genuinely ambiguous matches."""

    expected_name = _normalise_company_name(org_name)
    expected_location = _normalise_location(sponsor_location)
    scored = sorted(
        (
            _score_candidate(item, expected_name, expected_location)
            for item in items
            if isinstance(item, Mapping)
        ),
        key=lambda item: item.score,
        reverse=True,
    )
    if not scored:
        return MatchDecision(None, "not_found", 0.0, "No company candidates were returned.")

    best = scored[0]
    confidence = round(best.name_similarity, 3)
    if best.name_similarity < 0.78 or best.score < 72.0:
        return MatchDecision(
            None,
            "low_confidence",
            confidence,
            "The closest Companies House result was not similar enough.",
            str(best.candidate.get("title", "")).strip(),
            _candidate_location_display(best.candidate),
        )

    if len(scored) > 1:
        second = scored[1]
        score_gap = best.score - second.score
        second_is_plausible = second.name_similarity >= 0.78 and second.score >= 67.0
        if second_is_plausible and score_gap < 8.0:
            return MatchDecision(
                None,
                "ambiguous",
                confidence,
                "Multiple Companies House results matched with similar confidence.",
                str(best.candidate.get("title", "")).strip(),
                _candidate_location_display(best.candidate),
            )

    details = ["company name matched"]
    if str(best.candidate.get("company_status", "")).casefold() == "active":
        details.append("active company")
    if expected_location and best.location_match:
        details.append("location matched")
    return MatchDecision(
        best.candidate,
        "matched",
        confidence,
        "; ".join(details) + ".",
        str(best.candidate.get("title", "")).strip(),
        _candidate_location_display(best.candidate),
    )


def look_up_company(
    org_name: str,
    api_key: str,
    sponsor_town: Any = None,
    *,
    sponsor_location: Any = None,
) -> dict[str, Any]:
    """Look up one sponsor while preserving the original call signature.

    ``sponsor_town`` (or the equivalent keyword ``sponsor_location``) is used
    only to disambiguate search results.  Retryable API failures are raised so
    callers do not accidentally cache them as a permanent miss.
    """

    key = sf.normalise_name(org_name)
    location = sponsor_location if sponsor_location is not None else sponsor_town
    if not key:
        return _blank(
            key,
            str(org_name or ""),
            "invalid sponsor name",
            lookup_status="invalid_input",
            cacheable=False,
            match_reason="A non-empty sponsor name is required.",
        )

    search = call_api(
        SEARCH_URL,
        api_key,
        {"q": org_name, "items_per_page": 10},
    )
    raw_items = search.get("items", []) if search else []
    items = raw_items if isinstance(raw_items, list) else []
    if not items:
        return _blank(
            key,
            org_name,
            "no match found",
            lookup_status="not_found",
            cacheable=True,
            match_reason="Companies House returned no matching companies.",
        )

    decision = select_best_candidate(items, org_name, location)
    if decision.candidate is None:
        status = "ambiguous match" if decision.status == "ambiguous" else "low-confidence match"
        return _blank(
            key,
            org_name,
            status,
            lookup_status=decision.status,
            cacheable=False,
            match_confidence=decision.confidence,
            match_reason=decision.reason,
            matched_company_name=decision.best_candidate_name,
            matched_location=decision.best_candidate_location,
        )

    best = decision.candidate
    number = str(best.get("company_number", "")).strip()
    status = str(best.get("company_status", "")).strip()
    if not number:
        return _blank(
            key,
            org_name,
            "matched result had no company number",
            lookup_status="invalid_match",
            cacheable=False,
            match_confidence=decision.confidence,
            match_reason="The matched result did not include a company number.",
            matched_company_name=decision.best_candidate_name,
            matched_location=decision.best_candidate_location,
        )

    profile = call_api(PROFILE_URL.format(number), api_key)
    if profile is None:
        return {
            **_blank(
                key,
                org_name,
                status or "profile not found",
                lookup_status="profile_not_found",
                cacheable=False,
                match_confidence=decision.confidence,
                match_reason="The matched company profile was not found.",
                matched_company_name=decision.best_candidate_name,
                matched_location=decision.best_candidate_location,
            ),
            "company_number": number,
        }

    raw_sic_codes = profile.get("sic_codes", [])
    sic_codes = (
        [str(code).strip() for code in raw_sic_codes if str(code).strip()]
        if isinstance(raw_sic_codes, list)
        else []
    )
    section, label = ("?", "Unknown")
    if sic_codes:
        section, label = sf.sic_to_section(sic_codes[0])

    return {
        "name_key": key,
        "org_name": org_name,
        "company_number": number,
        "sic_codes": ", ".join(sic_codes),
        "sic_section": section,
        "sector_label": label if sic_codes else "Unknown (no SIC code)",
        "website": "",
        "careers_url": "",
        "company_status": str(profile.get("company_status", status)).strip(),
        "last_checked": _today(),
        "lookup_status": "matched",
        "cacheable": True,
        "match_confidence": decision.confidence,
        "match_reason": decision.reason,
        "matched_company_name": decision.best_candidate_name,
        "matched_location": decision.best_candidate_location,
        "matching_policy": MATCHING_POLICY,
    }


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _blank(
    key: str,
    org_name: str,
    status: str,
    *,
    lookup_status: str | None = None,
    cacheable: bool = True,
    match_confidence: float = 0.0,
    match_reason: str = "",
    matched_company_name: str = "",
    matched_location: str = "",
) -> dict[str, Any]:
    return {
        "name_key": key,
        "org_name": org_name,
        "company_number": "",
        "sic_codes": "",
        "sic_section": "?",
        "sector_label": "Unknown",
        "website": "",
        "careers_url": "",
        "company_status": status,
        "last_checked": _today(),
        "lookup_status": lookup_status or status,
        "cacheable": cacheable,
        "match_confidence": match_confidence,
        "match_reason": match_reason,
        "matched_company_name": matched_company_name,
        "matched_location": matched_location,
        "matching_policy": MATCHING_POLICY,
    }
