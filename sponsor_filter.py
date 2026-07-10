"""
sponsor_filter.py  --  the "brain" of the Sponsor Finder.

This file has NO website code in it. It is just the data work:
  - read the uploaded sponsor CSV
  - clean it and remove duplicate rows
  - (optionally) attach each company's real sector from the sector_cache
  - filter by visa route, rating, town/city and sector

The website (app.py) imports these functions and shows the results.
Keeping the logic here means we can test it without opening the website.
"""

import difflib
import re

import pandas as pd

# ---------------------------------------------------------------------------
# 1. Tidy up company names so the same company always matches itself.
#    "Northwind Data Labs Ltd." and "NORTHWIND DATA LABS LIMITED" should
#    both become "northwind data labs".
# ---------------------------------------------------------------------------
_LEGAL_SUFFIXES = [
    "limited",
    "ltd",
    "plc",
    "llp",
    "lp",
    "ltd.",
    "l.l.p",
    "company",
    "co",
]


def normalise_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.lower().strip()
    s = re.sub(r"[.,&/()]", " ", s)  # drop punctuation
    s = re.sub(r"\s+", " ", s).strip()  # collapse spaces
    words = [w for w in s.split(" ") if w not in _LEGAL_SUFFIXES]
    return " ".join(words).strip()


