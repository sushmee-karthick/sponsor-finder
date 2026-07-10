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
    assert app.dataframe[0].value["Company"].tolist() == [
        "Brightpath Care Homes Ltd",
        "Cobalt Cloud Solutions Ltd",
        "Northwind Data Labs Ltd",
    ]
    assert any("not immigration or legal advice" in item.value for item in app.caption)

    app.text_input(key="company_search").set_value("northWIND").run()

    assert not app.exception
    assert app.metric[0].value == "1"
    assert app.dataframe[0].value["Company"].tolist() == ["Northwind Data Labs Ltd"]

    app.multiselect(key="visa_routes").select("Global Business Mobility")
    app.multiselect(key="licence_ratings").select("A")
    app.run()

    assert not app.exception
    assert app.metric[0].value == "0"
    assert any("No sponsors match" in item.value for item in app.info)


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
    assert len(app.dataframe[0].value) == 50

    download = app.download_button(key="download_results")
    assert download.label == "Download all filtered results"
    assert "all 55 matches" in download.help

    app.number_input(key="results_page").set_value(2).run()

    assert not app.exception
    assert len(app.dataframe[0].value) == 5
    assert any("Showing 51–55 of 55 matches" in item.value for item in app.caption)


def test_uploaded_csv_and_invalid_file_error_are_graceful(monkeypatch, tmp_path):
    _configure_app(
        monkeypatch,
        tmp_path,
        ["Bundled Sponsor Ltd,London,,Worker (A rating),Skilled Worker"],
    )
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
    assert app.dataframe[0].value["Company"].tolist() == ["Uploaded Sponsor Ltd"]
    assert any("fresh-register.csv" in item.value for item in app.caption)

    app.file_uploader(key="sponsor_csv_upload").set_value(
        ("invalid.csv", b"Name,Town\nMissing Route,London\n", "text/csv")
    ).run()

    assert not app.exception
    assert any("Required columns were not found" in item.value for item in app.error)
