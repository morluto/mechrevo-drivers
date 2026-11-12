"""Regression tests for the physical performance-mode cycle."""
import importlib.util
import errno
import fcntl
import io
import json
import os
from pathlib import Path
import select
import struct
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "mechrevo_control.py"


def load_control_module():
    spec = importlib.util.spec_from_file_location("mechrevo_control_under_test", SOURCE)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


control = load_control_module()


class PerformanceModeCycleTests(unittest.TestCase):
    def call_with_profile(self, profile_id):
        with mock.patch.object(control, "get_current_mode_info", return_value=("", profile_id)), \
                mock.patch.object(control, "set_mode") as set_mode:
            result = control.cycle_mode(notify=False)
        return result, set_mode

    def test_office_advances_to_gaming(self):
        result, set_mode = self.call_with_profile("mechrevo_office")
        self.assertEqual(result, "gaming")
        set_mode.assert_called_once_with("gaming", notify=False)

    def test_gaming_advances_to_turbo(self):
        result, set_mode = self.call_with_profile("mechrevo_gaming")
        self.assertEqual(result, "turbo")
        set_mode.assert_called_once_with("turbo", notify=False)

    def test_gaming_quiet_advances_to_turbo(self):
        result, set_mode = self.call_with_profile("mechrevo_gaming_quiet")
        self.assertEqual(result, "turbo")
        set_mode.assert_called_once_with("turbo", notify=False)

    def test_turbo_wraps_back_to_office(self):
        result, set_mode = self.call_with_profile("mechrevo_turbo")
        self.assertEqual(result, "office")
        set_mode.assert_called_once_with("office", notify=False)

    def test_software_variants_advance_from_their_hardware_step(self):
        for profile, expected in (("__default_custom_profile__", "turbo"),
                                  ("mechrevo_fan_boost", "office")):
            with self.subTest(profile=profile):
                result, set_mode = self.call_with_profile(profile)
                self.assertEqual(result, expected)
                set_mode.assert_called_once_with(expected, notify=False)

    def test_unknown_profile_falls_back_to_gaming(self):
        result, set_mode = self.call_with_profile("some-user-profile")
        self.assertEqual(result, "gaming")
        set_mode.assert_called_once_with("gaming", notify=False)


