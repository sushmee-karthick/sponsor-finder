"""
companies_house.py  --  look up ONE company's sector on Companies House.
Used by the website's on-demand live lookup.
"""

import time
import requests
import sponsor_filter as sf

SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
PROFILE_URL = "https://api.company-information.service.gov.uk/company/{}"


def call_api(url, api_key, params=None):
    for attempt in range(4):
        r = requests.get(url, params=params, auth=(api_key, ""), timeout=20)
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    return None


def look_up_company(org_name, api_key):
    key = sf.normalise_name(org_name)
    try:
        search = call_api(SEARCH_URL, api_key, {"q": org_name, "items_per_page": 5})
    except Exception:
        return _blank(key, org_name, "lookup failed")

    if not search or not search.get("items"):
        return _blank(key, org_name, "no match found")

    best = search["items"][0]
    number = best.get("company_number", "")
    status = best.get("company_status", "")

    try:
        profile = call_api(PROFILE_URL.format(number), api_key) if number else None
    except Exception:
        profile = None
    sic_codes = profile.get("sic_codes", []) if profile else []

    section, label = ("?", "Unknown")
    if sic_codes:
        section, label = sf.sic_to_section(sic_codes[0])

    return {
        "name_key": key, "org_name": org_name, "company_number": number,
        "sic_codes": ", ".join(sic_codes), "sic_section": section,
        "sector_label": label if sic_codes else "Unknown (no SIC code)",
        "website": "", "careers_url": "", "company_status": status,
        "last_checked": time.strftime("%Y-%m-%d"),
    }


def _blank(key, org_name, status):
    return {
        "name_key": key, "org_name": org_name, "company_number": "",
        "sic_codes": "", "sic_section": "?", "sector_label": "Unknown",
        "website": "", "careers_url": "", "company_status": status,
        "last_checked": time.strftime("%Y-%m-%d"),
    }