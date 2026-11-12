"""Known signals and corrupt inputs verify offline audio measurements, not hardware."""
from __future__ import annotations

import contextlib
from datetime import timedelta
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_fan_audio.py"
SPEC = importlib.util.spec_from_file_location("analyze_fan_audio", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)

RATE = 48000


def sine(frequency=440, amplitude=0.1, seconds=1):
    return amplitude * np.sin(2 * np.pi * frequency * np.arange(int(RATE * seconds)) / RATE)


class AudioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fan-audio-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def wav(self, samples, name="input.wav", bits=16):
        path = self.root / name
        values = np.asarray(samples)
        channels = values.shape[1] if values.ndim == 2 else 1
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(channels)
            handle.setsampwidth(bits // 8)
            handle.setframerate(RATE)
            if bits == 16:
                handle.writeframes(np.clip(np.rint(values * 32768), -32768, 32767).astype("<i2").tobytes())
            else:
                handle.writeframes(bytes(int(values.size * bits / 8)))
        return path

    def telemetry(self, rows):
        path = self.root / "telemetry.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def test_known_sine_frequency_and_digital_level(self):
        report = module.analyze(self.wav(sine(440, 0.1)))
        window = report["windows"][0]
        self.assertEqual(window["signal_status"], "valid_signal")
        self.assertAlmostEqual(window["rms_dbfs"], -23.0103, places=2)
        self.assertAlmostEqual(window["peak_dbfs"], -20, places=2)
        self.assertEqual(window["spectral_peaks"][0]["frequency_hz"], 440)
        self.assertGreater(window["bands"]["mid"]["power_fraction"], .999)
        self.assertEqual(report["candidate_changes"]["segments"], [])
        json.dumps(report, allow_nan=False)

    def test_all_zero_is_unusable_not_healthy_or_quiet(self):
        report = module.analyze(self.wav(np.zeros(RATE * 2)))
        self.assertEqual(report["candidate_changes"]["status"], "no_valid_signal")
        self.assertEqual(report["candidate_changes"]["segments"], [])
        for window in report["windows"]:
            self.assertIsNone(window["rms_dbfs"])
            self.assertEqual(window["signal_status"], "no_valid_signal")
            self.assertEqual(window["spectral_peaks"], [])
            self.assertIsNone(window["bands"]["low"]["power_fraction"])
        json.dumps(report, allow_nan=False)

    def test_near_zero_not_valid_signal(self):
        report = module.analyze(self.wav(sine(amplitude=1/32768)))
        self.assertEqual(report["windows"][0]["signal_status"], "no_valid_signal")

    def test_dc_offset_is_not_sound_and_changes_do_not_make_loudness_candidates(self):
        samples = np.concatenate([np.full(RATE, .01), np.full(RATE, .5)])
        report = module.analyze(self.wav(samples))
        self.assertEqual(report["candidate_changes"]["status"], "no_valid_signal")
        self.assertEqual(report["candidate_changes"]["segments"], [])
        self.assertAlmostEqual(report["windows"][1]["raw_rms_dbfs"], -6.0206, places=3)
        self.assertIsNone(report["windows"][1]["rms_dbfs"])

    def test_dc_plus_sine_preserves_ac_sound_level(self):
        mono = module.analyze(self.wav(sine(amplitude=.01), "no-offset.wav"))["windows"][0]
        offset = module.analyze(self.wav(sine(amplitude=.01) + .5, "offset.wav"))["windows"][0]
        self.assertAlmostEqual(mono["rms_dbfs"], offset["rms_dbfs"], places=3)
        self.assertGreater(offset["raw_rms_dbfs"], offset["rms_dbfs"] + 30)
        self.assertEqual(offset["spectral_peaks"][0]["frequency_hz"], 440)

    def test_level_step_yields_candidate_with_window_bounds(self):
        samples = np.concatenate([sine(amplitude=.01) for _ in range(4)] +
                                 [sine(amplitude=.1) for _ in range(2)])
        report = module.analyze(self.wav(samples))
        segments = report["candidate_changes"]["segments"]
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0]["start_seconds"], segments[0]["end_seconds"]), (4, 6))
        self.assertEqual(segments[0]["label"], "candidate_sound_change")
        self.assertIn("rms_at_least_6_db_above_relative_reference", segments[0]["reasons"])

    def test_impulse_recognized_without_diagnosing_source(self):
        impulse = np.zeros(RATE)
        impulse[RATE // 2] = .8
        report = module.analyze(self.wav(impulse))
        self.assertIn("impulsive_envelope", report["windows"][0]["candidate_reasons"])
        self.assertGreater(report["windows"][0]["crest_factor_db"], 40)
        self.assertEqual(report["candidate_changes"]["segments"][0]["label"], "candidate_sound_change")

    def test_spectral_change_same_level_is_detected(self):
        report = module.analyze(self.wav(np.concatenate([sine(200), sine(4000)])))
        self.assertIn("large_spectral_change", report["windows"][1]["candidate_reasons"])
        self.assertGreater(report["windows"][0]["bands"]["low"]["power_fraction"], .999)
        self.assertGreater(report["windows"][1]["bands"]["high"]["power_fraction"], .999)

    def test_antiphase_stereo_does_not_disappear(self):
        source = sine(440, .2)
        mono = module.analyze(self.wav(source, "mono.wav"))["windows"][0]
        stereo = module.analyze(self.wav(np.column_stack([source, -source]), "stereo.wav"))["windows"][0]
        self.assertAlmostEqual(stereo["rms_dbfs"], mono["rms_dbfs"], places=3)
        self.assertEqual(stereo["spectral_peaks"][0]["frequency_hz"], 440)

    def test_clipping_counts_both_pcm_rails(self):
        values = np.tile([1, -1, 0, 0], RATE // 4)
        report = module.analyze(self.wav(values))
        self.assertEqual(report["windows"][0]["clipped_sample_fraction"], .5)

    def test_partial_last_window_is_labeled(self):
        report = module.analyze(self.wav(sine(seconds=1.25)))
        self.assertEqual(len(report["windows"]), 2)
        self.assertEqual(report["windows"][-1]["duration_seconds"], .25)
        self.assertEqual(report["windows"][-1]["start_seconds"], 1)
        self.assertIsNone(report["windows"][-1]["spectral_flux"])
        self.assertEqual(report["candidate_changes"]["segments"], [])

    def test_truncated_payload_rejected_even_if_wave_reader_tolerates_it(self):
        path = self.wav(sine())
        path.write_bytes(path.read_bytes()[:-100])
        with self.assertRaisesRegex(module.AnalysisError, "length|truncated"):
            module.analyze(path)

    def test_wav_truncated_during_format_read_is_clean_error(self):
        path = self.wav(sine())
        captured = path.read_bytes()[:20]
        with patch.object(Path, "open", return_value=io.BytesIO(captured)):
            with self.assertRaises(module.AnalysisError):
                module.inspect_wav(path)

    def test_incomplete_frame_with_correct_riff_size_rejected(self):
        path = self.wav(sine())
        data = bytearray(path.read_bytes()[:-1])
        struct.pack_into("<I", data, 4, len(data) - 8)
        struct.pack_into("<I", data, 40, len(data) - 44)
        path.write_bytes(data)
        with self.assertRaises(module.AnalysisError):
            module.analyze(path)

    def test_unsupported_width_and_channel_count_rejected(self):
        for bits, channels in ((8, 1), (24, 1), (16, 3)):
            with self.subTest(bits=bits, channels=channels):
                path = self.wav(np.zeros((100, channels)), f"{bits}-{channels}.wav", bits=bits)
                with self.assertRaises(module.AnalysisError):
                    module.analyze(path)

    def test_file_and_duration_limits_rejected_before_fft(self):
        path = self.wav(sine())
        with patch.object(module, "MAX_WAV_BYTES", 16), self.assertRaises(module.AnalysisError):
            module.analyze(path)
        with patch.object(module, "MAX_DURATION_SECONDS", .5), self.assertRaises(module.AnalysisError):
            module.analyze(path)

    def test_output_never_overwrites_or_changes_existing_file(self):
        audio = self.wav(sine())
        output = self.root / "existing.json"
        output.write_bytes(b"precious\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(["--input", str(audio), "--output", str(output)]), 2)
        self.assertEqual(output.read_bytes(), b"precious\n")
        with self.assertRaises(FileExistsError):
            module.write_exclusive({"hello": "world"}, output)

    def test_cli_successful_json_has_sources_and_no_raw_audio(self):
        path = self.wav(sine())
        output = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(["--input", str(path), "--output", str(output)]), 0)
        report = json.loads(output.read_text())
        self.assertEqual(len(report["sources"]["audio_sha256"]), 64)
        self.assertEqual(report["audio"]["sample_rate_hz"], 48000)
        self.assertIn("limitations", report)
        self.assertNotIn("samples", report)

    def test_requested_start_anchor_is_approximate_not_file_flush(self):
        path = self.wav(sine())
        metadata = self.root / "capture.json"
        metadata.write_text(json.dumps({"requested_start_at": "2026-10-17T22:24:24Z",
                                        "first_output_at": "2026-10-17T22:24:26Z"}))
        report = module.analyze(path, capture_metadata=metadata)
        self.assertEqual(report["synchronization"]["anchor_utc"], "2026-10-17T22:24:24+00:00")
        self.assertEqual(report["synchronization"]["alignment"], "approximate")
        self.assertIsNone(report["synchronization"]["sync_uncertainty_seconds"])
        metadata.write_text(json.dumps({"first_output_at": "2026-10-17T22:24:26Z"}))
        report = module.analyze(path, capture_metadata=metadata)
        self.assertIsNone(report["synchronization"]["anchor_utc"])

    def test_nearest_timestamp_within_range_and_stale_unknown(self):
        start = module.parse_timestamp("2026-10-17T22:24:24Z")
        rows = [{"_time": start + timedelta(seconds=i), "raw": {"cpu_fan": str(1000+i),
                 "gpu_fan": None, "cpu_ec_temperature": "48000"}} for i in (0, 1, 10)]
        windows = [{"start_seconds": x, "duration_seconds": 1} for x in (-1, 0, 5, 10)]
        module.align_telemetry(windows, rows, start)
        self.assertEqual(windows[0]["telemetry"]["reason"], "outside_telemetry_time_range")
        self.assertEqual(windows[1]["telemetry"]["cpu_fan_rpm"], 1000)
        self.assertEqual(windows[1]["telemetry"]["cpu_ec_temperature_celsius"], 48)
        self.assertIsNone(windows[1]["telemetry"]["gpu_fan_rpm"])
        self.assertEqual(windows[2]["telemetry"]["reason"], "nearest_telemetry_stale")
        self.assertIsNone(windows[2]["telemetry"]["cpu_fan_rpm"])
        self.assertIsNone(windows[3]["telemetry"]["cpu_fan_rpm"])

    def test_missing_anchor_never_guesses_time_from_filename(self):
        path = self.wav(sine(), "2026-10-17T22-24-24.wav")
        telemetry = self.telemetry([{"timestamp": "2026-10-17T22:24:24Z", "raw": {"cpu_fan": "2000"}}])
        report = module.analyze(path, telemetry=telemetry)
        self.assertEqual(report["windows"][0]["telemetry"]["reason"], "no_audio_time_anchor")
        self.assertIsNone(report["windows"][0]["telemetry"]["cpu_fan_rpm"])

    def test_bad_telemetry_ignored_with_explicit_incomplete_and_duplicates_unknown(self):
        path = self.wav(sine())
        telemetry = self.telemetry([{"timestamp": "2026-10-17T22:24:24Z", "raw": {"cpu_fan": "2000"}},
                                    {"timestamp": "2026-10-17T22:24:24Z", "raw": {"cpu_fan": "3000"}},
                                    {"timestamp": "naive-and-invalid", "raw": {}}])
        report = module.analyze(path, telemetry=telemetry, started_at="2026-10-17T22:24:24Z")
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["warnings"])
        self.assertIsNone(report["windows"][0]["telemetry"]["cpu_fan_rpm"])

    def test_rejects_naive_timestamps_and_nonfinite_sensor_values(self):
        with self.assertRaises(module.AnalysisError):
            module.parse_timestamp("2026-10-17T22:24:24")
        with self.assertRaises(module.AnalysisError):
            module.parse_timestamp("9999-12-31T23:59:59-01:00")
        for value in (True, "nan", "inf", -1, None, "bad", 10**1000):
            self.assertIsNone(module._number(value))

    def test_audio_clock_overflow_keeps_telemetry_unknown(self):
        start = module.parse_timestamp("9999-12-31T23:59:59+00:00")
        windows = [{"start_seconds": 2, "duration_seconds": 1}]
        module.align_telemetry(windows, [], start)
        self.assertEqual(windows[0]["telemetry"]["reason"], "audio_timestamp_out_of_range")
        self.assertIsNone(windows[0]["telemetry"]["cpu_fan_rpm"])

    def test_telemetry_giant_line_and_metadata_recursion_rejected(self):
        path = self.wav(sine())
        telemetry = self.root / "telemetry.jsonl"
        telemetry.write_bytes(b"x" * (module.MAX_JSON_LINE_BYTES + 1))
        with self.assertRaises(module.AnalysisError):
            module.analyze(path, telemetry=telemetry)
        metadata = self.root / "deep.json"
        metadata.write_text("[" * 2000 + "0" + "]" * 2000)
        with self.assertRaises(module.AnalysisError):
            module.analyze(path, capture_metadata=metadata)


if __name__ == "__main__":
    unittest.main()
