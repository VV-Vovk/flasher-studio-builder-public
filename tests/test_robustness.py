import os, sys, tempfile, unittest, subprocess, json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import build
import dependencies as dep

class RobustnessTests(unittest.TestCase):
    def test_retry_setup_network_error(self):
        cmd=['arduino-cli','core','update-index']
        responses=[subprocess.CompletedProcess(cmd,1,'','503 Service Unavailable'),subprocess.CompletedProcess(cmd,0,'done','')]
        with patch.object(build.subprocess,'run',side_effect=responses) as cli,patch.object(build.time,'sleep'):
            self.assertEqual(build.run(*cmd,capture=True),'done')
            self.assertEqual(cli.call_count,2)
    def test_no_retry_invalid_version(self):
        cmd=['arduino-cli','core','install','arduino:avr@9.9.9']
        with patch.object(build.subprocess,'run',return_value=subprocess.CompletedProcess(cmd,1,'','version not found')) as cli,patch.object(build.time,'sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError):build.run(*cmd)
            self.assertEqual(cli.call_count,1);sleep.assert_not_called()
    def test_no_retry_compiler(self):
        cmd=['arduino-cli','compile']
        with patch.object(build.subprocess,'run',side_effect=subprocess.CalledProcessError(1,cmd)) as cli:
            with self.assertRaises(subprocess.CalledProcessError):build.run(*cmd)
            self.assertEqual(cli.call_count,1)
    def test_wrapper_lock_and_legacy_library(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{}):
            root=Path(d)/'input';wrapper=root/'Export';parent=wrapper/'Demo';parent.mkdir(parents=True);(parent/'Demo.ino').touch()
            lib=wrapper/'libraries'/'OldLib';lib.mkdir(parents=True);(lib/'OldLib.h').write_text('int f();');(lib/'OldLib.cpp').write_text('int f(){return 1;}')
            (wrapper/'libraries.txt').write_text('OldLib\n');(wrapper/'flasher-lock.json').write_text(json.dumps(dep.make_lock('arduino:avr:uno','1.8.6',{},['OldLib'])))
            def compile(sketch,output,*args,**kw):
                self.assertTrue(kw['locked']);self.assertTrue((kw['local_libs']/'OldLib'/'OldLib.h').is_file());return set()
            work=Path(d)/'work';work.mkdir()
            with patch.object(build,'run',return_value='{}'),patch.object(build,'compile_project',side_effect=compile),patch.object(build,'install_declared') as install:
                _,meta=build.arduino(root,work,'arduino:avr:uno','','');install.assert_not_called()
            self.assertEqual(meta['bundledLibraries'],['OldLib']);self.assertEqual(meta['dependencyLock']['declared'],['OldLib'])
    def test_duplicate_nested_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parent=root/'Export'/'Demo';parent.mkdir(parents=True)
            (root/'flasher-lock.json').touch();(parent.parent/'flasher-lock.json').touch()
            with self.assertRaisesRegex(ValueError,'Expected one'):dep.read_lock(root,parent,'arduino:avr:uno','1.8.6')
