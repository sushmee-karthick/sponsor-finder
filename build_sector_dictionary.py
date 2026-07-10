"""Build the local Companies House sector cache safely.

The cache is always written next to this script, regardless of the shell's
current working directory.  Updates are keyed, buffered, and atomically
replaced so an interrupted write cannot corrupt the existing cache.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping
from getpass import getpass
from pathlib import Path
from typing import Any

import companies_house as ch
import sponsor_filter as sf
from cache_store import CACHE_HEADER, AtomicCSVCache, load_cache_keys

HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "sector_cache.csv"
PAUSE_SECONDS = 0.0  # companies_house.call_api applies per-request rate limiting
CHECKPOINT_EVERY = 250


def load_dotenv() -> None:
    """Read CH_API_KEY from a script-local .env file when it is not set."""

    dotenv_path = HERE / ".env"
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_dotenv()
API_KEY = os.environ.get("CH_API_KEY", "")


def load_done_keys(path: str | os.PathLike[str]) -> set[str]:
    """Compatibility wrapper used by older tooling and tests."""

    return load_cache_keys(path)


def call_api(url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Compatibility wrapper around the shared Companies House client."""

    return ch.call_api(
        url,
        API_KEY,
        params,
        max_attempts=6,
        timeout=30,
    )


def look_up_company(org_name: str, sponsor_town: Any = None) -> dict[str, Any]:
    """Look up one sponsor using the shared matching and retry policy."""

    return ch.look_up_company(org_name, API_KEY, sponsor_town=sponsor_town)


def blank_record(key: str, org_name: str, status: str) -> dict[str, Any]:
    """Return a legacy-shaped blank record for external callers."""

    return ch._blank(key, org_name, status)  # noqa: SLF001 - compatibility shim


def _prompt_for_api_key() -> str:
    print("No Companies House API key was found.")
    return getpass("Paste your Companies House API key (input hidden): ").strip()


def main() -> None:
    global API_KEY
    if not API_KEY:
        API_KEY = _prompt_for_api_key()
    if not API_KEY:
        sys.exit("No key given, stopping. Set CH_API_KEY or run the command again.")

    if len(sys.argv) >= 2:
        csv_path = sys.argv[1]
    else:
        csv_path = input("Type your CSV filename (e.g. sponsors.csv): ").strip().strip('"')

    long_df = sf.load_and_clean(csv_path)
    companies = sf.build_company_view(long_df)
    print(f"Found {len(companies)} unique companies in {csv_path}")

    cache = AtomicCSVCache(CACHE_FILE, fieldnames=CACHE_HEADER)

    # The legacy cache can identify only a normalised company name.  If the
    # sponsor data contains that name at multiple locations, persisting either
    # result would silently assign it to every location in the website.  Leave
    # those identities for review until the cache schema supports sponsor_key.
    ambiguous_key_mask = companies["name_key"].duplicated(keep=False)
    ambiguous_rows = companies[ambiguous_key_mask]
    ambiguous_keys = set(ambiguous_rows["name_key"])
    eligible = companies[~ambiguous_key_mask]
    todo = eligible[~eligible["name_key"].isin(cache.keys)]
    print(
        f"Already done: {len(cache.keys)}  |  Still to look up: {len(todo)}  |  "
        f"Ambiguous name keys skipped: {len(ambiguous_keys)} "
        f"({len(ambiguous_rows)} sponsor rows)"
    )

    buffered = 0
    skipped = 0
    unavailable = 0
    try:
        for index, row in enumerate(todo.itertuples(index=False), start=1):
            name = row.org_name
            sponsor_town = getattr(row, "town", None)
            print(f"[{index}/{len(todo)}] {name}")
            try:
                record = look_up_company(name, sponsor_town=sponsor_town)
            except ch.CompaniesHouseAuthenticationError as exc:
                raise SystemExit(str(exc)) from exc
            except ch.CompaniesHouseUnavailableError as exc:
                unavailable += 1
                print(f"  Temporary API failure; not cached: {exc}")
                continue
            except ch.CompaniesHouseError as exc:
                skipped += 1
                print(f"  API response rejected; not cached: {exc}")
                continue

            # Persist the location-aware identity for exact future attachment.
            record["sponsor_key"] = row.sponsor_key
            if not cache.upsert(record):
                skipped += 1
                reason = record.get("match_reason") or record.get("lookup_status", "not cacheable")
                print(f"  Review needed; not cached: {reason}")
                continue

            buffered += 1
            if buffered >= CHECKPOINT_EVERY:
                cache.flush()
                buffered = 0
            if PAUSE_SECONDS:
                time.sleep(PAUSE_SECONDS)
    finally:
        cache.flush()

    print(
        f"\nDone. Sector data saved atomically to {CACHE_FILE}. "
        f"Review needed: {skipped}; temporary failures left for retry: {unavailable}; "
        f"ambiguous sponsor identities skipped: {len(ambiguous_keys)}."
    )


if __name__ == "__main__":
    main()
