// SPDX-License-Identifier: GPL-2.0+
/*!
 * Copyright (c) 2019-2023 TUXEDO Computers GmbH <tux@tuxedocomputers.com>
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

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/init.h>
#include <linux/device.h>
#include <linux/ioctl.h>
#include <linux/fs.h>
#include <linux/mutex.h>
#include <linux/cdev.h>
#include <linux/uaccess.h>
#include <linux/delay.h>
#include <linux/version.h>
#include <linux/dmi.h>
#include <linux/err.h>
#include <linux/fs.h>
#include <linux/usb.h>
#include "../clevo_interfaces.h"
#include "../uniwill_interfaces.h"
#include "tuxedo_io_ioctl.h"

MODULE_DESCRIPTION("Hardware interface for TUXEDO laptops");
MODULE_AUTHOR("TUXEDO Computers GmbH <tux@tuxedocomputers.com>");
MODULE_VERSION("0.3.9");
MODULE_LICENSE("GPL");

MODULE_ALIAS_CLEVO_INTERFACES();
MODULE_ALIAS("wmi:" CLEVO_WMI_METHOD_GUID);
MODULE_ALIAS("wmi:" UNIWILL_WMI_MGMT_GUID_BA);
MODULE_ALIAS("wmi:" UNIWILL_WMI_MGMT_GUID_BB);
MODULE_ALIAS("wmi:" UNIWILL_WMI_MGMT_GUID_BC);

#define NB01_FAN_SPEED_MAX 0xff
#define FAN_ON_MIN_SPEED_PERCENT 25

// Initialized in module init, global for ioctl interface
static u32 id_check_clevo;
static u32 id_check_uniwill;

static struct uniwill_device_features_t *uw_feats;

static int uw_get_tdp_min(u8 tdp_index);
static int uw_get_tdp_max(u8 tdp_index);
static int uw_get_tdp(u8 tdp_index);
static int uw_set_tdp(u8 tdp_index, int tdp_value);
static int uw_apply_performance_profile_v1(enum uw_perf_profiles_v1 profile);
static int uw_set_performance_profile_v1(enum uw_perf_profiles_v1 profile);

/**
 * strstr version of dmi_match
 */
static bool __attribute__ ((unused)) dmi_string_in(enum dmi_field f, const char *str)
{
	const char *info = dmi_get_system_info(f);

	if (info == NULL || str == NULL)
		return info == str;

	return strstr(info, str) != NULL;
}

static u32 clevo_identify(void)
{
	return clevo_get_active_interface_id(NULL) == 0 ? 1 : 0;
}

/*
 * TDP boundary definitions per device
 */
static int tdp_min_ph4tux[] = { 0x05, 0x05, 0x00 };
static int tdp_max_ph4tux[] = { 0x26, 0x26, 0x00 };

static int tdp_min_ph4trx[] = { 0x05, 0x05, 0x00 };
static int tdp_max_ph4trx[] = { 0x32, 0x32, 0x00 };

static int tdp_min_ph4tqx[] = { 0x05, 0x05, 0x00 };
static int tdp_max_ph4tqx[] = { 0x32, 0x32, 0x00 };

static int tdp_min_phxaxx_mk1[] = { 0x05, 0x05, 0x00 };
static int tdp_max_phxaxx_mk1[] = { 0x32, 0x3c, 0x00 };

static int tdp_min_phxaxx_mk2[] = { 0x05, 0x05, 0x00 };
static int tdp_max_phxaxx_mk2[] = { 0x37, 0x64, 0x00 };

static int tdp_min_phxpxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_phxpxx[] = { 0x2d, 0x3c, 0x6e };

static int tdp_min_pfxluxg[] = { 0x05, 0x05, 0x05 };
static int tdp_max_pfxluxg[] = { 0x23, 0x23, 0x28 };

static int tdp_min_gmxngxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxngxx[] = { 0x50, 0x50, 0x5f };

static int tdp_min_gmxmgxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxmgxx[] = { 0x78, 0x78, 0xc8 };

static int tdp_min_gmxtgxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxtgxx[] = { 0x78, 0x78, 0xc8 };

static int tdp_min_gmxzgxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxzgxx[] = { 0x50, 0x50, 0x5f };

static int tdp_min_gmxagxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxagxx[] = { 0x78, 0x78, 0xd7 };

static int tdp_min_gmxrgxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxrgxx[] = { 0x64, 0x64, 0x6e };

static int tdp_min_gmxpxxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxpxxx[] = { 0x82, 0x82, 0xc8 };

static int tdp_min_gmxxgxx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxxgxx[] = { 0x50, 0x50, 0x64 };

