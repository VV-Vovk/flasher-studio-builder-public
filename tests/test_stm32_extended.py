import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import stm32,stm32_middleware as mw,stm32_git as sg,cubeide_gcc as ci,build

PREFIX='com.st.stm32cube.ide.mcu.gnu.managedbuild.'
def fixture(p):
    (p/'Core/Src').mkdir(parents=True);(p/'Core/Inc').mkdir();(p/'Core/Src/main.c').write_text('int main(void){for(;;){}}');(p/'Core/Src/skip.c').write_text('#error must not compile');(p/'flash.ld').write_text(stm32.linker(stm32.profile('STM32F030F4')[1]));(p/'.project').write_text('<projectDescription><name>Demo</name></projectDescription>')
    (p/'.cproject').write_text(f'''<cproject><configuration name="Debug"><folderInfo><toolChain superClass="{PREFIX}toolchain.exe.debug"><option superClass="{PREFIX}option.target_mcu" value="STM32F030F4Px"/><option superClass="{PREFIX}option.target_cpuid" value="0"/><tool superClass="{PREFIX}tool.c.compiler"><option superClass="{PREFIX}tool.c.compiler.option.includepaths" valueType="includePath"><listOptionValue value="../Core/Inc"/></option><option valueType="definedSymbols"><listOptionValue value="STM32F030x6"/></option></tool><tool superClass="{PREFIX}tool.c.linker"><option superClass="{PREFIX}tool.c.linker.option.script" value="${{workspace_loc:/Demo/flash.ld}}"/></tool></toolChain></folderInfo><sourceEntries><entry kind="sourcePath" name="Core" excluding="Src/skip.c"/></sourceEntries></configuration></cproject>''')
