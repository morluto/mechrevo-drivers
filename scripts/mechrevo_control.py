#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""MECHREVO Gaming Center (机械革命电竞控制台) for Linux.

This tool ports and integrates the complete feature set of the OEM Mechrevo
Gaming Center to Linux on the GM6PX0X (and compatible) platforms:
1. Operating Modes (Office / Gaming / Turbo; independent thermal power policy)
2. One-Click Fan Boost (一键强冷 / 100% Full Speed) & Auto Fan Control
3. Win Key Lock (电竞游戏防误触锁) via hardware scancode mapping
4. Touchpad Hardware Lock via I2C device bind/unbind
5. Fn Lock (F1-F12 primary vs multimedia hotkeys)
6. 3-Stage Battery Health Care (100% High Capacity / 80% Balanced / 60% Long-Life)
7. Single-Zone RGB Keyboard Lighting & 4-Level Brightness Control
8. Real-time Telemetry Dashboard (Dual Fan RPM, CPU/GPU EC Temperatures, Power)
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

PROFILES_PATH = Path("/etc/tcc/profiles")
SETTINGS_PATH = Path("/etc/tcc/settings")
def get_state_dir() -> Path:
    sys_dir = Path("/var/lib/mechrevo-control")
    if sys_dir.exists() and os.access(sys_dir, os.W_OK):
        return sys_dir
    errors = []
    if os.geteuid() == 0:
        try:
            sys_dir.mkdir(parents=True, exist_ok=True)
            return sys_dir
        except OSError as exc:
            errors.append(f"{sys_dir}: {exc}")
    user_dir = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mechrevo-control"
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    except OSError as exc:
        errors.append(f"{user_dir}: {exc}")
        fallback = Path("/tmp/mechrevo-control")
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            print("状态目录回退到 " + str(fallback) + ": " + "; ".join(errors), file=sys.stderr)
            return fallback
        except OSError as fallback_exc:
            errors.append(f"{fallback}: {fallback_exc}")
            raise RuntimeError("Unable to create a state directory: " + "; ".join(errors)) from fallback_exc


def get_state_file(name: str) -> Path:
    sys_file = Path("/var/lib/mechrevo-control") / name
    if sys_file.exists():
        return sys_file
    return get_state_dir() / name

FN_LOCK_PATH = Path("/sys/devices/platform/tuxedo_keyboard/fn_lock")
BATTERY_PROFILE_PATH = Path("/sys/devices/platform/tuxedo_keyboard/charging_profile/charging_profile")
RGB_LEDS_DIR = Path("/sys/class/leds/rgb:kbd_backlight")
TOUCHPAD_I2C_DEVICE = "i2c-UNIW0001:00"
TOUCHPAD_BIND_PATH = Path("/sys/bus/i2c/drivers/i2c_hid_acpi/bind")
TOUCHPAD_UNBIND_PATH = Path("/sys/bus/i2c/drivers/i2c_hid_acpi/unbind")
TOUCHPAD_BOUND_CHECK = Path(f"/sys/bus/i2c/drivers/i2c_hid_acpi/{TOUCHPAD_I2C_DEVICE}")
TOUCHPAD_DEVICE_PATH = Path(f"/sys/bus/i2c/devices/{TOUCHPAD_I2C_DEVICE}")