def _normalise_location(value) -> str:
    """Return a conservative, case-insensitive location identity component."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _key_parts(*parts: str) -> str:
    """Join identity parts without delimiter-collision ambiguity."""
    return "|".join(f"{len(part)}:{part}" for part in parts)


def make_sponsor_key(org_name: str, town: str = "", county: str = "") -> str:
    """Build a stable identity key for a sponsor at a particular location.

    A sponsor name alone is not unique in the Home Office register. The town and
    county are deliberately part of this key so unrelated branches such as two
    different Subway locations are not collapsed into one result.
    """
    return _key_parts(
        normalise_name(org_name),
        _normalise_location(town),
        _normalise_location(county),
    )


# ---------------------------------------------------------------------------
# 2. Turn a SIC code (the little sector "label" from Companies House) into one
#    of the 21 official sector sections (A-U). We only need the first 2 digits.
# ---------------------------------------------------------------------------
def sic_to_section(sic) -> tuple[str, str]:
    raw_code = str(sic).strip() if sic is not None else ""
    if re.fullmatch(r"99999(?:\.0+)?", raw_code):
        # 99999 is the Companies House placeholder for a dormant company, not
        # division 99's extraterritorial-organisation activity (99000).
        return ("?", "Dormant company")
    try:
        div = int(raw_code[:2])
    except (ValueError, TypeError):
        return ("?", "Unknown")
    table = [
        (1, 3, "A", "Agriculture, forestry & fishing"),
        (5, 9, "B", "Mining & quarrying"),
        (10, 33, "C", "Manufacturing"),
        (35, 35, "D", "Electricity & gas supply"),
        (36, 39, "E", "Water, sewerage & waste"),
        (41, 43, "F", "Construction"),
        (45, 47, "G", "Wholesale & retail trade"),
        (49, 53, "H", "Transport & storage"),
        (55, 56, "I", "Accommodation & food service"),
        (58, 63, "J", "Information & communication"),
        (64, 66, "K", "Finance & insurance"),
        (68, 68, "L", "Real estate"),
        (69, 75, "M", "Professional, scientific & technical"),
        (77, 82, "N", "Administrative & support service"),
        (84, 84, "O", "Public administration & defence"),
        (85, 85, "P", "Education"),
        (86, 88, "Q", "Health & social care"),
        (90, 93, "R", "Arts, entertainment & recreation"),
        (94, 96, "S", "Other service activities"),
        (97, 98, "T", "Households as employers"),
        (99, 99, "U", "International organisations"),
    ]
    for lo, hi, letter, label in table:
        if lo <= div <= hi:
            return (letter, label)
    return ("?", "Unknown")


# ---------------------------------------------------------------------------
# 2b. Tidy up messy town names. The real list is typed by hand by thousands of
#     companies, so the same town shows up as "london", "LONDON", "London.",
#     ",London" etc. We make them all into one tidy "London".
# ---------------------------------------------------------------------------
_COUNTRY_RE = re.compile(
    r"[,\s\-/]+(united kingdom|great britain|northern ireland|"
    r"england|scotland|wales|britain|u\.?k\.?|g\.?b\.?|eng|engand|englad)\s*$",
    re.IGNORECASE,
)


def clean_town(s) -> str:
    """Tidy a hand-typed town. Folds safe variants (London, London / London, UK /
    London EC3A 7AG) into one 'London', but leaves genuinely different places
    (Londonderry, London Colney, London Road) alone."""
    if not isinstance(s, str):
        return ""
    t = re.sub(r"[\-/]+", " ", s.strip())  # hyphens/slashes -> spaces
    t = re.sub(r"\s+", " ", t).strip(" ,.;:")
    if not t:
        return ""
    # strip trailing country/region tags, possibly several ("London, England, UK")
    prev = None
    while prev != t:
        prev = t
        t = _COUNTRY_RE.sub("", t).strip(" ,.;:-/")
    if not t:
        return ""
    # the town is the part before the first comma
    main = t.split(",")[0].strip()
    # drop trailing tokens that are postcode fragments (contain a digit) or junk
    tokens = main.split(" ")
    while len(tokens) > 1 and (
        any(ch.isdigit() for ch in tokens[-1]) or tokens[-1].strip(".,-/") == ""
    ):
        tokens.pop()
    main = " ".join(tokens).strip(" ,.;:-/")
    if not main:
        return ""
    # Title Case so LONDON / london / London all become "London"
    return main.title()


def looks_like_address(town: str) -> bool:
    """True if this 'town' is really a street address (starts with a number),
    e.g. '1 Concorde Way' or '111 New Street'. These are junk in the town box."""
    return bool(re.match(r"^\s*\d", str(town)))


# ---- Group towns into recognised MAIN places; everything else -> "Other" ----
MAIN_PLACES = [
    "London",
    "Manchester",
    "Birmingham",
    "Leeds",
    "Glasgow",
    "Edinburgh",
    "Liverpool",
    "Bristol",
    "Sheffield",
    "Cardiff",
    "Belfast",
    "Newcastle",
    "Nottingham",
    "Leicester",
    "Coventry",
    "Bradford",
    "Cambridge",
    "Oxford",
    "Reading",
    "Brighton",
    "Southampton",
    "Portsmouth",
    "Aberdeen",
    "Dundee",
    "Inverness",
    "Stirling",
    "Perth",
    "Swansea",
    "Newport",
    "Wrexham",
    "Londonderry",
    "Derry",
    "Derby",
    "Plymouth",
    "Wolverhampton",
    "Stoke",
    "Sunderland",
    "Preston",
    "Norwich",
    "Bournemouth",
    "Luton",
    "Middlesbrough",
    "Blackpool",
    "Hull",
    "York",
    "Peterborough",
    "Slough",
    "Watford",
    "Exeter",
    "Gloucester",
    "Bath",
    "Chelmsford",
    "Basingstoke",
    "Ipswich",
    "Swindon",
    "Crawley",
    "Colchester",
    "Maidstone",
    "Bolton",
    "Warrington",
    "Doncaster",
    "Telford",
    "Woking",
    "Guildford",
    "Chester",
    "Solihull",
    "Northampton",
    "Stevenage",
    "Harlow",
    "Redhill",
    "Uxbridge",
]
_MAIN_MULTI = ["Milton Keynes"]
_TOWN_EXCEPTIONS = {
    "london colney",
    "newcastle emlyn",
    "newcastle under lyme",
}  # contain a main-city token but are genuinely different places
_STREET_WORDS = {"road", "street", "lane", "avenue", "drive", "close", "court", "way"}
_MAIN_SINGLE = {p.lower(): p for p in MAIN_PLACES}
# Only the longer names are safe to fuzzy-match (catches 'Birmingam' -> 'Birmingham'
# without wrongly merging short names like Bath/York/Hull).
_MAIN_FUZZY = {p.lower(): p for p in MAIN_PLACES if len(p) >= 7}


def to_main_place(town) -> str:
    """Fold a town into a recognised main place, or 'Other'. Blank -> '' (no filter).
    Handles districts (London Paddington -> London) and typos (Birmingam -> Birmingham)."""
    if not isinstance(town, str) or not town.strip():
        return ""
    low = town.lower().strip()
    if low in _TOWN_EXCEPTIONS:
        return "Other"
    words = set(re.findall(r"[a-z]+", low))
    if words & _STREET_WORDS:  # it's a street address, not a town
        return "Other"
    hits = words & set(_MAIN_SINGLE)  # exact word match (fast, precise)
    if hits:
        return _MAIN_SINGLE[max(hits, key=len)]
    for phrase in _MAIN_MULTI:
        if re.search(r"\b" + re.escape(phrase.lower()) + r"\b", low):
            return phrase
    # fuzzy: catch misspellings of the longer city names
    for cand in [low] + [w for w in words if len(w) >= 6]:
        match = difflib.get_close_matches(cand, list(_MAIN_FUZZY), n=1, cutoff=0.87)
        if match:
            return _MAIN_FUZZY[match[0]]
    return "Other"


_CANON_CACHE = {}


def canonicalise_places(town_series: pd.Series) -> dict:
    """Return a mapping {raw_town -> clean canonical name}. Every real place keeps
    its own name (NO 'Other' bucket); the only changes are:
      * big cities and their districts fold together (London Paddington -> London),
      * misspellings merge into the common spelling (Birmingam -> Birmingham),
        and rarer typos of any town fold into that town's frequent spelling.
    'Frequent' spellings are trusted as correct because they appear many times.
    The result is cached so the app doesn't redo this work on every click."""
    counts = town_series[town_series != ""].value_counts()
    cache_key = hash(tuple(counts.index.tolist()))
    if cache_key in _CANON_CACHE:
        return _CANON_CACHE[cache_key]

    anchors = counts[counts >= 20].index.tolist()  # trusted correct spellings
    anchors_lower = {a.lower(): a for a in anchors}
    anchor_keys = list(anchors_lower.keys())

    mapping = {"": ""}
    for town in counts.index:
        mp = to_main_place(town)
        if mp != "Other":  # a known big city / district
            mapping[town] = mp
            continue
        low = town.lower()
        if low in anchors_lower:  # already a trusted spelling
            mapping[town] = town
            continue
        if len(low) >= 5:  # rare spelling -> nearest anchor
            m = difflib.get_close_matches(low, anchor_keys, n=1, cutoff=0.88)
            if m:
                mapping[town] = anchors_lower[m[0]]
                continue
        mapping[town] = town  # keep its own name

    _CANON_CACHE[cache_key] = mapping
    return mapping


