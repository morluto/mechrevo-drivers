/* Userspace spies around the Uniwill webcam ioctl. No devices, modules, or sysfs. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include "tuxedo_io_ioctl.h"

typedef uint8_t u8;
typedef uint32_t u32;
typedef long long loff_t;
typedef long ssize_t;
struct file { int unused; };
#define __user
#define USB_CLASS_VIDEO 0x0e
#define IS_ERR(ptr) ((unsigned long)(void *)(ptr) >= (unsigned long)-4095UL)
#define PTR_ERR(ptr) ((long)(void *)(ptr))
#define ERR_PTR(err) ((void *)(long)(err))

struct usb_interface_descriptor { uint8_t bInterfaceClass; };
struct usb_host_interface { struct usb_interface_descriptor desc; };
struct usb_interface { struct usb_host_interface *cur_altsetting; };
struct usb_config_descriptor { uint8_t bNumInterfaces; };
struct usb_host_config {
	struct usb_config_descriptor desc;
	struct usb_interface *interface[32];
};
struct device { const char *init_name; };
struct usb_device {
	unsigned authorized:1;
	const char *product;
	struct usb_host_config *actconfig;
	struct device dev;
};
#define dev_name(dev) ((dev)->init_name)

#define MAX_DEVICES 6
static struct usb_device devices[MAX_DEVICES];
static struct usb_host_config configs[MAX_DEVICES];
static struct usb_interface interfaces[MAX_DEVICES][4];
static struct usb_host_interface altsettings[MAX_DEVICES][4];
static int device_count;
static int usb_walks;

static struct usb_device *add_device(const char *name, const char *product, int authorized)
{
	struct usb_device *udev;

	assert(device_count < MAX_DEVICES);
	udev = &devices[device_count++];
	udev->dev.init_name = name;
	udev->product = product;
	udev->authorized = authorized;
	return udev;
}

static void add_interface(struct usb_device *udev, uint8_t class)
{
	int slot = (int)(udev - devices);
	int index = udev->actconfig ? udev->actconfig->desc.bNumInterfaces : 0;

	assert(index < 4);
	if (!udev->actconfig)
		udev->actconfig = &configs[slot];
	altsettings[slot][index].desc.bInterfaceClass = class;
	interfaces[slot][index].cur_altsetting = &altsettings[slot][index];
	udev->actconfig->interface[index] = &interfaces[slot][index];
	udev->actconfig->desc.bNumInterfaces = index + 1;
}

static int usb_for_each_dev(void *data, int (*fn)(struct usb_device *, void *))
{
	int i, status;

	++usb_walks;
	for (i = 0; i < device_count; ++i) {
		status = fn(&devices[i], data);
		if (status)
			return status;
	}
	return 0;
}

static unsigned long input_fault, output_fault;
static int input_copies, output_copies;
static unsigned long copy_from_user(void *destination, const void *source, size_t length)
{
	++input_copies;
	assert(input_fault <= length);
	memcpy(destination, source, length - input_fault);
	return input_fault;
}
static unsigned long copy_to_user(void *destination, const void *source, size_t length)
{
	++output_copies;
	assert(output_fault <= length);
	memcpy(destination, source, length - output_fault);
	return output_fault;
}

static int open_calls, write_calls, close_calls, open_errno, write_result, write_limit;
static int open_flags;
static char paths[4][64];
static char written_values[4];
static struct file files[4];

static int scnprintf(char *buffer, size_t size, const char *format, ...)
{
	va_list args;
	int length;

	va_start(args, format);
	length = vsnprintf(buffer, size, format, args);
	va_end(args);
	if (length < 0 || size == 0)
		return length < 0 ? length : 0;
	if ((size_t)length >= size)
		return (int)size - 1;
	return length;
}

struct file *filp_open(const char *path, int flags, unsigned mode)
{
	assert(mode == 0);
	open_flags = flags;
	if (open_errno)
		return ERR_PTR(open_errno);
	assert(open_calls < 4);
	snprintf(paths[open_calls], sizeof(paths[open_calls]), "%s", path);
	return &files[open_calls++];
}

static void apply_authorized(const char *path, char value)
{
	const char *prefix = "/sys/bus/usb/devices/";
	const char *suffix = "/authorized";
	size_t prefix_length = strlen(prefix);
	size_t path_length = strlen(path);
	size_t suffix_length = strlen(suffix);
	int i;

	assert(path_length > prefix_length + suffix_length);
	assert(strncmp(path, prefix, prefix_length) == 0);
	assert(strcmp(path + path_length - suffix_length, suffix) == 0);
	for (i = 0; i < device_count; ++i) {
		size_t name_length = strlen(devices[i].dev.init_name);

		if (name_length == path_length - prefix_length - suffix_length &&
		    strncmp(path + prefix_length, devices[i].dev.init_name, name_length) == 0) {
			devices[i].authorized = value == '1';
			return;
		}
	}
	assert(!"authorized write did not match a USB device");
}

long kernel_write(struct file *file, const void *buffer, size_t count, loff_t *position)
{
	(void)file;
	assert(count == 1 && position && *position == 0);
	assert(write_calls < 4);
	written_values[write_calls++] = *(const char *)buffer;
	if (write_limit && write_calls == write_limit)
		return -EIO;
	if (write_result != 1)
		return write_result;
	apply_authorized(paths[open_calls - 1], *(const char *)buffer);
	return 1;
}

int filp_close(struct file *file, void *id)
{
	(void)file;
	(void)id;
	++close_calls;
	return 0;
}

/* @WEBCAM_MACROS@ */
/* @WEBCAM_FUNCTIONS@ */