# Local cooling defaults: keep at least 60% in normal modes. This floor was
# exercised on GM6PX0X; it is a control request, not a guaranteed RPM or OEM curve.
MECHREVO_PROFILES = [
    {
        "id": "mechrevo_office",
        "name": "机械革命-办公节能模式 (Office)",
        "description": "办公节能：balance_power 偏好，CPU 上限 3.2GHz；不设置 PL1，保留独立温控",
        "display": {
            "brightness": 70,
            "useBrightness": False,
            "refreshRate": -1,
            "useRefRate": False,
            "xResolution": -1,
            "yResolution": -1,
            "useResolution": False,
        },
        "cpu": {
            "useMaxPerfGov": False,
            "governor": "powersave",
            "energyPerformancePreference": "balance_power",
            "noTurbo": False,
            "onlineCores": 24,
            "scalingMinFrequency": 800000,
            "scalingMaxFrequency": 3200000,
        },
        "webcam": {"status": True, "useStatus": True},
        "fan": {
            "useControl": True,
            "fanProfile": "Quiet",
            "minimumFanspeed": 60,
            "maximumFanspeed": 100,
            "offsetFanspeed": 0,
            "customFanCurve": {
                "tableCPU": [
                    {"temp": 20, "speed": 10},
                    {"temp": 30, "speed": 12},
                    {"temp": 40, "speed": 15},
                    {"temp": 50, "speed": 22},
                    {"temp": 60, "speed": 35},
                    {"temp": 70, "speed": 50},
                    {"temp": 80, "speed": 70},
                    {"temp": 90, "speed": 85},
                    {"temp": 100, "speed": 90},
                ],
                "tableGPU": [
                    {"temp": 20, "speed": 10},
                    {"temp": 30, "speed": 12},
                    {"temp": 40, "speed": 15},
                    {"temp": 50, "speed": 22},
                    {"temp": 60, "speed": 35},
                    {"temp": 70, "speed": 50},
                    {"temp": 80, "speed": 70},
                    {"temp": 90, "speed": 85},
                    {"temp": 100, "speed": 90},
                ],
            },
        },
        "odmProfile": {"name": ""},
        "odmPowerLimits": {"tdpValues": []},
        "nvidiaPowerCTRLProfile": {"cTGPOffset": 0},
    },
    {
        "id": "mechrevo_gaming",
        "name": "机械革命-游戏平衡模式 (Gaming)",
        "description": "游戏平衡：balance_performance 偏好，动态睿频；不设置 PL1，保留独立温控",
        "display": {
            "brightness": 80,
            "useBrightness": False,
            "refreshRate": -1,
            "useRefRate": False,
            "xResolution": -1,
            "yResolution": -1,
            "useResolution": False,
        },
        "cpu": {
            "useMaxPerfGov": False,
            "governor": "powersave",
            "energyPerformancePreference": "balance_performance",
            "noTurbo": False,
            "onlineCores": 24,
            "scalingMinFrequency": 800000,
            "scalingMaxFrequency": 4900000,
        },
        "webcam": {"status": True, "useStatus": True},
        "fan": {
            "useControl": True,
            "fanProfile": "Balanced",
            "minimumFanspeed": 60,
            "maximumFanspeed": 100,
            "offsetFanspeed": 0,
            "customFanCurve": {
                "tableCPU": [
                    {"temp": 20, "speed": 15},
                    {"temp": 30, "speed": 18},
                    {"temp": 40, "speed": 25},
                    {"temp": 50, "speed": 38},
                    {"temp": 60, "speed": 50},
                    {"temp": 70, "speed": 65},
                    {"temp": 80, "speed": 82},
                    {"temp": 90, "speed": 92},
                    {"temp": 100, "speed": 95},
                ],
                "tableGPU": [
                    {"temp": 20, "speed": 15},
                    {"temp": 30, "speed": 18},
                    {"temp": 40, "speed": 25},
                    {"temp": 50, "speed": 38},
                    {"temp": 60, "speed": 50},
                    {"temp": 70, "speed": 65},
                    {"temp": 80, "speed": 82},
                    {"temp": 90, "speed": 92},
                    {"temp": 100, "speed": 95},
                ],
            },
        },
        "odmProfile": {"name": ""},
        "odmPowerLimits": {"tdpValues": []},
        "nvidiaPowerCTRLProfile": {"cTGPOffset": 25},
    },
    {
        "id": "mechrevo_gaming_quiet",
        "name": "机械革命-游戏低噪模式 (Gaming Quiet)",
        "description": "保留游戏平衡 CPU 参数，较低风扇下限请求；不保证实际噪声或转速",
        "display": {
            "brightness": 80,
            "useBrightness": False,
            "refreshRate": -1,
            "useRefRate": False,
            "xResolution": -1,
            "yResolution": -1,
            "useResolution": False,
        },
        "cpu": {
            "useMaxPerfGov": False,
            "governor": "powersave",
            "energyPerformancePreference": "balance_performance",
            "noTurbo": False,
            "onlineCores": 24,
            "scalingMinFrequency": 800000,
            "scalingMaxFrequency": 4900000,
        },
        "webcam": {"status": True, "useStatus": True},
        "fan": {
            "useControl": True,
            "fanProfile": "Balanced",
            "minimumFanspeed": 50,
            "maximumFanspeed": 100,
            "offsetFanspeed": 0,
            "customFanCurve": {
                "tableCPU": [
                    {"temp": 20, "speed": 12},
                    {"temp": 30, "speed": 15},
                    {"temp": 40, "speed": 22},
                    {"temp": 50, "speed": 32},
                    {"temp": 60, "speed": 42},
                    {"temp": 70, "speed": 54},
                    {"temp": 80, "speed": 68},
                    {"temp": 90, "speed": 82},
                    {"temp": 100, "speed": 96},
                ],
                "tableGPU": [
                    {"temp": 20, "speed": 12},
                    {"temp": 30, "speed": 15},
                    {"temp": 40, "speed": 22},
                    {"temp": 50, "speed": 32},
                    {"temp": 60, "speed": 42},
                    {"temp": 70, "speed": 54},
                    {"temp": 80, "speed": 68},
                    {"temp": 90, "speed": 82},
                    {"temp": 100, "speed": 96},
                ],
            },
        },
        "odmProfile": {"name": ""},
        "odmPowerLimits": {"tdpValues": []},
        "nvidiaPowerCTRLProfile": {"cTGPOffset": 25},
    },
    {
        "id": "mechrevo_turbo",
        "name": "机械革命-极速狂暴模式 (Turbo)",
        "description": "狂暴性能：performance 偏好，允许空闲降频；不设置 PL1，保留独立温控",
        "display": {
            "brightness": 90,
            "useBrightness": False,
            "refreshRate": -1,
            "useRefRate": False,
            "xResolution": -1,
            "yResolution": -1,
            "useResolution": False,
        },
        "cpu": {
            "useMaxPerfGov": False,
            "governor": "powersave",
            "energyPerformancePreference": "performance",
            "noTurbo": False,
            "onlineCores": 24,
            "scalingMinFrequency": 800000,
            "scalingMaxFrequency": 5000000,
        },
        "webcam": {"status": True, "useStatus": True},
        "fan": {
            "useControl": True,
            "fanProfile": "Freezy",
            "minimumFanspeed": 60,
            "maximumFanspeed": 100,
            "offsetFanspeed": 0,
            "customFanCurve": {
                "tableCPU": [
                    {"temp": 20, "speed": 22},
                    {"temp": 30, "speed": 28},
                    {"temp": 40, "speed": 40},
                    {"temp": 50, "speed": 55},
                    {"temp": 60, "speed": 72},
                    {"temp": 70, "speed": 85},
                    {"temp": 80, "speed": 95},
                    {"temp": 90, "speed": 98},
                    {"temp": 100, "speed": 100},
                ],
                "tableGPU": [
                    {"temp": 20, "speed": 22},
                    {"temp": 30, "speed": 28},
                    {"temp": 40, "speed": 40},
                    {"temp": 50, "speed": 55},
                    {"temp": 60, "speed": 72},
                    {"temp": 70, "speed": 85},
                    {"temp": 80, "speed": 95},
                    {"temp": 90, "speed": 98},
                    {"temp": 100, "speed": 100},
                ],
            },
        },
        "odmProfile": {"name": ""},
        "odmPowerLimits": {"tdpValues": []},
        "nvidiaPowerCTRLProfile": {"cTGPOffset": 25},
    },
    {
        "id": "mechrevo_fan_boost",
        "name": "机械革命-一键强冷 (Fan Boost)",
        "description": "一键强冷：请求双风扇 100%，实际转速需回读；不设置 PL1",
        "display": {
            "brightness": 80,
            "useBrightness": False,
            "refreshRate": -1,
            "useRefRate": False,
            "xResolution": -1,
            "yResolution": -1,
            "useResolution": False,
        },
        "cpu": {
            "useMaxPerfGov": False,
            "governor": "powersave",
            "energyPerformancePreference": "balance_performance",
            "noTurbo": False,
            "onlineCores": 24,
            "scalingMinFrequency": 800000,
            "scalingMaxFrequency": 4900000,
        },
        "webcam": {"status": True, "useStatus": False},
        "fan": {
            "useControl": True,
            "fanProfile": "Freezy",
            "minimumFanspeed": 100,
            "maximumFanspeed": 100,
            "offsetFanspeed": 0,
            "customFanCurve": {
                "tableCPU": [{"temp": t, "speed": 100} for t in range(20, 101, 10)],
                "tableGPU": [{"temp": t, "speed": 100} for t in range(20, 101, 10)],
            },
        },
        "odmProfile": {"name": ""},
        "odmPowerLimits": {"tdpValues": []},
        "nvidiaPowerCTRLProfile": {"cTGPOffset": 25},
    },
]


def run_cmd(cmd: list[str], check: bool = True) -> str:
    """Run a shell command and return trimmed output."""
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command {' '.join(cmd)} failed (code {res.returncode}): {res.stderr.strip()}")
    return res.stdout.strip()


def ensure_state_dir() -> None:
    get_state_dir()


def call_tccd_dbus(method: str, signature: str = "", *args) -> str:
    """Call a method on com.tuxedocomputers.tccd D-Bus interface."""
    cmd = ["busctl", "call", "--json=short", "com.tuxedocomputers.tccd", "/com/tuxedocomputers/tccd", "com.tuxedocomputers.tccd", method]
    if signature:
        cmd.append(signature)
        cmd.extend(str(a) for a in args)
    return run_cmd(cmd)


# ==============================================================================
# 1. Operating Modes
# ==============================================================================

