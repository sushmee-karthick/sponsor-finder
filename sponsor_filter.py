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

import re
import difflib
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Tidy up company names so the same company always matches itself.
#    "Northwind Data Labs Ltd." and "NORTHWIND DATA LABS LIMITED" should
#    both become "northwind data labs".
# ---------------------------------------------------------------------------
_LEGAL_SUFFIXES = [
    "limited", "ltd", "plc", "llp", "lp", "ltd.", "l.l.p", "company", "co",
]

def normalise_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.lower().strip()
    s = re.sub(r"[.,&/()]", " ", s)          # drop punctuation
    s = re.sub(r"\s+", " ", s).strip()        # collapse spaces
    words = [w for w in s.split(" ") if w not in _LEGAL_SUFFIXES]
    return " ".join(words).strip()


# ---------------------------------------------------------------------------
# 2. Turn a SIC code (the little sector "label" from Companies House) into one
#    of the 21 official sector sections (A-U). We only need the first 2 digits.
# ---------------------------------------------------------------------------
def sic_to_section(sic) -> tuple[str, str]:
    try:
        div = int(str(sic).strip()[:2])
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
    t = re.sub(r"[\-/]+", " ", s.strip())        # hyphens/slashes -> spaces
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
    while len(tokens) > 1 and (any(ch.isdigit() for ch in tokens[-1])
                               or tokens[-1].strip(".,-/") == ""):
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
    "London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh", "Liverpool",
    "Bristol", "Sheffield", "Cardiff", "Belfast", "Newcastle", "Nottingham", "Leicester",
    "Coventry", "Bradford", "Cambridge", "Oxford", "Reading", "Brighton", "Southampton",
    "Portsmouth", "Aberdeen", "Dundee", "Inverness", "Stirling", "Perth", "Swansea",
    "Newport", "Wrexham", "Londonderry", "Derry", "Derby", "Plymouth", "Wolverhampton",
    "Stoke", "Sunderland", "Preston", "Norwich", "Bournemouth", "Luton", "Middlesbrough",
    "Blackpool", "Hull", "York", "Peterborough", "Slough", "Watford", "Exeter", "Gloucester",
    "Bath", "Chelmsford", "Basingstoke", "Ipswich", "Swindon", "Crawley", "Colchester",
    "Maidstone", "Bolton", "Warrington", "Doncaster", "Telford", "Woking", "Guildford",
    "Chester", "Solihull", "Northampton", "Stevenage", "Harlow", "Redhill", "Uxbridge",
]
_MAIN_MULTI = ["Milton Keynes"]
_TOWN_EXCEPTIONS = {"london colney"}      # look like a main city but genuinely aren't
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
    if words & _STREET_WORDS:             # it's a street address, not a town
        return "Other"
    hits = words & set(_MAIN_SINGLE)      # exact word match (fast, precise)
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

    anchors = counts[counts >= 20].index.tolist()          # trusted correct spellings
    anchors_lower = {a.lower(): a for a in anchors}
    anchor_keys = list(anchors_lower.keys())

    mapping = {"": ""}
    for town in counts.index:
        mp = to_main_place(town)
        if mp != "Other":                                  # a known big city / district
            mapping[town] = mp
            continue
        low = town.lower()
        if low in anchors_lower:                           # already a trusted spelling
            mapping[town] = town
            continue
        if len(low) >= 5:                                  # rare spelling -> nearest anchor
            m = difflib.get_close_matches(low, anchor_keys, n=1, cutoff=0.88)
            if m:
                mapping[town] = anchors_lower[m[0]]
                continue
        mapping[town] = town                               # keep its own name

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
            "Could not find the company-name and route columns. "
            f"Columns seen: {list(df.columns)}"
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
    out = out[out["name_key"] != ""]          # drop blank rows
    out.attrs["columns_detected"] = cols       # remember which column was which
    return out


# ---------------------------------------------------------------------------
# 5. Squash the long table into ONE row per company, listing all the visa
#    routes it holds. (A company appears once per route in the raw file.)
# ---------------------------------------------------------------------------
def build_company_view(long_df: pd.DataFrame) -> pd.DataFrame:
    def join_unique(series):
        return "; ".join(sorted({x for x in series if x}))

    grouped = (
        long_df.groupby("name_key")
        .agg(
            org_name=("org_name", "first"),
            town=("town", "first"),
            county=("county", "first"),
            routes=("route", join_unique),
            ratings=("rating", join_unique),
        )
        .reset_index()
    )
    # keep a list version of routes for easy filtering
    grouped["route_list"] = grouped["routes"].str.split("; ")
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
def attach_sectors(companies: pd.DataFrame, cache: pd.DataFrame | None) -> pd.DataFrame:
    companies = companies.copy()
    if cache is None or len(cache) == 0:
        companies["sector_label"] = "Not looked up yet"
        companies["sic_codes"] = ""
        companies["website"] = ""
        companies["careers_url"] = ""
        return companies

    cache = cache.copy()
    cache["name_key"] = cache["name_key"].astype(str)
    keep = ["name_key", "sector_label", "sic_codes", "website", "careers_url"]
    for col in keep:
        if col not in cache.columns:
            cache[col] = ""
    merged = companies.merge(cache[keep], on="name_key", how="left")
    merged["sector_label"] = merged["sector_label"].fillna("Not looked up yet")
    for col in ["sic_codes", "website", "careers_url"]:
        merged[col] = merged[col].fillna("")
    return merged


# ---------------------------------------------------------------------------
# 7. The actual filtering. Everything is optional; an empty choice = no filter.
# ---------------------------------------------------------------------------
def apply_filters(companies: pd.DataFrame,
                  routes=None, ratings=None, towns=None, sectors=None) -> pd.DataFrame:
    df = companies

    if routes:
        df = df[df["route_list"].apply(lambda rl: any(r in rl for r in routes))]
    if ratings:
        df = df[df["best_rating"].isin(ratings)]
    if towns:
        col = "main_place" if "main_place" in df.columns else "town"
        df = df[df[col].isin(towns)]
    if sectors and "sector_label" in df.columns:
        df = df[df["sector_label"].isin(sectors)]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 8. Helper: the list of choices to show in each filter box.
# ---------------------------------------------------------------------------
def filter_options(companies: pd.DataFrame, long_df: pd.DataFrame,
                   hide_address_like: bool = True) -> dict:
    routes = sorted({r for rl in companies["route_list"] for r in rl if r})
    ratings = sorted({r for r in companies["best_rating"] if r in ("A", "B")})
    sectors = (
        sorted(companies["sector_label"].unique().tolist())
        if "sector_label" in companies.columns else []
    )

    # Location options: use the grouped MAIN place (London, Manchester, ... , Other),
    # busiest first, with "Other" pushed to the bottom.
    col = "main_place" if "main_place" in companies.columns else "town"
    place_series = companies[col][companies[col] != ""]
    counts = place_series.value_counts()
    towns = [t for t in counts.index.tolist() if t != "Other"]
    if "Other" in counts.index:
        towns = towns + ["Other"]

    return {"routes": routes, "towns": towns, "ratings": ratings, "sectors": sectors}