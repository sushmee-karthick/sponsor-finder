from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

import build_sector_dictionary as builder
import cache_store
import companies_house as ch


def record(name_key: str, org_name: str, number: str, *, cacheable: bool = True) -> dict:
    return {
        "name_key": name_key,
        "org_name": org_name,
        "company_number": number,
        "sic_codes": "62012",
        "sic_section": "J",
        "sector_label": "Information & communication",
        "website": "",
        "careers_url": "",
        "company_status": "active",
        "last_checked": "2026-07-10",
        "matched_company_name": org_name,
        "matched_location": "London",
        "lookup_status": "matched",
        "match_confidence": "1.0",
        "match_reason": "company name matched; active company; location matched.",
        "matching_policy": "v2-name-status-location",
        "cacheable": cacheable,
    }


def read_cache(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as cache_file:
        return list(csv.DictReader(cache_file))


def test_upsert_cache_record_inserts_then_replaces_same_key(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_cache.csv"

    assert cache_store.upsert_cache_record(
        cache_path,
        record("northwind", "Northwind Ltd", "00000001"),
    )
    assert cache_store.upsert_cache_record(
        cache_path,
        record("northwind", "Northwind Limited", "00000002"),
    )

    rows = read_cache(cache_path)
    assert len(rows) == 1
    assert rows[0]["org_name"] == "Northwind Limited"
    assert rows[0]["company_number"] == "00000002"
    assert rows[0]["matched_company_name"] == "Northwind Limited"
    assert rows[0]["matching_policy"] == "v2-name-status-location"


def test_upsert_cache_records_preserves_other_keys_and_collapses_duplicates(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "sector_cache.csv"
    cache_path.write_text(
        "name_key,org_name,company_number,sic_codes,sic_section,sector_label,website,"
        "careers_url,company_status,last_checked\n"
        "northwind,Old Northwind,1,62012,J,Tech,,,active,2025-01-01\n"
        "contoso,Contoso,2,62012,J,Tech,,,active,2025-01-01\n"
        "northwind,Duplicate Northwind,3,62012,J,Tech,,,active,2025-01-02\n",
        encoding="utf-8",
    )

    written = cache_store.upsert_cache_records(
        cache_path,
        [record("northwind", "Current Northwind", "4")],
    )

    rows = read_cache(cache_path)
    assert written == 1
    assert [row["name_key"] for row in rows] == ["northwind", "contoso"]
    assert rows[0]["company_number"] == "4"
    assert rows[0]["lookup_status"] == "matched"
    assert rows[0]["matching_policy"] == "v2-name-status-location"
    assert rows[1]["lookup_status"] == ""
    assert rows[1]["matching_policy"] == ""
    assert set(cache_store.CACHE_HEADER) <= set(rows[0])


def test_upsert_cache_record_ignores_non_cacheable_result(tmp_path: Path) -> None:
    cache_path = tmp_path / "sector_cache.csv"

    assert not cache_store.upsert_cache_record(
        cache_path,
        record("northwind", "Northwind", "", cacheable=False),
    )
    assert not cache_path.exists()


def test_atomic_write_failure_preserves_previous_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "sector_cache.csv"
    cache_store.upsert_cache_record(
        cache_path,
        record("northwind", "Northwind", "00000001"),
    )
    before = cache_path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(cache_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        cache_store.upsert_cache_record(
            cache_path,
            record("northwind", "Northwind", "00000002"),
        )

    assert cache_path.read_bytes() == before
    assert list(tmp_path.glob(".sector_cache.csv.*.tmp")) == []


def test_prompt_for_api_key_uses_hidden_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(builder, "getpass", lambda prompt: "super-secret-key")

    assert builder._prompt_for_api_key() == "super-secret-key"
    assert "super-secret-key" not in capsys.readouterr().out


def test_main_skips_duplicate_name_keys_until_cache_supports_sponsor_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    companies = pd.DataFrame(
        [
            {
                "name_key": "shared",
                "sponsor_key": "shared-london",
                "org_name": "Shared Ltd",
                "town": "London",
            },
            {
                "name_key": "shared",
                "sponsor_key": "shared-manchester",
                "org_name": "Shared Ltd",
                "town": "Manchester",
            },
            {
                "name_key": "solo",
                "sponsor_key": "solo-bristol",
                "org_name": "Solo Ltd",
                "town": "Bristol",
            },
        ]
    )
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(builder, "API_KEY", "secret")
    monkeypatch.setattr(builder, "CACHE_FILE", tmp_path / "sector_cache.csv")
    monkeypatch.setattr(builder.sys, "argv", ["build_sector_dictionary.py", "input.csv"])
    monkeypatch.setattr(builder.sf, "load_and_clean", lambda path: object())
    monkeypatch.setattr(builder.sf, "build_company_view", lambda frame: companies)

    def fake_lookup(org_name: str, sponsor_town=None):
        calls.append((org_name, sponsor_town))
        return record("solo", org_name, "00000001")

    monkeypatch.setattr(builder, "look_up_company", fake_lookup)

    builder.main()

    assert calls == [("Solo Ltd", "Bristol")]
    cached_rows = read_cache(builder.CACHE_FILE)
    assert [row["name_key"] for row in cached_rows] == ["solo"]
    assert [row["sponsor_key"] for row in cached_rows] == ["solo-bristol"]
    output = capsys.readouterr().out
    assert "Ambiguous name keys skipped: 1 (2 sponsor rows)" in output
    assert "ambiguous sponsor identities skipped: 1" in output


def test_main_does_not_cache_retryable_api_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    companies = pd.DataFrame(
        [
            {
                "name_key": "offline",
                "sponsor_key": "offline-leeds",
                "org_name": "Offline Ltd",
                "town": "Leeds",
            },
            {
                "name_key": "online",
                "sponsor_key": "online-york",
                "org_name": "Online Ltd",
                "town": "York",
            },
        ]
    )

    monkeypatch.setattr(builder, "API_KEY", "secret")
    monkeypatch.setattr(builder, "CACHE_FILE", tmp_path / "sector_cache.csv")
    monkeypatch.setattr(builder.sys, "argv", ["build_sector_dictionary.py", "input.csv"])
    monkeypatch.setattr(builder.sf, "load_and_clean", lambda path: object())
    monkeypatch.setattr(builder.sf, "build_company_view", lambda frame: companies)

    def fake_lookup(org_name: str, sponsor_town=None):
        if org_name == "Offline Ltd":
            raise ch.CompaniesHouseUnavailableError("temporary outage")
        return record("online", org_name, "00000002")

    monkeypatch.setattr(builder, "look_up_company", fake_lookup)

    builder.main()

    rows = read_cache(builder.CACHE_FILE)
    assert [row["name_key"] for row in rows] == ["online"]
    assert "temporary failures left for retry: 1" in capsys.readouterr().out