class HardwareCycleBoundaryTests(unittest.TestCase):
    """Exercise the real cycle and switch functions at their DBus/ioctl edges."""

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.active_id = "mechrevo_office"
        self.raw_mode = 0xa0
        self.writes = []
        self.requests = []
        stack.enter_context(mock.patch.object(control, "sync_oem_profiles"))
        self.bus = stack.enter_context(mock.patch.object(control, "call_tccd_dbus", side_effect=self.dbus))
        stack.enter_context(mock.patch.object(Path, "exists", return_value=True))
        stack.enter_context(mock.patch.object(control.os, "open", return_value=7))
        self.close = stack.enter_context(mock.patch.object(control.os, "close"))
        self.ioctl = stack.enter_context(mock.patch.object(control.fcntl, "ioctl", side_effect=self.mode_ioctl))
        self.notify = stack.enter_context(mock.patch.object(control, "send_notification"))
        self.output = stack.enter_context(redirect_stdout(io.StringIO()))

    def dbus(self, method, *arguments):
        if method == "GetActiveProfileJSON":
            profile = {"id": self.active_id, "name": self.active_id}
            return json.dumps({"type": "s", "data": [json.dumps(profile)]})
        self.assertEqual(method, "SetTempProfileById")
        self.assertEqual(arguments[0], "s")
        self.active_id = arguments[1]
        self.requests.append(self.active_id)
        return '{"type":"b","data":[true]}'

    def mode_ioctl(self, fd, command, argument, *_):
        self.assertEqual(fd, 7)
        if command == 0x4008F012:
            self.raw_mode = struct.unpack("i", argument)[0]
            self.writes.append(self.raw_mode)
        else:
            self.assertEqual(command, 0x8008EF14)
            argument[:4] = struct.pack("i", self.raw_mode)
        return 0

    def test_complete_cycle_requests_three_distinct_hardware_modes(self):
        result = [control.cycle_mode(notify=True) for _ in range(3)]
        self.assertEqual(result, ["gaming", "turbo", "office"])
        self.assertEqual(self.requests, ["mechrevo_gaming", "mechrevo_turbo", "mechrevo_office"])
        self.assertEqual(self.writes, [0x00, 0x10, 0xa0])
        self.assertEqual(self.active_id, "mechrevo_office")
        self.assertEqual(self.notify.call_count, 3)
        self.assertEqual(self.close.call_count, 3)

    def test_variants_do_not_repeat_the_same_hardware_mode(self):
        for profile, expected_id, raw in (("mechrevo_gaming_quiet", "mechrevo_turbo", 0x10),
                                          ("__default_custom_profile__", "mechrevo_turbo", 0x10),
                                          ("mechrevo_fan_boost", "mechrevo_office", 0xa0)):
            with self.subTest(profile=profile):
                self.active_id = profile
                control.cycle_mode(notify=False)
                self.assertEqual(self.active_id, expected_id)
                self.assertEqual(self.writes[-1], raw)
        self.notify.assert_not_called()

    def test_profile_read_failure_does_not_select_a_fallback_or_announce_success(self):
        self.bus.side_effect = OSError("profile read disconnected")
        with self.assertRaisesRegex(OSError, "profile read disconnected"):
            control.cycle_mode(notify=True)
        self.assertEqual(self.requests, [])
        self.ioctl.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())

    def test_rejected_switch_does_not_write_hardware_or_announce_success(self):
        def reject(method, *arguments):
            if method == "SetTempProfileById":
                return '{"type":"b","data":[false]}'
            return self.dbus(method, *arguments)
        self.bus.side_effect = reject
        with self.assertRaisesRegex(RuntimeError, "did not accept"):
            control.cycle_mode(notify=True)
        self.assertEqual(self.active_id, "mechrevo_office")
        self.ioctl.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())

    def test_hardware_failure_closes_device_and_does_not_announce_success(self):
        self.ioctl.side_effect = OSError("mode write failed")
        with self.assertRaisesRegex(OSError, "mode write failed"):
            control.cycle_mode(notify=True)
        self.close.assert_called_once_with(7)
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())


class ControlFailureTests(unittest.TestCase):
    def test_dbus_transport_failure_is_not_replaced_by_default_mode(self):
        with mock.patch.object(control, "call_tccd_dbus", side_effect=OSError("bus down")), \
                self.assertRaises(OSError):
            control.get_current_mode_info()

    def test_malformed_dbus_profile_is_rejected(self):
        with mock.patch.object(control, "call_tccd_dbus", return_value="{}"), \
                self.assertRaisesRegex(RuntimeError, "no active profile"):
            control.get_current_mode_info()

    def test_mode_ioctl_failure_is_raised_and_fd_is_closed(self):
        with mock.patch.object(control.os, "open", return_value=7), \
                mock.patch.object(control.os, "close") as close, \
                mock.patch.object(control.fcntl, "ioctl", side_effect=OSError("ioctl failed")), \
                self.assertRaises(OSError):
            control.set_hardware_mode_led("gaming")
        close.assert_called_once_with(7)

    def test_mode_readback_mismatch_is_not_reported_as_success(self):
        def ioctl(_fd, command, argument, *_):
            if command == 0x8008EF14:
                argument[:4] = struct.pack("i", 0x10)
            return 0

        with mock.patch.object(control.os, "open", return_value=7), \
                mock.patch.object(control.os, "close") as close, \
                mock.patch.object(control.fcntl, "ioctl", side_effect=ioctl), \
                self.assertRaisesRegex(RuntimeError, "readback mismatch"):
            control.set_hardware_mode_led("gaming")
        close.assert_called_once_with(7)

    def test_gaming_quiet_uses_the_gaming_hardware_mode_request(self):
        def ioctl(_fd, command, argument, *_):
            if command == 0x8008EF14:
                argument[:4] = struct.pack("i", 0)
            return 0

        with mock.patch.object(control.os, "open", return_value=7), \
                mock.patch.object(control.os, "close"), \
                mock.patch.object(control.fcntl, "ioctl", side_effect=ioctl):
            control.set_hardware_mode_led("gaming-quiet")

    def test_notification_failure_is_visible(self):
        with mock.patch.object(control.shutil, "which", return_value=None), \
                self.assertRaisesRegex(RuntimeError, "notify-send"):
            control.send_notification("title", "message")




class ConfirmedProfileTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(control, "sync_oem_profiles"))
        self.bus = self.stack.enter_context(mock.patch.object(control, "call_tccd_dbus",
                                                              return_value='{"type":"b","data":[true]}'))
        self.active = self.stack.enter_context(mock.patch.object(control, "get_current_mode_info",
                                                                 return_value=("Gaming Quiet", "mechrevo_gaming_quiet")))
        self.led = self.stack.enter_context(mock.patch.object(control, "set_hardware_mode_led"))
        self.notify = self.stack.enter_context(mock.patch.object(control, "send_notification"))
        self.sleep = self.stack.enter_context(mock.patch.object(control.time, "sleep"))
        self.output = self.stack.enter_context(redirect_stdout(io.StringIO()))

    def test_quiet_mode_confirms_profile_before_lamp_or_success_notification(self):
        events = []
        profiles = iter([("Gaming", "mechrevo_gaming"), ("Quiet", "mechrevo_gaming_quiet")])
        def active():
            value = next(profiles)
            events.append(value[1])
            return value
        self.active.side_effect = active
        self.led.side_effect = lambda mode: events.append("led:" + mode)
        control.set_mode("gaming-quiet", notify=True)
        self.bus.assert_called_once_with("SetTempProfileById", "s", "mechrevo_gaming_quiet")
        self.assertEqual(events, ["mechrevo_gaming", "mechrevo_gaming_quiet", "led:gaming-quiet"])
        self.notify.assert_called_once()
        self.assertIn("[✓]", self.output.getvalue())

    def test_mode_notifications_do_not_invent_watts_or_achieved_rpm(self):
        for mode, profile in (('office', 'mechrevo_office'),
                              ('gaming', 'mechrevo_gaming'),
                              ('gaming-quiet', 'mechrevo_gaming_quiet'),
                              ('turbo', 'mechrevo_turbo'),
                              ('boost', 'mechrevo_fan_boost')):
            with self.subTest(mode=mode):
                self.active.return_value = ('Saved custom parameters', profile)
                control.set_mode(mode, notify=True)
                message = self.notify.call_args.args[1]
                self.assertIn('保存', message)
                for unsupported in ('45W', '75W', '130W', '100% 满转速'):
                    self.assertNotIn(unsupported, message)

    def test_rejected_or_malformed_reply_never_writes_lamp_or_announces_success(self):
        for response in ('{"type":"b","data":[false]}', '{', '{}',
                         '{"type":"b","data":[1]}', '{"type":"s","data":[true]}'):
            with self.subTest(response=response):
                self.bus.return_value = response
                with self.assertRaises(RuntimeError):
                    control.set_mode("gaming-quiet", notify=True)
        self.active.assert_not_called()
        self.led.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())

    def test_profile_timeout_never_writes_lamp_or_announces_success(self):
        self.active.return_value = ("Gaming", "mechrevo_gaming")
        with mock.patch.object(control.time, "monotonic", side_effect=[10.0, 15.0]), \
                self.assertRaisesRegex(RuntimeError, "Timed out"):
            control.set_mode("gaming-quiet", notify=True)
        self.led.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())

    def test_profile_read_failure_is_propagated_before_lamp_or_success_notification(self):
        self.active.side_effect = OSError("bus disconnected")
        with self.assertRaisesRegex(OSError, "bus disconnected"):
            control.set_mode("gaming-quiet", notify=True)
        self.led.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())

    def test_switch_transport_failure_never_writes_lamp_or_announces_success(self):
        self.bus.side_effect = OSError("switch request disconnected")
        with self.assertRaisesRegex(OSError, "switch request disconnected"):
            control.set_mode("gaming-quiet", notify=True)
        self.active.assert_not_called()
        self.led.assert_not_called()
        self.notify.assert_not_called()
        self.assertNotIn("[✓]", self.output.getvalue())


