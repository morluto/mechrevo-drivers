"""Exercise OEM RPM through the complete real hwmon translation unit."""
import unittest
import test_mechrevo_ec_sensors as sensors


class MechrevoEcRpm(unittest.TestCase):
    setUpClass = classmethod(sensors.MechrevoEcSensors.setUpClass.__func__)
    check_case = sensors.MechrevoEcSensors.check_case

    def test_every_oem_word_and_correct_gpu_low_address(self):
        self.check_case('rpm_values')

    def test_each_read_failure_range_error_rollover_retry_and_lock_release(self):
        self.check_case('rpm_errors')

    def test_acpi_identity_layout_and_startup_reads_fail_closed(self):
        self.check_case('rpm_qualification')

    def test_gm6bg0q_uses_its_own_secondary_low_byte(self):
        self.check_case('gm6bg0q')
