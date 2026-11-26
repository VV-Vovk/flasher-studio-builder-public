import hashlib, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/universal'))
import stm32_catalog as cat, stm32

# Synthetic schema fixtures, not copies of vendor packages or proof of hardware support.
def pdsc(family='f0',body='',processor='<processor Dcore="Cortex-M0" Dfpu="NO_FPU" Dendian="Little-endian"/>'):
    return f'<package><vendor>Keil</vendor><name>{cat.pack_name(family)}</name><devices><family Dfamily="STM32{family.upper()}">{processor}{body}</family></devices></package>'.encode()
def device(name='STM32F042F6',define='STM32F042x6',ram='0x1800',extra='',variants='<variant Dvariant="STM32F042F6Px"/>'):
    return f'<subFamily DsubFamily="test"><compile define="{define}"/><device Dname="{name}"><memory name="Flash" access="rx" start="0x08000000" size="0x8000" startup="1" default="1"/><memory name="SRAM" access="rwx" start="0x20000000" size="{ram}" default="1"/>{extra}{variants}</device></subFamily>'
class CatalogTests(unittest.TestCase):
    def test_exact_and_inheritance(self):
        data=pdsc(body=device());p=cat.resolve_data('STM32F042F6P6','f0',data,'fixture')
        self.assertEqual((p['define'],p['cpu'],p['flashKiB'],p['ramKiB']),('STM32F042x6','cortex-m0',32,6))
        self.assertEqual(p['deviceCatalog']['sha256'],hashlib.sha256(data).hexdigest());self.assertEqual(p['deviceCatalog']['base'],'STM32F042F6')
        self.assertEqual(cat.resolve_data('STM32F042F6P6TR','f0',data,'fixture')['ramKiB'],6)
    def test_no_guess(self):
        data=pdsc(body=device())
        for name in ('STM32F042','STM32F042F4P6','STM32F042F6T6','STM32F042F6P66'):
            with self.subTest(name=name),self.assertRaises(ValueError):cat.resolve_data(name,'f0',data,'fixture')
    def test_variant_override(self):
        data=pdsc(body=device(variants='<variant Dvariant="STM32F042F6Px"><memory name="SRAM" size="0x2000"/></variant>'))
        self.assertEqual(cat.resolve_data('STM32F042F6P6','f0',data,'fixture')['ramKiB'],8)
        self.assertEqual(cat.resolve_data('STM32F042F6','f0',data,'fixture')['ramKiB'],6)
    def test_other_banks_not_combined(self):
        data=pdsc(body=device(extra='<memory name="Other" access="rwx" start="0x20002000" size="0x8000" default="1"/><algorithm name="Flash/test.FLM" start="0x08000000" size="0x10000" default="1"/>'))
        p=cat.resolve_data('STM32F042F6','f0',data,'fixture');self.assertEqual((p['ramKiB'],p['flashKiB']),(6,32));self.assertEqual(len(p['deviceCatalog']['regions']),3);self.assertEqual(p['deviceCatalog']['flashAlgorithms'][0]['size'],65536)
    def test_ambiguous_ram_rejected(self):
        data=pdsc(body=device(extra='<memory name="Alias" access="rwx" start="0x20000000" size="0x8000" default="1"/>'))
        with self.assertRaisesRegex(ValueError,'unique default SRAM'):cat.resolve_data('STM32F042F6','f0',data,'fixture')
    def test_multicore_rejected(self):
        data=pdsc(body=device(extra='<processor Pname="CM0" Dcore="Cortex-M0"/><processor Pname="CM4" Dcore="Cortex-M4"/>'))
        with self.assertRaisesRegex(ValueError,'Multi-core'):cat.resolve_data('STM32F042F6','f0',data,'fixture')
    def test_missing_define_rejected(self):
        with self.assertRaisesRegex(ValueError,'macro'):cat.resolve_data('STM32F042F6','f0',pdsc(body=device(define='')),'fixture')
    def test_fpu(self):
        for core,value,expected in [('cortex-m4','SP_FPU','fpv4-sp-d16'),('cortex-m7','SP_FPU','fpv5-sp-d16'),('cortex-m7','DP_FPU','fpv5-d16'),('cortex-m3','NO_FPU',None)]:self.assertEqual(cat.fpu_flag(core,value),expected)
        with self.assertRaises(ValueError):cat.fpu_flag('cortex-m7','1')
    def test_f7_split_sram(self):
        body=device('STM32F746ZG','STM32F746xx',variants='<variant Dvariant="STM32F746ZGTx"/>',extra='<memory name="SRAM1" access="rwx" start="0x20010000" size="0x3C000" default="1"/><memory name="SRAM2" access="rwx" start="0x2004C000" size="0x4000" default="1"/>').replace('name="SRAM" access="rwx" start="0x20000000" size="0x1800" default="1"','name="DTCM" access="rwx" start="0x20000000" size="0x10000" default="0"')
        p=cat.resolve_data('STM32F746ZGT6','f7',pdsc('f7',body,'<processor Dcore="Cortex-M7" Dfpu="SP_FPU"/>'),'fixture')
        self.assertEqual((p['ramOrigin'],p['ramKiB']),(0x20010000,240));self.assertIn('0x20010000',stm32.linker(p))
    def test_wrong_family_xml_and_entity(self):
        for data in (pdsc('f4'),b'<!DOCTYPE package [<!ENTITY a "x">]><package/>'):
            with self.assertRaises(ValueError):cat.xml_root(data,'f0')
    def test_integration_cached_snapshot(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'FS_STM32_DFP_DIR':d,'FS_STM32_DFP_OFFLINE':'1'}):
            Path(d,'STM32F0xx_DFP.pdsc').write_bytes(pdsc(body=device()));cat.resolve.cache_clear()
            try:
                name,p=stm32.profile('STM32F042F6P6');self.assertEqual(name,'STM32F042F6P6');self.assertIn('LENGTH = 6K',stm32.linker(p))
                with tempfile.TemporaryDirectory() as project:
                    path=Path(project);(path/'main.c').write_text('int main(void){return 0;}');self.assertEqual(stm32.config(path,'stm32-bare',name)[1],name)
            finally:cat.resolve.cache_clear()
    def test_inventory_reports_restrictions(self):
        data=pdsc(body=device());inv=cat.inventory('f0',data,'fixture',{});self.assertEqual(len(inv['devices']),2);self.assertFalse(inv['devices'][0]['sourceOnly']);self.assertIn('not provisioned',inv['devices'][0]['reason'])
    def test_missing_snapshot_offline(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'FS_STM32_DFP_DIR':d,'FS_STM32_DFP_OFFLINE':'1'}):
            with self.assertRaisesRegex(ValueError,'No local DFP'):cat.fetch('f0')

    def test_legacy_f1_order_code_and_define(self):
        body=device('STM32F103RB','STM32F10X_MD',variants='')
        data=pdsc('f1',body,'<processor Dcore="Cortex-M3" Dfpu="0"/>')
        p=cat.resolve_data('STM32F103RBT6','f1',data,'fixture')
        self.assertEqual(p['define'],'STM32F103xB')
        self.assertEqual(p['ramKiB'],6)
        with self.assertRaises(ValueError):cat.resolve_data('STM32F103RCT6','f1',data,'fixture')
    def test_f1_macro_translation(self):
        for base,old,new in [('STM32F100C4','STM32F10X_LD_VL','STM32F100xB'),('STM32F101RG','STM32F10X_XL','STM32F101xG'),('STM32F102C6','STM32F10X_LD','STM32F102x6'),('STM32F105RC','STM32F10X_CL','STM32F105xC')]:
            self.assertEqual(cat.modern_f1_define(base,old),new)
        self.assertEqual(cat.modern_f1_define('STM32F103RB','STM32F10X_HD'),'STM32F10X_HD')
    def test_h7_axi_sram_only(self):
        body=device('STM32H743ZI','STM32H743xx',variants='<variant Dvariant="STM32H743ZITx"/>',extra='<memory name="RAM_D1" access="rwx" start="0x24000000" size="0x80000" default="1"/><memory name="RAM_D2" access="rwx" start="0x30000000" size="0x20000" default="1"/>').replace('name="SRAM"','name="DTCMRAM"').replace('size="0x1800" default="1"','size="0x20000" default="0"')
        p=cat.resolve_data('STM32H743ZIT6','h7',pdsc('h7',body,'<processor Dcore="Cortex-M7" Dfpu="DP_FPU"/>'),'fixture')
        self.assertEqual((p['ramOrigin'],p['ramKiB'],p['fpu']),(0x24000000,512,'fpv5-d16'))

    def test_cortex_m0plus_dfp_gcc_spelling(self):
        for family,base,define in [('c0','STM32C031C6','STM32C031xx'),('g0','STM32G071RB','STM32G071xx'),('l0','STM32L072CB','STM32L072xx')]:
            with self.subTest(family=family):
                body=device(base,define,variants='')
                recipe=cat.resolve_data(base,family,pdsc(family,body,'<processor Dcore="Cortex-M0+" Dfpu="NO_FPU"/>'),'fixture')
                self.assertEqual(recipe['cpu'],'cortex-m0plus')
                self.assertEqual(stm32.cpu_flags(recipe),['-mcpu=cortex-m0plus','-mthumb'])

    def test_wb_cpu1_geometry_and_link_limit(self):
        processor='<processor Dcore="Cortex-M4" Dfpu="SP_FPU" Dendian="Configurable"/>'
        for part,flash,ram,expected in [('STM32WB55RGVx',1024,192,192),('STM32WB55VYYx',640,192,192),('STM32WB35CEUxA',512,32,32),('STM32WB5MMGHx',1024,256,192),('STM32WB15CCUx',320,12,12)]:
            define='STM32'+part[5:9]+'xx'
            body=device(part,define,ram=hex(ram*1024),variants='').replace('size="0x8000" startup','size="'+hex(flash*1024)+'" startup')
            data=pdsc('wb',body,processor)
            target=part.replace('x','6')
            p=cat.resolve_data(target,'wb',data,'fixture')
            self.assertEqual((p['physicalFlashKiB'],p['flashKiB'],p['ramKiB'],p['cpu']),(flash,32,expected,'cortex-m4'))
            self.assertTrue(p['wbApplicationOnly'])
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);self.assertEqual(stm32.wb_application_recipe(root,p)['flashKiB'],32)
                (root/'flasher-native.json').write_text('{"wbAppFlashKiB":64}')
                self.assertEqual(stm32.wb_application_recipe(root,p)['flashKiB'],64)
                for bad in [flash,0,33,True]:
                    import json
                    (root/'flasher-native.json').write_text(json.dumps({'wbAppFlashKiB':bad}))
                    with self.assertRaises(ValueError):stm32.wb_application_recipe(root,p)
        self.assertEqual(cat.family_of('STM32WB55RGV6'),'wb')
        self.assertEqual(stm32.CUBE_TAGS['wb'],'v1.24.0')
    def test_wb_reject_wrong_geometry_or_cpu(self):
        body=device('STM32WB55RGVx','STM32WB55xx',variants='')
        for processor in ['<processor Dcore="Cortex-M4" Dfpu="SP_FPU" Dendian="Configurable"/>','<processor Dcore="Cortex-M0+" Dfpu="NO_FPU"/>']:
            with self.assertRaises(ValueError):cat.resolve_data('STM32WB55RGV6','wb',pdsc('wb',body,processor),'fixture')

    def test_wb_linker_empty_mailbox_only(self):
        ordinary=stm32.linker({'flashKiB':32,'ramKiB':12})
        wb=stm32.linker({'flashKiB':32,'ramKiB':12,'wbApplicationOnly':True})
        self.assertNotIn('_sMB_MEM2',ordinary)
        for fragment in ('_sMB_MEM2 = _ebss;', '_eMB_MEM2 = _sMB_MEM2;',
                         '_siMB_MEM2 = _sidata;', 'KEEP(*(MAPPING_TABLE',
                         'MB_MEM1 MB_MEM1.* .MB_MEM1 .MB_MEM1.*',
                         'MB_MEM2 MB_MEM2.* .MB_MEM2 .MB_MEM2.*',
                         'ASSERT(SIZEOF(.wb_shared_forbidden) == 0'):
            self.assertIn(fragment,wb)
        self.assertNotIn('RAM_SHARED',wb)
        self.assertIn('LENGTH = 12K',wb)
