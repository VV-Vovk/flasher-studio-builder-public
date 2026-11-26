import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import stm32
class RecoveryTests(unittest.TestCase):
 def test_layout(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);_,r=stm32.profile('STM32F103C8T6'); self.assertEqual(stm32.recovery_profile(p,'STM32F103C8T6',r),(r,None))
   (p/'flasher-native.json').write_text(json.dumps({'recoveryLayout':'fs10-stm32f103c8'})); link,meta=stm32.recovery_profile(p,'STM32F103C8T6',r)
   self.assertIn('ORIGIN = 0x08004000, LENGTH = 47K',stm32.linker(link));self.assertEqual(r['flashKiB'],64);self.assertEqual(meta['metadataOffset'],0x0800fc00)
   self.assertIn('SCB->VTOR = 0x08004000UL',stm32.recovery_system_source(p).read_text())
 def test_invalid(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); f=p/'flasher-native.json';_,r=stm32.profile('STM32F103C8T6')
   for val,target in [('wrong','STM32F103C8T6'),('fs10-stm32f103c8','STM32F103CBT6'),(123,'STM32F103C8T6')]:
    f.write_text(json.dumps({'recoveryLayout':val}));self.assertRaises(ValueError,stm32.recovery_profile,p,target,r)
