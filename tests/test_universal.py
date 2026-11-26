import hashlib,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import build
import auto_libraries as lib
class Tests(unittest.TestCase):
    def test_arch(self):
        with patch.dict(os.environ,{'FS_ARCH':'avr'}):
            self.assertTrue(lib.library_arch_compatible({'latest':{'architectures':['avr']}}))
            self.assertFalse(lib.library_arch_compatible({'latest':{'architectures':['esp32']}}))
    def test_zip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);z=p/'a.zip'
            with zipfile.ZipFile(z,'w') as f:
                f.writestr('Demo/Demo.ino','');f.writestr('Demo/Other.ino','');f.writestr('libraries/Mylib/library.properties','name=Mylib')
            build.unpack(z,p/'dest');self.assertEqual(build.detect(p/'dest'),'arduino');self.assertEqual(build.choose_sketch(p/'dest')[1].name,'Demo.ino')
    def test_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);z=p/'a.zip'
            with zipfile.ZipFile(z,'w') as f:f.writestr('../evil','x')
            with self.assertRaises(ValueError):build.unpack(z,p/'dest')
            self.assertFalse((p/'evil').exists())
    def test_pio(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'platformio.ini').touch();self.assertEqual(build.detect(p),'platformio')
    def test_fqbn(self):
        self.assertEqual(build.validate_fqbn('MiniCore:avr:328:variant=modelP,clock=8MHz_internal'),'MiniCore:avr')
        for x in ['bogus:avr:uno','arduino:avr:uno;rm','arduino:avr:uno:bad']:
            with self.assertRaises(ValueError):build.validate_fqbn(x)
    def test_package(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'src';src.mkdir();(src/'a.hex').write_bytes(b':00000001FF\n');(src/'a.o').write_bytes(b'x')
            build.package(src,p/'out',{'engine':'arduino'},'0'*32)
            m=json.loads((p/'out/manifest.json').read_text());self.assertEqual(len(m['files']),1);self.assertEqual(m['files'][0]['sha256'],hashlib.sha256((src/'a.hex').read_bytes()).hexdigest());self.assertFalse(m['automaticFlashingAllowed'])
    def test_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a.elf').touch()
            with self.assertRaises(ValueError):build.package(p,p/'out',{},'0'*32)
    def test_retries(self):
        from types import SimpleNamespace
        logs=iter([SimpleNamespace(returncode=1,stdout='',stderr='fatal error: ArduinoJson.h: No such file or directory'),SimpleNamespace(returncode=0,stdout='',stderr='')]);calls=[]
        def runner(cmd,**kw):calls.append(cmd);return next(logs)
        with patch.object(lib,'resolve_missing_header') as resolve:
            lib.compile_project(Path('sketch'),Path('build'),None,runner,fqbn='arduino:avr:uno',local_libs=Path('libs'))
            self.assertEqual(resolve.call_args.args[0],'ArduinoJson.h');self.assertIn('--libraries',calls[0]);self.assertEqual(len(calls),2)
if __name__=='__main__':unittest.main()
