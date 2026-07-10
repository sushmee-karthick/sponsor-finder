"""Streamlit interface for exploring the UK register of licensed sponsors.

Run locally with ``streamlit run app.py``.  Data preparation is cached so that
filter changes stay responsive, while live Companies House requests are always
explicit, capped, and scoped to the current browser session.
"""

from __future__ import annotations

import inspect
import io
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import companies_house as ch
import export_utils
import sponsor_filter as sf

try:
    import cache_store
except ImportError:  # The app still works with older checkouts, session-only.
    cache_store = None


HERE = Path(__file__).resolve().parent
DEFAULT_LIST = Path(os.environ.get("SPONSOR_FINDER_DEFAULT_LIST", HERE / "latest_sponsors.csv"))
SAMPLE_LIST = Path(os.environ.get("SPONSOR_FINDER_SAMPLE_LIST", HERE / "sample_sponsors.csv"))
CACHE = Path(os.environ.get("SPONSOR_FINDER_CACHE", HERE / "sector_cache.csv"))
MANIFEST = Path(os.environ.get("SPONSOR_FINDER_MANIFEST", HERE / "data_manifest.json"))

LIVE_LOOKUP_CAP = 10
PAGE_SIZES = (25, 50, 100, 250)
UNKNOWN_SECTORS = {
    "",
    "not looked up yet",
    "unknown",
    "unknown (no sic code)",
    "unavailable",
    "needs verification",
}
FILTER_STATE_KEYS = (
    "company_search",
    "visa_routes",
    "licence_ratings",
    "sponsor_towns",
    "sponsor_sectors",
    "include_unknown_sectors",
    "hide_address_locations",
    "results_page",
)


st.set_page_config(
    page_title="UK Sponsor Finder",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="auto",
)


def _file_version(path: Path) -> str:
    """Return a cheap cache-busting token without reading a large data file."""
    try:
        stat = path.stat()
    except OSError:
        return "missing"
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _is_unknown_sector(value: Any) -> bool:
    text = "" if pd.isna(value) else str(value).strip().lower()
    return text in UNKNOWN_SECTORS or text.startswith("lookup ")


def _unknown_sector_mask(frame: pd.DataFrame) -> pd.Series:
    if "sector_label" not in frame.columns:
        return pd.Series(True, index=frame.index, dtype=bool)
    return frame["sector_label"].map(_is_unknown_sector).astype(bool)


def _dataset_source(path: str, payload: bytes | None):
    return io.BytesIO(payload) if payload is not None else path


