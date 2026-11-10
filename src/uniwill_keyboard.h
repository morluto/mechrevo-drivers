/* SPDX-License-Identifier: GPL-2.0+ */
/*!
 * Copyright (c) 2020-2024 TUXEDO Computers GmbH <tux@tuxedocomputers.com>
 *
 * This file is part of tuxedo-drivers.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program; if not, see <https://www.gnu.org/licenses/>.
 */

#ifndef UNIWILL_KEYBOARD_H
#define UNIWILL_KEYBOARD_H

#include "tuxedo_keyboard_common.h"
#include <linux/acpi.h>
#include <linux/wmi.h>
#include <linux/workqueue.h>
#include <linux/mutex.h>
#include <linux/keyboard.h>
#include <linux/timer.h>
#include <linux/delay.h>
#include <linux/leds.h>
#include <linux/led-class-multicolor.h>
#include <linux/string.h>
#include <linux/version.h>
#include <linux/efi.h>
#include <linux/slab.h>
#include <linux/i8042.h>
#include <linux/serio.h>
#include <acpi/battery.h>
#include "uniwill_interfaces.h"
#include "uniwill_leds.h"

#define FAN_ON_MIN_SPEED_PERCENT 25

#define UNIWILL_OSD_RADIOON				0x01A
#define UNIWILL_OSD_RADIOOFF				0x01B
#define UNIWILL_OSD_KB_LED_LEVEL0			0x03B
#define UNIWILL_OSD_KB_LED_LEVEL1			0x03C
#define UNIWILL_OSD_KB_LED_LEVEL2			0x03D
#define UNIWILL_OSD_KB_LED_LEVEL3			0x03E
#define UNIWILL_OSD_KB_LED_LEVEL4			0x03F
#define UNIWILL_OSD_DC_ADAPTER_CHANGE			0x0AB
#define UNIWILL_OSD_MODE_CHANGE_KEY_EVENT		0x0B0

#define UNIWILL_KEY_RFKILL				0x0A4
#define UNIWILL_KEY_KBDILLUMDOWN			0x0B1
#define UNIWILL_KEY_KBDILLUMUP				0x0B2
#define UNIWILL_KEY_FN_LOCK				0x0B8
#define UNIWILL_KEY_KBDILLUMTOGGLE			0x0B9

#define UNIWILL_OSD_TOUCHPADWORKAROUND			0xFFF

#define UNIWILL_FN_LOCK_MASK				0x10

#define UW_MEMORY_OVERCLOCKING_SWITCH			0x33
#define UW_MEMORY_OVERCLOCKING_SUPPORT			0x60
#define UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SUPPORT	0x6E
#define UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SWITCH	0x6f

static void uw_charging_priority_write_state(void);
static void uw_charging_profile_write_state(void);
static int uniwill_set_custom_profile_mode(bool zero_bit_initially);
static void uniwill_restore_adapter_state(void);

struct tuxedo_keyboard_driver uniwill_keyboard_driver;

struct uniwill_device_features_t uniwill_device_features;

static bool uw_feats_loaded = false;

static u8 uniwill_kbd_bl_enable_state_on_start = 0xff;

static struct key_entry uniwill_wmi_keymap[] = {
	// { KE_KEY,	UNIWILL_OSD_RADIOON,		{ KEY_RFKILL } },
	// { KE_KEY,	UNIWILL_OSD_RADIOOFF,		{ KEY_RFKILL } },
	// { KE_KEY,	0xb0,				{ KEY_F13 } },
	// Manual mode rfkill
	{ KE_KEY,	UNIWILL_KEY_RFKILL,		{ KEY_RFKILL }},
	{ KE_KEY,	UNIWILL_OSD_TOUCHPADWORKAROUND,	{ KEY_F21 } },
	// Keyboard brightness
	{ KE_KEY,	UNIWILL_KEY_KBDILLUMDOWN,	{ KEY_KBDILLUMDOWN } },
	{ KE_KEY,	UNIWILL_KEY_KBDILLUMUP,		{ KEY_KBDILLUMUP } },
	{ KE_KEY,	UNIWILL_KEY_KBDILLUMTOGGLE,	{ KEY_KBDILLUMTOGGLE } },
	{ KE_KEY,	UNIWILL_OSD_KB_LED_LEVEL0,	{ KEY_KBDILLUMTOGGLE } },
	{ KE_KEY,	UNIWILL_OSD_KB_LED_LEVEL1,	{ KEY_KBDILLUMTOGGLE } },
	{ KE_KEY,	UNIWILL_OSD_KB_LED_LEVEL2,	{ KEY_KBDILLUMTOGGLE } },
	{ KE_KEY,	UNIWILL_OSD_KB_LED_LEVEL3,	{ KEY_KBDILLUMTOGGLE } },
	{ KE_KEY,	UNIWILL_OSD_KB_LED_LEVEL4,	{ KEY_KBDILLUMTOGGLE } },
	// Send FN_ESC to user space as input-event-codes.h does not define Fn-Lock
	{ KE_KEY,	UNIWILL_KEY_FN_LOCK,		{ KEY_FN_ESC } },
	// Only used to put ev bits
	{ KE_KEY,	0xffff,				{ KEY_F6 } },
	{ KE_KEY,	0xffff,				{ KEY_LEFTALT } },
	{ KE_KEY,	0xffff,				{ KEY_LEFTMETA } },
	{ KE_END,	0 }
};

static struct uniwill_interfaces_t {
	struct uniwill_interface_t *wmi;
} uniwill_interfaces = { .wmi = NULL };

uniwill_event_callb_t uniwill_event_callb;

/* Lock order: caller domain locks -> EC transaction -> transport.
 * Keep the lock private: callers compose only complete register updates. */
static DEFINE_MUTEX(uniwill_ec_transaction_lock);

static int uniwill_read_ec_ram_unlocked(u16 address, u8 *data)
{
	int status;

	if (!IS_ERR_OR_NULL(uniwill_interfaces.wmi))
		status = uniwill_interfaces.wmi->read_ec_ram(address, data);
	else {
		pr_err("no active interface while read addr 0x%04x\n", address);
		status = -EIO;
	}

	return status;
}
int uniwill_read_ec_ram(u16 address, u8 *data)
{
	int status;

	mutex_lock(&uniwill_ec_transaction_lock);
	status = uniwill_read_ec_ram_unlocked(address, data);
	mutex_unlock(&uniwill_ec_transaction_lock);
	return status;
}
EXPORT_SYMBOL(uniwill_read_ec_ram);

int uniwill_read_ec_ram_with_retry(u16 address, u8 *data, int retries)
{
	int status, i;

	if (retries <= 0)
		return -EINVAL;

	for (i = 0; i < retries; ++i) {
		status = uniwill_read_ec_ram(address, data);
		if (status != 0)
			pr_debug("uniwill_read_ec_ram(...) failed.\n");
		else
			break;
	}

	return status;
}
EXPORT_SYMBOL(uniwill_read_ec_ram_with_retry);

static int uniwill_read_ec_ram_u16(u16 hibyte_address, u16 lobyte_address, u16 *data) {
	int result;
	u8 hi, lo;
	result = uniwill_read_ec_ram(hibyte_address, &hi);
	if (result)
		return result;
	result = uniwill_read_ec_ram(lobyte_address, &lo);
	if (result)
		return result;
	*data = (hi << 8) | lo;
	return result;
}

static int uniwill_write_ec_ram_unlocked(u16 address, u8 data)
{
	int status;

	if (!IS_ERR_OR_NULL(uniwill_interfaces.wmi))
		status = uniwill_interfaces.wmi->write_ec_ram(address, data);
	else {
		pr_err("no active interface while write addr 0x%04x data 0x%02x\n", address, data);
		status = -EIO;
	}

	return status;
}
int uniwill_write_ec_ram(u16 address, u8 data)
{
	int status;

	mutex_lock(&uniwill_ec_transaction_lock);
	status = uniwill_write_ec_ram_unlocked(address, data);
	mutex_unlock(&uniwill_ec_transaction_lock);
	return status;
}
EXPORT_SYMBOL(uniwill_write_ec_ram);

int uniwill_update_ec_ram(u16 address, u8 clear_mask, u8 set_mask)
{
	u8 data;
	int status;

	mutex_lock(&uniwill_ec_transaction_lock);
	status = uniwill_read_ec_ram_unlocked(address, &data);
	if (!status)
		status = uniwill_write_ec_ram_unlocked(address, (data & ~clear_mask) | set_mask);
	mutex_unlock(&uniwill_ec_transaction_lock);
	return status;
}
EXPORT_SYMBOL(uniwill_update_ec_ram);

int uniwill_write_ec_ram_with_retry(u16 address, u8 data, int retries)
{
	int status, i;
	u8 control_data;

	if (retries <= 0)
		return -EINVAL;

	for (i = 0; i < retries; ++i) {
		status = uniwill_write_ec_ram(address, data);
		if (status != 0) {
			msleep(50);
			continue;
		}
		else {
			status = uniwill_read_ec_ram(address, &control_data);
			if (!status && data != control_data)
				status = -EIO;
			if (status != 0 || data != control_data) {
				msleep(50);
				continue;
			}
			break;
		}
	}

	return status;
}
EXPORT_SYMBOL(uniwill_write_ec_ram_with_retry);


int uniwill_wmi_evaluate(u8 function, u32 arg, u32 *return_buffer)
{
    int status;

    if (!IS_ERR_OR_NULL(uniwill_interfaces.wmi) &&
        !IS_ERR_OR_NULL(uniwill_interfaces.wmi->wmi_evaluate)) {
        status = uniwill_interfaces.wmi->wmi_evaluate(function, arg, return_buffer);
    } else {
        pr_err("no active interface or ec_evaluate while calling function %u\n", function);
        status = -EIO;
    }

    return status;
}
EXPORT_SYMBOL(uniwill_wmi_evaluate);

static DEFINE_MUTEX(uniwill_interface_modification_lock);

int uniwill_add_interface(struct uniwill_interface_t *interface)
{
	struct platform_device *dev;
	int status = 0;

	mutex_lock(&uniwill_interface_modification_lock);
	if (strcmp(interface->string_id, UNIWILL_INTERFACE_WMI_STRID) != 0) {
		status = -EINVAL;
		goto unlock;
	}
	if (!IS_ERR_OR_NULL(uniwill_interfaces.wmi) &&
	    uniwill_interfaces.wmi != interface) {
		status = -EBUSY;
		goto unlock;
	}

	/* Probe needs the transport, but events need the completed device. */
	uniwill_interfaces.wmi = interface;
	dev = tuxedo_keyboard_init_driver(&uniwill_keyboard_driver);
	if (IS_ERR_OR_NULL(dev)) {
		interface->event_callb = NULL;
		uniwill_interfaces.wmi = NULL;
		status = dev ? PTR_ERR(dev) : -ENODEV;
		goto unlock;
	}
	interface->event_callb = uniwill_event_callb;

unlock:
	mutex_unlock(&uniwill_interface_modification_lock);
	return status;
}
EXPORT_SYMBOL(uniwill_add_interface);

int uniwill_remove_interface(struct uniwill_interface_t *interface)
{
	int status = 0;

	mutex_lock(&uniwill_interface_modification_lock);
	if (strcmp(interface->string_id, UNIWILL_INTERFACE_WMI_STRID) != 0) {
		status = -EINVAL;
		goto unlock;
	}
	if (uniwill_interfaces.wmi != interface)
		goto unlock;

	interface->event_callb = NULL;
	tuxedo_keyboard_remove_driver(&uniwill_keyboard_driver);
	uniwill_interfaces.wmi = NULL;

unlock:
	mutex_unlock(&uniwill_interface_modification_lock);
	return status;
}
EXPORT_SYMBOL(uniwill_remove_interface);

int uniwill_get_active_interface_id(char **id_str)
{
	if (IS_ERR_OR_NULL(uniwill_interfaces.wmi))
		return -ENODEV;

	if (!IS_ERR_OR_NULL(id_str))
		*id_str = uniwill_interfaces.wmi->string_id;

	return 0;
}
EXPORT_SYMBOL(uniwill_get_active_interface_id);

static void key_event_work(struct work_struct *work)
{
	struct input_dev *input;

	// Delay sometimes needed to make userspace reliably separate
	// the touchpadtoggle key events from the custom key events
	// coming from firmware
	msleep(50);
	/* Input registration can fail while the keyboard itself stays bound.
	 * Removal drains this worker before clearing or freeing a valid input. */
	input = uniwill_keyboard_driver.input_device;
	if (!input)
		return;
	sparse_keymap_report_known_event(
		input,
		UNIWILL_OSD_TOUCHPADWORKAROUND,
		1,
		true
	);
}
static DECLARE_WORK(uniwill_key_event_work, key_event_work);

static int uniwill_write_kbd_bl_enable(u8 enable)
{
	return uniwill_update_ec_ram(UW_EC_REG_KBD_BL_STATUS, 1 << 1,
				    !(enable & 0x01) << 1);
}

void uniwill_event_callb(u32 code)
{
	switch (code) {
		case UNIWILL_OSD_MODE_CHANGE_KEY_EVENT:
			if (!uniwill_keyboard_driver.input_device)
				break;
			// Special key combination when mode change key is pressed (the one next to
			// the power key). Opens TCC by default when installed.
			input_report_key(uniwill_keyboard_driver.input_device, KEY_LEFTMETA, 1);
			input_report_key(uniwill_keyboard_driver.input_device, KEY_LEFTALT, 1);
			input_report_key(uniwill_keyboard_driver.input_device, KEY_F6, 1);
			input_sync(uniwill_keyboard_driver.input_device);
			input_report_key(uniwill_keyboard_driver.input_device, KEY_F6, 0);
			input_report_key(uniwill_keyboard_driver.input_device, KEY_LEFTALT, 0);
			input_report_key(uniwill_keyboard_driver.input_device, KEY_LEFTMETA, 0);
			input_sync(uniwill_keyboard_driver.input_device);
			break;
		case UNIWILL_OSD_DC_ADAPTER_CHANGE:
			// Refresh keyboard state and charging settings on cable switch event and make sure that the custom
			// profile mode is still applied in case it's needed.
			uniwill_restore_adapter_state();
			break;
		case UNIWILL_KEY_KBDILLUMTOGGLE:
		case UNIWILL_OSD_KB_LED_LEVEL0:
		case UNIWILL_OSD_KB_LED_LEVEL1:
		case UNIWILL_OSD_KB_LED_LEVEL2:
		case UNIWILL_OSD_KB_LED_LEVEL3:
		case UNIWILL_OSD_KB_LED_LEVEL4:
			// Notify userspace/UPower that the firmware changed the keyboard backlight
			// brightness on white only keyboards. Fallthrough on other keyboards to
			// emit KEY_KBDILLUMTOGGLE.
			if (uniwill_leds_notify_brightness_change_extern())
				return;
			fallthrough;
		default:
			if (uniwill_keyboard_driver.input_device != NULL)
				if (!sparse_keymap_report_known_event(uniwill_keyboard_driver.input_device, code, 1, true))
					TUXEDO_DEBUG("Unknown code - %d (%0#6x)\n", code, code);
	}
}

