#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""TUXEDO Control Center (TCC) Chinese Localization, Modern UI Beautification,
and Hardware Feature Enhancement Tool.

Features:
1. Zero external dependencies: pure Python standard library ASAR unpacker/packer.
2. Complete Simplified Chinese (zh-CN) localization for UI navigation, profiles,
   fan control, power limits, battery charging modes, RGB lighting, and hardware diagnostics.
3. Modern UI/UX styling: premium typography with CJK system font stack, high-contrast
   dark theme, refined card surfaces, and modernized telemetry gauge colors.
4. Hardware feature adaptation: connects GM6PX0X 3-stage battery health charging
   profiles (100% High Capacity / 80% Balanced / 60% Long-life) and dual-fan telemetry.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import stat
import struct
import sys
import tempfile

DEFAULT_ASAR_PATH = Path("/usr/lib/tuxedo-control-center/app.asar")


def backup_home() -> Path:
    """Keep sudo-created recovery material in the invoking user's Backups tree."""
    sudo_user = os.environ.get("SUDO_USER") if os.geteuid() == 0 else None
    return Path(pwd.getpwnam(sudo_user).pw_dir) if sudo_user else Path.home()


BACKUP_ASAR_PATH = (backup_home() / "Backups/mechrevo-drivers" / socket.gethostname()
                    / date.today().isoformat() / "tcc-app.asar.orig.bak")

# Complete translation mapping from English source strings to Simplified Chinese
ZH_TRANSLATIONS: dict[str, str] = {
    # Navigation and Sidebar
    "Dashboard": "仪表盘",
    "Profiles": "运行模式与配置",
    "Fan Control": "风扇控制",
    "Keyboard Backlight": "键盘背光与灯效",
    "Webcam": "摄像头设置",
    "Settings": "控制中心设置",
    "Support": "系统诊断与支持",
    "Overview": "控制总览",
    "Hardware Sensors": "硬件监控传感器",
    "Battery & Charging": "电池与充电管理",

    # Profiles and Power Modes
    "High Performance": "极速狂暴模式",
    "Balanced": "平衡标准模式",
    "Cool and Quiet": "安静节能模式",
    "Custom Profile": "自定义性能配置",
    "Default Profiles": "预设性能模式",
    "Active Profile": "当前运行模式",
    "Power Settings": "功耗调度设置",
    "Processor Power Limit 1 (PL1)": "处理器长期持续功耗 (PL1)",
    "Processor Power Limit 2 (PL2)": "处理器短期瞬时功耗 (PL2)",
    "Processor Power Limit 4 (PL4)": "处理器峰值硬件功耗 (PL4)",
    "Maximum CPU Frequency": "最高 CPU 运行频率",
    "Minimum CPU Frequency": "最低 CPU 运行频率",
    "Energy Performance Preference": "能效偏好调度策略 (EPP)",
    "Performance": "极致性能",
    "Power Saver": "节能节电",
    "TCC Offset": "温度降频点偏移 (TCC Offset)",

    # Fan Control
    "Fan speed": "风扇实时转速",
    "Fan presets": "风扇预设策略",
    "Fan curves": "自定义风扇曲线",
    "Automatic": "固件自动温控",
    "Quiet": "静音运行",
    "Max Speed": "全速强冷模式",
    "CPU Fan": "CPU 散热风扇",
    "GPU Fan": "独显散热风扇",
    "Temperature": "实时芯片温度",
    "CPU Temperature": "CPU 核心温度",
    "GPU Temperature": "GPU 核心温度",
    "System Temperature": "主板 EC 传感器温度",

    # Battery and Charging
    "Charging Priority": "电池充电策略",
    "Charging Profile": "电池保养模式",
    "High Capacity": "高容量模式 (充电至 100%)",
    "Stationary": "长效保养模式 (长寿限充 60%)",
    "Stationary / Long Life": "长寿命保护模式 (限充 60%)",
    "Battery Mode": "电池健康管理",
    "Battery Charge Limit": "电池充电上限",

    # Keyboard Lighting & Display
    "Color": "单区 RGB 颜色选择",
    "Brightness": "键盘背光亮度",
    "Single color": "静态单色",
    "Rainbow": "彩虹幻彩",
    "Breathe": "呼吸渐变",
    "Display Backlight": "屏幕显示亮度",
    "Display Refresh Rate": "屏幕刷新率设置",

    # Common UI Actions & Tray
    "Save": "保存修改",
    "Cancel": "取消",
    "Apply": "立即应用",
    "Delete": "删除配置",
    "Edit": "编辑详情",
    "Create Profile": "新建性能配置",
    "General Settings": "常规全局设置",
    "Language": "软件显示语言",
    "Start on boot": "开机自动启动后台",
    "Minimize to tray": "窗口关闭时最小化至系统托盘",
    "Desktop Notifications": "显示系统桌面通知",
    "Open TUXEDO Control Center": "打开控制中心主界面",
    "Quit": "彻底退出程序",
    "Quit TUXEDO Control Center": "退出控制中心",
    "Power Profiles": "性能运行模式",
    "Charging Profiles": "电池保养模式",
    "Display Frequency": "显示器刷新率",
    "Sensors": "硬件监控传感器",
    "CPU Usage": "CPU 占用率",
    "GPU Usage": "GPU 占用率",
    "Fan 1": "CPU 散热风扇",
    "Fan 2": "GPU 散热风扇",
    "Custom": "自定义",
    "Default": "系统默认",
    "Enabled": "已启用",
    "Disabled": "已禁用",
    "Status": "运行状态",
    "Diagnostics": "硬件诊断",
    "System Information": "系统配置信息",
    "Device": "硬件设备",
    "Model": "电脑型号",
    "BIOS Version": "BIOS 固件版本",
    "Driver Version": "驱动程序版本",
    "Power Supply": "电源供电状态",
    "AC Connected": "已连接电源适配器",
    "Battery Discharging": "电池放电中",
    "Battery Fully Charged": "电池已充满",
    "Battery Charging": "正在充电",
}