@st.cache_data(show_spinner=False)
def _load_and_prepare(
    source_path: str,
    source_payload: bytes | None,
    source_version: str,
    cache_path: str,
    cache_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load, clean, group, and enrich a data source once per file version."""
    # The version values intentionally participate in Streamlit's cache key.
    del source_version, cache_version

    long_df = sf.load_and_clean(_dataset_source(source_path, source_payload))
    companies = sf.build_company_view(long_df)
    cache_meta: dict[str, Any] = {
        "loaded": False,
        "rows": 0,
        "is_demo": False,
        "last_checked": "",
        "error": "",
    }

    cache_df: pd.DataFrame | None = None
    if cache_path and Path(cache_path).is_file():
        try:
            cache_df = pd.read_csv(cache_path, dtype=str).fillna("")
            cache_meta["loaded"] = True
            cache_meta["rows"] = len(cache_df)
            if "last_checked" in cache_df.columns:
                checked = {
                    str(value).strip() for value in cache_df["last_checked"] if str(value).strip()
                }
                cache_meta["is_demo"] = bool(checked) and checked <= {"DEMO"}
                real_dates = sorted(value for value in checked if value != "DEMO")
                cache_meta["last_checked"] = real_dates[-1] if real_dates else ""
        except Exception as exc:  # A broken enrichment cache must not hide the register.
            cache_meta["error"] = str(exc)
            cache_df = None

    try:
        companies = sf.attach_sectors(companies, cache_df)
    except Exception as exc:  # Degrade cleanly to register-only search.
        existing = cache_meta["error"]
        cache_meta["error"] = f"{existing}; {exc}".strip("; ")
        companies = sf.attach_sectors(companies, None)

    return long_df, companies, cache_meta


@st.cache_data(show_spinner=False)
def _load_manifest(path: str, version: str) -> dict[str, Any]:
    """Read optional provenance metadata without making startup depend on it."""
    del version
    if not path or not Path(path).is_file():
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _get_ch_key() -> str:
    """Read a Companies House key without displaying it or logging its source."""
    key = os.environ.get("CH_API_KEY", "").strip()
    if key:
        return key

    env_file = HERE / ".env"
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("CH_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except (OSError, UnicodeError):
        pass

    try:
        secret_files = (
            Path.home() / ".streamlit" / "secrets.toml",
            HERE / ".streamlit" / "secrets.toml",
        )
        if any(path.is_file() for path in secret_files) and "CH_API_KEY" in st.secrets:
            return str(st.secrets["CH_API_KEY"]).strip()
    except Exception:
        pass
    return ""


def _friendly_load_error(exc: Exception) -> str:
    if isinstance(exc, pd.errors.EmptyDataError):
        return "That CSV is empty. Choose a file containing sponsor records."
    if isinstance(exc, pd.errors.ParserError):
        return "That file is not a valid CSV. Check its delimiter and quoting, then try again."
    if isinstance(exc, UnicodeDecodeError):
        return "That CSV could not be decoded. Save it as UTF-8 and try again."
    if isinstance(exc, ValueError):
        return (
            "Required columns were not found. Include an organisation/company-name "
            "column and a visa-route column; town, county, and rating are optional."
        )
    return "The sponsor data could not be prepared. Check the file and try again."


def _apply_live_enrichment(
    companies: pd.DataFrame, live_records: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Overlay successful browser-session lookups on the cached company view."""
    if not live_records:
        return companies

    enriched = companies.copy()
    identity_col = "sponsor_key" if "sponsor_key" in enriched.columns else "name_key"
    overlay_fields = (
        "sector_label",
        "sic_codes",
        "website",
        "careers_url",
        "company_number",
        "company_status",
        "matched_company_name",
        "matched_location",
        "lookup_status",
        "match_confidence",
        "match_reason",
        "matching_policy",
    )
    for row_index, identity in enriched[identity_col].items():
        record = live_records.get(str(identity))
        if not record:
            continue
        for field in overlay_fields:
            if field not in record:
                continue
            if field not in enriched.columns:
                enriched[field] = ""
            enriched.at[row_index, field] = record.get(field, "")
    return enriched


def _lookup_company(name: str, town: str, api_key: str) -> dict[str, Any]:
    """Call old or new lookup implementations while preferring location context."""
    parameters = inspect.signature(ch.look_up_company).parameters
    kwargs: dict[str, str] = {}
    if "sponsor_town" in parameters:
        kwargs["sponsor_town"] = town
    elif "sponsor_location" in parameters:
        kwargs["sponsor_location"] = town
    elif "town" in parameters:
        kwargs["town"] = town
    return ch.look_up_company(name, api_key, **kwargs)


def _persist_lookup_records(records: list[dict[str, Any]]) -> int:
    """Persist cacheable, unambiguous records through the atomic cache API only."""
    safe_records = [record for record in records if record.get("cacheable") is True]
    if not safe_records or cache_store is None:
        return 0
    try:
        if hasattr(cache_store, "upsert_cache_records"):
            result = cache_store.upsert_cache_records(CACHE, safe_records)
            if isinstance(result, int) and not isinstance(result, bool):
                return result
            return len(safe_records) if result else 0
        if len(safe_records) == 1 and hasattr(cache_store, "upsert_cache_record"):
            return int(bool(cache_store.upsert_cache_record(CACHE, safe_records[0])))
    except (OSError, ValueError):
        return 0
    return 0


@st.cache_data(show_spinner=False, max_entries=8)
def _safe_csv_bytes(frame: pd.DataFrame) -> bytes:
    """Build a spreadsheet-safe export once per filtered result set."""
    return export_utils.safe_csv_bytes(frame)


def _clear_filters() -> None:
    for key in FILTER_STATE_KEYS:
        st.session_state.pop(key, None)


def _manifest_value(manifest: dict[str, Any], *keys: str) -> str:
    """Fetch a simple value from either a flat or a nested manifest."""
    current: Any = manifest
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return ""
        current = current[key]
    return str(current).strip() if current is not None else ""


def _display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    unknown = _unknown_sector_mask(display)
    confidence = (
        pd.to_numeric(display["match_confidence"], errors="coerce")
        if "match_confidence" in display.columns
        else pd.Series(float("nan"), index=display.index)
    )
    display["sector_data_status"] = "Candidate match — verify"
    display.loc[unknown, "sector_data_status"] = "Not available"
    has_confidence = ~unknown & confidence.notna()
    display.loc[has_confidence, "sector_data_status"] = confidence[has_confidence].map(
        lambda value: f"{value:.0%} name confidence — verify"
    )
    if "match_confidence" in display.columns:
        display["match_confidence"] = confidence.map(
            lambda value: f"{value:.0%}" if pd.notna(value) else ""
        )

    columns = [
        "org_name",
        "town",
        "county",
        "sector_label",
        "sector_data_status",
        "matched_company_name",
        "company_number",
        "company_status",
        "matched_location",
        "match_confidence",
        "match_reason",
        "matching_policy",
        "best_rating",
        "routes",
        "sic_codes",
        "website",
        "careers_url",
    ]
    columns = [column for column in columns if column in display.columns]
    labels = {
        "org_name": "Company",
        "town": "Town / city",
        "county": "County",
        "sector_label": "Sector candidate",
        "sector_data_status": "Sector data status",
        "matched_company_name": "Matched Companies House name",
        "company_number": "Company number",
        "company_status": "Company status",
        "matched_location": "Matched location",
        "match_confidence": "Name confidence",
        "match_reason": "Match rationale",
        "matching_policy": "Matching policy",
        "best_rating": "Rating",
        "routes": "Visa routes",
        "sic_codes": "SIC codes",
        "website": "Website",
        "careers_url": "Careers page",
    }
    return display[columns].rename(columns=labels)


# ---- Page header and data source -----------------------------------------
st.title("UK Sponsor Finder")
st.write(
    "Explore organisations on the UK register of licensed worker sponsors by "
    "company, route, rating, location, and sector."
)
st.caption(
    "Discovery tool, not immigration or legal advice. Always confirm current "
    "licence details on the official UKVI register."
)

st.sidebar.header("Search and filters")
source_choice = st.sidebar.radio(
    "Data source",
    ("Bundled register", "Upload a CSV"),
    help=(
        "The bundled file is the repository snapshot. Uploading lets you inspect a "
        "newer or custom register without changing repository data."
    ),
    key="data_source_choice",
)

source_path = ""
source_payload: bytes | None = None
source_label = ""
source_version = ""
using_fallback_sample = False

if source_choice == "Upload a CSV":
    upload = st.sidebar.file_uploader(
        "Sponsor register CSV",
        type=("csv",),
        help="The file needs company/organisation and visa-route columns.",
        key="sponsor_csv_upload",
    )
    if upload is None:
        st.info("Choose a sponsor-register CSV in the sidebar to begin.")
        st.stop()
    source_payload = upload.getvalue()
    source_label = upload.name
    source_version = f"upload:{len(source_payload)}"
else:
    selected_path = DEFAULT_LIST if DEFAULT_LIST.is_file() else SAMPLE_LIST
    using_fallback_sample = selected_path == SAMPLE_LIST and not DEFAULT_LIST.is_file()
    if not selected_path.is_file():
        st.error(
            "No bundled sponsor register is available. Add `latest_sponsors.csv` "
            "beside the app, or choose **Upload a CSV** in the sidebar."
        )
        st.stop()
    source_path = str(selected_path)
    source_label = "Bundled sample" if using_fallback_sample else "Bundled register"
    source_version = _file_version(selected_path)

try:
    with st.spinner("Preparing sponsor data…"):
        long_df, companies, cache_meta = _load_and_prepare(
            source_path,
            source_payload,
            source_version,
            str(CACHE),
            _file_version(CACHE),
        )
except Exception as exc:
    st.error(_friendly_load_error(exc))
    with st.expander("Technical details"):
        st.code(str(exc) or type(exc).__name__)
    st.stop()

if companies.empty:
    st.warning("No usable sponsor records were found in this data source.")
    st.stop()

manifest = _load_manifest(str(MANIFEST), _file_version(MANIFEST))
live_records = st.session_state.setdefault("live_sector_records", {})
companies = _apply_live_enrichment(companies, live_records)

snapshot_status = _manifest_value(
    manifest, "sponsor_snapshot", "provenance_status"
) or _manifest_value(manifest, "provenance_status")

if using_fallback_sample:
    st.warning("The full bundled register is unavailable, so the small sample is shown.")
if cache_meta["error"]:
    st.warning(
        "Sector enrichment is temporarily unavailable. Company, route, rating, and "
        "location search still work."
    )
if cache_meta["is_demo"]:
    st.info("Sector enrichment is demo data in this snapshot; treat it as illustrative.")
if source_choice == "Bundled register" and "legacy" in snapshot_status.lower():
    st.warning(
        "The bundled register is a legacy snapshot with no recorded retrieval date. "
        "Use the official UKVI register for current decisions."
    )

lookup_notice = st.session_state.pop("lookup_notice", None)
if lookup_notice:
    level, message = lookup_notice
    getattr(st, level, st.info)(message)

# ---- Filters --------------------------------------------------------------
st.sidebar.text_input(
    "Company name",
    placeholder="e.g. Northwind",
    help="Case-insensitive, literal name search.",
    key="company_search",
)
hide_address_locations = st.sidebar.checkbox(
    "Hide address-like locations",
    value=True,
    help="Removes entries that look like street addresses from the location choices.",
    key="hide_address_locations",
)
options = sf.filter_options(companies, long_df, hide_address_like=hide_address_locations)

selected_routes = st.sidebar.multiselect("Visa route", options.get("routes", []), key="visa_routes")
selected_ratings = st.sidebar.multiselect(
    "Sponsor rating",
    options.get("ratings", []),
    help="Ratings are evaluated for the selected route where the source data permits it.",
    key="licence_ratings",
)
selected_towns = st.sidebar.multiselect(
    "Town / city",
    options.get("towns", []),
    help="Locations are ordered by sponsor count. Type to search.",
    key="sponsor_towns",
)
sector_options = [sector for sector in options.get("sectors", []) if not _is_unknown_sector(sector)]
selected_sectors = st.sidebar.multiselect(
    "Sector candidate",
    sector_options,
    help="Sector labels come from Companies House candidate matches and require verification.",
    key="sponsor_sectors",
)
include_unknown_sectors = st.sidebar.checkbox(
    "Include sponsors without sector data",
    value=True,
    key="include_unknown_sectors",
)
st.sidebar.button("Clear filters", on_click=_clear_filters, key="clear_filters")

results = sf.apply_filters(
    companies,
    routes=selected_routes or None,
    ratings=selected_ratings or None,
    towns=selected_towns or None,
    sectors=selected_sectors or None,
)
search_query = st.session_state.get("company_search", "").strip()
if search_query:
    results = results[
        results["org_name"]
        .astype(str)
        .str.contains(search_query, case=False, regex=False, na=False)
    ]
if not include_unknown_sectors:
    results = results[~_unknown_sector_mask(results)]

sort_columns = [column for column in ("org_name", "town") if column in results.columns]
if sort_columns:
    results = results.sort_values(sort_columns, kind="stable")
results = results.reset_index(drop=True)

# ---- Status and metrics ---------------------------------------------------
all_unknown = _unknown_sector_mask(companies)
all_known_count = int((~all_unknown).sum())
source_summary = (
    f"{source_label} · {len(long_df):,} register rows · "
    f"{len(companies):,} sponsor records · "
    f"{all_known_count:,} with a sector candidate"
)
st.caption(source_summary)

metric_columns = st.columns(4)
with metric_columns[0]:
    st.metric("Matching sponsors", f"{len(results):,}")
with metric_columns[1]:
    a_rated = int(results["best_rating"].eq("A").sum()) if "best_rating" in results.columns else 0
    st.metric("A-rated matches", f"{a_rated:,}")
with metric_columns[2]:
    place_column = "main_place" if "main_place" in results.columns else "town"
    location_count = (
        int(results[place_column].replace("", pd.NA).dropna().nunique())
        if place_column in results.columns
        else 0
    )
    st.metric("Locations", f"{location_count:,}")
with metric_columns[3]:
    result_known = int((~_unknown_sector_mask(results)).sum())
    coverage = f"{(100 * result_known / len(results)):.0f}%" if len(results) else "—"
    st.metric("Sector coverage", coverage)

# ---- Paginated results and full export -----------------------------------
st.subheader("Results")
if results.empty:
    st.info("No sponsors match these filters. Remove a filter or broaden the company search.")
else:
    control_columns = st.columns((1, 1, 3))
    with control_columns[0]:
        page_size = st.selectbox("Rows per page", PAGE_SIZES, index=1, key="results_page_size")
    total_pages = max(1, math.ceil(len(results) / page_size))
    current_page = int(st.session_state.get("results_page", 1))
    if current_page > total_pages:
        st.session_state["results_page"] = total_pages
    elif current_page < 1:
        st.session_state["results_page"] = 1
    with control_columns[1]:
        page_number = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            step=1,
            key="results_page",
            disabled=total_pages == 1,
        )

    start = (int(page_number) - 1) * page_size
    stop = min(start + page_size, len(results))
    page_results = results.iloc[start:stop]
    display_results = _display_frame(results)
    display_page = display_results.iloc[start:stop]

    with control_columns[2]:
        st.caption(
            f"Showing {start + 1:,}–{stop:,} of {len(results):,} matches · "
            f"page {int(page_number):,} of {total_pages:,}"
        )
        st.download_button(
            "Download all filtered results",
            data=_safe_csv_bytes(display_results),
            file_name="uk_sponsor_finder_results.csv",
            mime="text/csv",
            help=f"Downloads all {len(results):,} matches, not only this page.",
            key="download_results",
        )

    column_config: dict[str, Any] = {}
    if "Website" in display_page.columns:
        column_config["Website"] = st.column_config.LinkColumn("Website")
    if "Careers page" in display_page.columns:
        column_config["Careers page"] = st.column_config.LinkColumn("Careers page")
    st.dataframe(
        display_page,
        hide_index=True,
        width="stretch",
        column_config=column_config,
    )

    page_missing = page_results[_unknown_sector_mask(page_results)]
    if len(page_missing):
        st.caption(
            f"{len(page_missing):,} sponsor(s) on this page have no sector candidate. "
            "Unknown values are retained rather than guessed."
        )

    # ---- Explicit, capped, location-aware Companies House lookup ----------
    api_key = _get_ch_key()
    with st.expander("Look up missing sector candidates"):
        st.write(
            "Companies House matching is enrichment only. Check the company number and "
            "identity before relying on a sector. Lookups are capped and never expose your API key."
        )
        if page_missing.empty:
            st.success("Every sponsor on this page already has a sector candidate.")
        elif not api_key:
            st.caption(
                "Live lookup is disabled. Set `CH_API_KEY` in the environment or in "
                "Streamlit Secrets to enable it."
            )
        else:
            identity_column = "sponsor_key" if "sponsor_key" in page_missing.columns else "name_key"
            candidates = page_missing.drop_duplicates(identity_column)
            candidate_ids = candidates[identity_column].astype(str).tolist()
            labels = {
                str(row[identity_column]): " — ".join(
                    part
                    for part in (
                        str(row.get("org_name", "")).strip(),
                        str(row.get("town", "")).strip(),
                    )
                    if part
                )
                for _, row in candidates.iterrows()
            }
            chosen_ids = st.multiselect(
                f"Sponsors on this page (up to {LIVE_LOOKUP_CAP})",
                candidate_ids,
                format_func=lambda value: labels.get(value, value),
                max_selections=LIVE_LOOKUP_CAP,
                key="live_lookup_choices",
            )
            if st.button(
                "Look up selected sponsors",
                disabled=not chosen_ids,
                key="run_live_lookup",
            ):
                selected = candidates[candidates[identity_column].astype(str).isin(chosen_ids)]
                name_duplicates = companies["name_key"].duplicated(keep=False)
                ambiguous_names = set(companies.loc[name_duplicates, "name_key"].astype(str))
                persistable: list[dict[str, Any]] = []
                successes = 0
                failures: list[str] = []
                progress = st.progress(0.0, text="Contacting Companies House…")
                for position, (_, row) in enumerate(selected.iterrows(), start=1):
                    name = str(row.get("org_name", ""))
                    town = str(row.get("town", ""))
                    identity = str(row[identity_column])
                    try:
                        record = dict(_lookup_company(name, town, api_key))
                    except ch.CompaniesHouseUnavailableError as exc:
                        failures.append(f"{name}: {exc}")
                        break
                    except ch.CompaniesHouseError as exc:
                        failures.append(f"{name}: {exc}")
                        break
                    except Exception as exc:
                        failures.append(f"{name}: {exc}")
                    else:
                        record.setdefault("org_name", name)
                        if identity_column == "sponsor_key":
                            record.setdefault("sponsor_key", identity)
                        live_records[identity] = record
                        successes += 1
                        is_ambiguous = str(row.get("name_key", "")) in ambiguous_names
                        if record.get("cacheable") is True and not is_ambiguous:
                            persistable.append(record)
                    progress.progress(
                        position / len(selected), text=f"Checked {position} of {len(selected)}"
                    )

                persisted = _persist_lookup_records(persistable)
                if successes:
                    detail = f"Updated {successes} sponsor(s) for this browser session."
                    if persisted:
                        detail += f" Saved {persisted} unambiguous match(es) to the local cache."
                    if failures:
                        detail += f" {len(failures)} lookup(s) could not be completed."
                    st.session_state["lookup_notice"] = ("success", detail)
                else:
                    st.session_state["lookup_notice"] = (
                        "warning",
                        "Companies House could not complete the selected lookups. Try again later.",
                    )
                st.rerun()