# ---------------------------------------------------------------------------
# 3. Work out which column in the CSV is which, even if the Home Office
#    renames the headers. We match on keywords, not exact spelling.
# ---------------------------------------------------------------------------
def detect_columns(df: pd.DataFrame) -> dict:
    found = {}
    for col in df.columns:
        c = col.lower()
        if "organis" in c or "company" in c or ("name" in c and "town" not in c):
            found.setdefault("org_name", col)
        elif "town" in c or "city" in c:
            found.setdefault("town", col)
        elif "county" in c:
            found.setdefault("county", col)
        elif "rating" in c or "type" in c:
            found.setdefault("type_rating", col)
        elif "route" in c:
            found.setdefault("route", col)
    return found


# ---------------------------------------------------------------------------
# 4. Read the CSV, rename columns to simple names, pull the A/B rating out of
#    the "Type & rating" text, and make a tidy "long" table (one row per
#    company-and-route).
# ---------------------------------------------------------------------------
def load_and_clean(source) -> pd.DataFrame:
    df = pd.read_csv(source, dtype=str).fillna("")
    cols = detect_columns(df)
    if "org_name" not in cols or "route" not in cols:
        raise ValueError(
            f"Could not find the company-name and route columns. Columns seen: {list(df.columns)}"
        )

    out = pd.DataFrame()
    out["org_name"] = df[cols["org_name"]].str.strip()
    out["town"] = df[cols["town"]].apply(clean_town) if "town" in cols else ""
    out["county"] = df[cols["county"]].str.strip() if "county" in cols else ""
    out["route"] = df[cols["route"]].str.strip()
    type_rating = df[cols["type_rating"]].str.strip() if "type_rating" in cols else ""
    out["type_rating"] = type_rating

    # rating = the A or B inside "(A rating)" / "(B rating)"
    out["rating"] = out["type_rating"].str.extract(r"\(([AB])\s*rating\)", expand=False).fillna("?")

    out["name_key"] = out["org_name"].apply(normalise_name)
    out = out[out["name_key"] != ""]  # drop blank rows
    out.attrs["columns_detected"] = cols  # remember which column was which
    return out