def sync_oem_profiles() -> None:
    """Append missing defaults; preserve existing profile choices and user fields."""
    import stat
    import tempfile

    def snapshot():
        try:
            before = PROFILES_PATH.lstat()
        except FileNotFoundError:
            return None, None
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Refusing non-regular profile store: {PROFILES_PATH}")
        descriptor = os.open(PROFILES_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise RuntimeError(f"Profile store changed while opening: {PROFILES_PATH}")
            contents = source.read()
            after = os.fstat(source.fileno())
        if identity(before) != identity(after):
            raise RuntimeError(f"Profile store changed while reading: {PROFILES_PATH}")
        return contents, after

    def identity(info):
        if info is None:
            return None
        return (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
                stat.S_IMODE(info.st_mode), info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def unique_object(pairs):
        value = {}
        for key, entry in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key in {PROFILES_PATH}: {key}")
            value[key] = entry
        return value

    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant in {PROFILES_PATH}: {value}")

    def profile_ids(records, origin):
        if not isinstance(records, list):
            raise ValueError(f"Expected profile list in {origin}")
        ids = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"].strip():
                raise ValueError(f"Invalid profile record at index {index} in {origin}")
            if record["id"] in ids:
                raise ValueError(f"Duplicate profile ID in {origin}: {record['id']}")
            ids.add(record["id"])
        return ids

    original, original_info = snapshot()
    if original is None:
        current_profiles = []
    else:
        current_profiles = json.loads(original.decode("utf-8"), object_pairs_hook=unique_object,
                                      parse_constant=invalid_constant)
    # TCC ships a root-owned ``__default_custom_profile__`` which is still
    # named "TUXEDO Defaults" on an untouched installation.  Power-state
    # switching always selects that ID, so merely appending Mechrevo profiles
    # leaves the machine on the generic curve.  Migrate only that exact stock
    # record to the qualified Gaming profile; any user edit is preserved.
    migrated = False
    gaming = next(record for record in MECHREVO_PROFILES if record["id"] == "mechrevo_gaming")
    migrated_profiles = []
    for record in current_profiles:
        if (record.get("id") == "__default_custom_profile__"
                and record.get("name") == "TUXEDO Defaults"
                and record.get("description") == "Edit profile to change behaviour"):
            replacement = json.loads(json.dumps(gaming))
            replacement["id"] = "__default_custom_profile__"
            migrated_profiles.append(replacement)
            migrated = True
        else:
            migrated_profiles.append(record)
    current_profiles = migrated_profiles
    existing_ids = profile_ids(current_profiles, PROFILES_PATH)
    profile_ids(MECHREVO_PROFILES, "built-in defaults")
    missing = [record for record in MECHREVO_PROFILES if record["id"] not in existing_ids]
    if not missing and not migrated:
        return  # No write, inode replacement, chmod, or mtime change for a complete store.

    payload = (json.dumps(current_profiles + missing, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".mechrevo-profiles-", dir=PROFILES_PATH.parent)
    temporary = Path(temporary_name)
    committed = False
    try:
        with os.fdopen(descriptor, "wb") as staged:
            if original_info is not None:
                staged_info = os.fstat(staged.fileno())
                if (staged_info.st_uid, staged_info.st_gid) != (original_info.st_uid, original_info.st_gid):
                    os.fchown(staged.fileno(), original_info.st_uid, original_info.st_gid)
                os.fchmod(staged.fileno(), stat.S_IMODE(original_info.st_mode))
            else:
                os.fchmod(staged.fileno(), 0o644)
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())

        latest, latest_info = snapshot()
        if latest != original or identity(latest_info) != identity(original_info):
            raise RuntimeError(f"Profile store changed concurrently; refusing overwrite: {PROFILES_PATH}")
        if original_info is None:
            # link is an atomic create-if-absent; a newly appeared destination is never replaced.
            os.link(temporary, PROFILES_PATH)
        else:
            # Final observed byte/identity comparison is above. Non-cooperating writers can
            # still race in the narrow interval before replace; this is not kernel-level CAS.
            os.replace(temporary, PROFILES_PATH)
        committed = True
        directory = os.open(PROFILES_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception as exc:
        if committed:
            raise RuntimeError(f"Profiles committed but directory durability check failed; inspect {PROFILES_PATH}: {exc}") from exc
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def send_notification(title: str, message: str, icon: str = "preferences-system-power") -> None:
    """Send a notification and propagate notifier failures."""
    if not shutil.which("notify-send"):
        raise RuntimeError("通知发送失败：找不到 notify-send")
    run_cmd(["notify-send", "-u", "critical", "-t", "3000",
             "-a", "MECHREVO Gaming Center", "-i", icon, title, message])


def get_current_mode_info() -> tuple[str, str]:
    """Get active profile (name, id)."""
    out = call_tccd_dbus("GetActiveProfileJSON")
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tccd returned invalid active-profile JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list) or not parsed["data"]:
        raise RuntimeError("tccd returned no active profile")
    raw_inner = parsed["data"][0]
    if isinstance(raw_inner, str):
        try:
            profile_data = json.loads(raw_inner)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"tccd returned invalid profile payload: {exc}") from exc
    else:
        profile_data = raw_inner
    if not isinstance(profile_data, dict):
        raise RuntimeError("tccd returned a non-object active profile")
    name = profile_data.get("name")
    profile_id = profile_data.get("id")
    if not isinstance(name, str) or not name or not isinstance(profile_id, str) or not profile_id:
        raise RuntimeError("tccd returned an incomplete active profile")
    return name, profile_id


def get_current_mode() -> str:
    """Get the active performance mode name."""
    return get_current_mode_info()[0]


EC_MODE_BYTES = {
    "office": 0xa0,
    "gaming": 0x00,
    "gaming-quiet": 0x00,
    "turbo": 0x10,
    "boost": 0x10,
}
# Hardware cycle order used by the physical key when tccd is not involved.
EC_MODE_CYCLE = (("office", 0xa0), ("gaming", 0x00), ("turbo", 0x10))
EC_CONTROL_DEVICE = Path("/dev/tuxedo_io")
W_UW_MODE = 0x4008f012
R_UW_MODE = 0x8008ef14


def read_hardware_mode() -> int:
    """Read the EC mode byte through tuxedo_io."""
    if not EC_CONTROL_DEVICE.exists():
        raise RuntimeError(f"Uniwill control device is unavailable: {EC_CONTROL_DEVICE}")
    fd = os.open(EC_CONTROL_DEVICE, os.O_RDWR)
    try:
        readback = bytearray(8)
        fcntl.ioctl(fd, R_UW_MODE, readback, True)
        return struct.unpack("i", readback[:4])[0] & 0xff
    finally:
        os.close(fd)


def write_hardware_mode(value: int) -> int:
    """Request an EC mode byte and verify the readback."""
    if not EC_CONTROL_DEVICE.exists():
        raise RuntimeError(f"Uniwill control device is unavailable: {EC_CONTROL_DEVICE}")
    value &= 0xff
    fd = os.open(EC_CONTROL_DEVICE, os.O_RDWR)
    try:
        fcntl.ioctl(fd, W_UW_MODE, struct.pack("i", value))
        readback = bytearray(8)
        fcntl.ioctl(fd, R_UW_MODE, readback, True)
        actual = struct.unpack("i", readback[:4])[0] & 0xff
    finally:
        os.close(fd)
    if actual != value:
        raise RuntimeError(f"EC mode readback mismatch: requested 0x{value:02x}, got 0x{actual:02x}")
    return actual


def set_hardware_mode_led(mode_key: str) -> None:
    """Request a mode byte and require the EC readback to match it.

    The driver exposes the mode byte, but Linux has no independent physical LED
    readback for this machine. A matching EC readback therefore proves only
    that the request reached the driver, not that a chassis lamp is illuminated.
    """
    if mode_key not in EC_MODE_BYTES:
        raise ValueError(f"Unknown hardware mode key: {mode_key}")
    write_hardware_mode(EC_MODE_BYTES[mode_key])


def cycle_hardware_mode() -> str:
    """Cycle the EC mode without tccd: office -> gaming -> turbo -> office."""
    current = read_hardware_mode()
    values = [value for _, value in EC_MODE_CYCLE]
    if current in values:
        next_name, next_value = EC_MODE_CYCLE[(values.index(current) + 1) % len(EC_MODE_CYCLE)]
    else:
        # Unknown mode byte: request the known Gaming value instead of guessing.
        next_name, next_value = EC_MODE_CYCLE[1]
    write_hardware_mode(next_value)
    return next_name


UEFI_POWER_MODE_EFIVAR = Path(
    "/sys/firmware/efi/efivars/UniWillVariable-9f33f85c-13ca-4fd1-9c4a-96217722c593"
)
UEFI_POWER_MODE_DATA_OFFSET = 0x52
UEFI_POWER_MODE_FILE_OFFSET = 4 + UEFI_POWER_MODE_DATA_OFFSET
UEFI_POWER_MODE_VALUES = {
    # NVRAM_STRUCT.PowerMode: Gaming=0, Office=1, Turbo=2, Custom=3.
    "office": 1,
    "gaming": 0,
    "gaming-quiet": 0,
    "turbo": 2,
    "boost": 2,
}
_DMI_ID = Path("/sys/class/dmi/id")


def _dmi_text(name: str) -> str | None:
    try:
        return (_DMI_ID / name).read_text().strip()
    except OSError:
        return None


def uefi_power_mode_supported() -> bool:
    """Only touch NVRAM on the exact model whose layout was verified."""
    return (_dmi_text("sys_vendor") == "MECHREVO"
            and _dmi_text("board_name") == "GM6BG0Q"
            and _dmi_text("product_name") == "Jiaolong16K Series GM6BG0Q"
            and _dmi_text("bios_version") == "N.1.19MRO15"
            and UEFI_POWER_MODE_EFIVAR.is_file())


def _efivar_immutable(path: Path) -> bool:
    text = run_cmd(["lsattr", "-d", str(path)])
    return "i" in text.split()[0]


def _set_efivar_immutable(path: Path, immutable: bool) -> None:
    run_cmd(["chattr", "+i" if immutable else "-i", str(path)])


def read_uefi_power_mode() -> int:
    """Read NVRAM_STRUCT.PowerMode from the UniWill UEFI variable."""
    if not uefi_power_mode_supported():
        raise RuntimeError("UniWill UEFI PowerMode is not supported on this machine")
    raw = UEFI_POWER_MODE_EFIVAR.read_bytes()
    if len(raw) <= UEFI_POWER_MODE_FILE_OFFSET:
        raise RuntimeError(f"UniWill UEFI variable is too short: {len(raw)} bytes")
    value = raw[UEFI_POWER_MODE_FILE_OFFSET]
    if value > 3:
        raise RuntimeError(f"Unknown UniWill UEFI PowerMode byte: 0x{value:02x}")
    return value


EC_MODE_NAMES = {
    0x00: "gaming",
    0xA0: "office",
    0x10: "turbo",
}
EC_MODE_TDP = {
    # Windows Control Center 5.17.49.19 profile values: PL1, PL2, PL4.
    "office": (35, 35, 215),
    "gaming": (80, 80, 215),
    "gaming-quiet": (80, 80, 215),
    "turbo": (95, 95, 215),
    "boost": (95, 95, 215),
}
W_UW_TDP = (0x4008F015, 0x4008F016, 0x4008F017)
R_UW_TDP = (0x8008EF18, 0x8008EF19, 0x8008EF1A)


def _read_tdp(fd: int) -> tuple[int, int, int]:
    values = []
    for command in R_UW_TDP:
        readback = bytearray(8)
        fcntl.ioctl(fd, command, readback, True)
        values.append(struct.unpack("i", readback[:4])[0])
    return tuple(values)


def _write_tdp(fd: int, values: tuple[int, int, int]) -> None:
    for command, value in zip(W_UW_TDP, values):
        fcntl.ioctl(fd, command, struct.pack("i", value))


def apply_mode_tdp(mode_key: str) -> tuple[int, int, int]:
    """Apply the package PL1/PL2/PL4 profile through tuxedo_io and verify it.

    Read the previous limits first and restore all three if any write or
    readback fails, so a partial failure cannot leave a mixed profile.
    """
    if mode_key not in EC_MODE_TDP:
        raise ValueError(f"Unknown TDP mode key: {mode_key}")
    if not EC_CONTROL_DEVICE.exists():
        raise RuntimeError(f"Uniwill control device is unavailable: {EC_CONTROL_DEVICE}")
    values = EC_MODE_TDP[mode_key]
    fd = os.open(EC_CONTROL_DEVICE, os.O_RDWR)
    try:
        previous = _read_tdp(fd)
        try:
            _write_tdp(fd, values)
            actual = _read_tdp(fd)
            if actual != values:
                raise RuntimeError(f"TDP readback mismatch: requested {values}, got {actual}")
        except Exception:
            try:
                _write_tdp(fd, previous)
                restored = _read_tdp(fd)
                if restored != previous:
                    raise RuntimeError(
                        f"TDP rollback readback mismatch: requested {previous}, got {restored}"
                    )
            except Exception as rollback:
                raise RuntimeError(
                    f"TDP profile failed and rollback failed: {rollback}"
                ) from rollback
            raise
    finally:
        os.close(fd)
    return values


def write_uefi_power_mode(mode_key: str) -> int:
    """Persist the selected mode in NVRAM while preserving every other byte.

    efivarfs exposes the four attribute bytes followed by the variable data.
    The file is normally immutable; clear that flag, write the complete
    variable, verify the exact readback, then restore the flag.
    """
    if mode_key not in UEFI_POWER_MODE_VALUES:
        raise ValueError(f"Unknown UEFI PowerMode key: {mode_key}")
    if not uefi_power_mode_supported():
        raise RuntimeError("UniWill UEFI PowerMode is not supported on this machine")

    target = UEFI_POWER_MODE_VALUES[mode_key]
    raw = bytearray(UEFI_POWER_MODE_EFIVAR.read_bytes())
    if len(raw) <= UEFI_POWER_MODE_FILE_OFFSET:
        raise RuntimeError(f"UniWill UEFI variable is too short: {len(raw)} bytes")
    current = raw[UEFI_POWER_MODE_FILE_OFFSET]
    if current > 3:
        raise RuntimeError(f"Unknown UniWill UEFI PowerMode byte: 0x{current:02x}")
    if current == target:
        return target

    raw[UEFI_POWER_MODE_FILE_OFFSET] = target
    immutable = _efivar_immutable(UEFI_POWER_MODE_EFIVAR)
    try:
        if immutable:
            _set_efivar_immutable(UEFI_POWER_MODE_EFIVAR, False)
        fd = os.open(UEFI_POWER_MODE_EFIVAR, os.O_WRONLY | os.O_CLOEXEC)
        try:
            pending = memoryview(raw)
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise OSError("short write to efivarfs")
                pending = pending[written:]
            try:
                os.fsync(fd)
            except OSError as exc:
                # efivarfs rejects fsync with EINVAL; its write path is
                # synchronous and the readback below is the durable check.
                if exc.errno != errno.EINVAL:
                    raise
        finally:
            os.close(fd)
        actual = UEFI_POWER_MODE_EFIVAR.read_bytes()
        if len(actual) != len(raw) or actual[:4] != raw[:4]:
            raise RuntimeError("UniWill UEFI variable changed size or attributes")
        if actual[UEFI_POWER_MODE_FILE_OFFSET] != target:
            raise RuntimeError(
                "UniWill UEFI PowerMode readback mismatch: "
                f"requested {target}, got {actual[UEFI_POWER_MODE_FILE_OFFSET]}"
            )
        for offset, (before, after) in enumerate(zip(raw, actual)):
            if offset == UEFI_POWER_MODE_FILE_OFFSET:
                continue
            if before != after:
                raise RuntimeError(
                    f"UniWill UEFI variable changed unrelated byte 0x{offset:02x}: "
                    f"0x{before:02x} -> 0x{after:02x}"
                )
    finally:
        if immutable:
            _set_efivar_immutable(UEFI_POWER_MODE_EFIVAR, True)
    return target

PROFILE_MODE_KEYS = {
    "__default_custom_profile__": "gaming",
    "mechrevo_office": "office",
    "mechrevo_gaming": "gaming",
    "mechrevo_gaming_quiet": "gaming",
    "mechrevo_turbo": "turbo",
    "mechrevo_fan_boost": "boost",
}


def sync_mode_led_from_profile(profile_id: str | None = None) -> str:
    """Make the physical mode LED follow the active TCC profile.

    The chassis button changes the LED as a side effect of the button path,
    but GUI, power-state and daemon changes can select a profile without that
    path.  Polling the profile identity gives those callers the same readback
    contract without writing the EC on every loop.
    """
    if profile_id is None:
        _, profile_id = get_current_mode_info()
    mode_key = PROFILE_MODE_KEYS.get(profile_id)
    if mode_key:
        set_hardware_mode_led(mode_key)
    return profile_id


def set_mode(mode_name: str, notify: bool = False) -> None:
    """Select a saved profile; do not claim fixed wattage or achieved fan RPM."""
    sync_oem_profiles()
    mapping = {
        "office": ("mechrevo_office", "办公节能模式 (Office)", "已应用保存的办公配置；实际功耗由独立温控决定"),
        "gaming": ("mechrevo_gaming", "游戏平衡模式 (Gaming)", "已应用保存的游戏配置；实际功耗由独立温控决定"),
        "gaming-quiet": ("mechrevo_gaming_quiet", "游戏低噪模式 (Gaming Quiet)", "已应用保存的低噪配置；实际风扇转速需回读"),
        "turbo": ("mechrevo_turbo", "极速狂暴模式 (Turbo)", "已应用保存的性能配置；不承诺固定瓦数或持续频率"),
        "boost": ("mechrevo_fan_boost", "一键全速强冷 (Fan Boost)", "已应用保存的强冷配置；风扇请求不等于实际转速"),
    }
    mode_key = mode_name.lower().strip()
    if mode_key not in mapping:
        raise ValueError(f"Unknown mode '{mode_name}'. Valid options: {', '.join(mapping.keys())}")

    target_id, title_name, desc_info = mapping[mode_key]
    response = call_tccd_dbus("SetTempProfileById", "s", target_id)
    try:
        accepted = json.loads(response)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tccd returned invalid profile-switch JSON: {exc}") from exc
    if (not isinstance(accepted, dict) or accepted.get("type") != "b"
            or not isinstance(accepted.get("data"), list) or len(accepted["data"]) != 1
            or accepted["data"][0] is not True):
        raise RuntimeError(f"tccd did not accept profile switch to {target_id}: {response}")
    deadline = time.monotonic() + 5.0
    while True:
        _, active_id = get_current_mode_info()
        if active_id == target_id:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Timed out waiting for active profile {target_id}; observed {active_id}")
        time.sleep(min(0.1, remaining))
    set_hardware_mode_led(mode_key)
    if notify:
        send_notification("★ 机械革命电竞控制台 ★", f"运行模式已切换为：【{title_name}】\n{desc_info}")
    print(f"[✓] 成功切换至机械革命运行模式: {title_name} ({target_id})")


def cycle_mode(notify: bool = True) -> str:
    """Cycle through the distinct hardware modes Office -> Gaming -> Turbo."""
    _, current_id = get_current_mode_info()
    order = ("office", "gaming", "turbo")
    # Quiet keeps Gaming's hardware mode; Fan Boost keeps Turbo's. Treat these
    # software variants as their current hardware step instead of repeating it.
    current_key = PROFILE_MODE_KEYS.get(current_id)
    if current_key == "boost":
        current_key = "turbo"
    if current_key in order:
        next_key = order[(order.index(current_key) + 1) % len(order)]
    else:
        next_key = "gaming"

    set_mode(next_key, notify=notify)
    return next_key


def toggle_touchpad() -> None:
    """Toggle touchpad via desktop script or omarchy tool."""
    script = Path.home() / ".config/hypr/scripts/toggle-touchpad.sh"
    if script.exists():
        run_cmd([str(script)])
    elif shutil.which("omarchy-toggle-touchpad"):
        run_cmd(["omarchy-toggle-touchpad"])
    elif shutil.which("omarchy-toggle-input-device"):
        run_cmd(["omarchy-toggle-input-device", "touchpad", "toggle"])
    else:
        raise RuntimeError("No supported touchpad toggle command is available")


def run_daemon(ec_only: bool = False) -> None:
    """Listen to physical hotkey events.

    With ``ec_only`` the daemon deliberately avoids tccd and D-Bus: it writes
    the mode byte through /dev/tuxedo_io and ignores all other keys. This mode
    is intended for the root system service, which can access the 0600 control
    device and the root:input event node.
    """
    import select

    dev_paths = [
        Path("/dev/input/by-path/platform-tuxedo_keyboard-event"),
    ]
    # Fallback to search /dev/input
    if not dev_paths[0].exists():
        for p in Path("/dev/input/by-path").glob("*tuxedo_keyboard*"):
            dev_paths.append(p)

    target_dev = None
    for p in dev_paths:
        if p.exists():
            target_dev = p
            break

    if not target_dev:
        print("错误: 找不到 tuxedo-keyboard 物理按键事件输入节点", file=sys.stderr)
        sys.exit(1)

    if ec_only:
        print(f"[*] MECHREVO EC-only 热键守护进程启动，监听设备: {target_dev}")
        # Fail fast when the kernel control node is absent; systemd restarts us
        # after the module/device appears.
        initial_mode = read_hardware_mode()
        print(f"[*] 当前 EC 模式字节: 0x{initial_mode:02x}（不依赖 tccd）")
        try:
            uefi_mode = read_uefi_power_mode()
        except Exception as exc:
            print(f"[!] UEFI PowerMode 读取失败: {exc}", file=sys.stderr)
        else:
            print(f"[*] 当前 UEFI PowerMode: {uefi_mode}")
            mode_name = EC_MODE_NAMES.get(initial_mode)
            expected_uefi = UEFI_POWER_MODE_VALUES.get(mode_name)
            if expected_uefi is not None and uefi_mode != expected_uefi:
                print(
                    f"[!] 启动状态不一致: EC {mode_name} 期望 UEFI {expected_uefi}，"
                    f"实际 {uefi_mode}；按一次模式键会重新同步",
                    file=sys.stderr,
                )
        last_profile_id = None
    else:
        print(f"[*] 机械革命硬件热键守护进程已启动，监听设备: {target_dev}")
        sync_oem_profiles()
        last_profile_id = sync_mode_led_from_profile()

    last_mode_trigger = 0.0
    last_fn_trigger = 0.0
    last_tp_trigger = 0.0
    last_kbl_trigger = 0.0

    with open(target_dev, "rb", buffering=0) as f:
        # struct input_event: timeval (16B), type (2B), code (2B), value (4B) -> 24B on 64-bit
        event_format = "qqHHi"
        event_size = struct.calcsize(event_format)

        while True:
            ready, _, _ = select.select([f], [], [], 1.0)
            if not ready:
                if ec_only:
                    continue
                current_profile_id = get_current_mode_info()[1]
                if current_profile_id != last_profile_id:
                    last_profile_id = sync_mode_led_from_profile(current_profile_id)
                continue
            data = f.read(event_size)
            if not data:
                raise RuntimeError(f"Hotkey input device disconnected: {target_dev}")
            if len(data) != event_size:
                raise RuntimeError(f"Incomplete hotkey input event: expected {event_size} bytes, got {len(data)}")
            _, _, ev_type, ev_code, ev_value = struct.unpack(event_format, data)
            # EV_KEY = 1, ev_value == 1 (key press)
            if ev_type == 1 and ev_value == 1:
                now = time.monotonic()
                # 1. Physical mode switch key (KEY_F6 = 64)
                if ev_code == 64:
                    if now - last_mode_trigger >= 0.35:  # 350ms debounce
                        last_mode_trigger = now
                        if ec_only:
                            previous_mode = read_hardware_mode()
                            mode = cycle_hardware_mode()
                            print(f"[*] 实体模式键 -> EC 模式 {mode}")
                            try:
                                tdp = apply_mode_tdp(mode)
                            except Exception as exc:
                                print(f"[!] TDP profile apply failed: {exc}", file=sys.stderr)
                                try:
                                    restored = write_hardware_mode(previous_mode)
                                except Exception as rollback:
                                    print(
                                        f"[!] EC 模式回滚失败: {rollback}",
                                        file=sys.stderr,
                                    )
                                else:
                                    print(
                                        f"[!] 已回滚 EC 模式到 0x{restored:02x}；"
                                        "本次不写 UEFI",
                                        file=sys.stderr,
                                    )
                                continue
                            print(f"[*] PL1/PL2/PL4 -> {tdp[0]}/{tdp[1]}/{tdp[2]} W")
                            try:
                                uefi_mode = write_uefi_power_mode(mode)
                            except Exception as exc:
                                print(f"[!] UEFI PowerMode 同步失败: {exc}", file=sys.stderr)
                            else:
                                print(f"[*] UEFI PowerMode -> {uefi_mode}")
                        else:
                            print("[*] 捕捉到机身实体模式按键触发！执行模式切换...")
                            cycle_mode(notify=True)
                            last_profile_id = sync_mode_led_from_profile()

                elif ec_only:
                    # The root EC-only service must not duplicate the user
                    # daemon's Fn-lock/touchpad/backlight actions.
                    continue

                # 2. Fn Lock toggle key (KEY_FN_ESC = 465)
                elif ev_code == 465:
                    if now - last_fn_trigger >= 0.35:
                        last_fn_trigger = now
                        print("[*] 捕捉到 Fn+Esc (Fn 模式锁) 物理组合键触发！执行切换...")
                        toggle_fn_lock(notify=True)

                # 3. Touchpad toggle key (KEY_F21 = 191)
                elif ev_code == 191:
                    if now - last_tp_trigger >= 0.4:
                        last_tp_trigger = now
                        print("[*] 捕捉到触控板硬件切换键 (KEY_F21) 触发！执行触控板开关...")
                        toggle_touchpad()

                # 4. Keyboard backlight keys (KEY_KBDILLUMTOGGLE = 228, KEY_KBDILLUMDOWN = 229, KEY_KBDILLUMUP = 230)
                elif ev_code == 228:
                    if now - last_kbl_trigger >= 0.2:
                        last_kbl_trigger = now
                        if shutil.which("omarchy-brightness-keyboard"):
                            run_cmd(["omarchy-brightness-keyboard", "cycle"])
                        else:
                            raise RuntimeError("找不到 omarchy-brightness-keyboard")
                elif ev_code == 229:
                    if now - last_kbl_trigger >= 0.1:
                        last_kbl_trigger = now
                        if shutil.which("omarchy-brightness-keyboard"):
                            run_cmd(["omarchy-brightness-keyboard", "down"])
                        else:
                            raise RuntimeError("找不到 omarchy-brightness-keyboard")
                elif ev_code == 230:
                    if now - last_kbl_trigger >= 0.1:
                        last_kbl_trigger = now
                        if shutil.which("omarchy-brightness-keyboard"):
                            run_cmd(["omarchy-brightness-keyboard", "up"])
                        else:
                            raise RuntimeError("找不到 omarchy-brightness-keyboard")


# ==============================================================================
# 2. Fan Boost / One-Click Full Speed
# ==============================================================================

def set_fan(action: str) -> None:
    """Control cooling fans (auto, boost, quiet)."""
    if action == "boost":
        set_mode("boost")
        print("[✓] 机械革命一键强冷 (Fan Boost) 已激活：双风扇已拉至 100% 满速强冷！")
    elif action == "auto":
        set_mode("gaming")
        print("[✓] 已恢复机械革命游戏智能温控自动模式。")
    elif action == "quiet":
        set_mode("office")
        print("[✓] 已切换至机械革命静音办公风扇模式。")
    else:
        raise ValueError(f"Unknown fan action '{action}'. Valid: auto, boost, quiet")


# ==============================================================================
# 3. Win Key Lock (电竞游戏防误触锁)
# ==============================================================================

def get_win_lock() -> bool:
    """Check if Win Key Lock is enabled."""
    f = get_state_file("win_lock")
    if f.exists():
        return f.read_text().strip() == "1"
    return False


def set_win_lock(enabled: bool) -> None:
    """Enable or disable Win Key lock via hardware AT scancode mapping."""
    # e05b is the scancode for Left Super/Windows key
    # 0 = disabled (no event emitted), 125 = KEY_LEFTMETA (standard)
    keycode = "0" if enabled else "125"
    run_cmd(["setkeycodes", "e05b", keycode])
    get_state_file("win_lock").write_text("1" if enabled else "0")
    state_str = "已锁定 (防误触生效，按 Win 键无响应)" if enabled else "已解锁 (正常使用)"
    print(f"[✓] 机械革命 Win 键防误触锁: {state_str}")


# ==============================================================================
# 4. Touchpad Hardware Lock
# ==============================================================================

def get_touchpad() -> bool:
    """Check if touchpad is enabled (device bound)."""
    if not TOUCHPAD_BOUND_CHECK.parent.exists():
        raise RuntimeError(f"Touchpad binding interface is unavailable: {TOUCHPAD_BOUND_CHECK.parent}")
    return TOUCHPAD_BOUND_CHECK.exists()


def set_touchpad(enabled: bool) -> None:
    """Enable or disable touchpad via I2C driver bind/unbind."""
    current = get_touchpad()
    if enabled and not current:
        if not TOUCHPAD_BIND_PATH.exists():
            raise RuntimeError(f"Touchpad bind interface is unavailable: {TOUCHPAD_BIND_PATH}")
        TOUCHPAD_BIND_PATH.write_text(TOUCHPAD_I2C_DEVICE)
    elif not enabled and current:
        if not TOUCHPAD_UNBIND_PATH.exists():
            raise RuntimeError(f"Touchpad unbind interface is unavailable: {TOUCHPAD_UNBIND_PATH}")
        TOUCHPAD_UNBIND_PATH.write_text(TOUCHPAD_I2C_DEVICE)
    actual = get_touchpad()
    if actual != enabled:
        raise RuntimeError(f"触控板状态回读不匹配: requested {enabled}, got {actual}")
    get_state_file("touchpad_state").write_text("1" if enabled else "0")
    state_str = "已开启 (正常滑动)" if enabled else "已锁定禁用 (防误触生效)"
    print(f"[✓] 机械革命触控板状态: {state_str}")


def restore_touchpad_state(timeout: float = 30.0) -> bool | None:
    """Reapply the saved hardware touchpad state after resume.

    Returns None when no state was saved. The i2c device may appear a moment
    after resume, so wait for it before bind/unbind; otherwise a late device
    registration could silently undo the saved off state.
    """
    state_file = get_state_file("touchpad_state")
    if not state_file.exists():
        return None
    value = state_file.read_text().strip()
    if value not in {"0", "1"}:
        raise RuntimeError(f"Invalid saved touchpad state: {value!r}")
    enabled = value == "1"
    deadline = time.monotonic() + timeout
    while not TOUCHPAD_DEVICE_PATH.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Touchpad device did not reappear: {TOUCHPAD_DEVICE_PATH}")
        time.sleep(0.25)
    set_touchpad(enabled)
    return enabled


# ==============================================================================
# 5. Fn Lock
# ==============================================================================

def get_fn_lock() -> bool:
    """Check if Fn Lock is enabled."""
    if not FN_LOCK_PATH.exists():
        raise RuntimeError("Fn lock sysfs interface not available on this platform")
    value = FN_LOCK_PATH.read_text().strip()
    if value not in {"0", "1"}:
        raise RuntimeError(f"Invalid Fn lock state: {value!r}")
    return value == "1"


def set_fn_lock(enabled: bool, notify: bool = True) -> None:
    """Enable or disable Fn Lock."""
    if not FN_LOCK_PATH.exists():
        raise RuntimeError("Fn lock sysfs interface not available on this platform.")
    val_str = "1" if enabled else "0"
    try:
        FN_LOCK_PATH.write_text(val_str)
    except OSError as exc:
        raise RuntimeError(f"写入 Fn lock 失败: {exc}") from exc
    actual = FN_LOCK_PATH.read_text().strip()
    if actual != val_str:
        raise RuntimeError(f"Fn lock 回读不匹配: requested {val_str}, got {actual!r}")

    # 1 = Multimedia priority, 0 = Standard F1-F12 priority
    mode_name = "多媒体快捷键优先" if enabled else "标准功能键优先 (F1-F12)"
    desc = "直接按 F1-F12 调节音量/亮度/触控板，按 Fn+Fx 触发标准功能键" if enabled else "直接按 F1-F12 触发标准功能键，按 Fn+Fx 调节多媒体"
    if shutil.which("omarchy-osd"):
        run_cmd(["omarchy-osd", "-i", "keyboard", "-m", f"Fn 锁定: {'已开启 (多媒体)' if enabled else '已关闭 (F1-F12)'}"])

    if notify:
        send_notification("★ 机械革命键盘 ★", f"Fn 键模式已切换为：\n【{mode_name}】\n{desc}")
    print(f"[✓] 机械革命 Fn 快捷键模式: {mode_name} ({desc})")


def toggle_fn_lock(notify: bool = True) -> bool:
    """Toggle Fn Lock state."""
    new_state = not get_fn_lock()
    set_fn_lock(new_state, notify=notify)
    return new_state



# ==============================================================================
# 6. Battery Health Care (3-Stage Charging)
# ==============================================================================

def get_battery_profile() -> str:
    """Get current battery charging profile."""
    if not BATTERY_PROFILE_PATH.exists():
        raise RuntimeError(f"Battery profile sysfs interface is unavailable: {BATTERY_PROFILE_PATH}")
    value = BATTERY_PROFILE_PATH.read_text().strip()
    if not value:
        raise RuntimeError("Battery profile sysfs returned an empty value")
    return value


def set_battery_profile(profile: str) -> None:
    """Set battery profile: high (100%), balanced (80%), stationary (60%)."""
    mapping = {
        "high": "high_capacity",
        "high_capacity": "high_capacity",
        "balanced": "balanced",
        "stationary": "stationary",
        "long_life": "stationary",
    }
    p_key = profile.lower().strip()
    if p_key not in mapping:
        raise ValueError(f"Unknown battery profile '{profile}'. Valid: high, balanced, stationary")

    target = mapping[p_key]
    if not BATTERY_PROFILE_PATH.exists():
        raise RuntimeError(f"Battery profile sysfs interface is unavailable: {BATTERY_PROFILE_PATH}")
    call_tccd_dbus("SetChargingProfile", "s", target)
    BATTERY_PROFILE_PATH.write_text(target)
    actual = BATTERY_PROFILE_PATH.read_text().strip()
    if actual != target:
        raise RuntimeError(f"电池档位回读不匹配: requested {target}, got {actual!r}")
    desc = {
        "high_capacity": "高容量模式 (充电至 100%)",
        "balanced": "平衡保养模式 (限充 80%)",
        "stationary": "长寿命保护模式 (限充 60%)",
    }[target]
    print(f"[✓] 机械革命电池健康保养模式: {desc}")


# ==============================================================================
# 7. RGB Keyboard Lighting
# ==============================================================================

def set_rgb(color_hex: str, brightness: int | None = None) -> None:
    """Set keyboard RGB color and brightness."""
    # Preset colors
    presets = {
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 100, 255),
        "cyan": (0, 220, 220),
        "magenta": (255, 0, 200),
        "yellow": (255, 200, 0),
        "white": (255, 255, 255),
        "orange": (255, 100, 0),
        "purple": (160, 32, 240),
        "ice": (120, 200, 255),
    }

    c_key = color_hex.lower().lstrip("#")
    if c_key in presets:
        r, g, b = presets[c_key]
    elif len(c_key) == 6:
        r = int(c_key[0:2], 16)
        g = int(c_key[2:4], 16)
        b = int(c_key[4:6], 16)
    else:
        raise ValueError(f"Invalid color '{color_hex}'. Use HEX code (e.g. ff0000) or preset: {', '.join(presets.keys())}")

    multi_intensity_path = RGB_LEDS_DIR / "multi_intensity"
    brightness_path = RGB_LEDS_DIR / "brightness"

    if not multi_intensity_path.exists():
        raise RuntimeError(f"键盘 RGB 接口不可用: {multi_intensity_path}")
    multi_intensity_path.write_text(f"{r} {g} {b}\n")
    actual_color = multi_intensity_path.read_text().strip()
    if actual_color != f"{r} {g} {b}":
        raise RuntimeError(f"键盘 RGB 回读不匹配: requested {r} {g} {b}, got {actual_color!r}")

    if brightness is not None:
        if not brightness_path.exists():
            raise RuntimeError(f"键盘亮度接口不可用: {brightness_path}")
        b_val = max(0, min(3, int(brightness)))
        brightness_path.write_text(f"{b_val}\n")
        actual_brightness = brightness_path.read_text().strip()
        if actual_brightness != str(b_val):
            raise RuntimeError(f"键盘亮度回读不匹配: requested {b_val}, got {actual_brightness!r}")

    print(f"[✓] 机械革命单区 RGB 灯效已更新: RGB({r}, {g}, {b})" + (f", 亮度: {brightness}/3" if brightness is not None else ""))


