"""Regression tests matching the GitHub failure: registry entry missing `provides`."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import auto_libraries as auto
import install_libraries as installer


def result(code=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class FakeArduino:
    def __init__(self, *, include_ambiguous=False):
        self.calls = []
        self.include_ambiguous = include_ambiguous
        self.installed = False
        self.compiles = 0

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:3] == ['lib', 'search']:
            term = argv[-1].lower()
            if term.startswith('provides'):
                return result(stdout=json.dumps({'libraries': []}))
            if 'gamepad' in term:
                lib = {'name': 'ESP32-BLE-Gamepad',
                       'latest': {'architectures': ['esp32']}}
                data = [lib, {'name': 'BLE-Gamepad-Client',
                              'latest': {'architectures': ['esp32'],
                                         'provides_includes': ['BLEGamepadClient.h']}}]
                if self.include_ambiguous:
                    data.append({'name': 'Arduino-BLE-Gamepad',
                                 'latest': {'architectures': ['esp32']}})
                return result(stdout=json.dumps({'libraries': data}))
            return result(stdout='{"libraries":[]}')
        if argv[1:3] == ['lib', 'install']:
            if argv[-1] in ('BleGamepad', 'BleGamepad@latest'):
                return result(code=1, stderr='Library not found')
            if argv[-1] == 'ESP32-BLE-Gamepad':
                self.installed = True
                return result()
            return result(code=1, stderr='Unexpected library '+argv[-1])
        if argv[1] == 'compile':
            self.compiles += 1
            if not self.installed:
                return result(code=1, stderr='fatal error: BleGamepad.h: No such file or directory')
            return result(code=0, stdout='Sketch uses 10% of flash')
        return result()


class TestFallback(unittest.TestCase):
    def test_no_provides_metadata_finds_blegamepad_by_name(self):
        cli = FakeArduino()
        found = auto.registry_matches('BleGamepad.h', cli)
        self.assertEqual(found, ['ESP32-BLE-Gamepad'])
        self.assertTrue(any('Gamepad' in c[-1] for c in cli.calls if c[1:3]==['lib','search']))

    def test_no_explicit_lib_compiles_with_autoinstall(self):
        cli = FakeArduino()
        auto.compile_project(Path('/tmp/sketch'), Path('/tmp/build'), 'esp32c3-supermini', cli)
        self.assertEqual(cli.compiles, 2)
        self.assertTrue(cli.installed)

    def test_explicit_wrong_short_name_recovers(self):
        cli = FakeArduino()
        self.assertEqual(installer.install_declared('BleGamepad', cli), 'ESP32-BLE-Gamepad')

    def test_name_ambiguity_safely_fails(self):
        cli = FakeArduino(include_ambiguous=True)
        with self.assertRaisesRegex(RuntimeError, 'Неоднозначная'):
            auto.resolve_missing_header('BleGamepad.h', set(), cli)
        self.assertFalse(cli.installed)

    def test_exact_header_provider_prioritized(self):
        provider = {'name': 'Adafruit NeoPixel', 'latest': {
            'provides_includes': ['Adafruit_NeoPixel.h'], 'architectures':['*']}}
        self.assertEqual(auto.name_score('Adafruit_NeoPixel.h', provider), 120)

    def test_unrelated_and_wrong_architecture_not_installed(self):
        self.assertEqual(auto.name_score('BleGamepad.h', {
            'name':'ESP32-BLE-Gamepad','latest':{'architectures':['avr']}}),0)
        self.assertEqual(auto.name_score('BleGamepad.h', {
            'name':'ESP32-BLE-Gamepad','latest':{'provides_includes':['Other.h']}}),0)
        self.assertEqual(auto.name_score('BleGamepad.h', {
            'name':'BLE-Gamepad-Client'}),0)

    def test_unknown_unrelated_header_rejected(self):
        cli = FakeArduino()
        with self.assertRaisesRegex(RuntimeError,'не найдена'):
            auto.resolve_missing_header('SomethingCompletelyDifferent.h', set(), cli)

    def test_camel_tokens_include_gamepad(self):
        self.assertIn('gamepad', auto.header_tokens('BleGamepad.h'))

if __name__ == '__main__':
    unittest.main()
