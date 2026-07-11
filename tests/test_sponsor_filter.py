import pandas as pd

import sponsor_filter as sf


def _long_df(rows: list[dict[str, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["name_key"] = frame["org_name"].apply(sf.normalise_name)
    return frame


def test_same_name_sponsors_in_different_locations_remain_distinct() -> None:
    sponsors = _long_df(
        [
            {
                "org_name": "Subway Ltd",
                "town": "London",
                "county": "Greater London",
                "route": "Skilled Worker",
                "rating": "A",
            },
            {
                "org_name": "SUBWAY LIMITED",
                "town": "London",
                "county": "Greater London",
                "route": "Creative Worker",
                "rating": "B",
            },
            {
                "org_name": "Subway Ltd",
                "town": "Manchester",
                "county": "Greater Manchester",
                "route": "Skilled Worker",
                "rating": "A",
            },
            {
                "org_name": "Subway Ltd",
                "town": "London",
                "county": "Essex",
                "route": "Skilled Worker",
                "rating": "A",
            },
        ]
    )

    companies = sf.build_company_view(sponsors)

    assert len(companies) == 3
    assert companies["sponsor_key"].is_unique
    assert set(companies["town"]) == {"London", "Manchester"}
    assert set(companies.loc[companies["town"] == "London", "county"]) == {
        "Greater London",
        "Essex",
    }

    london = companies[
        (companies["town"] == "London") & (companies["county"] == "Greater London")
    ].iloc[0]
    assert london["route_list"] == ["Creative Worker", "Skilled Worker"]

    reordered = sf.build_company_view(sponsors.sample(frac=1, random_state=42))
    assert set(reordered["sponsor_key"]) == set(companies["sponsor_key"])


def test_combined_route_and_rating_filters_require_a_real_pair() -> None:
    sponsors = _long_df(
        [
            {
                "org_name": "NETLIGHT CONSULTING LIMITED",
                "town": "London",
                "county": "",
                "route": "Skilled Worker",
                "rating": "A",
            },
            {
                "org_name": "NETLIGHT CONSULTING LIMITED",
                "town": "London",
                "county": "",
                "route": "Global Business Mobility",
                "rating": "B",
            },
        ]
    )
    companies = sf.build_company_view(sponsors)

    assert companies.iloc[0]["route_rating_pairs"] == (
        ("Global Business Mobility", "B"),
        ("Skilled Worker", "A"),
    )
    assert sf.apply_filters(
        companies,
        routes=["Global Business Mobility"],
        ratings=["A"],
    ).empty
    assert (
        len(
            sf.apply_filters(
                companies,
                routes=["Global Business Mobility"],
                ratings=["B"],
            )
        )
        == 1
    )
    assert len(sf.apply_filters(companies, routes=["Skilled Worker"], ratings=["A"])) == 1
    assert len(sf.apply_filters(companies, ratings=["B"])) == 1
    assert sf.filter_options(companies, sponsors)["ratings"] == ["A", "B"]


def test_dormant_company_code_is_not_an_international_organisation() -> None:
    assert sf.sic_to_section("99999") == ("?", "Dormant company")
    assert sf.sic_to_section(99999) == ("?", "Dormant company")
    assert sf.sic_to_section("99000") == ("U", "International organisations")


def test_legacy_dormant_cache_labels_are_repaired_when_attached() -> None:
    companies = sf.build_company_view(
        _long_df(
            [
                {
                    "org_name": "Dormant Example Ltd",
                    "town": "London",
                    "county": "",
                    "route": "Skilled Worker",
                    "rating": "A",
                }
            ]
        )
    )
    legacy_cache = pd.DataFrame(
        [
            {
                "name_key": "dormant example",
                "sic_codes": "99999",
                "sic_section": "U",
                "sector_label": "International organisations",
            }
        ]
    )

    attached = sf.attach_sectors(companies, legacy_cache)

    assert attached.loc[0, "sic_section"] == "?"
    assert attached.loc[0, "sector_label"] == "Dormant company"


def test_address_like_towns_can_be_hidden_from_filter_options() -> None:
    sponsors = _long_df(
        [
            {
                "org_name": "Address Based Sponsor Ltd",
                "town": "1 Concorde Way",
                "county": "",
                "route": "Skilled Worker",
                "rating": "A",
            },
            {
                "org_name": "City Based Sponsor Ltd",
                "town": "London",
                "county": "",
                "route": "Skilled Worker",
                "rating": "A",
            },
        ]
    )
    companies = sf.build_company_view(sponsors)

    hidden = sf.filter_options(companies, sponsors, hide_address_like=True)
    visible = sf.filter_options(companies, sponsors, hide_address_like=False)

    assert hidden["towns"] == ["London"]
    assert set(visible["towns"]) == {"1 Concorde Way", "London"}


def test_compound_newcastle_places_are_not_folded_into_newcastle() -> None:
    sponsors = _long_df(
        [
            {
                "org_name": "Example Sponsor Ltd",
                "town": sf.clean_town("Newcastle-under-Lyme"),
                "county": "Staffordshire",
                "route": "Skilled Worker",
                "rating": "A",
            }
        ]
    )

    companies = sf.build_company_view(sponsors)

    assert sf.to_main_place("Newcastle Under Lyme") == "Other"
    assert companies.loc[0, "main_place"] == "Newcastle Under Lyme"


def test_legacy_name_cache_is_not_broadcast_to_same_name_locations() -> None:
    sponsors = _long_df(
        [
            {
                "org_name": "Subway Ltd",
                "town": "Hatfield",
                "county": "Hertfordshire",
                "route": "Skilled Worker",
                "rating": "A",
            },
            {
                "org_name": "Subway Ltd",
                "town": "Manchester",
                "county": "Greater Manchester",
                "route": "Skilled Worker",
                "rating": "A",
            },
        ]
    )
    companies = sf.build_company_view(sponsors)
    cache = pd.DataFrame(
        [
            {
                "name_key": "",
                "org_name": "Subway Ltd",
                "company_number": "00000001",
                "sic_codes": "56103",
                "sic_section": "I",
                "sector_label": "Food services",
                "website": "https://old.example",
                "careers_url": "",
                "company_status": "active",
                "last_checked": "2026-05-01",
            },
            {
                "name_key": "stale legacy key",
                "org_name": "SUBWAY LIMITED",
                "company_number": "00000002",
                "sic_codes": "56103",
                "sic_section": "I",
                "sector_label": "Accommodation & food service",
                "website": "https://subway.example",
                "careers_url": "https://subway.example/careers",
                "company_status": "active",
                "last_checked": "2026-06-01",
            },
            {
                "name_key": "subway",
                "org_name": "Subway Ltd",
                "company_number": "",
                "sic_codes": "",
                "sic_section": "?",
                "sector_label": "Unknown",
                "website": "",
                "careers_url": "",
                "company_status": "lookup failed",
                "last_checked": "2026-07-01",
            },
        ]
    )

    attached = sf.attach_sectors(companies, cache)

    assert len(attached) == len(companies) == 2
    assert attached["sponsor_key"].is_unique
    assert set(attached["company_number"]) == {""}
    assert set(attached["sector_label"]) == {"Needs verification"}
    assert set(attached["lookup_status"]) == {"needs_verification"}
    assert set(attached["matching_policy"]) == {"legacy_name_key"}
    assert set(attached["match_reason"]) == {
        "Multiple sponsor locations share this legacy name key."
    }


def test_duplicate_cache_rows_are_deduplicated_and_audit_fields_are_carried() -> None:
    companies = sf.build_company_view(
        _long_df(
            [
                {
                    "org_name": "Single Site Foods Ltd",
                    "town": "Leeds",
                    "county": "West Yorkshire",
                    "route": "Skilled Worker",
                    "rating": "A",
                }
            ]
        )
    )
    cache = pd.DataFrame(
        [
            {
                "name_key": "",
                "org_name": "Single Site Foods Ltd",
                "company_number": "00000001",
                "sic_codes": "56103",
                "sic_section": "I",
                "sector_label": "Food services",
                "company_status": "active",
                "last_checked": "2026-05-01",
            },
            {
                "name_key": "stale legacy key",
                "org_name": "SINGLE SITE FOODS LIMITED",
                "company_number": "00000002",
                "sic_codes": "56103",
                "sic_section": "I",
                "sector_label": "Accommodation & food service",
                "company_status": "active",
                "last_checked": "2026-06-01",
                "matched_company_name": "Single Site Foods Limited",
                "matched_location": "Leeds",
                "lookup_status": "matched",
                "match_confidence": "0.96",
                "match_reason": "Name and location agree.",
                "matching_policy": "name_and_location_v1",
            },
        ]
    )

    attached = sf.attach_sectors(companies, cache)

    assert len(attached) == 1
    assert attached.loc[0, "company_number"] == "00000002"
    assert attached.loc[0, "matched_company_name"] == "Single Site Foods Limited"
    assert attached.loc[0, "matched_location"] == "Leeds"
    assert attached.loc[0, "lookup_status"] == "matched"
    assert attached.loc[0, "match_confidence"] == "0.96"
    assert attached.loc[0, "match_reason"] == "Name and location agree."
    assert attached.loc[0, "matching_policy"] == "name_and_location_v1"
