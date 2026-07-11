"""Safe export helpers that do not depend on the Streamlit runtime."""

from __future__ import annotations

from typing import Any

import pandas as pd

FORMULA_PREFIXES = ("=", "+", "-", "@")


def neutralise_formula_cell(value: Any) -> Any:
    """Prevent a string cell from becoming a spreadsheet formula."""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def safe_csv_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize a dataframe as UTF-8 CSV with formula-like cells neutralized."""
    safe = frame.map(neutralise_formula_cell)
    return safe.to_csv(index=False).encode("utf-8-sig")
