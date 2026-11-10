// SPDX-License-Identifier: GPL-2.0+
/* Read-only EC sensors verified on these exact machines and firmwares only. */
#include <linux/acpi.h>
#include <linux/delay.h>
#include <linux/dmi.h>
#include <linux/err.h>
#include <linux/hwmon.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>

#define MECHREVO_CPU_EC_TEMP 0x043e
#define MECHREVO_GPU_EC_TEMP 0x044f

/* OEM v5.17.51.34 RPM methods use INOU.ECRR, not the WMI transport. */
#define MECHREVO_CPU_RPM_HIGH 0x0464
#define MECHREVO_CPU_RPM_LOW  0x0465
#define MECHREVO_GPU_RPM_HIGH 0x046c
#define MECHREVO_RPM_ATTEMPTS 3
#define MECHREVO_ECRR_DELAY_MIN_US 6000
#define MECHREVO_ECRR_DELAY_MAX_US 12000
#define MECHREVO_PROJECT_ID 0x0740
#define MECHREVO_FAN_CTRL 0x078e
#define MECHREVO_PROJECT_ID_EXPECTED 0x10
#define MECHREVO_UNIVERSAL_FAN_CTRL 0x40

/* The GPU tachometer low byte is model-specific. GM6PX0X is qualified from
 * the OEM RPM method; GM6BG0Q was measured on hardware (only 0x046c/0x046d
 * follow the secondary fan across 50/200 duty steps while 0x046a/0x046b stay
 * at 0x41). Both pairs also match the in-tree Uniwill definitions.
 */
struct mechrevo_sensors_profile {
	const char *product_name;
	const char *board_name;
	const char *bios_version;
	u16 gpu_rpm_low;
};

static const struct mechrevo_sensors_profile mechrevo_sensors_profiles[] = {
	{
		.product_name = "Kuangshi16Pro Series GM6PX0X",
		.board_name = "GM6PX0X",
		.bios_version = "N.1.09MRO07",
		.gpu_rpm_low = 0x046b,
	},
	{
		.product_name = "Jiaolong16K Series GM6BG0Q",
		.board_name = "GM6BG0Q",
		.bios_version = "N.1.19MRO15",
		.gpu_rpm_low = 0x046d,
	},
};

static acpi_handle mechrevo_sensors_inou;
static const struct mechrevo_sensors_profile *mechrevo_sensors_profile;
static DEFINE_MUTEX(mechrevo_sensors_rpm_lock);
static struct platform_device *mechrevo_sensors_device;
static struct device *mechrevo_sensors_hwmon;

static const struct dmi_system_id mechrevo_sensors_dmi[] = {
	{
		.matches = {
			DMI_EXACT_MATCH(DMI_SYS_VENDOR, "MECHREVO"),
			DMI_EXACT_MATCH(DMI_PRODUCT_NAME, "Kuangshi16Pro Series GM6PX0X"),
			DMI_EXACT_MATCH(DMI_BOARD_NAME, "GM6PX0X"),
			DMI_EXACT_MATCH(DMI_BIOS_VERSION, "N.1.09MRO07"),
		},
	},
	{
		.matches = {
			DMI_EXACT_MATCH(DMI_SYS_VENDOR, "MECHREVO"),
			DMI_EXACT_MATCH(DMI_PRODUCT_NAME, "Jiaolong16K Series GM6BG0Q"),
			DMI_EXACT_MATCH(DMI_BOARD_NAME, "GM6BG0Q"),
			DMI_EXACT_MATCH(DMI_BIOS_VERSION, "N.1.19MRO15"),
		},
	},
	{ }
};
MODULE_DEVICE_TABLE(dmi, mechrevo_sensors_dmi);

static const struct mechrevo_sensors_profile *mechrevo_sensors_supported(void)
{
	unsigned int i;

	/* dmi_match compares the whole field, unlike substring DMI table matches. */
	for (i = 0; i < sizeof(mechrevo_sensors_profiles) /
				 sizeof(mechrevo_sensors_profiles[0]); i++) {
		const struct mechrevo_sensors_profile *profile =
			&mechrevo_sensors_profiles[i];

		if (dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		    dmi_match(DMI_PRODUCT_NAME, profile->product_name) &&
		    dmi_match(DMI_BOARD_NAME, profile->board_name) &&
		    dmi_match(DMI_BIOS_VERSION, profile->bios_version))
			return profile;
	}
	return NULL;
}

