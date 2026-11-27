import tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import native

class StandaloneMakeTests(unittest.TestCase):
    def fixture(self,p):
        (p/'src').mkdir()
        (p/'src'/'main.c').write_text('int main(void){for(;;){}}')
        (p/'Makefile').write_text('CC=arm-none-eabi-gcc\nall:\n\t$(CC) -Tflash.ld src/main.c -o result.elf\n')
        (p/'flash.ld').write_text('/* STM32F103C8T6 */')
    def test_arbitrary_structure_and_untouched_prebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'nested';p.mkdir();self.fixture(p)
            (p/'firmware').mkdir();(p/'firmware'/'old.hex').write_text('old')
            self.assertEqual(native.detect_native(root),'stm32cube')
            def run(*args,**kwargs):
                self.assertEqual(args,('make','-B','-j2'))
                self.assertEqual(kwargs['cwd'],p)
                (p/'result.elf').write_bytes(b'new elf');(p/'result.hex').write_bytes(b'new hex')
            out=root/'out';native.standalone_make_build(p,out,run)
            self.assertEqual(sorted(x.name for x in out.iterdir()),['result.elf','result.hex'])
    def test_prebuilt_is_not_a_new_build(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);(p/'old.elf').write_bytes(b'old')
            with self.assertRaisesRegex(ValueError,'new or rebuilt ELF'):native.standalone_make_build(p,p/'out',lambda *a,**k:None)
    def test_unrelated_makefile_not_stm32(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p);(p/'flash.ld').write_text('/* unrelated ARM project */')
            self.assertIsNone(native.detect_native(p))
    def test_multiple_outputs_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p)
            def run(*a,**k):
                (p/'a.elf').touch();(p/'b.elf').touch()
            with self.assertRaisesRegex(ValueError,'one new or rebuilt ELF'):native.standalone_make_build(p,p/'out',run)
