/* Exact production ioctl functions are injected below. The only services here
 * are userspace spies: no devices, sysfs files, modules or firmware are used. */
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

/* @REAL_INTERFACE_TYPES@ */

static struct uniwill_device_features_t features;
static struct uniwill_device_features_t *uw_feats;
static struct uniwill_device_features_t *provider_features = &features;
static bool features_ready;
static int minimums[] = { 5, 6, 7 };
static int maximums[] = { 80, 90, 200 };
static int *tdp_min_defs;
static int *tdp_max_defs;
static int interface_status = -ENODEV;
static int interface_calls, feature_calls, table_calls;
static int input_fault, output_fault, input_copies, output_copies;
static int ec_status, ec_reads, ec_writes, tdp_calls, mode_calls, fan_calls;
static int provider_status;
static u8 ec_value = 64, tdp_index_seen, tdp_value_seen;
static u8 clear_seen, set_seen;
static int uniwill_identify_lock;
static void mutex_lock(int *lock) { assert(!*lock); *lock = 1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock = 0; }

static int uniwill_get_active_interface_id(char **name)
{
	++interface_calls;
	if (!interface_status && name)
		*name = "mock-uniwill";
	return interface_status;
}

static struct uniwill_device_features_t *uniwill_get_device_features(void)
{
	++feature_calls;
	return provider_features;
}

static bool uniwill_device_features_ready(void)
{
	return features_ready;
}

/* TDP model mapping itself is unchanged. The actual identify function passes
 * the model before publishing uw_feats. */
static void uw_id_tdp(u8 model)
{
	assert(model == features.model);
	++table_calls;
	tdp_min_defs = minimums;
	tdp_max_defs = maximums;
}

static unsigned long copy_to_user(void *destination, const void *source, size_t length)
{
	++output_copies;
	if (output_fault)
		return 1;
	assert(destination && source);
	memcpy(destination, source, length);
	return 0;
}

static unsigned long copy_from_user(void *destination, const void *source, size_t length)
{
	++input_copies;
	if (input_fault)
		return 1;
	assert(destination && source);
	memcpy(destination, source, length);
	return 0;
}

static int uniwill_read_ec_ram(u16 address, u8 *value)
{
	(void)address;
	++ec_reads;
	if (ec_status)
		return ec_status;
	*value = ec_value;
	return 0;
}

#ifdef DEBUG
static int uniwill_write_ec_ram(u16 address, u8 value)
{
	(void)address;
	(void)value;
	++ec_writes;
	return provider_status;
}
#endif

static int uw_write_tdp(u8 index, u8 value)
{
	++tdp_calls;
	tdp_index_seen = index;
	tdp_value_seen = value;
	return provider_status;
}

static int uw_update_mode(u8 clear, u8 set)
{
	++mode_calls;
	clear_seen = clear;
	set_seen = set;
	return provider_status;
}

static int uw_set_mode(u8 value)
{
	(void)value;
	++mode_calls;
	return provider_status;
}

static u32 uw_set_fan(u32 index, u8 value)
{
	(void)index;
	(void)value;
	++fan_calls;
	return provider_status;
}

static u32 uw_set_fan_auto(void)
{
	++fan_calls;
	return provider_status;
}

struct file { int unused; };
static struct { const char *version; } mock_module = { "binding-test" };
#define THIS_MODULE (&mock_module)
static u32 id_check_clevo, id_check_uniwill;
static u32 clevo_identify(void) { return 0; }
static int clevo_calls, webcam_calls;
static long clevo_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	++clevo_calls;
	return -ENOTTY;
}

/* Also present for the unrelated, uncommitted webcam implementation. The
 * fixture must work unchanged against HEAD or the original dirty source. */
static __attribute__((unused)) long uniwill_webcam_ioctl(struct file *file,
						       unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	++webcam_calls;
	return -ENOTTY;
}

/* @REAL_DRIVER_FUNCTIONS@ */

#define COUNT(array) (sizeof(array) / sizeof((array)[0]))
#define IOCTL(command, value) fop_ioctl(NULL, command, (unsigned long)&(value))
static const unsigned int tdp_read_commands[] = { R_UW_TDP0, R_UW_TDP1, R_UW_TDP2 };
static const unsigned int tdp_write_commands[] = { W_UW_TDP0, W_UW_TDP1, W_UW_TDP2 };
static const unsigned int fan_read_commands[] = { R_UW_FANSPEED, R_UW_FANSPEED2 };

static void no_hardware_or_binding(void)
{
	assert(ec_reads == 0 && ec_writes == 0);
	assert(tdp_calls == 0 && mode_calls == 0 && fan_calls == 0);
	assert(feature_calls == 0 && table_calls == 0);
}