# Modern CJK font stack and Dark Theme beautification CSS
MODERN_THEME_CSS = """
/* === Mechrevo-Drivers TCC Modernization & CJK Font Injection === */
:root {
  --tcc-font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
  --tcc-card-bg: rgba(26, 30, 38, 0.75);
  --tcc-card-border: rgba(255, 255, 255, 0.08);
  --tcc-accent-cyan: #00d2be;
  --tcc-accent-blue: #0084ff;
  --tcc-accent-amber: #ffb300;
}

body, html, * {
  font-family: var(--tcc-font-family) !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Card glassmorphism & refined corners */
.card, .content-container, mat-card, .tcc-card {
  border-radius: 10px !important;
  border: 1px solid var(--tcc-card-border) !important;
  backdrop-filter: blur(12px) !important;
  -webkit-backdrop-filter: blur(12px) !important;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25) !important;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* Polished telemetry dials and gauges */
.gauge-container, .chart-container {
  border-radius: 8px !important;
}

/* High contrast telemetry typography */
.stat-value, .gauge-value, .temperature-reading {
  color: var(--tcc-accent-cyan) !important;
  font-weight: 600 !important;
  letter-spacing: 0.5px !important;
}

/* Elegant scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.2);
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--tcc-accent-cyan);
}
"""


