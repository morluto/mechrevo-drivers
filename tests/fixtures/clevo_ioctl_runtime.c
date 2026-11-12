/* Safe userspace spies around the exact Clevo ioctl and fop_ioctl functions.
 * Tests do not touch devices, load modules, write EC/sysfs, or require root. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include "tuxedo_io_ioctl.h"

typedef uint8_t u8;
typedef uint32_t u32;
struct file { int unused; };
#define __user
#define DMI_PRODUCT_SKU 1
/* @DRIVER_CONSTANTS@ */

static const char *product_sku = "mock-clevo";
static int dmi_match(int field, const char *value)
{
	assert(field == DMI_PRODUCT_SKU);
	return strcmp(product_sku, value) == 0;
}

static int interface_status, interface_calls;
static char interface_name[] = "mock-clevo-wmi";
static int clevo_get_active_interface_id(char **name)
{
	++interface_calls;
	if (!interface_status)
		*name = interface_name;
	return interface_status;
}

static unsigned long input_fault, output_fault;
static int input_copies, output_copies;
static size_t input_size, output_size;
static unsigned long copy_from_user(void *destination, const void *source, size_t length)
{
	++input_copies;
	input_size = length;
	assert(input_fault <= length);
	memcpy(destination, source, length - input_fault);
	return input_fault;
}
static unsigned long copy_to_user(void *destination, const void *source, size_t length)
{
	++output_copies;
	output_size = length;
	assert(output_fault <= length);
	memcpy(destination, source, length - output_fault);
	return output_fault;
}

static int method_calls, statuses[4];
static u8 methods[4];
static u32 arguments[4], results[4];
static int clevo_evaluate_method(u8 cmd, u32 arg, u32 *result)
{
	assert(method_calls < 4);
	methods[method_calls] = cmd;
	arguments[method_calls] = arg;
	/* Even a buggy transport that writes an error result must not leak it. */
	*result = results[method_calls];
	return statuses[method_calls++];
}

static int sleeps;
static unsigned int sleep_duration;
static void msleep(unsigned int duration)
{
	/* This must run after the successful firmware write, never before it. */
	assert(method_calls == 1 && methods[0] == CLEVO_CMD_SET_FANSPEED_VALUE);
	assert(statuses[0] == 0 && input_copies == 1);
	++sleeps;
	sleep_duration = duration;
}

/* @DRIVER_CLEVO_IOCTL@ */

static int uniwill_calls, uniwill_status;
static unsigned int uniwill_command;
static unsigned long uniwill_argument;
static long uniwill_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	++uniwill_calls;
	uniwill_command = cmd;
	uniwill_argument = arg;
	return uniwill_status;
}
static u32 id_check_clevo, id_check_uniwill;
static int uniwill_webcam_calls;
static long uniwill_webcam_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	++uniwill_webcam_calls;
	return -EIO;
}
static u32 clevo_identify(void) { return 1; }
static u32 uniwill_identify(void) { return 0; }
static struct { const char *version; } test_module = { "test-version" };
#define THIS_MODULE (&test_module)
/* @DRIVER_IOCTL_ENTRY@ */

static const unsigned int read_commands[] = {
	R_CL_FANINFO1, R_CL_FANINFO2, R_CL_FANINFO3,
	R_CL_WEBCAM_SW, R_CL_FLIGHTMODE_SW, R_CL_TOUCHPAD_SW
};
static const u8 read_methods[] = {
	CLEVO_CMD_GET_FANINFO1, CLEVO_CMD_GET_FANINFO2, CLEVO_CMD_GET_FANINFO3,
	CLEVO_CMD_GET_WEBCAM_SW, CLEVO_CMD_GET_FLIGHTMODE_SW, CLEVO_CMD_GET_TOUCHPAD_SW
};
static const unsigned int write_commands[] = {
	W_CL_FANSPEED, W_CL_FANAUTO, W_CL_WEBCAM_SW,
	W_CL_FLIGHTMODE_SW, W_CL_TOUCHPAD_SW, W_CL_PERF_PROFILE
};
static const u8 write_methods[] = {
	CLEVO_CMD_SET_FANSPEED_VALUE, CLEVO_CMD_SET_FANSPEED_AUTO, CLEVO_CMD_GET_WEBCAM_SW,
	CLEVO_CMD_SET_FLIGHTMODE_SW, CLEVO_CMD_SET_TOUCHPAD_SW, CLEVO_CMD_OPT
};
static const int errors[] = { -EIO, -ENODEV, -ENODATA, -ENOMEM, -EINVAL, -ETIMEDOUT, -1 };
static const u32 payloads[] = { 0, 1, 0x9abcde01, 0x80000000, 0xffffffff };
#define COUNT(array) (sizeof(array) / sizeof((array)[0]))

