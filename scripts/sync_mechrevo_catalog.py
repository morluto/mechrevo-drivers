#!/usr/bin/env python3
"""Refresh the public MECHREVO marketing catalog without touching hardware.

This directory is an inventory of official website entries, not a Linux
compatibility database. A marketing name never authorizes EC or power writes.
Only standard-library modules are used; importing this file does no I/O.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_URL = "https://gwapi.mechrevo.com/api/v1/client/display_products"
PRODUCT_URL = "https://www.mechrevo.com/cn/products/"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 10000
ENTRY_KEYS = {"id", "name", "slug", "category", "series", "series_id",
              "entry_kind", "url", "status"}
ENTRY_KINDS = {"laptop", "desktop", "software", "peripheral", "unknown"}
_UNSPECIFIED = object()


class CatalogError(ValueError):
    """The source or a snapshot cannot be safely accepted."""


def _integer(value, label, minimum=0, maximum=MAX_ENTRIES):
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _string(value, label, *, nullable=False, maximum=512):
    if nullable and value is None:
        return None
    if (not isinstance(value, str) or not value.strip() or
            len(value) > maximum or any(ord(c) < 32 for c in value)):
        raise CatalogError(f"{label} must be a nonempty bounded string")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(payload):
    try:
        return json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"invalid JSON: {exc}") from exc


def entry_kind(category, series):
    if category in {"游戏笔记本", "轻薄笔记本"}:
        return "laptop"
    if category == "零售台式机":
        return "desktop"
    if category == "应用软件":
        return "software"
    if category == "外设":
        return "peripheral"
    if category == "恒悦商用产品":
        return {"商用笔记本": "laptop", "商用台式机": "desktop"}.get(series, "unknown")
    return "unknown"


def normalize_entry(raw):
    if not isinstance(raw, dict):
        raise CatalogError("source entry must be an object")
    identifier = _string(raw.get("id"), "entry id", maximum=128)
    name = _string(raw.get("name"), "entry name")
    slug = _string(raw.get("slug"), "entry slug")
    category = _string(raw.get("product_category_name"), "category", nullable=True)
    series = _string(raw.get("product_serial_name"), "series", nullable=True)
    series_id = _string(raw.get("product_serial_id"), "series id", nullable=True, maximum=128)
    status = _integer(raw.get("status"), "entry status", maximum=1)
    return {"id": identifier, "name": name, "slug": slug, "category": category,
            "series": series, "series_id": series_id,
            "entry_kind": entry_kind(category, series),
            "url": PRODUCT_URL + quote(slug, safe=""), "status": status}


def fetch_bytes(url, timeout):
    request = Request(url, headers={"User-Agent": "mechrevo-drivers-catalog/1",
                                    "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.geturl().split("?", 1)[0] != API_URL:
                raise CatalogError("catalog API redirected to an unexpected endpoint")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, URLError) as exc:
        raise CatalogError(f"catalog request failed: {exc}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CatalogError("catalog page exceeds response size limit")
    return payload


def fetch_catalog(*, page_size=100, timeout=20, fetcher=None, fetched_at=None):
    """Fetch contiguous pages, rejecting short pages, drift and duplicate IDs."""
    _integer(page_size, "page size", minimum=1, maximum=1000)
    fetcher = fetcher or fetch_bytes
    entries, receipts, seen = [], [], set()
    total = None
    page, pages = 1, 1
    while page <= pages:
        url = API_URL + "?" + urlencode({"limit": page_size, "page": page})
        payload = fetcher(url, timeout)
        if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
            raise CatalogError("catalog fetcher returned invalid or oversized bytes")
        document = parse_json(payload)
        if not isinstance(document, dict) or document.get("status") != "SUCCESS":
            raise CatalogError(f"page {page}: API did not report SUCCESS")
        result = document.get("result")
        if not isinstance(result, dict):
            raise CatalogError(f"page {page}: missing result object")
        reported_total = _integer(result.get("total"), "source total", minimum=1)
        if total is None:
            total = reported_total
            pages = math.ceil(total / page_size)
        elif total != reported_total:
            raise CatalogError(f"page {page}: source total changed during pagination")
        objects = result.get("objects")
        expected = min(page_size, total - (page - 1) * page_size)
        if not isinstance(objects, list) or len(objects) != expected:
            raise CatalogError(f"page {page}: expected {expected} entries")
        for raw in objects:
            entry = normalize_entry(raw)
            if entry["id"] in seen:
                raise CatalogError(f"page {page}: duplicate entry id {entry['id']}")
            seen.add(entry["id"])
            entries.append(entry)
        receipts.append({"page": page, "count": len(objects),
                         "sha256": hashlib.sha256(payload).hexdigest()})
        page += 1
    snapshot = {"schema_version": 1,
                "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "source": {"url": API_URL, "total": total, "page_size": page_size,
                           "pages": pages, "page_receipts": receipts},
                "entries": sorted(entries, key=lambda entry: entry["id"])}
    validate_catalog(snapshot)
    return snapshot


def validate_catalog(snapshot):
    """Validate schema v1, its provenance receipts and every normalized entry."""
    if (not isinstance(snapshot, dict) or
            type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1):
        raise CatalogError("expected catalog schema_version 1")
    if set(snapshot) != {"schema_version", "fetched_at", "source", "entries"}:
        raise CatalogError("unexpected catalog fields")
    timestamp = _string(snapshot.get("fetched_at"), "fetched_at", maximum=64)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise CatalogError("fetched_at must be an ISO 8601 timestamp with timezone") from exc
    source = snapshot.get("source")
    if not isinstance(source, dict) or source.get("url") != API_URL:
        raise CatalogError("unexpected official catalog source")
    if set(source) != {"url", "total", "page_size", "pages", "page_receipts"}:
        raise CatalogError("unexpected catalog source fields")
    total = _integer(source.get("total"), "source total", minimum=1)
    size = _integer(source.get("page_size"), "page size", minimum=1, maximum=1000)
    pages = _integer(source.get("pages"), "pages", minimum=1)
    if pages != math.ceil(total / size):
        raise CatalogError("page count does not cover source total")
    receipts = source.get("page_receipts")
    if not isinstance(receipts, list) or len(receipts) != pages:
        raise CatalogError("incomplete page receipts")
    for number, receipt in enumerate(receipts, 1):
        if not isinstance(receipt, dict) or set(receipt) != {"page", "count", "sha256"}:
            raise CatalogError("invalid page receipt")
        if (type(receipt.get("page")) is not int or receipt["page"] != number or
                type(receipt.get("count")) is not int or
                receipt["count"] != min(size, total - (number - 1) * size) or
                not isinstance(receipt.get("sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])):
            raise CatalogError("invalid or noncontiguous page receipt")
    entries = snapshot.get("entries")
    if not isinstance(entries, list) or len(entries) != total:
        raise CatalogError("entry count does not match source total")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise CatalogError("unexpected normalized entry fields")
        normalized = normalize_entry({"id": entry["id"], "name": entry["name"],
                                      "slug": entry["slug"], "status": entry["status"],
                                      "product_category_name": entry["category"],
                                      "product_serial_name": entry["series"],
                                      "product_serial_id": entry["series_id"]})
        if entry != normalized or entry["entry_kind"] not in ENTRY_KINDS:
            raise CatalogError("entry classification or source URL is inconsistent")
        if entry["id"] in seen:
            raise CatalogError(f"duplicate entry id {entry['id']}")
        seen.add(entry["id"])
    return snapshot


def read_catalog(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise CatalogError("existing output must be a regular file, not a symlink")
    with path.open("rb") as stream:
        payload = stream.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CatalogError("existing catalog exceeds size limit")
    return validate_catalog(parse_json(payload))


def _catalog_digest(snapshot):
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_write(snapshot, path, *, expected_digest=_UNSPECIFIED):
    """Validate, lock the Linux output directory and refuse a stale overwrite.

    The short advisory lock coordinates other synchronizers using this function.
    It creates no lock file and does not claim to lock unrelated text editors.
    """
    validate_catalog(snapshot)
    path = Path(path)
    payload = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CatalogError("normalized catalog exceeds size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        mode, current_digest = 0o644, None
        if path.exists() or path.is_symlink():
            current_digest = _catalog_digest(read_catalog(path))
            mode = stat.S_IMODE(path.stat().st_mode)
        if expected_digest is not _UNSPECIFIED and current_digest != expected_digest:
            raise CatalogError("output changed during refresh; refusing stale overwrite")
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        os.close(directory_fd)


# @mark mechrevo.model_registry role=implementation
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="explicit snapshot path to create, update or check")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="fetch and compare entries; never write")
    action.add_argument("--dry-run", action="store_true", help="fetch and validate; never write")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args(argv)
    if not args.output and not args.dry_run:
        parser.error("--output is required unless --dry-run is used")
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be greater than 0 and at most 120 seconds")
    try:
        previous = None
        if args.output and (args.output.exists() or args.output.is_symlink() or args.check):
            previous = read_catalog(args.output)
        snapshot = fetch_catalog(page_size=args.page_size, timeout=args.timeout)
        summary = {"total": snapshot["source"]["total"], "pages": snapshot["source"]["pages"],
                   "kinds": {kind: sum(entry["entry_kind"] == kind for entry in snapshot["entries"])
                             for kind in sorted(ENTRY_KINDS)}}
        if args.check:
            summary["matches"] = previous["entries"] == snapshot["entries"]
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if summary["matches"] else 1
        if not args.dry_run:
            atomic_write(snapshot, args.output,
                         expected_digest=_catalog_digest(previous) if previous else None)
            summary["output"] = str(args.output)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (CatalogError, OSError) as exc:
        print(f"catalog: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
