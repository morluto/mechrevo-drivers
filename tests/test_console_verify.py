"""Verifier regressions use fake Cargo commands, never a compiler or hardware."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mechrevo_console_verify", ROOT / "scripts/verify_console.py")
verify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify
SPEC.loader.exec_module(verify)


class ConsoleVerificationTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MECHREVO_TEST_TMPDIR", ROOT / ".local-tests"))
        self.directory = Path(tempfile.mkdtemp(prefix="console-contract-", dir=base))
        self.root = self.directory / "repo"
        (self.root / "console/crates/probe/src").mkdir(parents=True)
        (self.root / ".local-tests").mkdir()
        (self.root / "data").mkdir()
        (self.root / "console/Cargo.toml").write_text('[workspace]\nmembers = ["crates/probe"]\n')
        (self.root / "console/Cargo.lock").write_text("version = 4\n")
        (self.root / "console/crates/probe/Cargo.toml").write_text('[package]\nname = "probe"\nversion = "0.1.0"\n')
        self.source = self.root / "console/crates/probe/src/lib.rs"
        self.source.write_text("pub fn probe() {}\n")
        (self.root / "data/mechrevo-catalog.json").write_text('{"models": []}\n')
        (self.root / "data/mechrevo-platform-evidence.json").write_text('{"platforms": []}\n')
        self.fonts = [self.root / "console" / name for name in verify.GUI_EMBEDDED_FONTS]
        self.fonts[0].parent.mkdir(parents=True)
        for font in self.fonts:
            font.write_bytes(b"fixture font: " + font.name.encode())
        self.font_license = self.fonts[0].parent / "OFL.txt"
        self.font_license.write_text("fixture font license\n")
        self.resources = self.root / "console/resources"
        self.resources.mkdir()
        self.oem_policy = self.resources / "org.mechrevo.console.oem.policy"
        self.oem_policy.write_text('<policyconfig><action id="org.mechrevo.console.oem"/></policyconfig>\n')
        self.calls = []
        self.windows_installed = True
        self.failure = None
        self.timeout = None
        self.mutate = None
        self.test_output = ("running 3 tests\n"
                            "test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; "
                            "0 filtered out; finished in 0.01s\n")
        self.env = patch.dict(os.environ, {"MECHREVO_TEST_TMPDIR": str(self.root / ".local-tests")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.uid = patch.object(verify.os, "geteuid", return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)

    @staticmethod
    def which(name):
        return "/fake/" + name

    def runner(self, argv, *, cwd, env, timeout, stream):
        self.calls.append((argv, cwd, env.copy(), timeout))
        if argv[1:] == ["target", "list", "--installed"]:
            stream.write("x86_64-unknown-linux-gnu\n")
            if self.windows_installed:
                stream.write(verify.WINDOWS_TARGET + "\n")
        elif argv[1] == "test":
            stream.write(self.test_output)
        else:
            stream.write("fake command output\n")
        if argv[1] == self.timeout:
            raise subprocess.TimeoutExpired(argv, timeout)
        if self.mutate and argv[1] == "test":
            self.mutate()
        return 7 if argv[1] == self.failure else 0

    def run_verifier(self, **kwargs):
        return verify.verify(self.root, runner=self.runner, which=self.which, **kwargs).as_dict()

    def run_main(self, args):
        out = io.StringIO()
        code = verify.main(args, root=self.root, runner=self.runner, which=self.which, stdout=out)
        return code, json.loads(out.getvalue())

    def test_success_has_all_checks_logs_hashes_and_locked_builds(self):
        result = self.run_verifier(timeout=42)
        self.assertEqual((result["exit_code"], result["outcome"], result["checks_executed"]), (0, "passed", 4))
        self.assertTrue(result["source_unchanged"])
        self.assertEqual(result["source_before"], result["source_after"])
        self.assertEqual(len(result["source_before"]["files"]), 9)
        for asset in (*self.fonts, self.font_license, self.oem_policy):
            self.assertIn(str(asset.relative_to(self.root)), result["source_before"]["files"])
        self.assertEqual({row["name"] for row in result["commands"]}, {"fmt", "test", "clippy", "windows"})
        for row in result["commands"] + result["prerequisites"]:
            self.assertEqual((row["status"], row["exit_code"]), ("passed", 0))
            log = Path(row["log"])
            self.assertTrue(log.is_relative_to(self.root / ".local-tests"))
            self.assertTrue(log.read_text())
        for row in result["commands"][1:]:
            self.assertIn("--locked", row["argv"])
        self.assertTrue(all(call[1] == self.root / "console" for call in self.calls))
        self.assertTrue(all(call[3] == 42 for call in self.calls[2:]))
        self.assertIn("--all-features", result["commands"][3]["argv"])
        self.assertEqual(result["commands"][2]["argv"][-3:], ["--", "-D", "warnings"])
        self.assertEqual(result["commands"][1]["test_results"]["totals"],
                         {"passed": 3, "failed": 0, "ignored": 0, "measured": 0, "filtered_out": 0})
        self.assertTrue(result["commands"][1]["test_results"]["totals_complete"])

    def test_failed_check_is_failed_even_when_windows_prerequisite_missing(self):
        self.failure = "test"
        self.windows_installed = False
        result = self.run_verifier()
        self.assertEqual((result["exit_code"], result["outcome"]), (1, "failed"))
        self.assertEqual(result["commands"][1]["exit_code"], 7)
        self.assertEqual(result["commands"][3]["status"], "incomplete")
        self.assertEqual(len(result["commands"]), 4)

    def test_missing_cargo_never_passes_or_executes_checks(self):
        result = verify.verify(self.root, runner=self.runner, which=lambda name: None).as_dict()
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 0))
        self.assertEqual(self.calls, [])
        self.assertEqual(len(result["commands"]), 4)
        self.assertTrue(all("NOT RUN" in Path(row["log"]).read_text() for row in result["commands"]))

    def test_missing_windows_target_keeps_native_checks_but_is_incomplete(self):
        self.windows_installed = False
        result = self.run_verifier()
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 3))
        self.assertEqual(result["commands"][-1]["executed"], False)
        self.assertTrue(all("install" not in row[0] and "add" not in row[0] for row in self.calls))

    def test_missing_rustup_cannot_claim_windows_compile_verification(self):
        result = verify.verify(self.root, runner=self.runner,
                               which=lambda name: "/fake/cargo" if name == "cargo" else None).as_dict()
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 3))

    def test_timeout_is_logged_and_incomplete_without_abandoning_other_checks(self):
        self.timeout = "test"
        result = self.run_verifier(timeout=0.25)
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 4))
        row = result["commands"][1]
        self.assertTrue(row["timed_out"])
        self.assertIsNone(row["exit_code"])
        self.assertIn("timed out", Path(row["log"]).read_text())
        self.assertEqual(result["commands"][-1]["status"], "passed")

    def test_multiple_test_binaries_include_zero_test_summaries_and_real_passes(self):
        self.test_output += ("test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; "
                             "0 filtered out; finished in 0.00s\n"
                             "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; "
                             "0 filtered out; finished in 0.01s\n")
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 0)
        summaries = result["commands"][1]["test_results"]
        self.assertEqual((summaries["summary_count"], summaries["totals"]["passed"]), (3, 5))

    def test_successful_runner_without_libtest_output_is_incomplete(self):
        self.test_output = ""
        result = self.run_verifier()
        row = result["commands"][1]
        self.assertEqual((result["exit_code"], row["exit_code"], row["status"]), (2, 0, "incomplete"))
        self.assertEqual(row["test_results"]["summary_count"], 0)
        self.assertIn("No stable libtest summaries", row["reason"])

    def test_zero_actual_tests_are_incomplete(self):
        self.test_output = ("test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; "
                            "0 filtered out; finished in 0.00s\n")
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("zero passed", result["commands"][1]["reason"])

    def test_ignored_filtered_and_malformed_test_summaries_are_incomplete(self):
        for output in ("test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s\n",
                       "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.00s\n",
                       "test result: ok. one passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n"):
            with self.subTest(output=output):
                self.test_output = output
                result = self.run_verifier()
                self.assertEqual((result["exit_code"], result["commands"][1]["status"]), (2, "incomplete"))

    def test_failed_summary_overrides_zero_command_exit_and_partial_scan(self):
        for status in ("FAILED", "ok"):
            with self.subTest(status=status):
                self.test_output = ("test result: " + status + ". 1 passed; 1 failed; 0 ignored; 0 measured; "
                                    "0 filtered out; finished in 0.00s\n"
                                    "test result: unrecognized\n")
                result = self.run_verifier()
                row = result["commands"][1]
                self.assertEqual((result["exit_code"], row["status"], row["exit_code"]), (1, "failed", 0))
                self.assertEqual(row["test_results"]["totals"]["failed"], 1)

    def test_test_log_parser_enforces_file_and_line_read_budgets(self):
        log = self.directory / "large-test.log"
        log.write_bytes(b"x" * 200)
        result = verify.parse_test_log(log, max_bytes=100, max_line_bytes=50)
        self.assertFalse(result["totals_complete"])
        self.assertEqual(result["bytes_scanned"], 0)
        result = verify.parse_test_log(log, max_bytes=300, max_line_bytes=50)
        self.assertFalse(result["totals_complete"])
        self.assertEqual(result["bytes_scanned"], 51)

    def test_source_hashing_accepts_read_induced_access_time_changes(self):
        baseline = verify.source_snapshot(self.root)
        old = self.font_license.stat().st_mtime_ns - 2 * 24 * 60 * 60 * 1_000_000_000
        os.utime(self.font_license, ns=(old, old))
        self.assertEqual(verify.source_snapshot(self.root), baseline)

    def test_test_log_parser_accepts_read_induced_access_time_changes(self):
        log = self.directory / "aged-test.log"
        log.write_text(self.test_output)
        old = log.stat().st_mtime_ns - 2 * 24 * 60 * 60 * 1_000_000_000
        os.utime(log, ns=(old, old))
        result = verify.parse_test_log(log)
        self.assertTrue(result["totals_complete"], result)
        self.assertEqual(result["totals"]["passed"], 3)

    def test_stable_metadata_preserves_identity_permissions_and_nanosecond_changes(self):
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
                  "st_size", "st_mtime_ns", "st_ctime_ns")
        actual = self.source.stat()
        values = {name: getattr(actual, name) for name in fields}
        original = verify.stable_file_metadata(actual)
        for name in fields:
            with self.subTest(field=name):
                changed = SimpleNamespace(**(values | {name: values[name] + 1}))
                self.assertNotEqual(verify.stable_file_metadata(changed), original)
        for atime in (0, actual.st_atime_ns + 1_000_000_000):
            changed = SimpleNamespace(**(values | {"st_atime_ns": atime}))
            self.assertEqual(verify.stable_file_metadata(changed), original)

    def test_source_edits_and_new_source_files_make_run_incomplete(self):
        changes = (lambda: self.source.write_text("pub fn changed() {}\n"),
                   lambda: (self.source.parent / "new.rs").write_text("pub fn new() {}\n"),
                   lambda: (self.root / "data/mechrevo-catalog.json").write_text('{"models": [1]}\n'),
                   lambda: (self.root / "data/mechrevo-platform-evidence.json").write_text('{"platforms": [1]}\n'))
        for mutate in changes:
            with self.subTest(mutate=mutate):
                self.mutate = mutate
                result = self.run_verifier()
                self.assertEqual(result["exit_code"], 2)
                self.assertFalse(result["source_unchanged"])
                self.assertNotEqual(result["source_before"]["sha256"], result["source_after"]["sha256"])

    def test_embedded_font_or_other_asset_edits_make_run_incomplete(self):
        for asset in (self.fonts[0], self.font_license):
            with self.subTest(asset=asset.name):
                self.mutate = lambda: asset.write_bytes(asset.read_bytes() + b" changed")
                result = self.run_verifier()
                self.assertEqual(result["exit_code"], 2)
                self.assertFalse(result["source_unchanged"])
                self.assertNotEqual(result["source_before"]["sha256"], result["source_after"]["sha256"])
                self.assertTrue(all(row["status"] == "passed" for row in result["commands"]))

    def test_each_missing_embedded_font_is_named_and_blocks_checks(self):
        for font in self.fonts:
            with self.subTest(font=font.name):
                original = font.read_bytes()
                font.unlink()
                try:
                    result = self.run_verifier()
                    self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 0))
                    relative = str(font.relative_to(self.root))
                    self.assertIn(relative, result["source_before"]["missing"])
                    self.assertIn(relative, result["incomplete_reasons"][0])
                finally:
                    font.write_bytes(original)

    def test_packaged_policy_and_future_nested_resources_are_hashed(self):
        nested = self.resources / "future/backend"
        nested.mkdir(parents=True)
        resource = nested / "protocol.conf"
        resource.write_text("fixture protocol resource\n")
        result = self.run_verifier()
        self.assertEqual((result["exit_code"], result["checks_executed"]), (0, 4))
        for path in (self.oem_policy, resource):
            self.assertIn(str(path.relative_to(self.root)), result["source_before"]["files"])
        self.assertEqual(result["source_before"], result["source_after"])

    def test_resource_edits_additions_and_removals_make_run_incomplete(self):
        extra = self.resources / "future-resource.txt"
        changes = (lambda: self.oem_policy.write_text(self.oem_policy.read_text() + "<!-- changed -->\n"),
                   lambda: extra.write_text("new packaged resource\n"),
                   lambda: extra.unlink())
        for mutate in changes:
            with self.subTest(mutate=mutate):
                self.mutate = mutate
                result = self.run_verifier()
                self.assertEqual(result["exit_code"], 2)
                self.assertFalse(result["source_unchanged"])
                self.assertNotEqual(result["source_before"]["sha256"], result["source_after"]["sha256"])
                self.assertTrue(all(row["status"] == "passed" for row in result["commands"]))

    def test_missing_required_oem_policy_is_named_and_blocks_checks(self):
        self.oem_policy.unlink()
        result = self.run_verifier()
        relative = str(self.oem_policy.relative_to(self.root))
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 0))
        self.assertIn(relative, result["source_before"]["missing"])
        self.assertIn(relative, result["incomplete_reasons"][0])

    def test_symlink_policy_is_rejected_without_running_checks(self):
        original = self.directory / "actual.policy"
        original.write_bytes(self.oem_policy.read_bytes())
        self.oem_policy.unlink()
        self.oem_policy.symlink_to(original)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source input", result["fatal_error"])
        self.assertEqual(self.calls, [])

    def test_symlink_nested_resource_directory_is_rejected(self):
        (self.resources / "linked-resources").symlink_to(self.directory, target_is_directory=True)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source input", result["fatal_error"])
        self.assertEqual(self.calls, [])

    def test_symlink_resources_root_is_rejected(self):
        original = self.directory / "actual-resources"
        self.resources.rename(original)
        self.resources.symlink_to(original, target_is_directory=True)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source directory", result["fatal_error"])
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO source contract")
    def test_nonregular_resource_is_rejected_before_opening(self):
        os.mkfifo(self.resources / "blocked-input")
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("not a regular file", result["fatal_error"])
        self.assertEqual(self.calls, [])

    def test_symlink_gui_asset_and_asset_directory_are_rejected(self):
        original = self.directory / "actual-font.ttf"
        original.write_bytes(self.fonts[0].read_bytes())
        self.fonts[0].unlink()
        self.fonts[0].symlink_to(original)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source input", result["fatal_error"])
        self.assertEqual(self.calls, [])
        self.fonts[0].unlink()
        self.fonts[0].write_bytes(original.read_bytes())
        extra = self.fonts[0].parent.parent / "linked-assets"
        extra.symlink_to(self.directory, target_is_directory=True)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source input", result["fatal_error"])
        self.assertEqual(self.calls, [])

    def test_missing_lock_and_zero_commands_are_incomplete(self):
        result = self.run_verifier(checks=())
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 0))
        (self.root / "console/Cargo.lock").unlink()
        result = self.run_verifier()
        self.assertEqual((result["exit_code"], result["checks_executed"]), (2, 0))
        self.assertIn("console/Cargo.lock", result["source_before"]["missing"])

    def test_existing_output_is_preserved_and_no_commands_run(self):
        output = self.directory / "receipt.json"
        code, result = self.run_main(["--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text()), result)
        original = output.read_bytes()
        self.calls.clear()
        code, result = self.run_main(["--output", str(output)])
        self.assertEqual(code, 1)
        self.assertIn("FileExistsError", result["fatal_error"])
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(self.calls, [])

    def test_root_refusal_has_no_files_or_commands(self):
        output = self.directory / "root-receipt.json"
        with patch.object(verify.os, "geteuid", return_value=0):
            code, result = self.run_main(["--output", str(output)])
        self.assertEqual(code, 1)
        self.assertIn("Refusing root", result["fatal_error"])
        self.assertFalse(output.exists())
        self.assertEqual(list((self.root / ".local-tests").iterdir()), [])
        self.assertEqual(self.calls, [])

    def test_external_and_symlink_artifact_directories_are_rejected(self):
        for base in (self.directory, self.root / ".local-tests/link"):
            with self.subTest(base=base):
                if base.name == "link":
                    base.symlink_to(self.directory, target_is_directory=True)
                with patch.dict(os.environ, {"MECHREVO_TEST_TMPDIR": str(base)}):
                    result = self.run_verifier()
                self.assertEqual(result["exit_code"], 1)
                self.assertIsNone(result["artifact_directory"])
                self.assertEqual(self.calls, [])

    def test_existing_cargo_target_directory_is_honored(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "/existing/cargo-target"}):
            result = self.run_verifier()
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["cargo_target_directory"], "/existing/cargo-target")
        self.assertTrue(all(call[2]["CARGO_TARGET_DIR"] == "/existing/cargo-target" for call in self.calls))
        result = self.run_verifier(env={})
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["cargo_target_directory"], str(self.root / ".local-tests/console-target"))
        self.assertEqual(Path(result["artifact_directory"]).parent, self.root / ".local-tests")
        preferred = self.root / ".local-tests/console"
        preferred.mkdir()
        result = self.run_verifier(env={})
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(Path(result["artifact_directory"]).parent, preferred)

    def test_nonfinite_and_nonpositive_timeout_rejected_before_artifacts(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                result = self.run_verifier(timeout=timeout)
                self.assertEqual(result["exit_code"], 1)
                self.assertIsNone(result["artifact_directory"])
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(os.name == "posix", "POSIX process-group cleanup contract")
    def test_real_runner_timeout_kills_process_group_and_reaps_child(self):
        child = MagicMock()
        child.pid = 12345
        child.wait.side_effect = [subprocess.TimeoutExpired(["cargo", "test"], 0.1), -9]
        manager = MagicMock()
        manager.__enter__.return_value = child
        with patch.object(verify.subprocess, "Popen", return_value=manager) as popen, \
                patch.object(verify.os, "killpg") as killpg:
            with self.assertRaises(subprocess.TimeoutExpired):
                verify.execute(["cargo", "test"], cwd=self.root, env={}, timeout=0.1, stream=io.StringIO())
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(12345, verify.signal.SIGKILL)
        self.assertEqual(child.wait.call_count, 2)

    def test_symlink_source_is_rejected_without_running_cargo(self):
        original = self.directory / "actual.rs"
        original.write_text(self.source.read_text())
        self.source.unlink()
        self.source.symlink_to(original)
        result = self.run_verifier()
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("Symlink source input", result["fatal_error"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