static int uniwill_set_custom_profile_mode(bool zero_bit_initially)
{
	// Set custom profile mode if needed
	struct uniwill_device_features_t *uw_feats = uniwill_get_device_features();
	u8 data;
	int status;

	if (!uw_feats->uniwill_custom_profile_mode_needed)
		return 0;

	status = uniwill_read_ec_ram(UW_EC_REG_CUSTOM_PROFILE, &data);
	if (status)
		return status;
	if (zero_bit_initially) {
		// Certain devices seem to need this first reset to zero on boot to have it properly applied
		data &= ~(1 << 6);
		status = uniwill_write_ec_ram(UW_EC_REG_CUSTOM_PROFILE, data);
		if (status)
			return status;
		msleep(50);
	}
	data |= (1 << 6);
	return uniwill_write_ec_ram(UW_EC_REG_CUSTOM_PROFILE, data);
}

#define UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS	0x24
#define UNIWILL_LIGHTBAR_LED_NAME_RGB_RED	"lightbar_rgb:1:status"
#define UNIWILL_LIGHTBAR_LED_NAME_RGB_GREEN	"lightbar_rgb:2:status"
#define UNIWILL_LIGHTBAR_LED_NAME_RGB_BLUE	"lightbar_rgb:3:status"
#define UNIWILL_LIGHTBAR_LED_NAME_ANIMATION	"lightbar_animation::status"

static void uniwill_write_lightbar_rgb(u8 red, u8 green, u8 blue)
{
	if (red <= UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS) {
		uniwill_write_ec_ram(0x0749, red);
	}
	if (green <= UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS) {
		uniwill_write_ec_ram(0x074a, green);
	}
	if (blue <= UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS) {
		uniwill_write_ec_ram(0x074b, blue);
	}
}

static void uniwill_read_lightbar_rgb(u8 *red, u8 *green, u8 *blue)
{
	uniwill_read_ec_ram(0x0749, red);
	uniwill_read_ec_ram(0x074a, green);
	uniwill_read_ec_ram(0x074b, blue);
}

static void uniwill_write_lightbar_animation(bool animation_status)
{
	u8 value;

	uniwill_read_ec_ram(0x0748, &value);
	if (animation_status) {
		value |= 0x80;
	} else {
		value &= ~0x80;
	}
	uniwill_write_ec_ram(0x0748, value);
}

static void uniwill_read_lightbar_animation(bool *animation_status)
{
	u8 lightbar_animation_data;
	uniwill_read_ec_ram(0x0748, &lightbar_animation_data);
	*animation_status = (lightbar_animation_data & 0x80) > 0;
}

static int lightbar_set_blocking(struct led_classdev *led_cdev, enum led_brightness brightness)
{
	u8 red = 0xff, green = 0xff, blue = 0xff;
	bool led_red = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_RED) != NULL;
	bool led_green = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_GREEN) != NULL;
	bool led_blue = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_BLUE) != NULL;
	bool led_animation = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_ANIMATION) != NULL;

	if (led_red || led_green || led_blue) {
		if (led_red) {
			red = brightness;
		} else if (led_green) {
			green = brightness;
		} else if (led_blue) {
			blue = brightness;
		}
		uniwill_write_lightbar_rgb(red, green, blue);
		// Also make sure the animation is off
		uniwill_write_lightbar_animation(false);
	} else if (led_animation) {
		if (brightness == 1) {
			uniwill_write_lightbar_animation(true);
		} else {
			uniwill_write_lightbar_animation(false);
		}
	}
	return 0;
}

static enum led_brightness lightbar_get(struct led_classdev *led_cdev)
{
	u8 red, green, blue;
	bool animation_status;
	bool led_red = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_RED) != NULL;
	bool led_green = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_GREEN) != NULL;
	bool led_blue = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_RGB_BLUE) != NULL;
	bool led_animation = strstr(led_cdev->name, UNIWILL_LIGHTBAR_LED_NAME_ANIMATION) != NULL;

	if (led_red || led_green || led_blue) {
		uniwill_read_lightbar_rgb(&red, &green, &blue);
		if (led_red) {
			return red;
		} else if (led_green) {
			return green;
		} else if (led_blue) {
			return blue;
		}
	} else if (led_animation) {
		uniwill_read_lightbar_animation(&animation_status);
		return animation_status ? 1 : 0;
	}

	return 0;
}

static bool uw_lightbar_loaded;
static struct led_classdev lightbar_led_classdevs[] = {
	{
		.name = UNIWILL_LIGHTBAR_LED_NAME_RGB_RED,
		.max_brightness = UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS,
		.brightness_set_blocking = &lightbar_set_blocking,
		.brightness_get = &lightbar_get
	},
	{
		.name = UNIWILL_LIGHTBAR_LED_NAME_RGB_GREEN,
		.max_brightness = UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS,
		.brightness_set_blocking = &lightbar_set_blocking,
		.brightness_get = &lightbar_get
	},
	{
		.name = UNIWILL_LIGHTBAR_LED_NAME_RGB_BLUE,
		.max_brightness = UNIWILL_LIGHTBAR_LED_MAX_BRIGHTNESS,
		.brightness_set_blocking = &lightbar_set_blocking,
		.brightness_get = &lightbar_get
	},
	{
		.name = UNIWILL_LIGHTBAR_LED_NAME_ANIMATION,
		.max_brightness = 1,
		.brightness_set_blocking = &lightbar_set_blocking,
		.brightness_get = &lightbar_get
	}
};

static int uw_lightbar_init(struct platform_device *dev)
{
	int i, j, status;

	bool lightbar_supported = false
		|| dmi_match(DMI_BOARD_NAME, "LAPQC71A")
		|| dmi_match(DMI_BOARD_NAME, "LAPQC71B")
		|| dmi_match(DMI_BOARD_NAME, "TRINITY1501I")
		|| dmi_match(DMI_BOARD_NAME, "TRINITY1701I")
		|| dmi_match(DMI_PRODUCT_NAME, "A60 MUV")
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XA03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI04")
		|| dmi_match(DMI_PRODUCT_SKU, "STEPOL1XA04")

#endif
		;

#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 18, 0)
	TUXEDO_ERROR(
		"Warning: Kernel version less that 4.18, lightbar might not be properly recognized.");
#endif

	if (!lightbar_supported)
		return -ENODEV;

	for (i = 0; i < ARRAY_SIZE(lightbar_led_classdevs); ++i) {
		status = led_classdev_register(&dev->dev, &lightbar_led_classdevs[i]);
		if (status < 0) {
			for (j = 0; j < i; j++)
				led_classdev_unregister(&lightbar_led_classdevs[j]);
			return status;
		}
	}

	// Init default state
	uniwill_write_lightbar_animation(false);
	uniwill_write_lightbar_rgb(0, 0, 0);

	return 0;
}

static int uw_lightbar_remove(struct platform_device *dev)
{
	int i;
	for (i = 0; i < ARRAY_SIZE(lightbar_led_classdevs); ++i) {
		led_classdev_unregister(&lightbar_led_classdevs[i]);
	}
	return 0;
}

/* Fan/PM callbacks may enter here with command -> state held. Sysfs must
 * never take those locks: remove drains its active callbacks with command held.
 * This mutex covers each charging EC update and its saved restoration value. */
static DEFINE_MUTEX(uniwill_charging_lock);
static bool uw_charging_prio_loaded = false;
static bool uw_charging_prio_state_valid;
static bool uw_charging_prio_last_written_value;

static ssize_t uw_charging_prios_available_show(struct device *child,
						struct device_attribute *attr,
						char *buffer);
static ssize_t uw_charging_prio_show(struct device *child,
				     struct device_attribute *attr, char *buffer);
static ssize_t uw_charging_prio_store(struct device *child,
				      struct device_attribute *attr,
				      const char *buffer, size_t size);

struct uw_charging_prio_attrs_t {
	struct device_attribute charging_prios_available;
	struct device_attribute charging_prio;
} uw_charging_prio_attrs = {
	.charging_prios_available = __ATTR(charging_prios_available, 0444, uw_charging_prios_available_show, NULL),
	.charging_prio = __ATTR(charging_prio, 0644, uw_charging_prio_show, uw_charging_prio_store)
};

static struct attribute *uw_charging_prio_attrs_list[] = {
	&uw_charging_prio_attrs.charging_prios_available.attr,
	&uw_charging_prio_attrs.charging_prio.attr,
	NULL
};

static struct attribute_group uw_charging_prio_attr_group = {
	.name = "charging_priority",
	.attrs = uw_charging_prio_attrs_list
};

/*
 * charging_prio values
 *     0 => charging priority
 *     1 => performance priority
 */
static int uw_set_charging_priority_locked(u8 charging_priority)
{
	int result;

	charging_priority &= 0x01;
	result = uniwill_update_ec_ram(0x07cc, 1 << 7, charging_priority << 7);
	if (!result) {
		uw_charging_prio_last_written_value = charging_priority;
		uw_charging_prio_state_valid = true;
	}
	return result;
}

static int uw_set_charging_priority(u8 charging_priority)
{
	int result;

	mutex_lock(&uniwill_charging_lock);
	result = uw_set_charging_priority_locked(charging_priority);
	mutex_unlock(&uniwill_charging_lock);
	return result;
}

static int uw_get_charging_priority(u8 *charging_priority)
{
	u8 value;
	int result = uniwill_read_ec_ram(0x07cc, &value);

	if (!result)
		*charging_priority = (value >> 7) & 0x01;
	return result;
}

static int uw_has_charging_priority(bool *status)
{
	u8 data;
	int result;

	/*
	 * The ODM dropped this feature for certain reasons by just disabling the feature within their Control Center.
	 * Therefore every device using the control center until version 5.9.49.16 at least theoretically supports the
	 * feature. However, due to the support identification bit, being listed among the following devices does not
	 * automatically mean that this device supports the feature.
	 * After 5.9.50.3 devices may still have the support identification bit set but don't officially support the
	 * feature anymore.
	*/
	bool device_before_feature_drop = false
		|| dmi_match(DMI_BOARD_NAME, "PH4PRX1_PH6PRX1") // IBP Gen8
		|| dmi_match(DMI_BOARD_NAME, "PH6PG01_PH6PG71")
		|| dmi_match(DMI_BOARD_NAME, "PH4PG31")
		|| dmi_match(DMI_BOARD_NAME, "PHxARX1_PHxAQF1") // IBP Gen7
		|| dmi_match(DMI_BOARD_NAME, "PH6AG01_PH6AQ71_PH6AQI1")
		|| dmi_match(DMI_BOARD_NAME, "PHxTxX1") // IBP Gen6
		|| dmi_match(DMI_BOARD_NAME, "GMxXGxx") // Polaris Gen5
		|| dmi_match(DMI_BOARD_NAME, "GMxNGxx") // Polaris Gen3
		|| dmi_match(DMI_BOARD_NAME, "GMxTGxx") // Stellaris/Polaris Gen3
		|| dmi_match(DMI_BOARD_NAME, "GMxZGxx") // Stellaris Gen3
		|| dmi_match(DMI_BOARD_NAME, "GMxMGxx") // Polaris Gen2
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501I1650TI") // Polaris Gen1
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501A1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701A1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701I1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501I2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501A2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701I2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701A2060")
		|| dmi_match(DMI_BOARD_NAME, "PF5LUXG") // Pulse Gen2
		|| dmi_match(DMI_BOARD_NAME, "PULSE1401") // Pulse Gen1
		|| dmi_match(DMI_BOARD_NAME, "PULSE1501")
		;

	if (!device_before_feature_drop) {
		*status = false;
		return 0;
	}

	result = uniwill_read_ec_ram(0x0742, &data);
	if (result != 0)
		return -EIO;

	if (data & (1 << 5))
		*status = true;
	else
		*status = false;

	return 0;
}

static void uw_charging_priority_write_state(void)
{
	int result;

	mutex_lock(&uniwill_charging_lock);
	if (uw_charging_prio_loaded && uw_charging_prio_state_valid) {
		result = uw_set_charging_priority_locked(uw_charging_prio_last_written_value);
		if (result)
			TUXEDO_ERROR("Could not restore charging priority: %d\n", result);
	}
	mutex_unlock(&uniwill_charging_lock);
}

static void uw_charging_priority_init(struct platform_device *dev)
{
	u8 value;
	int result;
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	mutex_lock(&uniwill_charging_lock);
	uw_charging_prio_loaded = false;
	uw_charging_prio_state_valid = false;
	if (!uw_feats->uniwill_has_charging_prio) {
		mutex_unlock(&uniwill_charging_lock);
		return;
	}
	result = uw_get_charging_priority(&value);
	if (!result) {
		uw_charging_prio_last_written_value = value;
		uw_charging_prio_state_valid = true;
	} else {
		TUXEDO_ERROR("Could not read initial charging priority: %d\n", result);
	}
	mutex_unlock(&uniwill_charging_lock);

	/* Publish after cache initialization. Do not hold charging while sysfs
	 * creates/removes files and may drain a callback waiting for that lock.
	 * A failed read still permits a userspace retry without restoring an
	 * unknown value in the meantime. */
	result = sysfs_create_group(&dev->dev.kobj, &uw_charging_prio_attr_group);
	mutex_lock(&uniwill_charging_lock);
	uw_charging_prio_loaded = !result;
	if (result)
		uw_charging_prio_state_valid = false;
	mutex_unlock(&uniwill_charging_lock);
}

static bool uw_charging_profile_loaded = false;
static bool uw_charging_profile_state_valid;
static u8 uw_charging_profile_last_written_value;

static ssize_t uw_charging_profiles_available_show(struct device *child,
						   struct device_attribute *attr,
						   char *buffer);
static ssize_t uw_charging_profile_show(struct device *child,
					struct device_attribute *attr, char *buffer);
static ssize_t uw_charging_profile_store(struct device *child,
					 struct device_attribute *attr,
					 const char *buffer, size_t size);