static int mechrevo_sensors_ecrr(u16 address, u8 *value)
{
	union acpi_object argument = { .type = ACPI_TYPE_INTEGER };
	struct acpi_object_list arguments = { .count = 1, .pointer = &argument };
	unsigned long long raw;
	acpi_status status;

	argument.integer.value = address;
	status = acpi_evaluate_integer(mechrevo_sensors_inou, "ECRR",
				       &arguments, &raw);
	if (ACPI_FAILURE(status))
		return -EIO;
	/* Match the delay used by the in-tree Uniwill ECRR transport. */
	usleep_range(MECHREVO_ECRR_DELAY_MIN_US, MECHREVO_ECRR_DELAY_MAX_US);
	if (raw > 255)
		return -ERANGE;
	*value = raw;
	return 0;
}

static int mechrevo_sensors_temperature(int channel, long *value)
{
	u16 address;
	u8 raw;
	int ret;

	if (channel == 0)
		address = MECHREVO_CPU_EC_TEMP;
	else if (channel == 1)
		address = MECHREVO_GPU_EC_TEMP;
	else
		return -EOPNOTSUPP;

	ret = mechrevo_sensors_ecrr(address, &raw);
	if (ret)
		return ret;
	if (raw > 125)
		return -ENODATA;

	*value = (long)raw * 1000;
	return 0;
}

static int mechrevo_sensors_rpm(int channel, long *value)
{
	u16 high_address, low_address;
	u8 high, low, check;
	int attempt, ret;

	if (!mechrevo_sensors_profile)
		return -ENODEV;
	if (channel == 0) {
		high_address = MECHREVO_CPU_RPM_HIGH;
		low_address = MECHREVO_CPU_RPM_LOW;
	} else if (channel == 1) {
		high_address = MECHREVO_GPU_RPM_HIGH;
		low_address = mechrevo_sensors_profile->gpu_rpm_low;
	} else {
		return -EOPNOTSUPP;
	}

	/* Serialize our readers and reject a high-byte rollover mid-sample.
	 * Firmware can still update independently; this is not an atomic EC read.
	 */
	mutex_lock(&mechrevo_sensors_rpm_lock);
	for (attempt = 0; attempt < MECHREVO_RPM_ATTEMPTS; attempt++) {
		ret = mechrevo_sensors_ecrr(high_address, &high);
		if (ret)
			goto out;
		ret = mechrevo_sensors_ecrr(low_address, &low);
		if (ret)
			goto out;
		ret = mechrevo_sensors_ecrr(high_address, &check);
		if (ret)
			goto out;
		if (high == check) {
			*value = ((long)high << 8) | low;
			ret = 0;
			goto out;
		}
	}
	ret = -EAGAIN;
out:
	mutex_unlock(&mechrevo_sensors_rpm_lock);
	return ret;
}

static int mechrevo_sensors_rpm_qualify(void)
{
	u8 project, capability;
	int ret;

	if (ACPI_FAILURE(acpi_get_handle(NULL, "\\_SB.INOU",
				       &mechrevo_sensors_inou)) ||
	    !acpi_has_method(mechrevo_sensors_inou, "ECRR"))
		return -ENODEV;
	ret = mechrevo_sensors_ecrr(MECHREVO_PROJECT_ID, &project);
	if (ret)
		return ret;
	ret = mechrevo_sensors_ecrr(MECHREVO_FAN_CTRL, &capability);
	if (ret)
		return ret;
	/* Only the observed project 0x10 and OEM RAM-fan-1p5 branch. */
	return project == MECHREVO_PROJECT_ID_EXPECTED &&
		(capability & MECHREVO_UNIVERSAL_FAN_CTRL) ? 0 : -ENODEV;
}