static u32 id_check_clevo, id_check_uniwill;
static int clevo_calls;
static unsigned int clevo_command;
static long clevo_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)arg;
	++clevo_calls;
	clevo_command = cmd;
	return 0;
}
static long uniwill_ioctl_interface(struct file *file, unsigned int cmd, unsigned long arg)
{
	(void)file;
	(void)cmd;
	(void)arg;
	return -ENOTTY;
}
static u32 clevo_identify(void) { return 0; }
static u32 uniwill_identify(void) { return 1; }
static struct { const char *version; } test_module = { "test-version" };
#define THIS_MODULE (&test_module)
/* @IOCTL_ENTRY@ */

static void reset(void)
{
	memset(devices, 0, sizeof(devices));
	memset(configs, 0, sizeof(configs));
	memset(interfaces, 0, sizeof(interfaces));
	memset(altsettings, 0, sizeof(altsettings));
	device_count = usb_walks = 0;
	input_fault = output_fault = 0;
	input_copies = output_copies = 0;
	open_calls = write_calls = close_calls = 0;
	open_errno = 0;
	write_result = 1;
	write_limit = 0;
	open_flags = 0;
	clevo_calls = 0;
	clevo_command = 0;
	id_check_clevo = 0;
	id_check_uniwill = 1;
	memset(paths, 0, sizeof(paths));
	memset(written_values, 0, sizeof(written_values));
}

static struct usb_device *camera(const char *name, int authorized)
{
	struct usb_device *udev = add_device(name, "HD Webcam", authorized);

	add_interface(udev, 0xfe);
	add_interface(udev, USB_CLASS_VIDEO);
	return udev;
}

static void get_enabled(void)
{
	u32 value = 99;

	reset();
	camera("1-5", 1);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(value == 1);
	assert(open_calls == 0 && write_calls == 0 && usb_walks == 1);
}

static void get_disabled_without_config(void)
{
	u32 value = 99;

	reset();
	add_device("1-5", "HD Webcam", 0);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(value == 0 && open_calls == 0);
}

static void get_absent(void)
{
	u32 value = 99;

	reset();
	add_device("1-2", "USB Optical Mouse", 1);
	add_device("1-4", "USB2.0 Hub", 1);
	add_interface(&devices[1], 0x09);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == -ENODEV);
	assert(value == 99 && open_calls == 0);
}

static void get_mixed(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 0);
	camera("1-6", 1);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(value == 1);
}

static void set_disables_only_camera(void)
{
	u32 value = 0x100;

	reset();
	camera("1-5", 1);
	add_device("1-2", "USB Optical Mouse", 1);
	add_device("1-3", "YubiKey OTP+FIDO+CCID", 1);
	add_device("1-4", "USB2.0 Hub", 1);
	add_interface(&devices[3], 0x09);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(open_calls == 1 && write_calls == 1 && close_calls == 1);
	assert(open_flags == O_WRONLY);
	assert(strcmp(paths[0], "/sys/bus/usb/devices/1-5/authorized") == 0);
	assert(written_values[0] == '0');
	assert(devices[0].authorized == 0);
	assert(devices[1].authorized == 1 && devices[2].authorized == 1 && devices[3].authorized == 1);
}

static void set_enables_named_camera_without_config(void)
{
	u32 value = 0x101;

	reset();
	add_device("2-1.4", "Integrated Camera", 0);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(open_calls == 1 && written_values[0] == '1');
	assert(strcmp(paths[0], "/sys/bus/usb/devices/2-1.4/authorized") == 0);
	assert(devices[0].authorized == 1);
}

static void set_noop_for_both_states(void)
{
	u32 off = 0x10;
	u32 on = 0x11;

	reset();
	camera("1-5", 0);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&off) == 0);
	assert(open_calls == 0 && devices[0].authorized == 0);
	reset();
	camera("1-5", 1);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&on) == 0);
	assert(open_calls == 0 && devices[0].authorized == 1);
}

static void set_stops_after_first_write_error(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	camera("1-6", 1);
	write_result = -EIO;
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EIO);
	assert(open_calls == 1 && write_calls == 1 && close_calls == 1);
	assert(strcmp(paths[0], "/sys/bus/usb/devices/1-5/authorized") == 0);
	assert(devices[0].authorized == 1 && devices[1].authorized == 1);
}

