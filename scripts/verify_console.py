#!/usr/bin/env python3
"""Verify the Rust console without root or hardware. Exit 0/1/2=passed/failed/incomplete."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, TextIO

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_TARGET = "x86_64-pc-windows-gnu"
DEFAULT_TIMEOUT = 900.0
GUI_EMBEDDED_FONTS = (
    "crates/gui/assets/fonts/Manrope.ttf",
)
CONSOLE_REQUIRED_RESOURCES = ("resources/org.mechrevo.console.oem.policy",)
TEST_LOG_MAX_BYTES = 16 * 1024 * 1024
TEST_LOG_MAX_LINE_BYTES = 4096
TEST_SUMMARY = re.compile(
    rb"test result: (ok|FAILED)\. ([0-9]{1,20}) passed; ([0-9]{1,20}) failed; "
    rb"([0-9]{1,20}) ignored; ([0-9]{1,20}) measured; ([0-9]{1,20}) filtered out; "
    rb"finished in [0-9]+(?:\.[0-9]+)?s\r?\n?"
)
CHECKS = (
    ("fmt", ("fmt", "--all", "--check")),
    ("test", ("test", "--workspace", "--all-features", "--locked")),
    ("clippy", ("clippy", "--workspace", "--all-targets", "--all-features", "--locked", "--", "-D", "warnings")),
    ("windows", ("check", "--workspace", "--all-features", "--locked", "--target", WINDOWS_TARGET)),
)


def checked_directory(path: Path) -> Path:
    """Reject symlinks in every existing path component, including the final one."""
    absolute = Path(os.path.abspath(path))
    for part in (absolute, *absolute.parents):
        if part.is_symlink():
            raise ValueError("Symlink directory is not allowed: " + str(part))
    if not absolute.is_dir():
        raise ValueError("An existing nonsymlink directory is required: " + str(absolute))
    return absolute


def artifact_base(root: Path, env: dict[str, str]) -> Path:
    local = checked_directory(root / ".local-tests")
    preferred = local / "console"
    base = Path(env.get("MECHREVO_TEST_TMPDIR", str(preferred if preferred.exists() else local)))
    base = checked_directory(base)
    if not base.is_relative_to(local):
        raise ValueError("Artifacts must be inside the existing nonsymlink .local-tests directory")
    return base


def stable_file_metadata(value: os.stat_result) -> tuple[int, ...]:
    """Ignore read-induced atime updates, but retain identity and nanosecond changes."""
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def source_snapshot(root: Path) -> dict[str, object]:
    """Hash source, GUI assets, packaged resources, and manifests; not atomic."""
    console = checked_directory(root / "console")
    required = (console / "Cargo.toml", console / "Cargo.lock", root / "data/mechrevo-catalog.json",
                root / "data/mechrevo-platform-evidence.json",
                *(console / name for name in GUI_EMBEDDED_FONTS),
                *(console / name for name in CONSOLE_REQUIRED_RESOURCES))
    paths = set(console.rglob("*.rs")) | set(console.rglob("Cargo.toml")) | set(required)
    for directory in (console / "crates/gui/assets", console / "resources"):
        if directory.is_symlink():
            raise ValueError("Symlink source directory is not allowed: " + str(directory))
        # Include licenses and future resource types, retaining symlink entries
        # so the common validation below rejects them instead of following them.
        paths.update(path for path in directory.rglob("*") if path.is_symlink() or not path.is_dir())
    files: dict[str, str] = {}
    missing: list[str] = []
    for path in sorted(paths):
        relative = str(path.relative_to(root))
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("Symlink source directory is not allowed: " + str(parent))
        if path.is_symlink():
            raise ValueError("Symlink source input is not allowed: " + relative)
        try:
            before = path.stat()
        except FileNotFoundError:
            missing.append(relative)
            continue
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Source input is not a regular file: " + relative)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if stable_file_metadata(opened) != stable_file_metadata(before):
                raise ValueError("Source changed before hashing: " + relative)
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
            after = os.fstat(stream.fileno())
        if (stable_file_metadata(before) != stable_file_metadata(after)
                or stable_file_metadata(path.stat()) != stable_file_metadata(after)):
            raise ValueError("Source changed while hashing: " + relative)
        files[relative] = digest.hexdigest()
    if not any(name.endswith(".rs") for name in files):
        missing.append("console/**/*.rs")
    serialized = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(serialized).hexdigest(), "files": files, "missing": missing}


def execute(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float, stream: TextIO) -> int:
    """A timeout kills the entire Cargo process group on POSIX before returning."""
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                          start_new_session=os.name == "posix") as child:
        try:
            return child.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if os.name == "posix":
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                child.kill()
            child.wait()
            raise


def parse_test_log(log: Path, *, max_bytes: int = TEST_LOG_MAX_BYTES,
                   max_line_bytes: int = TEST_LOG_MAX_LINE_BYTES) -> dict[str, object]:
    """Read stable libtest summaries with bounded file and per-line memory budgets."""
    totals = {name: 0 for name in ("passed", "failed", "ignored", "measured", "filtered_out")}
    result: dict[str, object] = {"summary_count": 0, "failed_summaries": 0, "totals": totals,
                                "totals_complete": False, "log_bytes": None, "bytes_scanned": 0,
                                "scan_limit_bytes": max_bytes, "line_limit_bytes": max_line_bytes,
                                "reason": None}
    try:
        with log.open("rb") as stream:
            before = os.fstat(stream.fileno())
            result["log_bytes"] = before.st_size
            if before.st_size > max_bytes:
                result["reason"] = "Test log exceeds the summary scan byte budget"
                return result
            while True:
                line = stream.readline(min(max_line_bytes + 1, max_bytes - result["bytes_scanned"] + 1))
                if not line:
                    break
                result["bytes_scanned"] += len(line)
                if result["bytes_scanned"] > max_bytes or len(line) > max_line_bytes:
                    result["reason"] = "Test log exceeds the summary scan byte or line budget"
                    return result
                match = TEST_SUMMARY.fullmatch(line)
                if match:
                    result["summary_count"] += 1
                    result["failed_summaries"] += match[1] == b"FAILED"
                    for name, count in zip(totals, match.groups()[1:]):
                        totals[name] += int(count)
                elif line.startswith(b"test result:"):
                    result["reason"] = "Unrecognized libtest summary format"
                    return result
            if (stable_file_metadata(before) != stable_file_metadata(os.fstat(stream.fileno()))
                    or stable_file_metadata(before) != stable_file_metadata(log.stat())):
                result["reason"] = "Test log changed during summary parsing"
                return result
        result["totals_complete"] = True
    except OSError as error:
        result["reason"] = type(error).__name__ + ": " + str(error)
    return result


def check_test_execution(record: dict[str, object]) -> None:
    """Exit zero alone cannot prove a configured Cargo runner executed libtest."""
    results = parse_test_log(Path(record["log"]))
    record["test_results"] = results
    totals = results["totals"]
    reason = None
    if results["failed_summaries"] or totals["failed"]:
        record.update(status="failed", reason="Libtest summaries report failed tests")
        return
    if record["status"] != "passed":
        return
    if not results["totals_complete"]:
        reason = results["reason"]
    elif not results["summary_count"]:
        reason = "No stable libtest summaries; test execution was not verified"
    elif not totals["passed"]:
        reason = "Libtest summaries contain zero passed tests"
    elif totals["ignored"] or totals["filtered_out"]:
        reason = "Libtest summaries contain ignored or filtered tests"
    if reason:
        record.update(status="incomplete", reason=reason)


@dataclass
class Report:
    checks_expected: int = len(CHECKS)
    commands: list[dict[str, object]] = field(default_factory=list)
    prerequisites: list[dict[str, object]] = field(default_factory=list)
    source_before: dict[str, object] | None = None
    source_after: dict[str, object] | None = None
    source_unchanged: bool = False
    artifact_directory: str | None = None
    cargo_target_directory: str | None = None
    incomplete_reasons: list[str] = field(default_factory=list)
    fatal_error: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def outcome(self) -> str:
        if self.fatal_error or any(row["status"] == "failed" for row in self.commands):
            return "failed"
        if (not self.commands or len(self.commands) != self.checks_expected or self.incomplete_reasons
                or not self.source_unchanged or any(row["status"] != "passed" for row in self.commands)):
            return "incomplete"
        return "passed"

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "outcome": self.outcome,
                "exit_code": {"passed": 0, "failed": 1, "incomplete": 2}[self.outcome],
                "scope": "local Cargo contracts and Windows target compile check; no hardware or Windows runtime acceptance",
                "checks_expected": self.checks_expected,
                "checks_executed": sum(row["executed"] for row in self.commands),
                "commands": self.commands, "prerequisites": self.prerequisites,
                "source_before": self.source_before, "source_after": self.source_after,
                "source_unchanged": self.source_unchanged,
                "artifact_directory": self.artifact_directory,
                "cargo_target_directory": self.cargo_target_directory,
                "incomplete_reasons": self.incomplete_reasons, "fatal_error": self.fatal_error,
                "elapsed_seconds": self.elapsed_seconds}


def record_command(name: str, argv: list[str], directory: Path, *, root: Path, env: dict[str, str],
                   timeout: float, runner: Callable, reason: str | None = None,
                   prerequisite: bool = False) -> dict[str, object]:
    log = directory / (name + ".log")
    record: dict[str, object] = {"name": name, "argv": argv, "status": "incomplete",
                                 "exit_code": None, "log": str(log), "executed": False,
                                 "timed_out": False, "timeout_seconds": timeout,
                                 "reason": reason, "elapsed_seconds": 0.0}
    start = time.monotonic()
    with log.open("x", encoding="utf-8") as stream:
        if reason:
            stream.write("NOT RUN: " + reason + "\n")
        else:
            record["executed"] = True
            try:
                code = runner(argv, cwd=root / "console", env=env, timeout=timeout, stream=stream)
                if type(code) is not int:
                    raise ValueError("Runner did not return an integer exit code")
                record["exit_code"] = code
                record["status"] = "passed" if code == 0 else ("incomplete" if prerequisite else "failed")
                if code:
                    record["reason"] = "Prerequisite probe failed" if prerequisite else "Command returned nonzero"
            except subprocess.TimeoutExpired:
                record.update(timed_out=True, reason="Command timed out after " + str(timeout) + " seconds")
                stream.write(str(record["reason"]) + "\n")
            except OSError as error:
                record["reason"] = type(error).__name__ + ": " + str(error)
                stream.write(str(record["reason"]) + "\n")
    if name == "test" and record["executed"]:
        check_test_execution(record)
    record["elapsed_seconds"] = time.monotonic() - start
    return record


def verify(root: Path, *, timeout: float = DEFAULT_TIMEOUT, runner: Callable = execute,
           which: Callable = shutil.which, env: dict[str, str] | None = None,
           checks: tuple = CHECKS) -> Report:
    report = Report(checks_expected=len(checks))
    started = time.monotonic()
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ValueError("Refusing root: console checks do not need elevated privileges")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be a positive finite number")
        root = checked_directory(root)
        child_env = dict(os.environ if env is None else env)
        child_env["CARGO_TERM_COLOR"] = "never"
        base = artifact_base(root, child_env)
        directory = Path(tempfile.mkdtemp(prefix="verify-console-", dir=base))
        report.artifact_directory = str(directory)
        if "CARGO_TARGET_DIR" not in child_env:
            target_base = root / ".local-tests/console-target"
            if not target_base.exists():
                target_base.mkdir()
            checked_directory(target_base)
            child_env["CARGO_TARGET_DIR"] = str(target_base)
        report.cargo_target_directory = child_env["CARGO_TARGET_DIR"]
        report.source_before = source_snapshot(root)
        missing = report.source_before["missing"]
        if missing:
            report.incomplete_reasons.append("Missing source inputs: " + ", ".join(missing))
        cargo, rustup = which("cargo"), which("rustup")
        windows_ready = False
        cargo_ready = False
        for name, tool, args in (("cargo-version", cargo, ["--version"]),
                                 ("windows-target", rustup, ["target", "list", "--installed"])):
            row = record_command(name, [tool or name.split("-")[0], *args], directory,
                                 root=root, env=child_env, timeout=min(timeout, 30.0), runner=runner,
                                 reason=None if tool else "Missing prerequisite: " + ("cargo" if name == "cargo-version" else "rustup"),
                                 prerequisite=True)
            report.prerequisites.append(row)
            if name == "cargo-version":
                cargo_ready = row["status"] == "passed"
            elif row["status"] == "passed":
                installed = Path(row["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
                windows_ready = WINDOWS_TARGET in [line.strip() for line in installed]
                if not windows_ready:
                    row.update(status="incomplete", reason="Windows Rust target is not installed: " + WINDOWS_TARGET)
        for name, args in checks:
            reason = None
            if missing:
                reason = "Source inputs are missing"
            elif not cargo_ready:
                reason = "Cargo is unavailable or its version probe did not succeed"
            elif name == "windows" and not windows_ready:
                reason = "Windows Rust target could not be verified: " + WINDOWS_TARGET
            report.commands.append(record_command(name, [cargo or "cargo", *args], directory,
                                   root=root, env=child_env, timeout=timeout, runner=runner, reason=reason))
        report.source_after = source_snapshot(root)
        report.source_unchanged = report.source_before == report.source_after
        if not report.source_unchanged:
            report.incomplete_reasons.append("Source inputs changed during verification; rerun against stable inputs")
    except (Exception, KeyboardInterrupt) as error:
        report.fatal_error = type(error).__name__ + ": " + str(error)
    report.elapsed_seconds = time.monotonic() - started
    return report


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


# @mark mechrevo.console_verification role=verification
def main(argv: list[str] | None = None, *, root: Path = ROOT, stdout: TextIO | None = None,
         runner: Callable = execute, which: Callable = shutil.which) -> int:
    stdout = stdout if stdout is not None else sys.stdout
    parser = Parser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per Cargo check (default: 900)")
    parser.add_argument("--output", type=Path, help="exclusive new JSON receipt; never overwrite an existing path")
    report = Report()
    fd: int | None = None
    try:
        args = parser.parse_args(argv)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ValueError("Refusing root: console checks do not need elevated privileges")
        if args.output is not None:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        report = verify(root, timeout=args.timeout, runner=runner, which=which)
        if fd is not None:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = None
                json.dump(report.as_dict(), stream, indent=2)
                stream.write("\n")
    except (Exception, KeyboardInterrupt) as error:
        report.fatal_error = type(error).__name__ + ": " + str(error)
    finally:
        if fd is not None:
            os.close(fd)
    result = report.as_dict()
    json.dump(result, stdout, indent=2)
    stdout.write("\n")
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