def apply_display_color(temp_k: int | None = None, gamma: float | None = None, is_identity: bool = False) -> None:
    """Apply screen color calibration safely (avoiding NVIDIA CTM grey screen)."""
    # X11 via xrandr
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("屏幕色彩设置需要 X11 DISPLAY")
    if not shutil.which("xrandr"):
        raise RuntimeError("找不到 xrandr，无法设置屏幕色彩")
    g_str = f"{gamma:.2f}:{gamma:.2f}:{gamma:.2f}" if gamma else "1.0:1.0:1.0"
    run_cmd(["xrandr", "--output", "eDP-1", "--gamma", g_str])


def set_screen_color_mode(mode_name: str, notify: bool = True) -> None:
    """Set screen color preset (standard, eyecare, gaming, movie)."""
    profiles = {
        "standard": {
            "name": "原彩标准模式 (Standard)",
            "desc": "标准 sRGB 还原 | 6500K 纯正色温 | Gamma 1.0",
            "temp": 6500,
            "gamma": 1.0,
            "identity": True,
        },
        "eyecare": {
            "name": "护眼防蓝光模式 (Eye Care)",
            "desc": "温润滤蓝光 | 4500K 暖色温 | 降低视觉疲劳",
            "temp": 4500,
            "gamma": 1.0,
            "identity": False,
        },
        "gaming": {
            "name": "电竞色彩增强模式 (Gaming)",
            "desc": "电竞暗部提亮 | 6800K 高清晰色温 | Gamma 1.15",
            "temp": 6800,
            "gamma": 1.15,
            "identity": False,
        },
        "movie": {
            "name": "影音沉浸模式 (Movie)",
            "desc": "高对比浓郁色彩 | 6000K 影视色温 | Gamma 1.05",
            "temp": 6000,
            "gamma": 1.05,
            "identity": False,
        },
    }

    m_key = mode_name.lower().strip()
    if m_key not in profiles:
        raise ValueError(f"Unknown color mode '{mode_name}'. Valid: {', '.join(profiles.keys())}")

    p = profiles[m_key]
    apply_display_color(temp_k=p["temp"], gamma=p["gamma"], is_identity=p["identity"])
    get_state_file("color_profile").write_text(m_key)
    if notify:
        send_notification("★ 机械革命电竞控制台 ★", f"屏幕色彩已切换为：【{p['name']}】\n{p['desc']}", icon="video-display")
    print(f"[✓] 机械革命屏幕色彩调教: {p['name']} ({p['desc']})")