struct uw_charging_profile_attrs_t {
	struct device_attribute charging_profiles_available;
	struct device_attribute charging_profile;
} uw_charging_profile_attrs = {
	.charging_profiles_available = __ATTR(charging_profiles_available, 0444, uw_charging_profiles_available_show, NULL),
	.charging_profile = __ATTR(charging_profile, 0644, uw_charging_profile_show, uw_charging_profile_store)
};

static struct attribute *uw_charging_profile_attrs_list[] = {
	&uw_charging_profile_attrs.charging_profiles_available.attr,
	&uw_charging_profile_attrs.charging_profile.attr,
	NULL
};

static struct attribute_group uw_charging_profile_attr_group = {
	.name = "charging_profile",
	.attrs = uw_charging_profile_attrs_list
};

/*
 * charging_profile values
 *     0 => high capacity
 *     1 => balanced
 *     2 => stationary
 */
static int uw_set_charging_profile_locked(u8 charging_profile)
{
	int result;

	/* Code 3 is reserved; never write or cache an undefined profile. */
	if (charging_profile > 2)
		return -EINVAL;

	/* Store unshifted value for later restoration. */
	result = uniwill_update_ec_ram(0x07a6, 0x03 << 4, charging_profile << 4);
	if (!result) {
		uw_charging_profile_last_written_value = charging_profile;
		uw_charging_profile_state_valid = true;
	}
	return result;
}

static int uw_set_charging_profile(u8 charging_profile)
{
	int result;

	mutex_lock(&uniwill_charging_lock);
	result = uw_set_charging_profile_locked(charging_profile);
	mutex_unlock(&uniwill_charging_lock);
	return result;
}

static int uw_get_charging_profile(u8 *charging_profile)
{
	u8 value;
	int result = uniwill_read_ec_ram(0x07a6, &value);

	if (result)
		return result;
	value = (value >> 4) & 0x03;
	if (value > 2)
		return -EIO;
	*charging_profile = value;
	return 0;
}

static int uw_has_charging_profile(bool *status)
{
	u8 data;
	int result;

	bool not_supported_device = false
		|| dmi_match(DMI_BOARD_NAME, "PF5PU1G")
		|| dmi_match(DMI_BOARD_NAME, "LAPQC71A")
		|| dmi_match(DMI_BOARD_NAME, "LAPQC71B")
		|| dmi_match(DMI_PRODUCT_NAME, "A60 MUV")
	;

	if (not_supported_device) {
		*status = false;
		return 0;
	}

	result = uniwill_read_ec_ram(0x078e, &data);
	if (result != 0)
		return -EIO;

	if (data & (1 << 3))
		*status = true;
	else
		*status = false;

	return 0;
}

static void uw_charging_profile_write_state(void)
{
	int result;

	mutex_lock(&uniwill_charging_lock);
	if (uw_charging_profile_loaded && uw_charging_profile_state_valid) {
		result = uw_set_charging_profile_locked(uw_charging_profile_last_written_value);
		if (result)
			TUXEDO_ERROR("Could not restore charging profile: %d\n", result);
	}
	mutex_unlock(&uniwill_charging_lock);
}

static void uw_charging_profile_init(struct platform_device *dev)
{
	u8 value;
	int result;
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	mutex_lock(&uniwill_charging_lock);
	uw_charging_profile_loaded = false;
	uw_charging_profile_state_valid = false;
	if (!uw_feats->uniwill_has_charging_profile) {
		mutex_unlock(&uniwill_charging_lock);
		return;
	}
	result = uw_get_charging_profile(&value);
	if (!result) {
		uw_charging_profile_last_written_value = value;
		uw_charging_profile_state_valid = true;
	} else {
		TUXEDO_ERROR("Could not read initial charging profile: %d\n", result);
	}
	mutex_unlock(&uniwill_charging_lock);

	/* Publish after cache initialization. Do not hold charging while sysfs
	 * creates/removes files and may drain a callback waiting for that lock.
	 * A failed read still permits a userspace retry without restoring an
	 * unknown value in the meantime. */
	result = sysfs_create_group(&dev->dev.kobj, &uw_charging_profile_attr_group);
	mutex_lock(&uniwill_charging_lock);
	uw_charging_profile_loaded = !result;
	if (result)
		uw_charging_profile_state_valid = false;
	mutex_unlock(&uniwill_charging_lock);
}

static void uw_charging_uninit(struct platform_device *dev)
{
	/* Do not hold charging while removing groups: an active sysfs callback
	 * can be waiting for it and sysfs_remove_group waits for that callback. */
	if (uw_charging_prio_loaded)
		sysfs_remove_group(&dev->dev.kobj, &uw_charging_prio_attr_group);
	if (uw_charging_profile_loaded)
		sysfs_remove_group(&dev->dev.kobj, &uw_charging_profile_attr_group);

	mutex_lock(&uniwill_charging_lock);
	uw_charging_prio_loaded = false;
	uw_charging_prio_state_valid = false;
	uw_charging_profile_loaded = false;
	uw_charging_profile_state_valid = false;
	mutex_unlock(&uniwill_charging_lock);
}

struct char_to_u8_t {
	char* descriptor;
	u8 value;
};

static struct char_to_u8_t charging_profile_options[] = {
	{ .descriptor = "high_capacity", .value = 0x00 },
	{ .descriptor = "balanced",	 .value = 0x01 },
	{ .descriptor = "stationary",	 .value = 0x02 }
};

static ssize_t uw_charging_profiles_available_show(struct device *child,
						   struct device_attribute *attr,
						   char *buffer)
{
	int i, n;
	n = ARRAY_SIZE(charging_profile_options);
	for (i = 0; i < n; ++i) {
		sprintf(buffer + strlen(buffer), "%s",
			charging_profile_options[i].descriptor);
		if (i < n - 1)
			sprintf(buffer + strlen(buffer), " ");
		else
			sprintf(buffer + strlen(buffer), "\n");
	}

	return strlen(buffer);
}

static ssize_t uw_charging_profile_show(struct device *child,
					struct device_attribute *attr, char *buffer)
{
	u8 charging_profile_value;
	int i, result;

	result = uw_get_charging_profile(&charging_profile_value);
	if (result != 0)
		return result;

	for (i = 0; i < ARRAY_SIZE(charging_profile_options); ++i)
		if (charging_profile_options[i].value == charging_profile_value) {
			sprintf(buffer, "%s\n", charging_profile_options[i].descriptor);
			return strlen(buffer);
		}

	pr_err("Read charging profile value not matched to a descriptor\n");

	return -EIO;
}

static ssize_t uw_charging_profile_store(struct device *child,
					 struct device_attribute *attr,
					 const char *buffer, size_t size)
{
	u8 charging_profile_value;
	int i, result;
	char *buffer_copy;
	char *charging_profile_descriptor;
	buffer_copy = kmemdup_nul(buffer, size, GFP_KERNEL);
	if (!buffer_copy)
		return -ENOMEM;
	charging_profile_descriptor = strstrip(buffer_copy);

	for (i = 0; i < ARRAY_SIZE(charging_profile_options); ++i)
		if (strcmp(charging_profile_options[i].descriptor, charging_profile_descriptor) == 0) {
			charging_profile_value = charging_profile_options[i].value;
			break;
		}

	kfree(buffer_copy);

	if (i < ARRAY_SIZE(charging_profile_options)) {
		// Option found try to set
		result = uw_set_charging_profile(charging_profile_value);
		if (result == 0)
			return size;
		else
			return -EIO;
	} else
		// Invalid input, not matched to an option
		return -EINVAL;
}

static struct char_to_u8_t charging_prio_options[] = {
	{ .descriptor = "charge_battery", .value = 0x00 },
	{ .descriptor = "performance",    .value = 0x01 }
};

static ssize_t uw_charging_prios_available_show(struct device *child,
						struct device_attribute *attr,
						char *buffer)
{
	int i, n;
	n = ARRAY_SIZE(charging_prio_options);
	for (i = 0; i < n; ++i) {
		sprintf(buffer + strlen(buffer), "%s",
			charging_prio_options[i].descriptor);
		if (i < n - 1)
			sprintf(buffer + strlen(buffer), " ");
		else
			sprintf(buffer + strlen(buffer), "\n");
	}

	return strlen(buffer);
}

static ssize_t uw_charging_prio_show(struct device *child,
				     struct device_attribute *attr, char *buffer)
{
	u8 charging_prio_value;
	int i, result;

	result = uw_get_charging_priority(&charging_prio_value);
	if (result != 0)
		return result;

	for (i = 0; i < ARRAY_SIZE(charging_prio_options); ++i)
		if (charging_prio_options[i].value == charging_prio_value) {
			sprintf(buffer, "%s\n", charging_prio_options[i].descriptor);
			return strlen(buffer);
		}

	pr_err("Read charging prio value not matched to a descriptor\n");

	return -EIO;
}

static ssize_t uw_charging_prio_store(struct device *child,
				      struct device_attribute *attr,
				      const char *buffer, size_t size)
{
	u8 charging_prio_value;
	int i, result;
	char *buffer_copy;
	char *charging_prio_descriptor;
	buffer_copy = kmemdup_nul(buffer, size, GFP_KERNEL);
	if (!buffer_copy)
		return -ENOMEM;
	charging_prio_descriptor = strstrip(buffer_copy);

	for (i = 0; i < ARRAY_SIZE(charging_prio_options); ++i)
		if (strcmp(charging_prio_options[i].descriptor, charging_prio_descriptor) == 0) {
			charging_prio_value = charging_prio_options[i].value;
			break;
		}

	kfree(buffer_copy);

	if (i < ARRAY_SIZE(charging_prio_options)) {
		// Option found try to set
		result = uw_set_charging_priority(charging_prio_value);
		if (result == 0)
			return size;
		else
			return -EIO;
	} else
		// Invalid input, not matched to an option
		return -EINVAL;
}

/*
 * We didn't find any identification bits to retrieve the information if the
 * device supports the features usb_powershare and ac_auto_boot. The nb02
 * control center reads the support flag either from the registry or from the
 * UniWillVariable efivar. The efivar most likely stores this information at an
 * offset of 92 bytes. However, tests have shown that the control center most
 * likely sets the bit in this variable itself dynamically, so we have to check
 * DMI strings for now.
 */
static int is_auto_boot_and_powershare_supported(bool *status)
{
	*status = false ||
		  // IBP Gen9
		  dmi_match(DMI_BOARD_NAME, "GXxMRXx") ||
		  dmi_match(DMI_BOARD_NAME, "GXxHRXx") ||
		  // IBP Gen10
		  dmi_match(DMI_BOARD_NAME, "XxHP4NAx") ||
		  dmi_match(DMI_BOARD_NAME, "XxKK4NAx_XxSP4NAx") ||
		  dmi_match(DMI_BOARD_NAME, "XxAR4NAx") ||

		  // Stellaris Gen6
		  dmi_match(DMI_BOARD_NAME, "GM6IXxB_MB1") ||
		  dmi_match(DMI_BOARD_NAME, "GM6IXxB_MB2") ||
		  dmi_match(DMI_BOARD_NAME, "GM7IXxN") ||
		  // Stellaris Gen7
		  dmi_match(DMI_BOARD_NAME, "X6AR5xxY") ||
		  dmi_match(DMI_BOARD_NAME, "X6AR5xxY_mLED") ||
		  dmi_match(DMI_BOARD_NAME, "X6FR5xxY") ||

		  // Stellaris Slim Gen6
		  dmi_match(DMI_BOARD_NAME, "GMxHGxx") ||
		  dmi_match(DMI_BOARD_NAME, "GM5IXxA") ||

		  // InfinityBook Max Gen10
		  dmi_match(DMI_BOARD_NAME, "X5KK45xS_X5SP45xS") ||
		  dmi_match(DMI_BOARD_NAME, "X6KK45xU_X6SP45xU") ||
		  dmi_match(DMI_BOARD_NAME, "X5AR45xS") ||
		  dmi_match(DMI_BOARD_NAME, "X6AR55xU") ||

		  // Stellaris Gen8
		  dmi_match(DMI_BOARD_NAME, "XxAF5xxx") ||
		  dmi_match(DMI_BOARD_NAME, "XxAF5xxx_mLED") ||

		  /* MECHREVO feature reports: WUJIE 15X Pro v4 and Jiaolong 16K
		   * (LKML 2026-10-16 / 2026-10-23). Same registers and bits as
		   * these helpers; the 16K stays within the reported BIOS scope. */
		  (dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		   (dmi_match(DMI_BOARD_NAME, "WUJIE Series-X5SP4NAG") ||
		    (dmi_match(DMI_BOARD_NAME, "GM6BG0Q") &&
		     dmi_match(DMI_PRODUCT_NAME, "Jiaolong16K Series GM6BG0Q") &&
		     dmi_match(DMI_BIOS_VERSION, "N.1.19MRO15")) ||
		    /* GM5HG0A owner report, LKML 2026-10-08: both switches
		     * tested separately, with the other switch disabled. */
		    (dmi_match(DMI_BOARD_NAME, "GM5HG0A") &&
		     dmi_match(DMI_PRODUCT_NAME, "Yilong15Pro Series GM5HG0A") &&
		     dmi_match(DMI_BIOS_VERSION, "N.1.09MRO19"))));

	return 0;
}

static bool uw_ac_auto_boot_loaded = false;
static bool uw_ac_auto_boot_last_written_value;

static ssize_t uw_ac_auto_boot_show(struct device *child,
				    struct device_attribute *attr,
				    char *buffer);
static ssize_t uw_ac_auto_boot_store(struct device *child,
				     struct device_attribute *attr,
				     const char *buffer, size_t size);

struct uw_ac_auto_boot_attrs_t
{
	struct device_attribute ac_auto_boot;
} uw_ac_auto_boot_attrs = {
	.ac_auto_boot = __ATTR(ac_auto_boot, 0644, uw_ac_auto_boot_show, uw_ac_auto_boot_store)
};

static struct attribute *uw_ac_auto_boot_attrs_list[] = {
	&uw_ac_auto_boot_attrs.ac_auto_boot.attr,
	NULL};

static struct attribute_group uw_ac_auto_boot_attr_group = {
	.name = "ac_auto_boot",
	.attrs = uw_ac_auto_boot_attrs_list};

static int uw_set_ac_auto_boot(u8 ac_auto_boot)
{
	int result;

	ac_auto_boot = (ac_auto_boot & 0x01) << 3;

	result = uniwill_update_ec_ram(UW_EC_REG_AC_AUTO_BOOT_STATUS,
				       1 << 3, ac_auto_boot);
	if (result == 0)
		uw_ac_auto_boot_last_written_value = ac_auto_boot;

	return result;
}