class HotkeyStreamTests(unittest.TestCase):
    def run_pipe(self, payload, *, close_writer=False):
        reader, writer = os.pipe()
        self.addCleanup(os.close, reader)
        if payload:
            os.write(writer, payload)
        if close_writer:
            os.close(writer)
        else:
            self.addCleanup(os.close, writer)
        real_select = select.select
        def ready(readers, writers, errors, timeout):
            result = real_select(readers, writers, errors, 0)
            if not result[0]:
                raise AssertionError("The F6 event was buffered; no second input should be needed")
            return result
        def stream(_path, mode, **kwargs):
            return os.fdopen(os.dup(reader), mode, **kwargs)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(Path, "exists", return_value=True))
        stack.enter_context(mock.patch.object(control, "open", side_effect=stream, create=True))
        stack.enter_context(mock.patch.object(control, "sync_oem_profiles"))
        stack.enter_context(mock.patch.object(control, "sync_mode_led_from_profile", return_value="mechrevo_gaming"))
        stack.enter_context(mock.patch.object(select, "select", side_effect=ready))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack

    def test_one_complete_mode_chord_is_handled_without_a_later_input(self):
        class ModeHandled(Exception):
            pass
        chord = [(125, 1), (56, 1), (64, 1), (64, 0), (56, 0), (125, 0)]
        payload = b"".join(struct.pack("qqHHi", 0, 0, 1, code, value) for code, value in chord)
        self.run_pipe(payload)
        with mock.patch.object(control, "cycle_mode", side_effect=ModeHandled) as cycle, \
                self.assertRaises(ModeHandled):
            control.run_daemon()
        cycle.assert_called_once_with(notify=True)

    def test_eof_is_a_visible_device_failure(self):
        self.run_pipe(b"", close_writer=True)
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            control.run_daemon()

    def test_short_input_event_is_a_visible_failure(self):
        self.run_pipe(b"short", close_writer=True)
        with self.assertRaisesRegex(RuntimeError, "Incomplete hotkey input event"):
            control.run_daemon()


class EcOnlyModeCycleTests(unittest.TestCase):
    def setUp(self):
        self.read = mock.patch.object(control, "read_hardware_mode").start()
        self.addCleanup(mock.patch.stopall)
        self.write = mock.patch.object(control, "write_hardware_mode").start()

    def test_cycle_order_matches_the_tcc_profile_order(self):
        for current, expected_name, expected_value in ((0xa0, "gaming", 0x00),
                                                       (0x00, "turbo", 0x10),
                                                       (0x10, "office", 0xa0)):
            with self.subTest(current=hex(current)):
                self.read.return_value = current
                self.write.reset_mock()
                self.assertEqual(control.cycle_hardware_mode(), expected_name)
                self.write.assert_called_once_with(expected_value)

    def test_unknown_mode_requests_gaming_without_guessing(self):
        self.read.return_value = 0x77
        self.assertEqual(control.cycle_hardware_mode(), "gaming")
        self.write.assert_called_once_with(0x00)

    def test_read_failure_does_not_write(self):
        self.read.side_effect = OSError("mode read failed")
        with self.assertRaisesRegex(OSError, "mode read failed"):
            control.cycle_hardware_mode()
        self.write.assert_not_called()

    def test_write_failure_is_propagated(self):
        self.read.return_value = 0x00
        self.write.side_effect = RuntimeError("mode write failed")
        with self.assertRaisesRegex(RuntimeError, "mode write failed"):
            control.cycle_hardware_mode()


