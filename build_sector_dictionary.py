"""
build_sector_dictionary.py  --  looks up each company's sector on Companies House.
Run it, and it will ASK you to paste your API key. No 'set' or '$env:' needed.
"""

import os
import sys
import time
import csv
import requests

import sponsor_filter as sf


def load_dotenv():
    """If there's a .env file next to this script, read CH_API_KEY from it."""
    import pathlib
    p = pathlib.Path(__file__).with_name(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()
API_KEY = os.environ.get("CH_API_KEY", "")
SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
PROFILE_URL = "https://api.company-information.service.gov.uk/company/{}"
CACHE_FILE = "sector_cache.csv"
PAUSE_SECONDS = 0.7

CACHE_HEADER = ["name_key", "org_name", "company_number", "sic_codes",
                "sic_section", "sector_label", "website", "careers_url",
                "company_status", "last_checked"]


def load_done_keys(path):
    done = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["name_key"])
    return done


def call_api(url, params=None):
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, auth=(API_KEY, ""), timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(3)          # network blip -> wait and retry
            continue
        if r.status_code == 429:               # rate limit
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (500, 502, 503, 504):   # their server hiccup
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    return None


def look_up_company(org_name):
    key = sf.normalise_name(org_name)
    search = call_api(SEARCH_URL, {"q": org_name, "items_per_page": 5})
    if not search or not search.get("items"):
        return blank_record(key, org_name, status="no match found")
    best = search["items"][0]
    number = best.get("company_number", "")
    status = best.get("company_status", "")
    profile = call_api(PROFILE_URL.format(number)) if number else None
    sic_codes = profile.get("sic_codes", []) if profile else []
    sic_str = ", ".join(sic_codes)
    section, label = ("?", "Unknown")
    if sic_codes:
        section, label = sf.sic_to_section(sic_codes[0])
    return {
        "name_key": key, "org_name": org_name, "company_number": number,
        "sic_codes": sic_str, "sic_section": section,
        "sector_label": label if sic_codes else "Unknown (no SIC code)",
        "website": "", "careers_url": "", "company_status": status,
        "last_checked": time.strftime("%Y-%m-%d"),
    }


def blank_record(key, org_name, status):
    return {
        "name_key": key, "org_name": org_name, "company_number": "",
        "sic_codes": "", "sic_section": "?", "sector_label": "Unknown",
        "website": "", "careers_url": "", "company_status": status,
        "last_checked": time.strftime("%Y-%m-%d"),
    }


def main():
    global API_KEY
    if not API_KEY:
        print("No API key found yet.")
        API_KEY = input("Paste your Companies House API key and press Enter: ").strip()
    if not API_KEY:
        sys.exit("No key given, stopping. Run it again and paste your key when asked.")

    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
    else:
        csv_path = input("Type your CSV filename (e.g. sponsors.csv): ").strip().strip('"')

    long_df = sf.load_and_clean(csv_path)
    companies = sf.build_company_view(long_df)
    print(f"Found {len(companies)} unique companies in {csv_path}")

    done = load_done_keys(CACHE_FILE)
    todo = companies[~companies["name_key"].isin(done)]
    print(f"Already done: {len(done)}  |  Still to look up: {len(todo)}")

    new_file = not os.path.exists(CACHE_FILE)
    with open(CACHE_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_HEADER)
        if new_file:
            writer.writeheader()
        for i, row in enumerate(todo.itertuples(index=False), start=1):
            name = row.org_name
            print(f"[{i}/{len(todo)}] {name}")
            record = look_up_company(name)
            writer.writerow(record)
            f.flush()
            time.sleep(PAUSE_SECONDS)

    print(f"\nDone. Sector data saved to {CACHE_FILE}. Re-run anytime to add new ones.")


if __name__ == "__main__":
    main()