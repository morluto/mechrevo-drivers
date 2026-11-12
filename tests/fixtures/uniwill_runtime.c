/* Userspace mocks for the exact driver functions injected by test_uniwill_runtime.py.
 * No device, sysfs, EC, module loading or root privileges are used. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include "tuxedo_io_ioctl.h"

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define __user

struct uniwill_device_features_t {
	u32 model;
	bool uniwill_has_mini_led_local_dimming;
	bool uniwill_has_double_pl4;
	bool uniwill_has_universal_ec_fan_control;
	bool uniwill_custom_profile_mode_needed;
	bool uniwill_profile_v1_two_profs;
	bool uniwill_profile_v1_three_profs;
	bool uniwill_profile_v1_three_profs_leds_only;
};
static struct uniwill_device_features_t uniwill_device_features;
#define features uniwill_device_features
static struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

struct platform_device { struct { int kobj; } dev; };
static int uw_mini_led_local_dimming_attr_group;
static bool uw_mini_led_local_dimming_loaded;
static int group_status, group_calls, dimming_calls;
static int sysfs_create_group(const int *kobj, const void *group)
{
	(void)kobj;
	(void)group;
	++group_calls;
	return group_status;
}
static int uw_set_mini_led_local_dimming(bool enabled)
{
	assert(!enabled);
	++dimming_calls;
	return 0;
}

static int minimums[] = {5, 6, 7};
static int maximums[] = {80, 90, 200};
static int *tdp_min_defs = minimums;
static int *tdp_max_defs = maximums;
static int ec_status, ec_reads, ec_write_status, ec_writes;
static u16 ec_error_address, ec_write_error_address;
static u16 written_addresses[8];
static u8 written_values[8], ec_value = 64;
static int copy_fault, copies, copy_attempts, copy_from_fault, input_copies;
static int uniwill_read_ec_ram(u16 address, u8 *value)
{
	++ec_reads;
	if (ec_status && (!ec_error_address || ec_error_address == address))
		return ec_status;
	*value = ec_value;
	return 0;
}
static int uniwill_write_ec_ram(u16 address, u8 value)
{
	assert(ec_writes < 8);
	written_addresses[ec_writes] = address;
	written_values[ec_writes++] = value;
	if (ec_write_status && (!ec_write_error_address || ec_write_error_address == address))
		return ec_write_status;
	return 0;
}
/* These spies verify ioctl routing and argument/error propagation only.
 * The actual serialized helpers are exercised by the fan runtime tests. */
/* @DRIVER_MODE_PROTOTYPES@ */
static int mode_status, mode_calls, mode_update_calls;
static u8 requested_mode, requested_clear_mask, requested_set_mask;
int uw_set_mode(u8 value)
{
	++mode_calls;
	requested_mode = value;
	if (mode_status)
		return mode_status;
	return uniwill_write_ec_ram(0x0751, value);
}
int uw_update_mode(u8 clear_mask, u8 set_mask)
{
	u8 current_value;
	int status;

	++mode_update_calls;
	requested_clear_mask = clear_mask;
	requested_set_mask = set_mask;
	if (mode_status)
		return mode_status;
	status = uniwill_read_ec_ram(0x0751, &current_value);
	if (status)
		return status;
	return uniwill_write_ec_ram(0x0751, (current_value & ~clear_mask) | set_mask);
}
static unsigned long copy_to_user(void *destination, const void *source, size_t length)
{
	++copy_attempts;
	if (copy_fault)
		return 1;
	memcpy(destination, source, length);
	++copies;
	return 0;
}
static unsigned long copy_from_user(void *destination, const void *source, size_t length)
{
	++input_copies;
	/* A partial copy must also stop the driver before it uses the argument. */
	memcpy(destination, source, copy_from_fault ? length / 2 : length);
	return copy_from_fault ? 1 : 0;
}
static int fan_status, fan_calls, fan_auto_calls;
static u32 selected_fan;
static u8 selected_speed;
static u32 uw_set_fan(u32 fan_index, u8 fan_speed)
{
	++fan_calls;
	selected_fan = fan_index;
	selected_speed = fan_speed;
	return fan_status;
}
static u32 uw_set_fan_auto(void)
{
	++fan_auto_calls;
	return fan_status;
}
static int interface_status;
static int uniwill_get_active_interface_id(char **name)
{
	if (name)
		*name = "mock-uniwill";
	return interface_status;
}