static void bind(void)
{
	u32 value = 0xdeadbeef;
	int interfaces_before = interface_calls, features_before = feature_calls;
	int tables_before = table_calls;

	interface_status = 0;
	features.model = 42;
	features_ready = true;
	features.uniwill_has_double_pl4 = true;
	features.uniwill_has_universal_ec_fan_control = true;
	features.uniwill_profile_v1_three_profs = true;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 1);
	assert(id_check_uniwill == 1 && uw_feats == &features);
	assert(interface_calls == interfaces_before + 1 &&
	       feature_calls == features_before + 1 &&
	       table_calls == tables_before + 1);
	assert(tdp_min_defs == minimums && tdp_max_defs == maximums);
}

static void unbound_metadata(void)
{
	u32 value = 0xdeadbeef;
	assert(IOCTL(R_UW_MODEL_ID, value) == -ENODEV);
	assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == -ENODEV);
	assert(uw_get_performance_profile_count() == 0);
	value = PROFILE_ENTHUSIAST;
	assert(IOCTL(W_UW_PERF_PROF, value) == -ENODEV);
	assert(uw_set_performance_profile_v1(PROFILE_POWERSAVE) == -ENODEV);
	assert(output_copies == 0 && input_copies == 1);
	/* Model, profile and valid profile-write queries each retry the failed
	 * startup identification; validation still happens before the probe. */
	assert(interface_calls == 3);
	no_hardware_or_binding();
}

static void unbound_fans(void)
{
	u32 value = 0xdeadbeef;
	for (size_t i = 0; i < COUNT(fan_read_commands); ++i)
		assert(IOCTL(fan_read_commands[i], value) == -ENODEV);
	assert(value == 0xdeadbeef && input_copies == 0 && output_copies == 0);
	assert(interface_calls == 2);
	no_hardware_or_binding();
}

static void unbound_tdp(void)
{
	u32 value = 40;
	/* A table is not a feature binding. Exercise the defensive boundary even
	 * if table metadata is present, and for every index (including non-PL4). */
	tdp_min_defs = minimums;
	tdp_max_defs = maximums;
	for (u8 i = 0; i < 3; ++i) {
		assert(IOCTL(tdp_read_commands[i], value) == -ENODEV);
		assert(IOCTL(tdp_write_commands[i], value) == -ENODEV);
		assert(uw_get_tdp(i) == -ENODEV);
		assert(uw_set_tdp(i, 40) == -ENODEV);
	}
	/* Limit metadata helpers do not dereference features. */
	assert(uw_get_tdp_min(0) == 5 && uw_get_tdp_max(2) == 200);
	assert(value == 40 && input_copies == 3 && output_copies == 0);
	/* Three reads and three writes retry identification; the provider is
	 * absent, so no feature read or EC access follows. */
	assert(interface_calls == 6);
	no_hardware_or_binding();
}

static void unbound_validation(void)
{
	u32 value;
	tdp_min_defs = minimums;
	tdp_max_defs = maximums;
	assert(uw_get_tdp_min(3) == -EINVAL);
	assert(uw_get_tdp_max(3) == -EINVAL);
	assert(uw_get_tdp(3) == -EINVAL);
	assert(uw_set_tdp(3, 40) == -EINVAL);
	assert(uw_set_tdp(0, 4) == -EINVAL);
	assert(uw_set_tdp(0, 81) == -EINVAL);
	for (size_t i = 0; i < COUNT(tdp_write_commands); ++i) {
		value = UINT32_MAX;
		assert(IOCTL(tdp_write_commands[i], value) == -EINVAL);
	}
	const u32 invalid_profiles[] = { 0, 4, 0x101, UINT32_MAX };
	for (size_t i = 0; i < COUNT(invalid_profiles); ++i) {
		value = invalid_profiles[i];
		assert(IOCTL(W_UW_PERF_PROF, value) == -EINVAL);
	}
	assert(uw_set_performance_profile_v1(0) == -EINVAL);
	assert(uw_set_performance_profile_v1(4) == -EINVAL);
	/* Missing limit support still wins over argument-range validation. */
	tdp_min_defs = NULL;
	assert(uw_set_tdp(0, 4) == -ENODEV);
	tdp_min_defs = minimums;
	tdp_max_defs = NULL;
	assert(uw_set_tdp(0, 81) == -ENODEV);
	assert(interface_calls == 0 && output_copies == 0);
	no_hardware_or_binding();
}

static void unbound_copy_faults(void)
{
	u32 value = 0;
	const unsigned int writes[] = { W_UW_TDP0, W_UW_TDP1, W_UW_TDP2, W_UW_PERF_PROF };
	input_fault = 1;
	for (size_t i = 0; i < COUNT(writes); ++i)
		assert(IOCTL(writes[i], value) == -EFAULT);
	assert(input_copies == 4 && output_copies == 0 && interface_calls == 0);
	no_hardware_or_binding();
}

