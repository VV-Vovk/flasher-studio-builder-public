import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'prepare_response.py'
RID = 'a' * 32

class MergedDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.sketch = self.root / 'sketch'
        self.build = self.root / 'build'
        self.output = self.root / 'out'
        self.sketch.mkdir()
        self.build.mkdir()

    def binary(self, at: pathlib.Path):
        at.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(8096)
        data[0] = 0xE9
        data[1] = 4
        data[12] = 5
        at.write_bytes(data)

    def run_pack(self):
        return subprocess.run([
            sys.executable, str(SCRIPT),str(self.sketch),str(self.output),
            RID,'esp32c3-supermini','BLE Joystick','1.0.0',str(self.build)
        ], capture_output=True, text=True)

    def test_build_path(self):
        self.binary(self.build/'sketch.ino.merged.bin')
        x=self.run_pack()
        self.assertEqual(x.returncode,0, x.stderr+x.stdout)
        doc=json.loads((self.output/'result.json').read_text())
        self.assertEqual(doc['release']['chip'],'esp32c3')
        self.assertEqual(doc['size'],8096)
        self.assertTrue((self.output/'firmware.bin').exists())

    def test_nested_arduino_export(self):
        self.binary(self.sketch/'build'/'esp32.esp32.esp32c3'/'sketch.ino.merged.bin')
        x=self.run_pack()
        self.assertEqual(x.returncode,0,x.stderr+x.stdout)

    def test_missing_fails_closed(self):
        x=self.run_pack()
        self.assertNotEqual(x.returncode,0)
        self.assertIn('Cannot assemble merged BIN',x.stderr+x.stdout)

    def test_ambiguous_fails_closed(self):
        self.binary(self.build/'one.merged.bin')
        self.binary(self.build/'other.merged.bin')
        x=self.run_pack()
        self.assertNotEqual(x.returncode,0)
        self.assertIn('Ambiguous',x.stderr+x.stdout)

if __name__ == '__main__': unittest.main()