class Extended(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.p=self.root/'project';self.p.mkdir();self.sdk=self.root/'sdk';self.sdk.mkdir();self.work=self.root/'work';self.work.mkdir();self.recipe=stm32.profile('STM32F030F4')[1]
    def put(self,base,name,text=''):
        p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    def test_profiles_and_fpu(self):
        self.assertEqual(len(stm32.PROFILES),42);self.assertEqual(len(stm32.CUBE_TAGS),12)
        for target,macro,flash,ram in [["STM32F042F6P6","STM32F042x6",32,6],["STM32F042C6T6","STM32F042x6",32,6],["STM32F042K6T6","STM32F042x6",32,6],["STM32F070C6T6","STM32F070x6",32,6],["STM32F070CBT6","STM32F070xB",128,16],["STM32F070RBT6","STM32F070xB",128,16],["STM32F072RBT6","STM32F072xB",128,16],["STM32F072CBT6","STM32F072xB",128,16],["STM32F103R8T6","STM32F103xB",64,20],["STM32F103RBT6","STM32F103xB",128,20],["STM32F103V8T6","STM32F103xB",64,20],["STM32F103VBT6","STM32F103xB",128,20]]:
            name,p=stm32.profile(target)
            self.assertEqual(name,target)
            self.assertEqual((p['define'],p['flashKiB'],p['ramKiB']),(macro,flash,ram))
        for target in ('STM32F070F6P6','STM32F070F6P6TR'):
            name,p=stm32.profile(target)
            self.assertEqual(name,target)
            self.assertEqual((p['define'],p['cpu'],p['flashKiB'],p['ramKiB']),('STM32F070x6','cortex-m0',32,6))
        _,r=stm32.profile('STM32G431CBT6');self.assertEqual(r['flashKiB'],128);self.assertEqual(r['ramKiB'],16);self.assertIn('-mfloat-abi=hard',stm32.cpu_flags(r));self.assertNotIn('-mfloat-abi=hard',stm32.cpu_flags(self.recipe))
    def test_mixed_family_rejected(self):
        f=self.put(self.p,'main.c','#include "stm32f0xx_hal.h"\n#include "stm32f1xx_hal.h"');self.assertRaises(ValueError,stm32.driver_modes,[f],'f0')
    def test_middleware_detect_and_configs(self):
        f=self.put(self.p,'main.c','#include "FreeRTOS.h"\n#include "ff.h"\n#include "usbd_cdc.h"');m=mw.detect([f]);self.assertEqual(m,{'freertos','fatfs','usb-device'});self.assertRaisesRegex(ValueError,'FreeRTOSConfig',mw.plan,[f],self.sdk,self.recipe,{},m)
    def test_freertos(self):
        p=self.put(self.p,'main.c','#include "FreeRTOS.h"');c=self.put(self.p,'FreeRTOSConfig.h');base='Middlewares/Third_Party/FreeRTOS/Source/'
        for f in ['tasks.c','queue.c','list.c','portable/GCC/ARM_CM0/port.c','portable/MemMang/heap_4.c','include/FreeRTOS.h']:self.put(self.sdk,base+f)
        src,dirs,flags,meta=mw.plan([p,c],self.sdk,self.recipe,{}, {'freertos'});self.assertEqual(meta['freertos']['port'],'ARM_CM0');self.assertIn('heap_4.c',[f.name for f in src]);self.assertRaises(ValueError,mw.plan,[p,c],self.sdk,self.recipe,{'freertosHeap':9},{'freertos'})
    def test_fatfs_usb(self):
        paths=[self.put(self.p,'main.c','#include "ff.h"\n#include "usbd_cdc.h"'),self.put(self.p,'ffconf.h'),self.put(self.p,'usbd_conf.h')]
        for f in ['Third_Party/FatFs/src/ff.c','ST/STM32_USB_Device_Library/Core/Src/usbd_core.c','ST/STM32_USB_Device_Library/Core/Src/usbd_ctlreq.c','ST/STM32_USB_Device_Library/Core/Src/usbd_ioreq.c','ST/STM32_USB_Device_Library/Class/CDC/Src/usbd_cdc.c']:self.put(self.sdk,'Middlewares/'+f)
        src,dirs,flags,meta=mw.plan(paths,self.sdk,self.recipe,{},mw.detect(paths));self.assertEqual(meta['usb-device']['classes'],['cdc']);self.assertIn('ff.c',[f.name for f in src]);self.assertNotIn('diskio.c',[f.name for f in src])
    def test_git_replay(self):
        item={'url':'https://github.com/example/lib.git','ref':'v1','folder':'lib','sources':['src/x.c'],'includeDirs':['include']};(self.p/sg.MANIFEST).write_text(json.dumps([item]));(self.p/sg.LOCK).write_text(json.dumps([{**item,'commit':'a'*40}]))
        def checkout(url,sha,dest):self.assertEqual(sha,'a'*40);self.put(dest,'src/x.c');self.put(dest,'include/x.h')
        with patch.object(sg.git_libraries,'checkout',side_effect=checkout),patch.object(sg.git_libraries,'resolve',side_effect=AssertionError('must not resolve again')):
            src,dirs,records=sg.install(self.p,self.work);self.assertEqual(src[0].name,'x.c');self.assertEqual(records[0]['commit'],'a'*40)
    def test_git_escape(self):
        self.assertRaises(ValueError,sg.relative,self.p,'../bad.c')
    def test_cubeide(self):
        fixture(self.p);self.assertEqual(build.detect(self.p),'stm32cubeide-gcc');plan=ci.parse(self.p);self.assertEqual(plan['arch'],['-mcpu=cortex-m0','-mthumb']);self.assertEqual([f.name for f in plan['sources']],['main.c']);self.assertEqual(plan['linker']['ld'][0],self.p/'flash.ld')
    def test_cubeide_reject_external(self):
        fixture(self.p);f=self.p/'.cproject';f.write_text(f.read_text().replace('../Core/Inc','../../external'));self.assertRaisesRegex(ValueError,'External',ci.parse,self.p)
    def test_cubeide_reject_linked(self):
        fixture(self.p);f=self.p/'.project';f.write_text('<projectDescription><name>Demo</name><linkedResources><link/></linkedResources></projectDescription>');self.assertRaisesRegex(ValueError,'linked resources',ci.parse,self.p)

    def test_cortex_m0plus_static_and_legacy_alias(self):
        for target in ('STM32C031C6T6','STM32G071RBT6','STM32L072CBT6'):
            recipe=stm32.profile(target)[1]
            self.assertEqual(recipe['cpu'],'cortex-m0plus')
            self.assertEqual(stm32.cpu_flags(recipe),['-mcpu=cortex-m0plus','-mthumb'])
        self.assertEqual(stm32.cpu_flags({'cpu':'cortex-m0+'}),['-mcpu=cortex-m0plus','-mthumb'])
        self.assertTrue(all(r['cpu']!='cortex-m0+' for r in stm32.PROFILES.values()))
    def test_cortex_m0plus_cubeide_aliases(self):
        fixture(self.p);f=self.p/'.cproject';original=f.read_text()
        for value in ('cortex-m0+','cortex-m0plus','com.st.cpu.cortex-m0+'):
            with self.subTest(value=value):
                f.write_text(original.replace('STM32F030F4Px','STM32G071RBT6').replace('target_cpuid" value="0"','target_cpuid" value="'+value+'"'))
                self.assertEqual(ci.parse(self.p)['arch'],['-mcpu=cortex-m0plus','-mthumb'])
    def test_cortex_m0plus_freertos(self):
        p=self.put(self.p,'main.c','#include "FreeRTOS.h"');c=self.put(self.p,'FreeRTOSConfig.h');base='Middlewares/Third_Party/FreeRTOS/Source/'
        for f in ['tasks.c','queue.c','list.c','portable/GCC/ARM_CM0/port.c','portable/MemMang/heap_4.c','include/FreeRTOS.h']:self.put(self.sdk,base+f)
        recipe=stm32.profile('STM32G071RBT6')[1]
        _,_,_,meta=mw.plan([p,c],self.sdk,recipe,{}, {'freertos'})
        self.assertEqual(meta['freertos']['port'],'ARM_CM0')