static int tdp_min_gmxixxb_mb1[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxixxb_mb1[] = { 0xcd, 0xcd, 0x190 };

static int tdp_min_gmxixxb_mb2[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxixxb_mb2[] = { 0xa0, 0xa0, 0xfa };

static int tdp_min_gmxixxn[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxixxn[] = { 0xa0, 0xa0, 0xfa };

static int tdp_min_gmxixxa[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxixxa[] = { 0x8c, 0x8c, 0xc8 };

static int tdp_min_gmxhgxa[] = { 0x05, 0x05, 0x05 };
static int tdp_max_gmxhgxa[] = { 0x5a, 0x5a, 0x64 };

static int tdp_min_x6ar5xx[] = { 0x05, 0x05, 0x05 };
static int tdp_max_x6ar5xx[] = { 0xd2, 0xd2, 0x1a4 };

// Actual min TDP from NB02 CC is 10 W, but 25 W was suggested after testing.
static int tdp_min_x6fr5xx[] = { 0x19, 0x19, 0x19 };
static int tdp_max_x6fr5xx[] = { 0xa2, 0xa2, 0xc3 };

static int tdp_min_xxxx45xs[] = { 0x0a, 0x0a, 0x0a };
static int tdp_max_xxxx45xs[] = { 0x64, 0x64, 0x69 };

static int tdp_min_x6ar55xu[] = { 0x0a, 0x0a, 0x0a };
static int tdp_max_x6ar55xu[] = { 0x91, 0x9b, 0x122 };

static int tdp_min_x5ar45xs[] = { 0x0a, 0x0a, 0x0a };
static int tdp_max_x5ar45xs[] = { 0x5a, 0x5a, 0xe6 };

static int tdp_min_x6xx45xu[] = { 0x0a, 0x0a, 0x0a };
static int tdp_max_x6xx45xu[] = { 0x64, 0x64, 0x69 };

static int tdp_min_xxaf5xxx[] = { 0x0a, 0x0a, 0x0a };
static int tdp_max_xxaf5xxx[] = { 0xd2, 0xd2, 0x1a4 };

/* Windows Control Center 5.17.49.19 profile values for this exact model:
 * Office/Gaming/Turbo use PL1/PL2/PL4 35/35/215, 80/80/215 and 95/95/215.
 * The lower bound remains 35 W for PL1/PL2 and 100 W for PL4 so the EC
 * defaults and an explicit reset remain representable. These are package
 * profile values, not a completed high-power thermal qualification; PL4 was
 * not load-tested at 215 W here.
 */
static int tdp_min_gm6bg0q[] = { 0x23, 0x23, 0x64 };
static int tdp_max_gm6bg0q[] = { 0x5f, 0x5f, 0xd7 };

static int *tdp_min_defs = NULL;
static int *tdp_max_defs = NULL;

static void uw_id_tdp(u8 model)
{
	if (model == UW_MODEL_PH4TUX) {
		tdp_min_defs = tdp_min_ph4tux;
		tdp_max_defs = tdp_max_ph4tux;
	} else if (model == UW_MODEL_PH4TRX) {
		tdp_min_defs = tdp_min_ph4trx;
		tdp_max_defs = tdp_max_ph4trx;
	} else if (model == UW_MODEL_PH4TQF) {
		tdp_min_defs = tdp_min_ph4tqx;
		tdp_max_defs = tdp_max_ph4tqx;
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 18, 0)
	} else if (dmi_match(DMI_PRODUCT_SKU, "IBP1XI07MK1")) {
		tdp_min_defs = tdp_min_phxaxx_mk1;
		tdp_max_defs = tdp_max_phxaxx_mk1;
	} else if (dmi_match(DMI_PRODUCT_SKU, "IBP1XI07MK2")) {
		tdp_min_defs = tdp_min_phxaxx_mk2;
		tdp_max_defs = tdp_max_phxaxx_mk2;
	} else if (dmi_match(DMI_PRODUCT_SKU, "IBP1XI08MK1") ||
		   dmi_match(DMI_PRODUCT_SKU, "IBP1XI08MK2") ||
		   dmi_match(DMI_PRODUCT_SKU, "IBP14I08MK2") ||
		   dmi_match(DMI_PRODUCT_SKU, "IBP16I08MK2") ||
		   dmi_match(DMI_PRODUCT_SKU, "OMNIA08IMK2")) {
		tdp_min_defs = tdp_min_phxpxx;
		tdp_max_defs = tdp_max_phxpxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "PULSE1502")) {
		tdp_min_defs = tdp_min_pfxluxg;
		tdp_max_defs = tdp_max_pfxluxg;
	} else if (dmi_match(DMI_PRODUCT_SKU, "POLARIS1XA02")) {
		tdp_min_defs = tdp_min_gmxngxx;
		tdp_max_defs = tdp_max_gmxngxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "POLARIS1XI02")) {
		tdp_min_defs = tdp_min_gmxmgxx;
		tdp_max_defs = tdp_max_gmxmgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "POLARIS1XI03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI03")) {
		tdp_min_defs = tdp_min_gmxtgxx;
		tdp_max_defs = tdp_max_gmxtgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "POLARIS1XA03")
		|| dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XA03")) {
		tdp_min_defs = tdp_min_gmxzgxx;
		tdp_max_defs = tdp_max_gmxzgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI04")) {
		tdp_min_defs = tdp_min_gmxagxx;
		tdp_max_defs = tdp_max_gmxagxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STEPOL1XA04")) {
		tdp_min_defs = tdp_min_gmxrgxx;
		tdp_max_defs = tdp_max_gmxrgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XI05")) {
		tdp_min_defs = tdp_min_gmxpxxx;
		tdp_max_defs = tdp_max_gmxpxxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "POLARIS1XA05")) {
		tdp_min_defs = tdp_min_gmxxgxx;
		tdp_max_defs = tdp_max_gmxxgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS1XA05")) {
		tdp_min_defs = tdp_min_gmxxgxx;
		tdp_max_defs = tdp_max_gmxxgxx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS16I06") &&
		   dmi_match(DMI_BOARD_NAME, "GM6IXxB_MB1")) {
		tdp_min_defs = tdp_min_gmxixxb_mb1;
		tdp_max_defs = tdp_max_gmxixxb_mb1;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS16I06") &&
		   dmi_match(DMI_BOARD_NAME, "GM6IXxB_MB2")) {
		tdp_min_defs = tdp_min_gmxixxb_mb2;
		tdp_max_defs = tdp_max_gmxixxb_mb2;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS17I06")) {
		tdp_min_defs = tdp_min_gmxixxn;
		tdp_max_defs = tdp_max_gmxixxn;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLSL15I06")) {
		tdp_min_defs = tdp_min_gmxixxa;
		tdp_max_defs = tdp_max_gmxixxa;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLSL15A06")) {
		tdp_min_defs = tdp_min_gmxhgxa;
		tdp_max_defs = tdp_max_gmxhgxa;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS16I07")) {
		tdp_min_defs = tdp_min_x6ar5xx;
		tdp_max_defs = tdp_max_x6ar5xx;
	} else if (dmi_match(DMI_PRODUCT_SKU, "STELLARIS16A07")) {
		tdp_min_defs = tdp_min_x6fr5xx;
		tdp_max_defs = tdp_max_x6fr5xx;
	} else if (dmi_match(DMI_BOARD_NAME, "X5KK45xS_X5SP45xS")) {
		tdp_min_defs = tdp_min_xxxx45xs;
		tdp_max_defs = tdp_max_xxxx45xs;
	} else if (dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		   dmi_match(DMI_BOARD_NAME, "JIAOLONG Series-X6xR55xK")) {
		/* Reuse the tested community mapping, not a marketing-name alias.
		 * These are validation bounds, never automatically applied targets. */
		tdp_min_defs = tdp_min_x6fr5xx;
		tdp_max_defs = tdp_max_x6fr5xx;
	} else if (dmi_match(DMI_BOARD_NAME, "X6AR55xU")) {
		tdp_min_defs = tdp_min_x6ar55xu;
		tdp_max_defs = tdp_max_x6ar55xu;
	} else if (dmi_match(DMI_BOARD_NAME, "X5AR45xS")) {
		tdp_min_defs = tdp_min_x5ar45xs;
		tdp_max_defs = tdp_max_x5ar45xs;
	} else if (dmi_match(DMI_BOARD_NAME, "X6KK45xU_X6SP45xU")) {
		tdp_min_defs = tdp_min_x6xx45xu;
		tdp_max_defs = tdp_max_x6xx45xu;
	} else if (dmi_match(DMI_BOARD_NAME, "XxAF5xxx") ||
		   dmi_match(DMI_BOARD_NAME, "XxAF5xxx_mLED")) {
		tdp_min_defs = tdp_min_xxaf5xxx;
		tdp_max_defs = tdp_max_xxaf5xxx;
	} else if (dmi_match(DMI_SYS_VENDOR, "MECHREVO") &&
		   dmi_match(DMI_BOARD_NAME, "GM6BG0Q") &&
		   dmi_match(DMI_PRODUCT_NAME, "Jiaolong16K Series GM6BG0Q") &&
		   dmi_match(DMI_BIOS_VERSION, "N.1.19MRO15")) {
		/* The same exact identity gates the boot/USB switches. Writing
		 * PL1=35 through ECRR capped package power to 35 W on hardware;
		 * other bounds are the OEM profile/registry points only. */
		tdp_min_defs = tdp_min_gm6bg0q;
		tdp_max_defs = tdp_max_gm6bg0q;
#endif
	} else {
		tdp_min_defs = NULL;
		tdp_max_defs = NULL;
	}
}

