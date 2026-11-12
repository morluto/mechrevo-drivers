#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, opt-in RAPL PL1 control for the qualified GM6PX0X host.

The XML changes thermald's cooling-device bounds; apply performs at most one
downward PL1 write per interface. This is not a competing power-control loop.
"""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET


XML = "/etc/thermald/mechrevo-power.xml"
DROPIN = "/etc/systemd/system/thermald.service.d/60-mechrevo-power.conf"
STATE = "/var/lib/mechrevo-power/state.json"
RECEIPTS = "/var/lib/mechrevo-power/receipts"
LOCK = "/run/lock/mechrevo-power.lock"
STOCK_UNIT = "/usr/lib/systemd/system/thermald.service"
FEATURES = "/etc/thermald/thermald-features.xml"
PREF = "/run/thermald/thd_preference.conf"
BACKUP_ROOT = "/home/lightjunction/Backups/projects/mechrevo-drivers/light/rapl-power-control"
STOCK_EXEC_START = "/usr/bin/thermald --systemd --dbus-enable --adaptive"
MANAGED_EXEC_START = "/usr/bin/thermald --systemd --dbus-enable --config-file " + XML
ZONES = ("/sys/class/powercap/intel-rapl:0", "/sys/class/powercap/intel-rapl-mmio:0")
PPCC_PATHS = (
    "/sys/bus/pci/devices/0000:00:04.0/power_limits",
    "/sys/bus/pci/devices/0000:00:0b.0/power_limits",
    "/sys/bus/platform/devices/INT3401:00/power_limits",
)
TCC_PATHS = tuple(p.rsplit("/", 1)[0] + "/tcc_offset_degree_celsius" for p in PPCC_PATHS[:2])
FOREIGN_CONFIGS = (
    "/etc/thermald/thermal-conf.xml", "/etc/thermald/thermal-conf.xml.auto",
    "/run/thermald/thermal-conf.xml", "/run/thermald/thermal-conf.xml.auto",
)
IDENTITY = {"sys_vendor": "MECHREVO", "product_name": "Kuangshi16Pro Series GM6PX0X",
            "bios_version": "N.1.09MRO07"}
CPU_MODEL = "12th Gen Intel(R) Core(TM) i9-12900HX"
QUALIFIED_THERMALD_SHA256 = "fbe6b27d2854fa8636c7bbdbcc953d1665a2c3b23534026dd42d68a2ffa8c767"
# RAPL's max_power field is the CPU thermal-spec reference, not a minimum
# writable limit. Keep host qualification separate from the user cap range.
THERMAL_SPEC_POWER_UW = 55_000_000
MIN_LIMIT_UW = 35_000_000
# A zero hysteresis made the qualified 90 C trip point chatter under a
# fluctuating workload: thermald repeatedly dropped PL1 to the floor and
# released it on the next one-second sample. Keep the qualified trip point,
# but require the package to cool 3 C before releasing the thermal clamp.
THERMAL_HYSTERESIS_MILLICELSIUS = 3_000
CPU_COOLING_DEVICES = ("rapl_controller", "intel_pstate", "intel_powerclamp", "cpufreq", "Processor")
CPU_TARGET_OVERRIDES = ("/run/thermald/thd_user_psv_temp.cpu.conf",
                        "/run/thermald/thd_user_set_max.cpu.conf")
CPU_COOLING_ORDER = "/etc/thermald/thermal-cpu-cdev-order.xml"


class PowerError(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def temperature_target(target):
    if target is not None and (type(target) is not int or target != 90):
        raise ValueError("Only the qualified optional 90 Celsius passive target is supported")


def polling_target(polling_seconds, target_celsius):
    if polling_seconds is not None and (type(polling_seconds) is not int
                                       or polling_seconds != 1 or target_celsius != 90):
        raise ValueError("Optional 1 second polling requires the qualified 90 Celsius passive target")


def rapl_debounce_target(seconds, target_celsius, polling_seconds):
    if seconds is not None and (type(seconds) is not int or seconds != 0
                                or type(target_celsius) is not int or target_celsius != 90
                                or type(polling_seconds) is not int or polling_seconds != 1):
        raise ValueError("Optional zero RAPL debounce requires explicit 90 Celsius target and 1 second polling")


def managed_exec_start(target_celsius=None):
    temperature_target(target_celsius)
    return MANAGED_EXEC_START + (" --loglevel=info" if target_celsius is not None else "")


class Environment:
    """Dependency boundary. CLI always uses the real system, never --root."""

    def __init__(self, root=Path("/"), runner=None, uid=None, owner_uid=0,
                 clock=time.time, sleeper=time.sleep):
        self.root = Path(root).resolve()
        self.runner = runner or self._run
        self.uid = os.geteuid() if uid is None else uid
        self.owner_uid = owner_uid
        self.clock = clock
        self.sleeper = sleeper

    @staticmethod
    def _run(argv):
        return subprocess.run(argv, text=True, capture_output=True, timeout=45)

    def path(self, logical):
        if not str(logical).startswith("/") or ".." in Path(logical).parts:
            raise PowerError("Invalid system path")
        return self.root / str(logical).lstrip("/")

    def command(self, *argv):
        try:
            result = self.runner(list(argv))
        except (OSError, subprocess.SubprocessError) as exc:
            raise PowerError(f"Command failed: {' '.join(argv)}: {exc}") from exc
        if result.returncode:
            raise PowerError(f"Command failed: {' '.join(argv)}: {result.stderr.strip()}")
        return result.stdout.strip()

    def read_control(self, logical):
        try:
            return self.path(logical).read_text().strip()
        except OSError as exc:
            raise PowerError(f"Cannot read {logical}: {exc}") from exc

    def read_package_temperature(self):
        """One native package sensor sample; diagnostic only, never a cooling guarantee."""
        start = time.monotonic_ns()
        devices = self.path("/sys/devices")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW

        def identity(info):
            return {"device": info.st_dev, "inode": info.st_ino,
                    "mode": info.st_mode, "uid": info.st_uid, "gid": info.st_gid}

        @contextmanager
        def directory(path):
            descriptors, parents = [], []
            try:
                parent = None
                parts = path.relative_to(self.root).parts
                for index, part in enumerate((str(self.root),) + parts):
                    fd = os.open(part, directory_flags, dir_fd=parent)
                    descriptors.append(fd)
                    logical = self.root.joinpath(*parts[:index])
                    parents.append((logical, identity(os.fstat(fd))))
                    parent = fd
                yield parent
                for logical, expected in parents:
                    if identity(logical.lstat()) != expected:
                        raise PowerError("CPU package sensor parent identity changed")
            finally:
                errors = []
                for fd in reversed(descriptors):
                    try:
                        os.close(fd)
                    except OSError as exc:
                        errors.append(str(exc))
                if errors:
                    raise PowerError("CPU package sensor directory close failed: " + "; ".join(errors))

        def read(parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode):
                    raise PowerError("CPU package sensor control is not a regular file")
                raw = bytearray()
                while len(raw) <= 64:
                    chunk = os.read(fd, 65 - len(raw))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if len(raw) > 64:
                    raise PowerError("CPU package sensor control exceeds read bound")
                expected = identity(before)
                if (identity(os.fstat(fd)) != expected
                        or identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected):
                    raise PowerError("CPU package sensor control identity changed")
                return bytes(raw).decode("ascii").strip(), expected
            finally:
                os.close(fd)

        def discover():
            sensors = []
            candidates = list(self.path("/sys/class/thermal").glob("thermal_zone*"))
            if len(candidates) > 64:
                raise PowerError("CPU package sensor discovery exceeds bound")
            for candidate in candidates:
                if not re.fullmatch(r"thermal_zone[0-9]+", candidate.name):
                    raise PowerError("Unqualified CPU package sensor class path")
                class_identity = identity(candidate.lstat())
                physical = candidate.resolve(strict=True)
                if not physical.is_relative_to(devices) or physical == devices:
                    raise PowerError("CPU package sensor must resolve within /sys/devices")
                with directory(physical) as parent:
                    sensor_type, type_identity = read(parent, "type")
                    if sensor_type == "x86_pkg_temp":
                        sensors.append((candidate, physical, identity(os.fstat(parent)), type_identity, class_identity))
                if identity(candidate.lstat()) != class_identity or candidate.resolve(strict=True) != physical:
                    raise PowerError("CPU package sensor class identity changed")
            if len(sensors) != 1:
                raise PowerError("Exactly one diagnostic x86_pkg_temp sensor is required")
            return sensors[0]

        try:
            selected = discover()
            candidate, physical, directory_identity, type_identity, class_identity = selected
            with directory(physical) as parent:
                if identity(os.fstat(parent)) != directory_identity:
                    raise PowerError("CPU package sensor directory identity changed")
                sensor_type, current_type_identity = read(parent, "type")
                if sensor_type != "x86_pkg_temp" or current_type_identity != type_identity:
                    raise PowerError("CPU package sensor type identity changed")
                value, temp_identity = read(parent, "temp")
                if not re.fullmatch(r"[0-9]+", value) or not 0 <= int(value) <= 125_000:
                    raise PowerError("CPU package temperature is outside its 0..125000 diagnostic range")
                if discover() != selected:
                    raise PowerError("CPU package sensor selection changed during read")
                if identity(os.stat("temp", dir_fd=parent, follow_symlinks=False)) != temp_identity:
                    raise PowerError("CPU package temperature control replaced during read")
            end = time.monotonic_ns()
            if type(start) is not int or type(end) is not int or not 0 <= start <= end:
                raise PowerError("CPU package temperature monotonic read window is invalid")
            return {"millicelsius": int(value), "read_window_ns": [start, end],
                    "sensor_identity": {"type": "x86_pkg_temp",
                        "class_path": "/" + str(candidate.relative_to(self.root)),
                        "device_path": "/" + str(physical.relative_to(self.root)),
                        "directory": directory_identity, "class_entry": class_identity, "type_file": type_identity,
                        "temp_file": temp_identity}}
        except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
            if isinstance(exc, PowerError):
                raise
            raise PowerError("CPU package temperature diagnostic failed: " + str(exc)) from exc

    def read_temperature_target(self):
        """Read the qualified CPU0 reference; never load MSR support or write it.

        Alder Lake's offset is six bits and only present with PLATFORM_INFO[30].
        Linux v6.12 turbostat documents both the capability and field decoding:
        https://github.com/torvalds/linux/blob/v6.12/tools/power/x86/turbostat/turbostat.c
        """
        if {key: self.read_control("/sys/class/dmi/id/" + key) for key in IDENTITY} != IDENTITY:
            raise PowerError("Temperature target: unqualified machine or BIOS")
        cpu0 = []
        for block in self.read_control("/proc/cpuinfo").split("\n\n"):
            row = {}
            for line in block.splitlines():
                key, separator, value = line.partition(":")
                if separator:
                    key = key.strip()
                    if key in row:
                        raise PowerError("Temperature target: ambiguous CPU capability record")
                    row[key] = value.strip()
            if row.get("processor") == "0":
                cpu0.append(row)
        if len(cpu0) != 1:
            raise PowerError("Temperature target: cannot identify CPU0 capabilities")
        row = cpu0[0]
        if (row.get("vendor_id") != "GenuineIntel" or row.get("cpu family") != "6"
                or row.get("model") != "151" or row.get("model name") != CPU_MODEL
                or int(row.get("cpuid level", "0")) < 6
                or not {"msr", "dtherm", "pts", "pln"} <= set(row.get("flags", "").split())):
            raise PowerError("Temperature target: CPU0 thermal MSR capabilities are not qualified")

        def support_identity():
            # A loaded-only module can disappear before open(), allowing the
            # kernel character-device autoloader to run. Accept proven built-in
            # MSR support only; an unknown identity is an unavailable diagnostic.
            module = self.path("/sys/module/msr").lstat()
            if not stat.S_ISDIR(module.st_mode):
                raise PowerError("Temperature target: existing MSR support is not a directory")
            if self.path("/sys/module/msr/initstate").exists() or self.path("/sys/module/msr/initstate").is_symlink():
                raise PowerError("Temperature target: loaded MSR module is not qualified; refusing possible autoload")
            release = self.read_control("/proc/sys/kernel/osrelease")
            if not re.fullmatch(r"[0-9][A-Za-z0-9._+-]{1,100}", release):
                raise PowerError("Temperature target: invalid running kernel release")
            builtin = self.regular("/usr/lib/modules/" + release + "/modules.builtin")
            if b"kernel/arch/x86/kernel/msr.ko" not in builtin.splitlines():
                raise PowerError("Temperature target: MSR support is not proven built-in; refusing possible autoload")
            notes = self.path("/sys/kernel/notes").read_bytes()
            if not notes:
                raise PowerError("Temperature target: missing kernel identity")
            boot = self.read_control("/proc/sys/kernel/random/boot_id")
            if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot):
                raise PowerError("Temperature target: invalid boot identity")
            return (boot, release, digest(builtin), digest(notes), module.st_dev, module.st_ino)

        baseline = support_identity()
        descriptors, directories = [], []
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            # Walk /dev/cpu/0 by dirfd so O_NOFOLLOW also protects parents.
            parent = None
            for name, logical in ((str(self.path("/dev")), "/dev"), ("cpu", "/dev/cpu"), ("0", "/dev/cpu/0")):
                fd = os.open(name, directory_flags, dir_fd=parent)
                descriptors.append(fd)
                info = os.fstat(fd)
                directories.append((logical, info.st_dev, info.st_ino))
                parent = fd
            before = os.stat("msr", dir_fd=parent, follow_symlinks=False)
            def valid_node(info):
                return stat.S_ISCHR(info.st_mode) and (os.major(info.st_rdev), os.minor(info.st_rdev)) == (202, 0)
            def identity(info):
                return (info.st_dev, info.st_ino, info.st_rdev)
            if not valid_node(before):
                raise PowerError("Temperature target: expected existing CPU0 MSR character device 202:0")
            fd = os.open("msr", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(fd)
            opened = os.fstat(fd)
            if not valid_node(opened) or identity(opened) != identity(before):
                raise PowerError("Temperature target: MSR device changed during open")
            def read(offset):
                raw = os.pread(fd, 8, offset)
                if len(raw) != 8:
                    raise PowerError(f"Temperature target: short MSR read at {offset:#x}")
                return int.from_bytes(raw, "little")
            platform = read(0xce)
            if not platform & (1 << 30):
                raise PowerError("Temperature target: PLATFORM_INFO does not advertise TCC offset support")
            target = read(0x1a2)
            tjmax, offset = (target >> 16) & 0xff, (target >> 24) & 0x3f
            # This exact host has a verified 100 C reference. Other TjMax
            # values remain unqualified, rather than guessed invalid hardware.
            if tjmax != 100 or offset >= tjmax:
                raise PowerError("Temperature target: unqualified TjMax or activation reference")
            if (support_identity() != baseline or not valid_node(os.fstat(fd))
                    or identity(os.fstat(fd)) != identity(before)
                    or identity(os.stat("msr", dir_fd=parent, follow_symlinks=False)) != identity(before)):
                raise PowerError("Temperature target: boot, support or MSR device identity changed")
            for logical, device, inode in directories:
                info = self.path(logical).lstat()
                if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (device, inode):
                    raise PowerError("Temperature target: MSR parent directory changed")
            return {"platform_info_raw": platform, "temperature_target_raw": target,
                    "tjmax_celsius": tjmax, "tcc_offset_celsius": offset,
                    "tcc_activation_celsius": tjmax - offset}
        finally:
            prior_error = sys.exc_info()[1]
            close_errors = []
            for fd in reversed(descriptors):
                try:
                    os.close(fd)
                except OSError as exc:
                    close_errors.append(str(exc))
            if close_errors:
                detail = "Temperature target: descriptor close failed: " + "; ".join(close_errors)
                if prior_error is not None:
                    detail += "; preceding read/check failure: " + str(prior_error)
                raise PowerError(detail) from prior_error

    def write_control(self, logical, value):
        try:
            path = self.path(logical)
            if path.is_symlink() or not path.resolve().is_relative_to(self.path("/sys")):
                raise PowerError(f"Untrusted sysfs control: {logical}")
            # sysfs accepts a single value; never truncate other control files.
            with path.open("w") as stream:
                stream.write(str(value) + "\n")
        except OSError as exc:
            raise PowerError(f"Cannot write {logical}: {exc}") from exc

    def exists(self, logical):
        return os.path.lexists(self.path(logical))

    @staticmethod
    def boot_id():
        # Process identity is a kernel boundary, independent of file-tree fixtures.
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError as exc:
            raise PowerError(f"Cannot read boot identity: {exc}") from exc

    def process_identity(self, pid=None):
        pid = os.getpid() if pid is None else pid
        if type(pid) is not int or pid <= 0:
            raise PowerError("Invalid transaction owner PID")
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return None
            return {"pid": pid, "start_ticks": int(fields[19]), "boot_id": self.boot_id()}
        except FileNotFoundError:
            return None
        except (OSError, ValueError, IndexError) as exc:
            raise PowerError(f"Cannot establish process identity for PID {pid}: {exc}") from exc

    def regular(self, logical, *, missing=False):
        path = self.path(logical)
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing:
                return None
            raise PowerError(f"Missing file: {logical}")
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o022:
            raise PowerError(f"Untrusted file (owner, mode or symlink): {logical}")
        self.no_symlink_parents(path)
        return path.read_bytes()

    def no_symlink_parents(self, path):
        for parent in path.parents:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise PowerError(f"Symlink parent refused: {parent}")

    def directory(self, logical, mode=0o700):
        path = self.path(logical)
        self.no_symlink_parents(path)
        if path.is_symlink():
            raise PowerError(f"Symlink directory refused: {logical}")
        path.mkdir(parents=True, mode=mode, exist_ok=True)
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o022:
            raise PowerError(f"Untrusted directory: {logical}")
        return path

    def atomic(self, logical, data, mode=0o600):
        path = self.path(logical)
        self.regular(logical, missing=True)
        directory = self.directory(str(Path(logical).parent))
        descriptor, temporary = tempfile.mkstemp(prefix=".mechrevo-power-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def remove(self, logical):
        if self.regular(logical, missing=True) is not None:
            self.path(logical).unlink()


class PowerController:
    def __init__(self, env=None):
        self.env = env or Environment()

    def require_root(self):
        if self.env.uid != 0:
            raise PowerError("set, clear and apply require root")

    @contextmanager
    def lock(self):
        self.require_root()
        self.env.directory(str(Path(LOCK).parent), 0o755)
        self.env.regular(LOCK, missing=True)
        fd = os.open(self.env.path(LOCK), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise PowerError("Another mechrevo-power operation is running") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load_state(self):
        raw = self.env.regular(STATE, missing=True)
        if raw is None:
            return None
        try:
            state = json.loads(raw)
            self.validate_state(state)
            return state
        except (ValueError, KeyError, TypeError) as exc:
            raise PowerError(f"Invalid managed state: {exc}") from exc

    @staticmethod
    def valid_hash(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def validate_observed(self, observed):
        if not isinstance(observed, dict) or set(observed) != set(ZONES):
            raise ValueError("Invalid powercap snapshot")
        for value in observed.values():
            if (not isinstance(value, dict) or type(value["pl1_uw"]) is not int
                    or not 0 < value["pl1_uw"] <= 2_147_483_647
                    or type(value["max_power_uw"]) is not int
                    or value["max_power_uw"] != THERMAL_SPEC_POWER_UW):
                raise ValueError("Invalid powercap snapshot values")
            physical = value["physical_path"]
            if (not isinstance(physical, str) or ".." in Path(physical).parts
                    or not Path(physical).is_relative_to(self.env.path("/sys"))):
                raise ValueError("Invalid powercap snapshot path")

    def validate_state(self, state):
        """Validate consumed nested data before any command can act on it.

        In particular bool is not an integer here and a truthy string is not
        an apply success. An apply receipt may be absent/null; a present
        transaction must be an object, never an empty record or array.
        """
        if (not isinstance(state, dict) or type(state["version"]) is not int
                or state["version"] != 1 or type(state["initial_ceiling_uw"]) is not int
                or not MIN_LIMIT_UW <= state["initial_ceiling_uw"] <= 2_147_483_647
                or type(state["cap_uw"]) is not int
                or not MIN_LIMIT_UW <= state["cap_uw"] <= state["initial_ceiling_uw"]):
            raise ValueError("Invalid state schema or cap")
        self.validate_target(state.get("target_celsius"))
        polling_target(state.get("polling_seconds"), state.get("target_celsius"))
        rapl_debounce_target(state.get("rapl_debounce_seconds"), state.get("target_celsius"), state.get("polling_seconds"))
        preference = state["preference"]
        if (state["host"] != IDENTITY or not isinstance(preference, dict)
                or type(preference["value"]) is not int or preference["value"] not in (0, 1)
                or preference["name"] != ("ENERGY_CONSERVE", "PERFORMANCE")[preference["value"]]):
            raise ValueError("Invalid identity or preference")
        self.validate_observed(state["initial_limits"])
        if state["initial_ceiling_uw"] != min(v["pl1_uw"] for v in state["initial_limits"].values()):
            raise ValueError("Initial ceiling does not match its snapshot")
        hashes = state["managed_hashes"]
        if (not isinstance(hashes, dict) or set(hashes) != {XML, DROPIN}
                or not all(self.valid_hash(value) for value in hashes.values())):
            raise ValueError("Invalid managed file hashes")
        if not all(self.valid_hash(state[key]) for key in
                   ("stock_unit_sha256", "features_sha256", "thermald_sha256")):
            raise ValueError("Invalid qualification hashes")
        if any(not isinstance(state[key], str) or not state[key] for key in ("backup", "operation_id")):
            raise ValueError("Invalid state metadata")
        pending = state.get("transaction")
        if "transaction" in state:
            if (not isinstance(pending, dict) or not isinstance(pending["id"], str) or not pending["id"]
                    or pending["operation"] not in ("set", "clear", "rollback", "rollback_stock", "recover")):
                raise ValueError("Invalid pending transaction")
            owner = pending["owner"]
            if (not isinstance(owner, dict) or set(owner) != {"pid", "start_ticks", "boot_id"}
                    or type(owner["pid"]) is not int or owner["pid"] <= 0
                    or type(owner["start_ticks"]) is not int or owner["start_ticks"] < 0
                    or not isinstance(owner["boot_id"], str) or not owner["boot_id"]):
                raise ValueError("Invalid transaction owner")
            if any(key in pending for key in ("prior_managed_hashes", "prior_cap_uw", "prior_target_celsius", "prior_polling_seconds", "prior_rapl_debounce_seconds")):
                prior = pending["prior_managed_hashes"]
                cap = pending["prior_cap_uw"]
                self.validate_target(pending.get("prior_target_celsius"))
                polling_target(pending.get("prior_polling_seconds"), pending.get("prior_target_celsius"))
                rapl_debounce_target(pending.get("prior_rapl_debounce_seconds"), pending.get("prior_target_celsius"), pending.get("prior_polling_seconds"))
                if cap is None and pending.get("prior_target_celsius") is not None:
                    raise ValueError("Unconfigured prior state cannot have a temperature target")
                if (not isinstance(prior, dict) or set(prior) != {XML, DROPIN}
                        or (cap is not None and (type(cap) is not int
                            or not MIN_LIMIT_UW <= cap <= state["initial_ceiling_uw"]))
                        or any(value is not None if cap is None else not self.valid_hash(value)
                               for value in prior.values())):
                    raise ValueError("Invalid previous managed configuration")
        applied = state.get("last_apply")
        if applied is not None:
            if (not isinstance(applied, dict) or type(applied["version"]) is not int or applied["version"] != 1
                    or applied["operation"] != "apply" or type(applied["success"]) is not bool
                    or not isinstance(applied["writes"], list)
                    or any(zone not in ZONES for zone in applied["writes"])
                    or (applied["transaction"] is not None and
                        (not isinstance(applied["transaction"], str) or not applied["transaction"]))):
                raise ValueError("Invalid apply receipt")
            if applied["success"]:
                if type(applied["cap_uw"]) is not int or applied["cap_uw"] != state["cap_uw"]:
                    raise ValueError("Apply receipt does not match the requested cap")
                self.validate_observed(applied["observed"])
                if any(value["pl1_uw"] > state["cap_uw"] for value in applied["observed"].values()):
                    raise ValueError("Successful apply receipt exceeds its cap")

    @staticmethod
    def validate_target(target):
        temperature_target(target)

    def qualify_target(self, target):
        if target is None:
            return
        self.validate_target(target)
        for path in CPU_TARGET_OVERRIDES:
            if self.env.exists(path):
                raise PowerError("Foreign CPU temperature override refused: " + path)
        order = self.env.regular(CPU_COOLING_ORDER, missing=True)
        if order is not None:
            # Arch ships this optional file with precisely the native order.
            # Accept its semantics, not arbitrary native-parser customization.
            if len(order) > 65_536 or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", order, re.I):
                raise PowerError("Unqualified CPU cooling order XML")
            try:
                root = ET.fromstring(order)
            except ET.ParseError as exc:
                raise PowerError("Invalid CPU cooling order XML") from exc
            if (root.tag != "CoolingDeviceOrder" or root.attrib
                    or (root.text or "").strip() or len(root) != len(CPU_COOLING_DEVICES)):
                raise PowerError("CPU cooling order must preserve all native defaults")
            for child, expected in zip(root, CPU_COOLING_DEVICES):
                if (child.tag != "CoolingDevice" or child.attrib or len(child)
                        or child.text != expected or (child.tail or "").strip()):
                    raise PowerError("CPU cooling order must preserve exact native names and order")
        # The XML must enter thermald's valid-sensor path. A missing sensor
        # otherwise takes a different temperature-only compatibility branch.
        sensors = []
        for candidate in self.env.path("/sys/class/thermal").glob("thermal_zone*"):
            try:
                sensor_type = (candidate / "type").read_text().strip()
                if sensor_type in ("pkg-temp-0", "soc_dts0"):
                    raise PowerError("Additional native CPU sensor would change trip matching")
                if sensor_type == "x86_pkg_temp":
                    sensors.append(candidate)
            except OSError as exc:
                raise PowerError("Cannot qualify native CPU thermal sensor") from exc
        if len(sensors) != 1 or not sensors[0].resolve().is_relative_to(self.env.path("/sys")):
            raise PowerError("Exactly one native x86_pkg_temp sensor is required")
        try:
            value = int((sensors[0] / "temp").read_text())
        except (OSError, ValueError) as exc:
            raise PowerError("Native CPU thermal sensor cannot be read") from exc
        if not 0 <= value <= 125_000:
            raise PowerError("Native CPU thermal sensor is outside its diagnostic range")

    def service(self):
        output = self.env.command("systemctl", "show", "thermald.service",
                                  "--property=FragmentPath,DropInPaths,ActiveState,ExecStart")
        result = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        for key in ("FragmentPath", "DropInPaths", "ActiveState", "ExecStart"):
            if key not in result:
                raise PowerError(f"systemctl omitted {key}")
        return result

    @staticmethod
    def exec_start(properties):
        raw = properties["ExecStart"]
        match = re.search(r"argv\[\]=(.*?)\s*;", raw)
        return match.group(1).strip() if match else raw.strip()

    def preference(self):
        raw = self.env.regular(PREF, missing=True)
        if raw is None:
            return {"value": 0, "name": "ENERGY_CONSERVE", "file_present": False}
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise PowerError("Invalid thermald preference file") from exc
        if value not in (0, 1):
            raise PowerError("Disabled or unknown thermald preference is unsupported")
        return {"value": value, "name": ("ENERGY_CONSERVE", "PERFORMANCE")[value],
                "file_present": True}

    def observe(self):
        observed = {}
        for zone in ZONES:
            physical = self.env.path(zone).resolve()
            if not physical.is_relative_to(self.env.path("/sys")):
                raise PowerError(f"Powercap link leaves sysfs: {zone}")
            for name, expected in (("name", "package-0"), ("enabled", "1"),
                                   ("constraint_0_name", "long_term")):
                if self.env.read_control(zone + "/" + name) != expected:
                    raise PowerError(f"Unsupported {zone}/{name}")
            try:
                power = int(self.env.read_control(zone + "/constraint_0_power_limit_uw"))
                maximum = int(self.env.read_control(zone + "/constraint_0_max_power_uw"))
            except ValueError as exc:
                raise PowerError(f"Invalid power value: {zone}") from exc
            if power <= 0 or power > 2_147_483_647 or maximum != THERMAL_SPEC_POWER_UW:
                raise PowerError(f"Unqualified PL1 or thermal-spec-power value: {zone}")
            observed[zone] = {"pl1_uw": power, "max_power_uw": maximum,
                              "physical_path": str(physical)}
        return observed

    def rapl_constraints(self):
        """Read optional diagnostics without changing PL1 qualification/state."""
        constraints, errors = {}, []
        for zone in ZONES:
            constraints[zone] = {}
            for index, label, expected in ((0, "pl1", "long_term"),
                                            (1, "pl2", "short_term")):
                entry = {"available": False, "name": None,
                         "name_valid": False, "power_limit_uw": None,
                         "time_window_us": None}
                constraints[zone][label] = entry
                prefix = f"{zone}/constraint_{index}"
                try:
                    physical = self.env.path(zone).resolve()
                    if not physical.is_relative_to(self.env.path("/sys")):
                        raise PowerError(f"Powercap link leaves sysfs: {zone}")
                    entry["name"] = self.env.read_control(prefix + "_name")
                    if entry["name"] != expected:
                        raise PowerError(f"Unsupported {prefix}_name: {entry['name']!r}")
                    entry["name_valid"] = True
                    power = int(self.env.read_control(prefix + "_power_limit_uw"))
                    window = int(self.env.read_control(prefix + "_time_window_us"))
                    if not 0 <= power <= 2_147_483_647 or window < 0:
                        raise PowerError(f"Invalid power or time window: {prefix}")
                    entry.update(available=True, power_limit_uw=power,
                                 time_window_us=window)
                except (PowerError, OSError, ValueError) as exc:
                    errors.append(f"{zone} {label} diagnostics unavailable: {exc}")
        return constraints, errors

    def validate_managed(self, state, *, allow_missing=False, allow_prior=False):
        prior = {}
        pending = state.get("transaction") or {}
        if allow_prior and "prior_managed_hashes" in pending:
            prior = pending["prior_managed_hashes"]
            prior_cap = pending.get("prior_cap_uw")
            if prior_cap is None:
                expected_prior = {XML: None, DROPIN: None}
            elif type(prior_cap) is int and MIN_LIMIT_UW <= prior_cap <= state["initial_ceiling_uw"]:
                expected_prior = {XML: digest(self.xml(prior_cap, state["preference"]["name"],
                                                      pending.get("prior_target_celsius"), pending.get("prior_polling_seconds"), pending.get("prior_rapl_debounce_seconds"))),
                                  DROPIN: digest(self.dropin(pending.get("prior_target_celsius")))}
            else:
                raise PowerError("Invalid previous managed cap in interrupted transaction")
            if prior != expected_prior:
                raise PowerError("Previous file hashes do not match a managed configuration")
        for path, expected in state["managed_hashes"].items():
            raw = self.env.regular(path, missing=allow_missing)
            if raw is None and allow_missing:
                continue
            if digest(raw) not in (expected, prior.get(path)):
                raise PowerError(f"Managed file changed; refusing overwrite: {path}")
        expected_xml = self.xml(state["cap_uw"], state["preference"]["name"], state.get("target_celsius"), state.get("polling_seconds"), state.get("rapl_debounce_seconds"))
        if (state["managed_hashes"][XML] != digest(expected_xml)
                or state["managed_hashes"][DROPIN] != digest(self.dropin(state.get("target_celsius")))):
            raise PowerError("Managed configuration does not match state")

    def configuration(self, state, *, require_running=True, disk_only=False,
                      allow_missing_managed=False):
        unit = self.env.regular(STOCK_UNIT)
        service_section = False
        commands = []
        for line in unit.decode().splitlines():
            line = line.strip()
            if line.startswith("["):
                service_section = line == "[Service]"
            elif service_section and line.startswith("ExecStart"):
                commands.append(line)
        if commands != ["ExecStart=" + STOCK_EXEC_START]:
            raise PowerError("Unqualified stock thermald unit")
        for path in FOREIGN_CONFIGS + ("/etc/systemd/system/thermald.service",
                                      "/run/systemd/system/thermald.service"):
            if self.env.exists(path):
                raise PowerError(f"Foreign thermald configuration refused: {path}")
        for base in ("/etc", "/run", "/usr/lib"):
            for suffix in ("thermald.service.d", "service.d"):
                directory = self.env.path(base + "/systemd/system/" + suffix)
                if directory.is_symlink():
                    raise PowerError(f"Symlink drop-in directory: {directory}")
                if directory.exists():
                    for path in directory.glob("*.conf"):
                        logical = "/" + str(path.relative_to(self.env.root))
                        if not state or logical != DROPIN:
                            raise PowerError(f"Foreign thermald drop-in refused: {logical}")
        features = self.env.regular(FEATURES)
        try:
            enabled = ET.fromstring(features).findtext("XMLThermalConfig", "").strip()
        except ET.ParseError as exc:
            raise PowerError("Invalid thermald feature configuration") from exc
        if enabled != "1":
            raise PowerError("thermald XMLThermalConfig must be 1")
        if state:
            self.validate_managed(state, allow_missing=allow_missing_managed,
                                  allow_prior=allow_missing_managed)
            if state["stock_unit_sha256"] != digest(unit) or state["features_sha256"] != digest(features):
                raise PowerError("Stock thermald unit or features changed since set")
        elif self.env.exists(XML) or self.env.exists(DROPIN):
            raise PowerError("Orphan or foreign mechrevo-power configuration refused")
        if disk_only:
            return None
        service = self.service()
        if service["FragmentPath"] != STOCK_UNIT:
            raise PowerError("thermald is not using the qualified stock unit")
        expected_paths = [DROPIN] if state else []
        if service["DropInPaths"].split() != expected_paths:
            raise PowerError("Loaded thermald drop-ins do not match managed files")
        expected_command = self.managed_exec_start(state.get("target_celsius")) if state else STOCK_EXEC_START
        if self.exec_start(service) != expected_command:
            raise PowerError("Loaded thermald command does not match configuration")
        if require_running and service["ActiveState"] != "active":
            raise PowerError("thermald must be active")
        if not require_running and service["ActiveState"] not in ("active", "activating"):
            raise PowerError("thermald must be active or starting before apply")
        return service

    def qualify(self, state, *, require_running=True):
        self.qualify_target(state.get("target_celsius") if state else None)
        host = {key: self.env.read_control("/sys/class/dmi/id/" + key) for key in IDENTITY}
        if host != IDENTITY:
            raise PowerError("This machine or BIOS has not been qualified")
        cpuinfo = self.env.read_control("/proc/cpuinfo")
        models = re.findall(r"^model name\s*:\s*(.*)$", cpuinfo, re.M)
        if not models or any(model.strip() != CPU_MODEL for model in models):
            raise PowerError("This CPU has not been qualified")
        if self.env.command("/usr/bin/thermald", "--version") != "2.5.13":
            raise PowerError("Only thermald 2.5.13 is qualified")
        binary_hash = digest(self.env.regular("/usr/bin/thermald"))
        if binary_hash != QUALIFIED_THERMALD_SHA256:
            raise PowerError("This thermald binary has not been qualified")
        if state and state["thermald_sha256"] != binary_hash:
            raise PowerError("thermald binary changed since set")
        for path in PPCC_PATHS + ("/sys/bus/platform/drivers/int3400 thermal",):
            if self.env.exists(path):
                raise PowerError(f"Unqualified adaptive or PPCC interface: {path}")
        tcc = {}
        for path in TCC_PATHS:
            if self.env.exists(path):
                try:
                    value = int(self.env.read_control(path))
                except ValueError as exc:
                    raise PowerError("Invalid TCC offset") from exc
                if value < 0 or value > 10:
                    raise PowerError("TCC offset could trigger thermald's unrelated workaround")
                tcc[path] = value
            else:
                tcc[path] = None
        service = self.configuration(state, require_running=require_running)
        preference = self.preference()
        observed = self.observe()
        if state and (host != state["host"] or preference["value"] != state["preference"]["value"]):
            raise PowerError("Host identity or thermald preference changed")
        if state and any(observed[zone]["physical_path"] != state["initial_limits"][zone]["physical_path"]
                         for zone in ZONES):
            raise PowerError("Powercap interface changed since set")
        return host, preference, observed, service, tcc

    @staticmethod
    def xml(cap_uw, preference, target_celsius=None, polling_seconds=None, rapl_debounce_seconds=None):
        temperature_target(target_celsius)
        polling_target(polling_seconds, target_celsius)
        rapl_debounce_target(rapl_debounce_seconds, target_celsius, polling_seconds)
        root = ET.Element("ThermalConfiguration")
        platform = ET.SubElement(root, "Platform")
        ET.SubElement(platform, "Name").text = "MECHREVO GM6PX0X user PL1 ceiling"
        ET.SubElement(platform, "ProductName").text = IDENTITY["product_name"]
        ET.SubElement(platform, "Preference").text = preference
        if polling_seconds is not None:
            ET.SubElement(platform, "PollingInterval").text = str(polling_seconds)
        cooling = ET.SubElement(platform, "CoolingDevices")
        for name in ("rapl_controller", "rapl_controller_mmio"):
            device = ET.SubElement(cooling, "CoolingDevice")
            ET.SubElement(device, "Type").text = name
            ET.SubElement(device, "MinState").text = str(cap_uw)
            ET.SubElement(device, "MaxState").text = str(cap_uw // 2)
            if name == "rapl_controller" and rapl_debounce_seconds is not None:
                ET.SubElement(device, "DebouncePeriod").text = str(rapl_debounce_seconds)
        if target_celsius is not None:
            zones = ET.SubElement(platform, "ThermalZones")
            zone = ET.SubElement(zones, "ThermalZone")
            ET.SubElement(zone, "Type").text = "cpu"
            trips = ET.SubElement(zone, "TripPoints")
            trip = ET.SubElement(trips, "TripPoint")
            ET.SubElement(trip, "SensorType").text = "x86_pkg_temp"
            ET.SubElement(trip, "Temperature").text = str(target_celsius * 1000)
            ET.SubElement(trip, "Hyst").text = str(THERMAL_HYSTERESIS_MILLICELSIUS)
            ET.SubElement(trip, "type").text = "passive"
            ET.SubElement(trip, "ControlType").text = "SEQUENTIAL"
            # Valid-sensor XML replaces the native PASSIVE trip. Reconstruct
            # all native fallback bindings, retaining order and default params.
            for name in CPU_COOLING_DEVICES:
                device = ET.SubElement(trip, "CoolingDevice")
                ET.SubElement(device, "type").text = name
                ET.SubElement(device, "influence").text = "0"
                ET.SubElement(device, "SamplingPeriod").text = "0"
        ET.indent(root)
        return b'<?xml version="1.0"?>\n' + ET.tostring(root, encoding="utf-8") + b"\n"

    @staticmethod
    def managed_exec_start(target_celsius=None):
        return managed_exec_start(target_celsius)

    @staticmethod
    def dropin(target_celsius=None):
        return ("# Managed by mechrevo-power; use mechrevo-power clear to remove.\n"
                "[Service]\nExecStart=\nExecStart=" + managed_exec_start(target_celsius) + "\n"
                "ExecStartPost=-/usr/bin/mechrevo-power apply\n").encode()

    def receipt(self, operation, success, **details):
        value = {"version": 1, "operation": operation, "success": success,
                 "time": self.env.clock(), **details}
        name = str(uuid.uuid4())
        self.env.atomic(RECEIPTS + "/" + name + ".json", json_bytes(value))
        return value

    def backup(self, operation, old_files, snapshot):
        date = time.strftime("%Y%m%d", time.localtime(self.env.clock()))
        name = date + "-" + str(uuid.uuid4())
        directory = BACKUP_ROOT + "/" + name
        self.env.directory(BACKUP_ROOT)
        self.env.directory(directory)
        files = {}
        for path, data in old_files.items():
            if data is None:
                files[path] = None
            else:
                info = self.env.path(path).lstat()
                files[path] = {"sha256": digest(data), "base64": base64.b64encode(data).decode(),
                               "uid": info.st_uid, "gid": info.st_gid,
                               "mode": stat.S_IMODE(info.st_mode), "size": len(data)}
        manifest = {"version": 1, "operation": operation, "time": self.env.clock(),
                    "files": files, "snapshot": snapshot}
        payload = json_bytes(manifest)
        target = directory + "/prewrite-state.json"
        self.env.atomic(target, payload)
        if self.env.regular(target) != payload:
            raise PowerError("Recovery backup verification failed")
        return target

    def restart(self):
        # Never call while holding flock: ExecStartPost runs apply and takes it.
        self.env.command("systemctl", "daemon-reload")
        self.env.command("systemctl", "restart", "thermald.service")

    def restore(self, old_files, expected_hashes, transaction):
        with self.lock():
            current = self.load_state()
            if not current or transaction not in (current.get("transaction", {}).get("id"),
                                                  current.get("operation_id")):
                raise PowerError("Transaction changed; automatic rollback refused")
            for path in (XML, DROPIN):
                raw = self.env.regular(path, missing=True)
                if raw is not None and digest(raw) not in (expected_hashes[path],
                        digest(old_files[path]) if old_files[path] is not None else None):
                    raise PowerError(f"File changed during operation; rollback refused: {path}")
            target = json.loads(old_files[STATE]) if old_files[STATE] is not None else None
            barrier = dict(target if target is not None else current)
            barrier.update(operation_id=transaction, last_apply=None, backup=current["backup"],
                           transaction={"id": transaction,
                                        "operation": "rollback" if target is not None else "rollback_stock",
                                        "owner": self.env.process_identity(),
                                        "prior_cap_uw": current["cap_uw"],
                                        "prior_target_celsius": current.get("target_celsius"),
                                        "prior_polling_seconds": current.get("polling_seconds"),
                                        "prior_rapl_debounce_seconds": current.get("rapl_debounce_seconds"),
                                        "prior_managed_hashes": expected_hashes})
            self.env.atomic(STATE, json_bytes(barrier))
            for path in (XML, DROPIN):
                if old_files[path] is None:
                    self.env.remove(path)
                else:
                    self.env.atomic(path, old_files[path], 0o644)
        self.restart()
        with self.lock():
            current = self.load_state()
            if not current or current.get("transaction", {}).get("id") != transaction:
                raise PowerError("Rollback transaction changed during restart")
            if target is None:
                self.configuration(None)
                self.observe()
                self.env.remove(STATE)
            else:
                _, _, observed, _, _ = self.qualify(current)
                applied = current.get("last_apply") or {}
                if (not applied.get("success") or applied.get("transaction") != transaction
                        or any(v["pl1_uw"] > current["cap_uw"] for v in observed.values())):
                    raise PowerError("Previous managed cap was not restored successfully")
                current.pop("transaction")
                current["last_rollback"] = self.receipt("rollback", True, observed=observed,
                                                        cap_uw=current["cap_uw"], transaction=transaction)
                self.env.atomic(STATE, json_bytes(current))

    def _stage_set(self, watts, transaction, context, target_celsius=None, polling_seconds=None, rapl_debounce_seconds=None):
        with self.lock():
            previous = self.load_state()
            if previous and previous.get("transaction"):
                raise PowerError("Another transaction is pending; inspect recovery receipts")
            host, preference, observed, _, tcc = self.qualify(previous)
            self.qualify_target(target_celsius)
            ceiling = previous["initial_ceiling_uw"] if previous else min(v["pl1_uw"] for v in observed.values())
            cap = watts * 1_000_000
            if cap < MIN_LIMIT_UW or cap > ceiling:
                raise PowerError(f"Limit must be between {MIN_LIMIT_UW // 1_000_000} and {ceiling // 1_000_000} whole watts")
            # Initial values bound the operation, not the notebook's safety rating.
            old_files = {path: self.env.regular(path, missing=True) for path in (XML, DROPIN, STATE, PREF)}
            backup = self.backup("set", old_files, {"host": host, "preference": preference,
                                                     "observed": observed, "tcc": tcc})
            xml, dropin = self.xml(cap, preference["name"], target_celsius, polling_seconds, rapl_debounce_seconds), self.dropin(target_celsius)
            hashes = {XML: digest(xml), DROPIN: digest(dropin)}
            state = {"version": 1, "cap_uw": cap, "initial_ceiling_uw": ceiling,
                     "target_celsius": target_celsius,
                     "polling_seconds": polling_seconds,
                     "rapl_debounce_seconds": rapl_debounce_seconds,
                     "initial_limits": previous["initial_limits"] if previous else observed,
                     "host": host, "preference": preference, "tcc": tcc,
                     "managed_hashes": hashes, "stock_unit_sha256": digest(self.env.regular(STOCK_UNIT)),
                     "features_sha256": digest(self.env.regular(FEATURES)),
                     "thermald_sha256": digest(self.env.regular("/usr/bin/thermald")), "backup": backup,
                     "operation_id": transaction,
                     "transaction": {"id": transaction, "operation": "set",
                                     "owner": self.env.process_identity(),
                                     "prior_cap_uw": previous["cap_uw"] if previous else None,
                                     "prior_target_celsius": previous.get("target_celsius") if previous else None,
                                     "prior_polling_seconds": previous.get("polling_seconds") if previous else None,
                                     "prior_rapl_debounce_seconds": previous.get("rapl_debounce_seconds") if previous else None,
                                     "prior_managed_hashes": previous["managed_hashes"] if previous else {XML: None, DROPIN: None}},
                     "last_apply": None}
            context.update(old_files=old_files, hashes=hashes, backup=backup, cap=cap, phase="staging")
            try:
                # Persist recovery ownership before touching the daemon's files.
                self.env.atomic(STATE, json_bytes(state))
                self.env.atomic(XML, xml, 0o644)
                self.env.atomic(DROPIN, dropin, 0o644)
            except (Exception, KeyboardInterrupt) as exc:
                # Service has not been reloaded. Restore only bytes this operation owns.
                for path in (XML, DROPIN, STATE):
                    raw = self.env.regular(path, missing=True)
                    allowed = (old_files[path], xml if path == XML else dropin if path == DROPIN else json_bytes(state))
                    if raw not in allowed and raw is not None:
                        raise PowerError(f"Staging failed; foreign bytes retained: {path}; backup {backup}") from exc
                    if old_files[path] is None:
                        self.env.remove(path)
                    else:
                        self.env.atomic(path, old_files[path], 0o644 if path != STATE else 0o600)
                self.receipt("set", False, error=str(exc), backup=backup, phase="staging")
                context["phase"] = "restored"
                raise PowerError(f"Configuration staging failed: {exc}") from exc
            context["phase"] = "staged"

    def set_limit(self, watts, target_celsius=None, polling_seconds=None, rapl_debounce_seconds=None):
        self.require_root()
        self.validate_target(target_celsius)
        polling_target(polling_seconds, target_celsius)
        rapl_debounce_target(rapl_debounce_seconds, target_celsius, polling_seconds)
        if type(watts) is not int:
            raise PowerError("Limit must be an integer number of watts")
        transaction = str(uuid.uuid4())
        context = {}
        try:
            # Includes lock.__exit__: signals during the staging/restart handoff
            # receive the same rollback as signals in the service command.
            self._stage_set(watts, transaction, context, target_celsius, polling_seconds, rapl_debounce_seconds)
            cap, backup = context["cap"], context["backup"]
            self.restart()
            with self.lock():
                current = self.load_state()
                if not current or current.get("transaction", {}).get("id") != transaction:
                    raise PowerError("Set transaction changed during restart")
                _, _, observed, _, _ = self.qualify(current)
                applied = current.get("last_apply") or {}
                if not applied.get("success") or applied.get("transaction") != transaction:
                    raise PowerError("ExecStartPost apply did not complete successfully")
                if any(v["pl1_uw"] > cap for v in observed.values()):
                    raise PowerError("Readback exceeds requested cap")
                current.pop("transaction")
                self.env.atomic(STATE, json_bytes(current))
                # Keep the final readback and receipt under the same lock: a new
                # set must not replace our desired cap between commit and status.
                status = self.status()
                if not status["holding_now"]:
                    raise PowerError("Final status does not confirm the requested cap: " + "; ".join(status["errors"]))
                status["last_operation"] = self.receipt("set", True, phase="completed", transaction=transaction,
                                                         cap_uw=cap, observed=status["observed"], backup=backup)
                return status
        except (Exception, KeyboardInterrupt) as exc:
            if context.get("phase") != "staged":
                raise
            backup = context["backup"]
            try:
                self.restore(context["old_files"], context["hashes"], transaction)
                recovery = "configuration restored and thermald active"
            except (Exception, KeyboardInterrupt) as rollback:
                recovery = f"ROLLBACK FAILED: {rollback}"
            self.receipt("set", False, error=str(exc), recovery=recovery, backup=backup)
            raise PowerError(f"Set failed: {exc}; {recovery}; recovery backup: {backup}") from exc

    def apply(self):
        self.require_root()
        with self.lock():
            state = self.load_state()
            if state is None:
                raise PowerError("No managed power limit is configured")
            transaction = state.get("transaction", {}).get("id")
            if state.get("transaction", {}).get("operation") not in (None, "set", "rollback"):
                raise PowerError("Configuration is being cleared")
            writes = []
            try:
                _, _, observed, _, _ = self.qualify(state, require_running=False)
                for zone in ZONES:
                    # Re-read immediately: preserve a stricter limit applied by cooling.
                    current = int(self.env.read_control(zone + "/constraint_0_power_limit_uw"))
                    if current <= 0:
                        raise PowerError(f"Invalid current PL1: {zone}")
                    if current > state["cap_uw"]:
                        self.env.write_control(zone + "/constraint_0_power_limit_uw", state["cap_uw"])
                        writes.append(zone)
                    value = int(self.env.read_control(zone + "/constraint_0_power_limit_uw"))
                    if value <= 0 or value > state["cap_uw"]:
                        raise PowerError(f"PL1 write/readback failed: {zone}")
                observed = self.observe()
                if any(v["pl1_uw"] > state["cap_uw"] for v in observed.values()):
                    raise PowerError("PL1 changed above cap during apply")
                receipt = self.receipt("apply", True, cap_uw=state["cap_uw"], observed=observed,
                                       writes=writes, transaction=transaction)
            except (Exception, KeyboardInterrupt) as exc:
                receipt = self.receipt("apply", False, error=str(exc), writes=writes, transaction=transaction)
                state["last_apply"] = receipt
                self.env.atomic(STATE, json_bytes(state))
                raise PowerError(f"Apply failed: {exc}") from exc
            state["last_apply"] = receipt
            self.env.atomic(STATE, json_bytes(state))
            return receipt

    def _stage_clear(self, transaction, context):
        with self.lock():
            state = self.load_state()
            if state is None:
                self.configuration(None)
                return False
            if state.get("transaction"):
                raise PowerError("A transaction is pending; inspect recovery receipts")
            self.configuration(state)
            old_files = {path: self.env.regular(path, missing=True) for path in (XML, DROPIN, STATE, PREF)}
            backup = self.backup("clear", old_files, {"observed": self.observe(), "preference": self.preference()})
            pending = dict(state, backup=backup,
                           transaction={"id": transaction, "operation": "clear",
                                        "owner": self.env.process_identity(),
                                        "prior_cap_uw": state["cap_uw"],
                                        "prior_target_celsius": state.get("target_celsius"),
                                        "prior_polling_seconds": state.get("polling_seconds"),
                                        "prior_rapl_debounce_seconds": state.get("rapl_debounce_seconds"),
                                        "prior_managed_hashes": state["managed_hashes"]})
            context.update(old_files=old_files, state=state, backup=backup, phase="staging")
            try:
                self.env.atomic(STATE, json_bytes(pending))
                self.env.remove(XML)
                self.env.remove(DROPIN)
            except (Exception, KeyboardInterrupt) as exc:
                # The running daemon has not been restarted. Restore its files.
                for path in (XML, DROPIN, STATE):
                    raw = self.env.regular(path, missing=True)
                    allowed = (old_files[path], json_bytes(pending) if path == STATE else None)
                    if raw not in allowed and raw is not None:
                        raise PowerError(f"Clear staging failed; foreign bytes retained: {path}; backup {backup}") from exc
                    self.env.atomic(path, old_files[path], 0o644 if path != STATE else 0o600)
                self.receipt("clear", False, error=str(exc), backup=backup, phase="staging")
                context["phase"] = "restored"
                raise PowerError(f"Clear staging failed: {exc}") from exc
            context["phase"] = "staged"
        return True

    def clear(self):
        self.require_root()
        transaction = str(uuid.uuid4())
        context = {}
        try:
            if not self._stage_clear(transaction, context):
                return self.status()
            backup = context["backup"]
            self.restart()
            with self.lock():
                current = self.load_state()
                if not current or current.get("transaction", {}).get("id") != transaction:
                    raise PowerError("Clear transaction changed during restart")
                # STATE remains pending until the stock daemon has actually restarted.
                self.configuration(None)
                observed = self.observe()
                preference = self.preference()
                self.env.remove(STATE)
                return self.receipt("clear", True, phase="completed", transaction=transaction,
                                    observed=observed, backup=backup, preference_preserved=preference)
        except (Exception, KeyboardInterrupt) as exc:
            if context.get("phase") != "staged":
                raise
            backup = context["backup"]
            try:
                self.restore(context["old_files"], context["state"]["managed_hashes"], transaction)
                recovery = "previous configuration restored and thermald active"
            except (Exception, KeyboardInterrupt) as rollback:
                recovery = f"ROLLBACK FAILED: {rollback}"
            self.receipt("clear", False, error=str(exc), recovery=recovery, backup=backup)
            raise PowerError(f"Clear failed: {exc}; {recovery}; recovery backup: {backup}") from exc

    def recover(self):
        """Explicitly restore stock policy after an interrupted owner has exited."""
        self.require_root()
        transaction = str(uuid.uuid4())
        backup = None
        try:
            with self.lock():
                state = self.load_state()
                pending = (state or {}).get("transaction")
                if not pending:
                    raise PowerError("No interrupted transaction to recover; use clear for an active cap")
                owner = pending.get("owner")
                if (not isinstance(owner, dict) or set(owner) != {"pid", "start_ticks", "boot_id"}
                        or type(owner["pid"]) is not int or owner["pid"] <= 0
                        or type(owner["start_ticks"]) is not int or owner["start_ticks"] < 0
                        or not isinstance(owner["boot_id"], str) or not owner["boot_id"]):
                    raise PowerError("Missing or invalid transaction owner; automatic recovery refused")
                if owner["boot_id"] == self.env.boot_id():
                    current_owner = self.env.process_identity(owner["pid"])
                    if current_owner == owner:
                        raise PowerError("Transaction owner is still running; recovery refused")
                # A clear may have removed either file before it was interrupted.
                # Any existing file must still be ours; never replace foreign bytes.
                self.configuration(state, disk_only=True, allow_missing_managed=True)
                old_files = {path: self.env.regular(path, missing=True)
                             for path in (XML, DROPIN, STATE, PREF)}
                backup = self.backup("recover", old_files,
                                     {"pending_transaction": pending, "observed": self.observe()})
                barrier = dict(state, backup=backup, operation_id=transaction,
                               transaction={"id": transaction, "operation": "recover",
                                            "owner": self.env.process_identity(),
                                            **({"prior_cap_uw": pending.get("prior_cap_uw"),
                                                "prior_target_celsius": pending.get("prior_target_celsius"),
                                                "prior_polling_seconds": pending.get("prior_polling_seconds"),
                                                "prior_rapl_debounce_seconds": pending.get("prior_rapl_debounce_seconds"),
                                                "prior_managed_hashes": pending["prior_managed_hashes"]}
                                               if "prior_managed_hashes" in pending else {})})
                self.env.atomic(STATE, json_bytes(barrier))
                self.env.remove(XML)
                self.env.remove(DROPIN)
            self.restart()
            with self.lock():
                current = self.load_state()
                if not current or current.get("transaction", {}).get("id") != transaction:
                    raise PowerError("Recovery transaction changed during restart")
                self.configuration(None)
                observed = self.observe()
                preference = self.preference()
                self.env.remove(STATE)
                return self.receipt("recover", True, phase="completed", transaction=transaction,
                                    observed=observed, backup=backup, recovered_transaction=pending,
                                    preference_preserved=preference)
        except (Exception, KeyboardInterrupt) as exc:
            if backup is not None:
                self.receipt("recover", False, error=str(exc), backup=backup,
                             recovery="pending state retained; retry recover after this owner exits")
                raise PowerError(f"Recovery failed: {exc}; recovery backup: {backup}") from exc
            if isinstance(exc, PowerError):
                raise
            raise PowerError(f"Recovery preflight failed: {exc}") from exc

    def status(self):
        result = {"managed": False, "desired_limit_uw": None, "observed": {},
                  "desired_temperature_celsius": None,
                  "desired_polling_seconds": None,
                  "desired_rapl_debounce_seconds": None,
                  "thermald": {}, "holding_now": False, "errors": [],
                  "holding_scope": "cpu_package_pl1", "pl2_managed": False}
        try:
            state = self.load_state()
            if state is None:
                orphaned = [path for path in (XML, DROPIN) if self.env.exists(path)]
                if orphaned:
                    raise PowerError("Orphan or foreign mechrevo-power configuration without managed state: "
                                     + ", ".join(orphaned))
            result["managed"] = state is not None
            if state:
                result["desired_limit_uw"] = state["cap_uw"]
                result["desired_temperature_celsius"] = state.get("target_celsius")
                result["desired_polling_seconds"] = state.get("polling_seconds")
                result["desired_rapl_debounce_seconds"] = state.get("rapl_debounce_seconds")
                result["pending_transaction"] = state.get("transaction")
                result["last_apply"] = state.get("last_apply")
        except (PowerError, OSError) as exc:
            result["errors"].append(str(exc))
            state = None
        try:
            result["thermald"] = self.service()
        except PowerError as exc:
            result["errors"].append(str(exc))
        try:
            result["observed"] = self.observe()
        except (PowerError, OSError, ValueError) as exc:
            result["errors"].append(str(exc))
        if state:
            try:
                _, _, observed, service, _ = self.qualify(state)
                result["observed"] = observed
                result["thermald"] = service
                if state.get("transaction"):
                    raise PowerError("Configuration transaction is pending")
                if not (state.get("last_apply") or {}).get("success"):
                    raise PowerError("Latest apply has not succeeded")
                if any(v["pl1_uw"] > state["cap_uw"] for v in result["observed"].values()):
                    raise PowerError("Observed PL1 exceeds the requested limit")
                result["holding_now"] = bool(result["observed"]) and not result["errors"]
            except (PowerError, OSError) as exc:
                result["errors"].append(str(exc))
        result["rapl_constraints"], result["diagnostic_errors"] = self.rapl_constraints()
        result["package_temperature"] = {
            "available": False, "millicelsius": None, "sensor_identity": None,
            "read_window_ns": None, "clock": "CLOCK_MONOTONIC",
            "meaning": "One actual x86_pkg_temp sample in the 0..125000 millicelsius diagnostic range; not a temperature guarantee or hardware qualification"}
        try:
            result["package_temperature"].update(self.env.read_package_temperature(), available=True)
        except (PowerError, OSError, ValueError) as exc:
            result["diagnostic_errors"].append(str(exc))
        result["temperature_target"] = {
            "available": False, "cpu": 0, "scope": "cpu0_temperature_target_reference",
            "platform_info_raw": None, "temperature_target_raw": None,
            "tjmax_celsius": None, "tcc_offset_celsius": None, "tcc_activation_celsius": None,
            "software_target_celsius": result["desired_temperature_celsius"],
            "software_precedes_hardware": None,
            "meaning": "Hardware activation reference and configured software passive target; neither is a hard temperature ceiling"}
        try:
            target = self.env.read_temperature_target()
            result["temperature_target"].update(target, available=True)
            software = result["desired_temperature_celsius"]
            if software is not None:
                result["temperature_target"]["software_precedes_hardware"] = software < target["tcc_activation_celsius"]
        except (PowerError, OSError, ValueError) as exc:
            result["diagnostic_errors"].append(str(exc))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read desired limit, actual PL1 and thermald state")
    setter = commands.add_parser("set", help="Configure a PL1 ceiling (qualified host only)")
    setter.add_argument("watts", type=int)
    setter.add_argument("--target-celsius", type=int, choices=(90,), help="Optional CPU passive cooling target; not a hard temperature limit")
    setter.add_argument("--polling-seconds", type=int, choices=(1,), help="Optional cold-state polling interval; requires --target-celsius 90")
    setter.add_argument("--rapl-debounce-seconds", type=int, choices=(0,), help="Optional zero RAPL cooldown; requires explicit --target-celsius 90 --polling-seconds 1")
    commands.add_parser("clear", help="Restore the stock thermald configuration")
    commands.add_parser("apply", help="Apply managed PL1 once; used by thermald ExecStartPost")
    commands.add_parser("recover", help="Restore stock policy after an interrupted transaction owner exits")
    args = parser.parse_args(argv)
    controller = PowerController()
    def interrupted(signum, _frame):
        raise PowerError("Interrupted by " + signal.Signals(signum).name)
    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        result = (controller.set_limit(args.watts, target_celsius=args.target_celsius, polling_seconds=args.polling_seconds, rapl_debounce_seconds=args.rapl_debounce_seconds) if args.command == "set"
                  else getattr(controller, args.command)())
        print(json.dumps(result, indent=2, sort_keys=True))
        # Keep JSON available to diagnostics while making failed checks visible
        # to shell callers. A healthy, unconfigured host still exits successfully.
        return 1 if args.command == "status" and result["errors"] else 0
    except (PowerError, OSError, ValueError, KeyboardInterrupt) as exc:
        print(f"mechrevo-power: {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    sys.exit(main())
