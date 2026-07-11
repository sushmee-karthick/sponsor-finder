"""Validate committed data snapshots against the repository manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_shape(path: Path) -> tuple[list[str], int]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = sum(1 for _ in reader)
    return header, rows


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []

    for section_name in ("sponsor_snapshot", "sector_cache"):
        section = manifest[section_name]
        path = ROOT / section["path"]
        if not path.is_file():
            errors.append(f"{section_name}: missing {path.name}")
            continue

        actual_hash = sha256(path)
        if actual_hash != section["sha256"]:
            errors.append(
                f"{section_name}: SHA-256 mismatch: expected {section['sha256']}, got {actual_hash}"
            )

        header, actual_rows = csv_shape(path)
        if actual_rows != section["row_count"]:
            errors.append(
                f"{section_name}: row-count mismatch: expected {section['row_count']}, "
                f"got {actual_rows}"
            )
        if not header or any(not value.strip() for value in header):
            errors.append(f"{section_name}: invalid CSV header")

        print(f"{section_name}: {actual_rows:,} rows, sha256={actual_hash}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Data snapshots match data_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