static DEFINE_MUTEX(uniwill_identify_lock);

/* Called with uniwill_identify_lock held. */
static u32 uw_identify_locked(void)
{
	struct uniwill_device_features_t *features;
	u32 result;

	result = uniwill_get_active_interface_id(NULL) == 0 ? 1 : 0;
	if (result) {
		features = uniwill_get_device_features();
		if (!features || !uniwill_device_features_ready()) {
			result = 0;
		} else {
			/* Initialize the TDP table before publishing uw_feats so a
			 * concurrent ready check cannot observe the model without
			 * its bounds. */
			uw_id_tdp(features->model);
			uw_feats = features;
		}
	}
	return result;
}

static u32 uniwill_identify(void)
{
	u32 result;

	mutex_lock(&uniwill_identify_lock);
	result = uw_identify_locked();
	mutex_unlock(&uniwill_identify_lock);
	return result;
}

/* tuxedo_io may initialize before the Uniwill interface provider registers
 * (reproduced on Jiaolong16K GM6BG0Q: R_UW_MODEL_ID failed with ENODEV until
 * R_HWCHECK_UW). Retry on first use instead of caching a load-order failure.
 * The lock serializes both the retry and reads of the published pointer, so a
 * caller cannot observe uw_feats before uw_id_tdp() finished; concurrent
 * first users still identify only once.
 */
static void uw_ensure_identified(void)
{
	mutex_lock(&uniwill_identify_lock);
	if (!uw_feats)
		uw_identify_locked();
	mutex_unlock(&uniwill_identify_lock);
}

