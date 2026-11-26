import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'prepare_response.py'
RID = 'f' * 32


def image(chip_id, size=256):
    b = bytearray(size)
    b[0] = 0xe9
    b[1] = 1
    b[12] = chip_id & 255
    b[13] = chip_id >> 8
    return bytes(b)


class AssembleMerged(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        self.sketch = self.root / 'sketch'
        self.out = self.root / 'output'
        self.build.mkdir()
        self.sketch.mkdir()
        self.boot_app0 = self.root / 'boot_app0.bin'
        self.boot_app0.write_bytes(b'BOOTAPP0')
        self.part = b'\xaa\x50' + (b'P' * 254)
        (self.build / 'sketch.ino.bootloader.bin').write_bytes(image(5))
        (self.build / 'sketch.ino.partitions.bin').write_bytes(self.part)
        (self.build / 'sketch.ino.bin').write_bytes(image(5, 1024))

    def pack(self, chip='esp32c3-supermini'):
        env = dict(os.environ, ESP_BOOT_APP0_PATH=str(self.boot_app0))
        return subprocess.run([sys.executable, str(SCRIPT), str(self.sketch), str(self.out),
                               RID, chip, 'Joystick', '1.0', str(self.build)],
                              env=env, text=True, capture_output=True)

    def test_full_assembled_firmware_c3(self):
        result = self.pack()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        merged = (self.out / 'firmware.bin').read_bytes()
        self.assertEqual(merged[:256], image(5))
        self.assertEqual(merged[256:0x8000], b'\xff' * (0x8000 - 256))
        self.assertEqual(merged[0x8000:0x8100], self.part)
        self.assertEqual(merged[0xe000:0xe008], b'BOOTAPP0')
        self.assertEqual(merged[0x10000:0x10400], image(5, 1024))
        self.assertEqual(len(merged), 0x10000 + 1024)
        meta = json.loads((self.out / 'result.json').read_text())
        self.assertEqual(meta['sha256'], hashlib.sha256(merged).hexdigest())
        self.assertEqual(meta['release']['images'][0]['offset'], 0)
        self.assertEqual(meta['release']['chip'], 'esp32c3')

    def test_missing_application_fails_closed(self):
        (self.build / 'sketch.ino.bin').unlink()
        result = self.pack()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('complete bootloader/partitions/application trio', result.stdout + result.stderr)

    def test_wrong_chip_app_fails_closed(self):
        (self.build / 'sketch.ino.bin').write_bytes(image(9))
        result = self.pack()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('wrong-chip application', result.stdout + result.stderr)

    def test_bootloader_overlap_fails_closed(self):
        (self.build / 'sketch.ino.bootloader.bin').write_bytes(image(5, 0x8100))
        result = self.pack()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Flash image overlap', result.stdout + result.stderr)

    def test_classic_esp32_bootloader_offset(self):
        (self.build / 'sketch.ino.bootloader.bin').write_bytes(image(0))
        (self.build / 'sketch.ino.bin').write_bytes(image(0, 1024))
        result = self.pack('esp32-devkit')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        merged = (self.out / 'firmware.bin').read_bytes()
        self.assertEqual(merged[:0x1000], b'\xff' * 0x1000)
        self.assertEqual(merged[0x1000:0x1100], image(0))

    def test_reject_corrupt_partition(self):
        (self.build / 'sketch.ino.partitions.bin').write_bytes(b'CORRUPT')
        result = self.pack()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('partition table signature', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
