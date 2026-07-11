"""Atomic, keyed CSV cache updates shared by the app and batch builder."""

from __future__ import annotations

import csv
import hashlib
import os
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # ``fcntl`` is available on the Linux/macOS deployment targets.
    import fcntl
except ImportError:  # pragma: no cover - fallback for unsupported platforms
    fcntl = None


CACHE_HEADER = [
    "name_key",
    "sponsor_key",
    "org_name",
    "company_number",
    "sic_codes",
    "sic_section",
    "sector_label",
    "website",
    "careers_url",
    "company_status",
    "last_checked",
    "matched_company_name",
    "matched_location",
    "lookup_status",
    "match_confidence",
    "match_reason",
    "matching_policy",
]

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _exclusive_cache_lock(path: Path):
    """Coordinate atomic read-modify-write updates across app processes."""

    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"sponsor-finder-{digest}.lock"
    with _thread_lock(path), lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _clean_record(record: Mapping[str, Any], fieldnames: Sequence[str]) -> dict[str, str]:
    return {
        field: "" if record.get(field) is None else str(record.get(field, ""))
        for field in fieldnames
    }


def _read_records(
    path: Path,
    fieldnames: Sequence[str],
    key_field: str,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    records: list[dict[str, str]] = []
    positions: dict[str, int] = {}
    if not path.exists():
        return records, positions

    with path.open(newline="", encoding="utf-8") as cache_file:
        reader = csv.DictReader(cache_file)
        if reader.fieldnames is None:
            return records, positions
        if key_field not in reader.fieldnames:
            raise ValueError(f"Cache is missing required column {key_field!r}: {path}")
        for raw_record in reader:
            record = _clean_record(raw_record, fieldnames)
            key = record.get(key_field, "").strip()
            if not key:
                continue
            if key in positions:
                records[positions[key]] = record
            else:
                positions[key] = len(records)
                records.append(record)
    return records, positions


def load_cache_keys(path: str | os.PathLike[str], *, key_field: str = "name_key") -> set[str]:
    """Read the non-empty cache keys without exposing mutable records."""

    cache_path = Path(path)
    if not cache_path.exists():
        return set()
    with cache_path.open(newline="", encoding="utf-8") as cache_file:
        reader = csv.DictReader(cache_file)
        if reader.fieldnames is None:
            return set()
        if key_field not in reader.fieldnames:
            raise ValueError(f"Cache is missing required column {key_field!r}: {cache_path}")
        return {
            str(record.get(key_field, "")).strip()
            for record in reader
            if str(record.get(key_field, "")).strip()
        }


def _atomic_write(
    path: Path,
    records: Iterable[Mapping[str, str]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as cache_file:
            writer = csv.DictWriter(cache_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
            cache_file.flush()
            os.fsync(cache_file.fileno())

        if path.exists():
            os.chmod(temporary_path, path.stat().st_mode)
        os.replace(temporary_path, path)

        # Ensure the directory entry is durable where the platform supports it.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:  # pragma: no cover - filesystem-specific safeguard
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:  # pragma: no cover - filesystem-specific safeguard
                pass
            finally:
                os.close(directory_fd)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def upsert_cache_records(
    path: str | os.PathLike[str],
    records: Iterable[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str] = CACHE_HEADER,
    key_field: str = "name_key",
) -> int:
    """Atomically insert or replace cache records, returning accepted count.

    Records explicitly marked ``cacheable=False`` are ignored.  Existing
    duplicate keys are collapsed and the most recently supplied value wins.
    """

    fields = tuple(fieldnames)
    if not fields or key_field not in fields:
        raise ValueError(f"fieldnames must contain {key_field!r}")

    pending: list[dict[str, str]] = []
    for raw_record in records:
        if raw_record.get("cacheable", True) is False:
            continue
        record = _clean_record(raw_record, fields)
        if not record[key_field].strip():
            raise ValueError(f"Cache record must contain a non-empty {key_field!r}")
        pending.append(record)
    if not pending:
        return 0

    cache_path = Path(path)
    with _exclusive_cache_lock(cache_path):
        existing, positions = _read_records(cache_path, fields, key_field)
        for record in pending:
            key = record[key_field].strip()
            if key in positions:
                existing[positions[key]] = record
            else:
                positions[key] = len(existing)
                existing.append(record)
        _atomic_write(cache_path, existing, fields)
    return len(pending)


def upsert_cache_record(
    path: str | os.PathLike[str],
    record: Mapping[str, Any],
    *,
    fieldnames: Sequence[str] = CACHE_HEADER,
    key_field: str = "name_key",
) -> bool:
    """Atomically upsert one record; return False for a non-cacheable result."""

    return bool(
        upsert_cache_records(
            path,
            [record],
            fieldnames=fieldnames,
            key_field=key_field,
        )
    )


class AtomicCSVCache:
    """Buffer batch records and periodically merge them into an atomic cache."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        fieldnames: Sequence[str] = CACHE_HEADER,
        key_field: str = "name_key",
    ) -> None:
        self.path = Path(path)
        self.fieldnames = tuple(fieldnames)
        self.key_field = key_field
        self.keys = load_cache_keys(self.path, key_field=key_field)
        self._pending: dict[str, Mapping[str, Any]] = {}

    def upsert(self, record: Mapping[str, Any]) -> bool:
        if record.get("cacheable", True) is False:
            return False
        key = str(record.get(self.key_field, "")).strip()
        if not key:
            raise ValueError(f"Cache record must contain a non-empty {self.key_field!r}")
        self._pending[key] = record
        self.keys.add(key)
        return True

    def flush(self) -> int:
        if not self._pending:
            return 0
        pending = list(self._pending.values())
        written = upsert_cache_records(
            self.path,
            pending,
            fieldnames=self.fieldnames,
            key_field=self.key_field,
        )
        self._pending.clear()
        return written