def get_screen_color_mode() -> str:
    """Get current screen color profile."""
    f = get_state_file("color_profile")
    if f.exists():
        c_id = f.read_text().strip()
        names = {
            "standard": "原彩标准模式 (6500K)",
            "eyecare": "护眼防蓝光模式 (4500K)",
            "gaming": "电竞色彩增强模式 (6800K)",
            "movie": "影音沉浸模式 (6000K)",
        }
        return names.get(c_id, c_id)
    return "原彩标准模式 (Standard)"


def set_screen_brightness(percent_str: str) -> None:
    """Set screen display brightness using brightnessctl."""
    val = percent_str.strip().rstrip("%")
    try:
        p_val = max(1, min(100, int(val)))
        run_cmd(["brightnessctl", "set", f"{p_val}%"])
        print(f"[✓] 屏幕显示亮度已设置为: {p_val}%")
    except Exception as e:
        raise RuntimeError(f"设置亮度失败: {e}")


# ==============================================================================
# 9. Real-Time Telemetry & Dashboard
# ==============================================================================

def read_hwmon_sensors() -> dict:
    """Read temperatures and fan RPM from mechrevo_ec_sensors and coretemp."""
    data = {"cpu_temp": "N/A", "gpu_temp": "N/A", "fan1_rpm": "N/A", "fan2_rpm": "N/A"}
    hwmon_base = Path("/sys/class/hwmon")
    if hwmon_base.exists():
        for hw in hwmon_base.glob("hwmon*"):
            name_file = hw / "name"
            if name_file.exists():
                name = name_file.read_text().strip()
                if name in ("mechrevo_ec", "mechrevo_ec_sensors"):
                    # fan1: CPU fan, fan2: GPU fan
                    f1 = hw / "fan1_input"
                    f2 = hw / "fan2_input"
                    t1 = hw / "temp1_input"
                    t2 = hw / "temp2_input"
                    if f1.exists():
                        data["fan1_rpm"] = f1.read_text().strip()
                    if f2.exists():
                        data["fan2_rpm"] = f2.read_text().strip()
                    if t1.exists():
                        data["cpu_temp"] = f"{int(t1.read_text().strip()) / 1000:.1f} °C"
                    if t2.exists():
                        data["gpu_temp"] = f"{int(t2.read_text().strip()) / 1000:.1f} °C"
                elif name == "coretemp" and data["cpu_temp"] == "N/A":
                    pkg = hw / "temp1_input"
                    if pkg.exists():
                        data["cpu_temp"] = f"{int(pkg.read_text().strip()) / 1000:.1f} °C"
    return data