static int uw_get_ac_auto_boot(u8 *ac_auto_boot)
{
	int result;
	result = uniwill_read_ec_ram(UW_EC_REG_AC_AUTO_BOOT_STATUS,
				     ac_auto_boot);
	if (result == 0)
		*ac_auto_boot = (*ac_auto_boot >> 3) & 0x01;
	return result;
}

static int uw_has_ac_auto_boot(bool *status)
{
	return is_auto_boot_and_powershare_supported(status);
}

static void uw_ac_auto_boot_init(struct platform_device *dev)
{
	u8 value;
	int result;
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	uw_ac_auto_boot_loaded = false;
	if (!uw_feats->uniwill_has_ac_auto_boot)
		return;
	/* Initialize only from a successful read, before publishing the group. */
	result = uw_get_ac_auto_boot(&value);
	if (result) {
		pr_err("Could not read initial AC auto-boot state: %d\n", result);
		return;
	}
	uw_ac_auto_boot_last_written_value = value;
	result = sysfs_create_group(&dev->dev.kobj, &uw_ac_auto_boot_attr_group);
	if (result)
		pr_err("Could not register AC auto-boot controls: %d\n", result);
	uw_ac_auto_boot_loaded = result == 0;
}

static ssize_t uw_ac_auto_boot_show(struct device *child,
				    struct device_attribute *attr,
				    char *buffer)
{
	u8 ac_auto_boot_value;
	int result;

	result = uw_get_ac_auto_boot(&ac_auto_boot_value);
	if (result == 0)
		return sprintf(buffer, "%d\n", ac_auto_boot_value);

	return -EIO;
}

static ssize_t uw_ac_auto_boot_store(struct device *child,
				     struct device_attribute *attr,
				     const char *buffer, size_t size)
{
	u8 ac_auto_boot_value;
	int result;

	if (kstrtou8(buffer, 10, &ac_auto_boot_value) ||
	    ac_auto_boot_value < 0 || ac_auto_boot_value > 1)
		return -EINVAL;

	result = uw_set_ac_auto_boot(ac_auto_boot_value);
	if (result == 0)
		return size;
	else
		return -EIO;
}

static bool uw_usb_powershare_loaded = false;
static bool uw_usb_powershare_last_written_value;

static ssize_t uw_usb_powershare_show(struct device *child,
				      struct device_attribute *attr,
				      char *buffer);
static ssize_t uw_usb_powershare_store(struct device *child,
				       struct device_attribute *attr,
				       const char *buffer, size_t size);

struct uw_usb_powershare_attrs_t
{
	struct device_attribute usb_powershare;
} uw_usb_powershare_attrs = {
	.usb_powershare = __ATTR(usb_powershare, 0644, uw_usb_powershare_show, uw_usb_powershare_store)
};

static struct attribute *uw_usb_powershare_attrs_list[] = {
	&uw_usb_powershare_attrs.usb_powershare.attr,
	NULL};

static struct attribute_group uw_usb_powershare_attr_group = {
	.name = "usb_powershare",
	.attrs = uw_usb_powershare_attrs_list};

static int uw_set_usb_powershare(u8 usb_powershare)
{
	int result;

	usb_powershare &= 0x01;
	/* RGB apply uses the same 0x0767 byte. Keep their unrelated bits in one
	 * shared EC read/modify/write transaction. */
	result = uniwill_update_ec_ram(UW_EC_REG_USB_POWERSHARE_STATUS,
				      1 << 4, usb_powershare << 4);
	if (!result)
		uw_usb_powershare_last_written_value = usb_powershare;
	return result;
}

static int uw_get_usb_powershare(u8 *usb_powershare)
{
	int result;
	result = uniwill_read_ec_ram(UW_EC_REG_USB_POWERSHARE_STATUS,
				     usb_powershare);
	if (result == 0)
		*usb_powershare = (*usb_powershare >> 4) & 0x01;
	return result;
}

static int uw_has_usb_powershare(bool *status)
{
	return is_auto_boot_and_powershare_supported(status);
}

static void uw_usb_powershare_init(struct platform_device *dev)
{
	u8 value;
	int result;
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	uw_usb_powershare_loaded = false;
	if (!uw_feats->uniwill_has_usb_powershare)
		return;
	result = uw_get_usb_powershare(&value);
	if (result) {
		pr_err("Could not read initial USB powershare state: %d\n", result);
		return;
	}
	uw_usb_powershare_last_written_value = value;
	result = sysfs_create_group(&dev->dev.kobj, &uw_usb_powershare_attr_group);
	if (result)
		pr_err("Could not register USB powershare controls: %d\n", result);
	uw_usb_powershare_loaded = result == 0;
}

static ssize_t uw_usb_powershare_show(struct device *child,
				      struct device_attribute *attr,
				      char *buffer)
{
	u8 usb_powershare_value;
	int result;

	result = uw_get_usb_powershare(&usb_powershare_value);
	if (result == 0)
		return sprintf(buffer, "%d\n", usb_powershare_value);

	return -EIO;
}

static ssize_t uw_usb_powershare_store(struct device *child,
				       struct device_attribute *attr,
				       const char *buffer, size_t size)
{
	u8 usb_powershare_value;
	int result;

	if (kstrtou8(buffer, 10, &usb_powershare_value) ||
	    usb_powershare_value < 0 || usb_powershare_value > 1)
		return -EINVAL;

	result = uw_set_usb_powershare(usb_powershare_value);
	if (result == 0)
		return size;
	else
		return -EIO;
}

static ssize_t raw_cycle_count_show(struct device *device,
				struct device_attribute *attr,
				char *buf)
{
	int result;
	u16 cycle_count;
	result = uniwill_read_ec_ram_u16(UW_EC_REG_BATTERY_CYCN_HI, UW_EC_REG_BATTERY_CYCN_LO, &cycle_count);
	if (result)
		return result;
	return snprintf(buf, PAGE_SIZE, "%d\n", cycle_count);
}

static ssize_t raw_xif1_show(struct device *device,
				struct device_attribute *attr,
				char *buf)
{
	int result;
	u16 xif1;
	result = uniwill_read_ec_ram_u16(UW_EC_REG_BATTERY_XIF1_HI, UW_EC_REG_BATTERY_XIF1_LO, &xif1);
	if (result)
		return result;
	return snprintf(buf, PAGE_SIZE, "%d\n", xif1);
}

static ssize_t raw_xif2_show(struct device *device,
				struct device_attribute *attr,
				char *buf)
{
	int result;
	u16 xif2;
	result = uniwill_read_ec_ram_u16(UW_EC_REG_BATTERY_XIF2_HI, UW_EC_REG_BATTERY_XIF2_LO, &xif2);
	if (result)
		return result;
	return snprintf(buf, PAGE_SIZE, "%d\n", xif2);
}

static DEVICE_ATTR_RO(raw_cycle_count);
static DEVICE_ATTR_RO(raw_xif1);
static DEVICE_ATTR_RO(raw_xif2);

static struct attribute *uw_battery_attrs[] = {
	&dev_attr_raw_cycle_count.attr,
	&dev_attr_raw_xif1.attr,
	&dev_attr_raw_xif2.attr,
	NULL,
};

ATTRIBUTE_GROUPS(uw_battery);

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 2, 0)
static int uw_battery_add(struct power_supply *battery)
#else
static int uw_battery_add(struct power_supply *battery, struct acpi_battery_hook *hook)
#endif
{
	TUXEDO_DEBUG("uw_battery_add\n");
	if (device_add_groups(&battery->dev, uw_battery_groups))
		return -ENODEV;

	return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 2, 0)
static int uw_battery_remove(struct power_supply *battery)
#else
static int uw_battery_remove(struct power_supply *battery, struct acpi_battery_hook *hook)
#endif
{
	TUXEDO_DEBUG("uw_battery_remove\n");
	device_remove_groups(&battery->dev, uw_battery_groups);
	return 0;
}

static struct acpi_battery_hook uw_battery_hook = {
	.add_battery = uw_battery_add,
	.remove_battery = uw_battery_remove,
	.name = "TUXEDO Battery Extension",
};

static bool uw_battery_hook_registered = false;

static void uw_battery_init(void)
{
	battery_hook_register(&uw_battery_hook);
	uw_battery_hook_registered = true;
}

static void uw_battery_uninit(void)
{
	if (uw_battery_hook_registered)
		battery_hook_unregister(&uw_battery_hook);
	else
		TUXEDO_ERROR("attempted to unregister battery hook which was not registered\n");
}


static bool uw_mini_led_local_dimming_loaded = false;
static bool uw_mini_led_local_dimming_last_written_value;

static ssize_t uw_mini_led_local_dimming_show(struct device *child,
				     struct device_attribute *attr, char *buffer);
static ssize_t uw_mini_led_local_dimming_store(struct device *child,
				      struct device_attribute *attr,
				      const char *buffer, size_t size);

struct uw_mini_led_local_dimming_attrs_t {
	struct device_attribute mini_led_local_dimming;
} uw_mini_led_local_dimming_attrs = {
	.mini_led_local_dimming = __ATTR(mini_led_local_dimming, 0644, uw_mini_led_local_dimming_show, uw_mini_led_local_dimming_store)
};

static struct attribute *uw_mini_led_local_dimming_attrs_list[] = {
	&uw_mini_led_local_dimming_attrs.mini_led_local_dimming.attr,
	NULL
};

static struct attribute_group uw_mini_led_local_dimming_attr_group = {
	.name = "mini_led_local_dimming",
	.attrs = uw_mini_led_local_dimming_attrs_list
};

/*
 * mini_led_local_dimming values
 *     0 => local dimming off
 *     1 => local dimming on
 */
static int uw_set_mini_led_local_dimming(u8 mini_led_local_dimming)
{
	int result;
	u32 uw_data[10];

	if (mini_led_local_dimming == 1) {
		result = uniwill_wmi_evaluate(UNIWILL_WMI_FUNCTION_FEATURE_TOGGLE,
					    UNIWILL_WMI_LOCAL_DIMMING_ON,
					    uw_data);
	} else {
		result = uniwill_wmi_evaluate(UNIWILL_WMI_FUNCTION_FEATURE_TOGGLE,
					    UNIWILL_WMI_LOCAL_DIMMING_OFF,
					    uw_data);
	}
	if (result != 0)
		return result;

	uw_mini_led_local_dimming_last_written_value = mini_led_local_dimming;

	return result;
}

static int uw_get_mini_led_local_dimming(u8 *mini_led_local_dimming)
{
	/*
	 * As of now, we do not have any possibility to read out the current state of local dimming. However,
	 * as this feature is set to disabled on boot per default by calling uw_set_mini_led_local_dimming,
	 * uw_mini_led_local_dimming_last_written_value is always initialized and thereby should not cause
	 * any harm.
	 *
	 * A rather hacky solution could be the following, as uniwill_wmi_evaluate writes the current state
	 * into the return buffer before overwriting it:

	 * u32 return_buffer;
	 * bool initial_status;
	 * uniwill_wmi_evaluate(local_dimming, off, return_buffer);
	 * if (return_buffer == UNIWILL_WMI_LOCAL_DIMMING_ON)
	 * 	initial_status = true;
	 * else
	 * 	initial_status = false;
	 * uniwill_wmi_evaluate(local_dimming, initial_status, return_buffer);
	 * *mini_led_local_dimming = initial_status;
	 */
	*mini_led_local_dimming = uw_mini_led_local_dimming_last_written_value;
	return 0;
}

static int uw_has_mini_led_local_dimming(bool *status)
{
	u8 data;
	int result;

	result = uniwill_read_ec_ram(UW_EC_REG_MINI_LED_LOCAL_DIMMING_SUPPORT,
				     &data);
	if (result)
		return result;

	*status = (data != 0xFF) && ((data & 0x01) > 0);
	return 0;
}

static void uw_mini_led_local_dimming_init(struct platform_device *dev)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	if (!uw_feats->uniwill_has_mini_led_local_dimming)
		return;

	uw_mini_led_local_dimming_loaded = sysfs_create_group(&dev->dev.kobj, &uw_mini_led_local_dimming_attr_group) == 0;

	// Only initialize a supported panel with an available control interface.
	if (uw_mini_led_local_dimming_loaded)
		uw_set_mini_led_local_dimming(false);
}

static ssize_t uw_mini_led_local_dimming_show(struct device *child,
				      struct device_attribute *attr,
				      char *buffer)
{
	u8 mini_led_local_dimming_value;
	int result;

	result = uw_get_mini_led_local_dimming(&mini_led_local_dimming_value);
	if (result == 0)
		return sprintf(buffer, "%d\n", mini_led_local_dimming_value);

	return -EIO;
}

static ssize_t uw_mini_led_local_dimming_store(struct device *child,
				       struct device_attribute *attr,
				       const char *buffer, size_t size)
{
	u8 mini_led_local_dimming_value;
	int result;

	if (kstrtou8(buffer, 10, &mini_led_local_dimming_value) ||
	    mini_led_local_dimming_value < 0 || mini_led_local_dimming_value > 1)
		return -EINVAL;

	result = uw_set_mini_led_local_dimming(mini_led_local_dimming_value);
	if (result == 0)
		return size;
	else
		return -EIO;
}

static efi_guid_t uw_oem_magic_guid =
	EFI_GUID(0x9f33f85c, 0x13ca, 0x4fd1,
	         0x9c, 0x4a, 0x96, 0x21, 0x77, 0x22, 0xc5, 0x93);

static int uw_has_hidden_bios_options(bool *status)
{
	*status = false
		// Stellaris 16 G7
		|| dmi_match(DMI_BOARD_NAME, "X6AR5xxY")
		|| dmi_match(DMI_BOARD_NAME, "X6AR5xxY_mLED")
		// IBM 16 G10
		|| dmi_match(DMI_BOARD_NAME, "X6AR55xU");
	return 0;
}

