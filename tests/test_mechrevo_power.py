"""Exercise the userspace power-cap transaction against an isolated host tree.

No service command or sysfs operation escapes the fake root.  Faults are
injected at the service/kernel I/O boundary, while controller decisions and
configuration transactions run normally.
"""

import importlib.util
import hashlib
import io
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mechrevo_power", ROOT / "scripts/mechrevo_power.py")
POWER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POWER
SPEC.loader.exec_module(POWER)


STOCK_UNIT = """[Unit]
Description=Thermal Daemon Service
ConditionVirtualization=no

[Service]
Type=dbus
SuccessExitStatus=2
BusName=org.freedesktop.thermald
ExecStart=/usr/bin/thermald --systemd --dbus-enable --adaptive
Restart=on-failure

[Install]
WantedBy=multi-user.target
Alias=dbus-org.freedesktop.thermald.service
"""


class FakeHost:
    def __init__(self, testcase, root=None):
        if root is None:
            directory = Path(os.environ.get("MECHREVO_TEST_TMPDIR", ROOT / ".local-tests"))
            directory.mkdir(parents=True, exist_ok=True)
            self.temp = tempfile.TemporaryDirectory(prefix="power-cli-", dir=directory)
            testcase.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
        else:
            self.root = Path(root)
        self.commands = []
        self.version = "2.5.13"
        self.active = True
        self.restart_failures = []
        self.apply_errors = []
        self.service_overrides = {}
        self.controller = None
        self.write("/sys/class/dmi/id/sys_vendor", "MECHREVO\n")
        self.write("/sys/class/dmi/id/product_name", "Kuangshi16Pro Series GM6PX0X\n")
        self.write("/sys/class/dmi/id/bios_version", "N.1.09MRO07\n")
        self.write("/proc/cpuinfo", "processor\t: 0\nmodel name\t: 12th Gen Intel(R) Core(TM) i9-12900HX\n")
        self.write(POWER.STOCK_UNIT, STOCK_UNIT)
        binary = self.write("/usr/bin/thermald", "isolated thermald v2.5.13 fixture\n")
        binary.chmod(0o755)
        qualified = mock.patch.object(POWER, "QUALIFIED_THERMALD_SHA256",
                                      hashlib.sha256(binary.read_bytes()).hexdigest())
        qualified.start()
        testcase.addCleanup(qualified.stop)
        self.write("/etc/thermald/thermald-features.xml", """<ThermaldFeatures>
<DbusControl>0</DbusControl><XMLThermalConfig>1</XMLThermalConfig>
<DataVaultFromFileSystem>1</DataVaultFromFileSystem>
<KobjectUeventSupport>1</KobjectUeventSupport>
</ThermaldFeatures>
""")
        self.write("/sys/bus/pci/devices/0000:00:04.0/tcc_offset_degree_celsius", "0\n")
        for zone in POWER.ZONES:
            for name, value in {
                "name": "package-0", "enabled": "1",
                "constraint_0_name": "long_term",
                "constraint_0_power_limit_uw": "140000000",
                "constraint_0_max_power_uw": "55000000",
                "constraint_0_time_window_us": "55967744",
                "constraint_1_name": "short_term",
                "constraint_1_power_limit_uw": "140000000",
                "constraint_1_time_window_us": "2440",
                "constraint_2_name": "peak_power",
                "constraint_2_power_limit_uw": "0",
            }.items():
                self.write(f"{zone}/{name}", value + "\n")
        self.write("/sys/devices/virtual/thermal/thermal_zone0/type", "x86_pkg_temp\n")
        self.write("/sys/devices/virtual/thermal/thermal_zone0/temp", "65000\n")
        sensor_class = self.path("/sys/class/thermal/thermal_zone0")
        sensor_class.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(sensor_class):
            sensor_class.symlink_to(self.path("/sys/devices/virtual/thermal/thermal_zone0"))
        self.env = POWER.Environment(root=self.root, runner=self.run,
                                     uid=0, owner_uid=os.geteuid())
        self.controller = POWER.PowerController(self.env)

    def path(self, absolute):
        return self.root / str(absolute).lstrip("/")

    def write(self, absolute, value):
        path = self.path(absolute)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def read(self, absolute):
        return self.path(absolute).read_text()

    def limit_path(self, index):
        return self.path(f"{POWER.ZONES[index]}/constraint_0_power_limit_uw")

    def limits(self):
        return [int(self.limit_path(i).read_text()) for i in range(2)]

    def protected_controls(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for zone in POWER.ZONES for path in self.path(zone).iterdir()
                if path.name != "constraint_0_power_limit_uw"}

    def run(self, argv):
        self.commands.append(list(argv))
        if argv == ["/usr/bin/thermald", "--version"]:
            return subprocess.CompletedProcess(argv, 0, self.version + "\n", "")
        if argv[:3] == ["systemctl", "show", "thermald.service"]:
            command = "/usr/bin/thermald --systemd --dbus-enable --adaptive"
            dropins = ""
            if self.path(POWER.DROPIN).exists():
                dropins = POWER.DROPIN
                for line in self.read(POWER.DROPIN).splitlines():
                    if line.startswith("ExecStart=") and line != "ExecStart=":
                        command = line.removeprefix("ExecStart=")
            properties = {"FragmentPath": POWER.STOCK_UNIT, "DropInPaths": dropins,
                          "ActiveState": "active" if self.active else "failed",
                          "ExecStart": f"{{ path=/usr/bin/thermald ; argv[]={command} ; }}"}
            properties.update(self.service_overrides)
            output = "".join(f"{key}={value}\n" for key, value in properties.items())
            return subprocess.CompletedProcess(argv, 0, output, "")
        if argv == ["systemctl", "daemon-reload"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv == ["systemctl", "restart", "thermald.service"]:
            failure = self.restart_failures.pop(0) if self.restart_failures else False
            self.active = not failure
            if failure:
                return subprocess.CompletedProcess(argv, 1, "", "injected restart failure")
            if self.path(POWER.DROPIN).exists():
                def deadlock(signum, frame):
                    raise AssertionError("ExecStartPost apply blocked by the set/restart lock")

                previous = signal.signal(signal.SIGALRM, deadlock)
                signal.setitimer(signal.ITIMER_REAL, 3)
                try:
                    self.controller.apply()
                except POWER.PowerError as error:
                    # ExecStartPost starts with '-', so thermald stays active.
                    self.apply_errors.append(str(error))
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous)
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"Unmocked service command: {argv!r}")