static void reset(void)
{
	product_sku = "mock-clevo";
	interface_status = interface_calls = 0;
	input_fault = output_fault = 0;
	input_copies = output_copies = 0;
	input_size = output_size = 0;
	method_calls = sleeps = uniwill_calls = uniwill_webcam_calls = 0;
	id_check_clevo = id_check_uniwill = 0;
	uniwill_status = 0;
	uniwill_command = 0;
	uniwill_argument = 0;
	sleep_duration = 0;
	memset(statuses, 0, sizeof(statuses));
	memset(methods, 0, sizeof(methods));
	memset(arguments, 0, sizeof(arguments));
	memset(results, 0, sizeof(results));
}

static long ioctl_value(unsigned int cmd, u32 *value)
{
	return fop_ioctl(NULL, cmd, (unsigned long)value);
}

static void read_success(void)
{
	for (size_t c = 0; c < COUNT(read_commands); ++c)
		for (size_t p = 0; p < COUNT(payloads); ++p) {
			u32 value = 0x12345678;
			reset();
			results[0] = payloads[p];
			assert(ioctl_value(read_commands[c], &value) == 0);
			assert(value == payloads[p]);
			assert(method_calls == 1 && methods[0] == read_methods[c]);
			assert(arguments[0] == 0 && output_copies == 1 && output_size == sizeof(u32));
			assert(input_copies == 0 && sleeps == 0 && uniwill_calls == 0);
		}
}

static void read_errors(void)
{
	for (size_t c = 0; c < COUNT(read_commands); ++c)
		for (size_t e = 0; e < COUNT(errors); ++e) {
			u32 value = 0x12345678;
			reset();
			statuses[0] = errors[e];
			results[0] = 0xdeadbeef;
			assert(ioctl_value(read_commands[c], &value) == errors[e]);
			assert(value == 0x12345678 && output_copies == 0 && input_copies == 0);
			assert(method_calls == 1 && methods[0] == read_methods[c] && uniwill_calls == 0);
		}
}

static void read_copy_faults(void)
{
	for (size_t c = 0; c < COUNT(read_commands); ++c)
		for (unsigned long fault = 1; fault <= sizeof(u32); ++fault) {
			u32 value = 0x12345678;
			reset();
			output_fault = fault;
			results[0] = 0xdeadbeef;
			assert(ioctl_value(read_commands[c], &value) == -EFAULT);
			assert(method_calls == 1 && output_copies == 1 && output_size == sizeof(u32));
			assert(input_copies == 0 && uniwill_calls == 0);
			if (fault == sizeof(u32))
				assert(value == 0x12345678);
		}
}

static void interface_strings(void)
{
	for (int missing = 0; missing <= 1; ++missing) {
		char value[32];
		reset();
		memset(value, 'X', sizeof(value));
		interface_status = missing ? -ENODEV : 0;
		assert(fop_ioctl(NULL, R_CL_HW_IF_STR, (unsigned long)value) == 0);
		assert(strcmp(value, missing ? "" : interface_name) == 0);
		assert(output_size == (missing ? 1 : sizeof(interface_name)));
		assert(interface_calls == 1 && output_copies == 1 && method_calls == 0);
		assert(input_copies == 0 && sleeps == 0 && uniwill_calls == 0);
	}
}

static void interface_copy_faults(void)
{
	for (int missing = 0; missing <= 1; ++missing)
		for (unsigned long fault = 1; fault <= (missing ? 1 : sizeof(interface_name)); ++fault) {
			char value[32];
			reset();
			memset(value, 'X', sizeof(value));
			interface_status = missing ? -ENODEV : 0;
			output_fault = fault;
			assert(fop_ioctl(NULL, R_CL_HW_IF_STR, (unsigned long)value) == -EFAULT);
			assert(interface_calls == 1 && output_copies == 1 && method_calls == 0);
			assert(input_copies == 0 && uniwill_calls == 0);
		}
}