/* @DRIVER_INTERFACE_TYPES@ */
static int uw_set_performance_profile_v1(enum uw_perf_profiles_v1 profile);

/* Use the real cross-module TDP transaction and lifecycle gates. These doubles
 * supply only the kernel mutex service; profile-routing spies above remain
 * independent so the ioctl tests can still observe public-profile arguments. */
struct mutex { bool held; };
static __attribute__((unused)) struct mutex uniwill_fan_command_lock, uniwill_fan_state_lock;
static __attribute__((unused)) bool uniwill_fan_removed, uniwill_pm_suspended, uniwill_fan_work_paused;
static __attribute__((unused)) bool uniwill_pm_ready = true;
static __attribute__((unused)) void mutex_lock(struct mutex *lock) { assert(!lock->held); lock->held = true; }
static __attribute__((unused)) void mutex_unlock(struct mutex *lock) { assert(lock->held); lock->held = false; }
static __attribute__((unused)) void uw_fan_quiesce_locked(void) { assert(0 && "TDP must not cancel fan work"); }
/* @DRIVER_TDP_PROVIDER@ */

/* @DRIVER_FUNCTIONS@ */

/* Keep the driver's outer ioctl entry intact so signed errno propagation is tested. */
struct file { int unused; };
static struct { const char *version; } mock_module = { "test" };
#define THIS_MODULE (&mock_module)
static u32 id_check_clevo, id_check_uniwill;
static u32 clevo_identify(void) { return 0; }
static u32 uniwill_identify(void) { return 1; }
/* The dispatcher's lazy-retry wrapper is exercised by test_tuxedo_io_identify;
 * here identification is already mocked and never fails. */
static bool uw_features_ready(void) { return uw_feats != NULL; }
static int clevo_calls;
static int uniwill_webcam_calls;
static long uniwill_webcam_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	++uniwill_webcam_calls;
	return -EIO;
}
static long clevo_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	++clevo_calls;
	return 0;
}

/* The kernel does not enable these userspace fixture warnings. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#pragma GCC diagnostic ignored "-Wunused-parameter"
/* @DRIVER_UNIWILL_IOCTL@ */
/* @DRIVER_IOCTL_ENTRY@ */
#pragma GCC diagnostic pop

static const unsigned int tdp_reads[] = {
	R_UW_TDP0, R_UW_TDP1, R_UW_TDP2,
	R_UW_TDP0_MIN, R_UW_TDP1_MIN, R_UW_TDP2_MIN,
	R_UW_TDP0_MAX, R_UW_TDP1_MAX, R_UW_TDP2_MAX
};
static const unsigned int ec_reads_cmds[] = {
	R_UW_FANSPEED, R_UW_FANSPEED2, R_UW_FAN_TEMP,
	R_UW_FAN_TEMP2, R_UW_MODE, R_UW_MODE_ENABLE
};
static const unsigned int writes_cmds[] = {
	W_UW_FANSPEED, W_UW_FANSPEED2, W_UW_MODE,
	W_UW_TDP0, W_UW_TDP1, W_UW_TDP2, W_UW_PERF_PROF
};
#define COUNT(array) (sizeof(array) / sizeof((array)[0]))
#define IOCTL(command, value) fop_ioctl(NULL, command, (unsigned long)&(value))

static void set_profile_features(unsigned int mask)
{
	features.uniwill_profile_v1_two_profs = (mask & 1) != 0;
	features.uniwill_profile_v1_three_profs = (mask & 2) != 0;
	features.uniwill_profile_v1_three_profs_leds_only = (mask & 4) != 0;
	features.uniwill_custom_profile_mode_needed = (mask & 8) != 0;
}

static void reset_mode_access(void)
{
	ec_reads = ec_writes = mode_calls = mode_update_calls = 0;
}