class PackageTemperatureDiagnostics(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost(self)
        self.env = self.host.env
        self.sensor = self.host.path("/sys/devices/virtual/thermal/thermal_zone0")
        target = mock.patch.object(self.env, "read_temperature_target", return_value={
            "platform_info_raw": 1 << 30, "temperature_target_raw": (100 << 16) | (5 << 24),
            "tjmax_celsius": 100, "tcc_offset_celsius": 5, "tcc_activation_celsius": 95})
        target.start()
        self.addCleanup(target.stop)

    def test_actual_package_sample_has_identity_and_monotonic_window(self):
        with mock.patch.object(POWER.time, "monotonic_ns", side_effect=[123, 456]):
            result = self.host.controller.status()
        temp = result["package_temperature"]
        self.assertTrue(temp["available"])
        self.assertEqual(temp["millicelsius"], 65000)
        self.assertEqual(temp["read_window_ns"], [123, 456])
        self.assertEqual(temp["clock"], "CLOCK_MONOTONIC")
        self.assertEqual(temp["sensor_identity"]["device_path"], "/sys/devices/virtual/thermal/thermal_zone0")
        self.assertEqual(temp["sensor_identity"]["temp_file"]["inode"], (self.sensor / "temp").stat().st_ino)
        self.assertEqual(result["temperature_target"]["tcc_activation_celsius"], 95)
        self.assertFalse(result["managed"])
        self.assertIn("not a temperature guarantee or hardware qualification", temp["meaning"])

    def test_diagnostic_range_includes_zero_and_125000(self):
        for value in (0, 125000):
            (self.sensor / "temp").write_text(str(value))
            self.assertEqual(self.env.read_package_temperature()["millicelsius"], value)

    def test_invalid_missing_or_unbounded_value_is_unavailable(self):
        for value in ("", "65.0", "nan", "-1", "125001", "+65000", "0" * 65):
            with self.subTest(value=value):
                (self.sensor / "temp").write_text(value)
                result = self.host.controller.status()
                self.assertFalse(result["package_temperature"]["available"])
                self.assertIsNone(result["package_temperature"]["millicelsius"])
                self.assertEqual(len(result["diagnostic_errors"]), 1)
        (self.sensor / "temp").unlink()
        self.assertFalse(self.host.controller.status()["package_temperature"]["available"])

    def test_missing_multiple_or_wrong_sensor_type_rejected(self):
        link = self.host.path("/sys/class/thermal/thermal_zone0")
        (self.sensor / "type").write_text("other")
        with self.assertRaisesRegex(POWER.PowerError, "Exactly one"):
            self.env.read_package_temperature()
        (self.sensor / "type").write_text("x86_pkg_temp")
        self.host.write("/sys/devices/virtual/thermal/thermal_zone1/type", "x86_pkg_temp")
        self.host.path("/sys/class/thermal/thermal_zone1").symlink_to(self.host.path("/sys/devices/virtual/thermal/thermal_zone1"))
        with self.assertRaisesRegex(POWER.PowerError, "Exactly one"):
            self.env.read_package_temperature()
        self.host.path("/sys/class/thermal/thermal_zone1").unlink()
        link.unlink()
        with self.assertRaisesRegex(POWER.PowerError, "Exactly one"):
            self.env.read_package_temperature()

    def test_sensor_outside_devices_and_symlink_controls_rejected(self):
        link = self.host.path("/sys/class/thermal/thermal_zone0")
        link.unlink()
        self.host.write("/outside/type", "x86_pkg_temp")
        link.symlink_to(self.host.path("/outside"))
        with self.assertRaisesRegex(POWER.PowerError, "/sys/devices"):
            self.env.read_package_temperature()
        link.unlink()
        link.symlink_to(self.sensor)
        for name in ("temp", "type"):
            control = self.sensor / name
            value = control.read_text()
            control.unlink()
            foreign = self.host.write("/foreign-" + name, value)
            control.symlink_to(foreign)
            with self.assertRaises(POWER.PowerError):
                self.env.read_package_temperature()
            control.unlink()
            control.write_text(value)

    def test_clock_failure_is_diagnostic_and_never_stale(self):
        self.assertEqual(self.host.controller.status()["package_temperature"]["millicelsius"], 65000)
        for clocks in ([20, 10], [True, 20]):
            with mock.patch.object(POWER.time, "monotonic_ns", side_effect=clocks):
                result = self.host.controller.status()
            self.assertFalse(result["package_temperature"]["available"])
            self.assertIsNone(result["package_temperature"]["millicelsius"])
            self.assertIsNone(result["package_temperature"]["sensor_identity"])
            self.assertEqual(result["errors"], [])

    def test_replaced_temp_or_class_link_during_read_rejected(self):
        original = POWER.os.read
        for kind in ("temp", "class"):
            replaced = []
            def read(fd, size):
                value = original(fd, size)
                if value == b"65000\n" and not replaced:
                    replaced.append(True)
                    if kind == "temp":
                        (self.sensor / "temp").unlink()
                        (self.sensor / "temp").write_text("65000\n")
                    else:
                        link = self.host.path("/sys/class/thermal/thermal_zone0")
                        link.unlink()
                        link.symlink_to(self.sensor)
                return value
            with mock.patch.object(POWER.os, "read", side_effect=read), self.assertRaises(POWER.PowerError):
                self.env.read_package_temperature()
            self.assertTrue(replaced)

    def test_replaced_physical_sensor_directory_rejected(self):
        original = POWER.os.read
        changed = []
        def read(fd, size):
            value = original(fd, size)
            if value == b"65000\n" and not changed:
                changed.append(True)
                self.sensor.rename(self.sensor.with_name("old_sensor"))
                self.host.write("/sys/devices/virtual/thermal/thermal_zone0/type", "x86_pkg_temp\n")
                self.host.write("/sys/devices/virtual/thermal/thermal_zone0/temp", "65000\n")
            return value
        with mock.patch.object(POWER.os, "read", side_effect=read), self.assertRaises(POWER.PowerError):
            self.env.read_package_temperature()
        self.assertTrue(changed)

    def test_package_diagnostic_failure_preserves_holding_and_is_readonly(self):
        self.host.controller.set_limit(55)
        before = self.host.controller.status()
        files = {p: p.read_bytes() for p in self.host.root.rglob("*") if p.is_file()}
        commands = len(self.host.commands)
        (self.sensor / "temp").write_text("invalid")
        files[self.sensor / "temp"] = b"invalid"
        with mock.patch.object(self.env, "write_control", side_effect=AssertionError("status wrote a control")):
            after = self.host.controller.status()
        self.assertTrue(before["holding_now"])
        self.assertTrue(after["holding_now"])
        self.assertEqual(after["errors"], before["errors"])
        self.assertFalse(after["package_temperature"]["available"])
        self.assertTrue(after["diagnostic_errors"])
        self.assertEqual({p: p.read_bytes() for p in files}, files)
        self.assertTrue(all(command[:2] not in (["systemctl", "restart"], ["systemctl", "daemon-reload"])
                            for command in self.host.commands[commands:]))

    def test_sensor_adapter_opens_readonly_and_closes_on_io_failure(self):
        original_open, original_close, original_read = POWER.os.open, POWER.os.close, POWER.os.read
        opened, closed, flags = [], [], []
        def open_file(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            flags.append(args[1])
            return fd
        def close_file(fd):
            closed.append(fd)
            return original_close(fd)
        def read_file(fd, size):
            value = original_read(fd, size)
            if value == b"65000\n":
                raise OSError("injected sensor read failure")
            return value
        with mock.patch.object(POWER.os, "open", side_effect=open_file), mock.patch.object(POWER.os, "close", side_effect=close_file), mock.patch.object(POWER.os, "read", side_effect=read_file), self.assertRaises(POWER.PowerError):
            self.env.read_package_temperature()
        self.assertEqual(len(opened), len(closed))
        self.assertTrue(all(flag & os.O_ACCMODE == os.O_RDONLY and flag & os.O_NOFOLLOW for flag in flags))


class PowerTransactions(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost(self)
        self.controller = self.host.controller
        # These transaction/RAPL tests isolate the optional hardware diagnostic.
        # Its real adapter is exercised in test_power_temperature_target.py.
        target = mock.patch.object(self.host.env, "read_temperature_target", return_value={
            "platform_info_raw": 1 << 30, "temperature_target_raw": (100 << 16) | (15 << 24),
            "tjmax_celsius": 100, "tcc_offset_celsius": 15, "tcc_activation_celsius": 85})
        target.start()
        self.addCleanup(target.stop)

    def assert_unconfigured(self):
        for path in (POWER.XML, POWER.DROPIN, POWER.STATE):
            self.assertFalse(self.host.path(path).exists(), str(path))

    def pending(self, operation="set"):
        self.controller.set_limit(55)
        state = json.loads(self.host.read(POWER.STATE))
        transaction = str(uuid.uuid4())
        state["operation_id"] = transaction
        state["transaction"] = {"id": transaction, "operation": operation,
                                "owner": self.host.env.process_identity()}
        self.host.write(POWER.STATE, json.dumps(state))
        return state

    def orphaned_owner(self):
        identity = self.host.env.process_identity
        return mock.patch.object(self.host.env, "process_identity",
                                 side_effect=lambda pid=None: identity() if pid is None else None)

    def test_recover_refuses_a_transaction_owned_by_a_live_process(self):
        self.pending()
        original = {path: self.host.read(path) for path in (POWER.XML, POWER.DROPIN, POWER.STATE)}
        with self.assertRaises(POWER.PowerError):
            self.controller.recover()
        self.assertEqual({path: self.host.read(path) for path in original}, original)
        self.assertTrue(self.host.active)

    def test_recover_accepts_a_reused_pid_with_a_different_start_time(self):
        state = self.pending()
        original = self.host.env.process_identity
        reused = dict(state["transaction"]["owner"])
        reused["start_ticks"] += 1
        with mock.patch.object(self.host.env, "process_identity",
                               side_effect=lambda pid=None: original() if pid is None else reused):
            with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
                self.controller.recover()
        writes.assert_not_called()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_recover_accepts_a_previous_boot_owner_even_if_its_pid_now_exists(self):
        self.pending()
        with mock.patch.object(self.host.env, "boot_id", return_value=str(uuid.uuid4())):
            self.controller.recover()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def _assert_recover_handles_partial_clear(self, missing):
        self.pending("clear")
        self.host.path(missing).unlink()
        with self.orphaned_owner():
            with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
                self.controller.recover()
        writes.assert_not_called()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.limits(), [55_000_000, 55_000_000])

    def test_recover_handles_clear_with_xml_already_removed(self):
        self._assert_recover_handles_partial_clear(POWER.XML)

    def test_recover_handles_clear_with_dropin_already_removed(self):
        self._assert_recover_handles_partial_clear(POWER.DROPIN)

    def test_recover_preserves_foreign_bytes_even_for_an_orphaned_transaction(self):
        self.pending("clear")
        foreign = self.host.read(POWER.XML) + "<!-- user changed this -->\n"
        self.host.write(POWER.XML, foreign)
        original_state = self.host.read(POWER.STATE)
        with self.orphaned_owner():
            with self.assertRaises(POWER.PowerError):
                self.controller.recover()
        self.assertEqual(self.host.read(POWER.XML), foreign)
        self.assertEqual(self.host.read(POWER.STATE), original_state)
        self.assertTrue(self.host.path(POWER.DROPIN).is_file())

    def test_failed_recover_retains_a_failure_receipt_and_can_be_retried(self):
        self.pending()
        self.host.restart_failures = [True, False]
        with self.orphaned_owner():
            with self.assertRaises(POWER.PowerError):
                self.controller.recover()
            self.assertTrue(self.host.path(POWER.STATE).is_file())
            receipts = [json.loads(path.read_text()) for path in self.host.path(POWER.RECEIPTS).glob("*.json")]
            self.assertTrue(any(receipt["operation"] == "recover" and not receipt["success"]
                                for receipt in receipts))
            self.controller.recover()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_recover_does_not_discard_a_completed_configuration(self):
        self.controller.set_limit(55)
        original = self.host.read(POWER.STATE)
        with self.assertRaises(POWER.PowerError):
            self.controller.recover()
        self.assertEqual(self.host.read(POWER.STATE), original)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_recover_fails_closed_when_owner_identity_cannot_be_read(self):
        self.pending()
        original = self.host.read(POWER.STATE)
        with mock.patch.object(self.host.env, "process_identity", side_effect=OSError("permission denied")):
            with self.assertRaises(POWER.PowerError):
                self.controller.recover()
        self.assertEqual(self.host.read(POWER.STATE), original)
        self.assertTrue(self.host.path(POWER.XML).is_file())

    def test_recover_accepts_verified_prior_xml_after_partial_limit_update(self):
        self.controller.set_limit(55)
        old_xml = self.host.read(POWER.XML)
        atomic = self.host.env.atomic

        def die_after_new_state(path, data, mode=0o600):
            atomic(path, data, mode)
            if path == POWER.STATE and json.loads(data)["cap_uw"] == 80_000_000:
                raise SystemExit("interrupted before replacing old XML")

        with mock.patch.object(self.host.env, "atomic", side_effect=die_after_new_state):
            with self.assertRaises(SystemExit):
                self.controller.set_limit(80)
        self.assertEqual(json.loads(self.host.read(POWER.STATE))["cap_uw"], 80_000_000)
        self.assertEqual(self.host.read(POWER.XML), old_xml)
        with self.orphaned_owner():
            self.controller.recover()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_recover_accepts_verified_prior_xml_during_interrupted_rollback(self):
        self.controller.set_limit(55)
        old_xml = self.host.read(POWER.XML).encode()
        self.host.restart_failures = [True]
        atomic = self.host.env.atomic
        restored_old_xml = False

        def die_after_restoring_xml(path, data, mode=0o600):
            nonlocal restored_old_xml
            atomic(path, data, mode)
            if path == POWER.XML and data == old_xml:
                restored_old_xml = True
                raise SystemExit("interrupted during rollback")

        with mock.patch.object(self.host.env, "atomic", side_effect=die_after_restoring_xml):
            with self.assertRaises(SystemExit):
                self.controller.set_limit(80)
        self.assertTrue(restored_old_xml)
        with self.orphaned_owner():
            self.controller.recover()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_sigkill_orphan_can_be_recovered_without_upward_hardware_writes(self):
        code = r'''
import os, signal, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_mechrevo_power import FakeHost
host = FakeHost(unittest.TestCase(), root=Path(sys.argv[1]))
run = host.env.runner
def killed_at_restart(argv):
    if argv == ['systemctl', 'restart', 'thermald.service']:
        os.kill(os.getpid(), signal.SIGKILL)
    return run(argv)
host.env.runner = killed_at_restart
host.controller.set_limit(55)
'''
        child = subprocess.Popen([sys.executable, "-c", code, str(self.host.root)],
                                 cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, -signal.SIGKILL, stdout + stderr)
        state = json.loads(self.host.read(POWER.STATE))
        self.assertEqual(state["transaction"]["owner"]["pid"], child.pid)
        self.assertIsNone(self.host.env.process_identity(child.pid))
        with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
            self.controller.recover()
        writes.assert_not_called()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_set_down_limits_both_interfaces_and_preserves_other_controls(self):
        before = self.host.protected_controls()
        result = self.controller.set_limit(55)
        self.assertEqual(self.host.limits(), [55_000_000, 55_000_000])
        self.assertEqual(self.host.protected_controls(), before)
        self.assertTrue(self.host.active)
        self.assertIsInstance(result, dict)
        self.assertTrue(self.host.path(POWER.STATE).is_file())
        root = ET.fromstring(self.host.read(POWER.XML))
        devices = {node.findtext("Type"): node for node in root.iter("CoolingDevice")}
        self.assertEqual(set(devices), {"rapl_controller", "rapl_controller_mmio"})
        for device in devices.values():
            self.assertEqual(int(device.findtext("MinState")), 55_000_000)
            self.assertEqual(int(device.findtext("MaxState")), 27_500_000)
        self.assertEqual(self.host.read(POWER.STOCK_UNIT), STOCK_UNIT)

    def test_apply_never_raises_a_thermally_lowered_interface(self):
        self.controller.set_limit(55)
        self.host.limit_path(0).write_text("40000000\n")
        self.host.limit_path(1).write_text("140000000\n")
        self.controller.apply()
        self.assertEqual(self.host.limits(), [40_000_000, 55_000_000])
        self.host.limit_path(1).write_text("30000000\n")
        self.controller.apply()
        self.assertEqual(self.host.limits(), [40_000_000, 30_000_000])

    def test_clear_restores_stock_service_without_a_direct_upward_limit_write(self):
        self.controller.set_limit(55)
        self.host.limit_path(0).write_text("40000000\n")
        self.host.limit_path(1).write_text("30000000\n")
        self.controller.clear()
        self.assert_unconfigured()
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.limits(), [40_000_000, 30_000_000])
        self.assertEqual(self.host.read(POWER.STOCK_UNIT), STOCK_UNIT)

    def test_clear_partial_staging_failure_restores_managed_files_and_service(self):
        self.controller.set_limit(55)
        original_files = {path: self.host.read(path) for path in (POWER.XML, POWER.DROPIN)}
        remove = self.host.env.remove
        failed = False

        def fail_dropin_once(path):
            nonlocal failed
            if path == POWER.DROPIN and not failed:
                failed = True
                raise OSError("injected failure after XML removal")
            return remove(path)

        with mock.patch.object(self.host.env, "remove", side_effect=fail_dropin_once):
            with self.assertRaises(POWER.PowerError):
                self.controller.clear()
        self.assertTrue(failed)
        self.assertEqual({path: self.host.read(path) for path in original_files}, original_files)
        state = json.loads(self.host.read(POWER.STATE))
        self.assertFalse(state.get("transaction"))
        self.assertTrue(self.host.active)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_initial_restart_failure_restores_configuration_and_active_thermal_daemon(self):
        self.host.restart_failures = [True, False]
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_second_interface_write_failure_rolls_back_config_and_keeps_thermal_daemon(self):
        before = self.host.protected_controls()
        original = self.host.env.write_control
        writes = []

        def fail_second(path, value):
            writes.append((str(path), value))
            if str(path).startswith(POWER.ZONES[1] + "/"):
                raise OSError("injected second-interface write failure")
            return original(path, value)

        with mock.patch.object(self.host.env, "write_control", side_effect=fail_second):
            with self.assertRaises(POWER.PowerError):
                self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.limits(), [55_000_000, 140_000_000])
        self.assertEqual(self.host.protected_controls(), before)
        self.assertEqual([value for _, value in writes], [55_000_000, 55_000_000])

    def test_kernel_readback_mismatch_is_failure_and_restores_thermal_service(self):
        original = self.host.env.write_control

        def ignored_write(path, value):
            original(path, value)
            self.host.path(path).write_text("133000000\n")

        with mock.patch.object(self.host.env, "write_control", side_effect=ignored_write):
            with self.assertRaises(POWER.PowerError):
                self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_service_and_rollback_failure_are_reported_instead_of_success(self):
        self.host.restart_failures = [True, True]
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertFalse(self.host.active)

    def test_managed_rollback_requires_apply_to_succeed_in_addition_to_daemon_active(self):
        self.controller.set_limit(55)
        old_xml = self.host.read(POWER.XML)
        run = self.host.env.runner

        def raise_before_every_restart(argv):
            if argv == ["systemctl", "restart", "thermald.service"]:
                for index in range(2):
                    self.host.limit_path(index).write_text("140000000\n")
            return run(argv)

        self.host.env.runner = raise_before_every_restart
        with mock.patch.object(self.host.env, "write_control", side_effect=OSError("kernel write denied")):
            with self.assertRaisesRegex(POWER.PowerError, "ROLLBACK FAILED"):
                self.controller.set_limit(60)
        self.assertTrue(self.host.active)
        self.assertEqual(self.host.read(POWER.XML), old_xml)
        self.assertFalse(self.controller.status()["holding_now"])

    def _assert_rollback_blocks_concurrent_mutation(self, operation):
        self.controller.set_limit(55)
        self.host.restart_failures = [True, False]
        run = self.host.env.runner
        restarts = 0
        rejected = []

        def concurrent_during_rollback(argv):
            nonlocal restarts
            if argv == ["systemctl", "restart", "thermald.service"]:
                restarts += 1
                if restarts == 2:
                    try:
                        if operation == "set":
                            self.controller.set_limit(65)
                        else:
                            self.controller.clear()
                    except POWER.PowerError:
                        rejected.append(True)
                    else:
                        rejected.append(False)
            return run(argv)

        self.host.env.runner = concurrent_during_rollback
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(60)
        self.assertEqual(rejected, [True], "rollback restart must retain its transaction barrier")
        self.assertEqual(json.loads(self.host.read(POWER.STATE))["cap_uw"], 55_000_000)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_rollback_blocks_concurrent_set_while_service_restarts(self):
        self._assert_rollback_blocks_concurrent_mutation("set")

    def test_rollback_blocks_concurrent_clear_while_service_restarts(self):
        self._assert_rollback_blocks_concurrent_mutation("clear")

    def test_stock_rollback_checks_the_actually_loaded_service_configuration(self):
        self.host.restart_failures = [True, False]
        run = self.host.env.runner
        restarts = 0

        def wrong_loaded_command_after_rollback(argv):
            nonlocal restarts
            result = run(argv)
            if argv == ["systemctl", "restart", "thermald.service"]:
                restarts += 1
                if restarts == 2:
                    self.host.service_overrides["ExecStart"] = "/usr/bin/thermald --no-existing-policy"
            return result

        self.host.env.runner = wrong_loaded_command_after_rollback
        with self.assertRaisesRegex(POWER.PowerError, "ROLLBACK FAILED"):
            self.controller.set_limit(55)
        self.assertTrue(self.host.active)

    def test_keyboard_interrupt_during_restart_restores_stock_configuration(self):
        run = self.host.env.runner
        interrupted = False

        def interrupt_once(argv):
            nonlocal interrupted
            if argv == ["systemctl", "restart", "thermald.service"] and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return run(argv)

        self.host.env.runner = interrupt_once
        with self.assertRaises((POWER.PowerError, KeyboardInterrupt)):
            self.controller.set_limit(55)
        self.assertTrue(interrupted)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def _interrupt_first_lock_exit(self):
        lock = self.controller.lock
        interrupted = False

        @contextmanager
        def interrupt_after_unlock():
            nonlocal interrupted
            with lock():
                yield
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt()

        return mock.patch.object(self.controller, "lock", side_effect=interrupt_after_unlock)

    def test_set_interrupt_at_unlock_restart_handoff_restores_stock_configuration(self):
        with self._interrupt_first_lock_exit():
            with self.assertRaises((POWER.PowerError, KeyboardInterrupt)):
                self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_clear_interrupt_at_unlock_restart_handoff_restores_managed_configuration(self):
        self.controller.set_limit(55)
        with self._interrupt_first_lock_exit():
            with self.assertRaises((POWER.PowerError, KeyboardInterrupt)):
                self.controller.clear()
        self.assertTrue(self.controller.status()["holding_now"])
        self.assertTrue(self.host.active)
        self.assertFalse(json.loads(self.host.read(POWER.STATE)).get("transaction"))

    def test_sigterm_during_cli_restart_restores_stock_configuration(self):
        code = r'''
import json, os, signal, sys, unittest
from unittest import mock
sys.path.insert(0, str(__import__('pathlib').Path.cwd() / 'tests'))
from test_mechrevo_power import FakeHost, POWER
case = unittest.TestCase()
host = FakeHost(case)
run = host.env.runner
interrupted = False
def terminate_once(argv):
    global interrupted
    if argv == ['systemctl', 'restart', 'thermald.service'] and not interrupted:
        interrupted = True
        os.kill(os.getpid(), signal.SIGTERM)
    return run(argv)
host.env.runner = terminate_once
try:
    with mock.patch.object(POWER, 'PowerController', return_value=host.controller):
        result = POWER.main(['set', '55'])
    print(json.dumps({'exit_code': result, 'interrupted': interrupted,
                      'active': host.active,
                      'remaining': [path for path in (POWER.XML, POWER.DROPIN, POWER.STATE)
                                    if host.path(path).exists()]}))
finally:
    case.doCleanups()
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        evidence = json.loads(result.stdout.splitlines()[-1])
        self.assertNotEqual(evidence["exit_code"], 0)
        self.assertTrue(evidence["interrupted"])
        self.assertTrue(evidence["active"])
        self.assertEqual(evidence["remaining"], [])

    def test_final_status_failure_cannot_be_returned_as_a_successful_set(self):
        status = self.controller.status

        def external_override_before_final_status():
            self.host.limit_path(0).write_text("133000000\n")
            return status()

        with mock.patch.object(self.controller, "status", side_effect=external_override_before_final_status):
            with self.assertRaises(POWER.PowerError):
                self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertTrue(self.host.active)

    def test_final_status_cannot_be_replaced_by_a_concurrent_limit_change(self):
        status = self.controller.status
        rejected = []

        def concurrent_set_during_final_status():
            try:
                self.controller.set_limit(60)
            except POWER.PowerError:
                rejected.append(True)
            else:
                rejected.append(False)
            return status()

        with mock.patch.object(self.controller, "status", side_effect=concurrent_set_during_final_status):
            result = self.controller.set_limit(55)
        self.assertEqual(rejected, [True])
        self.assertTrue(result["holding_now"])
        self.assertEqual(result["desired_limit_uw"], 55_000_000)
        self.assertEqual(json.loads(self.host.read(POWER.STATE))["cap_uw"], 55_000_000)

    def test_failed_apply_does_not_forge_a_successful_receipt(self):
        self.controller.set_limit(55)
        self.host.limit_path(0).write_text("140000000\n")
        self.host.limit_path(1).write_text("140000000\n")
        with mock.patch.object(self.host.env, "write_control", side_effect=OSError("write denied")):
            with self.assertRaises(POWER.PowerError):
                self.controller.apply()
        state = json.loads(self.host.read(POWER.STATE))
        self.assertFalse(state["last_apply"]["success"])
        self.assertFalse(self.controller.status()["holding_now"])

    def test_status_observes_actual_power_limits_instead_of_trusting_state(self):
        self.controller.set_limit(55)
        self.assertTrue(self.controller.status()["holding_now"])
        self.host.limit_path(0).write_text("133000000\n")
        status = self.controller.status()
        self.assertFalse(status["holding_now"])
        self.assertEqual(status["observed"][POWER.ZONES[0]]["pl1_uw"], 133_000_000)

    def test_status_requires_the_thermal_daemon_to_be_active(self):
        self.controller.set_limit(55)
        self.host.active = False
        self.assertFalse(self.controller.status()["holding_now"])

    def test_status_distinguishes_held_pl1_from_unmanaged_high_pl2(self):
        self.controller.set_limit(55)
        original_observed = self.controller.observe()
        status = self.controller.status()
        self.assertTrue(status["holding_now"])
        self.assertEqual(status["holding_scope"], "cpu_package_pl1")
        self.assertFalse(status["pl2_managed"])
        self.assertEqual(status["observed"], original_observed)
        self.assertEqual(status["diagnostic_errors"], [])
        for zone in POWER.ZONES:
            self.assertEqual(status["rapl_constraints"][zone], {
                "pl1": {"available": True, "name": "long_term", "name_valid": True,
                        "power_limit_uw": 55_000_000, "time_window_us": 55_967_744},
                "pl2": {"available": True, "name": "short_term", "name_valid": True,
                        "power_limit_uw": 140_000_000, "time_window_us": 2440}})

    def test_optional_pl2_diagnostics_fail_without_invalidating_pl1_holding(self):
        self.controller.set_limit(55)
        for zone in POWER.ZONES:
            for field, value in (("name", "peak_power"), ("power_limit_uw", "bad"),
                                 ("power_limit_uw", "-1"), ("time_window_us", "bad"),
                                 ("time_window_us", "-1"), ("name", None),
                                 ("power_limit_uw", None), ("time_window_us", None)):
                with self.subTest(zone=zone, field=field, value=value):
                    path = self.host.path(f"{zone}/constraint_1_{field}")
                    original = path.read_bytes()
                    try:
                        if value is None:
                            path.unlink()
                        else:
                            path.write_text(value + "\n")
                        status = self.controller.status()
                        self.assertTrue(status["holding_now"])
                        self.assertEqual(status["errors"], [])
                        entry = status["rapl_constraints"][zone]["pl2"]
                        self.assertFalse(entry["available"])
                        self.assertIsNone(entry["power_limit_uw"])
                        self.assertIsNone(entry["time_window_us"])
                        self.assertEqual(len(status["diagnostic_errors"]), 1)
                        self.assertIn(zone + " pl2", status["diagnostic_errors"][0])
                        other = next(candidate for candidate in POWER.ZONES if candidate != zone)
                        self.assertTrue(status["rapl_constraints"][other]["pl2"]["available"])
                    finally:
                        path.write_bytes(original)

    def test_status_diagnostics_do_not_write_controls_files_or_restart_services(self):
        self.controller.set_limit(55)
        before = {str(path.relative_to(self.host.root)): path.read_bytes()
                  for path in self.host.root.rglob("*") if path.is_file()}
        self.host.commands.clear()
        with mock.patch.object(self.host.env, "write_control", side_effect=AssertionError("write")), \
                mock.patch.object(self.host.env, "atomic", side_effect=AssertionError("atomic")), \
                mock.patch.object(self.host.env, "directory", side_effect=AssertionError("directory")):
            self.assertTrue(self.controller.status()["holding_now"])
        self.assertEqual(before, {str(path.relative_to(self.host.root)): path.read_bytes()
                                  for path in self.host.root.rglob("*") if path.is_file()})
        self.assertTrue(self.host.commands)
        self.assertTrue(all(command == ["/usr/bin/thermald", "--version"]
                            or command[:3] == ["systemctl", "show", "thermald.service"]
                            for command in self.host.commands))

    def test_missing_pl1_window_diagnostic_does_not_change_pl1_qualification(self):
        self.controller.set_limit(55)
        self.host.path(POWER.ZONES[0] + "/constraint_0_time_window_us").unlink()
        status = self.controller.status()
        self.assertTrue(status["holding_now"])
        self.assertEqual(status["errors"], [])
        self.assertFalse(status["rapl_constraints"][POWER.ZONES[0]]["pl1"]["available"])
        self.assertEqual(status["observed"][POWER.ZONES[0]]["pl1_uw"], 55_000_000)
        self.assertEqual(len(status["diagnostic_errors"]), 1)

    def test_status_preserves_actual_zero_pl2_readings_without_managing_them(self):
        self.controller.set_limit(55)
        for zone in POWER.ZONES:
            self.host.write(zone + "/constraint_1_power_limit_uw", "0\n")
            self.host.write(zone + "/constraint_1_time_window_us", "0\n")
        stdout = io.StringIO()
        with mock.patch.object(POWER, "PowerController", return_value=self.controller), \
                redirect_stdout(stdout):
            self.assertEqual(POWER.main(["status"]), 0)
        status = json.loads(stdout.getvalue())
        self.assertTrue(status["holding_now"])
        self.assertFalse(status["pl2_managed"])
        self.assertEqual(status["diagnostic_errors"], [])
        for zone in POWER.ZONES:
            entry = status["rapl_constraints"][zone]["pl2"]
            self.assertTrue(entry["available"])
            self.assertEqual(entry["power_limit_uw"], 0)
            self.assertEqual(entry["time_window_us"], 0)

    def test_status_uses_the_latest_qualification_readback(self):
        self.controller.set_limit(55)
        observe = self.controller.observe
        calls = 0

        def externally_raised_second_sample():
            nonlocal calls
            calls += 1
            if calls == 2:
                self.host.limit_path(0).write_text("133000000\n")
            return observe()

        with mock.patch.object(self.controller, "observe", side_effect=externally_raised_second_sample):
            status = self.controller.status()
        self.assertGreaterEqual(calls, 2)
        self.assertFalse(status["holding_now"])
        self.assertEqual(status["observed"][POWER.ZONES[0]]["pl1_uw"], 133_000_000)

    def test_invalid_requested_limits_do_not_write_configuration_or_hardware(self):
        for watts in (-1, 0, 34, 141, 55.5, "55", None):
            with self.subTest(watts=watts):
                with self.assertRaises(POWER.PowerError):
                    self.controller.set_limit(watts)
                self.assert_unconfigured()
                self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_lower_caps_keep_thermal_spec_identity_and_preserve_stricter_cooling(self):
        for watts in (35, 45, 54, 55):
            with self.subTest(watts=watts):
                self.host.limit_path(0).write_text("30000000\n")
                # The second interface is independently initialized above cap.
                self.host.limit_path(1).write_text("55000000\n")
                # Start with a managed baseline so initial ceiling is stable.
                if self.controller.load_state() is None:
                    self.host.limit_path(0).write_text("140000000\n")
                    self.host.limit_path(1).write_text("140000000\n")
                    self.controller.set_limit(55)
                    self.host.limit_path(0).write_text("30000000\n")
                status = self.controller.set_limit(watts)
                self.assertTrue(status["holding_now"])
                self.assertEqual(status["desired_limit_uw"], watts * 1_000_000)
                self.assertEqual(self.host.limits(), [30_000_000, watts * 1_000_000])
                self.assertTrue(all(v["max_power_uw"] == 55_000_000
                                    for v in status["observed"].values()))
                xml = ET.fromstring(self.host.read(POWER.XML))
                for device in xml.findall("./Platform/CoolingDevices/CoolingDevice"):
                    self.assertEqual(int(device.findtext("MinState")), watts * 1_000_000)
                    self.assertEqual(int(device.findtext("MaxState")), watts * 500_000)
                self.controller.apply()
                self.assertEqual(self.host.limits()[0], 30_000_000)

    def test_lower_cap_failed_restart_restores_previous_managed_cap(self):
        self.controller.set_limit(55)
        self.host.restart_failures = [True, False]
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(35)
        self.assertEqual(self.controller.load_state()["cap_uw"], 55_000_000)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_mutation_requires_root(self):
        self.host.env.uid = 1000
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_other_bios_is_rejected_before_any_mutation(self):
        self.host.write("/sys/class/dmi/id/bios_version", "N.1.10\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_other_product_is_rejected_before_any_mutation(self):
        self.host.write("/sys/class/dmi/id/product_name", "Similar GM6PX0X device\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_other_cpu_is_rejected_before_any_mutation(self):
        self.host.write("/proc/cpuinfo", "model name\t: Intel Core i9-14900HX\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_other_daemon_version_is_rejected_before_any_mutation(self):
        self.host.version = "2.5.14"
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_unqualified_daemon_binary_is_rejected_before_any_mutation(self):
        self.host.write("/usr/bin/thermald", "same-version different binary\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_daemon_binary_change_blocks_apply_before_hardware_writes(self):
        self.controller.set_limit(55)
        state = json.loads(self.host.read(POWER.STATE))
        self.assertEqual(state["thermald_sha256"],
                         hashlib.sha256(self.host.path("/usr/bin/thermald").read_bytes()).hexdigest())
        self.host.write("/usr/bin/thermald", "unreviewed daemon update\n")
        self.host.limit_path(0).write_text("133000000\n")
        with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
            with self.assertRaises(POWER.PowerError):
                self.controller.apply()
        writes.assert_not_called()
        self.assertEqual(self.host.limits(), [133_000_000, 55_000_000])
        self.assertFalse(self.controller.status()["holding_now"])

    def test_ppcc_firmware_is_rejected_before_any_mutation(self):
        self.host.write("/sys/bus/pci/devices/0000:00:04.0/power_limits", "firmware PPCC table\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_int3400_adaptive_firmware_is_rejected_before_any_mutation(self):
        self.host.path("/sys/bus/platform/drivers/int3400 thermal").mkdir(parents=True)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_tcc_offset_above_qualified_range_is_rejected(self):
        self.host.write("/sys/bus/pci/devices/0000:00:04.0/tcc_offset_degree_celsius", "11\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_tcc_offset_boundary_is_allowed(self):
        self.host.write("/sys/bus/pci/devices/0000:00:04.0/tcc_offset_degree_celsius", "10\n")
        self.controller.set_limit(55)
        self.assertEqual(self.host.limits(), [55_000_000, 55_000_000])

    def test_unknown_preference_is_rejected_without_erasing_it(self):
        self.host.write(POWER.PREF, "2\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertEqual(self.host.read(POWER.PREF), "2\n")

    def test_existing_preference_is_preserved(self):
        for preference in (0, 1):
            with self.subTest(preference=preference):
                self.host.write(POWER.PREF, f"{preference}\n")
                self.controller.set_limit(55)
                self.assertEqual(self.host.read(POWER.PREF), f"{preference}\n")
                xml = ET.fromstring(self.host.read(POWER.XML))
                self.assertEqual(xml.findtext(".//Preference"),
                                 ("ENERGY_CONSERVE", "PERFORMANCE")[preference])
                self.controller.clear()

    def test_missing_preference_uses_the_native_energy_conserve_default(self):
        self.assertFalse(self.host.path(POWER.PREF).exists())
        self.controller.set_limit(55)
        xml = ET.fromstring(self.host.read(POWER.XML))
        self.assertEqual(xml.findtext(".//Preference"), "ENERGY_CONSERVE")

    def test_foreign_stock_thermal_configuration_is_preserved(self):
        original = "<ThermalConfiguration><Platform><Name>existing cooling policy</Name></Platform></ThermalConfiguration>\n"
        path = "/etc/thermald/thermal-conf.xml"
        self.host.write(path, original)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(path), original)
        self.assert_unconfigured()

    def test_foreign_stock_exec_start_post_is_rejected(self):
        modified = STOCK_UNIT.replace("Restart=on-failure", "ExecStartPost=/usr/local/bin/power-policy\nRestart=on-failure")
        self.host.write(POWER.STOCK_UNIT, modified)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(POWER.STOCK_UNIT), modified)
        self.assert_unconfigured()

    def test_xml_thermal_config_disabled_is_rejected(self):
        path = "/etc/thermald/thermald-features.xml"
        original = self.host.read(path).replace("<XMLThermalConfig>1</XMLThermalConfig>",
                                                "<XMLThermalConfig>0</XMLThermalConfig>")
        self.host.write(path, original)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(path), original)
        self.assert_unconfigured()

    def test_disabled_powercap_interface_is_rejected(self):
        self.host.write(f"{POWER.ZONES[1]}/enabled", "0\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()
        self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_constraint_index_must_actually_be_long_term(self):
        self.host.write(f"{POWER.ZONES[1]}/constraint_0_name", "short_term\n")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assert_unconfigured()

    def test_status_without_managed_state_does_not_claim_a_user_cap(self):
        status = self.controller.status()
        self.assertFalse(status["managed"])
        self.assertFalse(status["holding_now"])
        self.assertIsNone(status["desired_limit_uw"])
        self.assertEqual(status["observed"][POWER.ZONES[0]]["pl1_uw"], 140_000_000)

    def test_foreign_xml_is_preserved(self):
        original = "<ThermalConfiguration><Platform><Name>user</Name></Platform></ThermalConfiguration>\n"
        self.host.write(POWER.XML, original)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(POWER.XML), original)
        self.assertFalse(self.host.path(POWER.STATE).exists())
        self.assertEqual(self.host.limits(), [140_000_000, 140_000_000])

    def test_foreign_service_dropin_is_preserved(self):
        original = "[Service]\nEnvironment=OTHER=1\n"
        self.host.write(POWER.DROPIN, original)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(POWER.DROPIN), original)
        self.assertFalse(self.host.path(POWER.STATE).exists())

    def test_xml_symlink_is_rejected_without_touching_its_target(self):
        target = self.host.write("/etc/user-original.xml", "preserve me\n")
        self.host.path(POWER.XML).parent.mkdir(parents=True, exist_ok=True)
        self.host.path(POWER.XML).symlink_to(target)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(target.read_text(), "preserve me\n")
        self.assertTrue(self.host.path(POWER.XML).is_symlink())

    def test_symlink_in_the_configuration_parent_is_rejected(self):
        directory = self.host.path(POWER.XML).parent
        # The baseline contains the features file; retain it in the target so
        # refusal cannot be explained by missing configuration data.
        target = self.host.path("/opt/thermal-config")
        target.parent.mkdir(parents=True)
        directory.rename(target)
        directory.symlink_to(target)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertFalse((target / Path(POWER.XML).name).exists())
        self.assertTrue(directory.is_symlink())
        self.assertFalse(self.host.path(POWER.STATE).exists())

    def test_state_symlink_is_rejected_without_touching_its_target(self):
        target = self.host.write("/etc/user-state.json", '{"user": "preserve"}\n')
        self.host.path(POWER.STATE).parent.mkdir(parents=True, exist_ok=True)
        self.host.path(POWER.STATE).symlink_to(target)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(target.read_text(), '{"user": "preserve"}\n')
        self.assertTrue(self.host.path(POWER.STATE).is_symlink())

    def test_malformed_state_is_preserved_and_rejected(self):
        original = '{"broken":'
        self.host.write(POWER.STATE, original)
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55)
        self.assertEqual(self.host.read(POWER.STATE), original)
        self.assertFalse(self.host.path(POWER.XML).exists())

    def test_managed_xml_modified_outside_the_tool_is_not_overwritten_or_removed(self):
        self.controller.set_limit(55)
        modified = self.host.read(POWER.XML) + "<!-- user adjustment -->\n"
        self.host.write(POWER.XML, modified)
        with self.assertRaises(POWER.PowerError):
            self.controller.clear()
        self.assertEqual(self.host.read(POWER.XML), modified)
        self.assertTrue(self.host.path(POWER.STATE).exists())


class PowerOrphanStatus(unittest.TestCase):
    """A missing state file must not make leftover configuration look healthy."""

    def setUp(self):
        self.host = FakeHost(self)
        self.controller = self.host.controller

    def snapshot(self):
        result = {}
        for path in self.host.root.rglob("*"):
            info = path.lstat()
            content = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            result[str(path.relative_to(self.host.root))] = (info.st_mode, info.st_uid, info.st_gid, content)
        return result

    def read_cli_status(self):
        before = self.snapshot()
        self.host.commands.clear()
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(self.host.env, "atomic", wraps=self.host.env.atomic) as atomic, \
                mock.patch.object(self.host.env, "remove", wraps=self.host.env.remove) as remove, \
                mock.patch.object(self.host.env, "directory", wraps=self.host.env.directory) as directory, \
                mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes, \
                mock.patch.object(POWER, "PowerController", return_value=self.controller), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = POWER.main(["status"])
        atomic.assert_not_called()
        remove.assert_not_called()
        directory.assert_not_called()
        writes.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(all(argv[:3] == ["systemctl", "show", "thermald.service"]
                            for argv in self.host.commands))
        return exit_code, json.loads(stdout.getvalue())

    def test_status_reports_each_orphaned_configuration_combination(self):
        for paths in ((POWER.XML,), (POWER.DROPIN,), (POWER.XML, POWER.DROPIN)):
            with self.subTest(paths=paths):
                for path in (POWER.XML, POWER.DROPIN):
                    if self.host.path(path).exists():
                        self.host.path(path).unlink()
                for path in paths:
                    data = self.controller.xml(55_000_000, "ENERGY_CONSERVE") if path == POWER.XML else self.controller.dropin()
                    self.host.write(path, data.decode())
                exit_code, status = self.read_cli_status()
                self.assertEqual(exit_code, 1)
                self.assertFalse(status["managed"])
                self.assertFalse(status["holding_now"])
                self.assertIsNone(status["desired_limit_uw"])
                self.assertTrue(status["observed"])
                self.assertIn("Orphan or foreign mechrevo-power configuration", "; ".join(status["errors"]))
                for path in paths:
                    self.assertIn(path, "; ".join(status["errors"]))

    def test_status_reports_broken_orphan_links_without_following_them(self):
        for path in (POWER.XML, POWER.DROPIN):
            with self.subTest(path=path):
                for candidate in (POWER.XML, POWER.DROPIN):
                    if os.path.lexists(self.host.path(candidate)):
                        self.host.path(candidate).unlink()
                link = self.host.path(path)
                link.parent.mkdir(parents=True, exist_ok=True)
                target = self.host.path("/missing-configuration-target")
                link.symlink_to(target)
                self.assertFalse(link.exists())
                exit_code, status = self.read_cli_status()
                self.assertEqual(exit_code, 1)
                self.assertIn(path, "; ".join(status["errors"]))
                self.assertFalse(status["holding_now"])
                self.assertTrue(link.is_symlink())
                self.assertFalse(target.exists())
                link.unlink()

    def test_status_without_state_or_configuration_remains_healthy_and_unqualified(self):
        self.host.write("/sys/class/dmi/id/product_name", "unqualified product\n")
        with mock.patch.object(self.controller, "qualify", side_effect=AssertionError("Unconfigured status must not qualify hardware")):
            exit_code, status = self.read_cli_status()
        self.assertEqual(exit_code, 0)
        self.assertEqual(status["errors"], [])
        self.assertFalse(status["managed"])
        self.assertFalse(status["holding_now"])

    def test_corrupt_state_error_is_not_replaced_by_an_orphan_diagnosis(self):
        self.host.write(POWER.STATE, '{"broken":')
        self.host.write(POWER.XML, self.controller.xml(55_000_000, "ENERGY_CONSERVE").decode())
        self.host.write(POWER.DROPIN, self.controller.dropin().decode())
        exit_code, status = self.read_cli_status()
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(status["errors"]), 1)
        self.assertIn("Invalid managed state:", status["errors"][0])
        self.assertNotIn("Orphan", status["errors"][0])
        self.assertFalse(status["holding_now"])

    def test_status_during_set_staging_reports_pending_state_without_orphaning_it(self):
        state_written, reader_done = threading.Event(), threading.Event()
        results, failures = [], []
        atomic = self.host.env.atomic
        staged = False

        def read_pending():
            try:
                if not state_written.wait(5):
                    raise AssertionError("set did not reach the state/XML boundary")
                results.append(self.controller.status())
            except BaseException as error:
                failures.append(error)
            finally:
                reader_done.set()

        def pause_after_pending_state(path, data, mode=0o600):
            nonlocal staged
            atomic(path, data, mode)
            if path == POWER.STATE and not staged:
                staged = True
                state_written.set()
                self.assertTrue(reader_done.wait(5), "status blocked behind set's transaction lock")

        reader = threading.Thread(target=read_pending)
        reader.start()
        try:
            with mock.patch.object(self.host.env, "atomic", side_effect=pause_after_pending_state):
                context = {}
                self.controller._stage_set(55, str(uuid.uuid4()), context)
        finally:
            state_written.set()
            reader.join(5)
        self.assertFalse(reader.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 1)
        pending = results[0]
        self.assertTrue(pending["managed"])
        self.assertEqual(pending["pending_transaction"]["operation"], "set")
        self.assertFalse(pending["holding_now"])
        self.assertTrue(pending["errors"])
        self.assertNotIn("Orphan", "; ".join(pending["errors"]))
        self.assertEqual(context["phase"], "staged")
        self.assertEqual(self.controller.load_state()["transaction"]["operation"], "set")


class PowerStateValidation(unittest.TestCase):
    """Malformed persisted data must never authorize writes or a holding claim."""

    def setUp(self):
        self.host = FakeHost(self)
        self.controller = self.host.controller
        self.controller.set_limit(55)
        self.valid = json.loads(self.host.read(POWER.STATE))
        self.host.commands.clear()

    def test_corrupt_nested_state_is_reported_and_preserved(self):
        mutations = [
            ((), []),
            (("version",), True),
            (("cap_uw",), True),
            (("initial_ceiling_uw",), True),
            (("initial_ceiling_uw",), 141_000_000),
            (("preference",), []),
            (("preference", "value"), False),
            (("preference", "value"), "0"),
            (("preference", "name"), "PERFORMANCE"),
            (("initial_limits",), []),
            (("initial_limits", POWER.ZONES[0]), {}),
            (("initial_limits", POWER.ZONES[0], "pl1_uw"), "140000000"),
            (("initial_limits", POWER.ZONES[0], "max_power_uw"), 54_000_000),
            (("initial_limits", POWER.ZONES[0], "physical_path"), "/outside/sysfs"),
            (("managed_hashes", POWER.XML), []),
            (("stock_unit_sha256",), "not-a-hash"),
            (("operation_id",), ""),
            (("backup",), ""),
            (("transaction",), None),
            (("transaction",), []),
            (("transaction",), {}),
            (("transaction",), "pending"),
            (("transaction",), {"id": "", "operation": "set", "owner": self.host.env.process_identity()}),
            (("transaction",), {"id": "pending", "operation": "unknown", "owner": self.host.env.process_identity()}),
            (("transaction",), {"id": "pending", "operation": "set", "owner": self.host.env.process_identity(),
                                "prior_cap_uw": None, "prior_managed_hashes": {POWER.XML: "foreign", POWER.DROPIN: None}}),
            (("last_apply",), []),
            (("last_apply",), {}),
            (("last_apply",), "success"),
            (("last_apply", "success"), "false"),
            (("last_apply", "success"), 1),
            (("last_apply", "operation"), "clear"),
            (("last_apply", "cap_uw"), 140_000_000),
            (("last_apply", "observed"), {}),
            (("last_apply", "observed", POWER.ZONES[0], "pl1_uw"), 140_000_000),
            (("last_apply", "writes"), ["/sys/foreign"]),
            (("last_apply", "transaction"), []),
        ]
        for keys, value in mutations:
            with self.subTest(keys=keys, value=value):
                state = json.loads(json.dumps(self.valid))
                if keys:
                    target = state
                    for key in keys[:-1]:
                        target = target[key]
                    target[keys[-1]] = value
                else:
                    state = value
                self.host.write(POWER.STATE, json.dumps(state))
                before = {path: path.read_bytes() for path in self.host.root.rglob("*") if path.is_file()}
                limits = self.host.limits()
                with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
                    status = self.controller.status()
                    self.assertFalse(status["holding_now"])
                    self.assertTrue(status["errors"])
                    self.assertIn("Invalid managed state:", status["errors"][0])
                    for operation in (lambda: self.controller.set_limit(55), self.controller.apply,
                                      self.controller.clear, self.controller.recover):
                        with self.assertRaises(POWER.PowerError):
                            operation()
                    writes.assert_not_called()
                self.assertEqual(self.host.limits(), limits)
                after = {path: path.read_bytes() for path in self.host.root.rglob("*") if path.is_file()}
                self.assertEqual(before, after)
                self.assertFalse(any(argv[:2] == ["systemctl", "restart"] for argv in self.host.commands))

    def test_invalid_pending_owner_is_reported_without_a_traceback(self):
        valid_owner = self.host.env.process_identity()
        for owner in (None, [], {}, dict(valid_owner, pid=True),
                      dict(valid_owner, start_ticks=-1), dict(valid_owner, boot_id="")):
            with self.subTest(owner=owner):
                state = dict(self.valid, transaction={"id": str(uuid.uuid4()), "operation": "set", "owner": owner})
                self.host.write(POWER.STATE, json.dumps(state))
                self.assertFalse(self.controller.status()["holding_now"])
                self.assertIn("Invalid managed state:", self.controller.status()["errors"][0])
                with self.assertRaises(POWER.PowerError):
                    self.controller.recover()
                self.assertEqual(json.loads(self.host.read(POWER.STATE)), state)

    def test_cli_status_exit_distinguishes_errors_from_healthy_unmanaged_state(self):
        for state, expected_exit in ((self.valid, 0), (dict(self.valid, last_apply={"success": "false"}), 1),
                                     (dict(self.valid, last_apply=None), 1), (None, 0)):
            with self.subTest(state=state):
                if state is None:
                    self.controller.clear()
                else:
                    self.host.write(POWER.STATE, json.dumps(state))
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(POWER, "PowerController", return_value=self.controller), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    result = POWER.main(["status"])
                status = json.loads(stdout.getvalue())
                self.assertEqual(result, expected_exit)
                self.assertEqual(bool(status["errors"]), expected_exit == 1)
                self.assertEqual(stderr.getvalue(), "")

    def test_valid_persisted_state_still_holds_and_applies(self):
        self.assertTrue(self.controller.status()["holding_now"])
        with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
            receipt = self.controller.apply()
        writes.assert_not_called()
        self.assertIs(receipt["success"], True)
        self.assertTrue(self.controller.status()["holding_now"])
        self.controller.clear()
        self.assertFalse(self.controller.status()["managed"])

    def test_failed_apply_receipt_and_staged_state_are_valid_but_not_holding(self):
        for receipt in (None, {"version": 1, "operation": "apply", "success": False,
                               "error": "injected failure", "writes": [], "transaction": None,
                               "time": 0}):
            with self.subTest(receipt=receipt):
                self.host.write(POWER.STATE, json.dumps(dict(self.valid, last_apply=receipt)))
                self.assertIsNotNone(self.controller.load_state())
                status = self.controller.status()
                self.assertFalse(status["holding_now"])
                self.assertIn("Latest apply has not succeeded", status["errors"])


class PassiveTemperatureTarget(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="passive-target-")
        self.addCleanup(self.temporary.cleanup)
        self.host = FakeHost(self, self.temporary.name)
        self.controller = self.host.controller
        self.host.write("/sys/class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
        self.host.write("/sys/class/thermal/thermal_zone0/temp", "65000\n")

    def state(self):
        return json.loads(self.host.read(POWER.STATE))

    def test_90_target_at_35_and_55_w_keeps_paired_range_and_native_fallback_bindings(self):
        for watts in (55, 35):
            with self.subTest(watts=watts):
                status = self.controller.set_limit(watts, target_celsius=90)
                self.assertTrue(status["holding_now"])
                self.assertEqual(status["desired_temperature_celsius"], 90)
                platform = ET.fromstring(self.host.read(POWER.XML)).find("Platform")
                trips = platform.findall("ThermalZones/ThermalZone/TripPoints/TripPoint")
                self.assertEqual(len(trips), 1)
                self.assertEqual(platform.findtext("ThermalZones/ThermalZone/Type"), "cpu")
                trip = trips[0]
                self.assertEqual({k: trip.findtext(k) for k in
                                  ("SensorType", "Temperature", "Hyst", "type", "ControlType")},
                                 {"SensorType": "x86_pkg_temp", "Temperature": "90000", "Hyst": "3000",
                                  "type": "passive", "ControlType": "SEQUENTIAL"})
                devices = trip.findall("CoolingDevice")
                self.assertEqual([d.findtext("type") for d in devices],
                                 ["rapl_controller", "intel_pstate", "intel_powerclamp", "cpufreq", "Processor"])
                for device in devices:
                    self.assertEqual({e.tag: e.text for e in device},
                                     {"type": device.findtext("type"), "influence": "0", "SamplingPeriod": "0"})
                for device in platform.findall("CoolingDevices/CoolingDevice"):
                    self.assertEqual(device.findtext("MinState"), str(watts * 1_000_000))
                    self.assertEqual(device.findtext("MaxState"), str(watts * 500_000))
                self.assertEqual(self.state()["target_celsius"], 90)
                self.assertIn("--loglevel=info", self.host.read(POWER.DROPIN))
                self.assertIn("--loglevel=info", status["thermald"]["ExecStart"])

    def test_set_without_target_restores_original_xml_bytes_and_clear_removes_policy(self):
        self.controller.set_limit(55, target_celsius=90)
        status = self.controller.set_limit(55)
        self.assertIsNone(status["desired_temperature_celsius"])
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), self.controller.xml(55_000_000, "ENERGY_CONSERVE"))
        self.assertEqual(self.host.path(POWER.DROPIN).read_bytes(), self.controller.dropin())
        self.assertNotIn("--loglevel", self.host.read(POWER.DROPIN))
        self.controller.set_limit(55, target_celsius=90)
        self.controller.clear()
        self.assertFalse(self.controller.status()["managed"])
        self.assertIsNone(self.controller.status()["desired_temperature_celsius"])
        self.assertFalse(self.host.path(POWER.XML).exists())

    def test_failed_restart_restores_previous_90_target_and_xml(self):
        self.controller.set_limit(55, target_celsius=90)
        previous = self.host.path(POWER.XML).read_bytes()
        self.host.restart_failures = [True, False]
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(35)
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), previous)
        self.assertEqual(self.state()["target_celsius"], 90)
        self.assertEqual(self.controller.status()["desired_temperature_celsius"], 90)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_failed_90_activation_restores_old_version1_without_target(self):
        self.controller.set_limit(55)
        state = self.state()
        state.pop("target_celsius")
        self.host.write(POWER.STATE, json.dumps(state))
        self.assertTrue(self.controller.status()["holding_now"])
        self.host.restart_failures = [True, False]
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(35, target_celsius=90)
        self.assertNotIn("target_celsius", self.state())
        self.assertTrue(self.controller.status()["holding_now"])
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), self.controller.xml(55_000_000, "ENERGY_CONSERVE"))

    def test_interrupted_set_accepts_prior_90_xml_hash_for_recovery(self):
        self.controller.set_limit(55, target_celsius=90)
        previous_xml = self.host.path(POWER.XML).read_bytes()
        previous_dropin = self.host.path(POWER.DROPIN).read_bytes()
        context = {}
        self.controller._stage_set(35, str(uuid.uuid4()), context)
        state = self.state()
        self.assertEqual(state["transaction"]["prior_target_celsius"], 90)
        self.host.path(POWER.XML).write_bytes(previous_xml)
        self.host.path(POWER.DROPIN).write_bytes(previous_dropin)
        identity = self.host.env.process_identity
        with mock.patch.object(self.host.env, "process_identity", side_effect=lambda pid=None: identity() if pid is None else None):
            receipt = self.controller.recover()
        self.assertTrue(receipt["success"])
        self.assertFalse(self.controller.status()["managed"])

    def test_corrupt_target_or_prior_target_blocks_every_mutation(self):
        self.controller.set_limit(55, target_celsius=90)
        original = self.state()
        for target in (True, False, 89, 91, 90.0, "90", {}, []):
            for prior in (False, True):
                with self.subTest(target=target, prior=prior):
                    value = json.loads(json.dumps(original))
                    if prior:
                        value["transaction"] = {"id": "pending", "operation": "set", "owner": self.host.env.process_identity(),
                                                "prior_cap_uw": 55_000_000, "prior_managed_hashes": value["managed_hashes"],
                                                "prior_target_celsius": target}
                    else:
                        value["target_celsius"] = target
                    self.host.write(POWER.STATE, json.dumps(value))
                    before = {p: self.host.path(p).read_bytes() for p in (POWER.STATE, POWER.XML, POWER.DROPIN)}
                    for operation in (lambda: self.controller.set_limit(55), self.controller.apply,
                                      self.controller.clear, self.controller.recover):
                        with self.assertRaises(POWER.PowerError):
                            operation()
                    self.assertEqual(before, {p: self.host.path(p).read_bytes() for p in before})

    def test_foreign_user_overrides_and_dangling_symlinks_are_preserved(self):
        for override in POWER.CPU_TARGET_OVERRIDES:
            for symlink in (False, True):
                with self.subTest(path=override, symlink=symlink):
                    path = self.host.path(override)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if symlink:
                        path.symlink_to("missing-foreign-target")
                    else:
                        path.write_text("97000\n")
                    with self.assertRaisesRegex(POWER.PowerError, "Foreign CPU temperature"):
                        self.controller.set_limit(55, target_celsius=90)
                    self.assertTrue(os.path.lexists(path))
                    self.assertFalse(self.host.path(POWER.STATE).exists())
                    path.unlink()

    def test_invalid_target_rejected_before_state_or_service_change(self):
        for value in (True, "90", 89, 91, 0, 125, 90.0):
            with self.subTest(value=value):
                before = list(self.host.commands)
                with self.assertRaises(ValueError):
                    self.controller.set_limit(55, target_celsius=value)
                self.assertEqual(before, self.host.commands)
                self.assertFalse(self.host.path(POWER.STATE).exists())

    def test_native_sensor_must_exist_be_unique_readable_and_in_range(self):
        sensor = self.host.path("/sys/class/thermal/thermal_zone0")
        for value in ("-1", "125001", "unknown"):
            (sensor / "temp").write_text(value)
            with self.assertRaises(POWER.PowerError):
                self.controller.set_limit(55, target_celsius=90)
        (sensor / "temp").write_text("65000")
        (sensor / "type").write_text("other")
        with self.assertRaisesRegex(POWER.PowerError, "Exactly one"):
            self.controller.set_limit(55, target_celsius=90)
        (sensor / "type").write_text("x86_pkg_temp")
        self.host.write("/sys/class/thermal/thermal_zone1/type", "x86_pkg_temp")
        self.host.write("/sys/class/thermal/thermal_zone1/temp", "65000")
        with self.assertRaisesRegex(POWER.PowerError, "Exactly one"):
            self.controller.set_limit(55, target_celsius=90)
        self.assertFalse(self.host.path(POWER.STATE).exists())

    def test_additional_native_cpu_sensor_is_rejected_before_xml_changes(self):
        for name in ("pkg-temp-0", "soc_dts0"):
            self.host.write("/sys/class/thermal/thermal_zone1/type", name)
            self.host.write("/sys/class/thermal/thermal_zone1/temp", "65000")
            with self.assertRaisesRegex(POWER.PowerError, "Additional native CPU sensor"):
                self.controller.set_limit(55, target_celsius=90)
        self.assertFalse(self.host.path(POWER.STATE).exists())

    def test_shipped_stock_order_with_comments_and_formatting_is_accepted_unchanged(self):
        stock = "<!-- Default native CPU cooling order -->\n<CoolingDeviceOrder>\n\t<!-- Order -->\n" + "".join(
            "\t<CoolingDevice>" + name + "</CoolingDevice>\n" for name in POWER.CPU_COOLING_DEVICES) + "</CoolingDeviceOrder>\n"
        self.host.write(POWER.CPU_COOLING_ORDER, stock)
        self.assertTrue(self.controller.set_limit(55, target_celsius=90)["holding_now"])
        self.assertEqual(self.host.read(POWER.CPU_COOLING_ORDER), stock)
        self.controller.clear()
        self.assertEqual(self.host.read(POWER.CPU_COOLING_ORDER), stock)

    def test_custom_or_unsafe_cooling_order_is_refused_without_overwriting(self):
        stock = "<CoolingDeviceOrder>" + "".join("<CoolingDevice>" + name + "</CoolingDevice>"
                for name in POWER.CPU_COOLING_DEVICES) + "</CoolingDeviceOrder>"
        bad = [stock.replace("rapl_controller", "other"),
               stock.replace("rapl_controller", "intel_pstate", 1),
               stock.replace("rapl_controller</", "rapl_controller </"),
               stock.replace("<CoolingDevice>cpufreq</CoolingDevice>", ""),
               stock.replace("</CoolingDeviceOrder>", "<CoolingDevice>extra</CoolingDevice></CoolingDeviceOrder>"),
               stock.replace("<CoolingDeviceOrder>", '<CoolingDeviceOrder mode="custom">'),
               stock.replace("<CoolingDevice>", '<CoolingDevice attr="x">', 1),
               stock.replace("rapl_controller", "<unknown>rapl_controller</unknown>"),
               stock.replace("CoolingDeviceOrder", "OtherRoot"),
               "<!DOCTYPE CoolingDeviceOrder>" + stock,
               '<!DOCTYPE CoolingDeviceOrder [<!ENTITY device "rapl_controller">]>' + stock,
               stock.replace("<CoolingDeviceOrder>", "<CoolingDeviceOrder>unrecognized-text")]
        for value in bad:
            with self.subTest(value=value):
                self.host.write(POWER.CPU_COOLING_ORDER, value)
                with self.assertRaises(POWER.PowerError):
                    self.controller.set_limit(55, target_celsius=90)
                self.assertEqual(self.host.read(POWER.CPU_COOLING_ORDER), value)
                self.assertFalse(self.host.path(POWER.STATE).exists())
        self.host.path(POWER.CPU_COOLING_ORDER).unlink()
        self.host.path(POWER.CPU_COOLING_ORDER).symlink_to("missing-native-order")
        with self.assertRaises(POWER.PowerError):
            self.controller.set_limit(55, target_celsius=90)
        self.assertTrue(self.host.path(POWER.CPU_COOLING_ORDER).is_symlink())

    def test_cli_target_option_reaches_the_transaction_and_defaults_to_none(self):
        for args, expected in ((["set", "55", "--target-celsius", "90"], 90), (["set", "55"], None)):
            with mock.patch.object(POWER, "PowerController", return_value=self.controller), mock.patch("sys.stdout"):
                self.assertEqual(POWER.main(args), 0)
            self.assertEqual(self.controller.status()["desired_temperature_celsius"], expected)


class PassivePollingInterval(unittest.TestCase):
    setUp = PassiveTemperatureTarget.setUp
    state = PassiveTemperatureTarget.state

    def test_absent_polling_keeps_preexisting_native_and_r9_target_xml_hashes(self):
        self.assertEqual(POWER.digest(self.controller.xml(55_000_000, "ENERGY_CONSERVE")),
                         "df2e2c43d6b5a866d3780a326cdc7450aea07a4e0e9716e1fc912f811c6191c8")
        self.assertEqual(POWER.digest(self.controller.xml(55_000_000, "ENERGY_CONSERVE", 90)),
                         "61a1a9f15821804d11a3781d21491287805413a3845453ceeb2f90fc3fd8b28e")

    def test_one_second_polling_changes_only_platform_interval_and_reports_desired_value(self):
        baseline = self.controller.xml(55_000_000, "ENERGY_CONSERVE", 90)
        status = self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        self.assertTrue(status["holding_now"])
        self.assertEqual(status["desired_polling_seconds"], 1)
        self.assertEqual(self.state()["polling_seconds"], 1)
        root = ET.fromstring(self.host.read(POWER.XML))
        platform = root.find("Platform")
        self.assertEqual(platform.findtext("PollingInterval"), "1")
        platform.remove(platform.find("PollingInterval"))
        # Whitespace after removing a node differs; compare complete XML
        # structure to confirm sensor, bindings, hysteresis and ranges unchanged.
        def shape(node):
            return (node.tag, node.attrib, (node.text or "").strip(), [shape(n) for n in node])
        self.assertEqual(shape(root), shape(ET.fromstring(baseline)))
        self.assertEqual(self.host.path(POWER.DROPIN).read_bytes(), self.controller.dropin(90))

    def test_legacy_90_missing_polling_field_keeps_xml_and_survives_enable_disable(self):
        self.controller.set_limit(55, target_celsius=90)
        value = self.state()
        value.pop("polling_seconds")
        self.host.write(POWER.STATE, json.dumps(value))
        before = self.host.path(POWER.XML).read_bytes()
        self.assertTrue(self.controller.status()["holding_now"])
        self.assertIsNone(self.controller.status()["desired_polling_seconds"])
        self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        status = self.controller.set_limit(55, target_celsius=90)
        self.assertIsNone(status["desired_polling_seconds"])
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), before)
        self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        status = self.controller.set_limit(55)
        self.assertIsNone(status["desired_temperature_celsius"])
        self.assertIsNone(status["desired_polling_seconds"])
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), self.controller.xml(55_000_000, "ENERGY_CONSERVE"))

    def test_failed_restart_restores_legacy90_or_polling90_exact_previous_bytes(self):
        for polling in (None, 1):
            self.controller.set_limit(55, target_celsius=90, polling_seconds=polling)
            value = self.state()
            if polling is None:
                value.pop("polling_seconds")
                self.host.write(POWER.STATE, json.dumps(value))
            before = {p: self.host.path(p).read_bytes() for p in (POWER.XML, POWER.DROPIN)}
            self.host.restart_failures = [True, False]
            with self.assertRaises(POWER.PowerError):
                self.controller.set_limit(35, target_celsius=90, polling_seconds=1 if polling is None else None)
            self.assertEqual(before, {p: self.host.path(p).read_bytes() for p in before})
            self.assertEqual(self.controller.status()["desired_polling_seconds"], polling)
            self.assertTrue(self.controller.status()["holding_now"])

    def test_interrupted_transaction_validates_prior_polling_xml_and_recovers_stock(self):
        self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        before = self.host.path(POWER.XML).read_bytes()
        self.controller._stage_set(35, str(uuid.uuid4()), {}, target_celsius=90)
        self.assertEqual(self.state()["transaction"]["prior_polling_seconds"], 1)
        self.host.path(POWER.XML).write_bytes(before)
        identity = self.host.env.process_identity
        with mock.patch.object(self.host.env, "process_identity", side_effect=lambda pid=None: identity() if pid is None else None):
            self.assertTrue(self.controller.recover()["success"])
        self.assertFalse(self.controller.status()["managed"])

    def test_clear_restores_stock_after_polling90(self):
        self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        self.assertTrue(self.controller.clear()["success"])
        self.assertFalse(self.controller.status()["managed"])
        self.assertFalse(self.host.path(POWER.XML).exists())

    def test_invalid_polling_and_missing_target_reject_before_mutation(self):
        for polling, target in ((True, 90), (False, 90), (1.0, 90), ("1", 90), (0, 90), (2, 90), (1, None)):
            with self.subTest(polling=polling, target=target):
                with self.assertRaises(ValueError):
                    self.controller.set_limit(55, target_celsius=target, polling_seconds=polling)
                self.assertFalse(self.host.path(POWER.STATE).exists())
        self.assertEqual(self.host.commands, [])

    def test_corrupt_current_or_prior_polling_blocks_all_mutations(self):
        self.controller.set_limit(55, target_celsius=90, polling_seconds=1)
        original = self.state()
        for polling in (True, 1.0, "1", 0, 2, {}):
            for prior in (False, True):
                value = json.loads(json.dumps(original))
                if prior:
                    value["transaction"] = {"id": "pending", "operation": "set", "owner": self.host.env.process_identity(),
                                            "prior_cap_uw": 55_000_000, "prior_target_celsius": 90,
                                            "prior_polling_seconds": polling, "prior_managed_hashes": value["managed_hashes"]}
                else:
                    value["polling_seconds"] = polling
                self.host.write(POWER.STATE, json.dumps(value))
                before = {p: self.host.path(p).read_bytes() for p in (POWER.STATE, POWER.XML, POWER.DROPIN)}
                for operation in (lambda: self.controller.set_limit(55), self.controller.apply,
                                  self.controller.clear, self.controller.recover):
                    with self.assertRaises(POWER.PowerError):
                        operation()
                self.assertEqual(before, {p: self.host.path(p).read_bytes() for p in before})

    def test_cli_explicit_polling_option_reaches_transaction(self):
        with mock.patch.object(POWER, "PowerController", return_value=self.controller), mock.patch("sys.stdout"):
            self.assertEqual(POWER.main(["set", "55", "--target-celsius", "90", "--polling-seconds", "1"]), 0)
        self.assertEqual(self.controller.status()["desired_polling_seconds"], 1)


class RaplDebounceInterval(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost(self)
        self.controller = self.host.controller
        self.host.write("/sys/class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
        self.host.write("/sys/class/thermal/thermal_zone0/temp", "65000\n")

    state = PassiveTemperatureTarget.state

    def fast(self, watts=55):
        return self.controller.set_limit(watts, target_celsius=90, polling_seconds=1,
                                         rapl_debounce_seconds=0)

    def test_absent_debounce_preserves_frozen_r10_xml_digest(self):
        self.assertEqual(POWER.digest(self.controller.xml(55_000_000, "ENERGY_CONSERVE", 90, 1)),
                         "e36b5396c4cf15d04ec46dd96f0f4215b98bd313b43ebd063032ad336419d2ea")

    def test_failed_clear_restores_explicit_zero_configuration(self):
        self.fast()
        before = self.host.path(POWER.XML).read_bytes()
        self.host.restart_failures = [True, False]
        with self.assertRaises(POWER.PowerError):
            self.controller.clear()
        self.assertEqual(self.host.path(POWER.XML).read_bytes(), before)
        self.assertEqual(self.controller.status()["desired_rapl_debounce_seconds"], 0)
        self.assertTrue(self.controller.status()["holding_now"])

    def test_zero_option_still_rejects_unqualified_host_before_staging(self):
        self.host.write("/sys/class/dmi/id/bios_version", "foreign BIOS\n")
        with self.assertRaises(POWER.PowerError):
            self.fast()
        self.assertFalse(self.host.path(POWER.STATE).exists())
        self.assertFalse(self.host.path(POWER.XML).exists())

    def test_zero_changes_only_bound_msr_device_and_reports_explicit_value(self):
        baseline = ET.fromstring(self.controller.xml(55_000_000, "ENERGY_CONSERVE", 90, 1))
        result = self.fast()
        self.assertTrue(result["holding_now"])
        self.assertEqual(result["desired_rapl_debounce_seconds"], 0)
        actual = ET.fromstring(self.host.read(POWER.XML))
        devices = actual.findall("Platform/CoolingDevices/CoolingDevice")
        self.assertEqual([(d.findtext("Type"), d.findtext("DebouncePeriod")) for d in devices],
                         [("rapl_controller", "0"), ("rapl_controller_mmio", None)])
        devices[0].remove(devices[0].find("DebouncePeriod"))
        def shape(node):
            return (node.tag, node.attrib, (node.text or "").strip(), [shape(n) for n in node])
        self.assertEqual(shape(actual), shape(baseline))

    def test_old_r8_r9_r10_states_load_and_enable_disable_preserves_exact_xml(self):
        for target, polling in ((None, None), (90, None), (90, 1)):
            with self.subTest(target=target, polling=polling):
                self.controller.set_limit(55, target_celsius=target, polling_seconds=polling)
                value = self.state()
                value.pop("rapl_debounce_seconds")
                self.host.write(POWER.STATE, json.dumps(value))
                original = self.host.path(POWER.XML).read_bytes()
                self.assertTrue(self.controller.status()["holding_now"])
                self.assertIsNone(self.controller.status()["desired_rapl_debounce_seconds"])
                self.fast()
                result = self.controller.set_limit(55, target_celsius=target, polling_seconds=polling)
                self.assertIsNone(result["desired_rapl_debounce_seconds"])
                self.assertEqual(self.host.path(POWER.XML).read_bytes(), original)

    def test_restart_failure_restores_both_native_and_zero_debounce_policy(self):
        for prior in (None, 0):
            with self.subTest(prior=prior):
                self.controller.set_limit(55, target_celsius=90, polling_seconds=1, rapl_debounce_seconds=prior)
                files = {p: self.host.path(p).read_bytes() for p in (POWER.XML, POWER.DROPIN)}
                self.host.restart_failures = [True, False]
                with self.assertRaises(POWER.PowerError):
                    self.controller.set_limit(35, target_celsius=90, polling_seconds=1,
                                              rapl_debounce_seconds=0 if prior is None else None)
                self.assertEqual(files, {p: self.host.path(p).read_bytes() for p in files})
                self.assertEqual(self.controller.status()["desired_rapl_debounce_seconds"], prior)
                self.assertTrue(self.controller.status()["holding_now"])

    def test_pending_prior_zero_xml_is_validated_and_recovered_without_upward_write(self):
        self.fast()
        old_xml = self.host.path(POWER.XML).read_bytes()
        self.controller._stage_set(35, str(uuid.uuid4()), {}, target_celsius=90, polling_seconds=1)
        self.assertEqual(self.state()["transaction"]["prior_rapl_debounce_seconds"], 0)
        self.host.path(POWER.XML).write_bytes(old_xml)
        identity = self.host.env.process_identity
        with mock.patch.object(self.host.env, "process_identity", side_effect=lambda pid=None: identity() if pid is None else None), \
                mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
            self.assertTrue(self.controller.recover()["success"])
        writes.assert_not_called()
        self.assertFalse(self.controller.status()["managed"])

    def test_actual_sigkill_zero_debounce_transaction_recovers_stock(self):
        code = r'''