static void independent_commands(void)
{
	u32 value = 0;
	char text[32];
	assert(IOCTL(R_UW_FANS_OFF_AVAILABLE, value) == 0 && value == 1);
	assert(IOCTL(R_UW_FANS_MIN_SPEED, value) == 0 && value == FAN_ON_MIN_SPEED_PERCENT);
	assert(IOCTL(R_MOD_VERSION, text) == 0 && strcmp(text, "binding-test") == 0);
	assert(IOCTL(R_UW_HW_IF_STR, text) == 0 && text[0] == '\0');
	interface_status = 0;
	assert(IOCTL(R_UW_HW_IF_STR, text) == 0 && strcmp(text, "mock-uniwill") == 0);
	assert(interface_calls == 2);
	assert(fop_ioctl(NULL, W_UW_MODE_ENABLE, 0) == 0);
	output_fault = 1;
	assert(IOCTL(R_UW_FANS_MIN_SPEED, value) == -EFAULT);
	assert(IOCTL(R_UW_HW_IF_STR, text) == -EFAULT);
	assert(input_copies == 0 && uw_feats == NULL);
	no_hardware_or_binding();
}

static void unknown_commands(void)
{
	u32 value = 0xdeadbeef;
	const unsigned int unknown[] = {
		0, UINT32_MAX, _IOR(MAGIC_READ_UW, 0xfe, int32_t *),
		_IOW(MAGIC_WRITE_UW, 0xfe, int32_t *)
	};
	const unsigned int known[] = {
		R_UW_MODEL_ID, R_UW_FANSPEED, R_UW_FANSPEED2, R_UW_PROFS_AVAILABLE,
		R_UW_TDP0, R_UW_TDP1, R_UW_TDP2, W_UW_TDP0, W_UW_TDP1,
		W_UW_TDP2, W_UW_PERF_PROF, W_UW_MODE_ENABLE
	};
	for (size_t i = 0; i < COUNT(unknown); ++i) {
		assert(IOCTL(unknown[i], value) == -ENOTTY);
		assert(uniwill_ioctl_interface(NULL, unknown[i], (unsigned long)&value) == -ENOTTY);
	}
	for (size_t i = 0; i < COUNT(known); ++i) {
		unsigned int malformed[] = {
			known[i] ^ ((unsigned int)_IOC_READ << _IOC_DIRSHIFT),
			known[i] ^ (1u << _IOC_SIZESHIFT),
			_IOC(_IOC_DIR(known[i]), 0xff, _IOC_NR(known[i]), _IOC_SIZE(known[i]))
		};
		for (size_t j = 0; j < COUNT(malformed); ++j)
			assert(IOCTL(malformed[j], value) == -ENOTTY);
	}
	assert(value == 0xdeadbeef && input_copies == 0 && output_copies == 0);
	assert(interface_calls == 0);
	no_hardware_or_binding();
}

static void identify_absent(void)
{
	u32 value = 0xdeadbeef;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 0);
	assert(uw_feats == NULL && id_check_uniwill == 0 && interface_calls == 1);
	assert(IOCTL(R_UW_MODEL_ID, value) == -ENODEV);
	assert(value == 0 && output_copies == 1);
	assert(interface_calls == 2);
	no_hardware_or_binding();
}

static void identify_not_ready(void)
{
	u32 value = 0xdeadbeef;
	interface_status = 0;
	features.model = 42;
	features_ready = false;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 0);
	assert(uw_feats == NULL && feature_calls == 1 && table_calls == 0);
	features_ready = true;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 1);
	assert(uw_feats == &features && feature_calls == 2 && table_calls == 1);
}

static void identify_null_provider(void)
{
	u32 value = 0xdeadbeef;
	interface_status = 0;
	provider_features = NULL;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 0);
	assert(uw_feats == NULL && id_check_uniwill == 0);
	assert(interface_calls == 1 && feature_calls == 1 && table_calls == 0);
	assert(tdp_min_defs == NULL && tdp_max_defs == NULL);
	assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == -ENODEV);
	assert(interface_calls == 2 && feature_calls == 2);
	assert(ec_reads == 0 && ec_writes == 0 && tdp_calls == 0 && mode_calls == 0);
}

