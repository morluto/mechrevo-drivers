#!/usr/bin/env python3
"""Run offline repository contracts. Exit 0=passed, 1=failed, 2=incomplete."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, replace
from enum import Enum
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Iterator, TextIO
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Domain(str, Enum):
    POWER = "power"
    THERMAL = "thermal"
    TCC = "tcc"
    THERMALD = "thermald"
    DRIVER = "driver"
    CONSOLE = "console"
    FAN_AUDIO = "fan-audio"
    ALL = "all"


PATTERNS: dict[Domain, tuple[str, ...]] = {
    Domain.POWER: ("test_mechrevo_power.py", "test_power_*.py", "test_peak_limit_trial.py"),
    Domain.THERMAL: ("test_mechrevo_thermal.py", "test_analyze_thermal.py", "test_gpu_pm_trial.py"),
    Domain.TCC: ("test_tcc_*.py",),
    Domain.THERMALD: ("test_thermald_*.py",),
    Domain.DRIVER: ("test_uniwill_*.py", "test_clevo_ioctl_runtime.py", "test_nvidia_power_runtime.py",
                    "test_mechrevo_ec*.py", "test_compare_ec_paths.py", "test_factory_policy_probe.py"),
    Domain.CONSOLE: ("test_console_*.py", "test_mechrevo_catalog.py", "test_mechrevo_hotkey.py"),
    Domain.FAN_AUDIO: ("test_analyze_fan_audio.py",),
    Domain.ALL: ("test_*.py",),
}

# Keep optional tests in ALL; a missing prerequisite makes that scope incomplete.
OPTIONAL_DEPENDENCIES = {"test_analyze_fan_audio.py": ("numpy",)}


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"

    @property
    def exit_code(self) -> int:
        return {Outcome.PASSED: 0, Outcome.FAILED: 1, Outcome.INCOMPLETE: 2}[self]


@dataclass(frozen=True)
class Report:
    domain: str
    modules: tuple[str, ...] = ()
    discovered: int = 0
    ran: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    expected_failures: int = 0
    unexpected_successes: int = 0
    load_errors: tuple[str, ...] = ()
    prerequisites: tuple[tuple[str, str], ...] = ()
    details: tuple[tuple[str, str, str], ...] = ()
    fatal_error: str | None = None
    temporary_directory: str | None = None
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in ("discovered", "ran", "failures", "errors", "skipped", "expected_failures", "unexpected_successes"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("Invalid test count: " + name)

    @property
    def outcome(self) -> Outcome:
        if self.fatal_error or self.failures or self.errors or self.load_errors or self.unexpected_successes:
            return Outcome.FAILED
        if self.prerequisites or not self.ran or self.skipped or self.expected_failures or self.ran != self.discovered:
            return Outcome.INCOMPLETE
        return Outcome.PASSED

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1, "domain": self.domain, "outcome": self.outcome.value,
            "exit_code": self.outcome.exit_code, "scope": "local offline unittest contracts; no hardware acceptance",
            "modules": list(self.modules), "discovered": self.discovered, "ran": self.ran,
            "failures": self.failures, "errors": self.errors, "skipped": self.skipped,
            "expected_failures": self.expected_failures, "unexpected_successes": self.unexpected_successes,
            "load_errors": list(self.load_errors),
            "prerequisites": [{"dependency": dependency, "reason": reason}
                              for dependency, reason in self.prerequisites],
            "details": [{"kind": k, "test": t, "message": m} for k, t, m in self.details],
            "fatal_error": self.fatal_error, "temporary_directory": self.temporary_directory,
            "elapsed_seconds": self.elapsed_seconds,
        }


def temporary_base(root: Path) -> Path:
    local = root / ".local-tests"
    if not local.is_dir() or local.is_symlink():
        raise ValueError("An existing nonsymlink .local-tests directory is required")
    base = Path(os.environ.get("MECHREVO_TEST_TMPDIR", str(local))).absolute()
    if not base.is_dir() or base.is_symlink() or not base.resolve().is_relative_to(local.resolve()):
        raise ValueError("MECHREVO_TEST_TMPDIR must be an existing directory inside .local-tests")
    return base


@contextmanager
def test_environment(directory: Path) -> Iterator[None]:
    """Use documented temp controls; keep external compiler/Node/TypeScript configuration."""
    values = {"MECHREVO_TEST_TMPDIR": str(directory), "UNIWILL_TEST_TMPDIR": str(directory),
              "TMPDIR": str(directory), "PYTHONDONTWRITEBYTECODE": "1"}
    previous = {key: os.environ.get(key) for key in values}
    old_temp, old_bytecode, old_path = tempfile.tempdir, sys.dont_write_bytecode, sys.path[:]
    try:
        os.environ.update(values)
        tempfile.tempdir = str(directory)
        sys.dont_write_bytecode = True
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tempfile.tempdir, sys.dont_write_bytecode = old_temp, old_bytecode
        sys.path[:] = old_path


def evaluate(suite: unittest.TestSuite, loader: unittest.TestLoader, report: Report, stream: TextIO) -> Report:
    """Derive outcome from the real result, including setup/load errors and expected failures."""
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    details: list[tuple[str, str, str]] = []
    for kind, rows in (("failure", result.failures), ("error", result.errors),
                       ("skip", result.skipped), ("expected_failure", result.expectedFailures)):
        details.extend((kind, test.id(), message) for test, message in rows)
    details.extend(("unexpected_success", test.id(), "Unexpected success") for test in result.unexpectedSuccesses)
    return replace(report, discovered=discovered, ran=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   expected_failures=len(result.expectedFailures), unexpected_successes=len(result.unexpectedSuccesses),
                   load_errors=tuple(loader.errors), details=tuple(details))


def verify(root: Path, domain: Domain, stream: TextIO) -> Report:
    if os.geteuid() == 0:
        return Report(domain.value, fatal_error="Refusing root: these offline tests do not need elevated privileges")
    start = time.monotonic()
    report = Report(domain.value)
    try:
        base = temporary_base(root)
        directory = Path(tempfile.mkdtemp(prefix="verify-" + domain.value + "-", dir=base))
        report = replace(report, temporary_directory=str(directory))
        with test_environment(directory), redirect_stdout(stream):
            tests = root / "tests"
            files = sorted({p for pattern in PATTERNS[domain] for p in tests.glob(pattern) if p.is_file()})
            blocked: set[str] = set()
            prerequisites: list[tuple[str, str]] = []
            for path in files:
                for dependency in OPTIONAL_DEPENDENCIES.get(path.name, ()):
                    try:
                        importlib.import_module(dependency)
                    except Exception as exc:
                        blocked.add(path.name)
                        prerequisites.append((dependency, path.name + " requires " + dependency + ": "
                                              + type(exc).__name__ + ": " + str(exc)))
            report = replace(report, modules=tuple(p.name for p in files),
                             prerequisites=tuple(prerequisites))
            loader = unittest.TestLoader()
            suite = unittest.TestSuite()
            for path in files:
                if path.name not in blocked:
                    suite.addTests(loader.discover(str(tests), pattern=path.name, top_level_dir=str(tests)))
            report = evaluate(suite, loader, report, stream)
    except (Exception, KeyboardInterrupt) as exc:
        report = replace(report, fatal_error=type(exc).__name__ + ": " + str(exc))
    return replace(report, elapsed_seconds=time.monotonic() - start)


class CLIError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIError(message)


def main(argv: list[str] | None = None, *, root: Path = ROOT,
         stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    parser = Parser(description=__doc__)
    parser.add_argument("--domain", choices=[d.value for d in Domain], default=Domain.ALL.value)
    parser.add_argument("--output", type=Path, help="new JSON file; never overwrite an existing path")
    fd: int | None = None
    report = Report("unknown", fatal_error="Invocation did not start")
    try:
        args = parser.parse_args(argv)
        domain = Domain(args.domain)
        report = Report(domain.value)
        if os.geteuid() == 0:
            report = Report(domain.value, fatal_error="Refusing root: these offline tests do not need elevated privileges")
        else:
            temporary_base(root)
            if args.output is not None:
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            report = verify(root, domain, stderr)
            if fd is not None:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    fd = None
                    json.dump(report.as_dict(), output, indent=2)
                    output.write("\n")
    except (Exception, KeyboardInterrupt) as exc:
        report = replace(report, fatal_error=type(exc).__name__ + ": " + str(exc))
    finally:
        if fd is not None:
            os.close(fd)
    json.dump(report.as_dict(), stdout, indent=2)
    stdout.write("\n")
    return report.outcome.exit_code


def cli(*, root: Path = ROOT) -> int:
    """Keep inherited child/raw FD stdout on stderr; reserve original stdout for JSON."""
    sys.stdout.flush()
    original = os.dup(1)
    try:
        os.dup2(2, 1)
        with os.fdopen(os.dup(original), "w", encoding="utf-8") as output:
            return main(root=root, stdout=output)
    finally:
        sys.stdout.flush()
        os.dup2(original, 1)
        os.close(original)


if __name__ == "__main__":
    raise SystemExit(cli())