static void reject_command(unsigned int cmd)
{
	u32 value[16] = {0xdeadbeef};
	assert(IOCTL(cmd, value) == -ENOTTY);
	assert(uniwill_ioctl_interface(NULL, cmd, (unsigned long)value) == -ENOTTY);
	assert(value[0] == 0xdeadbeef && input_copies == 0 && copy_attempts == 0);
	assert(ec_reads == 0 && ec_writes == 0 && fan_calls == 0 && fan_auto_calls == 0);
	assert(mode_calls == 0 && mode_update_calls == 0 && clevo_calls == 0);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *test = argv[1];
	u32 value = 0xdeadbeef;
	struct platform_device device = {0};

	if (strcmp(test, "miniled_unsupported") == 0) {
		uw_mini_led_local_dimming_init(&device);
		assert(!uw_mini_led_local_dimming_loaded);
		assert(group_calls == 0 && dimming_calls == 0);
	} else if (strcmp(test, "miniled_supported") == 0) {
		features.uniwill_has_mini_led_local_dimming = true;
		uw_mini_led_local_dimming_init(&device);
		assert(uw_mini_led_local_dimming_loaded);
		assert(group_calls == 1 && dimming_calls == 1);
	} else if (strcmp(test, "miniled_registration_failure") == 0) {
		features.uniwill_has_mini_led_local_dimming = true;
		group_status = -ENOMEM;
		uw_mini_led_local_dimming_init(&device);
		assert(!uw_mini_led_local_dimming_loaded);
		assert(group_calls == 1 && dimming_calls == 0);
	} else if (strcmp(test, "tdp_unsupported") == 0) {
		tdp_min_defs = NULL;
		tdp_max_defs = NULL;
		for (size_t i = 0; i < COUNT(tdp_reads); ++i)
			assert(IOCTL(tdp_reads[i], value) == -ENODEV);
		assert(value == 0xdeadbeef && copies == 0 && ec_reads == 0);
	} else if (strcmp(test, "tdp_supported") == 0) {
		u32 expected[] = {64, 64, 64, 5, 6, 7, 80, 90, 200};
		for (size_t i = 0; i < COUNT(tdp_reads); ++i) {
			assert(IOCTL(tdp_reads[i], value) == 0);
			assert(value == expected[i]);
		}
		assert(copies == 9 && ec_reads == 3);
	} else if (strcmp(test, "tdp_ec_error") == 0) {
		ec_status = -EIO;
		for (size_t i = 0; i < 3; ++i)
			assert(IOCTL(tdp_reads[i], value) == -EIO);
		assert(value == 0xdeadbeef && copies == 0 && ec_reads == 3);
	} else if (strcmp(test, "tdp_invalid_index") == 0) {
		assert(uw_get_tdp(3) == -EINVAL);
		assert(uw_get_tdp_min(3) == -EINVAL);
		assert(uw_get_tdp_max(3) == -EINVAL);
		assert(ec_reads == 0);
	} else if (strcmp(test, "tdp_disabled_limit") == 0) {
		minimums[0] = 0;
		maximums[0] = 0;
		assert(fop_ioctl(NULL, R_UW_TDP0, (unsigned long)&value) == -ENODEV);
		assert(fop_ioctl(NULL, R_UW_TDP0_MIN, (unsigned long)&value) == -ENODEV);
		assert(fop_ioctl(NULL, R_UW_TDP0_MAX, (unsigned long)&value) == -ENODEV);
		assert(value == 0xdeadbeef && copies == 0 && ec_reads == 0);
	} else if (strcmp(test, "tdp_copy_fault") == 0) {
		copy_fault = 1;
		for (size_t i = 0; i < COUNT(tdp_reads); ++i)
			assert(IOCTL(tdp_reads[i], value) == -EFAULT);
		assert(value == 0xdeadbeef && copies == 0);
	} else if (strcmp(test, "tdp_double_pl4") == 0) {
		features.uniwill_has_double_pl4 = true;
		assert(fop_ioctl(NULL, R_UW_TDP2, (unsigned long)&value) == 0);
		assert(value == 128 && copies == 1 && ec_reads == 1);
	} else if (strcmp(test, "ec_read_error") == 0) {
		ec_status = -EIO;
		for (size_t i = 0; i < COUNT(ec_reads_cmds); ++i)
			assert(IOCTL(ec_reads_cmds[i], value) == -EIO);
		assert(value == 0xdeadbeef && copy_attempts == 0 && ec_reads == 6);
	} else if (strcmp(test, "ec_read_success") == 0) {
		for (size_t i = 0; i < COUNT(ec_reads_cmds); ++i) {
			assert(IOCTL(ec_reads_cmds[i], value) == 0);
			assert(value == 64);
		}
		assert(copies == 6 && ec_reads == 6);
	} else if (strcmp(test, "fan_zero_mapping") == 0) {
		ec_value = 1;
		assert(IOCTL(R_UW_FANSPEED, value) == 0 && value == 1);
		features.uniwill_has_universal_ec_fan_control = true;
		assert(IOCTL(R_UW_FANSPEED, value) == 0 && value == 0);
		assert(IOCTL(R_UW_FANSPEED2, value) == 0 && value == 0);
	} else if (strcmp(test, "all_read_copy_faults") == 0) {
		const unsigned int metadata[] = {
			R_UW_HW_IF_STR, R_UW_MODEL_ID, R_UW_FANS_OFF_AVAILABLE,
			R_UW_FANS_MIN_SPEED, R_UW_PROFS_AVAILABLE,
			R_MOD_VERSION, R_HWCHECK_CL, R_HWCHECK_UW
		};
		copy_fault = 1;
		for (size_t i = 0; i < COUNT(ec_reads_cmds); ++i)
			assert(IOCTL(ec_reads_cmds[i], value) == -EFAULT);
		for (size_t i = 0; i < COUNT(metadata); ++i)
			assert(IOCTL(metadata[i], value) == -EFAULT);
		interface_status = -ENODEV;
		assert(IOCTL(R_UW_HW_IF_STR, value) == -EFAULT);
		assert(value == 0xdeadbeef && copies == 0 && copy_attempts == 15);
		/* Neither generic nor Uniwill commands invoke the Clevo dispatch. */
		assert(clevo_calls == 0);
	} else if (strcmp(test, "read_metadata_success") == 0) {
		char text[32];
		assert(IOCTL(R_MOD_VERSION, text) == 0 && strcmp(text, "test") == 0);
		assert(IOCTL(R_HWCHECK_CL, value) == 0 && value == 0);
		assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 1);
		assert(IOCTL(R_UW_HW_IF_STR, text) == 0 && strcmp(text, "mock-uniwill") == 0);
		interface_status = -ENODEV;
		assert(IOCTL(R_UW_HW_IF_STR, text) == 0 && text[0] == '\0');
		features.model = 42;
		assert(IOCTL(R_UW_MODEL_ID, value) == 0 && value == 42);
		assert(IOCTL(R_UW_FANS_OFF_AVAILABLE, value) == 0 && value == 1);
		assert(IOCTL(R_UW_FANS_MIN_SPEED, value) == 0 && value == 25);
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 0);
		features.uniwill_profile_v1_two_profs = true;
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 2);
		features.uniwill_profile_v1_two_profs = false;
		features.uniwill_profile_v1_three_profs = true;
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 3);
		features.uniwill_profile_v1_three_profs = false;
		features.uniwill_profile_v1_three_profs_leds_only = true;
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 3);
	} else if (strcmp(test, "write_copy_faults") == 0) {
		copy_from_fault = 1;
		features.uniwill_custom_profile_mode_needed = true;
		for (size_t i = 0; i < COUNT(writes_cmds); ++i)
			assert(IOCTL(writes_cmds[i], value) == -EFAULT);
		assert(input_copies == 7 && ec_reads == 0 && ec_writes == 0);
		assert(fan_calls == 0 && fan_auto_calls == 0);
		assert(mode_calls == 0 && mode_update_calls == 0);
	} else if (strcmp(test, "fan_write_success") == 0) {
		for (value = 0; value <= UINT8_MAX; ++value) {
			assert(IOCTL(W_UW_FANSPEED, value) == 0);
			assert(selected_fan == 0 && selected_speed == value);
			assert(IOCTL(W_UW_FANSPEED2, value) == 0);
			assert(selected_fan == 1 && selected_speed == value);
		}
		assert(fan_calls == 512 && input_copies == 512);
		assert(IOCTL(W_UW_FANAUTO, value) == 0 && fan_auto_calls == 1);
		assert(fop_ioctl(NULL, W_UW_FANAUTO, 0) == 0 && fan_auto_calls == 2);
		assert(input_copies == 512);
	} else if (strcmp(test, "fan_write_out_of_range") == 0) {
		const u32 invalid_values[] = {256, UINT32_MAX};
		for (size_t i = 0; i < COUNT(invalid_values); ++i) {
			value = invalid_values[i];
			assert(IOCTL(W_UW_FANSPEED, value) == -EINVAL);
			assert(IOCTL(W_UW_FANSPEED2, value) == -EINVAL);
		}
		assert(input_copies == 4 && fan_calls == 0 && fan_auto_calls == 0);
		assert(ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "fan_write_error") == 0) {
		value = 52;
		fan_status = -EINVAL;
		assert(IOCTL(W_UW_FANSPEED, value) == -EINVAL);
		assert(IOCTL(W_UW_FANSPEED2, value) == -EINVAL);
		assert(IOCTL(W_UW_FANAUTO, value) == -EINVAL);
		assert(fan_calls == 2 && fan_auto_calls == 1);
	} else if (strcmp(test, "mode_write_success") == 0) {
		const u32 values[] = {0, 1, 255, 256, 0x1234, UINT32_MAX};
		for (size_t i = 0; i < COUNT(values); ++i) {
			value = values[i];
			assert(IOCTL(W_UW_MODE, value) == 0);
			assert(requested_mode == (u8)value && mode_calls == (int)i + 1);
			assert(written_addresses[i] == 0x0751 && written_values[i] == (u8)value);
		}
		assert(ec_writes == 6 && ec_reads == 0 && mode_update_calls == 0);
	} else if (strcmp(test, "mode_write_error") == 0) {
		ec_write_status = -EIO;
		assert(IOCTL(W_UW_MODE, value) == -EIO && ec_writes == 1);
		assert(mode_calls == 1 && mode_update_calls == 0);
	} else if (strcmp(test, "mode_helper_error") == 0) {
		const int errnos[] = {-ENODEV, -EIO, -ETIMEDOUT};
		value = 0x1234;
		for (size_t i = 0; i < COUNT(errnos); ++i) {
			mode_status = errnos[i];
			assert(IOCTL(W_UW_MODE, value) == errnos[i]);
			assert(mode_calls == (int)i + 1 && requested_mode == 0x34);
		}
		assert(mode_update_calls == 0 && ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "tdp_write_unsupported") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		tdp_min_defs = NULL;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == -ENODEV);
		assert(IOCTL(W_UW_TDP1, value) == -ENODEV);
		assert(IOCTL(W_UW_TDP2, value) == -ENODEV);
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0);
	} else if (strcmp(test, "tdp_write_invalid_index") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		assert(uw_set_tdp(3, 30) == -EINVAL);
		assert(ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "tdp_write_invalid_value") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		value = 4;
		assert(IOCTL(W_UW_TDP0, value) == -EINVAL);
		value = 81;
		assert(IOCTL(W_UW_TDP0, value) == -EINVAL);
		value = UINT32_MAX;
		assert(IOCTL(W_UW_TDP0, value) == -EINVAL);
		assert(ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "tdp_write_invalid_max") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		value = 30;
		tdp_max_defs = NULL;
		assert(IOCTL(W_UW_TDP0, value) == -ENODEV);
		tdp_max_defs = maximums;
		maximums[0] = 0;
		assert(IOCTL(W_UW_TDP0, value) == -ENODEV);
		assert(ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "tdp_write_success") == 0) {
		const unsigned int cmds[] = {W_UW_TDP0, W_UW_TDP1, W_UW_TDP2};
		value = 30;
		for (size_t i = 0; i < COUNT(cmds); ++i) {
			assert(IOCTL(cmds[i], value) == 0);
			assert(written_addresses[i] == 0x0783 + i && written_values[i] == 30);
		}
		assert(ec_reads == 0 && ec_writes == 3);
	} else if (strcmp(test, "tdp_write_double_pl4") == 0) {
		features.uniwill_has_double_pl4 = true;
		value = 129;
		assert(IOCTL(W_UW_TDP2, value) == 0);
		assert(ec_writes == 1 && written_addresses[0] == 0x0785 && written_values[0] == 64);
	} else if (strcmp(test, "tdp_write_ec_error") == 0) {
		ec_write_status = -EIO;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == -EIO);
		assert(IOCTL(W_UW_TDP1, value) == -EIO);
		assert(IOCTL(W_UW_TDP2, value) == -EIO);
		assert(ec_writes == 3);
	} else if (strcmp(test, "tdp_profile_read_error") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		ec_status = -EIO;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == -EIO);
		assert(ec_reads == 1 && ec_writes == 0 && mode_update_calls == !ACTUAL_TDP_PROVIDER);
	} else if (strcmp(test, "tdp_profile_write_error") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		ec_write_status = -EIO;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == -EIO);
		assert(ec_reads == 1 && ec_writes == 1 && written_addresses[0] == 0x0751);
		assert(mode_update_calls == !ACTUAL_TDP_PROVIDER);
	} else if (strcmp(test, "tdp_profile_success") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == 0);
		assert(ec_reads == 1 && ec_writes == 2);
		assert(written_addresses[0] == 0x0751 && written_values[0] == 0x50);
		assert(written_addresses[1] == 0x0783 && written_values[1] == 30);
		assert(mode_update_calls == !ACTUAL_TDP_PROVIDER);
		if (!ACTUAL_TDP_PROVIDER)
			assert(requested_clear_mask == 0xb0 && requested_set_mask == 0x10);
	} else if (strcmp(test, "tdp_provider_gate_error") == 0) {
		const unsigned int commands[] = {W_UW_TDP0, W_UW_TDP1, W_UW_TDP2};
		features.uniwill_custom_profile_mode_needed = true;
		mode_status = -ENODEV;
		uniwill_pm_ready = false;
		value = 30;
		for (size_t i = 0; i < COUNT(commands); ++i)
			assert(IOCTL(commands[i], value) == -ENODEV);
		assert(mode_update_calls == (ACTUAL_TDP_PROVIDER ? 0 : 3));
		assert(mode_calls == 0 && ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "tdp_ec_error_after_profile") == 0) {
		features.uniwill_custom_profile_mode_needed = true;
		ec_write_status = -EIO;
		ec_write_error_address = 0x0783;
		value = 30;
		assert(IOCTL(W_UW_TDP0, value) == -EIO);
		assert(ec_writes == 2 && written_addresses[1] == 0x0783);
	} else if (strcmp(test, "profile_read_error") == 0) {
		features.uniwill_profile_v1_three_profs = true;
		ec_status = -EIO;
		value = PROFILE_OVERBOOST;
		assert(IOCTL(W_UW_PERF_PROF, value) == -EIO);
		assert(ec_reads == 1 && ec_writes == 0 && mode_update_calls == 1);
	} else if (strcmp(test, "profile_write_error") == 0) {
		features.uniwill_profile_v1_three_profs = true;
		ec_write_status = -EIO;
		value = PROFILE_OVERBOOST;
		assert(IOCTL(W_UW_PERF_PROF, value) == -EIO);
		assert(ec_reads == 1 && ec_writes == 1 && mode_update_calls == 1);
	} else if (strcmp(test, "profile_invalid") == 0) {
		const u32 invalid[] = {0, 4, 0x101, 0x10003, UINT32_MAX};
		for (size_t i = 0; i < COUNT(invalid); ++i) {
			value = invalid[i];
			assert(IOCTL(W_UW_PERF_PROF, value) == -EINVAL);
		}
		assert(mode_update_calls == 0 && mode_calls == 0 && ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "profile_helper_error") == 0) {
		features.uniwill_profile_v1_three_profs = true;
		const int errnos[] = {-ENODEV, -EIO, -ETIMEDOUT};
		value = PROFILE_ENTHUSIAST;
		for (size_t i = 0; i < COUNT(errnos); ++i) {
			mode_status = errnos[i];
			assert(IOCTL(W_UW_PERF_PROF, value) == errnos[i]);
			assert(mode_update_calls == (int)i + 1);
			assert(requested_clear_mask == 0xb0 && requested_set_mask == 0);
		}
		assert(mode_calls == 0 && ec_reads == 0 && ec_writes == 0);
	} else if (strcmp(test, "profile_success") == 0) {
		features.uniwill_profile_v1_three_profs = true;
		u8 expected[] = {0xef, 0x4f, 0x5f};
		ec_value = 0xff;
		for (value = 1; value <= 3; ++value) {
			assert(IOCTL(W_UW_PERF_PROF, value) == 0);
			assert(written_addresses[value - 1] == 0x0751);
			assert(written_values[value - 1] == expected[value - 1]);
		}
		assert(mode_update_calls == 3 && mode_calls == 0);
	} else if (strcmp(test, "profile_masks") == 0) {
		features.uniwill_profile_v1_three_profs = true;
		const u8 bits[] = {0xa0, 0, 0x10};
		for (unsigned int previous = 0; previous <= UINT8_MAX; ++previous) {
			for (value = 1; value <= 3; ++value) {
				ec_value = previous;
				ec_reads = ec_writes = 0;
				assert(IOCTL(W_UW_PERF_PROF, value) == 0);
				assert(requested_clear_mask == 0xb0 && requested_set_mask == bits[value - 1]);
				assert(ec_reads == 1 && ec_writes == 1 && written_addresses[0] == 0x0751);
				assert(written_values[0] == ((previous & 0x4f) | bits[value - 1]));
			}
		}
		assert(mode_update_calls == 768 && mode_calls == 0);
	} else if (strcmp(test, "profile_count_matrix") == 0) {
		for (unsigned int mask = 0; mask < 16; ++mask) {
			set_profile_features(mask);
			assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0);
			assert(value == ((mask & 1) ? 2u : (mask & 6) ? 3u : 0u));
		}
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0);
	} else if (strcmp(test, "profile_capability_matrix") == 0) {
		const u8 bits[] = {0xa0, 0, 0x10};
		for (unsigned int mask = 0; mask < 16; ++mask) {
			set_profile_features(mask);
			const u32 count = (mask & 1) ? 2 : (mask & 6) ? 3 : 0;
			for (value = 1; value <= 3; ++value) {
				reset_mode_access();
				const int expected = !count ? -ENODEV : value > count ? -EINVAL : 0;
				assert(IOCTL(W_UW_PERF_PROF, value) == expected);
				if (expected) {
					assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0);
				} else {
					assert(ec_reads == 1 && ec_writes == 1 && mode_update_calls == 1);
					assert(written_addresses[0] == 0x0751);
					assert(written_values[0] == ((ec_value & 0x4f) | bits[value - 1]));
				}
				assert(mode_calls == 0);
			}
		}
	} else if (strcmp(test, "profile_two_rejects_overboost") == 0) {
		set_profile_features(1);
		value = PROFILE_OVERBOOST;
		assert(IOCTL(W_UW_PERF_PROF, value) == -EINVAL);
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0 && mode_calls == 0);
	} else if (strcmp(test, "profile_two_precedence") == 0) {
		set_profile_features(15);
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 2);
		value = PROFILE_OVERBOOST;
		assert(IOCTL(W_UW_PERF_PROF, value) == -EINVAL);
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0 && mode_calls == 0);
	} else if (strcmp(test, "profile_leds_only") == 0) {
		const u8 expected[] = {0xef, 0x4f, 0x5f};
		set_profile_features(4);
		ec_value = 0xff;
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 3);
		for (value = 1; value <= 3; ++value) {
			assert(IOCTL(W_UW_PERF_PROF, value) == 0);
			assert(written_addresses[value - 1] == 0x0751);
			assert(written_values[value - 1] == expected[value - 1]);
		}
		assert(ec_reads == 3 && ec_writes == 3 && mode_update_calls == 3 && mode_calls == 0);
	} else if (strcmp(test, "profile_custom_only_tdp") == 0) {
		const unsigned int commands[] = {W_UW_TDP0, W_UW_TDP1, W_UW_TDP2};
		set_profile_features(8);
		assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 0);
		for (value = 1; value <= 3; ++value)
			assert(IOCTL(W_UW_PERF_PROF, value) == -ENODEV);
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0 && mode_calls == 0);
		for (size_t i = 0; i < COUNT(commands); ++i) {
			reset_mode_access();
			value = 30;
			assert(IOCTL(commands[i], value) == 0);
			assert(ec_reads == 1 && ec_writes == 2 && mode_update_calls == !ACTUAL_TDP_PROVIDER);
			if (!ACTUAL_TDP_PROVIDER)
				assert(requested_clear_mask == 0xb0 && requested_set_mask == 0x10);
			assert(written_addresses[0] == 0x0751 && written_values[0] == 0x50);
			assert(written_addresses[1] == 0x0783 + i && written_values[1] == 30);
		}
	} else if (strcmp(test, "profile_invalid_capability_matrix") == 0) {
		const u32 invalid[] = {0, 4, 0x101, 0x10003, UINT32_MAX};
		for (unsigned int mask = 0; mask < 16; ++mask) {
			set_profile_features(mask);
			for (size_t i = 0; i < COUNT(invalid); ++i) {
				value = invalid[i];
				assert(IOCTL(W_UW_PERF_PROF, value) == -EINVAL);
			}
		}
		assert(ec_reads == 0 && ec_writes == 0 && mode_update_calls == 0 && mode_calls == 0);
	} else if (strcmp(test, "mode_enable_noop") == 0) {
		assert(IOCTL(W_UW_MODE_ENABLE, value) == 0);
		assert(fop_ioctl(NULL, W_UW_MODE_ENABLE, 0) == 0);
		assert(value == 0xdeadbeef && input_copies == 0 && copy_attempts == 0);
		assert(ec_reads == 0 && ec_writes == 0 && fan_calls == 0 && fan_auto_calls == 0);
		assert(mode_calls == 0 && mode_update_calls == 0);
	} else if (strcmp(test, "unknown_commands") == 0) {
		const unsigned int commands[] = {
			0, 0xffffffff, _IOR(IOCTL_MAGIC, 0xfe, int32_t *),
			_IOR(MAGIC_READ_UW, 0xfe, int32_t *),
			_IOW(MAGIC_WRITE_UW, 0xfe, int32_t *)
		};
		for (size_t i = 0; i < COUNT(commands); ++i)
			reject_command(commands[i]);
		const unsigned int foreign_commands[] = {R_MOD_VERSION, R_CL_FANINFO1, W_CL_FANSPEED};
		for (size_t i = 0; i < COUNT(foreign_commands); ++i)
			assert(uniwill_ioctl_interface(NULL, foreign_commands[i], 0) == -ENOTTY);
	} else if (strcmp(test, "malformed_commands") == 0) {
		const unsigned int commands[] = {
			R_UW_HW_IF_STR, R_UW_MODEL_ID, R_UW_FANSPEED, R_UW_FANSPEED2,
			R_UW_FAN_TEMP, R_UW_FAN_TEMP2, R_UW_MODE, R_UW_MODE_ENABLE,
			R_UW_FANS_OFF_AVAILABLE, R_UW_FANS_MIN_SPEED,
			R_UW_TDP0, R_UW_TDP1, R_UW_TDP2,
			R_UW_TDP0_MIN, R_UW_TDP1_MIN, R_UW_TDP2_MIN,
			R_UW_TDP0_MAX, R_UW_TDP1_MAX, R_UW_TDP2_MAX, R_UW_PROFS_AVAILABLE,
			W_UW_FANSPEED, W_UW_FANSPEED2, W_UW_MODE, W_UW_MODE_ENABLE,
			W_UW_FANAUTO, W_UW_TDP0, W_UW_TDP1, W_UW_TDP2, W_UW_PERF_PROF
		};
		for (size_t i = 0; i < COUNT(commands); ++i) {
			reject_command(commands[i] ^ ((unsigned int)_IOC_READ << _IOC_DIRSHIFT));
			reject_command(commands[i] ^ (1U << _IOC_SIZESHIFT));
			reject_command(_IOC(_IOC_DIR(commands[i]), 0xff,
					    _IOC_NR(commands[i]), _IOC_SIZE(commands[i])));
		}
#ifdef DEBUG
	} else if (strcmp(test, "debug_copy_from_faults") == 0) {
		u32 args[10] = {0x51, 0x07, 0x34};
		copy_from_fault = 1;
		assert(IOCTL(R_TF_BC, args) == -EFAULT);
		assert(IOCTL(W_TF_BC, args) == -EFAULT);
		assert(ec_reads == 0 && ec_writes == 0 && copy_attempts == 0);
	} else if (strcmp(test, "debug_read_error") == 0) {
		u32 args[10] = {0x51, 0x07, 0x34};
		ec_status = -EIO;
		assert(IOCTL(R_TF_BC, args) == -EIO);
		assert(args[0] == 0x51 && copy_attempts == 0);
	} else if (strcmp(test, "debug_write_error") == 0) {
		u32 args[10] = {0x51, 0x07, 0x34};
		ec_write_status = -EIO;
		assert(IOCTL(W_TF_BC, args) == -EIO);
		assert(args[0] == 0x51 && copy_attempts == 0);
	} else if (strcmp(test, "debug_copy_to_faults") == 0) {
		u32 args[10] = {0x51, 0x07, 0x34};
		copy_fault = 1;
		assert(IOCTL(R_TF_BC, args) == -EFAULT);
		assert(IOCTL(W_TF_BC, args) == -EFAULT);
		assert(copy_attempts == 2 && ec_reads == 1 && ec_writes == 1);
	} else if (strcmp(test, "debug_success") == 0) {
		u32 args[10] = {0x51, 0x07, 0x34};
		assert(IOCTL(R_TF_BC, args) == 0 && args[0] == 64);
		args[0] = 0x51;
		assert(IOCTL(W_TF_BC, args) == 0 && args[0] == 0);
		assert(ec_writes == 1 && written_addresses[0] == 0x0751 && written_values[0] == 0x34);
#endif
	} else {
		return 2;
	}
	assert(clevo_calls == 0 && uniwill_webcam_calls == 0);
	return 0;
}
