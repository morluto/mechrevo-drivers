"""Compile and exercise the complete actual hwmon C driver with kernel mocks.

No EC or hardware access. Set MECHREVO_EC_SENSORS_SOURCE for mutation checks.
"""
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MechrevoEcSensors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = Path(os.environ.get('UNIWILL_TEST_TMPDIR',
                                     ROOT / '.local-tests/ec-sensors'))
        parent.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='sensors-', dir=parent)
        cls.addClassCleanup(cls.temp.cleanup)
        source_path = Path(os.environ.get('MECHREVO_EC_SENSORS_SOURCE',
                                         ROOT / 'src/mechrevo_ec_sensors.c'))
        cls.source = source_path.read_text()
        production = re.sub(r'^#include .+\n', '', cls.source, flags=re.MULTILINE)
        fixture = (ROOT / 'tests/fixtures/mechrevo_ec_sensors.c').read_text()
        source = Path(cls.temp.name) / 'runtime.c'
        source.write_text(fixture.replace('/* @DRIVER@ */', production))
        cls.binary = Path(cls.temp.name) / 'runtime'
        result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-Wno-unused-parameter', '-Wno-unused-const-variable',
                                 str(source), '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def check_case(self, case):
        def no_core():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True,
                                timeout=10, preexec_fn=no_core)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_identity_requires_each_complete_verified_field(self):
        self.check_case('identity')

    def test_transport_errors_and_initial_availability_fail_closed(self):
        self.check_case('transport')

    def test_all_bytes_both_channels_preserve_output_on_invalid_temperatures(self):
        self.check_case('temperature')

    def test_two_read_only_temperature_and_fan_channels_and_honest_labels(self):
        self.check_case('interface')

    def test_registration_failures_cleanup_and_successful_unload_order(self):
        self.check_case('lifecycle')

    def test_acpi_transport_needs_no_private_tuxedo_module(self):
        self.check_case('independent_transport')
        self.assertNotRegex(self.source, r'\b(?:uniwill_read_ec_ram|request_module)\s*\(')
        self.assertRegex(self.source, r'acpi_evaluate_integer\([^;]*"ECRR"')

    def test_production_has_no_write_or_background_polling_interface(self):
        self.assertNotRegex(self.source, r'\b(?:uniwill_write_ec_ram|schedule_work|schedule_delayed_work|timer_setup|kthread_run)\s*\(')
        self.assertNotRegex(self.source, r'\bECRW\b|acpi_evaluate_object\s*\(')
        self.assertNotRegex(self.source, r'\.write\s*=')
        self.assertNotRegex(self.source, r'\bMODULE_SOFTDEP\s*\(')
        self.assertNotRegex(self.source, r'\b(?:delete_module|symbol_put|module_put)\s*\(')


if __name__ == '__main__':
    unittest.main()