static void uw_show_hidden_bios_options(void)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	efi_status_t st;
	u32 attr = 0;
	unsigned long size = 0;
	u8 *buf = NULL;
	bool changed = false;
	efi_char16_t name[] = L"OemMagicVariable";
	u8 b1, b2;

	if (!uw_feats->uniwill_has_hidden_bios_options) {
		pr_debug("hidden_bios_options: not supported on this device\n");
		return;
	}

	if (!efi_enabled(EFI_RUNTIME_SERVICES)) {
		pr_warn(
			"hidden_bios_options: EFI runtime services not available\n");
		return;
	}

	st = efi.get_variable(name, &uw_oem_magic_guid, &attr, &size, NULL);
	if (st != EFI_BUFFER_TOO_SMALL) {
		pr_err(
			"hidden_bios_options: get_variable probe failed: st=0x%lx\n",
			(unsigned long)st);
		return;
	}

	if (size <= UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SWITCH) {
		pr_err(
			"hidden_bios_options: EFI variable too small (%lu bytes)\n",
			size);
		return;
	}

	buf = kmalloc(size, GFP_KERNEL);
	if (!buf) {
		pr_err("hidden_bios_options: something went wrong during allocating read buffer\n");
		return;
	}

	st = efi.get_variable(name, &uw_oem_magic_guid, &attr, &size, buf);
	if (st != EFI_SUCCESS) {
		pr_err(
			"hidden_bios_options: get_variable read failed: st=0x%lx\n",
			(unsigned long)st);
		kfree(buf);
		return;
	}

	if (buf[UW_MEMORY_OVERCLOCKING_SUPPORT] != 0x01 ||
	    buf[UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SUPPORT] != 0x01) {
		pr_warn(
			"hidden_bios_options: support bits not set (mem=0x%02x cpu=0x%02x) -> skip\n",
			buf[UW_MEMORY_OVERCLOCKING_SUPPORT],
			buf[UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SUPPORT]);
		kfree(buf);
		return;
	}

	b1 = buf[UW_MEMORY_OVERCLOCKING_SWITCH];
	b2 = buf[UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SWITCH];

	if (!((b1 == 0x00 || b1 == 0x01) && (b2 == 0x00 || b2 == 0x01))) {
		pr_err("hidden_bios_options: unexpected byte values off1=0x%02x off2=0x%02x -> skip\n",
			b1, b2);
		kfree(buf);
		return;
	}

	if (b1 == 0x00) {
		buf[UW_MEMORY_OVERCLOCKING_SWITCH] = 0x01;
		changed = true;
	}
	if (b2 == 0x00) {
		buf[UW_CPU_PERFORMANCE_AND_OVERCLOCKING_SWITCH] = 0x01;
		changed = true;
	}

	if (!changed) {
		pr_debug("hidden_bios_options: already enabled\n");
		kfree(buf);
		return;
	}

	st = efi.set_variable(name, &uw_oem_magic_guid, attr, size, buf);
	if (st != EFI_SUCCESS) {
		pr_warn("hidden_bios_options: set_variable failed: st=0x%lx\n",
			(unsigned long)st);
		kfree(buf);
		return;
	}

	pr_info("hidden_bios_options: enabled hidden BIOS options\n");

	kfree(buf);
}

static const u8 uw_romid_PH4PxX[14] = {0x0C, 0x00, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static const u8 uw_romid_PH6PxX[14] = {0x0C, 0x01, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static const struct dmi_system_id uw_sku_romid_table[] = {
	// IBPG8 mk1
	// Logic: If product serial matches 16inch use that, else default to 14inch
	{
		.matches = {
			DMI_MATCH(DMI_PRODUCT_SKU, "IBP1XI08MK1"),
			DMI_MATCH(DMI_PRODUCT_SERIAL, "PH6PRX"),
		},
		.driver_data = (void *)&uw_romid_PH6PxX
	},
	{
		.matches = {
			DMI_MATCH(DMI_PRODUCT_SKU, "IBP1XI08MK1"),
		},
		.driver_data = (void *)&uw_romid_PH4PxX
	},
	// IBP16G8 mk2
	{
		.matches = {
			DMI_MATCH(DMI_PRODUCT_SKU, "IBP1XI08MK2"),
			DMI_MATCH(DMI_PRODUCT_SERIAL, "PH6"),
		},
		.driver_data = (void *)&uw_romid_PH6PxX
	},
	{}
};

static int set_rom_id(void) {
	int i, ret;
	const struct dmi_system_id *uw_sku_romid;
	const u8 *romid;
	u8 data;
	bool romid_false = false;

	uw_sku_romid = dmi_first_match(uw_sku_romid_table);
	if (!uw_sku_romid)
		return 0;

	romid = (const u8 *)uw_sku_romid->driver_data;
	pr_debug("ROMID 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X 0x%02X\n",
		 romid[0], romid[1], romid[2], romid[3], romid[4], romid[5], romid[6], romid[7],
		 romid[8], romid[9], romid[10], romid[11], romid[12], romid[13]);

	for (i = 0; i < 14; ++i) {
		ret = uniwill_read_ec_ram_with_retry(UW_EC_REG_ROMID_START + i, &data, 3);
		if (ret) {
			pr_debug("uniwill_read_ec_ram_with_retry(...) failed.\n");
			return ret;
		}
		pr_debug("ROMID index: %d, expected value: 0x%02X, actual value: 0x%02X\n", i, romid[i], data);
		if (data != romid[i]) {
			pr_debug("ROMID is false. Correcting...\n");
			romid_false = true;
			break;
		}
	}

	if (romid_false) {
		ret = uniwill_write_ec_ram_with_retry(UW_EC_REG_ROMID_SPECIAL_1, 0xA5, 3);
		if (ret) {
			pr_debug("uniwill_write_ec_ram_with_retry(...) failed.\n");
			return ret;
		}
		ret = uniwill_write_ec_ram_with_retry(UW_EC_REG_ROMID_SPECIAL_2, 0x78, 3);
		if (ret) {
			pr_debug("uniwill_write_ec_ram_with_retry(...) failed.\n");
			return ret;
		}
		for (i = 0; i < 14; ++i) {
			ret = uniwill_write_ec_ram_with_retry(UW_EC_REG_ROMID_START + i, romid[i], 3);
			if (ret) {
				pr_debug("uniwill_write_ec_ram_with_retry(...) failed.\n");
				return ret;
			}
		}
	}
	else
		pr_debug("ROMID is correct.\n");

	return 0;
}

static int has_universal_ec_fan_control(void) {
	int ret;
	u8 data;

	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;

	bool universal_fan_control_exception = false
		// For some reason, on this particular device, the 2nd fan is not controlled via the
		// "GPU" fan curve when the bit to separate both fancurves is set, but the old fan
		// control works just fine.
		|| uw_feats->model == UW_MODEL_PH4TRX
		// For some devices the "universal fan control" doesn't work for turning the fans
		// off reliably, however, the old fan control works.
		|| dmi_match(DMI_BOARD_NAME, "GXxMRXx")
		|| dmi_match(DMI_BOARD_NAME, "XxAR4NAx")
		|| dmi_match(DMI_BOARD_NAME, "X6FR5xxY")
		|| dmi_match(DMI_BOARD_NAME, "X5AR45xS")
	;

	if (universal_fan_control_exception) {
		return 0;
	}

	ret = uniwill_read_ec_ram(0x078e, &data);
	if (ret < 0) {
		return ret;
	}
	return (data >> 6) & 1;
}

static int has_double_pl4(bool *status)
{
	u8 data;
	int result;

	result = uniwill_read_ec_ram(0x0727, &data);
	if (result)
		return result;

	if (data & (1 << 7))
		*status = true;
	else
		*status = false;

	return 0;
}

struct uniwill_device_features_t *uniwill_get_device_features(void)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	u32 status;
	int result;
	bool feats_loaded;

	if (uw_feats_loaded)
		return uw_feats;

	feats_loaded = true;

	status = uniwill_read_ec_ram(0x0740, &uw_feats->model);
	if (status != 0) {
		uw_feats->model = 0;
		feats_loaded = false;
	}

	uw_feats->uniwill_profile_v1_two_profs = false
		|| dmi_match(DMI_BOARD_NAME, "PF5PU1G")
		|| dmi_match(DMI_BOARD_NAME, "PULSE1401")
		|| dmi_match(DMI_BOARD_NAME, "PULSE1501")
	;

	uw_feats->uniwill_profile_v1_three_profs = false
	// Devices with "classic" profile support
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501A1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501A2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501I1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1501I2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701A1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701A2060")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701I1650TI")
		|| dmi_match(DMI_BOARD_NAME, "POLARIS1701I2060")
		|| dmi_match(DMI_BOARD_NAME, "GXxMRXx")
		|| dmi_match(DMI_BOARD_NAME, "GXxHRXx")
		|| dmi_match(DMI_BOARD_NAME, "XxHP4NAx")
		|| dmi_match(DMI_BOARD_NAME, "XxKK4NAx_XxSP4NAx")
		|| dmi_match(DMI_BOARD_NAME, "XxAR4NAx")

		// Note: XMG Fusion removed for now, seem to have
		// neither same power profile control nor TDP set
		//|| dmi_match(DMI_BOARD_NAME, "LAPQC71A")
		//|| dmi_match(DMI_BOARD_NAME, "LAPQC71B")
		//|| dmi_match(DMI_PRODUCT_NAME, "A60 MUV")
	;

	uw_feats->uniwill_profile_v1_three_profs_leds_only = false
	// Devices where profile mainly controls power profile LED status
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
		|| dmi_match(DMI_PRODUCT_SKU, "POLARIS1XA02")
		|| dmi_match(DMI_PRODUCT_SKU, "POLARIS1XI02")
		|| dmi_match(DMI_PRODUCT_SKU, "POLARIS1XA03")
		|| dmi_match(DMI_PRODUCT_SKU, "POLARIS1XI03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XA03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI04")
		|| dmi_match(DMI_PRODUCT_SKU, "STEPOL1XA04")
#endif
	;

	uw_feats->uniwill_custom_profile_mode_needed = false
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
		/* sklynic's tested JIAOLONG 16 Pro 2025 adaptation; exact DMI. */
		|| (dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		    dmi_match(DMI_BOARD_NAME, "JIAOLONG Series-X6xR55xK"))
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS16I06")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS17I06")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS16I07")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS16A07")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLSL15I06")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLSL15A06")
		|| dmi_match(DMI_BOARD_NAME, "GXxMRXx")
		|| dmi_match(DMI_BOARD_NAME, "GXxHRXx")
		|| dmi_match(DMI_BOARD_NAME, "XxHP4NAx")
		|| dmi_match(DMI_BOARD_NAME, "XxKK4NAx_XxSP4NAx")
		|| dmi_match(DMI_BOARD_NAME, "X5KK45xS_X5SP45xS")
		|| dmi_match(DMI_BOARD_NAME, "X6KK45xU_X6SP45xU")
		|| dmi_match(DMI_BOARD_NAME, "X6AR55xU")
		|| dmi_match(DMI_BOARD_NAME, "X5AR45xS")
		|| dmi_match(DMI_BOARD_NAME, "XxAF5xxx")
		|| dmi_match(DMI_BOARD_NAME, "XxAF5xxx_mLED")
#endif
	;


	if (has_double_pl4(&uw_feats->uniwill_has_double_pl4) != 0)
		feats_loaded = false;

	uw_feats->uniwill_profile_v1 =
		uw_feats->uniwill_profile_v1_two_profs ||
		uw_feats->uniwill_profile_v1_three_profs;
	/* GX4HRXL supports the same three mode values (mech-forza-kmod),
	 * but has no evidence for the legacy fan-curve copy in probe. Advertise
	 * modes after computing that legacy initialization flag. GM6BG0Q also
	 * stays out of the fan-table copy: the OEM control center owns its
	 * curves, and hardware only qualified the 0x0751 mode values. */
	uw_feats->uniwill_profile_v1_three_profs |=
		(dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		 (dmi_match(DMI_BOARD_NAME, "GX4HRXL") ||
		  (dmi_match(DMI_BOARD_NAME, "GM6BG0Q") &&
		   dmi_match(DMI_PRODUCT_NAME, "Jiaolong16K Series GM6BG0Q") &&
		   dmi_match(DMI_BIOS_VERSION, "N.1.19MRO15"))));

	if (uw_has_charging_priority(&uw_feats->uniwill_has_charging_prio) != 0)
		feats_loaded = false;
	if (uw_has_charging_profile(&uw_feats->uniwill_has_charging_profile) != 0)
		feats_loaded = false;
	if (uw_has_ac_auto_boot(&uw_feats->uniwill_has_ac_auto_boot) != 0)
		feats_loaded = false;
	if (uw_has_usb_powershare(&uw_feats->uniwill_has_usb_powershare) != 0)
		feats_loaded = false;
	if (uw_has_mini_led_local_dimming(&uw_feats->uniwill_has_mini_led_local_dimming) != 0)
		feats_loaded = false;
	if (uw_has_hidden_bios_options(&uw_feats->uniwill_has_hidden_bios_options) != 0)
		feats_loaded = false;

	result = has_universal_ec_fan_control();
	if (result < 0) {
		feats_loaded = false;
	} else {
		uw_feats->uniwill_has_universal_ec_fan_control = (result == 1);
	}


	if (feats_loaded)
		pr_debug("feats loaded\n");
	else
		pr_debug("feats not yet loaded\n");

	uw_feats_loaded = feats_loaded;

	return uw_feats;
}
EXPORT_SYMBOL(uniwill_get_device_features);

bool uniwill_device_features_ready(void)
{
	return uw_feats_loaded;
}
EXPORT_SYMBOL(uniwill_device_features_ready);

// Fn lock

static int uniwill_wmi_fn_lock_get(int *on)
{
	u8 data;
	int err;

	err = uniwill_read_ec_ram(UW_EC_REG_KBD_FN_LOCK_STATUS_BIT, &data);
	if (err)
		return err;

	if (on)
		*on = (data & UNIWILL_FN_LOCK_MASK) >> 4;

	return 0;
}

static int uniwill_wmi_fn_lock_set(int on)
{
	/* Preserve the other fields across a single shared EC transaction. */
	return uniwill_update_ec_ram(UW_EC_REG_KBD_FN_LOCK_STATUS_BIT,
				    UNIWILL_FN_LOCK_MASK,
				    on ? UNIWILL_FN_LOCK_MASK : 0);
}

static ssize_t uniwill_fn_lock_show(struct device *dev,
		struct device_attribute *attr,
		char *buf)
{
	int err, on;

	err = uniwill_wmi_fn_lock_get(&on);
	if (err)
		return err;

	return sprintf(buf, "%d\n", on);
}

static ssize_t uniwill_fn_lock_store(struct device *dev,
		struct device_attribute *attr,
		const char *buf, size_t size)
{
	int on, err;

	if (kstrtoint(buf, 10, &on) ||
			on < 0 || on > 1)
		return -EINVAL;

	err = uniwill_wmi_fn_lock_set(on);
	if (err)
		return err;

	return size;
}

static bool uniwill_fn_lock_available(void){
	int err, on;

	// Fn lock does not work for XMG Fusion
	// exclude all versions
	if (dmi_match(DMI_BOARD_NAME, "LAPQC71A")
	    || dmi_match(DMI_BOARD_NAME, "LAPQC71B")
	    || dmi_match(DMI_PRODUCT_NAME, "A60 MUV")) {
		return 0;
	}

	// do a read for test (this may not produce an error)
	err = uniwill_wmi_fn_lock_get(&on);
	if (err)
		return 0;
	else
		return 1;
}

