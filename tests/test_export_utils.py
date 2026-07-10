from __future__ import annotations

import csv
import io

import pandas as pd

from export_utils import neutralise_formula_cell, safe_csv_bytes


def test_formula_like_cells_are_neutralised_without_changing_normal_text() -> None:
    assert neutralise_formula_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert neutralise_formula_cell("  @Formula Sponsor") == "'  @Formula Sponsor"
    assert neutralise_formula_cell("Northwind Ltd") == "Northwind Ltd"
    assert neutralise_formula_cell(42) == 42


def test_safe_csv_bytes_exports_every_row_with_utf8_bom() -> None:
    frame = pd.DataFrame(
        {
            "Company": ["@Formula Sponsor Ltd", "=Formula Two Ltd"]
            + [f"Sponsor {number:03d} Ltd" for number in range(53)]
        }
    )

    payload = safe_csv_bytes(frame)
    assert payload.startswith(b"\xef\xbb\xbf")

    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert len(rows) == 55
    companies = {row["Company"] for row in rows}
    assert "'@Formula Sponsor Ltd" in companies
    assert "'=Formula Two Ltd" in companies
    assert "@Formula Sponsor Ltd" not in companies
