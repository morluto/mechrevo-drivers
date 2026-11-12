#!/usr/bin/env python3
"""Local, bounded PCM WAV measurements; never records audio or controls hardware.

Requires NumPy, already supplied by the caller's environment. No network access.
The generated candidates describe sound changes, not their physical cause.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

MAX_WAV_BYTES = 256 * 1024 * 1024
MAX_DURATION_SECONDS = 600
MAX_TELEMETRY_BYTES = 16 * 1024 * 1024
MAX_TELEMETRY_ROWS = 20000
MAX_JSON_LINE_BYTES = 65536
MIN_SIGNAL_DBFS = -80.0
MAX_TELEMETRY_AGE_SECONDS = 2.0


class AnalysisError(ValueError):
    """Input cannot support a complete, bounded analysis."""


def parse_timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AnalysisError("timestamp must be an ISO 8601 string with a UTC offset") from exc
    if result.tzinfo is None:
        raise AnalysisError("timestamp must include a UTC offset")
    try:
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise AnalysisError("timestamp falls outside representable UTC range") from exc


def db(value: float) -> float | None:
    """Amplitude in dBFS, with digital zero represented by null, never -Infinity."""
    return round(20 * math.log10(value), 4) if value > 0 else None


def inspect_wav(path: Path) -> dict:
    """Validate RIFF boundaries before trusting frame counts or allocating arrays."""
    size = path.stat().st_size
    if size > MAX_WAV_BYTES:
        raise AnalysisError(f"WAV exceeds {MAX_WAV_BYTES} byte limit")
    if size < 44:
        raise AnalysisError("truncated WAV header")
    with path.open("rb") as handle:
        header = handle.read(12)
        if header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise AnalysisError("only little-endian RIFF WAVE is supported (no RF64/RIFX)")
        riff_end = struct.unpack_from("<I", header, 4)[0] + 8
        if riff_end != size:
            raise AnalysisError("RIFF length differs from file size: truncated or trailing data")
        offset, fmt, data, chunks = 12, None, None, 0
        while offset < riff_end:
            chunks += 1
            if chunks > 4096:
                raise AnalysisError("RIFF exceeds 4096 chunk limit")
            if offset + 8 > riff_end:
                raise AnalysisError("truncated RIFF chunk header")
            handle.seek(offset)
            chunk_header = handle.read(8)
            if len(chunk_header) != 8:
                raise AnalysisError("WAV changed while reading RIFF chunk header")
            chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)
            start = offset + 8
            end = start + chunk_size
            if end + (chunk_size % 2) > riff_end:
                raise AnalysisError("truncated RIFF chunk payload")
            if chunk_id == b"fmt ":
                if fmt is not None or chunk_size < 16:
                    raise AnalysisError("duplicate or truncated PCM format chunk")
                format_data = handle.read(16)
                if len(format_data) != 16:
                    raise AnalysisError("WAV changed while reading PCM format")
                fmt = struct.unpack("<HHIIHH", format_data)
            elif chunk_id == b"data":
                if data is not None:
                    raise AnalysisError("multiple data chunks are unsupported")
                data = (start, chunk_size)
            offset = end + (chunk_size % 2)
        if fmt is None or data is None:
            raise AnalysisError("WAV requires one format and one data chunk")
        encoding, channels, rate, byte_rate, block_align, bits = fmt
        if encoding != 1 or bits != 16:
            raise AnalysisError("only uncompressed signed PCM 16-bit WAV is supported")
        if channels not in (1, 2):
            raise AnalysisError("only mono or stereo WAV is supported")
        if not 8000 <= rate <= 192000:
            raise AnalysisError("sample rate must be between 8000 and 192000 Hz")
        if block_align != 2 * channels or byte_rate != rate * block_align:
            raise AnalysisError("inconsistent PCM byte rate or frame alignment")
        if data[1] == 0 or data[1] % block_align:
            raise AnalysisError("empty or incomplete PCM frames")
        frames = data[1] // block_align
        if frames / rate > MAX_DURATION_SECONDS:
            raise AnalysisError(f"WAV exceeds {MAX_DURATION_SECONDS} second limit")
    return {"size_bytes": size, "sample_rate_hz": rate, "channels": channels,
            "bits_per_sample": bits, "frames": frames, "duration_seconds": frames / rate,
            "data_offset": data[0], "data_bytes": data[1]}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _peaks(power: np.ndarray, frequencies: np.ndarray, valid: bool) -> list[dict]:
    if not valid:
        return []
    local = np.flatnonzero((power[1:-1] > power[:-2]) & (power[1:-1] >= power[2:])) + 1
    local = local[(frequencies[local] >= 20) & (frequencies[local] <= 20000)]
    selected = []
    total = float(np.sum(power))
    for index in sorted(local, key=lambda i: power[i], reverse=True):
        frequency = float(frequencies[index])
        if all(abs(frequency - item["frequency_hz"]) >= 20 for item in selected):
            selected.append({"frequency_hz": round(frequency, 2),
                             "bin_power_fraction": round(float(power[index]) / total, 6)})
        if len(selected) == 5:
            break
    return selected


# @mark mechrevo.fan_diagnostics role=analysis
def measure_windows(path: Path, info: dict) -> list[dict]:
    """One second at a time. Stereo energies are averaged, never waveform-mixed."""
    rate, channels = info["sample_rate_hz"], info["channels"]
    frequencies = np.fft.rfftfreq(rate, 1 / rate)
    previous_spectrum = None
    windows = []
    with path.open("rb") as handle:
        handle.seek(info["data_offset"])
        remaining = info["frames"]
        while remaining:
            frames = min(rate, remaining)
            raw = handle.read(frames * channels * 2)
            if len(raw) != frames * channels * 2:
                raise AnalysisError("PCM payload changed or became truncated during reading")
            integers = np.frombuffer(raw, dtype="<i2").reshape(-1, channels)
            samples = integers.astype(np.float64) / 32768
            raw_rms = float(np.sqrt(np.mean(samples ** 2)))
            peak = float(np.max(np.abs(samples)))
            dc_offsets = np.mean(samples, axis=0)
            centered = samples - dc_offsets
            rms = float(np.sqrt(np.mean(centered ** 2)))
            level = db(rms)
            valid = level is not None and level > MIN_SIGNAL_DBFS
            tapered = centered * np.hanning(frames)[:, None]
            transform = np.fft.rfft(tapered, n=rate, axis=0)
            power = np.mean(np.abs(transform) ** 2, axis=1)
            power[0] = 0
            total = float(np.sum(power))
            spectrum = np.sqrt(power)
            spectrum_sum = float(np.sum(spectrum))
            normalized = spectrum / spectrum_sum if spectrum_sum else np.zeros_like(spectrum)
            flux = None
            if valid and frames == rate and previous_spectrum is not None:
                flux = round(float(np.sum(np.maximum(normalized - previous_spectrum, 0))), 6)
            previous_spectrum = normalized if valid and frames == rate else None
            bands = {}
            for name, low, high in (("low", 20, 250), ("mid", 250, 2000),
                                    ("high", 2000, min(20000, rate / 2))):
                fraction = float(np.sum(power[(frequencies >= low) & (frequencies < high)]))
                bands[name] = {"lower_hz": low, "upper_hz": high,
                               "power_fraction": round(fraction / total, 6) if valid and total else None}
            envelope_frames = max(1, rate // 50)
            count = frames // envelope_frames
            envelope = np.sqrt(np.mean(centered[:count * envelope_frames].reshape(
                count, envelope_frames, channels) ** 2, axis=(1, 2))) if count else np.array([])
            envelope_mean = float(np.mean(envelope)) if len(envelope) else 0
            envelope_cv = (float(np.std(envelope)) / envelope_mean) if envelope_mean and valid else None
            crest = db(float(np.max(np.abs(centered))) / rms) if valid else None
            windows.append({"index": len(windows), "start_seconds": len(windows),
                            "duration_seconds": round(frames / rate, 6),
                            "signal_status": "valid_signal" if valid else "no_valid_signal",
                            "rms_dbfs": level, "raw_rms_dbfs": db(raw_rms),
                            "dc_offset_per_channel_full_scale": [round(float(x), 8) for x in dc_offsets],
                            "peak_dbfs": db(peak),
                            "clipped_sample_fraction": round(float(np.mean(
                                (integers == -32768) | (integers == 32767))), 8),
                            "spectral_peaks": _peaks(power, frequencies, valid),
                            "bands": bands, "spectral_flux": flux,
                            "crest_factor_db": crest,
                            "rms_envelope_cv": round(envelope_cv, 6) if envelope_cv is not None else None})
            remaining -= frames
    return windows


def candidate_changes(windows: list[dict]) -> dict:
    levels = [w["rms_dbfs"] for w in windows if w["signal_status"] == "valid_signal"]
    if not levels:
        return {"reference_rms_dbfs": None, "reference_method": "20th percentile of valid windows",
                "status": "no_valid_signal", "segments": []}
    reference = float(np.percentile(levels, 20))
    segments = []
    for window in windows:
        reasons = []
        if window["signal_status"] == "valid_signal":
            if window["rms_dbfs"] - reference >= 6:
                reasons.append("rms_at_least_6_db_above_relative_reference")
            if (window["crest_factor_db"] or 0) >= 18 and (window["rms_envelope_cv"] or 0) >= 0.75:
                reasons.append("impulsive_envelope")
            if (window["spectral_flux"] or 0) >= 0.35:
                reasons.append("large_spectral_change")
        window["candidate_reasons"] = reasons
        if reasons:
            end = window["start_seconds"] + window["duration_seconds"]
            if segments and segments[-1]["end_seconds"] == window["start_seconds"]:
                segments[-1]["end_seconds"] = end
                segments[-1]["reasons"] = sorted(set(segments[-1]["reasons"] + reasons))
            else:
                segments.append({"start_seconds": window["start_seconds"], "end_seconds": end,
                                 "label": "candidate_sound_change", "reasons": reasons})
    return {"reference_rms_dbfs": round(reference, 4),
            "reference_method": "20th percentile of valid windows; not a known healthy baseline",
            "status": "measured", "segments": segments}


def load_telemetry(path: Path) -> tuple[list[dict], list[str]]:
    if path.stat().st_size > MAX_TELEMETRY_BYTES:
        raise AnalysisError("telemetry exceeds 16 MiB bound")
    rows, warnings = [], []
    with path.open("rb") as handle:
        total_bytes, line_number = 0, 0
        while line := handle.readline(MAX_JSON_LINE_BYTES + 1):
            line_number += 1
            total_bytes += len(line)
            if len(line) > MAX_JSON_LINE_BYTES or line_number > MAX_TELEMETRY_ROWS:
                raise AnalysisError("telemetry exceeds row count or line size bound")
            if total_bytes > MAX_TELEMETRY_BYTES:
                raise AnalysisError("telemetry grew beyond 16 MiB bound")
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise AnalysisError("telemetry row is not an object")
                row["_time"] = parse_timestamp(row.get("timestamp"))
                if not isinstance(row.get("raw"), dict):
                    raise AnalysisError("telemetry raw field missing")
                rows.append(row)
            except (ValueError, UnicodeError, RecursionError) as exc:
                warnings.append(f"telemetry line {line_number} unavailable: {exc}")
    rows.sort(key=lambda row: row["_time"])
    # Equal timestamps cannot establish which measurement was current.
    duplicate_times = {rows[i]["_time"] for i in range(1, len(rows))
                       if rows[i]["_time"] == rows[i-1]["_time"]}
    if duplicate_times:
        warnings.append("duplicate telemetry timestamps removed as ambiguous")
        rows = [row for row in rows if row["_time"] not in duplicate_times]
    return rows, warnings


def _number(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def align_telemetry(windows: list[dict], rows: list[dict], start: datetime | None) -> None:
    times = [row["_time"] for row in rows]
    fields = {"cpu_fan": ("cpu_fan_rpm", 1), "gpu_fan": ("gpu_fan_rpm", 1),
              "cpu_ec_temperature": ("cpu_ec_temperature_celsius", 1000),
              "gpu_ec_temperature": ("gpu_ec_temperature_celsius", 1000),
              "cpu_package_temperature": ("cpu_package_temperature_celsius", 1000)}
    for window in windows:
        clock_overflow = False
        try:
            target = (start + timedelta(seconds=window["start_seconds"] + window["duration_seconds"] / 2)
                      if start is not None else None)
        except OverflowError:
            target, clock_overflow = None, True
        reading = {name: None for name, _ in fields.values()}
        reading.update({"cpu_busy_percent": None, "source_timestamp": None,
                        "offset_from_window_center_seconds": None, "alignment": "unknown",
                        "reason": ("audio_timestamp_out_of_range" if clock_overflow else
                                   "no_audio_time_anchor" if target is None else "no_telemetry")})
        if target is not None and times:
            if target < times[0] or target > times[-1]:
                reading["reason"] = "outside_telemetry_time_range"
            else:
                insertion = bisect.bisect_left(times, target)
                choices = [i for i in (insertion - 1, insertion) if 0 <= i < len(rows)]
                index = min(choices, key=lambda i: abs((times[i] - target).total_seconds()))
                row = rows[index]
                delta = (times[index] - target).total_seconds()
                if abs(delta) > MAX_TELEMETRY_AGE_SECONDS:
                    reading["reason"] = "nearest_telemetry_stale"
                else:
                    for raw_name, (name, divisor) in fields.items():
                        value = _number(row["raw"].get(raw_name))
                        reading[name] = value / divisor if value is not None else None
                    interval = row.get("cpu_interval")
                    busy = _number(interval.get("busy_percent")) if isinstance(interval, dict) else None
                    reading.update({"cpu_busy_percent": busy if busy is not None and busy <= 100 else None,
                                    "source_timestamp": times[index].isoformat(),
                                    "offset_from_window_center_seconds": round(delta, 6),
                                    "alignment": "approximate", "reason": "nearest_valid_timestamp"})
        window["telemetry"] = reading


def analyze(input_path: Path, telemetry: Path | None = None,
            capture_metadata: Path | None = None, started_at: str | None = None) -> dict:
    info = inspect_wav(input_path)
    before_digest = _sha256(input_path)
    warnings = []
    anchor = None
    anchor_source = "unavailable"
    metadata = {}
    if capture_metadata:
        if capture_metadata.stat().st_size > 65536:
            raise AnalysisError("capture metadata exceeds 64 KiB bound")
        try:
            metadata = json.loads(capture_metadata.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise AnalysisError(f"invalid capture metadata: {exc}") from exc
        if not isinstance(metadata, dict):
            raise AnalysisError("capture metadata must be an object")
    if started_at is not None:
        anchor, anchor_source = parse_timestamp(started_at), "explicit_assumption_from_started_at"
    elif metadata.get("actual_input_start_at"):
        anchor = parse_timestamp(metadata["actual_input_start_at"])
        anchor_source = "capture_actual_input_start_at_unverified"
        warnings.append("actual_input_start_at is caller-supplied; its provenance is not independently verified")
    elif metadata.get("requested_start_at"):
        anchor = parse_timestamp(metadata["requested_start_at"])
        anchor_source = "process_request_approximation"
    if metadata.get("first_output_at"):
        warnings.append("first_output_at is a file flush time, not an audio sampling start")
    windows = measure_windows(input_path, info)
    if _sha256(input_path) != before_digest:
        raise AnalysisError("WAV changed during analysis; retry after recording has stopped")
    candidates = candidate_changes(windows)
    rows = []
    if telemetry:
        rows, telemetry_warnings = load_telemetry(telemetry)
        warnings.extend(telemetry_warnings)
    align_telemetry(windows, rows, anchor)
    if any(w["telemetry"]["reason"] == "audio_timestamp_out_of_range" for w in windows):
        warnings.append("audio wall-clock calculation exceeded timestamp range; affected telemetry is unknown")
    return {"schema_version": 1, "status": "incomplete" if warnings else "complete",
            "purpose": "candidate_sound_changes_only; no source attribution or mechanical diagnosis",
            "sources": {"audio_path": str(input_path), "audio_sha256": before_digest,
                        "telemetry_path": str(telemetry) if telemetry else None,
                        "capture_metadata_path": str(capture_metadata) if capture_metadata else None},
            "audio": {key: value for key, value in info.items() if key not in ("data_offset",)},
            "synchronization": {"anchor_utc": anchor.isoformat() if anchor else None,
                                "anchor_source": anchor_source, "alignment": "approximate" if anchor else "unknown",
                                "sync_uncertainty_seconds": None,
                                "maximum_nearest_telemetry_offset_seconds": MAX_TELEMETRY_AGE_SECONDS},
            "algorithm": {"window_seconds": 1, "minimum_signal_dbfs": MIN_SIGNAL_DBFS,
                          "spectrum": "DC removed; Hann window; FFT channel powers averaged; 1 Hz bins",
                          "stereo_policy": "channel energy average; no waveform mixing or phase cancellation",
                          "units": {"rms_dbfs": "20 log10(DC-removed RMS / digital full-scale)",
                                    "raw_rms_dbfs": "20 log10(raw PCM RMS / digital full-scale), including DC",
                                    "peak_dbfs": "20 log10(peak / digital full-scale)",
                                    "bands": "fraction of DC-removed window spectral power",
                                    "spectral_flux": "positive L1 change of normalized magnitude spectrum",
                                    "rms_envelope_cv": "20 ms envelope standard deviation / mean"}},
            "limitations": ["dBFS is relative digital level, not calibrated sound pressure dB SPL",
                            "microphone gain, AGC, speech, typing, speakers and placement can change these metrics",
                            "no_valid_signal means zero/near-zero recording, not a healthy or quiet fan",
                            "spectral peaks do not identify a fan, bearing defect, or resonant component",
                            "aliasing cannot be inferred or undone; results are limited by Nyquist and capture filters",
                            "one-second windows localize changes only to a window; partial last windows differ in resolution and have no flux comparison",
                            "RPM association uses a guessed/supplied wall-clock anchor with unknown capture latency",
                            "a user marker is receipt time, never a measured acoustic onset",
                            "relative reference is an observed percentile, not a known healthy baseline"],
            "warnings": warnings, "candidate_changes": candidates, "windows": windows}


def write_exclusive(report: dict, output: Path) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="finished PCM16 mono/stereo WAV; never uploaded")
    parser.add_argument("--telemetry", type=Path, help="timestamped JSONL, raw RPM and millidegree temperatures")
    parser.add_argument("--capture-metadata", type=Path, help="local capture JSON; flush time is not sampling onset")
    parser.add_argument("--started-at", help="assumed audio wall-clock start, ISO 8601 with UTC offset")
    parser.add_argument("--output", type=Path, required=True, help="new JSON file; existing file is never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise AnalysisError("output already exists; choose a new path")
        report = analyze(args.input, args.telemetry, args.capture_metadata, args.started_at)
        write_exclusive(report, args.output)
    except (AnalysisError, OSError) as exc:
        print(f"analysis unavailable: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(args.output), "status": report["status"],
                      "windows": len(report["windows"]),
                      "candidate_segments": len(report["candidate_changes"]["segments"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