static u8 direct_fan_control_current_value_fan0 = 0;
static u8 direct_fan_control_current_value_fan1 = 0;
static u8 direct_fan_control_current_value_fan0_suspend_save = 0;
static u8 direct_fan_control_current_value_fan1_suspend_save = 0;
static bool fans_initialized = false;
/* A committed RAM table owns manual cooling even if a later target write
 * fails. This must never enable the legacy periodic restart worker. */
static bool universal_fan_manual_active;
static bool direct_fan_control_started = false;
static bool direct_fan_control_restart_needed = false;
static bool direct_fan_control_suspend = false;
/* A failed explicit mode override may have reached firmware. Keep the old
 * targets for an explicit retry, but never let background work or PM silently
 * reapply them over that uncertain request. */
static bool legacy_fan_mode_override_blocked;
/* The fan-restore flag above is false in AUTO. It cannot describe device PM. */
static bool uniwill_pm_ready;
static bool uniwill_pm_suspended;
/* Lock order: command -> state -> EC transport. The worker only takes state.
 * Never wait for that worker with state held: cancellation first blocks its
 * entry/requeue under state, drops state, and drains it under command. */
static DEFINE_MUTEX(uniwill_fan_command_lock);
static DEFINE_MUTEX(uniwill_fan_state_lock);
static bool uniwill_fan_work_paused;
static bool uniwill_fan_removed;
static void restart_direct_fan_control_work_handler(struct work_struct *work);
static int uw_restore_fan_state_locked(void);
static DECLARE_DELAYED_WORK(direct_fan_control_restart_delayed_work, restart_direct_fan_control_work_handler);

static void uw_fan_quiesce_locked(void)
{
	lockdep_assert_held(&uniwill_fan_command_lock);
	lockdep_assert_held(&uniwill_fan_state_lock);
	uniwill_fan_work_paused = true;
	mutex_unlock(&uniwill_fan_state_lock);
	cancel_delayed_work_sync(&direct_fan_control_restart_delayed_work);
	mutex_lock(&uniwill_fan_state_lock);
}

static int uw_fan_lock(bool cancel_work)
{
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	if (uniwill_fan_removed) {
		mutex_unlock(&uniwill_fan_state_lock);
		mutex_unlock(&uniwill_fan_command_lock);
		return -ENODEV;
	}
	if (cancel_work)
		uw_fan_quiesce_locked();
	return 0;
}

static void uw_fan_unlock(void)
{
	uniwill_fan_work_paused = false;
	mutex_unlock(&uniwill_fan_state_lock);
	mutex_unlock(&uniwill_fan_command_lock);
}

static int uw_fan_lock_active(bool cancel_work)
{
	int status = uw_fan_lock(false);
	if (status)
		return status;
	if (!uniwill_pm_ready) {
		uw_fan_unlock();
		return -ENODEV;
	}
	if (uniwill_pm_suspended) {
		uw_fan_unlock();
		return -EBUSY;
	}
	if (cancel_work)
		uw_fan_quiesce_locked();
	return 0;
}

static void uw_legacy_fan_override_begin_locked(void)
{
	if (uniwill_device_features.uniwill_has_universal_ec_fan_control)
		return;
	if (direct_fan_control_started || direct_fan_control_suspend ||
	    legacy_fan_mode_override_blocked) {
		legacy_fan_mode_override_blocked = true;
		uw_fan_quiesce_locked();
		/* No automatic requeue after an ambiguous read/write failure. */
		direct_fan_control_restart_needed = direct_fan_control_started;
	}
}

static void uw_legacy_fan_override_finish_locked(int status)
{
	if (status || uniwill_device_features.uniwill_has_universal_ec_fan_control)
		return;
	direct_fan_control_started = false;
	direct_fan_control_restart_needed = false;
	direct_fan_control_suspend = false;
	legacy_fan_mode_override_blocked = false;
	direct_fan_control_current_value_fan0 = 0;
	direct_fan_control_current_value_fan1 = 0;
	direct_fan_control_current_value_fan0_suspend_save = 0;
	direct_fan_control_current_value_fan1_suspend_save = 0;
}

int uw_set_mode(u8 value)
{
	int status = uw_fan_lock_active(false);
	if (status)
		return status;
	uw_legacy_fan_override_begin_locked();
	status = uniwill_write_ec_ram(0x0751, value);
	uw_legacy_fan_override_finish_locked(status);
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_set_mode);

int uw_update_mode(u8 clear_mask, u8 set_mask)
{
	u8 value;
	int status = uw_fan_lock_active(false);
	if (status)
		return status;
	/* Profile/TDP updates preserve bit 6 and retain manual ownership. */
	if ((clear_mask | set_mask) & 0x40)
		uw_legacy_fan_override_begin_locked();
	status = uniwill_read_ec_ram(0x0751, &value);
	if (!status)
		status = uniwill_write_ec_ram(0x0751, (value & ~clear_mask) | set_mask);
	if ((clear_mask | set_mask) & 0x40)
		uw_legacy_fan_override_finish_locked(status);
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_update_mode);

/* The mode prerequisite and TDP write form one device command. In particular,
 * neither a new profile nor PM/removal may intervene before the final write.
 * The caller validates the model's power limits before encoding this byte. */
int uw_write_tdp(u8 tdp_index, u8 tdp_data)
{
	u8 mode;
	int status;

	if (tdp_index > 2)
		return -EINVAL;
	status = uw_fan_lock_active(false);
	if (status)
		return status;
	if (uniwill_device_features.uniwill_custom_profile_mode_needed) {
		status = uniwill_read_ec_ram(0x0751, &mode);
		if (!status)
			status = uniwill_write_ec_ram(0x0751, (mode & ~0xb0) | 0x10);
	}
	if (!status)
		status = uniwill_write_ec_ram(0x0783 + tdp_index, tdp_data);
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_write_tdp);

static int set_full_fan_mode_locked(bool enable) {
	u8 mode_data;
	int status;

	status = uniwill_read_ec_ram(0x0751, &mode_data);
	if (status)
		return status;

	if (enable && !(mode_data & 0x40)) {
		// If not "full fan mode" (i.e. 0x40 bit not set) switch to it (required for old fancontrol)
		return uniwill_write_ec_ram(0x0751, mode_data | 0x40);
	}
	else if (!enable && (mode_data & 0x40)) {
		// If "full fan mode" (i.e. 0x40 bit set) turn it off (required for new fancontrol)
		return uniwill_write_ec_ram(0x0751, mode_data & ~0x40);
	}

	return 0;
}

int set_full_fan_mode(bool enable)
{
	int status = uw_fan_lock_active(false);
	if (status)
		return status;
	uw_legacy_fan_override_begin_locked();
	status = set_full_fan_mode_locked(enable);
	uw_legacy_fan_override_finish_locked(status);
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(set_full_fan_mode);

static int uw_init_fan_locked(void) {
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	int i, temp_offset, status, recovery_status;

	u16 addr_use_custom_fan_table_0 = 0x07c5; // use different tables for both fans (0x0f00-0x0f2f and 0x0f30-0x0f5f respectivly)
	u16 addr_use_custom_fan_table_1 = 0x07c6; // enable 0x0fxx fantables
	u8 offset_use_custom_fan_table_0 = 7;
	u8 offset_use_custom_fan_table_1 = 2;
	u8 value_use_custom_fan_table_0;
	u8 value_use_custom_fan_table_1;
	u16 addr_cpu_custom_fan_table_end_temp = 0x0f00;
	u16 addr_cpu_custom_fan_table_start_temp = 0x0f10;
	u16 addr_cpu_custom_fan_table_fan_speed = 0x0f20;
	u16 addr_gpu_custom_fan_table_end_temp = 0x0f30;
	u16 addr_gpu_custom_fan_table_start_temp = 0x0f40;
	u16 addr_gpu_custom_fan_table_fan_speed = 0x0f50;

	if (!fans_initialized && uw_feats->uniwill_has_universal_ec_fan_control) {
		/* OEM RAMFan1p5 commits disable -> table -> enable. Never edit a
		 * live table, including after a stale initialization cache. */
		status = uniwill_read_ec_ram(addr_use_custom_fan_table_1, &value_use_custom_fan_table_1);
		if (status)
			return status;
		if (value_use_custom_fan_table_1 & (1 << offset_use_custom_fan_table_1)) {
			status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_1,
				value_use_custom_fan_table_1 & ~(1 << offset_use_custom_fan_table_1), 3);
			if (status)
				return status;
		}

		status = set_full_fan_mode_locked(false);
		if (status)
			return status;

		status = uniwill_read_ec_ram(addr_use_custom_fan_table_0, &value_use_custom_fan_table_0);
		if (status)
			return status;
		if (!((value_use_custom_fan_table_0 >> offset_use_custom_fan_table_0) & 1)) {
			status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_0, value_use_custom_fan_table_0 + (1 << offset_use_custom_fan_table_0), 3);
			if (status)
				return status;
		}

		// Setup
		// - one controllable zone 0-115 deg
		// - rest 116-117, 117-118 etc single non reachable dummy zones
		//   with increasing ranges and max fan (same or increasing)
		status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_end_temp, 115, 3);
		if (status)
			return status;
		status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_start_temp, 0, 3);
		if (status)
			return status;
		status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_fan_speed, 0x01, 3);
		if (status)
			return status;
		status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_end_temp, 120, 3);
		if (status)
			return status;
		status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_start_temp, 0, 3);
		if (status)
			return status;
		status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_fan_speed, 0x01, 3);
		if (status)
			return status;
		temp_offset = 115;
		for (i = 0x1; i <= 0xf; ++i) {
			status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_end_temp + i, temp_offset + i + 1, 3);
			if (status)
				return status;
			status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_start_temp + i, temp_offset + i, 3);
			if (status)
				return status;
			status = uniwill_write_ec_ram_with_retry(addr_cpu_custom_fan_table_fan_speed + i, 0xc8, 3);
			if (status)
				return status;
			status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_end_temp + i, temp_offset + i + 1, 3);
			if (status)
				return status;
			status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_start_temp + i, temp_offset + i, 3);
			if (status)
				return status;
			status = uniwill_write_ec_ram_with_retry(addr_gpu_custom_fan_table_fan_speed + i, 0xc8, 3);
			if (status)
				return status;
		}

		status = uniwill_read_ec_ram(addr_use_custom_fan_table_1, &value_use_custom_fan_table_1);
		if (status)
			return status;
		if (!((value_use_custom_fan_table_1 >> offset_use_custom_fan_table_1) & 1)) {
			/* The commit may land even if transport verification fails. Keep
			 * conservative ownership until disabling is itself verified. */
			universal_fan_manual_active = true;
			status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_1, value_use_custom_fan_table_1 + (1 << offset_use_custom_fan_table_1), 3);
			if (status) {
				/* A write may have reached firmware even when verification
				 * failed. Preserve the original errno and report recovery
				 * independently; failed transport cannot prove AUTO. */
				recovery_status = uniwill_read_ec_ram(addr_use_custom_fan_table_1,
					&value_use_custom_fan_table_1);
				if (!recovery_status)
					recovery_status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_1,
						value_use_custom_fan_table_1 & ~(1 << offset_use_custom_fan_table_1), 3);
				if (recovery_status)
					pr_err("Could not disable fan table after failed commit: %d\n", recovery_status);
				else
					universal_fan_manual_active = false;
				return status;
			}
		}
		universal_fan_manual_active = true;
	}

	fans_initialized = true;

	return 0;
}

/* Rebuilding an owned table resets both first duties. Preserve the complete
 * successful pair before rebuilding, even for a one-fan explicit request.
 * The pending flag keeps setters inside restore from recursively restoring. */
static int uw_init_fan_preserving_targets_locked(void)
{
	bool restore_pair = uniwill_device_features.uniwill_has_universal_ec_fan_control &&
		!fans_initialized && universal_fan_manual_active && !direct_fan_control_suspend;
	int status;

	if (restore_pair) {
		direct_fan_control_current_value_fan0_suspend_save = direct_fan_control_current_value_fan0;
		direct_fan_control_current_value_fan1_suspend_save = direct_fan_control_current_value_fan1;
		direct_fan_control_suspend = true;
	}
	status = uw_init_fan_locked();
	/* Raw initialization already handles uncertain commit recovery. */
	if (!status && restore_pair)
		status = uw_restore_fan_state_locked();
	return status;
}

int uw_init_fan(void)
{
	bool universal;
	int status = uw_fan_lock_active(false);
	if (status)
		return status;
	universal = uniwill_device_features.uniwill_has_universal_ec_fan_control;
	/* A valid table was historically a no-op here, including under FULL.
	 * Pending PM intent must not turn that no-op into table cancellation. */
	if (universal && direct_fan_control_suspend && fans_initialized) {
		u8 mode;
		status = uniwill_read_ec_ram(0x0751, &mode);
		if (status || (mode & 0x40))
			goto unlock;
	}
	status = uw_init_fan_preserving_targets_locked();
	/* A repeated explicit init may enter with intent saved by an earlier
	 * failed init or PM restore. Internal setters must not do this step. */
	if (!status && universal && direct_fan_control_suspend)
		status = uw_restore_fan_state_locked();
	/* FULL may change after the precheck. PM cancellation returns zero,
	 * but cannot establish successful initialization of a disabled table. */
	if (!status && universal && !fans_initialized)
		status = -EBUSY;
unlock:
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_init_fan);

/* State is already held by both public commands and the maintenance worker.
 * This is a bounded sequence of transport calls, not an atomic transaction or
 * a mechanical-speed guarantee; transport latency is not bounded here. */
static int uw_restart_direct_fan_control_locked(u8 fan0, u8 fan1)
{
	int i, status;
	u16 addr_fan0 = 0x1804;
	u16 addr_fan1 = 0x1809;

	lockdep_assert_held(&uniwill_fan_state_lock);
	status = set_full_fan_mode_locked(false);
	if (status)
		return status;
	msleep(10);
	status = set_full_fan_mode_locked(true);
	if (status)
		return status;

	// Attempt to write both fans as quick as possible before complete ramp-up
	pr_debug("prevent ramp-up start\n");
	for (i = 0; i < 10; ++i) {
		status = uniwill_write_ec_ram(addr_fan0, fan0);
		if (status)
			return status;
		status = uniwill_write_ec_ram(addr_fan1, fan1);
		if (status)
			return status;
		msleep(10);
	}
	pr_debug("prevent ramp-up done\n");
	return 0;
}