# ---------------------------------------------------------------------------
# 5. Squash the long table into ONE row per sponsor location, listing all the
#    visa routes it holds. (A sponsor appears once per route in the raw file.)
# ---------------------------------------------------------------------------
def build_company_view(long_df: pd.DataFrame) -> pd.DataFrame:
    work = long_df.copy()

    for col in ("org_name", "town", "county", "route", "rating"):
        if col not in work.columns:
            work[col] = ""
        work[col] = work[col].apply(lambda value: value.strip() if isinstance(value, str) else "")

    # Do not trust a caller-supplied key blindly: old dataframes may not have
    # one, and a blank key must never make unrelated sponsors share a group.
    computed_name_keys = work["org_name"].apply(normalise_name)
    if "name_key" not in work.columns:
        work["name_key"] = computed_name_keys
    else:
        supplied_name_keys = work["name_key"].apply(normalise_name)
        work["name_key"] = supplied_name_keys.where(supplied_name_keys != "", computed_name_keys)

    work = work[work["name_key"] != ""]
    work["sponsor_key"] = [
        make_sponsor_key(org_name, town, county)
        for org_name, town, county in zip(
            work["org_name"], work["town"], work["county"], strict=False
        )
    ]
    work["_route_rating_pair"] = list(zip(work["route"], work["rating"], strict=False))

    def join_unique(series):
        return "; ".join(sorted({x for x in series if x}))

    def collect_route_rating_pairs(series):
        return tuple(sorted({(route, rating) for route, rating in series if route}))

    grouped = (
        work.groupby("sponsor_key", sort=False)
        .agg(
            name_key=("name_key", "first"),
            org_name=("org_name", "first"),
            town=("town", "first"),
            county=("county", "first"),
            routes=("route", join_unique),
            ratings=("rating", join_unique),
            route_rating_pairs=("_route_rating_pair", collect_route_rating_pairs),
        )
        .reset_index()
    )
    # keep a list version of routes for easy filtering
    grouped["route_list"] = grouped["routes"].apply(
        lambda routes: routes.split("; ") if routes else []
    )
    grouped["best_rating"] = grouped["ratings"].apply(
        lambda r: "A" if "A" in r else ("B" if "B" in r else "?")
    )
    # Clean each company's town into one canonical name (no 'Other' bucket).
    _map = canonicalise_places(grouped["town"])
    grouped["main_place"] = grouped["town"].map(_map).fillna(grouped["town"])
    return grouped


# ---------------------------------------------------------------------------
# 6. Attach the real sector to each company using the sector_cache (built
#    separately from Companies House). If we have no info yet, we say so
#    honestly instead of guessing.
# ---------------------------------------------------------------------------
_CACHE_OUTPUT_DEFAULTS = {
    "company_number": "",
    "sic_codes": "",
    "sic_section": "?",
    "sector_label": "Not looked up yet",
    "website": "",
    "careers_url": "",
    "company_status": "",
    "last_checked": "",
    "matched_company_name": "",
    "matched_location": "",
    "lookup_status": "",
    "match_confidence": "",
    "match_reason": "",
    "matching_policy": "",
}
_UNKNOWN_CACHE_SECTORS = {
    "",
    "Not looked up yet",
    "Unknown",
    "Unknown (no SIC code)",
}


def _deduplicate_cache(cache: pd.DataFrame, key: str) -> pd.DataFrame:
    """Select one deterministic, useful cache row per identity key."""
    candidates = cache[cache[key] != ""].copy()
    if candidates.empty:
        return candidates

    candidates["_cache_enriched"] = (
        ~candidates["sector_label"].isin(_UNKNOWN_CACHE_SECTORS)
        | (candidates["sic_codes"] != "")
        | (candidates["company_number"] != "")
    )
    candidates["_cache_completeness"] = candidates[list(_CACHE_OUTPUT_DEFAULTS)].ne("").sum(axis=1)
    candidates["_cache_date"] = pd.to_datetime(candidates["last_checked"], errors="coerce")
    candidates["_cache_order"] = range(len(candidates))

    candidates = candidates.sort_values(
        [key, "_cache_enriched", "_cache_date", "_cache_completeness", "_cache_order"],
        kind="stable",
        na_position="first",
    ).drop_duplicates(key, keep="last")
    return candidates.drop(
        columns=[
            "_cache_enriched",
            "_cache_completeness",
            "_cache_date",
            "_cache_order",
        ]
    )