def show_dashboard() -> None:
    """Display modern Mechrevo Gaming Center status card."""
    sensors = read_hwmon_sensors()
    mode = get_current_mode()
    win_lock = "已锁定 (防误触)" if get_win_lock() else "未锁定 (正常)"
    touchpad = "已启用" if get_touchpad() else "已禁用"
    fn_lock = "F1-F12 优先" if get_fn_lock() else "多媒体快捷键优先"
    battery = {
        "high_capacity": "100% 高容量模式",
        "balanced": "80% 平衡保养模式",
        "stationary": "60% 长寿保护模式",
    }.get(get_battery_profile(), get_battery_profile())

    color_mode = get_screen_color_mode()

    card = f"""
===================================================================
        ★ 机械革命电竞控制台 (MECHREVO Gaming Center) ★
===================================================================
【运行性能模式】:  {mode}
【屏幕色彩调教】:  {color_mode}
【系统散热监控】:
  • CPU 核心温度:  {sensors['cpu_temp']}
  • GPU 核心温度:  {sensors['gpu_temp']}
  • CPU 散热风扇:  {sensors['fan1_rpm']} RPM
  • 独显散热风扇:  {sensors['fan2_rpm']} RPM

【电竞专属开关】:
  • Win 键防误触:  {win_lock}
  • 笔记本触控板:  {touchpad}
  • Fn 键锁定状态: {fn_lock}
  • 电池健康保养:  {battery}
===================================================================
提示:
  切换模式:  mechrevo-control mode [office|gaming|turbo|cycle]
  屏幕调色:  mechrevo-control color [standard|eyecare|gaming|movie]
  屏幕亮度:  mechrevo-control brightness [10-100%]
  一键强冷:  mechrevo-control fan boost (恢复: fan auto)
  防误触锁:  mechrevo-control win-lock [on|off|toggle]
  触控板锁:  mechrevo-control touchpad [on|off|toggle]
  背光调节:  mechrevo-control rgb [cyan|red|blue|#HEX] [0-3]
===================================================================
"""
    print(card)