static void restart_direct_fan_control_work_handler(struct work_struct *work)
{
	int status;

	mutex_lock(&uniwill_fan_state_lock);
	if (uniwill_fan_work_paused || uniwill_fan_removed || !uniwill_pm_ready || uniwill_pm_suspended || !direct_fan_control_started || legacy_fan_mode_override_blocked)
		goto unlock;
	pr_debug("restart fan control\n");

	status = uw_restart_direct_fan_control_locked(direct_fan_control_current_value_fan0,
						    direct_fan_control_current_value_fan1);
	if (status)
		goto failed;

	direct_fan_control_restart_needed = false;
	goto reschedule;

failed:
	direct_fan_control_restart_needed = true;
	pr_err("Could not restart direct fan control: %d\n", status);

reschedule:
	if (!uniwill_fan_work_paused && !uniwill_fan_removed && uniwill_pm_ready && !uniwill_pm_suspended)
		schedule_delayed_work(&direct_fan_control_restart_delayed_work, msecs_to_jiffies(50 * 60 * 1000));
unlock:
	mutex_unlock(&uniwill_fan_state_lock);
}

static int direct_fan_control(u32 fan_index, u8 fan_speed, bool prevent_rampup)
{
	u16 addr_for_fan;
	u16 addr_fan0 = 0x1804;
	u16 addr_fan1 = 0x1809;
	int status;

	if (fan_index == 0) {
		addr_for_fan = addr_fan0;
	} else if (fan_index == 1) {
		addr_for_fan = addr_fan1;
	} else {
		return -EINVAL;
	}

	if (prevent_rampup && (!direct_fan_control_started || direct_fan_control_restart_needed)) {
		/* These are desired targets, not proof of applied mechanical speed.
		 * Keep them and conservative ownership if a transport call fails. */
		if (fan_index == 0)
			direct_fan_control_current_value_fan0 = fan_speed;
		else
			direct_fan_control_current_value_fan1 = fan_speed;
		direct_fan_control_started = true;
		direct_fan_control_restart_needed = true;
		status = uw_restart_direct_fan_control_locked(direct_fan_control_current_value_fan0,
							    direct_fan_control_current_value_fan1);
		if (status)
			return status;
		direct_fan_control_restart_needed = false;
		/* Only periodic maintenance remains asynchronous. The initial or
		 * recovery command reports every required transport error itself. */
		schedule_delayed_work(&direct_fan_control_restart_delayed_work,
				      msecs_to_jiffies(50 * 60 * 1000));
	} else {
		status = uniwill_write_ec_ram(addr_for_fan, fan_speed & 0xff);
		if (status)
			return status;
		if (fan_index == 0)
			direct_fan_control_current_value_fan0 = fan_speed;
		else
			direct_fan_control_current_value_fan1 = fan_speed;
	}

	return 0;
}

static u32 uw_set_fan_locked(u32 fan_index, u8 fan_speed)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	u16 addr_for_fan;

	u16 addr_cpu_custom_fan_table_fan_speed = 0x0f20;
	u16 addr_gpu_custom_fan_table_fan_speed = 0x0f50;

	u8 byte_data;
	int status;

	if (fan_index > 1)
		return -EINVAL;

	if (uw_feats->uniwill_has_universal_ec_fan_control) {
		if (fan_speed > NB02_FAN_SPEED_MAX)
			return -EINVAL;
		status = uniwill_read_ec_ram(0x0751, &byte_data);
		if (status)
			return status;
		if (!(byte_data & 0x40)) {
			status = uw_init_fan_preserving_targets_locked();
			if (status)
				return status;

			if (fan_index == 0)
				addr_for_fan = addr_cpu_custom_fan_table_fan_speed;
			else
				addr_for_fan = addr_gpu_custom_fan_table_fan_speed;

			// Don't allow vallues between fan-off and minimum fan-on-speed
			if (fan_speed < FAN_ON_MIN_SPEED_PERCENT * NB02_FAN_SPEED_MAX / 2 / 100)
				fan_speed = 0;
			else if (fan_speed < FAN_ON_MIN_SPEED_PERCENT * NB02_FAN_SPEED_MAX / 100)
				fan_speed = FAN_ON_MIN_SPEED_PERCENT * NB02_FAN_SPEED_MAX / 100;

			if (fan_speed == 0) {
				// Avoid hard coded EC behaviour: Setting fan speed = 0x00 spins the fan up
				// to 0x3c (30%) for 3 minutes before going to 0x00. Setting fan speed = 1
				// also causes the fan to stop since on 2020 or later TF devices the
				// microcontroller in the fan itself is intelligent enough to not try to
				// start up the motor when the speed is to slow. Older devices don't use
				// this fan controll anyway, but the else case below.
				fan_speed = 1;
			}

			status = uniwill_write_ec_ram(addr_for_fan, fan_speed & 0xff);
			if (!status)
				status = direct_fan_control(fan_index, fan_speed, false);
			if (status) {
				/* Either write may have landed. Keep the last successful
				 * pair and require full recovery before another target. */
				if (!direct_fan_control_suspend) {
					direct_fan_control_current_value_fan0_suspend_save = direct_fan_control_current_value_fan0;
					direct_fan_control_current_value_fan1_suspend_save = direct_fan_control_current_value_fan1;
					direct_fan_control_suspend = true;
				}
				fans_initialized = false;
			}
			return status;
		}
		/* Full fan mode owns fan control; do not claim an unapplied target. */
		return -EBUSY;
	}
	else { // old workaround using full fan mode
		if (direct_fan_control_suspend && !direct_fan_control_started) {
			direct_fan_control_current_value_fan0 = direct_fan_control_current_value_fan0_suspend_save;
			direct_fan_control_current_value_fan1 = direct_fan_control_current_value_fan1_suspend_save;
		}
		status = direct_fan_control(fan_index, fan_speed, true);
		if (!status)
			legacy_fan_mode_override_blocked = false;
		if (!status && direct_fan_control_suspend) {
			/* A recovery restart applies the complete desired pair, including
			 * a target retained from an earlier failed per-fan request. */
			direct_fan_control_current_value_fan0_suspend_save = direct_fan_control_current_value_fan0;
			direct_fan_control_current_value_fan1_suspend_save = direct_fan_control_current_value_fan1;
		}
		return status;
	}

	return 0;
}

u32 uw_set_fan(u32 fan_index, u8 fan_speed)
{
	int status = uw_fan_lock_active(false);
	if (status)
		return status;
	if (fan_index > 1 ||
	    (uniwill_device_features.uniwill_has_universal_ec_fan_control && fan_speed > NB02_FAN_SPEED_MAX)) {
		uw_fan_unlock();
		return -EINVAL;
	}
	if (direct_fan_control_restart_needed)
		uw_fan_quiesce_locked();
	/* Failed PM restoration retains both saved targets. Retry that complete
	 * operation before accepting a new per-fan request. */
	if (uniwill_device_features.uniwill_has_universal_ec_fan_control && direct_fan_control_suspend) {
		status = uw_restore_fan_state_locked();
		if (status) {
			uw_fan_unlock();
			return status;
		}
	}
	status = (int)uw_set_fan_locked(fan_index, fan_speed);
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_set_fan);

static u32 uw_set_fan_auto_locked(void)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	u8 mode_data;
	int status;

	if (uw_feats->uniwill_has_universal_ec_fan_control) {
		u16 addr_use_custom_fan_table_0 = 0x07c5; // use different tables for both fans (0x0f00-0x0f2f and 0x0f30-0x0f5f respectivly)
		u16 addr_use_custom_fan_table_1 = 0x07c6; // enable 0x0fxx fantables
		u8 offset_use_custom_fan_table_0 = 7;
		u8 offset_use_custom_fan_table_1 = 2;
		u8 value_use_custom_fan_table_0;
		u8 value_use_custom_fan_table_1;
		/* A partial reset must not leave the initialization cache valid. */
		fans_initialized = false;
		status = uniwill_read_ec_ram(addr_use_custom_fan_table_1, &value_use_custom_fan_table_1);
		if (status)
			return status;
		if ((value_use_custom_fan_table_1 >> offset_use_custom_fan_table_1) & 1) {
			status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_1, value_use_custom_fan_table_1 - (1 << offset_use_custom_fan_table_1), 3);
			if (status)
				return status;
		}
		status = uniwill_read_ec_ram(addr_use_custom_fan_table_0, &value_use_custom_fan_table_0);
		if (status)
			return status;
		if ((value_use_custom_fan_table_0 >> offset_use_custom_fan_table_0) & 1) {
			status = uniwill_write_ec_ram_with_retry(addr_use_custom_fan_table_0, value_use_custom_fan_table_0 - (1 << offset_use_custom_fan_table_0), 3);
			if (status)
				return status;
		}
	}
	else {
		/* Keep manual-mode recovery active if the EC reset fails. Only a
		 * subsequent manual request should restart the cancelled worker. */
		direct_fan_control_restart_needed = direct_fan_control_started;
		// Get current mode after the worker can no longer change it.
		status = uniwill_read_ec_ram(0x0751, &mode_data);
		if (status)
			return status;
		// Switch off "full fan mode" (i.e. unset 0x40 bit)
		status = uniwill_write_ec_ram(0x0751, mode_data & 0xbf);
		if (status)
			return status;
	}

	universal_fan_manual_active = false;
	legacy_fan_mode_override_blocked = false;
	direct_fan_control_started = false;
	direct_fan_control_restart_needed = false;
	direct_fan_control_suspend = false;
	direct_fan_control_current_value_fan0 = 0;
	direct_fan_control_current_value_fan1 = 0;

	return 0;
}

u32 uw_set_fan_auto(void)
{
	int status = uw_fan_lock_active(true);
	if (status)
		return status;
	/* An explicit AUTO may reach firmware even when transport fails. Do not
	 * let PM replay old legacy targets until a new explicit manual request.
	 * PM's temporary AUTO uses the locked helper and retains its rollback. */
	if (!uniwill_device_features.uniwill_has_universal_ec_fan_control &&
	    (direct_fan_control_started || direct_fan_control_suspend || legacy_fan_mode_override_blocked))
		legacy_fan_mode_override_blocked = true;
	status = (int)uw_set_fan_auto_locked();
	uw_fan_unlock();
	return status;
}
EXPORT_SYMBOL(uw_set_fan_auto);

static int uw_fan_control_start(void)
{
	int status;
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	uw_fan_quiesce_locked();
	uniwill_fan_removed = true;
	uniwill_pm_ready = false;
	direct_fan_control_suspend = false;
	fans_initialized = false;
	/* Failed removal can leave an owned/uncertain RAM table. A rebind in
	 * this module must verify its release before forgetting that ownership.
	 * Lost capability is not permission to touch an unqualified device. */
	if (universal_fan_manual_active) {
		status = uniwill_device_features.uniwill_has_universal_ec_fan_control ?
			(int)uw_set_fan_auto_locked() : -ENODEV;
		if (status) {
			uw_fan_unlock();
			return status;
		}
	}
	uniwill_fan_removed = false;
	uniwill_pm_suspended = false;
	fans_initialized = false;
	universal_fan_manual_active = false;
	legacy_fan_mode_override_blocked = false;
	direct_fan_control_started = false;
	direct_fan_control_restart_needed = false;
	direct_fan_control_suspend = false;
	direct_fan_control_current_value_fan0 = 0;
	direct_fan_control_current_value_fan1 = 0;
	direct_fan_control_current_value_fan0_suspend_save = 0;
	direct_fan_control_current_value_fan1_suspend_save = 0;
	status = uniwill_write_ec_ram(0x0751, 0x00);
	uniwill_fan_removed = status != 0;
	uw_fan_unlock();
	return status;
}

static u8 uniwill_touchp_toggle_seq[] = {
	0xe0, 0x5b, // Super down
	0x1d,       // Control down
	0x76,       // Zenkaku/Hankaku down
	0xf6,       // Zenkaku/Hankaku up
	0x9d,       // Control up
	0xe0, 0xdb  // Super up
};
static bool uniwill_i8042_filter_installed;
static u8 uniwill_touchp_toggle_seq_pos;

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 14, 0)
static bool uniwill_i8042_filter(unsigned char data, unsigned char str,
				 struct serio *port __always_unused)
#else
static bool uniwill_i8042_filter(unsigned char data, unsigned char str,
				 struct serio *port __always_unused,
				 void *context __always_unused)
#endif
{
	if (unlikely(str & I8042_STR_AUXDATA))
		return false;

	if (unlikely(data == uniwill_touchp_toggle_seq[uniwill_touchp_toggle_seq_pos])) {
		++uniwill_touchp_toggle_seq_pos;
		if (unlikely(data == 0x76 || data == 0xf6))
			return true;
		else if (unlikely(uniwill_touchp_toggle_seq_pos == ARRAY_SIZE(uniwill_touchp_toggle_seq))) {
			schedule_work(&uniwill_key_event_work);
			uniwill_touchp_toggle_seq_pos = 0;
		}
		return false;
	}

	uniwill_touchp_toggle_seq_pos = 0;
	return false;
}

static void uniwill_restore_adapter_state(void)
{
	int status = uw_fan_lock(false);
	if (status)
		return;
	/* A late event must not undo suspend's custom-profile reset or touch
	 * LED/charging resources before probe or after removal. */
	if (uniwill_pm_ready && !uniwill_pm_suspended) {
		status = uniwill_set_custom_profile_mode(false);
		if (status)
			TUXEDO_ERROR("Could not restore custom profile mode: %d\n", status);
		uniwill_leds_restore_state_extern();
		msleep(50);
		uw_charging_priority_write_state();
		uw_charging_profile_write_state();
	}
	uw_fan_unlock();
}

static void uniwill_keyboard_prepare_remove(void)
{
	/* The common hook and a direct platform unbind may both quiesce us. */
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	uniwill_pm_ready = false;
	uniwill_pm_suspended = true;
	mutex_unlock(&uniwill_fan_state_lock);
	/* i8042_remove_filter() synchronizes the filter before work is drained,
	 * so no new touchpad workaround can be queued after cancellation. */
	if (uniwill_i8042_filter_installed) {
		if (i8042_remove_filter(uniwill_i8042_filter))
			pr_info("Could not remove i8042 filter.\n");
		uniwill_i8042_filter_installed = false;
	}
	/* The old callback is synchronized before its partial sequence is reset. */
	uniwill_touchp_toggle_seq_pos = 0;
	cancel_work_sync(&uniwill_key_event_work);
	mutex_unlock(&uniwill_fan_command_lock);
}

