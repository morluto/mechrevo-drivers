"""Regression tests for the physical performance-mode cycle."""
import importlib.util
import fcntl
import io
import json
import os
from pathlib import Path
import select
import struct
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


if __name__ == "__main__":
    unittest.main()