static void set_open_error_changes_nothing(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	open_errno = -EACCES;
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EACCES);
	assert(open_calls == 0 && write_calls == 0 && close_calls == 0);
	assert(devices[0].authorized == 1);
}

static void set_short_write_is_eio(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	write_result = 0;
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EIO);
	assert(close_calls == 1 && devices[0].authorized == 1);
}

static void set_second_device_error_keeps_first_change(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	camera("1-6", 1);
	write_limit = 2;
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EIO);
	assert(open_calls == 2 && close_calls == 2);
	assert(devices[0].authorized == 0 && devices[1].authorized == 1);
	assert(strcmp(paths[1], "/sys/bus/usb/devices/1-6/authorized") == 0);
}

static void set_absent_does_not_open(void)
{
	u32 value = 1;

	reset();
	add_device("1-2", "USB Optical Mouse", 1);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -ENODEV);
	assert(open_calls == 0 && devices[0].authorized == 1);
}

static void copy_faults_precede_usb_access(void)
{
	u32 value = 1;

	reset();
	camera("1-5", 1);
	input_fault = sizeof(value);
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EFAULT);
	assert(usb_walks == 0 && open_calls == 0 && devices[0].authorized == 1);

	reset();
	camera("1-5", 1);
	input_fault = 1;
	assert(uniwill_webcam_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == -EFAULT);
	assert(usb_walks == 0 && open_calls == 0);

	reset();
	camera("1-5", 1);
	output_fault = sizeof(value);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == -EFAULT);
	assert(usb_walks == 1 && open_calls == 0 && devices[0].authorized == 1);
}

static void video_class_counts_without_product_text(void)
{
	u32 value = 0;

	reset();
	add_device("1-5", NULL, 1);
	add_interface(&devices[0], USB_CLASS_VIDEO);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(value == 1);
}

static void bad_names_are_not_cameras(void)
{
	u32 value = 7;

	reset();
	add_device("1-5:1.0", "HD Webcam", 1);
	add_device("usb1", "HD Webcam", 1);
	add_device("../1-5", "HD Webcam", 1);
	add_device("1-5/authorized", "HD Webcam", 1);
	assert(uniwill_webcam_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == -ENODEV);
	assert(open_calls == 0 && value == 7);
	assert(devices[0].authorized == 1 && devices[1].authorized == 1);
}

static void unknown_command_is_enotty(void)
{
	reset();
	camera("1-5", 1);
	assert(uniwill_webcam_ioctl(NULL, W_CL_FANAUTO, 0) == -ENOTTY);
	assert(usb_walks == 0 && open_calls == 0);
}

static void route_uniwill_only(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	assert(fop_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(clevo_calls == 0 && open_calls == 1 && devices[0].authorized == 0);
}

static void route_keeps_clevo_without_uniwill_or_when_both_exist(void)
{
	u32 value = 1;

	reset();
	id_check_uniwill = 0;
	id_check_clevo = 0;
	camera("1-5", 1);
	assert(fop_ioctl(NULL, W_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(clevo_calls == 1 && clevo_command == W_CL_WEBCAM_SW);
	assert(usb_walks == 0 && open_calls == 0 && devices[0].authorized == 1);

	reset();
	id_check_uniwill = 1;
	id_check_clevo = 1;
	camera("1-5", 1);
	assert(fop_ioctl(NULL, R_CL_WEBCAM_SW, (unsigned long)&value) == 0);
	assert(clevo_calls == 1 && clevo_command == R_CL_WEBCAM_SW);
	assert(usb_walks == 0 && devices[0].authorized == 1);
}

static void other_clevo_commands_stay_on_clevo(void)
{
	u32 value = 0;

	reset();
	camera("1-5", 1);
	assert(fop_ioctl(NULL, W_CL_FANAUTO, (unsigned long)&value) == 0);
	assert(clevo_calls == 1 && clevo_command == W_CL_FANAUTO);
	assert(usb_walks == 0 && open_calls == 0 && devices[0].authorized == 1);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
#define CASE(name) if (strcmp(argv[1], #name) == 0) { name(); return 0; }
	CASE(get_enabled)
	CASE(get_disabled_without_config)
	CASE(get_absent)
	CASE(get_mixed)
	CASE(set_disables_only_camera)
	CASE(set_enables_named_camera_without_config)
	CASE(set_noop_for_both_states)
	CASE(set_stops_after_first_write_error)
	CASE(set_second_device_error_keeps_first_change)
	CASE(set_open_error_changes_nothing)
	CASE(set_short_write_is_eio)
	CASE(set_absent_does_not_open)
	CASE(copy_faults_precede_usb_access)
	CASE(video_class_counts_without_product_text)
	CASE(bad_names_are_not_cameras)
	CASE(unknown_command_is_enotty)
	CASE(route_uniwill_only)
	CASE(route_keeps_clevo_without_uniwill_or_when_both_exist)
	CASE(other_clevo_commands_stay_on_clevo)
	assert(!"Unknown testcase");
}
