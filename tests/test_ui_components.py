from __future__ import annotations

import ui_components as ui


def test_filter_chips_escape_user_controlled_values():
    labels = ui.active_filter_labels(
        search='<img src=x onerror="alert(1)">',
        routes=["Skilled <Worker>"],
        ratings=[],
        towns=[],
        sectors=[],
        include_unknown_sectors=True,
    )

    markup = ui.filter_chips_html(labels)

    assert "<img" not in markup
    assert "&lt;img" in markup
    assert "Skilled &lt;Worker&gt;" in markup
    assert "2 active filters" in markup


def test_safe_http_url_rejects_non_web_and_malformed_links():
    assert ui.safe_http_url("https://example.com/careers") == "https://example.com/careers"
    assert ui.safe_http_url("http://example.org") == "http://example.org"
    assert ui.safe_http_url("javascript:alert(1)") == ""
    assert ui.safe_http_url("data:text/html,unsafe") == ""
    assert ui.safe_http_url("example.com") == ""
    assert ui.safe_http_url("https://") == ""


def test_snapshot_badge_keeps_legacy_warning_visible():
    legacy = ui.snapshot_badge_html("legacy snapshot")
    current_unknown = ui.snapshot_badge_html("")
    uploaded = ui.snapshot_badge_html("legacy snapshot", uploaded=True)

    assert "Legacy snapshot" in legacy
    assert "verify current licence" in legacy
    assert "Repository snapshot" in current_unknown
    assert "Uploaded CSV" in uploaded
    assert "Legacy snapshot" not in uploaded
