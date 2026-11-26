"""Real GNU link with custom mailbox section; synthetic application, not BLE middleware."""
import json,os,subprocess,tempfile,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_stm32_extended import fixture
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    root=Path(td);p=root/'project';p.mkdir();fixture(p);f=p/'.cproject'
    f.write_text(f.read_text().replace('STM32F030F4Px','STM32WB55RGVx').replace('target_cpuid" value="0"','target_cpuid" value="cortex-m4"').replace('STM32F030x6','STM32WB55xx').replace('<tool superClass=', '<option superClass="option.fpu" value="fpv4-sp-d16"/><option superClass="option.floatabi" value="hard"/><tool superClass=',1))
    (p/'Core/Inc/project_config.h').write_text('/* Portable project include directory. */\n')
    (p/'flasher-native.json').write_text(json.dumps({'wbAppFlashKiB':32}))
    (p/'Core/Src/main.c').write_text("""
#include <stdint.h>
__attribute__((section("MAPPING_TABLE"),used)) volatile uint32_t table[8];
__attribute__((section("MB_MEM2"),used)) volatile uint32_t mailbox;
void Reset_Handler(void){table[0]=42;mailbox=42;for(;;){}}
__attribute__((section(".isr_vector"),used)) const uintptr_t vectors[]={0x20030000,(uintptr_t)Reset_Handler};
""")
    (p/'flash.ld').write_text("""
ENTRY(Reset_Handler)
MEMORY {
 FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 32K
 RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 192K
 SHARED (rw) : ORIGIN = 0x20030000, LENGTH = 1K
}
SECTIONS {
 .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
 .text : { *(.text*) *(.rodata*) } > FLASH
 MAPPING_TABLE (NOLOAD) : { KEEP(*(MAPPING_TABLE)) } > SHARED
 .mailbox (NOLOAD) : { KEEP(*(MB_MEM2)) } > SHARED
}
""")
    original=(p/'flash.ld').read_text()
    original_cproject=(p/'.cproject').read_text()
    source=(p/'Core/Src/main.c').read_text()
    for mode in ('valid','outside-budget','outside-ram','initialized-shared','ota','ota-bad-marker','ota-reserved-ram','wb55-64','wb35-32','wb50-64','wb30-32','wb35-ram-gap'):
        (p/'Core/Src/main.c').write_text(source)
        (p/'.cproject').write_text(original_cproject)
        target='STM32WB55RGV6'
        (p/'flasher-native.json').write_text(json.dumps({'wbAppFlashKiB':32}))
        script=original
        if mode=='outside-budget':script=script.replace('0x08000000','0x08010000')
        if mode=='outside-ram':script=script.replace('0x20030000, LENGTH = 1K','0x20040000, LENGTH = 1K')
        if mode=='initialized-shared':script=script.replace('.mailbox (NOLOAD)', '.mailbox').replace('} > SHARED','} > SHARED AT> FLASH')
        if mode.startswith('ota'):
            (p/'flasher-native.json').write_text(json.dumps({'wbAppFlashKiB':32,'wbOtaLayout':'st-ble-app-0x7000'}))
            script=script.replace('0x08000000, LENGTH = 32K','0x08007000, LENGTH = 4K').replace('0x20000000, LENGTH = 192K','0x20000004, LENGTH = 196604')
            script=script.replace(' .text :', ' .tag 0x08007140 : { LONG(ADDR(.endtag)); } > FLASH\n .text :')
            script=script.replace(' MAPPING_TABLE', ' .endtag : { LONG(0x94448a29); } > FLASH\n MAPPING_TABLE',1)
            if mode=='ota-bad-marker':script=script.replace('0x94448a29','0x0')
            if mode=='ota-reserved-ram':
                script=script.replace('0x20000004, LENGTH = 196604','0x20000000, LENGTH = 192K').replace(' MAPPING_TABLE',' .bad (NOLOAD) : { LONG(0); } > RAM\n MAPPING_TABLE',1)
        if mode.startswith('wb'):
            target,macro,ram={'wb55-64':('STM32WB55CCU6','STM32WB55xx',64),'wb35-32':('STM32WB35CEU6A','STM32WB35xx',32),'wb50-64':('STM32WB50CGU6','STM32WB50xx',64),'wb30-32':('STM32WB30CEU6A','STM32WB30xx',32),'wb35-ram-gap':('STM32WB35CEU6A','STM32WB35xx',32)}[mode]
            (p/'.cproject').write_text(original_cproject.replace('STM32WB55RGVx',target).replace('STM32WB55xx',macro))
            (p/'Core/Src/main.c').write_text(source.replace('0x20030000,','0x%08x,'%(0x20000000+ram*1024)))
            script=script.replace('LENGTH = 192K','LENGTH = %dK'%ram)
            if mode=='wb35-ram-gap':script=script.replace(' MAPPING_TABLE',' .bad 0x20008000 (NOLOAD) : { LONG(0); }\n MAPPING_TABLE',1)
        (p/'flash.ld').write_text(script)
        if mode=='initialized-shared':
            f=p/'Core/Src/main.c';f.write_text(f.read_text().replace('mailbox;','mailbox=7;'))
        archive=root/(mode+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for x in p.rglob('*'):
                if x.is_file():z.write(x,x.relative_to(p))
        out=root/('out-'+mode)
        cmd=[sys.executable,str(ROOT/'tools/universal/build.py'),'--source',str(archive),'--engine','stm32cubeide-gcc','--native-target',target,'--work',str(root/('work-'+mode)),'--out',str(out),'--request-id','0'*32]
        run=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);print(run.stdout)
        if mode=='valid':
            run.check_returncode()
            m=json.loads((out/'manifest.json').read_text())['build']
            assert m['wbFullProject'] is True and m['memory']['flashKiB']==32 and m['wbFlashRanges'][0]['start']==0x08000000
            audit=m['wbMemoryAudit'];assert audit['layout']=='wb55-sram192-rm0434'
            assert any(s['area']=='sram2a' and s['loadStart'] is None and s['name']=='MAPPING_TABLE' and s['start']==0x20030000 for s in audit['sections'])
            if os.environ.get('FS_WB_WEB_AUDIT'):
                subprocess.run(['node',str(ROOT/'tests/wb_web_contract.mjs'),str(out),os.environ['FS_WB_WEB_AUDIT']],check=True)
            print('WB_FULL_PROJECT_PASS custom shared RAM NOLOAD and CPU1 HEX + ELF audit')
        elif mode.startswith('wb') and mode!='wb35-ram-gap':
            run.check_returncode()
            m=json.loads((out/'manifest.json').read_text())['build']
            assert m['wbMemoryAudit']['layout']=='wb3x5x-sram%d-an5451'%ram
            if os.environ.get('FS_WB_WEB_AUDIT'):
                subprocess.run(['node',str(ROOT/'tests/wb_web_contract.mjs'),str(out),os.environ['FS_WB_WEB_AUDIT']],check=True)
            print('WB_GEOMETRY_PASS '+target)
        elif mode=='ota':
            run.check_returncode()
            m=json.loads((out/'manifest.json').read_text())['build']
            assert m['wbOtaOrigin']==0x08007000 and m['wbOtaLayout']=='st-ble-app-0x7000'
            assert m['wbFlashRanges'][0]['start']==0x08007000
            b=(out/'firmware.bin').read_bytes();assert int.from_bytes(b[-4:],'little')==0x94448a29
            if os.environ.get('FS_WB_WEB_AUDIT'):
                subprocess.run(['node',str(ROOT/'tests/wb_web_contract.mjs'),str(out),os.environ['FS_WB_WEB_AUDIT']],check=True)
            print('WB_OTA_PROJECT_PASS relocated application and end marker')
        else:
            expected={'wb35-ram-gap':'WB ELF allocation outside','ota-bad-marker':'WB OTA end marker invalid','ota-reserved-ram':'WB ELF allocation outside','outside-budget':'WB HEX must contain only CPU1','outside-ram':'WB ELF allocation outside','initialized-shared':'WB shared SRAM requires'}[mode]
            assert run.returncode and expected in run.stdout,run.stdout
            print('WB_FULL_PROJECT_REJECT '+mode)