def attach_sectors(companies: pd.DataFrame, cache: pd.DataFrame | None) -> pd.DataFrame:
    companies = companies.copy()

    computed_company_keys = (
        companies["org_name"].apply(normalise_name)
        if "org_name" in companies.columns
        else pd.Series("", index=companies.index, dtype=object)
    )
    if "name_key" in companies.columns:
        supplied_company_keys = companies["name_key"].apply(normalise_name)
        companies["name_key"] = computed_company_keys.where(
            computed_company_keys != "", supplied_company_keys
        )
    else:
        companies["name_key"] = computed_company_keys

    if "sponsor_key" not in companies.columns:
        towns = companies.get("town", pd.Series("", index=companies.index))
        counties = companies.get("county", pd.Series("", index=companies.index))
        companies["sponsor_key"] = [
            make_sponsor_key(name_key, town, county)
            for name_key, town, county in zip(companies["name_key"], towns, counties, strict=False)
        ]

    # Make repeated attachment safe instead of producing _x/_y columns.
    companies = companies.drop(
        columns=[col for col in _CACHE_OUTPUT_DEFAULTS if col in companies.columns]
    )

    if cache is None or len(cache) == 0:
        for col, default in _CACHE_OUTPUT_DEFAULTS.items():
            companies[col] = default
        return companies

    cache = cache.copy()
    for col in _CACHE_OUTPUT_DEFAULTS:
        if col not in cache.columns:
            cache[col] = ""
        cache[col] = cache[col].fillna("").astype(str).str.strip()

    # Repair legacy cache rows created before 99999 was distinguished from the
    # true division-99 SIC code (99000). Without this migration-at-read-time,
    # the existing cache would keep displaying dormant companies as
    # international organisations indefinitely.
    first_sic_code = cache["sic_codes"].str.split(",").str[0].str.strip()
    dormant_mask = first_sic_code.str.fullmatch(r"99999(?:\.0+)?", na=False)
    cache.loc[dormant_mask, "sic_section"] = "?"
    cache.loc[dormant_mask, "sector_label"] = "Dormant company"

    supplied_cache_keys = (
        cache["name_key"].apply(normalise_name)
        if "name_key" in cache.columns
        else pd.Series("", index=cache.index, dtype=object)
    )
    computed_cache_keys = (
        cache["org_name"].apply(normalise_name)
        if "org_name" in cache.columns
        else pd.Series("", index=cache.index, dtype=object)
    )
    # Legacy cache files sometimes have a missing or stale name_key. Prefer the
    # source organisation name when available, then fall back to the old key.
    cache["name_key"] = computed_cache_keys.where(computed_cache_keys != "", supplied_cache_keys)

    sponsor_cache = None
    legacy_name_cache = cache
    if "sponsor_key" in cache.columns:
        cache["sponsor_key"] = cache["sponsor_key"].fillna("").astype(str).str.strip()
        sponsor_cache = _deduplicate_cache(cache, "sponsor_key").set_index("sponsor_key")
        # Rows with a sponsor_key are safe only for that exact location. They
        # must not become a name-only fallback for a different branch.
        legacy_name_cache = cache[cache["sponsor_key"] == ""]

    name_cache = _deduplicate_cache(legacy_name_cache, "name_key").set_index("name_key")

    ambiguous_name = (companies["name_key"] != "") & companies["name_key"].duplicated(keep=False)
    legacy_match = companies["name_key"].isin(name_cache.index)
    exact_match = pd.Series(False, index=companies.index)
    if sponsor_cache is not None:
        exact_match = companies["sponsor_key"].isin(sponsor_cache.index)

    for col, default in _CACHE_OUTPUT_DEFAULTS.items():
        by_name = companies["name_key"].map(name_cache[col]).mask(ambiguous_name)
        if sponsor_cache is not None:
            by_sponsor = companies["sponsor_key"].map(sponsor_cache[col])
            values = by_sponsor.combine_first(by_name)
        else:
            values = by_name
        companies[col] = values.fillna(default)

    legacy_applied = legacy_match & ~ambiguous_name & ~exact_match
    blank_lookup_status = companies["lookup_status"] == ""
    companies.loc[legacy_applied & blank_lookup_status, "lookup_status"] = "legacy_cache"
    blank_matching_policy = companies["matching_policy"] == ""
    companies.loc[legacy_applied & blank_matching_policy, "matching_policy"] = "legacy_name_key"
    blank_match_reason = companies["match_reason"] == ""
    companies.loc[legacy_applied & blank_match_reason, "match_reason"] = (
        "Legacy cache match was based on sponsor name only."
    )

    needs_verification = ambiguous_name & legacy_match & ~exact_match
    companies.loc[needs_verification, "sector_label"] = "Needs verification"
    companies.loc[needs_verification, "lookup_status"] = "needs_verification"
    companies.loc[needs_verification, "match_reason"] = (
        "Multiple sponsor locations share this legacy name key."
    )
    companies.loc[needs_verification, "matching_policy"] = "legacy_name_key"

    return companies


