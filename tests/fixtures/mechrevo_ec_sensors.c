/* Kernel API doubles; the complete production translation unit follows. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef void *acpi_handle;
typedef int acpi_status;
#define ACPI_TYPE_INTEGER 1
#define ACPI_FAILURE(x) ((x) != 0)
union acpi_object { int type; struct { int type; unsigned long long value; } integer; };
struct acpi_object_list { unsigned count; union acpi_object *pointer; };
#define DEFINE_MUTEX(x) int x
static void mutex_lock(int *lock) { assert(!*lock); *lock = 1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock = 0; }
static int handle_error, method_missing, acpi_calls, acpi_fail_at, acpi_range_at;
static int low_b_reads, low_d_reads;
static u8 project_id = 0x10, capability = 0xec;
static unsigned long long rpm_bytes[4] = {15, 38, 19, 75};
static u8 temps[2];
static u8 high_script[6];
static unsigned high_script_count, high_script_position;
static acpi_status acpi_get_handle(acpi_handle parent, const char *path, acpi_handle *handle)
{ assert(!parent && !strcmp(path, "\\_SB.INOU")); *handle = (void *)1; return handle_error; }
static bool acpi_has_method(acpi_handle handle, const char *method)
{ assert(handle == (void *)1 && !strcmp(method, "ECRR")); return !method_missing; }
static acpi_status acpi_evaluate_integer(acpi_handle handle, const char *method,
    struct acpi_object_list *args, unsigned long long *value)
{
    assert(handle == (void *)1 && !strcmp(method, "ECRR"));
    assert(args->count == 1 && args->pointer->type == ACPI_TYPE_INTEGER);
    acpi_calls++;
    if (acpi_calls == acpi_fail_at) return 1;
    if (acpi_calls == acpi_range_at) { *value = 256; return 0; }
    switch (args->pointer->integer.value) {
    case 0x0740: *value = project_id; break;
    case 0x078e: *value = capability; break;
    case 0x043e: *value = temps[0]; break;
    case 0x044f: *value = temps[1]; break;
    case 0x0464: case 0x046c:
        if (high_script_position < high_script_count)
            *value = high_script[high_script_position++];
        else *value = rpm_bytes[args->pointer->integer.value == 0x0464 ? 0 : 2];
        break;
    case 0x0465: *value = rpm_bytes[1]; break;
    case 0x046b: low_b_reads++; *value = rpm_bytes[3]; break;
    case 0x046d: low_d_reads++; *value = rpm_bytes[3]; break;
    default: assert(false);
    }
    return 0;
}
static void usleep_range(unsigned int min, unsigned int max)
{ assert(min == 6000 && max == 12000); }
typedef unsigned short umode_t;
#define __init
#define __exit
#define module_init(x)
#define module_exit(x)
#define MODULE_DESCRIPTION(x)
#define MODULE_LICENSE(x)
#define MODULE_DEVICE_TABLE(t, x)
#define DMI_SYS_VENDOR 0
#define DMI_PRODUCT_NAME 1
#define DMI_BIOS_VERSION 2
#define DMI_BOARD_NAME 3
struct dmi_system_id { int matches[4]; };
#define DMI_EXACT_MATCH(a,b) (a + 1)
#define PLATFORM_DEVID_NONE (-1)
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
enum hwmon_sensor_types { hwmon_temp, hwmon_fan, hwmon_in };
enum { hwmon_temp_input, hwmon_temp_label, hwmon_temp_max };
enum { hwmon_fan_input, hwmon_fan_label, hwmon_fan_max };
#define HWMON_F_INPUT 1
#define HWMON_F_LABEL 2
#define HWMON_T_INPUT 1
#define HWMON_T_LABEL 2
struct device { int unused; };
struct platform_device { struct device dev; };
struct hwmon_ops {
    umode_t (*is_visible)(const void *, enum hwmon_sensor_types, u32, int);
    int (*read)(struct device *, enum hwmon_sensor_types, u32, int, long *);
    int (*read_string)(struct device *, enum hwmon_sensor_types, u32, int, const char **);
    void *write;
};
struct hwmon_channel_info { int type; const u32 *config; };
#define HWMON_CHANNEL_INFO(stype, ...) \
    (&(const struct hwmon_channel_info){ .type = hwmon_##stype, \
     .config = (const u32[]){__VA_ARGS__, 0} })
struct hwmon_chip_info {
    const struct hwmon_ops *ops;
    const struct hwmon_channel_info *const *info;
};
static const char *identities[][4] = {
    {"MECHREVO", "Kuangshi16Pro Series GM6PX0X", "N.1.09MRO07", "GM6PX0X"},
    {"MECHREVO", "Jiaolong16K Series GM6BG0Q", "N.1.19MRO15", "GM6BG0Q"},
};
#define MODEL_COUNT (sizeof(identities) / sizeof(identities[0]))
static int model_index;
static const char *dmi_values[4];
static int register_ret[2];
static int platform_registers, platform_unregisters, hwmon_registers, hwmon_unregisters;
static struct platform_device mock_platform;
static struct device mock_hwmon;
static char events[16];
static unsigned event_count;
static bool dmi_match(int field, const char *value)
{ return dmi_values[field] && strcmp(dmi_values[field], value) == 0; }
static struct platform_device *platform_device_register_simple(
    const char *name, int id, const void *resources, unsigned count)
{
    assert(strcmp(name, "mechrevo_ec_sensors") == 0);
    assert(id == -1 && resources == NULL && count == 0);
    platform_registers++; events[event_count++] = 'P';
    return register_ret[0] ? ERR_PTR(register_ret[0]) : &mock_platform;
}
static void platform_device_unregister(struct platform_device *device)
{
    assert(device == &mock_platform);
    platform_unregisters++; events[event_count++] = 'p';
}
static struct device *hwmon_device_register_with_info(struct device *parent,
    const char *name, void *data, const struct hwmon_chip_info *chip, const void *groups)
{
    assert(parent == &mock_platform.dev && data == NULL && groups == NULL);
    assert(strcmp(name, "mechrevo_ec") == 0);
    assert(chip->info[0]->type == hwmon_temp && chip->info[1]->type == hwmon_fan && chip->info[2] == NULL);
    assert(chip->info[0]->config[0] == 3 && chip->info[0]->config[1] == 3);
    assert(chip->info[0]->config[2] == 0 && chip->ops->write == NULL);
    assert(chip->info[1]->config[0] == 3 && chip->info[1]->config[1] == 3);
    assert(chip->info[1]->config[2] == 0);
    hwmon_registers++; events[event_count++] = 'H';
    return register_ret[1] ? ERR_PTR(register_ret[1]) : &mock_hwmon;
}
static void hwmon_device_unregister(struct device *device)
{
    assert(device == &mock_hwmon);
    hwmon_unregisters++; events[event_count++] = 'h';
}
/* @DRIVER@ */
static void select_model(int model)
{
    model_index = model;
    for (int i = 0; i < 4; i++) dmi_values[i] = identities[model][i];
}
static void reset(void)
{
    handle_error = method_missing = acpi_calls = acpi_fail_at = acpi_range_at = 0;
    low_b_reads = low_d_reads = 0;
    project_id = 0x10; capability = 0xec;
    rpm_bytes[0] = 15; rpm_bytes[1] = 38; rpm_bytes[2] = 19; rpm_bytes[3] = 75;
    high_script_count = high_script_position = 0;
    mechrevo_sensors_inou = (void *)1; mechrevo_sensors_rpm_lock = 0;
    select_model(0);
    mechrevo_sensors_profile = &mechrevo_sensors_profiles[0];
    register_ret[0] = register_ret[1] = 0;
    temps[0] = 63; temps[1] = 55;
    platform_registers = platform_unregisters = hwmon_registers = hwmon_unregisters = 0;
    event_count = 0; memset(events, 0, sizeof(events));
    mechrevo_sensors_device = NULL; mechrevo_sensors_hwmon = NULL;
}
static void identity_case(void)
{
    char suffixed[100];
    for (int model = 0; model < (int)MODEL_COUNT; model++) {
        for (int field = 0; field < 4; field++) {
            for (int variant = 0; variant < 3; variant++) {
                reset(); select_model(model);
                snprintf(suffixed, sizeof(suffixed), "%s extra", identities[model][field]);
                dmi_values[field] = variant == 0 ? NULL : variant == 1 ? "other" : suffixed;
                assert(mechrevo_sensors_init() == -ENODEV);
                assert(acpi_calls == 0 && platform_registers == 0);
            }
        }
    }
}
static void transport_case(void)
{
    for (int channel = 0; channel < 2; channel++) {
        reset(); acpi_fail_at = 1; long value = 777;
        assert(mechrevo_sensors_temperature(channel, &value) == -EIO);
        assert(value == 777 && acpi_calls == 1);
        reset(); acpi_range_at = 1; value = 777;
        assert(mechrevo_sensors_temperature(channel, &value) == -ERANGE);
        assert(value == 777 && acpi_calls == 1);
    }
    reset(); acpi_fail_at = 3;
    assert(mechrevo_sensors_init() == -EIO);
    assert(!platform_registers && !hwmon_registers);
    reset(); acpi_range_at = 4;
    assert(mechrevo_sensors_init() == -ERANGE);
    assert(!platform_registers && !hwmon_registers);
}
static void independent_transport_case(void)
{
    reset();
    assert(mechrevo_sensors_init() == 0);
    assert(acpi_calls == 10);
    mechrevo_sensors_exit();
    assert(hwmon_unregisters == 1 && platform_unregisters == 1);
}
static void temperature_case(void)
{
    reset();
    for (int channel = 0; channel < 2; channel++) {
        for (int raw = 0; raw <= 255; raw++) {
            temps[channel] = raw; long value = -987;
            int ret = mechrevo_sensors_read(NULL, hwmon_temp, hwmon_temp_input, channel, &value);
            assert(ret == (raw <= 125 ? 0 : -ENODATA));
            assert(value == (raw <= 125 ? raw * 1000 : -987));
            if (raw > 125) {
                assert(mechrevo_sensors_init() == -ENODATA);
                assert(platform_registers == 0);
            }
        }
        temps[channel] = 63;
    }
}
static void interface_case(void)
{
    reset();
    for (int type = hwmon_temp; type <= hwmon_in; type++)
        for (int attr = 0; attr < 4; attr++)
            for (int channel = -1; channel < 4; channel++) {
                bool valid = (type == hwmon_temp || type == hwmon_fan) && channel >= 0 && channel < 2;
                long value = 123; const char *label = "unchanged";
                assert(mechrevo_sensors_is_visible(NULL, type, attr, channel) ==
                       (valid && (attr == hwmon_temp_input || attr == hwmon_temp_label) ? 0444 : 0));
                int before = acpi_calls;
                assert(mechrevo_sensors_read(NULL, type, attr, channel, &value) ==
                       (valid && attr == hwmon_temp_input ? 0 : -EOPNOTSUPP));
                assert(acpi_calls == before +
                       (valid && attr == hwmon_temp_input ? (type == hwmon_temp ? 1 : 3) : 0));
                if (!(valid && attr == hwmon_temp_input)) assert(value == 123);
                assert(mechrevo_sensors_read_string(NULL, type, attr, channel, &label) ==
                       (valid && attr == hwmon_temp_label ? 0 : -EOPNOTSUPP));
                assert(strcmp(label, valid && attr == hwmon_temp_label ?
                       (type == hwmon_temp ? (channel == 0 ? "CPU EC" : "GPU EC") : (channel == 0 ? "CPU fan" : "GPU fan")) : "unchanged") == 0);
            }
}
static void lifecycle_case(void)
{
    reset(); register_ret[0] = -ENOMEM;
    assert(mechrevo_sensors_init() == -ENOMEM);
    assert(platform_registers == 1 && !platform_unregisters && !hwmon_registers);
    assert(mechrevo_sensors_device == NULL && mechrevo_sensors_hwmon == NULL);
    reset(); register_ret[1] = -EIO;
    assert(mechrevo_sensors_init() == -EIO);
    assert(platform_registers == 1 && platform_unregisters == 1 && hwmon_registers == 1 && !hwmon_unregisters);
    assert(strcmp(events, "PHp") == 0);
    assert(mechrevo_sensors_device == NULL && mechrevo_sensors_hwmon == NULL);
    register_ret[1] = 0;
    assert(mechrevo_sensors_init() == 0); /* Retry after failure. */
    mechrevo_sensors_exit();
    assert(strcmp(events, "PHpPHhp") == 0);
    reset();
    assert(mechrevo_sensors_init() == 0 && acpi_calls == 10);
    assert(platform_registers == 1 && hwmon_registers == 1);
    mechrevo_sensors_exit();
    assert(strcmp(events, "PHhp") == 0);
}
static void rpm_values_case(void)
{
    for (int model = 0; model < (int)MODEL_COUNT; model++) {
        reset(); select_model(model);
        mechrevo_sensors_profile = &mechrevo_sensors_profiles[model];
        /* Every possible OEM word, including stopped/maximum; no guessed sentinel. */
        for (int channel = 0; channel < 2; channel++) {
            for (unsigned word = 0; word <= 65535; word++) {
                rpm_bytes[channel * 2] = word >> 8;
                rpm_bytes[channel * 2 + 1] = word & 255;
                long value = -1;
                int before = acpi_calls;
                assert(mechrevo_sensors_read(NULL, hwmon_fan, hwmon_fan_input, channel, &value) == 0);
                assert(value == word && acpi_calls == before + 3);
                assert(mechrevo_sensors_rpm_lock == 0);
            }
        }
        assert(low_b_reads == (model == 0 ? 65536 : 0));
        assert(low_d_reads == (model == 1 ? 65536 : 0));
    }
}
static void rpm_errors_case(void)
{
    for (int channel = 0; channel < 2; channel++) {
        for (int failure = 1; failure <= 3; failure++) {
            for (int range = 0; range < 2; range++) {
                reset(); long value = 777;
                if (range) acpi_range_at = failure; else acpi_fail_at = failure;
                assert(mechrevo_sensors_rpm(channel, &value) == (range ? -ERANGE : -EIO));
                assert(value == 777 && acpi_calls == failure && !mechrevo_sensors_rpm_lock);
                acpi_fail_at = acpi_range_at = 0;
                assert(mechrevo_sensors_rpm(channel, &value) == 0); /* lock released */
            }
        }
        for (int failure = 4; failure <= 9; failure++) {
            reset(); long value = 777;
            for (int i = 0; i < 6; i++) high_script[i] = i;
            high_script_count = 6; acpi_fail_at = failure;
            assert(mechrevo_sensors_rpm(channel, &value) == -EIO);
            assert(value == 777 && acpi_calls == failure && !mechrevo_sensors_rpm_lock);
        }
        reset(); long value = 777;
        for (int i = 0; i < 6; i++) high_script[i] = i;
        high_script_count = 6;
        assert(mechrevo_sensors_rpm(channel, &value) == -EAGAIN);
        assert(value == 777 && acpi_calls == 9 && !mechrevo_sensors_rpm_lock);
        reset(); high_script_count = 4;
        high_script[0] = 15; high_script[1] = 16; high_script[2] = high_script[3] = 17;
        assert(mechrevo_sensors_rpm(channel, &value) == 0);
        assert(value == ((17L << 8) | (long)rpm_bytes[channel * 2 + 1]) && acpi_calls == 6);
    }
}
static void rpm_qualification_case(void)
{
    for (int model = 0; model < (int)MODEL_COUNT; model++) {
        for (int variant = 0; variant < 6; variant++) {
            reset(); select_model(model);
            if (variant == 0) handle_error = 1;
            if (variant == 1) method_missing = 1;
            if (variant == 2) project_id = 0x11;
            if (variant == 3) capability &= ~0x40;
            if (variant == 4) acpi_fail_at = 1;
            if (variant == 5) acpi_range_at = 2;
            assert(mechrevo_sensors_init() == (variant == 4 ? -EIO : variant == 5 ? -ERANGE : -ENODEV));
            assert(!platform_registers && !hwmon_registers);
        }
        /* Any initial sensor read failure must prevent partial registration. */
        for (int failure = 3; failure <= 10; failure++) {
            reset(); select_model(model); acpi_fail_at = failure;
            assert(mechrevo_sensors_init() == -EIO);
            assert(!platform_registers && !hwmon_registers);
        }
        reset(); select_model(model); capability = 0x40;
        assert(mechrevo_sensors_init() == 0);
        assert(acpi_calls == 10); mechrevo_sensors_exit();
    }
}
static void gm6bg0q_case(void)
{
    long value;

    /* The secondary tachometer low byte is 0x046d on GM6BG0Q... */
    reset(); select_model(1);
    mechrevo_sensors_profile = mechrevo_sensors_supported();
    assert(mechrevo_sensors_profile == &mechrevo_sensors_profiles[1]);
    rpm_bytes[2] = 0x12; rpm_bytes[3] = 0x34;
    assert(mechrevo_sensors_read(NULL, hwmon_fan, hwmon_fan_input, 1, &value) == 0);
    assert(value == 0x1234 && low_d_reads == 1 && low_b_reads == 0 && acpi_calls == 3);

    /* ... and remains 0x046b for the already-qualified GM6PX0X. */
    reset(); select_model(0);
    mechrevo_sensors_profile = mechrevo_sensors_supported();
    assert(mechrevo_sensors_profile == &mechrevo_sensors_profiles[0]);
    rpm_bytes[2] = 0x12; rpm_bytes[3] = 0x34;
    assert(mechrevo_sensors_read(NULL, hwmon_fan, hwmon_fan_input, 1, &value) == 0);
    assert(value == 0x1234 && low_b_reads == 1 && low_d_reads == 0 && acpi_calls == 3);

    /* Cross-model tuples are not combined into a match. */
    reset(); dmi_values[1] = "Other"; dmi_values[3] = "GM6BG0Q";
    assert(mechrevo_sensors_init() == -ENODEV && acpi_calls == 0);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "identity")) identity_case();
    else if (!strcmp(argv[1], "transport")) transport_case();
    else if (!strcmp(argv[1], "temperature")) temperature_case();
    else if (!strcmp(argv[1], "interface")) interface_case();
    else if (!strcmp(argv[1], "lifecycle")) lifecycle_case();
    else if (!strcmp(argv[1], "independent_transport")) independent_transport_case();
    else if (!strcmp(argv[1], "rpm_values")) rpm_values_case();
    else if (!strcmp(argv[1], "rpm_errors")) rpm_errors_case();
    else if (!strcmp(argv[1], "rpm_qualification")) rpm_qualification_case();
    else if (!strcmp(argv[1], "gm6bg0q")) gm6bg0q_case();
    else assert(false);
    return 0;
}