class EcOnlyHotkeyStreamTests(unittest.TestCase):
    def run_pipe(self, payload):
        reader, writer = os.pipe()
        self.addCleanup(os.close, reader)
        os.write(writer, payload)
        self.addCleanup(os.close, writer)
        real_select = select.select

        def ready(readers, writers, errors, timeout):
            result = real_select(readers, writers, errors, 0)
            if not result[0]:
                raise AssertionError("The EC-only F6 event was buffered")
            return result

        def stream(_path, mode, **kwargs):
            return os.fdopen(os.dup(reader), mode, **kwargs)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(Path, "exists", return_value=True))
        stack.enter_context(mock.patch.object(control, "open", side_effect=stream, create=True))
        self.read = stack.enter_context(mock.patch.object(control, "read_hardware_mode", return_value=0x00))
        self.sync_profiles = stack.enter_context(mock.patch.object(control, "sync_oem_profiles"))
        self.sync_led = stack.enter_context(mock.patch.object(control, "sync_mode_led_from_profile"))
        self.get_profile = stack.enter_context(mock.patch.object(control, "get_current_mode_info"))
        self.touchpad = stack.enter_context(mock.patch.object(control, "toggle_touchpad"))
        self.read_uefi = stack.enter_context(mock.patch.object(control, "read_uefi_power_mode", return_value=0))
        self.write_uefi = stack.enter_context(mock.patch.object(control, "write_uefi_power_mode"))
        self.apply_tdp = stack.enter_context(mock.patch.object(control, "apply_mode_tdp", return_value=(95, 95, 215)))
        stack.enter_context(mock.patch.object(select, "select", side_effect=ready))
        stack.enter_context(redirect_stdout(io.StringIO()))

    def test_ec_only_f6_uses_the_ec_path_and_never_calls_tccd(self):
        class ModeHandled(Exception):
            pass
        payload = b"".join(struct.pack("qqHHi", 0, 0, 1, code, value)
                           for code, value in [(125, 1), (56, 1), (64, 1)])
        self.run_pipe(payload)
        with mock.patch.object(control, "cycle_hardware_mode", side_effect=ModeHandled) as cycle:
            with self.assertRaises(ModeHandled):
                control.run_daemon(ec_only=True)
        cycle.assert_called_once_with()
        self.assertEqual(self.read.call_count, 2)
        self.sync_profiles.assert_not_called()
        self.sync_led.assert_not_called()
        self.get_profile.assert_not_called()

    def test_ec_only_persists_uefi_power_mode_after_the_ec_cycle(self):
        class Synced(BaseException):
            pass
        payload = b"".join(struct.pack("qqHHi", 0, 0, 1, code, value)
                           for code, value in [(64, 1)])
        self.run_pipe(payload)
        with mock.patch.object(control, "cycle_hardware_mode", return_value="turbo"):
            self.write_uefi.side_effect = Synced
            with self.assertRaises(Synced):
                control.run_daemon(ec_only=True)
        self.apply_tdp.assert_called_once_with("turbo")
        self.write_uefi.assert_called_once_with("turbo")
        self.read_uefi.assert_called_once_with()

    def test_ec_only_ignores_non_mode_keys(self):
        class ModeHandled(Exception):
            pass
        payload = b"".join(struct.pack("qqHHi", 0, 0, 1, code, value)
                           for code, value in [(191, 1), (191, 0), (64, 1)])
        self.run_pipe(payload)
        with mock.patch.object(control, "cycle_hardware_mode", side_effect=ModeHandled) as cycle:
            with self.assertRaises(ModeHandled):
                control.run_daemon(ec_only=True)
        cycle.assert_called_once_with()
        self.touchpad.assert_not_called()

    def test_ec_only_startup_requires_the_mode_device(self):
        self.run_pipe(b"")
        self.read.side_effect = OSError("control device unavailable")
        with self.assertRaisesRegex(OSError, "control device unavailable"):
            control.run_daemon(ec_only=True)
        self.sync_profiles.assert_not_called()


class UefiPowerModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "UniWillVariable"
        raw = bytearray(184)
        raw[:4] = b"\x07\x00\x00\x00"
        raw[0x56] = 0
        self.path.write_bytes(raw)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(control, "uefi_power_mode_supported", return_value=True))
        self.stack.enter_context(mock.patch.object(control, "UEFI_POWER_MODE_EFIVAR", self.path))
        self.immutable = self.stack.enter_context(
            mock.patch.object(control, "_efivar_immutable", return_value=False))
        self.set_immutable = self.stack.enter_context(
            mock.patch.object(control, "_set_efivar_immutable"))

    def test_reads_the_documented_power_mode_offset(self):
        for value in (0, 1, 2, 3):
            raw = bytearray(self.path.read_bytes())
            raw[0x56] = value
            self.path.write_bytes(raw)
            self.assertEqual(control.read_uefi_power_mode(), value)

    def test_unrelated_payload_change_is_rejected(self):
        real_write = control.os.write

        def mutate_after_write(fd, data):
            written = real_write(fd, data)
            raw = bytearray(self.path.read_bytes())
            raw[0x10] ^= 0x01
            self.path.write_bytes(raw)
            return written

        with mock.patch.object(control.os, "write", side_effect=mutate_after_write), \
                self.assertRaisesRegex(RuntimeError, "unrelated byte"):
            control.write_uefi_power_mode("turbo")

    def test_writes_only_the_power_mode_byte(self):
        raw = bytearray(self.path.read_bytes())
        raw[0x10] = 0xaa
        raw[0x57] = 0xbb
        self.path.write_bytes(raw)
        self.assertEqual(control.write_uefi_power_mode("office"), 1)
        actual = self.path.read_bytes()
        self.assertEqual(actual[:4], b"\x07\x00\x00\x00")
        self.assertEqual(actual[0x56], 1)
        self.assertEqual(actual[0x10], 0xaa)
        self.assertEqual(actual[0x57], 0xbb)
        self.assertEqual(len(actual), len(raw))

    def test_round_trips_all_ordinary_modes(self):
        for key, value in (("office", 1), ("gaming", 0), ("turbo", 2)):
            with self.subTest(key=key):
                self.assertEqual(control.write_uefi_power_mode(key), value)
                self.assertEqual(control.read_uefi_power_mode(), value)

    def test_immutable_flag_is_restored(self):
        self.immutable.return_value = True
        control.write_uefi_power_mode("turbo")
        self.assertEqual(self.set_immutable.call_args_list,
                         [mock.call(self.path, False), mock.call(self.path, True)])

    def test_unsupported_identity_does_not_touch_nvram(self):
        with mock.patch.object(control, "uefi_power_mode_supported", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "not supported"):
                control.write_uefi_power_mode("turbo")
        self.assertEqual(self.path.read_bytes()[0x56], 0)

    def test_short_variable_is_rejected(self):
        self.path.write_bytes(b"\x07\x00\x00\x00short")
        with self.assertRaisesRegex(RuntimeError, "too short"):
            control.write_uefi_power_mode("turbo")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown UEFI PowerMode"):
            control.write_uefi_power_mode("fan-boost")

    def test_efivarfs_fsync_einval_is_accepted(self):
        with mock.patch.object(control.os, "fsync",
                               side_effect=OSError(errno.EINVAL, "efivarfs fsync")):
            self.assertEqual(control.write_uefi_power_mode("turbo"), 2)
        self.assertEqual(self.path.read_bytes()[0x56], 2)

    def test_other_fsync_errors_are_visible(self):
        with mock.patch.object(control.os, "fsync",
                               side_effect=OSError(errno.EIO, "disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                control.write_uefi_power_mode("turbo")


class ModeTdpProfileTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(control.Path, "exists", return_value=True))
        self.stack.enter_context(mock.patch.object(control.os, "open", return_value=7))
        self.close = self.stack.enter_context(mock.patch.object(control.os, "close"))
        self.values = [0, 0, 0]
        self.writes = []
        self.ioctl = self.stack.enter_context(mock.patch.object(control.fcntl, "ioctl", side_effect=self.mode_ioctl))

    def mode_ioctl(self, fd, command, argument, *_):
        self.assertEqual(fd, 7)
        if command in control.W_UW_TDP:
            index = control.W_UW_TDP.index(command)
            self.values[index] = struct.unpack("i", argument)[0]
            self.writes.append((index, self.values[index]))
        else:
            index = control.R_UW_TDP.index(command)
            argument[:4] = struct.pack("i", self.values[index])
        return 0

    def test_each_package_profile_writes_and_reads_pl1_pl2_pl4(self):
        for mode, values in (("office", (35, 35, 215)),
                             ("gaming", (80, 80, 215)),
                             ("turbo", (95, 95, 215))):
            with self.subTest(mode=mode):
                self.values = [0, 0, 0]
                self.writes = []
                self.assertEqual(control.apply_mode_tdp(mode), values)
                self.assertEqual(tuple(self.values), values)
                self.assertEqual(self.writes, [(0, values[0]), (1, values[1]), (2, values[2])])

    def test_readback_mismatch_is_visible(self):
        def mismatched(_fd, command, argument, *_):
            if command in control.W_UW_TDP:
                return 0
            index = control.R_UW_TDP.index(command)
            argument[:4] = struct.pack("i", 100 if index == 2 else 35)
            return 0
        with mock.patch.object(control.fcntl, "ioctl", side_effect=mismatched), \
                self.assertRaisesRegex(RuntimeError, "TDP readback mismatch"):
            control.apply_mode_tdp("office")

    def test_write_failure_rolls_back_previous_limits(self):
        self.values = [35, 35, 215]
        failed = False

        def fail_second_write(fd, command, argument, *_):
            nonlocal failed
            self.assertEqual(fd, 7)
            if command in control.W_UW_TDP:
                index = control.W_UW_TDP.index(command)
                if index == 1 and not failed:
                    failed = True
                    raise OSError("second PL write failed")
                self.values[index] = struct.unpack("i", argument)[0]
            else:
                index = control.R_UW_TDP.index(command)
                argument[:4] = struct.pack("i", self.values[index])
            return 0

        with mock.patch.object(control.fcntl, "ioctl", side_effect=fail_second_write), \
                self.assertRaisesRegex(OSError, "second PL write failed"):
            control.apply_mode_tdp("turbo")
        self.assertEqual(self.values, [35, 35, 215])

    def test_unknown_mode_is_rejected_before_open(self):
        with mock.patch.object(control.os, "open") as opened, \
                self.assertRaisesRegex(ValueError, "Unknown TDP mode"):
            control.apply_mode_tdp("fan-boost")
        opened.assert_not_called()


class TouchpadRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "touchpad_state"
        self.device = Path(self.tmp.name) / "i2c-UNIW0001:00"
        self.device.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(control, "get_state_file", return_value=self.state))
        self.stack.enter_context(mock.patch.object(control, "TOUCHPAD_DEVICE_PATH", self.device))
        self.set = self.stack.enter_context(mock.patch.object(control, "set_touchpad"))

    def test_restores_saved_off_and_on_states(self):
        for value, enabled in (("0", False), ("1", True)):
            with self.subTest(value=value):
                self.state.write_text(value)
                self.set.reset_mock()
                self.assertEqual(control.restore_touchpad_state(), enabled)
                self.set.assert_called_once_with(enabled)

    def test_missing_state_is_a_noop(self):
        self.assertIsNone(control.restore_touchpad_state())
        self.set.assert_not_called()

    def test_invalid_state_is_rejected(self):
        self.state.write_text("2")
        with self.assertRaisesRegex(RuntimeError, "Invalid saved touchpad state"):
            control.restore_touchpad_state()
        self.set.assert_not_called()

    def test_waits_for_late_i2c_device_then_applies_state(self):
        self.state.write_text("0")
        device = mock.Mock()
        device.exists.side_effect = [False, True]
        with mock.patch.object(control, "TOUCHPAD_DEVICE_PATH", device), \
                mock.patch.object(control.time, "monotonic", side_effect=[0.0, 0.0]), \
                mock.patch.object(control.time, "sleep") as sleep:
            self.assertEqual(control.restore_touchpad_state(), False)
        sleep.assert_called_once_with(0.25)
        self.set.assert_called_once_with(False)

    def test_timeout_is_visible(self):
        self.state.write_text("0")
        device = mock.Mock()
        device.exists.return_value = False
        with mock.patch.object(control, "TOUCHPAD_DEVICE_PATH", device), \
                mock.patch.object(control.time, "monotonic", side_effect=[0.0, 31.0]), \
                mock.patch.object(control.time, "sleep"), \
                self.assertRaisesRegex(RuntimeError, "did not reappear"):
            control.restore_touchpad_state()
        self.set.assert_not_called()


class TouchpadSleepHookTests(unittest.TestCase):
    def test_hook_is_executable_and_only_runs_post(self):
        hook = ROOT / "scripts/mechrevo-touchpad-sleep"
        self.assertTrue(os.access(hook, os.X_OK))
        text = hook.read_text()
        self.assertIn('[ "${1:-}" = "post" ]', text)
        self.assertIn("/var/lib/mechrevo-control/touchpad_state", text)
        self.assertIn("/usr/bin/mechrevo-control touchpad restore", text)


if __name__ == "__main__":
    unittest.main()
