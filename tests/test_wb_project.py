import sys,tempfile,unittest,json,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import wb_project as w,stm32,cubeide_gcc as ci
from test_stm32_extended import fixture
from unittest.mock import patch
R={'family':'wb','define':'STM32WB55xx','cpu':'cortex-m4','fpu':'fpv4-sp-d16','ramKiB':192,'ramOrigin':0x20000000,'physicalFlashKiB':1024,'flashKiB':32,'wbApplicationOnly':True}
TARGET='STM32WB55RGV6'
def rec(addr,typ,b=b''):
    raw=bytes([len(b)])+addr.to_bytes(2,'big')+bytes([typ])+b
    return ':'+(raw+bytes([-sum(raw)%256])).hex()+'\n'
class WBProject(unittest.TestCase):
    def test_exact_target(self):
        for name in ('STM32WB55RGVx',TARGET,TARGET+'TR'):self.assertTrue(w.match_target(name,TARGET))
        for name in ('STM32WB55RG','STM32WB55CGVx','STM32WB55RGVA','STM32WB35RGVx'):self.assertFalse(w.match_target(name,TARGET))
        self.assertFalse(w.match_target('STM32WB55RGVx','STM32WB55RGVX'))
    def test_budget(self):
        self.assertEqual(w.budget({'wbAppFlashKiB':256},R),256)
        for obj in ({},{'wbAppFlashKiB':True},{'wbAppFlashKiB':33},{'wbAppFlashKiB':1024}):
            with self.assertRaises(ValueError):w.budget(obj,R)
    def test_full_project_plan(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);fixture(p);f=p/'.cproject'
            f.write_text(f.read_text().replace('STM32F030F4Px','STM32WB55RGVx').replace('target_cpuid" value="0"','target_cpuid" value="cortex-m4"').replace('STM32F030x6','STM32WB55xx').replace('<tool superClass=', '<option superClass="option.fpu" value="fpv4-sp-d16"/><option superClass="option.floatabi" value="hard"/><tool superClass=',1))
            (p/'flasher-native.json').write_text(json.dumps({'wbAppFlashKiB':256}))
            with patch.object(stm32,'profile',side_effect=lambda name:(name,R)):
                self.assertEqual(stm32.config(p,'stm32cubeide-gcc',TARGET)[1],TARGET)
                with self.assertRaisesRegex(ValueError,'exact selected target'):stm32.config(p,'stm32cubeide-gcc')
                with self.assertRaisesRegex(ValueError,'differs'):stm32.config(p,'stm32cubeide-gcc','STM32WB55CGU6')
                f.write_text(f.read_text().replace('STM32WB55xx','STM32WB35xx'))
                with self.assertRaisesRegex(ValueError,'macro'):stm32.config(p,'stm32cubeide-gcc',TARGET)
    def test_hex_vectors_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);h=p/'firmware.hex'
            start=rec(0,4,b'\x08\x00');good=rec(0,0,struct.pack('<II',0x20030000,0x08000009)+b'\x00\xbf')
            eof=rec(0,1)
            h.write_text(start+good+eof);self.assertEqual(w.verify_output(p,R,32)[0]['size'],10)
            for bad in (start+good+rec(0x8000,0,b'x')+eof,start+good+rec(0,4,b'\x20\x03')+rec(0,0,b'x')+eof,start+rec(0,0,struct.pack('<II',0x20040000,0x08000009)+b'x'*2)+eof):
                h.write_text(bad)
                with self.assertRaises(ValueError):w.verify_output(p,R,32)

    def test_ota_origin_and_tags(self):
        cfg={'wbAppFlashKiB':32,'wbOtaLayout':w.OTA_LAYOUT}
        self.assertEqual(w.origin(cfg,R,w.budget(cfg,R)),w.OTA_BASE)
        for obj in ({**cfg,'wbAppFlashKiB':28},{**cfg,'wbOtaLayout':'custom'}):
            with self.assertRaises(ValueError):w.budget(obj,R)
        with self.assertRaises(ValueError):w.budget(cfg,{**R,'ramKiB':64})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);h=p/'firmware.hex';start=rec(0,4,b'\x08\x00');eof=rec(0,1)
            prefix=rec(0x7000,0,struct.pack('<II',0x20030000,0x08007009)+b'\x00\xbf')
            tag=rec(0x7140,0,struct.pack('<I',0x08007144))
            end=rec(0x7144,0,struct.pack('<I',w.OTA_MAGIC))
            h.write_text(start+prefix+tag+end+eof)
            self.assertEqual(w.verify_output(p,R,32,w.OTA_BASE)[0]['start'],w.OTA_BASE)
            self.assertEqual((p/'firmware.bin').read_bytes()[10:0x140],b'\xff'*(0x140-10))
            with self.assertRaises(ValueError):w.verify_output(p,R,32)
            h.write_text(start+prefix+tag+rec(0x7144,0,b'\x00'*4)+eof)
            with self.assertRaisesRegex(ValueError,'end marker'):w.verify_output(p,R,32,w.OTA_BASE)
