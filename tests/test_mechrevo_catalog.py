#!/usr/bin/env python3
"""Offline regression tests for the official website catalog synchronizer."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_mechrevo_catalog.py"
SPEC = importlib.util.spec_from_file_location("sync_mechrevo_catalog", SCRIPT)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)
STAMP = "2026-10-18T00:00:00Z"


def raw_entry(identifier="a", **changes):
    entry = {"id": identifier, "name": "旷世 16 Pro", "slug": identifier,
             "product_category_name": "游戏笔记本", "product_serial_name": "旷世",
             "product_serial_id": "series1", "status": 1,
             "creator_mobile": "must-not-be-exported", "detail": "private or irrelevant"}
    entry.update(changes)
    return entry


def page_bytes(entries, total=None, **changes):
    document = {"status": "SUCCESS", "result": {
        "total": len(entries) if total is None else total, "objects": entries}}
    document.update(changes)
    return json.dumps(document, ensure_ascii=False).encode()


def fetch_pages(pages):
    calls = []

    def fetcher(url, timeout):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        return pages[page - 1]

    fetcher.calls = calls
    return fetcher


def snapshot():
    return catalog.fetch_catalog(fetcher=fetch_pages([page_bytes([raw_entry()])]),
                                 fetched_at=STAMP)


class PaginationTests(unittest.TestCase):
    # @mark mechrevo.model_registry role=verification
    def test_complete_contiguous_pagination_and_receipts(self):
        fetcher = fetch_pages([page_bytes([raw_entry("b"), raw_entry("a")], total=3),
                               page_bytes([raw_entry("c")], total=3)])
        result = catalog.fetch_catalog(page_size=2, fetcher=fetcher, fetched_at=STAMP)
        self.assertEqual([entry["id"] for entry in result["entries"]], ["a", "b", "c"])
        self.assertEqual(result["source"]["pages"], 2)
        self.assertEqual([r["count"] for r in result["source"]["page_receipts"]], [2, 1])
        self.assertEqual(len(fetcher.calls), 2)
        self.assertEqual(parse_qs(urlsplit(fetcher.calls[1]).query), {"limit": ["2"], "page": ["2"]})
        self.assertEqual(set(result["entries"][0]), catalog.ENTRY_KEYS)
        self.assertNotIn("must-not-be-exported", json.dumps(result))

    def test_exact_multiple_needs_no_empty_extra_page(self):
        fetcher = fetch_pages([page_bytes([raw_entry("a")], total=2),
                               page_bytes([raw_entry("b")], total=2)])
        self.assertEqual(catalog.fetch_catalog(page_size=1, fetcher=fetcher)["source"]["pages"], 2)
        self.assertEqual(len(fetcher.calls), 2)

    def test_total_drift_rejected(self):
        fetcher = fetch_pages([page_bytes([raw_entry("a")], total=2),
                               page_bytes([raw_entry("b")], total=3)])
        with self.assertRaisesRegex(catalog.CatalogError, "total changed"):
            catalog.fetch_catalog(page_size=1, fetcher=fetcher)

    def test_duplicate_across_pages_rejected(self):
        fetcher = fetch_pages([page_bytes([raw_entry("a")], total=2),
                               page_bytes([raw_entry("a")], total=2)])
        with self.assertRaisesRegex(catalog.CatalogError, "duplicate entry"):
            catalog.fetch_catalog(page_size=1, fetcher=fetcher)

    def test_duplicate_within_page_rejected(self):
        with self.assertRaisesRegex(catalog.CatalogError, "duplicate entry"):
            catalog.fetch_catalog(fetcher=fetch_pages([page_bytes([raw_entry(), raw_entry()])]))

    def test_short_empty_and_oversized_pages_rejected(self):
        for objects in [[], [raw_entry()], [raw_entry("a"), raw_entry("b"), raw_entry("c")]]:
            with self.subTest(length=len(objects)), self.assertRaises(catalog.CatalogError):
                catalog.fetch_catalog(page_size=2, fetcher=fetch_pages([page_bytes(objects, total=3)]))

    def test_source_failure_and_malformed_payload_rejected(self):
        for payload in [b"not json", b'{"status":"SUCCESS","status":"FAILED"}',
                        page_bytes([raw_entry()], status="FAILED"), b'[]',
                        page_bytes([raw_entry()], total=True), page_bytes([], total=0),
                        page_bytes([raw_entry()], total=catalog.MAX_ENTRIES + 1)]:
            with self.subTest(payload=payload[:60]), self.assertRaises(catalog.CatalogError):
                catalog.fetch_catalog(fetcher=fetch_pages([payload]))

    def test_invalid_page_sizes_rejected_before_network(self):
        for size in [0, -1, 1001, True]:
            fetcher = fetch_pages([])
            with self.subTest(size=size), self.assertRaises(catalog.CatalogError):
                catalog.fetch_catalog(page_size=size, fetcher=fetcher)
            self.assertEqual(fetcher.calls, [])

    def test_network_failure_has_a_clear_error(self):
        with patch.object(catalog, "urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(catalog.CatalogError, "request failed"):
                catalog.fetch_bytes(catalog.API_URL, 1)


class SchemaTests(unittest.TestCase):
    def test_checked_in_catalog_is_complete_and_uses_public_entry_fields(self):
        path = SCRIPT.parents[1] / "data" / "mechrevo-catalog.json"
        result = catalog.read_catalog(path)
        self.assertEqual(len(result["entries"]), result["source"]["total"])
        self.assertTrue(any(entry["entry_kind"] == "laptop" for entry in result["entries"]))
        self.assertTrue(all(set(entry) == catalog.ENTRY_KEYS for entry in result["entries"]))

    def test_nullable_uncategorized_entries_are_preserved(self):
        value = catalog.normalize_entry(raw_entry(product_category_name=None,
                                                   product_serial_name=None,
                                                   product_serial_id=None))
        self.assertEqual(value["entry_kind"], "unknown")
        self.assertIsNone(value["category"])
        self.assertIsNone(value["series_id"])

    def test_official_categories_are_not_all_laptops(self):
        cases = [("轻薄笔记本", "无界", "laptop"), ("零售台式机", "无界", "desktop"),
                 ("应用软件", "控制台", "software"), ("外设", "鼠标", "peripheral"),
                 ("恒悦商用产品", "商用笔记本", "laptop"),
                 ("恒悦商用产品", "商用台式机", "desktop"),
                 (None, "深海泰坦", "unknown"), ("new category", "new series", "unknown")]
        for category, series, expected in cases:
            with self.subTest(category=category, series=series):
                self.assertEqual(catalog.entry_kind(category, series), expected)

    def test_source_fields_are_bounded_and_status_is_not_boolean(self):
        for change in [{"id": ""}, {"name": "\n"}, {"slug": "a" * 513},
                       {"status": True}, {"status": 2}, {"product_category_name": 7}]:
            with self.subTest(change=change), self.assertRaises(catalog.CatalogError):
                catalog.normalize_entry(raw_entry(**change))

    def test_unknown_fields_and_forged_classification_are_rejected(self):
        for field, value in [("entry_kind", "supported"), ("url", "https://untrusted.invalid"),
                             ("serial_number", "must-not-exist")]:
            result = snapshot()
            result["entries"][0][field] = value
            with self.subTest(field=field), self.assertRaises(catalog.CatalogError):
                catalog.validate_catalog(result)

    def test_unknown_metadata_fields_are_rejected_at_each_level(self):
        for select in [lambda d: d, lambda d: d["source"],
                       lambda d: d["source"]["page_receipts"][0]]:
            result = snapshot()
            select(result)["private_data"] = "not part of schema v1"
            with self.assertRaises(catalog.CatalogError):
                catalog.validate_catalog(result)

    def test_missing_or_reordered_receipts_and_bad_timestamp_rejected(self):
        for change in [lambda d: d["source"]["page_receipts"].clear(),
                       lambda d: d["source"]["page_receipts"][0].update(page=2),
                       lambda d: d["source"]["page_receipts"][0].update(sha256="invalid"),
                       lambda d: d["source"].update(total=2),
                       lambda d: d.update(fetched_at="2026-10-18"),
                       lambda d: d.update(schema_version=2),
                       lambda d: d.update(schema_version=True)]:
            result = snapshot()
            change(result)
            with self.assertRaises(catalog.CatalogError):
                catalog.validate_catalog(result)


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mechrevo-catalog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "catalog.json"
        self.old = snapshot()
        catalog.atomic_write(self.old, self.path)
        self.old_bytes = self.path.read_bytes()

    def run_main(self, argv, **mock_kwargs):
        with patch.object(catalog, "fetch_catalog", **mock_kwargs), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return catalog.main(argv)

    def test_new_nested_output_and_existing_snapshot_round_trip(self):
        self.assertEqual(catalog.read_catalog(self.path), self.old)
        other = self.root / "nested" / "new.json"
        catalog.atomic_write(self.old, other)
        self.assertEqual(catalog.read_catalog(other), self.old)
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)

    def test_network_failure_never_changes_existing_file(self):
        result = self.run_main(["--output", str(self.path)], side_effect=catalog.CatalogError("offline"))
        self.assertEqual(result, 2)
        self.assertEqual(self.path.read_bytes(), self.old_bytes)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_invalid_new_snapshot_does_not_replace_existing(self):
        invalid = copy.deepcopy(self.old)
        invalid["entries"].append(invalid["entries"][0])
        with self.assertRaises(catalog.CatalogError):
            catalog.atomic_write(invalid, self.path)
        self.assertEqual(self.path.read_bytes(), self.old_bytes)

    def test_replace_failure_preserves_existing_and_removes_own_temporary(self):
        with patch.object(catalog.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                catalog.atomic_write(self.old, self.path)
        self.assertEqual(self.path.read_bytes(), self.old_bytes)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_concurrent_refresh_does_not_overwrite_a_newer_snapshot(self):
        updated = copy.deepcopy(self.old)
        updated["fetched_at"] = "2026-10-19T00:00:00Z"

        def concurrent_refresh(**_kwargs):
            catalog.atomic_write(updated, self.path)
            return self.old

        result = self.run_main(["--output", str(self.path)], side_effect=concurrent_refresh)
        self.assertEqual(result, 2)
        self.assertEqual(catalog.read_catalog(self.path), updated)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_concurrent_creation_does_not_overwrite_the_new_file(self):
        new_path = self.root / "new.json"

        def concurrent_creation(**_kwargs):
            catalog.atomic_write(self.old, new_path)
            return self.old

        result = self.run_main(["--output", str(new_path)], side_effect=concurrent_creation)
        self.assertEqual(result, 2)
        self.assertEqual(catalog.read_catalog(new_path), self.old)

    def test_directory_lock_failure_preserves_existing(self):
        with patch.object(catalog.fcntl, "flock", side_effect=OSError("lock failed")):
            with self.assertRaises(OSError):
                catalog.atomic_write(self.old, self.path)
        self.assertEqual(self.path.read_bytes(), self.old_bytes)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_existing_unrelated_file_and_symlink_refused(self):
        other = self.root / "other.json"
        other.write_text('{"unrelated":true}')
        link = self.root / "link.json"
        link.symlink_to(self.path)
        for output in [other, link]:
            with self.subTest(output=output), self.assertRaises(catalog.CatalogError):
                catalog.atomic_write(self.old, output)
        self.assertEqual(other.read_text(), '{"unrelated":true}')
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.path.read_bytes(), self.old_bytes)

    def test_check_ignores_retrieval_time_but_detects_changed_entries(self):
        updated = copy.deepcopy(self.old)
        updated["fetched_at"] = "2026-10-19T00:00:00Z"
        self.assertEqual(self.run_main(["--output", str(self.path), "--check"], return_value=updated), 0)
        updated["entries"][0]["name"] = "new official name"
        self.assertEqual(self.run_main(["--output", str(self.path), "--check"], return_value=updated), 1)
        self.assertEqual(self.path.read_bytes(), self.old_bytes)

    def test_dry_run_and_missing_check_output_never_write(self):
        new_path = self.root / "new.json"
        self.assertEqual(self.run_main(["--output", str(new_path), "--dry-run"], return_value=self.old), 0)
        self.assertFalse(new_path.exists())
        self.assertEqual(self.run_main(["--output", str(new_path), "--check"], return_value=self.old), 2)
        self.assertFalse(new_path.exists())


if __name__ == "__main__":
    unittest.main()
