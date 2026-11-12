"""Compile the actual Clevo ioctl and entry point against safe userspace spies."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"(?m)^static[^;{]*\b" + re.escape(name) + r"\([^;{]*\)\s*\{", source)
    if not match:
        raise AssertionError("Missing driver function: " + name)
    depth = 1
    position = match.end()
    while depth and position < len(source):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
        position += 1
    if depth:
        raise AssertionError("Unbalanced driver function: " + name)
    return source[match.start():position]


class ClevoIoctlRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / ".local-tests"
        parent.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=parent)
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        source_root = Path(os.environ.get("CLEVO_IO_SOURCE_ROOT", ROOT))
        io = (source_root / "src/tuxedo_io/tuxedo_io.c").read_text()
        interfaces = (source_root / "src/clevo_interfaces.h").read_text()
        # Use the actual public ioctl header and actual firmware command and fan
        # constants; only the kernel service implementations are mocked.
        constants = re.findall(r"(?m)^#define CLEVO_CMD_\w+[^\n]*$", interfaces)
        for name in ("NB01_FAN_SPEED_MAX", "FAN_ON_MIN_SPEED_PERCENT"):
            match = re.search(r"(?m)^#define " + name + r"\s+[^\n]*$", io)
            if not match:
                raise AssertionError("Missing driver constant: " + name)
            constants.append(match.group())
        fixture = (ROOT / "tests/fixtures/clevo_ioctl_runtime.c").read_text()
        fixture = fixture.replace("/* @DRIVER_CONSTANTS@ */", "\n".join(constants))
        fixture = fixture.replace("/* @DRIVER_CLEVO_IOCTL@ */", function(io, "clevo_ioctl_interface"))
        fixture = fixture.replace("/* @DRIVER_IOCTL_ENTRY@ */", function(io, "fop_ioctl"))
        source = path / "runtime.c"
        source.write_text(fixture)
        cls.binaries = {}
        for debug in (False, True):
            binary = path / ("runtime-debug" if debug else "runtime")
            result = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 # The actual kernel callbacks have an unused file argument;
                 # the pre-fix sensitivity run also discards status/copy_result.
                 "-Wno-unused-parameter", "-Wno-unused-but-set-variable",
                 "-I", str(source_root / "src/tuxedo_io"),
                 *(["-DDEBUG"] if debug else []), str(source), "-o", str(binary)],
                text=True, capture_output=True,
            )
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            cls.binaries[debug] = binary

    def check_case(self, case):
        for debug, binary in self.binaries.items():
            with self.subTest(debug=debug):
                result = subprocess.run([str(binary), case], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_six_reads_preserve_full_u32_and_command_routing(self):
        self.check_case("read_success")

    def test_all_six_read_transport_errors_return_signed_errno_without_copy(self):
        self.check_case("read_errors")

    def test_all_six_read_partial_and_full_output_faults_return_efault(self):
        self.check_case("read_copy_faults")

    def test_live_and_missing_interface_strings_keep_existing_behavior(self):
        self.check_case("interface_strings")

    def test_interface_string_partial_and_full_copy_faults_return_efault(self):
        self.check_case("interface_copy_faults")

    def test_all_six_writes_reject_partial_and_full_input_faults_before_transport(self):
        self.check_case("write_copy_faults")

    def test_all_six_writes_preserve_original_transport_errno(self):
        self.check_case("write_errors")

    def test_unexpected_positive_transport_status_stops_dependent_operations(self):
        self.check_case("positive_status")

    def test_fan_packed_three_byte_mapping_for_all_256_values_in_each_position(self):
        self.check_case("fan_mapping")

    def test_fan_delay_only_follows_successful_manual_set(self):
        self.check_case("fan_delay")

    def test_auto_flight_touchpad_writes_preserve_full_u32_payload(self):
        self.check_case("write_payloads")

    def test_performance_profile_uses_low_byte_for_all_256_values(self):
        self.check_case("performance_profile")

    def test_webcam_get_failure_never_issues_set(self):
        self.check_case("webcam_get_errors")

    def test_webcam_matching_low_bit_is_a_noop_for_all_256_values(self):
        self.check_case("webcam_noop")

    def test_webcam_toggle_preserves_full_payload_and_reports_set_failure(self):
        self.check_case("webcam_set")

    def test_disabled_webcam_dmi_models_keep_read_write_policy(self):
        self.check_case("webcam_dmi")

    def test_uniwill_only_webcam_leaves_clevo_and_clevo_still_owns_shared_platforms(self):
        self.check_case("webcam_platform_route")

    def test_unknown_commands_return_enotty_without_user_copy_or_hardware_access(self):
        self.check_case("unknown_commands")

    def test_all_clevo_and_generic_commands_reject_wrong_direction_size_and_type(self):
        self.check_case("malformed_commands")

    def test_debug_aliases_only_route_to_uniwill_in_debug_builds(self):
        self.check_case("debug_command_routing")


if __name__ == "__main__":
    unittest.main()
