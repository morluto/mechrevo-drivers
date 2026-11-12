"""Offline verification runner contracts; no hardware or service access."""
from dataclasses import FrozenInstanceError
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mechrevo_verify", ROOT / "scripts/verify.py")
verify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify
SPEC.loader.exec_module(verify)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MECHREVO_TEST_TMPDIR", ROOT / ".local-tests"))
        self.directory = Path(tempfile.mkdtemp(prefix="verify-contract-", dir=base))
        self.root = self.directory / "repo"
        (self.root / "tests").mkdir(parents=True)
        (self.root / ".local-tests").mkdir()
        self.env = patch.dict(os.environ, {"MECHREVO_TEST_TMPDIR": str(self.root / ".local-tests")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.uid = patch.object(verify.os, "geteuid", return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)

    def source(self, body):
        # Unique module name avoids unittest's process-wide import cache across roots.
        name = "test_probe_" + self.directory.name.replace("-", "_") + ".py"
        (self.root / "tests" / name).write_text(body)

    def audio_source(self, body):
        name = "test_analyze_fan_audio"
        (self.root / "tests" / (name + ".py")).write_text(body)
        # Discovery caches module names process-wide, including the real audio suite.
        previous = sys.modules.pop(name, None)
        def restore():
            sys.modules.pop(name, None)
            if previous is not None:
                sys.modules[name] = previous
        self.addCleanup(restore)

    def run_main(self, args=None):
        out, err = io.StringIO(), io.StringIO()
        code = verify.main(args or [], root=self.root, stdout=out, stderr=err)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_success(self):
        self.source("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): print('diagnostic'); self.assertTrue(True)\n")
        code, result, err = self.run_main()
        self.assertEqual((code, result["outcome"], result["ran"]), (0, "passed", 1))
        self.assertIn("diagnostic", err)
        self.assertTrue(Path(result["temporary_directory"]).is_relative_to(self.root / ".local-tests"))

    def test_result_categories(self):
        for kind, method, outcome, code in (
            ("failure", "self.fail('actual failure')", "failed", 1),
            ("error", "raise RuntimeError('actual error')", "failed", 1),
            ("skip", "self.skipTest('missing tool')", "incomplete", 2),
        ):
            with self.subTest(kind=kind):
                class T(unittest.TestCase):
                    pass
                exec("def test_case(self): " + method, {}, namespace := {})
                T.test_case = namespace["test_case"]
                result = verify.evaluate(unittest.defaultTestLoader.loadTestsFromTestCase(T),
                                         unittest.TestLoader(), verify.Report("all"), io.StringIO())
                self.assertEqual((result.outcome.value, result.outcome.exit_code), (outcome, code))
                self.assertEqual(result.details[0][0], kind)

    def test_expected_and_unexpected_success(self):
        class Expected(unittest.TestCase):
            @unittest.expectedFailure
            def test_expected(self): self.fail("known")
        class Unexpected(unittest.TestCase):
            @unittest.expectedFailure
            def test_unexpected(self): pass
        for cls, outcome in ((Expected, "incomplete"), (Unexpected, "failed")):
            result = verify.evaluate(unittest.defaultTestLoader.loadTestsFromTestCase(cls),
                                     unittest.TestLoader(), verify.Report("all"), io.StringIO())
            self.assertEqual(result.outcome.value, outcome)

    def test_empty(self):
        code, result, _ = self.run_main()
        self.assertEqual((code, result["outcome"], result["ran"]), (2, "incomplete", 0))

    def test_load_error(self):
        self.source("raise ImportError('missing dependency')\n")
        code, result, _ = self.run_main()
        self.assertEqual((code, result["outcome"]), (1, "failed"))
        self.assertTrue(result["load_errors"])
        self.assertEqual(result["errors"], 1)

    def test_unknown_domain(self):
        code, result, _ = self.run_main(["--domain", "unknown"])
        self.assertEqual((code, result["outcome"]), (1, "failed"))
        self.assertIn("invalid choice", result["fatal_error"])

    def test_output_is_exclusive(self):
        self.source("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n")
        path = self.directory / "result.json"
        code, result, _ = self.run_main(["--output", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(path.read_text()), result)
        original = path.read_bytes()
        code, result, _ = self.run_main(["--output", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("FileExistsError", result["fatal_error"])
        self.assertEqual(path.read_bytes(), original)

    def test_root_refusal_before_files(self):
        path = self.directory / "forbidden.json"
        with patch.object(verify.os, "geteuid", return_value=0):
            code, result, _ = self.run_main(["--output", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("Refusing root", result["fatal_error"])
        self.assertFalse(path.exists())
        self.assertEqual(list((self.root / ".local-tests").iterdir()), [])

    def test_external_temp_rejected(self):
        with patch.dict(os.environ, {"MECHREVO_TEST_TMPDIR": str(self.directory)}):
            code, result, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("inside .local-tests", result["fatal_error"])

    def test_environment_restored_and_external_tools_preserved(self):
        original_temp = tempfile.tempdir
        original_path = sys.path[:]
        with patch.dict(os.environ, {"TCC_NODE": "/custom/node", "TCC_TYPESCRIPT_MODULE": "/custom/typescript"}):
            with verify.test_environment(self.directory):
                self.assertEqual(os.environ["TCC_NODE"], "/custom/node")
                self.assertEqual(os.environ["TCC_TYPESCRIPT_MODULE"], "/custom/typescript")
                self.assertEqual(tempfile.gettempdir(), str(self.directory))
                self.assertEqual(os.environ["UNIWILL_TEST_TMPDIR"], str(self.directory))
            self.assertEqual(os.environ["MECHREVO_TEST_TMPDIR"], str(self.root / ".local-tests"))
        self.assertEqual(tempfile.tempdir, original_temp)
        self.assertEqual(sys.path, original_path)

    def test_fan_audio_domain_selects_only_audio_module_and_imports_numpy(self):
        self.audio_source("import unittest\nclass T(unittest.TestCase):\n def test_audio(self): pass\n")
        self.source("raise AssertionError('unrelated domain must not load')\n")
        with patch.object(verify.importlib, "import_module", return_value=object()) as dependency:
            code, result, _ = self.run_main(["--domain", "fan-audio"])
        dependency.assert_called_once_with("numpy")
        self.assertEqual((code, result["outcome"], result["ran"]), (0, "passed", 1))
        self.assertEqual(result["modules"], ["test_analyze_fan_audio.py"])
        self.assertEqual(result["prerequisites"], [])

    def test_missing_numpy_is_incomplete_before_loading_audio_module(self):
        self.audio_source("raise AssertionError('missing dependency must prevent import')\n")
        with patch.object(verify.importlib, "import_module", side_effect=ModuleNotFoundError("No module named 'numpy'")):
            code, result, _ = self.run_main(["--domain", "fan-audio"])
        self.assertEqual((code, result["outcome"], result["discovered"], result["ran"]), (2, "incomplete", 0, 0))
        self.assertEqual(result["modules"], ["test_analyze_fan_audio.py"])
        self.assertEqual(result["prerequisites"][0]["dependency"], "numpy")
        self.assertIn("ModuleNotFoundError", result["prerequisites"][0]["reason"])
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["load_errors"], [])

    def test_all_keeps_audio_selected_when_its_dependency_is_missing(self):
        self.audio_source("raise AssertionError('missing dependency must prevent import')\n")
        self.source("import unittest\nclass T(unittest.TestCase):\n def test_regular(self): pass\n")
        with patch.object(verify.importlib, "import_module", side_effect=ImportError("NumPy unavailable")):
            code, result, _ = self.run_main(["--domain", "all"])
        self.assertEqual((code, result["outcome"], result["ran"]), (2, "incomplete", 1))
        self.assertIn("test_analyze_fan_audio.py", result["modules"])
        self.assertEqual(len(result["modules"]), 2)
        self.assertEqual(result["prerequisites"][0]["dependency"], "numpy")
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["errors"], 0)

    def test_driver_domain_does_not_probe_audio_dependencies(self):
        self.audio_source("raise AssertionError('audio is outside driver domain')\n")
        name = "test_uniwill_verifier_" + self.directory.name.replace("-", "_") + ".py"
        (self.root / "tests" / name).write_text("import unittest\nclass T(unittest.TestCase):\n def test_driver(self): pass\n")
        with patch.object(verify.importlib, "import_module", side_effect=AssertionError("Must not probe NumPy")) as dependency:
            code, result, _ = self.run_main(["--domain", "driver"])
        dependency.assert_not_called()
        self.assertEqual((code, result["outcome"], result["ran"]), (0, "passed", 1))
        self.assertEqual(result["modules"], [name])
        self.assertEqual(result["prerequisites"], [])

    def test_derived_immutable_outcome(self):
        result = verify.Report("all", discovered=1, ran=1, skipped=1)
        self.assertEqual(result.outcome, verify.Outcome.INCOMPLETE)
        with self.assertRaises(FrozenInstanceError): result.ran = 0
        for count in (-1, True, "1"):
            with self.assertRaises(ValueError): verify.Report("all", ran=count)
        self.assertEqual(verify.Report("all", discovered=2, ran=1).outcome, verify.Outcome.INCOMPLETE)

    def test_cli_raw_and_child_stdout_remain_diagnostics(self):
        self.source("import os,subprocess,sys,unittest\nclass T(unittest.TestCase):\n def test_raw(self):\n  os.write(1,b'raw diagnostic\\n')\n  subprocess.run([sys.executable,'-c',\"print('child diagnostic')\"],check=True)\n")
        code = ("import importlib.util,sys; from pathlib import Path; "
                "s=importlib.util.spec_from_file_location('v',sys.argv[1]); "
                "v=importlib.util.module_from_spec(s); sys.modules['v']=v; s.loader.exec_module(v); "
                "sys.argv=[sys.argv[0]]; raise SystemExit(v.cli(root=Path(" + repr(str(self.root)) + ")))")
        child = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT / "scripts/verify.py")],
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout)["outcome"], "passed")
        self.assertIn("raw diagnostic", child.stderr)
        self.assertIn("child diagnostic", child.stderr)


if __name__ == "__main__":
    unittest.main()
