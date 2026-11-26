import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import stm32

class SourceDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.p=self.root/'input';self.p.mkdir();self.work=self.root/'work';self.work.mkdir();self.sdk=self.root/'sdk'
        self.recipe=stm32.profile('STM32F030F4P6')[1]
        self.driver=self.sdk/'Drivers/STM32F0xx_HAL_Driver';self.inc=self.driver/'Inc';self.src=self.driver/'Src'
        for d in (self.inc,self.src,self.sdk/'Drivers/CMSIS/Include',self.sdk/'Drivers/CMSIS/Device/ST/STM32F0xx/Include',self.sdk/'Drivers/CMSIS/Device/ST/STM32F0xx/Source/Templates/gcc'):d.mkdir(parents=True)
        for f in ('Drivers/CMSIS/Device/ST/STM32F0xx/Source/Templates/gcc/startup_stm32f030x6.s','Drivers/CMSIS/Device/ST/STM32F0xx/Source/Templates/system_stm32f0xx.c'):(self.sdk/f).touch()
        (self.inc/'stm32f0xx_hal_conf_template.h').write_text('#define HAL_MODULE_ENABLED\n')
        for name in ('hal','hal_gpio','hal_msp_template','hal_timebase_tim_template','ll_gpio'):(self.src/('stm32f0xx_'+name+'.c')).touch()
    def put(self,path,text=''):
        f=self.p/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(text);return f
    def plan(self):return stm32.driver_plan(self.p,self.work,self.recipe,self.sdk)
    def test_nested_project_sources(self):
        self.put('project/Core/Src/main.c','#include "motor.h"');lib=self.put('project/lib/motor.c','');header=self.put('project/lib/inc/motor.h','#include "stm32f0xx_hal.h"');self.put('project/Core/Inc/main.h');self.put('project/lib/examples/main.c')
        p,target,_=stm32.config(self.p,'stm32-bare','STM32F030F4P6');self.assertEqual(p,self.p/'project')
        source,dirs,flags,mode=stm32.driver_plan(p,self.work,self.recipe,self.sdk);self.assertIn(lib,source);self.assertIn(header.parent,dirs);self.assertTrue(mode['hal']);self.assertIn('-DUSE_HAL_DRIVER',flags);self.assertFalse(any('examples' in f.parts for f in source))
    def test_hal_template_and_sources(self):
        self.put('main.c','#include "stm32f0xx_hal.h"');source,dirs,flags,mode=self.plan();self.assertTrue(mode['generatedHalConfig']);self.assertTrue((dirs[0]/'stm32f0xx_hal_conf.h').is_file());self.assertIn(self.src/'stm32f0xx_hal.c',source);self.assertIn(self.src/'stm32f0xx_hal_gpio.c',source);self.assertFalse(any('template' in f.name.lower() for f in source));self.assertIn(self.work/'hal_default_tick.c',source)
    def test_ll_only(self):
        self.put('main.c','#include "stm32f0xx_ll_gpio.h"');source,dirs,flags,mode=self.plan();self.assertTrue(mode['ll']);self.assertFalse(mode['hal']);self.assertIn('-DUSE_FULL_LL_DRIVER',flags);self.assertNotIn('-DUSE_HAL_DRIVER',flags);self.assertIn(self.src/'stm32f0xx_ll_gpio.c',source);self.assertNotIn(self.src/'stm32f0xx_hal.c',source)
    def test_mixed_and_custom_conf(self):
        self.put('main.c','#include "custom.h"');self.put('custom.h','#include "stm32f0xx_hal.h"\n#include "stm32f0xx_ll_gpio.h"');f=self.put('inc/stm32f0xx_hal_conf.h','my configuration');self.put('flasher-native.json','{"hseHz":12000000}');source,dirs,flags,mode=self.plan();self.assertTrue(mode['hal'] and mode['ll']);self.assertFalse(mode['generatedHalConfig']);self.assertEqual(dirs[0],f.parent);self.assertEqual(f.read_text(),'my configuration');self.assertIn('-DHSE_VALUE=12000000U',flags)
    def test_cmsis_only(self):
        self.put('main.c','#include "stm32f0xx.h"\n// HAL_Init();');source,dirs,flags,mode=self.plan();self.assertFalse(mode['hal'] or mode['ll']);self.assertEqual(len(source),3);self.assertNotIn('-DUSE_HAL_DRIVER',flags)
    def test_wrong_family(self):
        self.put('main.c','#include "stm32f1xx_hal.h"');self.assertRaisesRegex(ValueError,'family differs',self.plan)
    def test_no_driver_version_mixing(self):
        self.put('main.c','#include "stm32f0xx_hal.h"');self.put('lib/stm32f0xx_hal_gpio.c');self.assertRaisesRegex(ValueError,'Bundled ST driver',self.plan)
    def test_duplicate_hal_configs(self):
        self.put('main.c','#include "stm32f0xx_hal.h"');self.put('inc/stm32f0xx_hal_conf.h');self.put('lib/stm32f0xx_hal_conf.h');self.assertRaisesRegex(ValueError,'Several HAL',self.plan)
    def test_bad_hse(self):
        self.put('main.c','int main(void){}');self.put('flasher-native.json','{"hseHz":"bad"}');self.assertRaisesRegex(ValueError,'hseHz',self.plan)

    def test_ll_usb_indirect_hal_config(self):
        self.put('main.c','#include "stm32f0xx_ll_gpio.h"')
        usb=self.src/'stm32f0xx_ll_usb.c';usb.write_text('#include "stm32f0xx_hal.h"')
        source,dirs,flags,mode=self.plan()
        self.assertIn(usb,source)
        self.assertTrue((dirs[0]/'stm32f0xx_hal_conf.h').is_file())
        self.assertFalse(mode['hal'])
        self.assertTrue(mode['generatedHalConfig'])
    def test_explicit_ll_usb_with_hal_dependency(self):
        self.put('main.c','#include "stm32f0xx_ll_usb.h"')
        source,dirs,flags,mode=self.plan()
        self.assertIn(self.src/'stm32f0xx_hal.c',source)
        self.assertIn(self.work/'hal_default_tick.c',source)
