"""Test safe function modules only; the full legacy CLI is never imported."""
import importlib.util
import ast
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LEGACY = HERE / 'fixtures/mechrevo_profile_store_legacy.py'
CANDIDATE = REPO / 'patches/mechrevo_profile_store.py'
# Synthetic profile data tests the store algorithm, not OEM tuning claims.
DEFAULTS = [
    {'id': 'mechrevo_office', 'name': 'Fixture Office', 'fan': {
        'fanProfile': 'Quiet', 'minimumFanspeed': 0,
        'customFanCurve': {'tableCPU': [{'temp': 20, 'speed': 10}]}}},
    {'id': 'fixture-secondary', 'name': 'Fixture Secondary', 'fan': {'minimumFanspeed': 0}},
    {'id': 'fixture-third', 'name': 'Fixture Third', 'extra': {'preserve': True}},
]


def load_function(path, destination):
    # Import only these safe function modules; never import the complete CLI.
    spec = importlib.util.spec_from_file_location('isolated_profile_store', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROFILES_PATH = destination
    module.MECHREVO_PROFILES = copy.deepcopy(DEFAULTS)
    return module.sync_oem_profiles, module.__dict__


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("MECHREVO_TEST_TMPDIR"))
        self.path = Path(self.tmp.name) / 'profiles'
        self.fn, self.ns = load_function(CANDIDATE, self.path)
        self.defaults = self.ns['MECHREVO_PROFILES']
        self.old_fn, _ = load_function(LEGACY, self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def tuned(self):
        data = copy.deepcopy(self.defaults)
        office = next(p for p in data if p['id'] == 'mechrevo_office')
        office['fan']['minimumFanspeed'] = 60
        office['fan']['fanProfile'] = 'Quiet'
        office['fan']['customFanCurve']['tableCPU'] = [{'temp': 21, 'speed': 28}]
        office['custom_user_state'] = {'nested': ['retain', {'floor-note': '用户已校准'}]}
        return data

    def write(self, data, mode=0o640):
        raw = (json.dumps(data, ensure_ascii=False, indent=3) + '\n\n').encode()
        self.path.write_bytes(raw)
        self.path.chmod(mode)
        return raw

    def assert_no_staged_files(self):
        self.assertEqual(list(self.path.parent.glob('.mechrevo-profiles-*')), [])

    def test_old_function_resets_60_but_candidate_preserves_exact_complete_store(self):
        data = self.tuned()
        self.write(data)
        self.old_fn()
        self.assertEqual(next(p for p in json.loads(self.path.read_bytes()) if p['id'] == 'mechrevo_office')['fan']['minimumFanspeed'], 0)
        before = self.write(data)
        info = self.path.stat()
        with mock.patch.object(tempfile, 'mkstemp', side_effect=AssertionError('complete list must never stage a file')):
            self.fn()
        after = self.path.stat()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((after.st_ino, after.st_mtime_ns, stat.S_IMODE(after.st_mode)),
                         (info.st_ino, info.st_mtime_ns, stat.S_IMODE(info.st_mode)))

    def test_append_only_missing_defaults_preserves_order_all_nested_values_and_mode_owner(self):
        office = next(p for p in self.tuned() if p['id'] == 'mechrevo_office')
        existing = [{'id': 'user-first', 'anything': {'values': [None, True, 42]}}, office,
                    {'id': 'user-last', 'fan': {'minimumFanspeed': 37}}]
        self.write(existing, mode=0o640)
        before = self.path.stat()
        defaults_before = copy.deepcopy(self.defaults)
        self.fn()
        result = json.loads(self.path.read_bytes())
        self.assertEqual(result[:len(existing)], existing)
        self.assertEqual(result[len(existing):], [p for p in self.defaults if p['id'] != 'mechrevo_office'])
        self.assertEqual(self.defaults, defaults_before)
        after = self.path.stat()
        self.assertEqual((stat.S_IMODE(after.st_mode), after.st_uid, after.st_gid),
                         (stat.S_IMODE(before.st_mode), before.st_uid, before.st_gid))
        self.assert_no_staged_files()

    def test_missing_store_creates_defaults_exclusively_at_0644(self):
        self.fn()
        self.assertEqual(json.loads(self.path.read_bytes()), self.defaults)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        self.assert_no_staged_files()

    def test_malformed_json_unicode_containers_records_and_duplicate_ids_never_overwritten(self):
        samples = [b'{', b'\xff', b'{}', b'null', b'7', b'[null]', b'[{}]', b'[{"id":""}]',
                   b'[{"id":"   "}]', b'[{"id":4}]', b'[{"id":"x"},{"id":"x"}]',
                   b'[{"id":"x","id":"y"}]', b'[{"id":"x","value":NaN}]']
        for original in samples:
            with self.subTest(original=original):
                self.path.write_bytes(original)
                info = self.path.stat()
                with self.assertRaises((ValueError, UnicodeError)):
                    self.fn()
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.path.stat().st_ino, info.st_ino)
                self.assert_no_staged_files()

    def test_invalid_builtin_defaults_fail_without_replacing_existing_store(self):
        original = self.write([{'id': 'custom'}])
        self.ns['MECHREVO_PROFILES'].append(copy.deepcopy(self.defaults[0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate profile ID'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)

    def test_read_permission_error_propagates_without_false_success(self):
        original = self.write([{'id': 'custom'}])
        real_open = os.open
        def denied(path, *args, **kwargs):
            if Path(path) == self.path:
                raise PermissionError('read denied')
            return real_open(path, *args, **kwargs)
        with mock.patch.object(os, 'open', side_effect=denied), self.assertRaisesRegex(PermissionError, 'read denied'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)

    def test_staging_permission_error_propagates_without_rewriting_original(self):
        original = self.write([{'id': 'custom'}])
        with mock.patch.object(tempfile, 'mkstemp', side_effect=PermissionError('write denied')), \
             self.assertRaisesRegex(PermissionError, 'write denied'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)
        self.assert_no_staged_files()

    def test_file_fsync_failure_keeps_original_and_removes_staging(self):
        original = self.write([{'id': 'custom'}])
        with mock.patch.object(os, 'fsync', side_effect=OSError('file sync failed')), \
             self.assertRaisesRegex(OSError, 'file sync failed'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)
        self.assert_no_staged_files()

    def test_replace_permission_error_keeps_original_and_removes_staging(self):
        original = self.write([{'id': 'custom'}])
        with mock.patch.object(os, 'replace', side_effect=PermissionError('replace denied')), \
             self.assertRaisesRegex(PermissionError, 'replace denied'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)
        self.assert_no_staged_files()

    def test_observed_concurrent_byte_change_is_preserved_and_rejected(self):
        self.write([{'id': 'custom'}])
        concurrent = b'[{"id":"concurrent-user","fan":{"minimumFanspeed":61}}]\n'
        real_stage = tempfile.mkstemp
        def during_stage(*args, **kwargs):
            staged = real_stage(*args, **kwargs)
            self.path.write_bytes(concurrent)
            return staged
        with mock.patch.object(tempfile, 'mkstemp', side_effect=during_stage), \
             self.assertRaisesRegex(RuntimeError, 'changed concurrently'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), concurrent)
        self.assert_no_staged_files()

    def test_observed_concurrent_inode_change_with_equal_bytes_is_rejected(self):
        original = self.write([{'id': 'custom'}])
        real_stage = tempfile.mkstemp
        def during_stage(*args, **kwargs):
            staged = real_stage(*args, **kwargs)
            alternate = self.path.with_name('new-user-inode')
            alternate.write_bytes(original)
            os.replace(alternate, self.path)
            return staged
        with mock.patch.object(tempfile, 'mkstemp', side_effect=during_stage), \
             self.assertRaisesRegex(RuntimeError, 'changed concurrently'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)
        self.assert_no_staged_files()

    def test_observed_concurrent_permission_change_is_preserved_and_rejected(self):
        original = self.write([{'id': 'custom'}], mode=0o640)
        real_stage = tempfile.mkstemp
        def during_stage(*args, **kwargs):
            staged = real_stage(*args, **kwargs)
            self.path.chmod(0o600)
            return staged
        with mock.patch.object(tempfile, 'mkstemp', side_effect=during_stage), \
             self.assertRaisesRegex(RuntimeError, 'changed concurrently'):
            self.fn()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assert_no_staged_files()

    def test_new_destination_appearing_after_check_is_not_overwritten(self):
        real_link = os.link
        concurrent = b'[{"id":"created-concurrently"}]\n'
        def appearing(src, dst):
            self.path.write_bytes(concurrent)
            return real_link(src, dst)
        with mock.patch.object(os, 'link', side_effect=appearing), self.assertRaises(FileExistsError):
            self.fn()
        self.assertEqual(self.path.read_bytes(), concurrent)
        self.assert_no_staged_files()

    def test_post_commit_directory_fsync_failure_reports_changed_state_not_success(self):
        self.write([{'id': 'custom'}])
        real_fsync = os.fsync
        calls = 0
        def sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('directory sync failed')
            return real_fsync(fd)
        with mock.patch.object(os, 'fsync', side_effect=sync), \
             self.assertRaisesRegex(RuntimeError, 'Profiles committed but directory durability check failed'):
            self.fn()
        self.assertEqual(json.loads(self.path.read_bytes()), [{'id': 'custom'}] + self.defaults)
        self.assert_no_staged_files()

    def test_symlink_store_is_rejected_without_touching_target(self):
        target = self.path.with_name('external-target')
        original = b'[{"id":"keep-target"}]'
        target.write_bytes(original)
        self.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            self.fn()
        self.assertEqual(target.read_bytes(), original)


class ShippedFanDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("MECHREVO_TEST_TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'profiles'
        source = REPO / 'scripts/mechrevo_control.py'
        tree = ast.parse(source.read_text())
        # Execute only the shipped data and store function, never hardware helpers.
        nodes = [node for node in tree.body if
                 (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                  t.id == 'MECHREVO_PROFILES' for t in node.targets)) or
                 (isinstance(node, ast.FunctionDef) and node.name == 'sync_oem_profiles')]
        self.ns = {'json': json, 'os': os, 'Path': Path, 'PROFILES_PATH': self.path}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)
        self.sync = self.ns['sync_oem_profiles']

    def test_new_store_keeps_all_operating_modes_above_low_speed_floor(self):
        self.sync()
        profiles = {p['id']: p for p in json.loads(self.path.read_bytes())}
        for name in ('office', 'gaming', 'turbo'):
            with self.subTest(mode=name):
                fan = profiles['mechrevo_' + name]['fan']
                self.assertTrue(fan['useControl'])
                self.assertNotEqual(fan['fanProfile'], 'Custom')  # TCC ignores floors for custom curves.
                self.assertGreaterEqual(fan['minimumFanspeed'], 60)
                self.assertEqual(fan['maximumFanspeed'], 100)
        quiet = profiles['mechrevo_gaming_quiet']['fan']
        self.assertEqual(quiet['fanProfile'], 'Balanced')
        self.assertGreaterEqual(quiet['minimumFanspeed'], 50)
        self.assertEqual(quiet['maximumFanspeed'], 100)
        self.assertEqual(profiles['mechrevo_fan_boost']['fan']['minimumFanspeed'], 100)

    def test_new_defaults_keep_dynamic_cpu_policy_without_claiming_power_limits(self):
        self.sync()
        profiles = {p['id']: p for p in json.loads(self.path.read_bytes())}
        office = profiles['mechrevo_office']['cpu']
        self.assertEqual(office['energyPerformancePreference'], 'balance_power')
        self.assertEqual(office['scalingMaxFrequency'], 3200000)
        turbo = profiles['mechrevo_turbo']['cpu']
        self.assertFalse(turbo['useMaxPerfGov'])
        self.assertEqual(turbo['governor'], 'powersave')
        self.assertEqual(turbo['energyPerformancePreference'], 'performance')
        self.assertEqual(turbo['scalingMinFrequency'], 800000)
        self.assertEqual(turbo['scalingMaxFrequency'], 5000000)
        for profile in profiles.values():
            with self.subTest(profile=profile['id']):
                self.assertFalse(profile['display']['useBrightness'])
                self.assertFalse(profile['display']['useRefRate'])
                self.assertFalse(profile['display']['useResolution'])
                self.assertFalse(profile['cpu']['noTurbo'])
                self.assertEqual(profile['cpu']['onlineCores'], 24)
                self.assertEqual(profile['odmPowerLimits']['tdpValues'], [])
                self.assertEqual(profile['odmProfile']['name'], '')
                self.assertNotIn('原厂', profile['description'])
                for unsupported in ('45W', '75W', '130W'):
                    self.assertNotIn(unsupported, profile['description'])
        self.assertEqual(profiles['mechrevo_gaming_quiet']['cpu'],
                         profiles['mechrevo_gaming']['cpu'])

    def test_tuning_defaults_never_silently_rewrites_saved_cpu_display_or_fans(self):
        saved = copy.deepcopy(self.ns['MECHREVO_PROFILES'])
        for profile in saved:
            profile['cpu']['energyPerformancePreference'] = 'power'
            profile['cpu']['scalingMaxFrequency'] = 2900000
            profile['display']['useBrightness'] = True
            profile['display']['brightness'] = 17
            profile['fan']['minimumFanspeed'] = 63
            profile['user_note'] = '保留旧配置，更新默认值不等于同意迁移'
        before = (json.dumps(saved, ensure_ascii=False, indent=3) + '\n').encode()
        self.path.write_bytes(before)
        self.sync()
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_user_floor_is_preserved_while_missing_modes_get_new_defaults(self):
        office = copy.deepcopy(self.ns['MECHREVO_PROFILES'][0])
        office['fan']['minimumFanspeed'] = 25
        self.path.write_text(json.dumps([office]))
        self.sync()
        profiles = json.loads(self.path.read_bytes())
        self.assertEqual(profiles[0], office)
        for profile in profiles[1:]:
            minimum = profile['fan']['minimumFanspeed']
            self.assertGreaterEqual(minimum, 50)
            if profile['id'] != 'mechrevo_gaming_quiet':
                self.assertGreaterEqual(minimum, 60)
        before = self.path.read_bytes()
        self.sync()
        self.assertEqual(self.path.read_bytes(), before)

    def test_stock_tuxedo_default_is_migrated_to_mechrevo_gaming(self):
        stock = {
            'id': '__default_custom_profile__',
            'name': 'TUXEDO Defaults',
            'description': 'Edit profile to change behaviour',
            'fan': {'minimumFanspeed': 0},
        }
        self.path.write_text(json.dumps([stock]))
        self.sync()
        profiles = json.loads(self.path.read_bytes())
        default = profiles[0]
        self.assertEqual(default['id'], '__default_custom_profile__')
        self.assertEqual(default['name'], '机械革命-游戏平衡模式 (Gaming)')
        self.assertEqual(default['fan']['fanProfile'], 'Balanced')
        self.assertEqual(default['fan']['minimumFanspeed'], 60)
        self.assertEqual(default['cpu']['energyPerformancePreference'], 'balance_performance')

    def test_user_named_default_is_preserved(self):
        custom = {
            'id': '__default_custom_profile__',
            'name': '我的低噪配置',
            'description': '用户修改',
            'fan': {'minimumFanspeed': 25},
        }
        self.path.write_text(json.dumps([custom]))
        self.sync()
        profiles = json.loads(self.path.read_bytes())
        self.assertEqual(profiles[0], custom)

    def test_corrupt_existing_store_is_not_replaced_by_cooling_defaults(self):
        self.path.write_bytes(b'{broken')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.path.read_bytes(), b'{broken')