/* Feature-gated commands retry identification on first use. Argument
 * validation and user copies still happen before this where the handler can
 * decide without the feature set, so malformed requests do not probe. */
static bool uw_features_ready(void)
{
	uw_ensure_identified();
	return uw_feats != NULL;
}

/*static int fop_open(struct inode *inode, struct file *file)
{
	return 0;
}

static int fop_release(struct inode *inode, struct file *file)
{
	return 0;
}*/

static long clevo_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	u32 result = 0;
	int status;
	u32 copy_result = 0;
	u32 argument = (u32) arg;
	int i;

	u32 clevo_arg;

	const char str_no_if[] = "";
	char *str_clevo_if;

	switch (cmd) {
		case R_CL_HW_IF_STR:
			if (clevo_get_active_interface_id(&str_clevo_if) == 0) {
				copy_result = copy_to_user((char *) arg, str_clevo_if, strlen(str_clevo_if) + 1);
			} else {
				copy_result = copy_to_user((char *) arg, str_no_if, strlen(str_no_if) + 1);
			}
			break;
		case R_CL_FANINFO1:
			status = clevo_evaluate_method(CLEVO_CMD_GET_FANINFO1, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		case R_CL_FANINFO2:
			status = clevo_evaluate_method(CLEVO_CMD_GET_FANINFO2, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		case R_CL_FANINFO3:
			status = clevo_evaluate_method(CLEVO_CMD_GET_FANINFO3, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		/*case R_CL_FANINFO4:
			status = clevo_evaluate_method(CLEVO_CMD_GET_FANINFO4, 0);
			copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;*/
		case R_CL_WEBCAM_SW:
			if (dmi_match(DMI_PRODUCT_SKU, "AURA14GEN3") ||
			    dmi_match(DMI_PRODUCT_SKU, "AURA15GEN3") ||
			    dmi_match(DMI_PRODUCT_SKU, "AURA14GEN4 / AURA15GEN4"))
				return -ENODEV;
			status = clevo_evaluate_method(CLEVO_CMD_GET_WEBCAM_SW, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		case R_CL_FLIGHTMODE_SW:
			status = clevo_evaluate_method(CLEVO_CMD_GET_FLIGHTMODE_SW, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		case R_CL_TOUCHPAD_SW:
			status = clevo_evaluate_method(CLEVO_CMD_GET_TOUCHPAD_SW, 0, &result);
			if (status)
				return status;
			copy_result = copy_to_user((int32_t *) arg, &result, sizeof(result));
			break;
		case W_CL_FANSPEED:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;

			// Don't allow vallues between fan-off and minimum fan-on-speed
			u8 fanspeeds[3] = { argument & 0xff, argument >> 8 & 0xff, argument >> 16 & 0xff };
			for (i = 0; i < 3; ++i) {
				if (fanspeeds[i] < FAN_ON_MIN_SPEED_PERCENT * NB01_FAN_SPEED_MAX / 2 / 100)
					fanspeeds[i] = 0;
				else if (fanspeeds[i] < FAN_ON_MIN_SPEED_PERCENT * NB01_FAN_SPEED_MAX / 100)
					fanspeeds[i] = FAN_ON_MIN_SPEED_PERCENT * NB01_FAN_SPEED_MAX / 100;
			}
			argument = fanspeeds[0];
			argument |= fanspeeds[1] << 8;
			argument |= fanspeeds[2] << 16;

			status = clevo_evaluate_method(CLEVO_CMD_SET_FANSPEED_VALUE, argument, &result);
			if (status)
				return status;
			// Note: Delay needed to let hardware catch up with the written value.
			// No known ready flag. If the value is read too soon, the old value
			// will still be read out.
			// (Theoretically needed for other methods as well.)
			// Can it be lower? 50ms is too low
			msleep(100);
			break;
		case W_CL_FANAUTO:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			status = clevo_evaluate_method(CLEVO_CMD_SET_FANSPEED_AUTO, argument, &result);
			if (status)
				return status;
			break;
		case W_CL_WEBCAM_SW:
			if (dmi_match(DMI_PRODUCT_SKU, "AURA14GEN3") ||
			    dmi_match(DMI_PRODUCT_SKU, "AURA15GEN3"))
				return -ENODEV;
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			status = clevo_evaluate_method(CLEVO_CMD_GET_WEBCAM_SW, 0, &result);
			if (status)
				return status;
			// Only set status if it isn't already the right value
			// (workaround for old and/or buggy WMI interfaces that toggle on write)
			if ((argument & 0x01) != (result & 0x01)) {
				status = clevo_evaluate_method(CLEVO_CMD_SET_WEBCAM_SW, argument, &result);
				if (status)
					return status;
			}
			break;
		case W_CL_FLIGHTMODE_SW:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			status = clevo_evaluate_method(CLEVO_CMD_SET_FLIGHTMODE_SW, argument, &result);
			if (status)
				return status;
			break;
		case W_CL_TOUCHPAD_SW:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			status = clevo_evaluate_method(CLEVO_CMD_SET_TOUCHPAD_SW, argument, &result);
			if (status)
				return status;
			break;
		case W_CL_PERF_PROFILE:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			clevo_arg = (CLEVO_CMD_OPT_SUB_SET_PERF_PROF << 0x18) | (argument & 0xff);
			status = clevo_evaluate_method(CLEVO_CMD_OPT, clevo_arg, &result);
			if (status)
				return status;
			break;
		default:
			return -ENOTTY;
	}

	return copy_result ? -EFAULT : 0;
}

static int uw_get_tdp_min(u8 tdp_index)
{
	if (tdp_index > 2)
		return -EINVAL;

	if (tdp_min_defs == NULL)
		return -ENODEV;

	if (tdp_min_defs[tdp_index] <= 0) {
		return -ENODEV;
	}

	return tdp_min_defs[tdp_index];
}

static int uw_get_tdp_max(u8 tdp_index)
{
	if (tdp_index > 2)
		return -EINVAL;

	if (tdp_max_defs == NULL)
		return -ENODEV;

	if (tdp_max_defs[tdp_index] <= 0) {
		return -ENODEV;
	}

	return tdp_max_defs[tdp_index];
}

static int uw_get_tdp(u8 tdp_index)
{
	u8 tdp_data;
	int tdp_value;
	u16 tdp_base_addr = 0x0783;
	u16 tdp_current_addr = tdp_base_addr + tdp_index;
	int status;

	// Use min tdp to detect support for chosen tdp parameter
	int min_tdp_status = uw_get_tdp_min(tdp_index);
	if (min_tdp_status < 0)
		return min_tdp_status;
	if (!uw_feats)
		return -ENODEV;

	status = uniwill_read_ec_ram(tdp_current_addr, &tdp_data);
	if (status < 0)
		return status;

	if (tdp_index == 2 && uw_feats->uniwill_has_double_pl4)
		tdp_value = (int)tdp_data * 2;
	else
		tdp_value = tdp_data;

	return tdp_value;
}

static int uw_set_tdp(u8 tdp_index, int tdp_value)
{
	int tdp_min, tdp_max;
	u8 tdp_data;

	// Use min tdp to detect support for chosen tdp parameter
	tdp_min = uw_get_tdp_min(tdp_index);
	if (tdp_min < 0)
		return tdp_min;
	tdp_max = uw_get_tdp_max(tdp_index);
	if (tdp_max < 0)
		return tdp_max;
	if (tdp_value < tdp_min || tdp_value > tdp_max)
		return -EINVAL;
	if (!uw_feats)
		return -ENODEV;

	if (tdp_index == 2 && uw_feats->uniwill_has_double_pl4)
		tdp_data = tdp_value / 2;
	else
		tdp_data = tdp_value;

	return uw_write_tdp(tdp_index, tdp_data);
}

static u32 uw_get_performance_profile_count(void)
{
	if (!uw_feats)
		return 0;
	if (uw_feats->uniwill_profile_v1_two_profs)
		return 2;
	if (uw_feats->uniwill_profile_v1_three_profs ||
	    uw_feats->uniwill_profile_v1_three_profs_leds_only)
		return 3;
	return 0;
}

/* Apply the established public-profile mode bits. Custom TDP uses the
 * provider's complete mode-plus-power transaction instead. */
static int uw_apply_performance_profile_v1(enum uw_perf_profiles_v1 profile)
{
	u8 profile_bits;

	switch (profile) {
	case PROFILE_POWERSAVE:
		profile_bits = 0xa0;
		break;
	case PROFILE_ENTHUSIAST:
		profile_bits = 0x00;
		break;
	case PROFILE_OVERBOOST:
		profile_bits = 0x10;
		break;
	default:
		return -EINVAL;
	}

	return uw_update_mode(0xb0, profile_bits);
}

static int uw_set_performance_profile_v1(enum uw_perf_profiles_v1 profile)
{
	u32 count;

	if (profile < PROFILE_POWERSAVE || profile > PROFILE_OVERBOOST)
		return -EINVAL;

	count = uw_get_performance_profile_count();
	if (!count)
		return -ENODEV;
	if ((u32)profile > count)
		return -EINVAL;

	return uw_apply_performance_profile_v1(profile);
}

/* Unsupported TDP queries must return an errno, not an unsigned power value. */
static long uw_copy_tdp_value(unsigned long arg, int value)
{
	u32 user_value;

	if (value < 0)
		return value;

	user_value = value;
	return copy_to_user((void __user *) arg, &user_value, sizeof(user_value)) ? -EFAULT : 0;
}

static long uniwill_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	u32 result = 0;
	u32 copy_result = 0;
	u32 argument;
	int status;
	u8 byte_data;
	const char str_no_if[] = "";
	char *str_uniwill_if;

#ifdef DEBUG
	union uw_ec_read_return reg_read_return;
	union uw_ec_write_return reg_write_return;
	u32 uw_arg[10];
	u32 uw_result[10];
	int i;
	for (i = 0; i < 10; ++i) {
		uw_result[i] = 0xdeadbeef;
	}
#endif

	switch (cmd) {
		case R_UW_HW_IF_STR:
			if (uniwill_get_active_interface_id(&str_uniwill_if) == 0) {
				copy_result = copy_to_user((char *) arg, str_uniwill_if, strlen(str_uniwill_if) + 1);
			} else {
				copy_result = copy_to_user((char *) arg, str_no_if, strlen(str_no_if) + 1);
			}
			break;
		case R_UW_MODEL_ID:
			if (!uw_features_ready())
				return -ENODEV;
			result = uw_feats->model;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FANSPEED:
			if (!uw_features_ready())
				return -ENODEV;
			status = uniwill_read_ec_ram(0x1804, &byte_data);
			if (status < 0)
				return status;
			if (uw_feats->uniwill_has_universal_ec_fan_control && byte_data == 1)
				byte_data = 0; // 1 is 0 behaviour see: uw_set_fan
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FANSPEED2:
			if (!uw_features_ready())
				return -ENODEV;
			status = uniwill_read_ec_ram(0x1809, &byte_data);
			if (status < 0)
				return status;
			if (uw_feats->uniwill_has_universal_ec_fan_control && byte_data == 1)
				byte_data = 0; // 1 is 0 behaviour see: uw_set_fan
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FAN_TEMP:
			status = uniwill_read_ec_ram(0x043e, &byte_data);
			if (status < 0)
				return status;
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FAN_TEMP2:
			status = uniwill_read_ec_ram(0x044f, &byte_data);
			if (status < 0)
				return status;
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_MODE:
			status = uniwill_read_ec_ram(0x0751, &byte_data);
			if (status < 0)
				return status;
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_MODE_ENABLE:
			status = uniwill_read_ec_ram(0x0741, &byte_data);
			if (status < 0)
				return status;
			result = byte_data;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FANS_OFF_AVAILABLE:
			/*result = uw_feats->uniwill_has_universal_ec_fan_control ? 1 : 0;
			if (result == 1) {
				result = 0;
			}
			else if (result == 0) {
				result = 1;
			}*/
			result = 1;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_FANS_MIN_SPEED:
			/*result = uw_feats->uniwill_has_universal_ec_fan_control? 1 : 0;
			if (result == 1) {
				result = 20;
			}
			else if (result == 0) {
				result = 0;
			}*/
			result = FAN_ON_MIN_SPEED_PERCENT;
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
		case R_UW_TDP0:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp(0));
		case R_UW_TDP1:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp(1));
		case R_UW_TDP2:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp(2));
		case R_UW_TDP0_MIN:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_min(0));
		case R_UW_TDP1_MIN:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_min(1));
		case R_UW_TDP2_MIN:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_min(2));
		case R_UW_TDP0_MAX:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_max(0));
		case R_UW_TDP1_MAX:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_max(1));
		case R_UW_TDP2_MAX:
			if (!uw_features_ready())
				return -ENODEV;
			return uw_copy_tdp_value(arg, uw_get_tdp_max(2));
		case R_UW_PROFS_AVAILABLE:
			if (!uw_features_ready())
				return -ENODEV;
			result = uw_get_performance_profile_count();
			copy_result = copy_to_user((void *) arg, &result, sizeof(result));
			break;
