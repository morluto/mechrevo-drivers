"""Exercise real ASAR deployment using private files; never change host services."""
import importlib.util
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("tcc_customize_deploy", ROOT / "scripts/customize_tcc.py")
TCC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TCC)


class CustomizeDeploymentTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("MECHREVO_TEST_TMPDIR", ROOT / ".local-tests"))
        self.temporary = tempfile.TemporaryDirectory(prefix="tcc-deploy-", dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.backup = self.directory / "Backups/project/host/date/app.asar"
        self.target = self.directory / "app.asar"
        self.frontend = "dist/tuxedo-control-center/ng-app/browser"
        source = self.directory / "source"
        locale = source / self.frontend / "en"
        (locale / "assets/locale").mkdir(parents=True)
        (locale / "index.html").write_text('<html lang="en"><title>TuxedoControlCenter</title></html>')
        (locale / "main-fixture.js").write_text('const label = "Dashboard";')
        (locale / "styles-fixture.css").write_text("body { color: white; }")
        (locale / "assets/locale/lang.xlf").write_text("<xliff/>")
        TCC.pack_asar(source, self.target)
        self.target.chmod(0o640)
        self.original = self.target.read_bytes()
        self.settings = self.directory / "settings"
        self.settings.write_text('{"fanControlEnabled":false}\n')

    def invoke(self, *arguments):
        """Redirect the historical global path too, so old-code regression runs stay safe."""
        stdout, stderr = io.StringIO(), io.StringIO()

        def scoped_path(value):
            return self.settings if str(value) == "/etc/tcc/settings" else Path(value)

        with (mock.patch.object(TCC, "BACKUP_ASAR_PATH", self.backup),
              mock.patch.object(TCC, "Path", side_effect=scoped_path),
              mock.patch.object(TCC.os, "system") as commands,
              mock.patch.object(TCC, "update_desktop_entry", create=True) as desktop,
              mock.patch.object(sys, "argv", ["customize_tcc.py", "--asar", str(self.target), *arguments]),
              mock.patch.object(sys, "stdout", stdout),
              mock.patch.object(sys, "stderr", stderr)):
            code = TCC.main()
        return code, stdout.getvalue(), stderr.getvalue(), commands, desktop

    def test_deploy_replaces_target_and_preserves_backup_without_host_side_effects(self):
        old_inode = self.target.stat().st_ino
        result, output, errors, commands, desktop = self.invoke("--deploy")
        self.assertEqual(result, 0, errors)
        self.assertNotEqual(self.target.read_bytes(), self.original, "successful deployment must install the candidate ASAR")
        self.assertNotEqual(self.target.stat().st_ino, old_inode)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o600)
        unpacked = self.directory / "installed"
        TCC.unpack_asar(self.target, unpacked)
        self.assertIn("仪表盘", (unpacked / self.frontend / "zh/main-fixture.js").read_text())
        self.assertIn("Backup:", output)
        self.assertEqual(self.settings.read_text(), '{"fanControlEnabled":false}\n')
        commands.assert_not_called()
        desktop.assert_not_called()
        self.assertEqual(list(self.directory.glob(".app.asar.*.tmp")), [])

    def test_build_failure_leaves_target_and_backup_untouched(self):
        with mock.patch.object(TCC, "pack_asar", side_effect=OSError("build failed")):
            result, output, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("build failed", errors)
        self.assertNotIn("installed and verified", output)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_deploy_reads_electron_header_padding_without_shifting_member_bytes(self):
        import json
        import struct

        _, _, _, previous_size = struct.unpack("<IIII", self.original[:16])
        header = json.loads(self.original[16:16 + previous_size])
        header["padding_fixture"] = ""
        raw = json.dumps(header, separators=(",", ":")).encode()
        if len(raw) % 4 == 0:
            header["padding_fixture"] = "x"
            raw = json.dumps(header, separators=(",", ":")).encode()
        padding = -len(raw) % 4
        self.assertGreater(padding, 0)
        self.original = (struct.pack("<IIII", 4, len(raw) + padding + 8, len(raw) + padding + 4, len(raw))
                         + raw + b"\0" * padding + self.original[16 + previous_size:])
        self.target.write_bytes(self.original)
        result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 0, errors)
        unpacked = self.directory / "installed-native"
        TCC.unpack_asar(self.target, unpacked)
        self.assertEqual((unpacked / self.frontend / "en/main-fixture.js").read_text(), 'const label = "Dashboard";')
        self.assertIn("仪表盘", (unpacked / self.frontend / "zh/main-fixture.js").read_text())
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_truncated_candidate_never_replaces_target(self):
        real_pack = TCC.pack_asar

        def truncate(*args, **kwargs):
            real_pack(*args, **kwargs)
            candidate = args[1]
            candidate.write_bytes(candidate.read_bytes()[:-3])

        with mock.patch.object(TCC, "pack_asar", side_effect=truncate):
            result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("Truncated ASAR member", errors)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_different_existing_backup_is_never_overwritten_or_used(self):
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(b"older recovery copy")
        result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("Existing backup differs", errors)
        self.assertEqual(self.backup.read_bytes(), b"older recovery copy")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_identical_existing_backup_is_reused_without_rewriting(self):
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(self.original)
        before = self.backup.stat()
        result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 0, errors)
        self.assertEqual(self.backup.stat().st_ino, before.st_ino)
        self.assertEqual(self.backup.stat().st_mtime_ns, before.st_mtime_ns)

    def test_backup_symlink_is_rejected(self):
        self.backup.parent.mkdir(parents=True)
        elsewhere = self.directory / "protected-recovery"
        elsewhere.write_bytes(self.original)
        self.backup.symlink_to(elsewhere)
        result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("regular ASAR", errors)
        self.assertEqual(elsewhere.read_bytes(), self.original)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_backup_failure_prevents_target_replacement(self):
        with mock.patch.object(TCC, "preserve_backup", side_effect=OSError("backup full")):
            result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("backup full", errors)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_replace_failure_keeps_original_and_verified_backup(self):
        with mock.patch.object(TCC.os, "replace", side_effect=OSError("replace denied")):
            result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("replace denied", errors)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(list(self.directory.glob(".app.asar.*.tmp")), [])

    def test_failed_readback_rolls_back_original(self):
        real_replace = TCC.os.replace
        replaces = []

        def corrupt_first(source, target):
            real_replace(source, target)
            replaces.append((source, target))
            if len(replaces) == 1:
                Path(target).write_bytes(b"corrupt installed bytes")

        with mock.patch.object(TCC.os, "replace", side_effect=corrupt_first):
            result, output, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("Installed ASAR verification failed", errors)
        self.assertNotIn("installed and verified", output)
        self.assertEqual(len(replaces), 2)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_target_changed_during_build_is_not_overwritten(self):
        real_pack = TCC.pack_asar

        def change_target(*args, **kwargs):
            real_pack(*args, **kwargs)
            self.target.write_bytes(b"another deployment")

        with mock.patch.object(TCC, "pack_asar", side_effect=change_target):
            result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 1)
        self.assertIn("Target changed", errors)
        self.assertEqual(self.target.read_bytes(), b"another deployment")
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_restore_atomically_reuses_explicit_backup_and_keeps_recovery(self):
        result, _, errors, _, _ = self.invoke("--deploy")
        self.assertEqual(result, 0, errors)
        deployed_inode = self.target.stat().st_ino
        result, output, errors, commands, desktop = self.invoke("--restore", "--backup", str(self.backup))
        self.assertEqual(result, 0, errors)
        self.assertIn("Restored and verified", output)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertNotEqual(self.target.stat().st_ino, deployed_inode)
        self.assertEqual(self.backup.read_bytes(), self.original)
        commands.assert_not_called()
        desktop.assert_not_called()

    def test_restore_missing_backup_does_not_change_target(self):
        result, _, errors, _, _ = self.invoke("--restore")
        self.assertEqual(result, 1)
        self.assertIn("Error:", errors)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_restore_rejects_corrupt_and_truncated_recovery_before_replacement(self):
        self.backup.parent.mkdir(parents=True)
        for invalid in (b"not an ASAR", self.original[:-5]):
            with self.subTest(backup=invalid[:12]):
                self.backup.write_bytes(invalid)
                result, output, errors, _, _ = self.invoke("--restore")
                self.assertEqual(result, 1)
                self.assertIn("Error:", errors)
                self.assertNotIn("Restored and verified", output)
                self.assertEqual(self.target.read_bytes(), self.original)
                self.assertEqual(self.backup.read_bytes(), invalid)

    def test_restore_rejects_escaping_archive_member(self):
        import json
        import struct

        header = json.dumps({"files": {"../escape": {"size": 1, "offset": "0"}}}).encode()
        header += b" " * (-len(header) % 4)
        invalid = struct.pack("<IIII", 4, len(header) + 8, len(header) + 4, len(header)) + header + b"x"
        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(invalid)
        result, _, errors, _, _ = self.invoke("--restore")
        self.assertEqual(result, 1)
        self.assertIn("Invalid ASAR member name", errors)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_restore_rejects_missing_archive_directory(self):
        import struct

        self.backup.parent.mkdir(parents=True)
        self.backup.write_bytes(struct.pack("<IIII", 4, 12, 8, 4) + b"{}  ")
        result, _, errors, _, _ = self.invoke("--restore")
        self.assertEqual(result, 1)
        self.assertIn("Invalid ASAR root directory", errors)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_backup_cannot_be_target(self):
        result, _, errors, _, _ = self.invoke("--deploy", "--backup", str(self.target))
        self.assertEqual(result, 1)
        self.assertIn("different paths", errors)
        self.assertEqual(self.target.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