import os, signal, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_mechrevo_power import FakeHost
host = FakeHost(unittest.TestCase(), root=Path(sys.argv[1]))
host.write('/sys/class/thermal/thermal_zone0/type', 'x86_pkg_temp\n')
host.write('/sys/class/thermal/thermal_zone0/temp', '65000\n')
run = host.env.runner
def killed_at_restart(argv):
    if argv == ['systemctl', 'restart', 'thermald.service']:
        os.kill(os.getpid(), signal.SIGKILL)
    return run(argv)
host.env.runner = killed_at_restart
host.controller.set_limit(55, target_celsius=90, polling_seconds=1, rapl_debounce_seconds=0)
'''
        child = subprocess.run([sys.executable, "-B", "-c", code, str(self.host.root)],
                               cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stdout + child.stderr)
        self.assertEqual(self.state()["rapl_debounce_seconds"], 0)
        with mock.patch.object(self.host.env, "write_control", wraps=self.host.env.write_control) as writes:
            self.assertTrue(self.controller.recover()["success"])
        writes.assert_not_called()
        self.assertFalse(self.controller.status()["managed"])

    def test_clear_removes_zero_policy(self):
        self.fast()
        self.assertTrue(self.controller.clear()["success"])
        self.assertFalse(self.host.path(POWER.XML).exists())
        self.assertIsNone(self.controller.status()["desired_rapl_debounce_seconds"])

    def test_reject_nonzero_and_implicit_dependencies_before_any_change(self):
        cases = [(v, 90, 1) for v in (True, False, "0", 0.0, -1, 1, {}, [])]
        cases += [(0, None, None), (0, 90, None), (0, None, 1)]
        for seconds, target, polling in cases:
            with self.subTest(seconds=seconds, target=target, polling=polling):
                with self.assertRaises(ValueError):
                    self.controller.set_limit(55, target_celsius=target, polling_seconds=polling,
                                              rapl_debounce_seconds=seconds)
        self.assertFalse(self.host.path(POWER.STATE).exists())
        self.assertEqual(self.host.commands, [])

    def test_corrupt_current_and_prior_reject_all_mutations_without_overwrite(self):
        self.fast()
        original = self.state()
        for seconds in (True, False, "0", 0.0, -1, 1, {}, []):
            for prior in (False, True):
                with self.subTest(seconds=seconds, prior=prior):
                    value = json.loads(json.dumps(original))
                    if prior:
                        value["transaction"] = {"id": "pending", "operation": "set", "owner": self.host.env.process_identity(),
                                                "prior_cap_uw": 55_000_000, "prior_target_celsius": 90,
                                                "prior_polling_seconds": 1, "prior_rapl_debounce_seconds": seconds,
                                                "prior_managed_hashes": value["managed_hashes"]}
                    else:
                        value["rapl_debounce_seconds"] = seconds
                    self.host.write(POWER.STATE, json.dumps(value))
                    before = {p: self.host.path(p).read_bytes() for p in (POWER.STATE, POWER.XML, POWER.DROPIN)}
                    for operation in (lambda: self.controller.set_limit(55), self.controller.apply,
                                      self.controller.clear, self.controller.recover):
                        with self.assertRaises(POWER.PowerError):
                            operation()
                    self.assertEqual(before, {p: self.host.path(p).read_bytes() for p in before})

    def test_zero_requires_dependencies_in_stored_current_and_prior_records(self):
        self.fast()
        original = self.state()
        for prior in (False, True):
            for target, polling in ((None, None), (90, None)):
                value = json.loads(json.dumps(original))
                if prior:
                    value["transaction"] = {"id": "pending", "operation": "set", "owner": self.host.env.process_identity(),
                                            "prior_cap_uw": 55_000_000, "prior_target_celsius": target,
                                            "prior_polling_seconds": polling, "prior_rapl_debounce_seconds": 0,
                                            "prior_managed_hashes": value["managed_hashes"]}
                else:
                    value.update(target_celsius=target, polling_seconds=polling)
                self.host.write(POWER.STATE, json.dumps(value))
                with self.assertRaises(POWER.PowerError):
                    self.controller.load_state()

    def test_cli_requires_explicit_dependencies_and_applies_zero(self):
        with mock.patch.object(POWER, "PowerController", return_value=self.controller), mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(POWER.main(["set", "55", "--rapl-debounce-seconds", "0"]), 1)
            self.assertEqual(POWER.main(["set", "55", "--target-celsius", "90", "--polling-seconds", "1",
                                         "--rapl-debounce-seconds", "0"]), 0)
        self.assertEqual(self.controller.status()["desired_rapl_debounce_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