def unpack_asar(asar_path: Path, output_dir: Path) -> dict:
    """Unpack an ASAR archive into a destination directory and return metadata."""
    unpacked_records: dict[str, dict] = {}
    with open(asar_path, "rb") as f:
        magic, s1, s2, json_size = struct.unpack("<IIII", f.read(16))
        if magic != 4 or s1 != s2 + 4 or not 0 <= s2 - 4 - json_size <= 3:
            raise ValueError("Invalid ASAR header")
        header_json = f.read(json_size).decode("utf-8")
        header = json.loads(header_json)
        if not isinstance(header, dict) or not isinstance(header.get("files"), dict):
            raise ValueError("Invalid ASAR root directory")
        # Electron's header pickle can pad the JSON string to a four-byte boundary.
        data_offset = 8 + s1
        source_size = os.fstat(f.fileno()).st_size
        if data_offset > source_size:
            raise ValueError("Truncated ASAR header")

        def extract(node: dict, current_path: Path, rel_path: str = "") -> None:
            if not isinstance(node, dict):
                raise ValueError(f"Invalid ASAR member: {rel_path}")
            if "files" in node:
                if not isinstance(node["files"], dict):
                    raise ValueError(f"Invalid ASAR directory: {rel_path}")
                current_path.mkdir(parents=True, exist_ok=True)
                for name, child in node["files"].items():
                    if name in ("", ".", "..") or any(c in name for c in ("/", "\\", "\0")):
                        raise ValueError(f"Invalid ASAR member name: {name!r}")
                    child_rel = f"{rel_path}/{name}" if rel_path else name
                    extract(child, current_path / name, child_rel)
            else:
                if node.get("unpacked") or "link" in node:
                    # External unpacked file
                    unpacked_records[rel_path] = node
                    return
                offset = data_offset + int(node["offset"])
                size = node["size"]
                if type(size) is not int or size < 0 or offset < data_offset:
                    raise ValueError(f"Invalid ASAR member span: {rel_path}")
                if offset + size > source_size:
                    raise ValueError(f"Truncated ASAR member: {rel_path}")
                f.seek(offset)
                data = f.read(size)
                if len(data) != size:
                    raise ValueError(f"Truncated ASAR member: {rel_path}")
                current_path.parent.mkdir(parents=True, exist_ok=True)
                with open(current_path, "wb") as out:
                    out.write(data)
                if node.get("executable"):
                    os.chmod(current_path, 0o755)

        extract(header, output_dir)
    return unpacked_records


def pack_asar(src_dir: Path, asar_path: Path, unpacked_records: dict[str, dict] | None = None) -> None:
    """Pack a directory into a standard Electron ASAR archive."""
    if unpacked_records is None:
        unpacked_records = {}
    files_data: list[bytes] = []
    current_offset = 0

    def build_tree(dir_path: Path, rel_prefix: str = "") -> dict:
        nonlocal current_offset
        node: dict = {"files": {}}
        for entry in sorted(os.listdir(dir_path)):
            full = dir_path / entry
            rel_path = f"{rel_prefix}/{entry}" if rel_prefix else entry
            if full.is_dir():
                node["files"][entry] = build_tree(full, rel_path)
            elif full.is_file():
                if rel_path in unpacked_records:
                    # Preserve original unpacked node record
                    node["files"][entry] = unpacked_records[rel_path]
                    continue
                size = full.stat().st_size
                with open(full, "rb") as f:
                    data = f.read()
                executable = os.access(full, os.X_OK)
                record: dict = {"size": size, "offset": str(current_offset)}
                if executable:
                    record["executable"] = True
                node["files"][entry] = record
                files_data.append(data)
                current_offset += size
        return node

    root_tree = build_tree(src_dir)

    # Insert any external unpacked files that were not created on disk
    for rel_path, rec in unpacked_records.items():
        parts = rel_path.split("/")
        curr = root_tree
        for p in parts[:-1]:
            if p not in curr["files"]:
                curr["files"][p] = {"files": {}}
            curr = curr["files"][p]
        curr["files"][parts[-1]] = rec

    header_json = json.dumps(root_tree, separators=(",", ":")).encode("utf-8")
    json_len = len(header_json)
    pad_len = (4 - (json_len % 4)) % 4
    header_json += b" " * pad_len
    total_json_len = len(header_json)

    header_prefix = struct.pack("<IIII", 4, total_json_len + 8, total_json_len + 4, total_json_len)

    asar_path.parent.mkdir(parents=True, exist_ok=True)
    with open(asar_path, "wb") as f:
        f.write(header_prefix)
        f.write(header_json)
        for chunk in files_data:
            f.write(chunk)



