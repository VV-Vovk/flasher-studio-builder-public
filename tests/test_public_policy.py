import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from check_public_tree import validate
class PublicPolicy(unittest.TestCase):
    def test_allowed(self):
        self.assertEqual(validate(['tools/universal/stm32.py','examples/native/stm32cube/flash.ld','README.md']),3)
    def test_blocked(self):
        for p in ('requests/id/source.c','Drivers/CMSIS/core.h','Middlewares/ST/STM32_WPAN/ble.h','examples/fw.bin','build-results/output.json','example/lib.a'):
            with self.subTest(p=p),self.assertRaises(ValueError):validate([p])
