"""Exercise real ioctl feature-binding boundaries with no hardware access."""
from pathlib import Path
import os
import re
import resource
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"(?m)^static[^;{]*\b" + re.escape(name) + r"\([^;{]*\)\s*\{", source)
    if not match:
        raise AssertionError("Missing driver function: " + name)
    depth, position = 1, match.end()
    while depth and position < len(source):
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    if depth:
        raise AssertionError("Unbalanced driver function: " + name)
    return source[match.start():position]


def disable_core_dumps():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class UniwillFeatureBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = Path(os.environ.get("UNIWILL_TEST_TMPDIR", ROOT / ".local-tests"))
        parent.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="feature-binding-", dir=parent)
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        # A single original source file is sufficient for the sensitivity run;
        # no archived whole tree or real module is executed.
        source = Path(os.environ.get(
            "UNIWILL_FEATURE_IO_SOURCE", ROOT / "src/tuxedo_io/tuxedo_io.c"
        )).read_text()
        interfaces = (ROOT / "src/uniwill_interfaces.h").read_text()
        types = []
        for kind, name in (("struct", "uniwill_device_features_t"),
                           ("union", "uw_ec_read_return"),
                           ("union", "uw_ec_write_return"),
                           ("enum", "uw_perf_profiles_v1")):
            declaration = re.search(r"(?ms)^" + kind + " " + name + r" \{.*?^};", interfaces)
            if not declaration:
                raise AssertionError("Missing real driver type: " + name)
            types.append(declaration.group())
        constant = re.search(r"(?m)^#define FAN_ON_MIN_SPEED_PERCENT\s+.+$", source)
        if not constant:
            raise AssertionError("Missing fan minimum speed constant")
        names = (
            "uw_identify_locked", "uniwill_identify",
            "uw_ensure_identified", "uw_features_ready",
            "uw_get_tdp_min", "uw_get_tdp_max",
            "uw_get_tdp", "uw_set_tdp", "uw_get_performance_profile_count",
            "uw_apply_performance_profile_v1", "uw_set_performance_profile_v1",
            "uw_copy_tdp_value", "uniwill_ioctl_interface", "fop_ioctl",
        )
        fixture = (ROOT / "tests/fixtures/uniwill_feature_binding_runtime.c").read_text()
        fixture = fixture.replace("/* @REAL_INTERFACE_TYPES@ */", "\n\n".join(types))
        fixture = fixture.replace("/* @REAL_DRIVER_FUNCTIONS@ */", "\n\n".join(
            [constant.group()] + [function(source, name) for name in names]
        ))
        unit = path / "runtime.c"
        unit.write_text(fixture)
        cls.binaries = {}
        for debug in (False, True):
            binary = path / ("runtime-debug" if debug else "runtime")
            compiled = subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-Wno-unused-parameter", "-Wno-unused-but-set-variable",
                 "-I", str(ROOT / "src/tuxedo_io"),
                 *(["-DDEBUG"] if debug else []), str(unit), "-o", str(binary)],
                text=True, capture_output=True, timeout=30,
            )
            if compiled.returncode:
                raise AssertionError(compiled.stdout + compiled.stderr)
            cls.binaries[debug] = binary

    def check_case(self, name):
        for debug, binary in self.binaries.items():
            with self.subTest(debug=debug):
                result = subprocess.run(
                    [str(binary), name], text=True, capture_output=True,
                    timeout=10, preexec_fn=disable_core_dumps,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unbound_model_and_profile_queries_do_not_copy_or_touch_ec(self):
        self.check_case("unbound_metadata")

    def test_unbound_both_fan_reads_reject_before_ec_access(self):
        self.check_case("unbound_fans")

    def test_unbound_tdp_helpers_reject_before_ec_or_provider_writes(self):
        self.check_case("unbound_tdp")

    def test_unbound_tdp_index_range_and_profile_validation_keep_errno_order(self):
        self.check_case("unbound_validation")

    def test_unbound_write_copy_faults_still_precede_feature_checks(self):
        self.check_case("unbound_copy_faults")

    def test_constants_interface_string_and_noop_do_not_trigger_binding(self):
        self.check_case("independent_commands")

    def test_unknown_and_malformed_commands_do_not_probe_or_access_hardware(self):
        self.check_case("unknown_commands")

    def test_absent_interface_identification_leaves_features_unbound(self):
        self.check_case("identify_absent")

    def test_incomplete_feature_probe_is_not_published_or_used_for_tdp_mapping(self):
        self.check_case("identify_not_ready")

    def test_null_provider_result_is_not_published_or_used_for_tdp_mapping(self):
        self.check_case("identify_null_provider")

    def test_late_binding_through_real_hwcheck_restores_queries_and_valid_writes(self):
        self.check_case("late_binding")

    def test_failed_reidentification_keeps_published_metadata_and_transport_errors(self):
        self.check_case("disconnect")

    def test_null_feature_reprobe_keeps_previous_static_metadata_without_remapping(self):
        self.check_case("reprobe_null_provider")

    def test_bound_queries_preserve_copy_and_transport_failures(self):
        self.check_case("bound_failures")

    def test_debug_historical_aliases_do_not_require_model_features(self):
        self.check_case("debug_aliases")


if __name__ == "__main__":
    unittest.main()