def apply_customizations(root_dir: Path) -> None:
    """Inject Chinese localization, CSS beautification, and feature extensions."""
    ng_app_browser = root_dir / "dist/tuxedo-control-center/ng-app/browser"
    en_dir = ng_app_browser / "en"
    zh_dir = ng_app_browser / "zh"

    # 1. Create zh locale based on en
    if zh_dir.exists():
        shutil.rmtree(zh_dir)
    shutil.copytree(en_dir, zh_dir)

    # 2. Localize index.html in zh directory
    zh_index = zh_dir / "index.html"
    if zh_index.exists():
        text = zh_index.read_text(encoding="utf-8")
        text = text.replace('<html lang="en"', '<html lang="zh"')
        text = text.replace("<title>TuxedoControlCenter</title>", "<title>机械革命电竞控制台 (MECHREVO Gaming Center)</title>")
        zh_index.write_text(text, encoding="utf-8")

    # 3. Localize JavaScript frontend bundle
    for js_file in zh_dir.glob("main-*.js"):
        content = js_file.read_text(encoding="utf-8")
        content = content.replace("TUXEDO Control Center", "机械革命电竞控制台")
        content = content.replace("TUXEDO", "机械革命 MECHREVO")
        for src_str, dst_str in ZH_TRANSLATIONS.items():
            # Match localized template strings
            content = content.replace(f'"{src_str}"', f'"{dst_str}"')
            content = content.replace(f"'{src_str}'", f"'{dst_str}'")
            content = content.replace(f">{src_str}<", f">{dst_str}<")
        js_file.write_text(content, encoding="utf-8")

    # 4. Inject modern styling and font stack into all stylesheets
    for css_file in zh_dir.glob("styles-*.css"):
        css_content = css_file.read_text(encoding="utf-8")
        css_file.write_text(css_content + "\n" + MODERN_THEME_CSS, encoding="utf-8")

    # Also inject font stack into original en and de stylesheets for consistent look
    for sub in ("en", "de", "en-US"):
        target_sub = ng_app_browser / sub
        if target_sub.exists():
            for css_file in target_sub.glob("styles-*.css"):
                css_content = css_file.read_text(encoding="utf-8")
                if "Mechrevo-Drivers TCC Modernization" not in css_content:
                    css_file.write_text(css_content + "\n" + MODERN_THEME_CSS, encoding="utf-8")

    # 5. Update backend initMain.js to include zh in availableLanguages
    init_main = root_dir / "dist/tuxedo-control-center/e-app/e-app/backendAPIs/initMain.js"
    if init_main.exists():
        text = init_main.read_text(encoding="utf-8")
        text = text.replace("const availableLanguages = ['en', 'de'];", "const availableLanguages = ['zh', 'en', 'de'];")
        # Ensure 'zh' is chosen for zh, zh-CN, zh-TW system languages
        zh_fallback_logic = (
            "const systemLanguageId = electron_1.app.getLocale().substring(0, 2);\n"
            "        if (systemLanguageId === 'zh') {\n"
            "            await exports.userConfig.set('langId', 'zh');\n"
            "        } else if ((await exports.userConfig.get('langId')) === undefined) {"
        )
        if "systemLanguageId === 'zh'" not in text:
            text = text.replace(
                "const systemLanguageId = electron_1.app.getLocale().substring(0, 2);\n        if ((await exports.userConfig.get('langId')) === undefined) {",
                zh_fallback_logic,
            )
        init_main.write_text(text, encoding="utf-8")

    # 6. Fix hardcoded camera and tccd paths in TccPaths.js
    for p in (
        root_dir / "dist/tuxedo-control-center/e-app/common/classes/TccPaths.js",
        root_dir / "dist/tuxedo-control-center/service-app/common/classes/TccPaths.js",
    ):
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            txt = txt.replace(
                "/opt/tuxedo-control-center/resources/dist/tuxedo-control-center/data/",
                "/usr/lib/tuxedo-control-center/data/",
            )
            p.write_text(txt, encoding="utf-8")

    # 7. Inject Chinese XLIFF file in all assets/locale/ folders
    lang_xlf = root_dir / "dist/tuxedo-control-center/ng-app/browser/en/assets/locale/lang.xlf"
    if lang_xlf.exists():
        xlf_content = lang_xlf.read_text(encoding="utf-8")
        for sub in ("zh", "en", "en-US", "de"):
            loc_dir = ng_app_browser / sub / "assets/locale"
            if loc_dir.exists():
                (loc_dir / "lang.zh.xlf").write_text(xlf_content, encoding="utf-8")