#ifdef DEBUG
		case R_TF_BC:
			copy_result = copy_from_user(&uw_arg, (void *) arg, sizeof(uw_arg));
			if (copy_result)
				return -EFAULT;
			reg_read_return.dword = 0;
			status = uniwill_read_ec_ram((uw_arg[1] << 8) | uw_arg[0], &reg_read_return.bytes.data_low);
			if (status < 0)
				return status;
			copy_result = copy_to_user((void *) arg, &reg_read_return.dword, sizeof(reg_read_return.dword));
			// pr_info("R_TF_BC args [%0#2x, %0#2x, %0#2x, %0#2x]\n", uw_arg[0], uw_arg[1], uw_arg[2], uw_arg[3]);
			/*if (uniwill_ec_direct) {
				result = uw_ec_read_addr_direct(uw_arg[0], uw_arg[1], &reg_read_return);
				copy_result = copy_to_user((void *) arg, &reg_read_return.dword, sizeof(reg_read_return.dword));
			} else {
				result = uw_wmi_ec_evaluate(uw_arg[0], uw_arg[1], uw_arg[2], uw_arg[3], 1, uw_result);
				copy_result = copy_to_user((void *) arg, &uw_result, sizeof(uw_result));
			}*/
			break;
#endif
		case W_UW_FANSPEED:
		case W_UW_FANSPEED2:
			// Get fan speed argument
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			if (argument > 0xff)
				return -EINVAL;
			if (!uw_features_ready())
				return -ENODEV;
			return (int)uw_set_fan(cmd == W_UW_FANSPEED2, argument);
		case W_UW_MODE:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			return uw_set_mode(argument & 0xff);
		case W_UW_MODE_ENABLE:
			// Note: Is for the moment set and cleared on init/exit of module (uniwill mode)
			/*
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			uniwill_write_ec_ram(0x0741, argument & 0x01);
			*/
			break;
		case W_UW_FANAUTO:
			if (!uw_features_ready())
				return -ENODEV;
			return (int)uw_set_fan_auto();
		case W_UW_TDP0:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			if ((int32_t)argument < 0)
				return -EINVAL;
			if (!uw_features_ready())
				return -ENODEV;
			return uw_set_tdp(0, argument);
		case W_UW_TDP1:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			if ((int32_t)argument < 0)
				return -EINVAL;
			if (!uw_features_ready())
				return -ENODEV;
			return uw_set_tdp(1, argument);
		case W_UW_TDP2:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			if ((int32_t)argument < 0)
				return -EINVAL;
			if (!uw_features_ready())
				return -ENODEV;
			return uw_set_tdp(2, argument);
		case W_UW_PERF_PROF:
			copy_result = copy_from_user(&argument, (int32_t *) arg, sizeof(argument));
			if (copy_result)
				return -EFAULT;
			if (argument < PROFILE_POWERSAVE || argument > PROFILE_OVERBOOST)
				return -EINVAL;
			if (!uw_features_ready())
				return -ENODEV;
			return uw_set_performance_profile_v1(argument);