def main() -> int:
    parser = argparse.ArgumentParser(description="机械革命电竞控制台 Linux 核心管理工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # mode
    p_mode = subparsers.add_parser("mode", help="切换或查看运行模式 (gaming, gaming-quiet, turbo, office, boost, cycle)")
    p_mode.add_argument("target", nargs="?", choices=["office", "gaming", "gaming-quiet", "turbo", "boost", "cycle"], help="目标模式")
    p_mode.add_argument("--notify", action="store_true", help="发送桌面通知")

    # color
    p_color = subparsers.add_parser("color", help="屏幕色彩调教 (standard, eyecare, gaming, movie)")
    p_color.add_argument("target", nargs="?", choices=["standard", "eyecare", "gaming", "movie"], help="色彩预设")

    # brightness
    p_bright = subparsers.add_parser("brightness", help="屏幕显示亮度设置 (1-100%%)")
    p_bright.add_argument("percent", help="亮度百分比 (例如 80%% 或 80)")

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="启动机身模式物理按键监听守护进程")
    p_daemon.add_argument(
        "--ec-only",
        action="store_true",
        help="不依赖 tccd，直接用 /dev/tuxedo_io 切换 EC 模式（需要 root；供系统服务使用）",
    )

    # fan
    p_fan = subparsers.add_parser("fan", help="风扇控制 (auto, boost, quiet)")
    p_fan.add_argument("action", choices=["auto", "boost", "quiet"], help="风扇操作")

    # win-lock
    p_win = subparsers.add_parser("win-lock", help="Win 键防误触锁控制")
    p_win.add_argument("action", nargs="?", choices=["on", "off", "toggle", "status"], default="status")

    # touchpad
    p_tp = subparsers.add_parser("touchpad", help="笔记本触控板硬件开关")
    p_tp.add_argument("action", nargs="?", choices=["on", "off", "toggle", "status", "restore"], default="status")

    # fn-lock
    p_fn = subparsers.add_parser("fn-lock", help="Fn 快捷键锁控制")
    p_fn.add_argument("action", nargs="?", choices=["on", "off", "toggle", "status"], default="status")

    # battery
    p_bat = subparsers.add_parser("battery", help="电池健康保养模式 (high, balanced, stationary)")
    p_bat.add_argument("profile", nargs="?", choices=["high", "balanced", "stationary"], help="保养模式")

    # rgb
    p_rgb = subparsers.add_parser("rgb", help="键盘 RGB 背光与亮度调节")
    p_rgb.add_argument("color", help="RGB 十六进制颜色代码或预设名称 (red, cyan, blue, etc.)")
    p_rgb.add_argument("brightness", nargs="?", type=int, choices=[0, 1, 2, 3], help="背光亮度 (0-3)")

    # status / dashboard
    subparsers.add_parser("status", help="查看电竞控制台系统仪表盘")

    # sync
    subparsers.add_parser("sync-profiles", help="向控制中心注入机械革命原厂 Profiles")

    args = parser.parse_args()

    if not args.command or args.command == "status":
        show_dashboard()
        return 0

    try:
        if args.command == "mode":
            if args.target == "cycle":
                cycle_mode(notify=True)
            elif args.target:
                set_mode(args.target, notify=args.notify)
            else:
                print(f"当前运行模式: {get_current_mode()}")
        elif args.command == "color":
            if args.target:
                set_screen_color_mode(args.target, notify=True)
            else:
                print(f"当前屏幕色彩模式: {get_screen_color_mode()}")
        elif args.command == "brightness":
            set_screen_brightness(args.percent)
        elif args.command == "daemon":
            run_daemon(ec_only=args.ec_only)
        elif args.command == "fan":
            set_fan(args.action)
        elif args.command == "win-lock":
            if args.action == "on":
                set_win_lock(True)
            elif args.action == "off":
                set_win_lock(False)
            elif args.action == "toggle":
                set_win_lock(not get_win_lock())
            else:
                print(f"Win 键锁状态: {'已锁定 (防误触生效)' if get_win_lock() else '未锁定 (正常)'}")
        elif args.command == "touchpad":
            if args.action == "on":
                set_touchpad(True)
            elif args.action == "off":
                set_touchpad(False)
            elif args.action == "toggle":
                set_touchpad(not get_touchpad())
            elif args.action == "restore":
                restored = restore_touchpad_state()
                if restored is None:
                    print("没有保存的触控板硬件状态，跳过恢复")
                else:
                    print(f"已恢复触控板硬件状态: {'开启' if restored else '禁用'}")
            else:
                print(f"触控板状态: {'已启用' if get_touchpad() else '已禁用'}")
        elif args.command == "fn-lock":
            if args.action == "on":
                set_fn_lock(True, notify=True)
            elif args.action == "off":
                set_fn_lock(False, notify=True)
            elif args.action == "toggle":
                toggle_fn_lock(notify=True)
            else:
                mode = "多媒体快捷键优先" if get_fn_lock() else "标准功能键优先 (F1-F12)"
                print(f"Fn 键模式: {mode}")
        elif args.command == "battery":
            if args.profile:
                set_battery_profile(args.profile)
            else:
                print(f"当前电池保养模式: {get_battery_profile()}")
        elif args.command == "rgb":
            set_rgb(args.color, args.brightness)
        elif args.command == "sync-profiles":
            sync_oem_profiles()
            print("[✓] 机械革命原厂 Profiles 已成功注入 /etc/tcc/profiles")
        return 0
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
