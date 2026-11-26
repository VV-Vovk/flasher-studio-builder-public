"""Offline behavioral tests; GitHub Actions integration still requires deployment."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

TOOLS = Path(__file__).resolve().parents[2] / 'tools'
sys.path.insert(0, str(TOOLS))
import auto_libraries as auto
import install_libraries as explicit


def result(code=0, output='', error=''):
    return SimpleNamespace(returncode=code, stdout=output, stderr=error)


class TestDependencyResolution(unittest.TestCase):
    def test_exact_provides_blegamepad(self):
        calls = []
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[:3] == ['arduino-cli','lib','search']:
                if 'provides=BleGamepad.h' in cmd:
                    return result(output=json.dumps({'libraries':[{'name':'ESP32-BLE-Gamepad'}]}))
                return result(output='{"libraries":[]}')
            return result()
        self.assertEqual(auto.registry_matches('BleGamepad.h',runner), ['ESP32-BLE-Gamepad'])
        self.assertIn('provides=BleGamepad.h', calls[0])

    def test_auto_installs_blegamepad_via_header(self):
        calls = []
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:3]==['lib','search']:
                return result(output=json.dumps({'libraries':[{'name':'ESP32-BLE-Gamepad'}]}))
            return result()
        installed=set()
        auto.resolve_missing_header('BleGamepad.h', installed, runner)
        self.assertEqual(installed, {'ESP32-BLE-Gamepad'})
        self.assertIn(['arduino-cli','lib','install','ESP32-BLE-Gamepad'],calls)

    def test_user_specified_short_name_is_resolved(self):
        calls=[]
        def runner(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1:3]==['lib','install']:
                return result(code=1, error='not found') if cmd[-1]=='BleGamepad' else result()
            if cmd[1:3]==['lib','search']:
                return result(output=json.dumps({'libraries':[{'name':'ESP32-BLE-Gamepad'}]}))
            return result()
        resolved=explicit.install_declared('BleGamepad',runner)
        self.assertEqual(resolved,'ESP32-BLE-Gamepad')
        self.assertIn(['arduino-cli','lib','install','ESP32-BLE-Gamepad'],calls)

    def test_version_preserved_after_resolution(self):
        def runner(cmd,**kwargs):
            if cmd[1:3]==['lib','install']:
                return result(code=1, error='not found') if cmd[-1].startswith('BleGamepad@') else result()
            return result(output='{"libraries":[{"name":"ESP32-BLE-Gamepad"}]}')
        self.assertEqual(explicit.install_declared('BleGamepad@0.7.3',runner), 'ESP32-BLE-Gamepad@0.7.3')

    def test_latest_alias_resolves_without_literal_version(self):
        def runner(cmd,**kwargs):
            if cmd[1:3]==['lib','install']:
                return result(code=1, error='not found') if cmd[-1]=='BleGamepad@latest' else result()
            return result(output='{"libraries":[{"name":"ESP32-BLE-Gamepad"}]}')
        self.assertEqual(explicit.install_declared('BleGamepad@latest',runner), 'ESP32-BLE-Gamepad')

    def test_ambiguity_is_not_guessed(self):
        def runner(cmd,**kwargs):
            return result(output='{"libraries":[{"name":"A"},{"name":"B"}]}')
        with self.assertRaisesRegex(RuntimeError,'Неоднозначная'):
            auto.resolve_missing_header('Same.h',set(),runner)

    def test_trusted_github_fallback_retained(self):
        calls=[]
        def runner(cmd,**kwargs):
            calls.append(cmd)
            if cmd[1:3]==['lib','search']:
                return result(output='{"libraries":[]}')
            return result()
        attempted=set()
        auto.resolve_missing_header('HijelHID_BLEMouse.h',attempted,runner)
        self.assertIn('HijelHID_BLEMouse@0.1.0',attempted)
        self.assertTrue(any('--git-url' in c for c in calls))

    def test_unknown_header_does_not_download_random_git(self):
        calls=[]
        def runner(cmd,**kwargs):
            calls.append(cmd)
            return result(output='{"libraries":[]}')
        with self.assertRaisesRegex(RuntimeError,'не найдена'):
            auto.resolve_missing_header('unknown_header_foo.h',set(),runner)
        self.assertFalse(any('--git-url' in c for c in calls))

    def test_no_unrelated_fuzzy_provider(self):
        def runner(cmd,**kwargs):
            if 'provides=BleGamepad.h' in cmd:
                return result(output='{"libraries":[]}')
            return result(output='{"libraries":[{"name":"Unrelated","latest":{"provides_includes":["Different.h"]}}]}')
        self.assertEqual(auto.registry_matches('BleGamepad.h',runner),[])

    def test_bad_library_name_rejected_for_cli_install(self):
        self.assertIsNone(explicit.candidate_header('../evil'))
        self.assertIsNone(explicit.candidate_header('file:///url'))

    def test_auto_retry_sketch(self):
        calls=[]
        def runner(cmd,**kwargs):
            calls.append(cmd)
            if cmd[1]=='compile':
                times=sum(c[1]=='compile' for c in calls)
                return result(code=1, output='fatal error: BleGamepad.h: No such file or directory') if times==1 else result()
            if cmd[1:3]==['lib','search']:
                return result(output='{"libraries":[{"name":"ESP32-BLE-Gamepad"}]}')
            return result()
        auto.compile_project(Path('/tmp/sketch'),Path('/tmp/build'),'esp32c3-supermini',runner)
        self.assertEqual(sum(c[1]=='compile' for c in calls),2)

if __name__ == '__main__': unittest.main()