#ifdef DEBUG
		case W_TF_BC:
			reg_write_return.dword = 0;
			copy_result = copy_from_user(&uw_arg, (void *) arg, sizeof(uw_arg));
			if (copy_result)
				return -EFAULT;
			status = uniwill_write_ec_ram((uw_arg[1] << 8) | uw_arg[0], uw_arg[2]);
			if (status < 0)
				return status;
			copy_result = copy_to_user((void *) arg, &reg_write_return.dword, sizeof(reg_write_return.dword));
			/*if (uniwill_ec_direct) {
				result = uw_ec_write_addr_direct(uw_arg[0], uw_arg[1], uw_arg[2], uw_arg[3], &reg_write_return);
				copy_result = copy_to_user((void *) arg, &reg_write_return.dword, sizeof(reg_write_return.dword));
			} else {
				result = uw_wmi_ec_evaluate(uw_arg[0], uw_arg[1], uw_arg[2], uw_arg[3], 0, uw_result);
				copy_result = copy_to_user((void *) arg, &uw_result, sizeof(uw_result));
				reg_write_return.dword = uw_result[0];
			}*/
			/*pr_info("data_high %0#2x\n", reg_write_return.bytes.data_high);
			pr_info("data_low %0#2x\n", reg_write_return.bytes.data_low);
			pr_info("addr_high %0#2x\n", reg_write_return.bytes.addr_high);
			pr_info("addr_low %0#2x\n", reg_write_return.bytes.addr_low);*/
			break;
