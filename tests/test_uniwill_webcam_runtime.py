"""Compile the Uniwill webcam ioctl against userspace USB and sysfs spies."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = (
    "uniwill_webcam_contains",
    "uniwill_webcam_name_is_device",
    "uniwill_webcam_device_is_camera",
    "uniwill_webcam_write_authorized",
    "uniwill_webcam_visit",
    "uniwill_webcam_ioctl",
)
CASES = (
    "get_enabled",
    "get_disabled_without_config",
    "get_absent",
    "get_mixed",
    "set_disables_only_camera",
    "set_enables_named_camera_without_config",
    "set_noop_for_both_states",
    "set_stops_after_first_write_error",
    "set_second_device_error_keeps_first_change",
    "set_open_error_changes_nothing",
    "set_short_write_is_eio",
    "set_absent_does_not_open",
    "copy_faults_precede_usb_access",
    "video_class_counts_without_product_text",
    "bad_names_are_not_cameras",
    "unknown_command_is_enotty",
    "route_uniwill_only",
    "route_keeps_clevo_without_uniwill_or_when_both_exist",
    "other_clevo_commands_stay_on_clevo",
)


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


class UniwillWebcamRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / ".local-tests"
        parent.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=parent)
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        source_root = Path(os.environ.get("UNIWILL_WEBCAM_SOURCE_ROOT", ROOT))
        io = (source_root / "src/tuxedo_io/tuxedo_io.c").read_text()
        macros = re.findall(r"(?m)^#define UW_WEBCAM_\w+[^\n]*$", io)
        if len(macros) != 3:
            raise AssertionError("Webcam walk fields changed: " + repr(macros))
        bodies = "\n\n".join(function(io, name) for name in FUNCTIONS)
        if "0x0727" in bodies or "uniwill_write_ec_ram" in bodies or "CLEVO_CMD" in bodies:
            raise AssertionError("Uniwill webcam path references EC or Clevo firmware")
        fixture = (ROOT / "tests/fixtures/uniwill_webcam_runtime.c").read_text()
        fixture = fixture.replace("/* @WEBCAM_MACROS@ */", "\n".join(macros))
        fixture = fixture.replace("/* @WEBCAM_FUNCTIONS@ */", bodies)
        fixture = fixture.replace("/* @IOCTL_ENTRY@ */", function(io, "fop_ioctl"))
        source = path / "runtime.c"
        source.write_text(fixture)
        cls.binaries = {}
        for debug in (False, True):
            binary = path / ("runtime-debug" if debug else "runtime")
            result = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-parameter", "-Wno-unused-function",
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

    def test_webcam_reads_writes_failures_and_routing(self):
        for case in CASES:
            with self.subTest(case=case):
                self.check_case(case)


if __name__ == "__main__":
    unittest.main()