static umode_t mechrevo_sensors_is_visible(const void *data,
					 enum hwmon_sensor_types type,
					 u32 attr, int channel)
{
	if (channel < 0 || channel > 1)
		return 0;
	if (type == hwmon_temp)
		return attr == hwmon_temp_input || attr == hwmon_temp_label ? 0444 : 0;
	if (type == hwmon_fan)
		return attr == hwmon_fan_input || attr == hwmon_fan_label ? 0444 : 0;
	return 0;
}

static int mechrevo_sensors_read(struct device *dev,
				enum hwmon_sensor_types type,
				u32 attr, int channel, long *value)
{
	if (type == hwmon_temp && attr == hwmon_temp_input)
		return mechrevo_sensors_temperature(channel, value);
	if (type == hwmon_fan && attr == hwmon_fan_input)
		return mechrevo_sensors_rpm(channel, value);
	return -EOPNOTSUPP;
}

static int mechrevo_sensors_read_string(struct device *dev,
				       enum hwmon_sensor_types type,
				       u32 attr, int channel,
				       const char **value)
{
	if (channel < 0 || channel > 1)
		return -EOPNOTSUPP;
	if (type == hwmon_temp && attr == hwmon_temp_label)
		*value = channel == 0 ? "CPU EC" : "GPU EC";
	else if (type == hwmon_fan && attr == hwmon_fan_label)
		*value = channel == 0 ? "CPU fan" : "GPU fan";
	else
		return -EOPNOTSUPP;
	return 0;
}

static const struct hwmon_ops mechrevo_sensors_ops = {
	.is_visible = mechrevo_sensors_is_visible,
	.read = mechrevo_sensors_read,
	.read_string = mechrevo_sensors_read_string,
};

static const struct hwmon_channel_info * const mechrevo_sensors_info[] = {
	HWMON_CHANNEL_INFO(temp,
		HWMON_T_INPUT | HWMON_T_LABEL,
		HWMON_T_INPUT | HWMON_T_LABEL),
	HWMON_CHANNEL_INFO(fan,
		HWMON_F_INPUT | HWMON_F_LABEL,
		HWMON_F_INPUT | HWMON_F_LABEL),
	NULL,
};

static const struct hwmon_chip_info mechrevo_sensors_chip = {
	.ops = &mechrevo_sensors_ops,
	.info = mechrevo_sensors_info,
};

static int __init mechrevo_sensors_init(void)
{
	long value;
	int ret;

	mechrevo_sensors_profile = mechrevo_sensors_supported();
	if (!mechrevo_sensors_profile)
		return -ENODEV;
	ret = mechrevo_sensors_rpm_qualify();
	if (ret)
		return ret;
	ret = mechrevo_sensors_temperature(0, &value);
	if (ret)
		return ret;
	ret = mechrevo_sensors_temperature(1, &value);
	if (ret)
		return ret;

	ret = mechrevo_sensors_rpm(0, &value);
	if (ret)
		return ret;
	ret = mechrevo_sensors_rpm(1, &value);
	if (ret)
		return ret;

	mechrevo_sensors_device = platform_device_register_simple(
		"mechrevo_ec_sensors", PLATFORM_DEVID_NONE, NULL, 0);
	if (IS_ERR(mechrevo_sensors_device)) {
		ret = PTR_ERR(mechrevo_sensors_device);
		mechrevo_sensors_device = NULL;
		return ret;
	}
	mechrevo_sensors_hwmon = hwmon_device_register_with_info(
		&mechrevo_sensors_device->dev, "mechrevo_ec", NULL,
		&mechrevo_sensors_chip, NULL);
	if (IS_ERR(mechrevo_sensors_hwmon)) {
		ret = PTR_ERR(mechrevo_sensors_hwmon);
		mechrevo_sensors_hwmon = NULL;
		platform_device_unregister(mechrevo_sensors_device);
		mechrevo_sensors_device = NULL;
		return ret;
	}
	return 0;
}

static void __exit mechrevo_sensors_exit(void)
{
	hwmon_device_unregister(mechrevo_sensors_hwmon);
	platform_device_unregister(mechrevo_sensors_device);
}

module_init(mechrevo_sensors_init);
module_exit(mechrevo_sensors_exit);
MODULE_DESCRIPTION("Read-only MECHREVO EC temperatures and fan RPM");
MODULE_LICENSE("GPL");
