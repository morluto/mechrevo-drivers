"""Compile the real load-order retry helpers with userspace mocks."""
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"(?m)^static[^;{]*\b" + re.escape(name) + r"\([^;{]*\)\s*\{",
                      source)
    if not match:
        raise AssertionError("Missing driver function: " + name)
    depth, end = 1, match.end()
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


class TuxedoIoIdentify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = Path(os.environ.get("UNIWILL_TEST_TMPDIR", ROOT / ".local-tests"))
        parent.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="io-identify-", dir=parent)
        cls.addClassCleanup(cls.temp.cleanup)
        io = Path(os.environ.get("UNIWILL_IO_SOURCE_ROOT", ROOT) /
                  "src/tuxedo_io/tuxedo_io.c").read_text()
        pieces = [function(io, name) for name in
                  ("uw_identify_locked", "uniwill_identify",
                   "uw_ensure_identified")]
        fixture = (ROOT / "tests/fixtures/tuxedo_io_identify.c").read_text()
        source = Path(cls.temp.name) / "runtime.c"
        source.write_text(fixture.replace("/* @DRIVER@ */", "\n\n".join(pieces)))
        cls.binary = Path(cls.temp.name) / "runtime"
        result = subprocess.run(
            ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
             str(source), "-o", str(cls.binary)],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def check_case(self, case):
        def no_core():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        result = subprocess.run([str(self.binary), case], capture_output=True,
                                text=True, timeout=10, preexec_fn=no_core)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_load_order_failure_is_retried_and_success_is_cached(self):
        self.check_case("load_order")

    def test_feature_failure_keeps_retrying_without_caching(self):
        self.check_case("feature_failure")

    def test_incomplete_feature_probe_is_not_cached_as_ready(self):
        self.check_case("feature_not_ready")

    def test_concurrent_first_users_identify_exactly_once(self):
        self.check_case("concurrency")


if __name__ == "__main__":
    unittest.main()