#endif
		default:
			return -ENOTTY;
	}

	return copy_result ? -EFAULT : 0;
}

/* Uniwill OEM v5.17.51.34 turns the camera on or off by enabling or disabling
 * the Camera-class device. 0x0727 is already the custom-profile byte, so this
 * path never writes EC RAM. It only changes authorization of a USB device whose
 * name is a bus port, and whose product or interface says it is a camera.
 * usb_authorize_device() is not exported to modules; the sysfs attribute is.
 * Clevo firmware webcam commands stay on the Clevo path.
 */
#define UW_WEBCAM_FOUND		0
#define UW_WEBCAM_ENABLED	1
#define UW_WEBCAM_ENABLE	2

static int uniwill_webcam_contains(const char *haystack, const char *needle)
{
	size_t i, j;

	if (!haystack || !needle || !needle[0])
		return 0;
	for (i = 0; haystack[i]; ++i) {
		for (j = 0; needle[j]; ++j) {
			char left = haystack[i + j];
			char right = needle[j];

			if (!left)
				return 0;
			if (left >= 'A' && left <= 'Z')
				left += 'a' - 'A';
			if (right >= 'A' && right <= 'Z')
				right += 'a' - 'A';
			if (left != right)
				break;
		}
		if (!needle[j])
			return 1;
	}
	return 0;
}

static int uniwill_webcam_name_is_device(const char *name)
{
	size_t i;
	int dash = 0;

	if (!name || !name[0])
		return 0;
	for (i = 0; name[i]; ++i) {
		char c = name[i];

		if (i >= 31)
			return 0;
		if (c == '-') {
			if (i == 0 || dash)
				return 0;
			dash = 1;
			continue;
		}
		if (c == '.') {
			if (!dash || name[i - 1] == '-' || name[i - 1] == '.')
				return 0;
			continue;
		}
		if (c < '0' || c > '9')
			return 0;
	}
	if (!dash || name[i - 1] == '-' || name[i - 1] == '.')
		return 0;
	return 1;
}

static int uniwill_webcam_device_is_camera(struct usb_device *udev)
{
	int i;

	if (!udev || !uniwill_webcam_name_is_device(dev_name(&udev->dev)))
		return 0;
	if (uniwill_webcam_contains(udev->product, "webcam") ||
	    uniwill_webcam_contains(udev->product, "camera"))
		return 1;
	if (!udev->actconfig)
		return 0;
	for (i = 0; i < udev->actconfig->desc.bNumInterfaces; ++i) {
		struct usb_interface *intf = udev->actconfig->interface[i];

		if (intf && intf->cur_altsetting &&
		    intf->cur_altsetting->desc.bInterfaceClass == USB_CLASS_VIDEO)
			return 1;
	}
	return 0;
}

static int uniwill_webcam_write_authorized(struct usb_device *udev, int enable)
{
	char path[64];
	struct file *file;
	loff_t pos = 0;
	char value = enable ? '1' : '0';
	ssize_t written;
	int length;

	if (!uniwill_webcam_name_is_device(dev_name(&udev->dev)))
		return -EINVAL;
	length = scnprintf(path, sizeof(path), "/sys/bus/usb/devices/%s/authorized",
			   dev_name(&udev->dev));
	if (length < 0 || length >= (int)sizeof(path))
		return -ENAMETOOLONG;
	file = filp_open(path, O_WRONLY, 0);
	if (IS_ERR(file))
		return PTR_ERR(file);
	written = kernel_write(file, &value, 1, &pos);
	filp_close(file, NULL);
	if (written < 0)
		return written;
	return written == 1 ? 0 : -EIO;
}

