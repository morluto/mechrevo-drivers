/* Compile the actual feature detection and ioctl helpers with transport spies. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define KERNEL_VERSION(a,b,c) (((a) << 16) | ((b) << 8) | (c))
#define DMI_SYS_VENDOR 0
#define DMI_BOARD_NAME 1
#define DMI_PRODUCT_SKU 2
#define DMI_PRODUCT_NAME 3
#define DMI_BIOS_VERSION 4
#define pr_debug(...) ((void)0)
#define pr_err(...) ((void)0)
/* @TYPES@ */
static struct uniwill_device_features_t uniwill_device_features;
static struct uniwill_device_features_t *uw_feats;
static bool uw_feats_loaded;
static const char *dmi[5];
static int reads, writes, read_error, write_error;
static bool double_pl4;
static u8 ec[65536], written_index, written_value;
static bool uw_ac_auto_boot_last_written_value, uw_usb_powershare_last_written_value;
static bool uw_ac_auto_boot_loaded, uw_usb_powershare_loaded;
struct platform_device { struct { int kobj; } dev; };
static int uw_ac_auto_boot_attr_group, uw_usb_powershare_attr_group;
static int group_calls, group_error;
static int sysfs_create_group(int *kobj, int *group)
{
    assert(kobj);
    assert(group == &uw_ac_auto_boot_attr_group || group == &uw_usb_powershare_attr_group);
    group_calls++;
    return group_error;
}
static bool dmi_match(int field, const char *value)
{ return dmi[field] && !strcmp(dmi[field], value); }
static int uniwill_read_ec_ram(u16 addr, u8 *value)
{ reads++; if (read_error < 0) return read_error; *value = ec[addr]; return 0; }
static int uniwill_update_ec_ram(u16 addr, u8 clear, u8 set)
{
    u8 value;
    int result = uniwill_read_ec_ram(addr, &value);
    if (result) return result;
    writes++;
    if (write_error) return write_error;
    ec[addr] = (value & ~clear) | set;
    return 0;
}
static int uw_update_mode(u8 clear, u8 set)
{ writes++; if (write_error) return write_error; ec[0x0751] = (ec[0x0751] & ~clear) | set; return 0; }
static int uw_write_tdp(u8 index, u8 value)
{ writes++; written_index = index; written_value = value; return write_error; }
static int has_double_pl4(bool *value)
{ *value = double_pl4; return 0; }
static int unavailable(bool *value) { *value = false; return 0; }
#define uw_has_charging_priority unavailable
#define uw_has_charging_profile unavailable
#define uw_has_mini_led_local_dimming unavailable
#define uw_has_hidden_bios_options unavailable
static int has_universal_ec_fan_control(void) { return 0; }
/* @TABLES@ */
/* @PRODUCTION@ */
static void detect(const char *vendor, const char *board, const char *sku)
{
    memset(&uniwill_device_features, 0, sizeof(uniwill_device_features));
    uw_feats_loaded = false;
    dmi[0] = vendor; dmi[1] = board; dmi[2] = sku;
    uw_feats = uniwill_get_device_features();
    uw_id_tdp(uw_feats->model);
    assert(writes == 0); /* Identification must never apply a power target. */
}
static void reset(void)
{
    reads = writes = read_error = write_error = 0;
    group_calls = group_error = 0;
    uw_ac_auto_boot_loaded = uw_usb_powershare_loaded = false;
    double_pl4 = false;
    dmi[3] = dmi[4] = NULL;
    memset(ec, 0, sizeof(ec));
}
static void gx4hrxl(void)
{
    reset(); detect("MECHREVO", "GX4HRXL", NULL);
    assert(uw_get_performance_profile_count() == 3);
    assert(!uw_feats->uniwill_profile_v1); /* No implicit legacy fan-curve copy. */
    assert(!uw_feats->uniwill_custom_profile_mode_needed);
    for (int initial = 0; initial <= 255; initial++) {
        for (int profile = 1; profile <= 3; profile++) {
            ec[0x0751] = initial;
            assert(uw_set_performance_profile_v1(profile) == 0);
            int bits[] = {0, 0xa0, 0, 0x10};
            assert(ec[0x0751] == ((initial & ~0xb0) | bits[profile]));
        }
    }
    int before = writes;
    assert(uw_set_performance_profile_v1(0) == -EINVAL);
    assert(uw_set_performance_profile_v1(4) == -EINVAL);
    for (int index = 0; index < 3; index++) {
        assert(uw_get_tdp(index) == -ENODEV);
        assert(uw_set_tdp(index, 50) == -ENODEV);
    }
    assert(writes == before);
    write_error = -ETIMEDOUT;
    assert(uw_set_performance_profile_v1(PROFILE_ENTHUSIAST) == -ETIMEDOUT);
}
static void jiaolong(void)
{
    reset(); detect("MECHREVO", "JIAOLONG Series-X6xR55xK", NULL);
    assert(uw_get_performance_profile_count() == 0); /* Custom mode is not classic mode. */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
    assert(uw_feats->uniwill_custom_profile_mode_needed);
    int maximum[] = {162, 162, 195};
    for (int doubled = 0; doubled < 2; doubled++) {
        uw_feats->uniwill_has_double_pl4 = doubled;
        for (int index = 0; index < 3; index++) {
            assert(uw_get_tdp_min(index) == 25 && uw_get_tdp_max(index) == maximum[index]);
            for (int value = 0; value <= maximum[index] + 1; value++) {
                int before = writes;
                bool valid = value >= 25 && value <= maximum[index];
                assert(uw_set_tdp(index, value) == (valid ? 0 : -EINVAL));
                assert(writes == before + valid);
                if (valid) {
                    assert(written_index == index);
                    assert(written_value == (doubled && index == 2 ? value / 2 : value));
                }
            }
            ec[0x0783 + index] = 51;
            assert(uw_get_tdp(index) == (doubled && index == 2 ? 102 : 51));
        }
    }
    write_error = -EIO;
    assert(uw_set_tdp(0, 50) == -EIO);
    read_error = -ETIMEDOUT;
    assert(uw_get_tdp(0) == -ETIMEDOUT);
#else
    assert(!uw_feats->uniwill_custom_profile_mode_needed);
    assert(uw_set_tdp(0, 50) == -ENODEV);
#endif
    assert(uw_set_tdp(3, 50) == -EINVAL);
    assert(uw_get_tdp(255) == -EINVAL);
}
static void identity(void)
{
    const char *vendors[] = {NULL, "Other", "Other MECHREVO", "MECHREVO extra"};
    const char *boards[] = {"GX4HRXL", "JIAOLONG Series-X6xR55xK"};
    for (unsigned b = 0; b < 2; b++) {
        for (unsigned v = 0; v < 4; v++) {
            reset(); detect(vendors[v], boards[b], NULL);
            assert(!uw_feats->uniwill_profile_v1 && !uw_feats->uniwill_custom_profile_mode_needed);
            assert(uw_set_tdp(0, 50) == -ENODEV);
            assert(uw_set_performance_profile_v1(PROFILE_POWERSAVE) == -ENODEV);
            assert(writes == 0);
        }
    }
    const char *unknown[] = {NULL, "GX4HRXL extra", "GX4HRX", "X6FR57TK",
        "JIAOLONG Series-X6xR55xK extra", "GM6BG0Q", "GM6PX0X"};
    for (unsigned b = 0; b < sizeof(unknown)/sizeof(*unknown); b++) {
        reset(); detect("MECHREVO", unknown[b], NULL);
        assert(!uw_feats->uniwill_profile_v1 && !uw_feats->uniwill_custom_profile_mode_needed);
        assert(uw_set_tdp(0, 50) == -ENODEV && writes == 0);
    }
}
static void existing(void)
{
    reset(); detect("TUXEDO", "GXxHRXx", NULL);
    assert(uw_feats->uniwill_profile_v1 && uw_get_performance_profile_count() == 3);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
    assert(uw_feats->uniwill_custom_profile_mode_needed);
    reset(); detect("TUXEDO", "X6FR5xxY", "STELLARIS16A07");
    assert(uw_get_tdp_min(0) == 25 && uw_get_tdp_max(0) == 162);
#endif
}
static void retry(void)
{
    reset(); read_error = -EIO;
    detect("MECHREVO", "GX4HRXL", NULL);
    assert(!uw_feats_loaded);
    read_error = 0;
    assert(uniwill_get_device_features() == uw_feats && uw_feats_loaded);
    assert(reads == 2 && writes == 0);
    assert(uniwill_get_device_features() == uw_feats && reads == 2);
}
static void settings_identity(void)
{
    const char *boards[] = {"WUJIE Series-X5SP4NAG", "GM6BG0Q", "GM5HG0A"};
    const char *products[] = {NULL, "Jiaolong16K Series GM6BG0Q", "Yilong15Pro Series GM5HG0A"};
    const char *bioses[] = {NULL, "N.1.19MRO15", "N.1.09MRO19"};
    for (int board = 0; board < 3; board++) {
        const char *good[] = {"MECHREVO", boards[board], NULL, products[board], bioses[board]};
        reset();
        dmi[3] = good[3]; dmi[4] = good[4];
        detect("MECHREVO", boards[board], NULL);
        assert(uw_feats->uniwill_has_ac_auto_boot && uw_feats->uniwill_has_usb_powershare);
        assert(!uw_feats->uniwill_profile_v1 && !uw_feats->uniwill_custom_profile_mode_needed);
        assert(uw_get_performance_profile_count() == (board == 1 ? 3 : 0));
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
        if (board == 1) {
            assert(uw_get_tdp_min(0) == 35 && uw_get_tdp_max(0) == 95);
            assert(uw_get_tdp_min(1) == 35 && uw_get_tdp_max(1) == 95);
            assert(uw_get_tdp_min(2) == 100 && uw_get_tdp_max(2) == 215);
        } else
#endif
        {
            assert(uw_set_tdp(0, 50) == -ENODEV && writes == 0);
        }
        for (int field = 0; field < 5; field++) {
            if (field == DMI_PRODUCT_SKU || (board == 0 && field > DMI_BOARD_NAME)) continue;
            for (int variant = 0; variant < 3; variant++) {
                reset();
                for (int i = 0; i < 5; i++) dmi[i] = good[i];
                dmi[DMI_BOARD_NAME] = boards[board];
                dmi[field] = variant == 0 ? NULL : variant == 1 ? "Other" : "MECHREVO extra";
                detect(dmi[0], dmi[1], NULL);
                assert(!uw_feats->uniwill_has_ac_auto_boot && !uw_feats->uniwill_has_usb_powershare);
                assert(uw_get_performance_profile_count() == 0);
                assert(uw_set_tdp(0, 50) == -ENODEV && writes == 0);
            }
        }
    }
    const char *unknown[] = {"WUJIE Series-X5SP4NAG extra", "WUJIE", "GM6BG0Q extra",
        "GM6BG5Q", "GM6PX0X", "GX4HRXL", "JIAOLONG Series-X6xR55xK", "GM5HG0A extra"};
    for (unsigned i = 0; i < sizeof(unknown)/sizeof(*unknown); i++) {
        reset(); detect("MECHREVO", unknown[i], NULL);
        assert(!uw_feats->uniwill_has_ac_auto_boot && !uw_feats->uniwill_has_usb_powershare);
    }
    reset(); detect("TUXEDO", "GXxHRXx", NULL);
    assert(uw_feats->uniwill_has_ac_auto_boot && uw_feats->uniwill_has_usb_powershare);
}
static void settings_transactions(void)
{
    const char *boards[] = {"WUJIE Series-X5SP4NAG", "GM6BG0Q", "GM5HG0A"};
    const char *products[] = {NULL, "Jiaolong16K Series GM6BG0Q", "Yilong15Pro Series GM5HG0A"};
    const char *bioses[] = {NULL, "N.1.19MRO15", "N.1.09MRO19"};
    for (int model = 0; model < 3; model++) {
        reset(); dmi[3] = products[model]; dmi[4] = bioses[model];
        detect("MECHREVO", boards[model], NULL);
        assert(uw_feats->uniwill_has_ac_auto_boot && uw_feats->uniwill_has_usb_powershare);
        for (int initial = 0; initial <= 255; initial++) {
            for (int enabled = 0; enabled < 2; enabled++) {
                u8 value;
                ec[0x0726] = initial;
                assert(uw_set_ac_auto_boot(enabled) == 0);
                assert(ec[0x0726] == ((initial & ~8) | (enabled << 3)));
                assert(uw_get_ac_auto_boot(&value) == 0 && value == enabled);
                ec[0x0767] = initial;
                assert(uw_set_usb_powershare(enabled) == 0);
                assert(ec[0x0767] == ((initial & ~16) | (enabled << 4)));
                assert(uw_get_usb_powershare(&value) == 0 && value == enabled);
            }
        }
        for (int setting = 0; setting < 2; setting++) {
            int (*set)(u8) = setting ? uw_set_usb_powershare : uw_set_ac_auto_boot;
            int (*get)(u8 *) = setting ? uw_get_usb_powershare : uw_get_ac_auto_boot;
            for (int failure = 0; failure < 2; failure++) {
                read_error = write_error = 0;
                assert(set(0) == 0);
                bool old_ac = uw_ac_auto_boot_last_written_value;
                bool old_usb = uw_usb_powershare_last_written_value;
                int before = writes;
                if (failure) write_error = -EIO; else read_error = -ETIMEDOUT;
                assert(set(1) == (failure ? -EIO : -ETIMEDOUT));
                assert(writes == before + failure);
                assert(uw_ac_auto_boot_last_written_value == old_ac);
                assert(uw_usb_powershare_last_written_value == old_usb);
                if (!failure) {
                    u8 value = 99;
                    assert(get(&value) == -ETIMEDOUT && value == 99);
                }
            }
        }
    }
}
static void gm6bg0q(void)
{
    reset(); dmi[3] = "Jiaolong16K Series GM6BG0Q"; dmi[4] = "N.1.19MRO15";
    detect("MECHREVO", "GM6BG0Q", NULL);
    assert(uw_get_performance_profile_count() == 3);
    assert(!uw_feats->uniwill_profile_v1); /* Curves stay owned by the OEM EC. */
    assert(!uw_feats->uniwill_custom_profile_mode_needed);
    assert(!uw_feats->uniwill_has_double_pl4);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
    for (int index = 0; index < 3; index++) {
        int minimum = index < 2 ? 35 : 100;
        int maximum = index < 2 ? 95 : 215;
        assert(uw_get_tdp_min(index) == minimum);
        assert(uw_get_tdp_max(index) == maximum);
        for (int value = 0; value <= 200; value++) {
            int before = writes;
            bool valid = value >= minimum && value <= maximum;
            assert(uw_set_tdp(index, value) == (valid ? 0 : -EINVAL));
            assert(writes == before + valid);
            if (valid) {
                assert(written_index == index);
                assert(written_value == value); /* No PL4 doubling on this model. */
            }
        }
        ec[0x0783 + index] = 51;
        assert(uw_get_tdp(index) == 51);
    }
#else
    for (int index = 0; index < 3; index++) {
        assert(uw_get_tdp_min(index) == -ENODEV);
        assert(uw_set_tdp(index, 50) == -ENODEV && writes == 0);
    }
#endif
    for (int initial = 0; initial <= 255; initial++) {
        for (int profile = 1; profile <= 3; profile++) {
            int bits[] = {0, 0xa0, 0, 0x10};
            ec[0x0751] = initial;
            assert(uw_set_performance_profile_v1(profile) == 0);
            assert(ec[0x0751] == ((initial & ~0xb0) | bits[profile]));
        }
    }
    int before = writes;
    assert(uw_set_performance_profile_v1(0) == -EINVAL);
    assert(uw_set_performance_profile_v1(4) == -EINVAL);
    assert(writes == before);
    /* BIOS or product mismatch removes modes, TDP and no EC write happens. */
    reset(); dmi[3] = "Jiaolong16K Series GM6BG0Q"; dmi[4] = "N.1.19MRO14";
    detect("MECHREVO", "GM6BG0Q", NULL);
    assert(uw_get_performance_profile_count() == 0);
    assert(uw_set_tdp(0, 50) == -ENODEV && writes == 0);
    assert(uw_set_performance_profile_v1(PROFILE_POWERSAVE) == -ENODEV);
    reset(); dmi[3] = "Jiaolong16K Series GM6BG0Q x"; dmi[4] = "N.1.19MRO15";
    detect("MECHREVO", "GM6BG0Q", NULL);
    assert(uw_get_performance_profile_count() == 0);
    assert(uw_set_tdp(2, 100) == -ENODEV && writes == 0);
}
static void settings_init(void)
{
    struct platform_device dev = {0};
    for (int setting = 0; setting < 2; setting++) {
        void (*init)(struct platform_device *) = setting ? uw_usb_powershare_init : uw_ac_auto_boot_init;
        bool *loaded = setting ? &uw_usb_powershare_loaded : &uw_ac_auto_boot_loaded;
        bool *cached = setting ? &uw_usb_powershare_last_written_value : &uw_ac_auto_boot_last_written_value;
        bool *supported = setting ? &uniwill_device_features.uniwill_has_usb_powershare : &uniwill_device_features.uniwill_has_ac_auto_boot;
        int address = setting ? 0x0767 : 0x0726, mask = setting ? 16 : 8;
        for (int enabled = 0; enabled < 2; enabled++) {
            reset(); *supported = true; *cached = !enabled; ec[address] = enabled ? mask : 0;
            init(&dev);
            assert(*loaded && *cached == enabled && reads == 1 && group_calls == 1 && writes == 0);
        }
        reset(); *supported = false; *loaded = true;
        init(&dev);
        assert(!*loaded && reads == 0 && group_calls == 0 && writes == 0);
        reset(); *supported = true; *cached = true; read_error = -ETIMEDOUT;
        init(&dev);
        assert(!*loaded && *cached && reads == 1 && group_calls == 0 && writes == 0);
        read_error = 0;
        init(&dev); /* A later successful initialization can publish the state. */
        assert(*loaded && !*cached && reads == 2 && group_calls == 1 && writes == 0);
        reset(); *supported = true; group_error = -ENOMEM;
        init(&dev);
        assert(!*loaded && reads == 1 && group_calls == 1 && writes == 0);
    }
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "gx4hrxl")) gx4hrxl();
    else if (!strcmp(argv[1], "jiaolong")) jiaolong();
    else if (!strcmp(argv[1], "identity")) identity();
    else if (!strcmp(argv[1], "existing")) existing();
    else if (!strcmp(argv[1], "retry")) retry();
    else if (!strcmp(argv[1], "gm6bg0q")) gm6bg0q();
    else if (!strcmp(argv[1], "settings_identity")) settings_identity();
    else if (!strcmp(argv[1], "settings_transactions")) settings_transactions();
    else if (!strcmp(argv[1], "settings_init")) settings_init();
    else assert(false);
    return 0;
}