# ---- Provenance and trust -------------------------------------------------
with st.expander("Data provenance and limitations"):
    st.markdown(
        "- **Sponsor register:** the bundled CSV is a repository snapshot. Verify a "
        "sponsor's current status on the [official UKVI register](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers).\n"
        "- **Sector enrichment:** SIC sectors are Companies House candidate matches. "
        "Similar company names can refer to different legal entities; verify the company number.\n"
        "- **What inclusion means:** a sponsor licence does not mean there is an open job, "
        "that the organisation will sponsor a particular role, or that sponsorship is guaranteed.\n"
        "- **Uploaded files:** uploads are processed in the running app session and do not "
        "replace the repository's bundled register."
    )
    manifest_source = (
        _manifest_value(manifest, "sponsor_snapshot", "source_url")
        or _manifest_value(manifest, "source_url")
        or _manifest_value(manifest, "source", "url")
    )
    manifest_status = (
        _manifest_value(manifest, "sponsor_snapshot", "provenance_status")
        or _manifest_value(manifest, "status")
        or _manifest_value(manifest, "verification_status")
        or _manifest_value(manifest, "source", "status")
    )
    sector_manifest_status = _manifest_value(manifest, "sector_cache", "verification_status")
    if manifest_source:
        st.caption(f"Snapshot source recorded in the data manifest: {manifest_source}")
    if manifest_status:
        st.caption(f"Snapshot verification status: {manifest_status}")
    if sector_manifest_status:
        st.caption(f"Sector cache verification status: {sector_manifest_status}")
    if cache_meta["last_checked"]:
        st.caption(
            "Latest recorded Companies House cache check: "
            f"{cache_meta['last_checked']} (individual records may be older)."
        )