static int uniwill_keyboard_abort_probe(int status, bool disable_manual_mode)
{
	int cleanup_status;

	/* No device resources or event filter have been published yet. Close
	 * exported fan commands and drain a request that raced initialization. */
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	uniwill_fan_removed = true;
	uw_fan_quiesce_locked();
	/* Only undo the manual-enable write that this probe confirmed. A
	 * partially copied curve or a failed enable has no known rollback. */
	if (disable_manual_mode) {
		cleanup_status = uniwill_write_ec_ram(0x0741, 0x00);
		if (cleanup_status)
			TUXEDO_ERROR("Could not disable manual fan mode after failed probe: %d\n", cleanup_status);
	}
	mutex_unlock(&uniwill_fan_state_lock);
	mutex_unlock(&uniwill_fan_command_lock);
	TUXEDO_ERROR("Could not initialize fan control: %d\n", status);
	return status;
}

static int uniwill_keyboard_probe(struct platform_device *dev)
{
	u32 i;
	u8 data;
	int status;
	struct uniwill_device_features_t *uw_feats;

	/* A new binding must not restore a backlight state from an old one. */
	uniwill_kbd_bl_enable_state_on_start = 0xff;
	set_rom_id();

	uw_feats = uniwill_get_device_features();

	// FIXME Hard set balanced profile until we have implemented a way to
	// switch it while tuxedo_io is loaded
	// uw_ec_write_addr(0x51, 0x07, 0x00, 0x00, &reg_write_return);
	status = uw_fan_control_start();
	if (status)
		return status;

	if (uw_feats->uniwill_profile_v1) {
		// Set manual-mode fan-curve in 0x0743 - 0x0747
		// Some kind of default fan-curve is stored in 0x0786 - 0x078a: Using it to initialize manual-mode fan-curve
		for (i = 0; i < 5; ++i) {
			status = uniwill_read_ec_ram(0x0786 + i, &data);
			if (status)
				return uniwill_keyboard_abort_probe(status, false);
			status = uniwill_write_ec_ram(0x0743 + i, data);
			if (status)
				return uniwill_keyboard_abort_probe(status, false);
		}
	}

	// Make sure custom TDP/custom fan curve mode is set. Using the
	// custom profile mode flag to ID this set of devices.
	status = uniwill_set_custom_profile_mode(true);
	if (status)
		TUXEDO_ERROR("Could not initialize custom profile mode: %d\n", status);

	// Enable manual mode
	status = uniwill_write_ec_ram(0x0741, 0x01);
	if (status)
		return uniwill_keyboard_abort_probe(status, false);

	// Zero second fan temp for detection
	status = uniwill_write_ec_ram(0x044f, 0x00);
	if (status)
		return uniwill_keyboard_abort_probe(status, true);

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 9, 0)
	TUXEDO_ERROR("Warning: Kernel version less that 5.9, keyboard backlight might not be properly recognized.");
#endif
	status = uniwill_read_ec_ram(UW_EC_REG_KBD_BL_STATUS, &data);
	if (status)
		TUXEDO_ERROR("Could not read initial keyboard backlight state: %d\n", status);
	else
		uniwill_kbd_bl_enable_state_on_start = !((data >> 1) & 0x01);
	uniwill_leds_init(dev);
	status = uniwill_write_kbd_bl_enable(1);
	if (status)
		TUXEDO_ERROR("Could not enable keyboard backlight: %d\n", status);

	status = uw_lightbar_init(dev);
	uw_lightbar_loaded = (status >= 0);

	uw_charging_priority_init(dev);
	uw_charging_profile_init(dev);
	uw_ac_auto_boot_init(dev);
	uw_usb_powershare_init(dev);
	uw_mini_led_local_dimming_init(dev);
	uw_show_hidden_bios_options();
	uw_battery_init();

	// Ignore return value, it just means there is already a filter active
	// which is fine, because it is probably just the upstream patch of this
	// filter.
	/* Start a fresh sequence before the callback can be published. */
	uniwill_touchp_toggle_seq_pos = 0;
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 14, 0)
	status = i8042_install_filter(uniwill_i8042_filter);
#else
	status = i8042_install_filter(uniwill_i8042_filter, NULL);
#endif
	uniwill_i8042_filter_installed = status == 0;
	if (status)
		pr_info("Could not install i8042 filter.\n");

	/* Only a completed probe may accept cable-change restoration. */
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	uniwill_pm_ready = true;
	mutex_unlock(&uniwill_fan_state_lock);
	mutex_unlock(&uniwill_fan_command_lock);

	return 0;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 11, 0)
static int uniwill_keyboard_remove(struct platform_device *dev)
#else
static void uniwill_keyboard_remove(struct platform_device *dev)
#endif
{
	int status;

	uniwill_keyboard_prepare_remove();

	/* Drain fan activity before any device resources or manual mode go away.
	 * Keep command locked until teardown ends; a later probe starts a new
	 * lifecycle explicitly instead of accepting a stale exported request. */
	mutex_lock(&uniwill_fan_command_lock);
	mutex_lock(&uniwill_fan_state_lock);
	uniwill_fan_removed = true;
	uw_fan_quiesce_locked();
	/* AP-exists (0x0741) is not proof that firmware disables RAM tables.
	 * Release only a table this lifecycle owns, while transport/resources
	 * are still available. Universal AUTO preserves the FULL-mode byte. */
	if (uniwill_device_features.uniwill_has_universal_ec_fan_control &&
	    universal_fan_manual_active) {
		status = (int)uw_set_fan_auto_locked();
		if (status)
			TUXEDO_ERROR("Could not restore automatic fan control during removal: %d\n", status);
	}
	/* Teardown cannot replay saved PM targets, even when AUTO failed. Keep
	 * uncertain hardware ownership for diagnostics; reprobe resets it. */
	direct_fan_control_suspend = false;
	fans_initialized = false;
	mutex_unlock(&uniwill_fan_state_lock);

	uw_charging_uninit(dev);

	uw_battery_uninit();

	uniwill_leds_remove(dev);

	// Restore previous backlight enable state
	if (uniwill_kbd_bl_enable_state_on_start != 0xff) {
		status = uniwill_write_kbd_bl_enable(uniwill_kbd_bl_enable_state_on_start);
		if (status)
			TUXEDO_ERROR("Could not restore keyboard backlight state: %d\n", status);
	}

	if (uw_lightbar_loaded)
		uw_lightbar_remove(dev);

	// Disable manual mode
	status = uniwill_write_ec_ram(0x0741, 0x00);
	if (status)
		TUXEDO_ERROR("Could not disable manual fan mode: %d\n", status);

	mutex_unlock(&uniwill_fan_command_lock);

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 11, 0)
	return 0;
#endif
}

static int uw_restore_fan_state_locked(void)
{
	int result, status, recovery_status;
	bool universal = uniwill_device_features.uniwill_has_universal_ec_fan_control;

	if (!direct_fan_control_suspend || (!universal && legacy_fan_mode_override_blocked))
		return 0;

	if (universal) {
		u8 mode;
		result = uniwill_read_ec_ram(0x0751, &mode);
		if (result)
			goto restore_failed;
		/* FULL can supersede a failed resume through either mode API. */
		if (mode & 0x40) {
			/* FULL overrides the target, but clearing FULL later must not
			 * revive an unowned RAM table. AUTO preserves 0x0751. */
			return (int)uw_set_fan_auto_locked();
		}
	}

	/* The first legacy request synchronously writes both fans. Restore both
	 * desired targets first so it cannot write a zero left by AUTO. */
	direct_fan_control_current_value_fan0 = direct_fan_control_current_value_fan0_suspend_save;
	direct_fan_control_current_value_fan1 = direct_fan_control_current_value_fan1_suspend_save;
	result = (int)uw_set_fan_locked(0, direct_fan_control_current_value_fan0_suspend_save);
	/* Never hide a failed first restore behind an implicit retry while
	 * applying the second fan in this same callback. */
	status = result ? 0 : (int)uw_set_fan_locked(1, direct_fan_control_current_value_fan1_suspend_save);
	if (status && !result)
		result = status;
	if (!result)
		direct_fan_control_suspend = false;
restore_failed:
	if (result && universal && result != -EBUSY) {
		/* Do not leave a partially restored manual table active. Desired
		 * targets survive AUTO so a later callback/request can retry. */
		recovery_status = (int)uw_set_fan_auto_locked();
		direct_fan_control_suspend = true;
		if (recovery_status)
			pr_err("Could not restore automatic fan control after failed PM restore: %d\n", recovery_status);
	}

	return result;
}

static int uniwill_keyboard_suspend(struct platform_device *dev, pm_message_t state)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	u8 data;
	int status, restore_status;
	bool profile_was_enabled = false;

	status = uw_fan_lock(true);
	if (status)
		return status;
	if (!uniwill_pm_ready) {
		uw_fan_unlock();
		return -ENODEV;
	}
	if (uniwill_pm_suspended) {
		uw_fan_unlock();
		return 0;
	}
	if (uw_feats->uniwill_has_universal_ec_fan_control &&
	    (universal_fan_manual_active || direct_fan_control_suspend)) {
		status = uniwill_read_ec_ram(0x0751, &data);
		if (status)
			goto failed;
		/* An explicit FULL override supersedes pending manual restoration.
		 * Observe the actual mode, including raw mode API changes. */
		if (data & 0x40) {
			status = (int)uw_set_fan_auto_locked();
			if (status)
				goto failed;
		}
	}
	if ((direct_fan_control_started || universal_fan_manual_active || direct_fan_control_suspend) &&
	    (uw_feats->uniwill_has_universal_ec_fan_control || !legacy_fan_mode_override_blocked)) {
		if (!direct_fan_control_suspend) {
			direct_fan_control_current_value_fan0_suspend_save = direct_fan_control_current_value_fan0;
			direct_fan_control_current_value_fan1_suspend_save = direct_fan_control_current_value_fan1;
		}
		direct_fan_control_suspend = true;
		status = (int)uw_set_fan_auto_locked();
		/* An explicit auto request cancels restoration; suspend must keep it. */
		direct_fan_control_suspend = true;
		if (status)
			goto failed;
	}

	if (uw_feats->uniwill_custom_profile_mode_needed) {
		bool was_enabled;
		// Unset "customer mode light" before suspend. Otherwise at
		// least one device is known to immediately wake up.
		status = uniwill_read_ec_ram(0x0727, &data);
		if (status)
			goto failed;
		was_enabled = !!(data & (1 << 6));
		data &= ~(1 << 6);
		/* A failed transport write may still have reached the EC. */
		profile_was_enabled = was_enabled;
		status = uniwill_write_ec_ram(0x0727, data);
		if (status)
			goto failed;
	}
	status = uniwill_write_kbd_bl_enable(0);
	if (status)
		goto failed;
	uniwill_pm_suspended = true;
	uw_fan_unlock();
	return 0;

failed:
	/* A failed suspend is not guaranteed to receive a resume callback. */
	if (profile_was_enabled) {
		restore_status = uniwill_set_custom_profile_mode(false);
		if (restore_status)
			pr_err("Could not restore custom profile mode after failed suspend: %d\n", restore_status);
	}
	restore_status = uw_restore_fan_state_locked();
	if (restore_status)
		pr_err("Could not restore direct fan control after failed suspend: %d\n", restore_status);
	uw_fan_unlock();
	return status;
}

static int uniwill_keyboard_resume(struct platform_device *dev)
{
	struct uniwill_device_features_t *uw_feats = &uniwill_device_features;
	u8 data;
	int result, status;
	bool restore_fans;

	result = uw_fan_lock(false);
	if (result)
		return result;
	if (!uniwill_pm_ready) {
		uw_fan_unlock();
		return -ENODEV;
	}
	/* Keep queued fan work out until this complete callback releases state. */
	uniwill_pm_suspended = true;
	/* Firmware may lose RAM tables while asleep, even when live registers
	 * happen to survive on another model. Never trust a pre-sleep cache. */
	if (uw_feats->uniwill_has_universal_ec_fan_control) {
		/* Repeated resume callbacks must not invalidate a live manual table
		 * without also restoring the other fan's target. */
		if (universal_fan_manual_active && !direct_fan_control_suspend) {
			direct_fan_control_current_value_fan0_suspend_save = direct_fan_control_current_value_fan0;
			direct_fan_control_current_value_fan1_suspend_save = direct_fan_control_current_value_fan1;
			direct_fan_control_suspend = true;
		}
		fans_initialized = false;
	}
	restore_fans = direct_fan_control_suspend;
	if (direct_fan_control_restart_needed)
		uw_fan_quiesce_locked();
	result = uw_restore_fan_state_locked();
	/* FULL may have successfully cancelled the previous manual intent.
	 * A later unrelated resume error must not resurrect that old target. */
	if (uw_feats->uniwill_has_universal_ec_fan_control &&
	    !universal_fan_manual_active && !direct_fan_control_suspend)
		restore_fans = false;

	if (uw_feats->uniwill_custom_profile_mode_needed) {
		// Re-set "customer mode light" on resume
		status = uniwill_read_ec_ram(0x0727, &data);
		if (!status) {
			data |= (1 << 6);
			status = uniwill_write_ec_ram(0x0727, data);
		}
		if (status && !result)
			result = status;
	}
	uniwill_leds_restore_state_extern();
	status = uniwill_write_kbd_bl_enable(1);
	if (status && !result)
		result = status;
	// Restore charging settings on resume
	uw_charging_priority_write_state();
	uw_charging_profile_write_state();
	if (result) {
		/* Later EC failures must not consume saved manual targets. A failed
		 * resume need not be retried by PM, so ordinary commands remain a
		 * recovery path once this callback returns. */
		if (restore_fans) {
			direct_fan_control_suspend = true;
			direct_fan_control_restart_needed = direct_fan_control_started;
		}
		uw_fan_quiesce_locked();
	}
	uniwill_pm_suspended = false;
	uw_fan_unlock();
	return result;
}

static struct platform_driver platform_driver_uniwill = {
	.remove = uniwill_keyboard_remove,
	.suspend = uniwill_keyboard_suspend,
	.resume = uniwill_keyboard_resume,
	.driver =
		{
			.name = DRIVER_NAME,
			.owner = THIS_MODULE,
		},
};

struct tuxedo_keyboard_driver uniwill_keyboard_driver = {
	.platform_driver = &platform_driver_uniwill,
	.probe = uniwill_keyboard_probe,
	.key_map = uniwill_wmi_keymap,
	.fn_lock_available = uniwill_fn_lock_available,
	.fn_lock_show = uniwill_fn_lock_show,
	.fn_lock_store = uniwill_fn_lock_store,
	.prepare_remove = uniwill_keyboard_prepare_remove,
};

#endif // UNIWILL_KEYBOARD_H