class ModeLedSyncTests(unittest.TestCase):
    def setUp(self):
        source = REPO / 'scripts/mechrevo_control.py'
        tree = ast.parse(source.read_text())
        nodes = [node for node in tree.body if
                 (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name)
                  and t.id == 'PROFILE_MODE_KEYS' for t in node.targets)) or
                 (isinstance(node, ast.FunctionDef) and node.name == 'sync_mode_led_from_profile')]
        self.leds = []
        self.ns = {
            'PROFILE_MODE_KEYS': {},
            'get_current_mode_info': lambda: ('', 'mechrevo_gaming'),
            'set_hardware_mode_led': self.leds.append,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.ns)

    def test_external_profile_change_updates_the_matching_led_once(self):
        sync = self.ns['sync_mode_led_from_profile']
        self.assertEqual(sync('mechrevo_turbo'), 'mechrevo_turbo')
        self.assertEqual(self.leds, ['turbo'])

    def test_default_profile_is_treated_as_mechrevo_gaming(self):
        sync = self.ns['sync_mode_led_from_profile']
        self.assertEqual(sync('__default_custom_profile__'), '__default_custom_profile__')
        self.assertEqual(self.leds, ['gaming'])

    def test_unknown_profile_is_not_written_to_the_ec(self):
        sync = self.ns['sync_mode_led_from_profile']
        self.assertEqual(sync('unrecognized-profile'), 'unrecognized-profile')
        self.assertEqual(self.leds, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