static int uniwill_webcam_visit(struct usb_device *udev, void *data)
{
	int *walk = data;
	int desired, status;

	if (!uniwill_webcam_device_is_camera(udev))
		return 0;
	++walk[UW_WEBCAM_FOUND];
	if (udev->authorized)
		++walk[UW_WEBCAM_ENABLED];
	if (walk[UW_WEBCAM_ENABLE] < 0)
		return 0;
	desired = walk[UW_WEBCAM_ENABLE] & 0x01;
	if (udev->authorized == desired)
		return 0;
	status = uniwill_webcam_write_authorized(udev, desired);
	if (status)
		return status;
	return 0;
}

static long uniwill_webcam_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	int walk[3] = { 0, 0, -1 };
	u32 argument = 0;
	u32 result;
	int status;

	(void)file;
	if (cmd == W_CL_WEBCAM_SW) {
		if (copy_from_user(&argument, (u32 __user *)arg, sizeof(argument)))
			return -EFAULT;
		walk[UW_WEBCAM_ENABLE] = argument & 0x01;
	} else if (cmd != R_CL_WEBCAM_SW) {
		return -ENOTTY;
	}
	status = usb_for_each_dev(walk, uniwill_webcam_visit);
	if (status)
		return status;
	if (!walk[UW_WEBCAM_FOUND])
		return -ENODEV;
	if (cmd == W_CL_WEBCAM_SW)
		return 0;
	result = walk[UW_WEBCAM_ENABLED] ? 1 : 0;
	if (copy_to_user((u32 __user *)arg, &result, sizeof(result)))
		return -EFAULT;
	return 0;
}

static long fop_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	u32 copy_result;

	const char *module_version = THIS_MODULE->version;
	switch (cmd) {
		case R_MOD_VERSION:
			copy_result = copy_to_user((char *) arg, module_version, strlen(module_version) + 1);
			break;
		// Hardware id checks, 1 = positive, 0 = negative
		case R_HWCHECK_CL:
			id_check_clevo = clevo_identify();
			copy_result = copy_to_user((void *) arg, (void *) &id_check_clevo, sizeof(id_check_clevo));
			break;
		case R_HWCHECK_UW:
			id_check_uniwill = uniwill_identify();
			copy_result = copy_to_user((void *) arg, (void *) &id_check_uniwill, sizeof(id_check_uniwill));
			break;
#ifdef DEBUG
		/* These historical Uniwill commands use Clevo ioctl magic values. */
		case R_TF_BC:
		case W_TF_BC:
			return uniwill_ioctl_interface(file, cmd, arg);
#endif
		default:
			if ((cmd == R_CL_WEBCAM_SW || cmd == W_CL_WEBCAM_SW) &&
			    id_check_uniwill && !id_check_clevo)
				return uniwill_webcam_ioctl(file, cmd, arg);
			switch (_IOC_TYPE(cmd)) {
				case MAGIC_READ_CL:
				case MAGIC_WRITE_CL:
					return clevo_ioctl_interface(file, cmd, arg);
				case MAGIC_READ_UW:
				case MAGIC_WRITE_UW:
					return uniwill_ioctl_interface(file, cmd, arg);
				default:
					return -ENOTTY;
			}
	}

	return copy_result ? -EFAULT : 0;
}

static struct file_operations fops_dev = {
	.owner              = THIS_MODULE,
	.unlocked_ioctl     = fop_ioctl
//	.open               = fop_open,
//	.release            = fop_release
};

struct class *tuxedo_io_device_class;
dev_t tuxedo_io_device_handle;

static struct cdev tuxedo_io_cdev;

static int __init tuxedo_io_init(void)
{
	int err;

	// Hardware identification
	id_check_clevo = clevo_identify();
	id_check_uniwill = uniwill_identify();

#ifdef DEBUG
	pr_debug("DEBUG is defined\n");

	if (id_check_clevo == 0 && id_check_uniwill == 0) {
		pr_debug("No matching hardware found on module load\n");
	}
#endif

	err = alloc_chrdev_region(&tuxedo_io_device_handle, 0, 1, "tuxedo_io_cdev");
	if (err != 0) {
		pr_err("Failed to allocate chrdev region\n");
		return err;
	}
	cdev_init(&tuxedo_io_cdev, &fops_dev);
	err = (cdev_add(&tuxedo_io_cdev, tuxedo_io_device_handle, 1));
	if (err < 0) {
		pr_err("Failed to add cdev\n");
		unregister_chrdev_region(tuxedo_io_device_handle, 1);
	}

#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 4, 0)
	tuxedo_io_device_class = class_create(THIS_MODULE, "tuxedo_io");
#else
	tuxedo_io_device_class = class_create("tuxedo_io");
#endif

	device_create(tuxedo_io_device_class, NULL, tuxedo_io_device_handle, NULL, "tuxedo_io");
	pr_debug("Module init successful\n");

	return 0;
}

static void __exit tuxedo_io_exit(void)
{
	device_destroy(tuxedo_io_device_class, tuxedo_io_device_handle);
	class_destroy(tuxedo_io_device_class);
	cdev_del(&tuxedo_io_cdev);
	unregister_chrdev_region(tuxedo_io_device_handle, 1);
	pr_debug("Module exit\n");
}

module_init(tuxedo_io_init);
module_exit(tuxedo_io_exit);