# ---------------------------------------------------------------------------
# 7. The actual filtering. Everything is optional; an empty choice = no filter.
# ---------------------------------------------------------------------------
def _route_values(value) -> set[str]:
    if isinstance(value, str):
        return {route for route in value.split("; ") if route}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {route for route in value if isinstance(route, str) and route}
    return set()


def _route_rating_values(value) -> set[tuple[str, str]]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    pairs = set()
    for pair in value:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            route, rating = pair
            if isinstance(route, str) and isinstance(rating, str) and route:
                pairs.add((route, rating))
    return pairs


def apply_filters(
    companies: pd.DataFrame, routes=None, ratings=None, towns=None, sectors=None
) -> pd.DataFrame:
    df = companies
    selected_routes = {route for route in (routes or []) if route}
    selected_ratings = {rating for rating in (ratings or []) if rating}

    if selected_routes and selected_ratings and "route_rating_pairs" in df.columns:
        # A route and rating must occur on the same raw sponsor-register row.
        # Aggregating them independently would make an A-rated Skilled Worker
        # route falsely satisfy an A + Global Business Mobility search.
        def matches_pair(row) -> bool:
            pairs = _route_rating_values(row["route_rating_pairs"])
            if pairs:
                return any(
                    route in selected_routes and rating in selected_ratings
                    for route, rating in pairs
                )
            return (
                bool(_route_values(row.get("route_list", "")) & selected_routes)
                and row.get("best_rating", "") in selected_ratings
            )

        df = df[df.apply(matches_pair, axis=1)]
    else:
        if selected_routes:
            df = df[
                df["route_list"].apply(lambda value: bool(_route_values(value) & selected_routes))
            ]
        if selected_ratings:
            if "route_rating_pairs" in df.columns:
                df = df[
                    df["route_rating_pairs"].apply(
                        lambda value: any(
                            rating in selected_ratings for _, rating in _route_rating_values(value)
                        )
                    )
                ]
            else:
                df = df[df["best_rating"].isin(selected_ratings)]
    if towns:
        col = "main_place" if "main_place" in df.columns else "town"
        df = df[df[col].isin(towns)]
    if sectors and "sector_label" in df.columns:
        df = df[df["sector_label"].isin(sectors)]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 8. Helper: the list of choices to show in each filter box.
# ---------------------------------------------------------------------------
def filter_options(
    companies: pd.DataFrame, long_df: pd.DataFrame, hide_address_like: bool = True
) -> dict:
    routes = sorted({route for value in companies["route_list"] for route in _route_values(value)})
    ratings = set()
    if "route_rating_pairs" in companies.columns:
        ratings.update(
            rating
            for value in companies["route_rating_pairs"]
            for _, rating in _route_rating_values(value)
            if rating in ("A", "B")
        )
    if "rating" in long_df.columns:
        ratings.update(rating for rating in long_df["rating"] if rating in ("A", "B"))
    if not ratings and "best_rating" in companies.columns:
        ratings.update(rating for rating in companies["best_rating"] if rating in ("A", "B"))
    ratings = sorted(ratings)
    sectors = (
        sorted(companies["sector_label"].unique().tolist())
        if "sector_label" in companies.columns
        else []
    )

    # Location options: use the grouped MAIN place (London, Manchester, ... , Other),
    # busiest first, with "Other" pushed to the bottom.
    col = "main_place" if "main_place" in companies.columns else "town"
    locations = companies
    if hide_address_like:
        raw_location_col = "town" if "town" in companies.columns else col
        locations = companies[~companies[raw_location_col].apply(looks_like_address)]
    place_series = locations[col][locations[col] != ""]
    counts = place_series.value_counts()
    towns = [t for t in counts.index.tolist() if t != "Other"]
    if "Other" in counts.index:
        towns = towns + ["Other"]

    return {"routes": routes, "towns": towns, "ratings": ratings, "sectors": sectors}