static void write_copy_faults(void)
{
	for (size_t c = 0; c < COUNT(write_commands); ++c)
		for (unsigned long fault = 1; fault <= sizeof(u32); ++fault) {
			u32 value = 0xffffffff;
			reset();
			input_fault = fault;
			assert(ioctl_value(write_commands[c], &value) == -EFAULT);
			assert(input_copies == 1 && input_size == sizeof(u32));
			assert(method_calls == 0 && output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
		}
}

static void write_errors(void)
{
	for (size_t c = 0; c < COUNT(write_commands); ++c)
		for (size_t e = 0; e < COUNT(errors); ++e) {
			u32 value = 0xdeadbeef;
			reset();
			statuses[0] = errors[e];
			assert(ioctl_value(write_commands[c], &value) == errors[e]);
			assert(input_copies == 1 && input_size == sizeof(u32));
			assert(method_calls == 1 && methods[0] == write_methods[c]);
			assert(output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
		}
}

static void positive_status(void)
{
	/* Actual integer WMI/ACPI producers return 0 or a negative errno.
	 * Do not mistake an unexpected positive status for a successful operation,
	 * convert it to an invented errno, or continue dependent copy/write/delay. */
	for (size_t c = 0; c < COUNT(read_commands); ++c) {
		u32 value = 0x12345678;
		reset();
		statuses[0] = 1;
		assert(ioctl_value(read_commands[c], &value) == 1);
		assert(value == 0x12345678 && output_copies == 0 && uniwill_calls == 0);
	}
	for (size_t c = 0; c < COUNT(write_commands); ++c) {
		u32 value = 0xdeadbeef;
		reset();
		statuses[0] = 1;
		assert(ioctl_value(write_commands[c], &value) == 1);
		assert(method_calls == 1 && sleeps == 0 && uniwill_calls == 0);
	}
	u32 value = 1;
	reset();
	statuses[1] = 1;
	assert(ioctl_value(W_CL_WEBCAM_SW, &value) == 1);
	assert(method_calls == 2 && methods[1] == CLEVO_CMD_SET_WEBCAM_SW && uniwill_calls == 0);
}

static u32 mapped_speed(u32 value)
{
	const u32 half_minimum = FAN_ON_MIN_SPEED_PERCENT * NB01_FAN_SPEED_MAX / 2 / 100;
	const u32 minimum = FAN_ON_MIN_SPEED_PERCENT * NB01_FAN_SPEED_MAX / 100;
	return value < half_minimum ? 0 : value < minimum ? minimum : value;
}

static void fan_mapping(void)
{
	for (unsigned int position = 0; position < 3; ++position)
		for (u32 speed = 0; speed <= 255; ++speed) {
			/* Other two fans stay above the minimum and have distinct bytes.
			 * The fourth input byte must retain its existing ignored behavior. */
			u32 value = (0xabf0c080 & ~(0xffu << (position * 8))) | (speed << (position * 8));
			u32 expected = 0;
			for (unsigned int fan = 0; fan < 3; ++fan)
				expected |= mapped_speed((value >> (fan * 8)) & 0xff) << (fan * 8);
			reset();
			assert(ioctl_value(W_CL_FANSPEED, &value) == 0);
			assert(method_calls == 1 && methods[0] == CLEVO_CMD_SET_FANSPEED_VALUE);
			assert(arguments[0] == expected && sleeps == 1 && sleep_duration == 100);
			assert(input_size == sizeof(u32) && output_copies == 0 && uniwill_calls == 0);
		}
}

static void fan_delay(void)
{
	u32 value = 0x7f7f7f;
	reset();
	assert(ioctl_value(W_CL_FANSPEED, &value) == 0);
	assert(method_calls == 1 && sleeps == 1 && sleep_duration == 100);
	reset();
	statuses[0] = -EIO;
	assert(ioctl_value(W_CL_FANSPEED, &value) == -EIO);
	assert(method_calls == 1 && sleeps == 0);
	reset();
	assert(ioctl_value(W_CL_FANAUTO, &value) == 0);
	assert(method_calls == 1 && sleeps == 0);
}

static void write_payloads(void)
{
	const unsigned int commands[] = { W_CL_FANAUTO, W_CL_FLIGHTMODE_SW, W_CL_TOUCHPAD_SW };
	const u8 expected_methods[] = { CLEVO_CMD_SET_FANSPEED_AUTO, CLEVO_CMD_SET_FLIGHTMODE_SW, CLEVO_CMD_SET_TOUCHPAD_SW };
	for (size_t c = 0; c < COUNT(commands); ++c)
		for (size_t p = 0; p < COUNT(payloads); ++p) {
			u32 value = payloads[p];
			reset();
			assert(ioctl_value(commands[c], &value) == 0);
			assert(method_calls == 1 && methods[0] == expected_methods[c]);
			assert(arguments[0] == payloads[p] && input_size == sizeof(u32));
			assert(output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
		}
}

static void performance_profile(void)
{
	for (u32 profile = 0; profile <= 255; ++profile) {
		u32 value = 0xdeadbe00 | profile;
		reset();
		assert(ioctl_value(W_CL_PERF_PROFILE, &value) == 0);
		assert(method_calls == 1 && methods[0] == CLEVO_CMD_OPT);
		assert(arguments[0] == (((u32)CLEVO_CMD_OPT_SUB_SET_PERF_PROF << 24) | profile));
		assert(output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
	}
}

static void webcam_get_errors(void)
{
	for (size_t e = 0; e < COUNT(errors); ++e)
		for (u32 bit = 0; bit <= 1; ++bit) {
			u32 value = 0xdeadbe00 | bit;
			reset();
			statuses[0] = errors[e];
			results[0] = bit ^ 1;
			assert(ioctl_value(W_CL_WEBCAM_SW, &value) == errors[e]);
			assert(method_calls == 1 && methods[0] == CLEVO_CMD_GET_WEBCAM_SW);
			assert(output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
		}
}

static void webcam_noop(void)
{
	for (u32 low = 0; low <= 255; ++low) {
		u32 value = 0xdeadbe00 | low;
		reset();
		results[0] = 0x87654320 | (low & 1);
		assert(ioctl_value(W_CL_WEBCAM_SW, &value) == 0);
		assert(method_calls == 1 && methods[0] == CLEVO_CMD_GET_WEBCAM_SW);
		assert(arguments[0] == 0 && output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
	}
}

static void webcam_set(void)
{
	for (size_t p = 0; p < COUNT(payloads); ++p) {
		u32 value = payloads[p];
		reset();
		results[0] = (value ^ 1) & 1;
		assert(ioctl_value(W_CL_WEBCAM_SW, &value) == 0);
		assert(method_calls == 2 && methods[0] == CLEVO_CMD_GET_WEBCAM_SW);
		assert(methods[1] == CLEVO_CMD_SET_WEBCAM_SW && arguments[1] == payloads[p]);
		assert(output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
	}
	for (size_t e = 0; e < COUNT(errors); ++e) {
		u32 value = 0xdeadbeef;
		reset();
		statuses[1] = errors[e];
		assert(ioctl_value(W_CL_WEBCAM_SW, &value) == errors[e]);
		assert(method_calls == 2 && methods[1] == CLEVO_CMD_SET_WEBCAM_SW);
		assert(arguments[1] == value && output_copies == 0 && uniwill_calls == 0);
	}
}

static void webcam_dmi(void)
{
	const char *models[] = { "AURA14GEN3", "AURA15GEN3", "AURA14GEN4 / AURA15GEN4" };
	for (size_t m = 0; m < COUNT(models); ++m) {
		u32 value = 1;
		reset();
		product_sku = models[m];
		assert(ioctl_value(R_CL_WEBCAM_SW, &value) == -ENODEV);
		assert(method_calls == 0 && input_copies == 0 && output_copies == 0 && uniwill_calls == 0);
		reset();
		product_sku = models[m];
		if (m < 2) {
			assert(ioctl_value(W_CL_WEBCAM_SW, &value) == -ENODEV);
			assert(method_calls == 0 && input_copies == 0 && output_copies == 0 && uniwill_calls == 0);
		} else {
			/* Existing Gen4 policy blocks GET ioctl but not the SET ioctl. */
			assert(ioctl_value(W_CL_WEBCAM_SW, &value) == 0);
			assert(input_copies == 1 && method_calls == 2 && uniwill_calls == 0);
		}
	}
}

static void reject_command(unsigned int cmd)
{
	u32 value[16] = {0x12345678};
	reset();
	assert(ioctl_value(cmd, value) == -ENOTTY);
	assert(clevo_ioctl_interface(NULL, cmd, (unsigned long)value) == -ENOTTY);
	assert(value[0] == 0x12345678 && method_calls == 0 && interface_calls == 0);
	assert(input_copies == 0 && output_copies == 0 && sleeps == 0 && uniwill_calls == 0);
}

static void unknown_commands(void)
{
	const unsigned int commands[] = {
		0, 0xffffffff, _IOR(MAGIC_READ_CL, 0xfe, int32_t *),
		_IOW(MAGIC_WRITE_CL, 0xfe, int32_t *),
		_IOR(IOCTL_MAGIC, 0xfe, int32_t *)
	};
	for (size_t c = 0; c < COUNT(commands); ++c)
		reject_command(commands[c]);
}

static void malformed_commands(void)
{
	const unsigned int commands[] = {
		R_MOD_VERSION, R_HWCHECK_CL, R_HWCHECK_UW, R_CL_HW_IF_STR,
		R_CL_FANINFO1, R_CL_FANINFO2, R_CL_FANINFO3,
		R_CL_WEBCAM_SW, R_CL_FLIGHTMODE_SW, R_CL_TOUCHPAD_SW,
		W_CL_FANSPEED, W_CL_FANAUTO, W_CL_WEBCAM_SW,
		W_CL_FLIGHTMODE_SW, W_CL_TOUCHPAD_SW, W_CL_PERF_PROFILE
	};
	for (size_t c = 0; c < COUNT(commands); ++c) {
		/* Keep the command number but corrupt one encoded field at a time. */
		reject_command(commands[c] ^ ((unsigned int)_IOC_READ << _IOC_DIRSHIFT));
		reject_command(commands[c] ^ (1U << _IOC_SIZESHIFT));
		reject_command(_IOC(_IOC_DIR(commands[c]), 0xff,
				    _IOC_NR(commands[c]), _IOC_SIZE(commands[c])));
	}
}

static void debug_command_routing(void)
{
	/* Freeze the historical encoding, including the read command's _IOW. */
	const unsigned int commands[] = {
		_IOW(MAGIC_READ_CL, 0x91, uint32_t *),
		_IOW(MAGIC_WRITE_CL, 0x91, uint32_t *)
	};
	for (size_t c = 0; c < COUNT(commands); ++c) {
		u32 value[10] = {0x51, 0x07, 0x34};
		reset();
		uniwill_status = -EIO;
#ifdef DEBUG
		assert(ioctl_value(commands[c], value) == -EIO);
		assert(uniwill_calls == 1 && uniwill_command == commands[c]);
		assert(uniwill_argument == (unsigned long)value);
#else
		assert(ioctl_value(commands[c], value) == -ENOTTY);
		assert(uniwill_calls == 0);
#endif
		assert(clevo_ioctl_interface(NULL, commands[c], (unsigned long)value) == -ENOTTY);
		assert(method_calls == 0 && interface_calls == 0);
		assert(input_copies == 0 && output_copies == 0 && sleeps == 0);
		reject_command(commands[c] ^ ((unsigned int)_IOC_READ << _IOC_DIRSHIFT));
		reject_command(commands[c] ^ (1U << _IOC_SIZESHIFT));
	}
}

static void webcam_platform_route(void)
{
	u32 value = 1;

	reset();
	id_check_clevo = 1;
	id_check_uniwill = 1;
	results[0] = 0;
	assert(ioctl_value(W_CL_WEBCAM_SW, &value) == 0);
	assert(method_calls == 2 && methods[0] == CLEVO_CMD_GET_WEBCAM_SW);
	assert(methods[1] == CLEVO_CMD_SET_WEBCAM_SW && arguments[1] == 1);
	assert(uniwill_webcam_calls == 0);

	reset();
	id_check_clevo = 0;
	id_check_uniwill = 1;
	results[0] = 1;
	assert(ioctl_value(W_CL_WEBCAM_SW, &value) == -EIO);
	assert(method_calls == 0 && uniwill_webcam_calls == 1);
	assert(input_copies == 0 && output_copies == 0);
	assert(ioctl_value(R_CL_WEBCAM_SW, &value) == -EIO);
	assert(method_calls == 0 && uniwill_webcam_calls == 2);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
#define CASE(name) if (strcmp(argv[1], #name) == 0) { name(); return 0; }
	CASE(read_success)
	CASE(read_errors)
	CASE(read_copy_faults)
	CASE(interface_strings)
	CASE(interface_copy_faults)
	CASE(write_copy_faults)
	CASE(write_errors)
	CASE(positive_status)
	CASE(fan_mapping)
	CASE(fan_delay)
	CASE(write_payloads)
	CASE(performance_profile)
	CASE(webcam_get_errors)
	CASE(webcam_noop)
	CASE(webcam_set)
	CASE(webcam_dmi)
	CASE(webcam_platform_route)
	CASE(unknown_commands)
	CASE(malformed_commands)
	CASE(debug_command_routing)
	assert(!"Unknown testcase");
}
