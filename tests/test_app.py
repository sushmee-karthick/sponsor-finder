from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).parents[1] / "app.py"
CSV_HEADER = "Organisation Name,Town/City,County,Type & rating,Route\n"


def _configure_app(monkeypatch, tmp_path: Path, rows: list[str]) -> Path:
    register = tmp_path / "register.csv"
    register.write_text(CSV_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("SPONSOR_FINDER_DEFAULT_LIST", str(register))
    monkeypatch.setenv("SPONSOR_FINDER_SAMPLE_LIST", str(register))
    monkeypatch.setenv("SPONSOR_FINDER_CACHE", str(tmp_path / "missing-cache.csv"))
    monkeypatch.setenv("SPONSOR_FINDER_MANIFEST", str(tmp_path / "missing-manifest.json"))
    monkeypatch.delenv("CH_API_KEY", raising=False)
    return register


def _run_app() -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not app.exception
    return app


def _table_with_columns(app: AppTest, required: set[str]):
    matches = [table.value for table in app.dataframe if required <= set(table.value.columns)]
    assert len(matches) == 1
    return matches[0]


def _overview_table(app: AppTest):
    return _table_with_columns(app, {"Company", "Visa routes", "Rating"})


def test_company_search_and_route_specific_filters(monkeypatch, tmp_path):
    _configure_app(
        monkeypatch,
        tmp_path,
        [
            "Northwind Data Labs Ltd,London,,Worker (A rating),Skilled Worker",
            "Northwind Data Labs Ltd,London,,Worker (B rating),Global Business Mobility",
            (
                "Brightpath Care Homes Ltd,Manchester,Greater Manchester,"
                "Worker (A rating),Health and Care Worker"
            ),
            "Cobalt Cloud Solutions Ltd,Bristol,,Worker (A rating),Skilled Worker",
        ],
    )

    app = _run_app()

    assert app.title[0].value == "UK Sponsor Finder"
    assert app.metric[0].value == "3"
    assert _overview_table(app)["Company"].tolist() == [
        "Brightpath Care Homes Ltd",
        "Cobalt Cloud Solutions Ltd",
        "Northwind Data Labs Ltd",
    ]
    assert any("not immigration or legal advice" in item.value for item in app.caption)

    app.text_input(key="company_search").set_value("northWIND").run()

    assert not app.exception
    assert app.metric[0].value == "1"
    assert _overview_table(app)["Company"].tolist() == ["Northwind Data Labs Ltd"]

    app.multiselect(key="visa_routes").select("Global Business Mobility")
    app.multiselect(key="licence_ratings").select("A")
    app.run()

    assert not app.exception
    assert app.metric[0].value == "0"
    assert any("No sponsors match" in item.value for item in app.info)

    app.button(key="clear_filters").click().run()

    assert not app.exception
    assert app.text_input(key="company_search").value == ""
    assert app.metric[0].value == "3"


def test_pagination_and_full_formula_safe_csv_download(monkeypatch, tmp_path):
    rows = [
        "@Formula Sponsor Ltd,London,,Worker (A rating),Skilled Worker",
        "=Formula Two Ltd,Leeds,,Worker (A rating),Skilled Worker",
    ]
    rows.extend(
        f"Sponsor {number:03d} Ltd,Manchester,,Worker (A rating),Skilled Worker"
        for number in range(53)
    )
    _configure_app(monkeypatch, tmp_path, rows)

    app = _run_app()

    assert app.metric[0].value == "55"
    assert len(_overview_table(app)) == 50

    download = app.download_button(key="download_results")
    assert download.label == "Download all filtered results"
    assert "all 55 matches" in download.help

    app.number_input(key="results_page").set_value(2).run()

    assert not app.exception
    assert len(_overview_table(app)) == 5
    assert any("Showing 51–55 of 55 matches" in item.value for item in app.caption)

    app.text_input(key="company_search").set_value("Formula Two").run()

    assert not app.exception
    assert app.number_input(key="results_page").value == 1
    assert _overview_table(app)["Company"].tolist() == ["=Formula Two Ltd"]


def test_uploaded_csv_and_invalid_file_error_are_graceful(monkeypatch, tmp_path):
    _configure_app(
        monkeypatch,
        tmp_path,
        ["Bundled Sponsor Ltd,London,,Worker (A rating),Skilled Worker"],
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"sponsor_snapshot":{"provenance_status":"legacy snapshot"},'
        '"sector_cache":{"verification_status":"unverified"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("SPONSOR_FINDER_MANIFEST", str(manifest))
    app = _run_app()

    app.radio(key="data_source_choice").set_value("Upload a CSV").run()
    assert not app.exception
    assert len(app.file_uploader) == 1

    uploaded = (
        CSV_HEADER + "Uploaded Sponsor Ltd,Cardiff,,Worker (A rating),Health and Care Worker\n"
    ).encode()
    app.file_uploader(key="sponsor_csv_upload").upload(
        "fresh-register.csv", uploaded, "text/csv"
    ).run()

    assert not app.exception
    assert app.metric[0].value == "1"
    assert _overview_table(app)["Company"].tolist() == ["Uploaded Sponsor Ltd"]
    assert any("fresh-register.csv" in item.value for item in app.caption)
    assert any("Uploaded CSV" in item.value for item in app.markdown)
    assert any(
        "Repository snapshot provenance metadata does not apply" in item.value
        for item in app.caption
    )
    assert not any("Snapshot verification status" in item.value for item in app.caption)
    assert any("Sector cache verification status: unverified" in item.value for item in app.caption)

    app.file_uploader(key="sponsor_csv_upload").set_value(
        ("invalid.csv", b"Name,Town\nMissing Route,London\n", "text/csv")
    ).run()

    assert not app.exception
    assert any("Required columns were not found" in item.value for item in app.error)


def test_results_separate_sponsor_overview_from_match_audit(monkeypatch, tmp_path):
    _configure_app(
        monkeypatch,
        tmp_path,
        ["Audit Ready Sponsor Ltd,London,,Worker (A rating),Skilled Worker"],
    )

    app = _run_app()

    overview = _overview_table(app)
    audit = _table_with_columns(
        app,
        {
            "Company",
            "Matched Companies House name",
            "Company number",
            "Name confidence",
            "Match rationale",
        },
    )
    assert overview["Company"].tolist() == ["Audit Ready Sponsor Ltd"]
    assert audit["Company"].tolist() == ["Audit Ready Sponsor Ltd"]
    assert "Matched Companies House name" not in overview.columns
    assert [tab.label for tab in app.tabs] == ["Sponsor overview", "Match audit"]