static void late_binding(void)
{
	u32 value = 0;
	assert(IOCTL(R_UW_MODEL_ID, value) == -ENODEV);
	bind();
	assert(IOCTL(R_UW_MODEL_ID, value) == 0 && value == 42);
	assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 3);
	ec_value = 1;
	assert(IOCTL(R_UW_FANSPEED, value) == 0 && value == 0);
	assert(IOCTL(R_UW_FANSPEED2, value) == 0 && value == 0);
	ec_value = 64;
	assert(IOCTL(R_UW_TDP2, value) == 0 && value == 128);
	value = 129;
	assert(IOCTL(W_UW_TDP2, value) == 0);
	assert(tdp_calls == 1 && tdp_index_seen == 2 && tdp_value_seen == 64);
	value = PROFILE_OVERBOOST;
	assert(IOCTL(W_UW_PERF_PROF, value) == 0);
	assert(mode_calls == 1 && clear_seen == 0xb0 && set_seen == 0x10);
	/* The first model query retried identification before R_HWCHECK_UW. */
	assert(interface_calls == 2 && feature_calls == 1 && table_calls == 1);
	assert(ec_reads == 3 && ec_writes == 0);
}

static void disconnect(void)
{
	u32 value = 0;
	bind();
	interface_status = -ENODEV;
	ec_status = -ENODEV;
	provider_status = -ENODEV;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 0);
	/* Preserve the preexisting metadata lifetime: provider features are
	 * static, while actual transport/provider operations report absence. */
	assert(uw_feats == &features && id_check_uniwill == 0);
	assert(IOCTL(R_UW_MODEL_ID, value) == 0 && value == 42);
	assert(IOCTL(R_UW_PROFS_AVAILABLE, value) == 0 && value == 3);
	for (size_t i = 0; i < COUNT(fan_read_commands); ++i)
		assert(IOCTL(fan_read_commands[i], value) == -ENODEV);
	assert(IOCTL(R_UW_TDP2, value) == -ENODEV);
	value = 40;
	assert(IOCTL(W_UW_TDP2, value) == -ENODEV);
	assert(interface_calls == 2 && feature_calls == 1 && table_calls == 1);
}

static void reprobe_null_provider(void)
{
	u32 value = 0;
	bind();
	provider_features = NULL;
	assert(IOCTL(R_HWCHECK_UW, value) == 0 && value == 0);
	assert(id_check_uniwill == 0 && uw_feats == &features);
	assert(feature_calls == 2 && table_calls == 1);
	assert(IOCTL(R_UW_MODEL_ID, value) == 0 && value == 42);
	assert(tdp_min_defs == minimums && tdp_max_defs == maximums);
}

static void bound_failures(void)
{
	u32 value = 0;
	bind();
	output_fault = 1;
	const unsigned int reads[] = {
		R_UW_MODEL_ID, R_UW_PROFS_AVAILABLE, R_UW_FANSPEED, R_UW_FANSPEED2, R_UW_TDP2
	};
	for (size_t i = 0; i < COUNT(reads); ++i)
		assert(IOCTL(reads[i], value) == -EFAULT);
	output_fault = 0;
	ec_status = -ETIMEDOUT;
	value = 0xdeadbeef;
	const int outputs = output_copies;
	assert(IOCTL(R_UW_FANSPEED, value) == -ETIMEDOUT);
	assert(IOCTL(R_UW_FANSPEED2, value) == -ETIMEDOUT);
	assert(IOCTL(R_UW_TDP2, value) == -ETIMEDOUT);
	assert(value == 0xdeadbeef && output_copies == outputs);
	provider_status = -EIO;
	value = 40;
	assert(IOCTL(W_UW_TDP2, value) == -EIO);
	value = PROFILE_ENTHUSIAST;
	assert(IOCTL(W_UW_PERF_PROF, value) == -EIO);
	assert(interface_calls == 1 && feature_calls == 1 && table_calls == 1);
}

static void debug_aliases(void)
{
#ifdef DEBUG
	u32 arguments[10] = { 0x51, 0x07, 0x34 };
	assert(IOCTL(R_TF_BC, arguments) == 0 && arguments[0] == ec_value);
	arguments[0] = 0x51;
	assert(IOCTL(W_TF_BC, arguments) == 0 && arguments[0] == 0);
	assert(ec_reads == 1 && ec_writes == 1 && input_copies == 2 && output_copies == 2);
#endif
	assert(uw_feats == NULL && interface_calls == 0 && feature_calls == 0 && table_calls == 0);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
#define CASE(name) if (strcmp(argv[1], #name) == 0) { name(); goto done; }
	CASE(unbound_metadata)
	CASE(unbound_fans)
	CASE(unbound_tdp)
	CASE(unbound_validation)
	CASE(unbound_copy_faults)
	CASE(independent_commands)
	CASE(unknown_commands)
	CASE(identify_absent)
	CASE(identify_not_ready)
	CASE(identify_null_provider)
	CASE(late_binding)
	CASE(disconnect)
	CASE(reprobe_null_provider)
	CASE(bound_failures)
	CASE(debug_aliases)
	return 2;
done:
	assert(clevo_calls == 0 && webcam_calls == 0);
	return 0;
}
