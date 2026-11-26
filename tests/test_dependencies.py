import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import build
import dependencies as dep
import auto_libraries as lib
import install_libraries as installer

class DependencyTests(unittest.TestCase):
    def test_snapshot_and_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); book=root/'book'; f=book/'libraries'/'Json'/'library.properties';f.parent.mkdir(parents=True);f.write_text('name=ArduinoJson\nversion=7.3.1\n')
            versions=dep.snapshot(book);self.assertEqual(versions,{'ArduinoJson':'7.3.1'})
            obj=dep.make_lock('arduino:avr:uno','1.8.6',versions,['ArduinoJson.h'])
            (root/'flasher-lock.json').write_text(json.dumps(obj))
            self.assertEqual(dep.read_lock(root,root,'arduino:avr:uno','1.8.6'),(versions,['ArduinoJson.h']))
            with self.assertRaises(ValueError):dep.read_lock(root,root,'arduino:avr:nano','1.8.6')
    def test_bad_lock(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'flasher-lock.json').write_text(json.dumps(dep.make_lock('arduino:avr:uno','1.8.6',{'--evil':'1.0.0'})))
            with self.assertRaises(ValueError):dep.read_lock(p,p,'arduino:avr:uno','1.8.6')
    def test_conflict(self):
        with self.assertRaises(RuntimeError):dep.verify_versions({'A':'1.0'},{'A':'2.0'})
        with self.assertRaises(RuntimeError):dep.verify_versions({}, {'A':'2.0'},exact=True)
        dep.verify_versions({'A':'1.0'},{'A':'1.0','B':'2.0'})
    def test_locked_missing_header_does_not_install(self):
        with patch.object(lib,'resolve_missing_header') as resolver:
            with self.assertRaisesRegex(RuntimeError,'Locked dependencies'):
                lib.compile_project(Path('s'),Path('b'),None,lambda *a,**kw:SimpleNamespace(returncode=1,stdout='',stderr='fatal error: A.h: No such file or directory'),fqbn='arduino:avr:uno',locked=True)
            resolver.assert_not_called()
    def test_latest_and_no_overwrite(self):
        calls=[]
        def runner(cmd,**kwargs):calls.append(cmd);return SimpleNamespace(returncode=0)
        self.assertEqual(installer.install_declared('ArduinoJson@latest',runner),'ArduinoJson')
        self.assertEqual(calls[0][-2:],['--no-overwrite','ArduinoJson'])
    def test_header_extensions(self):
        self.assertEqual(lib.missing_headers('fatal error: foo.hxx: No such file or directory'),['foo.hxx'])
    def test_full_arduino_replay_with_mock_cli(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{}):
            root=Path(d)/'input';parent=root/'Demo';parent.mkdir(parents=True);(parent/'Demo.ino').write_text('');(parent/'Alpha.ino').write_text('')
            local=root/'libraries'/'Local';local.mkdir(parents=True);(local/'library.properties').write_text('name=Local\nversion=1.0.0');nested=local/'examples'/'Other';nested.mkdir(parents=True);(nested/'library.properties').write_text('name=Other\n')
            def fake_install(name):
                f=Path(os.environ['ARDUINO_DIRECTORIES_USER'])/'libraries'/name/'library.properties';f.parent.mkdir(parents=True,exist_ok=True);f.write_text(f'name={name}\nversion=1.2.3');
            def fake_run(*args,**kw):
                if args[:3]==('arduino-cli','lib','install'):
                    name,version=args[-1].split('@');self.assertEqual(version,'1.2.3');self.assertIn('--no-deps',args);fake_install(name)
                if args[:3]==('arduino-cli','lib','list'):return '{}'
            def fake_compile(sketch,output,*args,**kw):
                self.assertEqual(sketch.name,'Demo');self.assertTrue((sketch/'Demo.ino').is_file());self.assertTrue((sketch/'Alpha.ino').is_file());self.assertEqual([p.name for p in kw['local_libs'].iterdir()],['Local'])
                if not kw['locked']:fake_install('ArduinoJson')
                (output/'Demo.hex').write_bytes(b'actual test fixture');return {'ArduinoJson'} if not kw['locked'] else set()
            with patch.object(build,'run',side_effect=fake_run),patch.object(build,'compile_project',side_effect=fake_compile):
                work=Path(d)/'w1';work.mkdir();output,m=build.arduino(root,work,'arduino:avr:uno','','')
                self.assertEqual(m['dependencyLock']['libraries'],{'ArduinoJson':'1.2.3'})
                build.package(output,Path(d)/'out',m,'0'*32)
                lock=Path(d)/'out'/'flasher-lock.json';(root/'flasher-lock.json').write_bytes(lock.read_bytes())
                work2=Path(d)/'w2';work2.mkdir();_,m2=build.arduino(root,work2,'arduino:avr:uno','','');self.assertEqual(m2['dependencyLock'],m['dependencyLock'])
    def test_git_fallback_not_claimed_reproducible(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{}):
            p=Path(d);root=p/'input';root.mkdir();(root/'a.ino').touch();w=p/'work';w.mkdir()
            with patch.object(build,'run',return_value='{}'),patch.object(build,'compile_project',return_value={'ESP32-BLE-Controller@main'}):
                _,m=build.arduino(root,w,'esp32:esp32:esp32c3','','')
            self.assertNotIn('dependencyLock',m);self.assertIn('Git fallback',m['lockUnavailable'])