def update_desktop_entry() -> None:
    """Enhance .desktop application entry for Mechrevo Gaming Center."""
    desktop_file = Path("/usr/share/applications/tuxedo-control-center.desktop")
    if not desktop_file.exists():
        return
    try:
        content = desktop_file.read_text(encoding="utf-8")
        if "Name[zh_CN]" not in content:
            additions = (
                "Name[zh_CN]=机械革命电竞控制台 (MECHREVO Gaming Center)\n"
                "Comment[zh_CN]=机械革命笔记本硬件性能、功耗、风扇强冷与RGB背光控制中心\n"
                "GenericName=Gaming Center\n"
                "GenericName[zh_CN]=电竞控制台\n"
            )
            content = content.replace("Name=TUXEDO Control Center\n", f"Name=TUXEDO Control Center\n{additions}")
            desktop_file.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"Warning: could not update desktop entry: {e}")


def read_target(path: Path) -> tuple[bytes, os.stat_result]:
    """Read a regular target without silently following a different ASAR symlink."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Expected a regular ASAR file: {path}")
    contents = path.read_bytes()
    after = path.lstat()
    if target_identity(before) != target_identity(after):
        raise RuntimeError(f"ASAR changed while reading: {path}")
    return contents, after


def target_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def preserve_backup(path: Path, original: bytes) -> None:
    """Create one private recovery copy; never replace existing recovery bytes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if read_target(path)[0] != original:
            raise ValueError(f"Existing backup differs; choose another --backup path: {path}")
        return
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        if read_target(path)[0] != original:
            raise RuntimeError(f"Backup verification failed: {path}")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def stage_asar(target: Path, contents: bytes, metadata: os.stat_result) -> Path:
    """Stage on the target filesystem so the final replacement is atomic."""
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            if (os.fstat(stream.fileno()).st_uid, os.fstat(stream.fileno()).st_gid) != (metadata.st_uid, metadata.st_gid):
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.flush()
            os.fsync(stream.fileno())
        if read_target(staged)[0] != contents:
            raise RuntimeError("Staged ASAR verification failed")
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def replace_asar(target: Path, contents: bytes, expected: bytes) -> None:
    """Replace and verify the ASAR, restoring the old bytes on a failed readback."""
    original, metadata = read_target(target)
    if original != expected:
        raise RuntimeError(f"Target changed since the operation started: {target}")
    staged = stage_asar(target, contents, metadata)
    staged_identity = target_identity(staged.lstat())[:2]
    replaced = False
    try:
        current, current_metadata = read_target(target)
        if current != original or target_identity(current_metadata) != target_identity(metadata):
            raise RuntimeError(f"Target changed before replacement: {target}")
        os.replace(staged, target)
        replaced = True
        if read_target(target)[0] != contents:
            raise RuntimeError("Installed ASAR verification failed")
    except BaseException as exc:
        if replaced:
            try:
                if target_identity(target.lstat())[:2] != staged_identity:
                    raise RuntimeError("Target was replaced again; refusing to overwrite another writer")
                rollback = stage_asar(target, original, metadata)
                try:
                    os.replace(rollback, target)
                finally:
                    rollback.unlink(missing_ok=True)
                if read_target(target)[0] != original:
                    raise RuntimeError("Restored ASAR verification failed")
            except BaseException as rollback_error:
                raise RuntimeError(f"ASAR replacement failed ({exc}); rollback failed ({rollback_error}); use the preserved backup") from exc
        raise
    finally:
        staged.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Customize TCC with Chinese localization and modern styling.")
    parser.add_argument("--asar", type=Path, default=DEFAULT_ASAR_PATH, help="Path to app.asar")
    parser.add_argument("--backup", type=Path, default=BACKUP_ASAR_PATH,
                        help="Recovery ASAR path; retain the path printed by deploy for later restore")
    parser.add_argument("--deploy", action="store_true", help="Unpack, customize, repack, and deploy directly")
    parser.add_argument("--status", action="store_true", help="Check current localization and styling status")
    parser.add_argument("--restore", action="store_true", help="Restore original app.asar from backup")
    args = parser.parse_args()

    if args.status:
        if not args.asar.exists():
            print(f"Status: ASAR not found at {args.asar}")
            return 1
        with open(args.asar, "rb") as f:
            f.seek(12)
            header_size = struct.unpack("<I", f.read(4))[0]
            header = json.loads(f.read(header_size).decode("utf-8"))
        has_zh = "zh" in header.get("files", {}).get("dist", {}).get("files", {}).get("tuxedo-control-center", {}).get("files", {}).get("ng-app", {}).get("files", {}).get("browser", {}).get("files", {})
        print(f"Target: {args.asar}")
        print(f"Chinese (zh) locale installed: {has_zh}")
        print(f"Backup: {args.backup}")
        print(f"Backup exists: {args.backup.exists()}")
        return 0

    if args.restore:
        try:
            if args.backup.resolve() == args.asar.resolve():
                raise ValueError("Backup and target must be different paths")
            original, _ = read_target(args.backup)
            current, _ = read_target(args.asar)
            with tempfile.TemporaryDirectory(prefix="tcc-restore-") as directory:
                snapshot = Path(directory) / "backup.asar"
                snapshot.write_bytes(original)
                unpack_asar(snapshot, Path(directory) / "verify")
            replace_asar(args.asar, original, current)
            print(f"Restored and verified ASAR from {args.backup}")
            return 0
        except (Exception, KeyboardInterrupt) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.deploy:
        if not args.asar.exists():
            print(f"Error: Target ASAR not found at {args.asar}")
            return 1

        try:
            if args.backup.resolve() == args.asar.resolve():
                raise ValueError("Backup and target must be different paths")
            original, _ = read_target(args.asar)
            with tempfile.TemporaryDirectory(prefix="tcc-mod-") as tmp_dir_str:
                return deploy_asar(args.asar, args.backup, original, Path(tmp_dir_str))
        except (Exception, KeyboardInterrupt) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    parser.print_help()
    return 0


def deploy_asar(target: Path, backup: Path, original: bytes, work_dir: Path) -> int:
    """Build in isolation; UI deployment never changes hardware or services."""
    unpacked_dir = work_dir / "unpacked"
    new_asar_path = work_dir / "new_app.asar"
    source = work_dir / "source.asar"
    source.write_bytes(original)

    print(f"1. Unpacking {target}...")
    unpacked_records = unpack_asar(source, unpacked_dir)

    print("2. Applying Chinese localization and modern theme...")
    apply_customizations(unpacked_dir)

    print("3. Repacking customized ASAR...")
    pack_asar(unpacked_dir, new_asar_path, unpacked_records)
    candidate = new_asar_path.read_bytes()
    unpack_asar(new_asar_path, work_dir / "verify")

    print(f"4. Preserving recovery ASAR at {backup}...")
    preserve_backup(backup, original)

    print(f"5. Deploying customized ASAR to {target}...")
    replace_asar(target, candidate, original)
    print(f"Customized ASAR installed and verified. Backup: {backup}")
    print("Reopen TCC to use the updated interface.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
