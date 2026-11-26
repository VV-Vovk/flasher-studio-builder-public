import sys,tempfile,unittest,json,os,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import stm32,build
class STM32Tests(unittest.TestCase):
    def test_bare_profiles(self):
        for name,flash,ram in [('STM32F030F4P6',16,4),('STM32F030C8T6',64,8),('STM32F103C8T6',64,20)]:
            _,p=stm32.profile(name);self.assertEqual((p['flashKiB'],p['ramKiB']),(flash,ram));self.assertIn(f'LENGTH = {flash}K',stm32.linker(p))
        with self.assertRaises(ValueError):stm32.profile('STM32F030')
    def test_raw_c(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'source.c').write_text('int main(void){}');build.unpack(p/'source.c',p/'input');self.assertEqual(build.detect(p/'input','STM32F030F4P6'),'stm32-bare');self.assertEqual(stm32.config(p/'input','stm32-bare','STM32F030F4P6')[1],'STM32F030F4P6')
            with self.assertRaises(ValueError):build.detect(p/'input')
    def test_ioc_detection_and_script(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'source.ioc').write_text('Mcu.CPN=STM32F030F4P6\n');build.unpack(p/'source.ioc',p/'input');self.assertEqual(build.detect(p/'input'),'stm32cubemx');self.assertEqual(stm32.config(p/'input','stm32cubemx')[1],'STM32F030F4P6');self.assertIn('project generate',stm32.mx_script(p/'input/project.ioc',p/'gen'))
            (p/'input/main.c').touch()
            with self.assertRaisesRegex(ValueError,'existing source'):stm32.config(p/'input','stm32cubemx')
    def test_cubeide_detection(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'.project').write_text('<projectDescription><name>Demo</name></projectDescription>');(p/'.cproject').write_text('<cproject/>');self.assertEqual(build.detect(p),'stm32cubeide');self.assertEqual(stm32.config(p,'stm32cubeide')[1],'project-configured')
    def test_apply_user_code(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=p/'main.c';f.write_text('head\n/* USER CODE BEGIN 2 */\nold\n/* USER CODE END 2 */\ntail');m=p/'code.json';m.write_text(json.dumps({'main.c':{'2':'new();'}}));stm32.apply_user_code(p,m);self.assertIn('new();',f.read_text());self.assertIn('tail',f.read_text());self.assertNotIn('old',f.read_text())
            m.write_text(json.dumps({'main.c':{'unknown':'bad'}}));before=f.read_text()
            with self.assertRaises(ValueError):stm32.apply_user_code(p,m)
            self.assertEqual(before,f.read_text())
    def test_user_code_escape(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'src').mkdir();(p/'main.c').touch();m=p/'src/code.json';m.write_text(json.dumps({'../main.c':{'2':'a'}}));self.assertRaises(ValueError,stm32.apply_user_code,p/'src',m)
    def test_missing_tool(self):
        with patch.dict(os.environ,{'FS_CUBEMX_EXECUTABLE':''}):self.assertRaises(ValueError,stm32.tool,'FS_CUBEMX_EXECUTABLE')
    def test_conflicting_target(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'main.c').touch();(p/'flasher-native.json').write_text('{"target":"STM32F030C8"}');self.assertRaises(ValueError,stm32.config,p,'stm32-bare','STM32F030F4')
