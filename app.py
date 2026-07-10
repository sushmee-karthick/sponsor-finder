"""
app.py  --  the "face" of the Sponsor Finder (the website people use).

Run it locally with:   streamlit run app.py
- Reads the pre-built sector_cache.csv (kept fresh by weekly_refresh.py).
- Can look up a MISSING company's sector live, on demand (needs an API key).
"""

import io
import os
import csv
import pathlib
import pandas as pd
import streamlit as st
import sponsor_filter as sf
import companies_house as ch

st.set_page_config(page_title="UK Sponsor Finder", page_icon="🔎", layout="wide")
st.title("🔎 UK Sponsor Finder")
st.write(
       "Find UK companies that can sponsor your work visa — "
       "filter by visa type, location, and industry."
   )

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_sponsors.csv")
DEFAULT_LIST = os.path.join(HERE, "latest_sponsors.csv")   # the list shown to everyone
CACHE = os.path.join(HERE, "sector_cache.csv")
LIVE_CAP = 25   # most companies we'll look up live in one click (protects the rate limit)

CACHE_HEADER = ["name_key", "org_name", "company_number", "sic_codes",
                "sic_section", "sector_label", "website", "careers_url",
                "company_status", "last_checked"]


# --- find an API key quietly: env var / .env (local) -> secrets (deployed) ---
def get_ch_key():
    # 1. environment variable
    key = os.environ.get("CH_API_KEY", "")
    if key:
        return key
    # 2. a local .env file
    p = pathlib.Path(HERE) / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line.startswith("CH_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # 3. Streamlit secrets -- only touch this if a secrets file actually exists,
    #    otherwise Streamlit prints a "No secrets found" notice.
    try:
        secret_files = [
            pathlib.Path.home() / ".streamlit" / "secrets.toml",
            pathlib.Path(HERE) / ".streamlit" / "secrets.toml",
        ]
        if any(f.exists() for f in secret_files) and "CH_API_KEY" in st.secrets:
            return str(st.secrets["CH_API_KEY"])
    except Exception:
        pass
    return ""


def append_to_cache(rec):
    """Best-effort save of a live lookup so it's remembered next time (works locally)."""
    try:
        new = not os.path.exists(CACHE)
        with open(CACHE, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CACHE_HEADER)
            if new:
                w.writeheader()
            w.writerow({k: rec.get(k, "") for k in CACHE_HEADER})
    except Exception:
        pass


API_KEY = get_ch_key()
live = st.session_state.setdefault("live_sectors", {})   # name_key -> record


# --- 1. Get the data (always the latest kept list; no uploading) -----------
source = None
if os.path.exists(DEFAULT_LIST):
    source = DEFAULT_LIST
elif os.path.exists(SAMPLE):
    source = SAMPLE
    st.info("Showing the small sample list (the full list isn't installed yet).")

if source is None:
    st.info("No list found. Add a `latest_sponsors.csv` next to app.py.")
    st.stop()

try:
    long_df = sf.load_and_clean(source)
except Exception as e:
    st.error(f"Sorry, I couldn't read that file. {e}")
    st.stop()

companies = sf.build_company_view(long_df)

detected = long_df.attrs.get("columns_detected", {})
with st.expander("Columns I detected in your file (click to check)"):
    if detected:
        st.table(pd.DataFrame(
            {"This part of the app": list(detected.keys()),
             "...came from your column": list(detected.values())}
        ))

# attach sectors from the cache, then overlay anything looked up live this session
cache = pd.read_csv(CACHE, dtype=str) if os.path.exists(CACHE) else None
companies = sf.attach_sectors(companies, cache)
if live:
    mask = companies["name_key"].isin(live)
    for i in companies[mask].index:
        rec = live[companies.at[i, "name_key"]]
        companies.at[i, "sector_label"] = rec["sector_label"]
        companies.at[i, "sic_codes"] = rec.get("sic_codes", "")

UNKNOWN = {"Not looked up yet", "Unknown", "Unknown (no SIC code)", ""}
known_sectors = (~companies["sector_label"].isin(UNKNOWN)).sum()
is_demo = cache is not None and "last_checked" in cache.columns and \
    set(cache["last_checked"].dropna().unique()) <= {"DEMO"}

if known_sectors == 0:
    st.info("**No sectors filled in yet.** Run the lookup (build_sector_dictionary.py or "
            "weekly_refresh.py) to fill the cache. Visa, Rating and Town filters still work.")
elif is_demo:
    st.info("Using the small **demo** sector data. Run the lookup for real sectors.")
else:
    st.success(f"Sectors loaded for {known_sectors:,} companies.")


# --- 2. Filters ------------------------------------------------------------
st.sidebar.header("Filters")
st.sidebar.caption("Leave a box empty to ignore that filter.")
hide_addr = st.sidebar.checkbox("Hide odd town entries (street addresses)", value=True)
opts = sf.filter_options(companies, long_df, hide_address_like=hide_addr)

pick_routes = st.sidebar.multiselect("Visa route", opts["routes"])
pick_ratings = st.sidebar.multiselect("Rating (A can issue new visas)", opts["ratings"])
pick_towns = st.sidebar.multiselect("Town / City", opts["towns"],
                                     help="Busiest first. Type to search.")
pick_sectors = st.sidebar.multiselect("Sector", opts["sectors"])
st.sidebar.caption("Tip: tech companies are under **Information & communication**.")


# --- 3. Results ------------------------------------------------------------
results = sf.apply_filters(companies, routes=pick_routes or None,
                           ratings=pick_ratings or None, towns=pick_towns or None,
                           sectors=pick_sectors or None)

st.subheader(f"{len(results)} companies found")

show_cols = ["org_name", "town", "county", "sector_label", "best_rating",
             "routes", "sic_codes", "website", "careers_url"]
show_cols = [c for c in show_cols if c in results.columns]
nice = {"org_name": "Company", "town": "Town/City", "county": "County",
        "sector_label": "Sector", "best_rating": "Rating", "routes": "Visa routes",
        "sic_codes": "SIC code", "website": "Website", "careers_url": "Careers page"}

if len(results) == 0:
    st.info("Nothing matched. Try removing a filter to widen the search.")
else:
    st.dataframe(results[show_cols].rename(columns=nice),
                 use_container_width=True, hide_index=True)
    buf = io.StringIO()
    results[show_cols].rename(columns=nice).to_csv(buf, index=False)
    st.download_button("⬇️ Download these results as CSV", data=buf.getvalue(),
                       file_name="my_filtered_sponsors.csv", mime="text/csv")


# --- 4. On-demand LIVE lookup for companies missing a sector ---------------
missing = results[results["sector_label"].isin(UNKNOWN)] if len(results) else results
if len(missing) > 0:
    st.divider()
    st.markdown(f"**{len(missing)} of these don't have a sector yet.**")
    if not API_KEY:
        st.caption("Add an API key to look them up live: put `CH_API_KEY=...` in a `.env` "
                   "file locally, or in Streamlit **Secrets** when deployed.")
    else:
        names = missing["org_name"].tolist()
        chosen = st.multiselect(
            f"Pick companies to look up live now (up to {LIVE_CAP} at a time):",
            names, max_selections=LIVE_CAP,
        )
        if st.button("🔎 Look up sectors now (live)", disabled=not chosen):
            prog = st.progress(0.0)
            for n, name in enumerate(chosen, start=1):
                rec = ch.look_up_company(name, API_KEY)
                live[rec["name_key"]] = rec
                append_to_cache(rec)
                prog.progress(n / len(chosen))
            st.success(f"Looked up {len(chosen)}. Refreshing…")
            st.rerun()

st.caption("Being on the list means a company *can* sponsor — not that it has a job open "
           "now. Always check the company's own careers page.")
