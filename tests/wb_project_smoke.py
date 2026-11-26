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
    for mode in ('valid','outside-budget','outside-ram','initialized-shared'):
        script=original
        if mode=='outside-budget':script=script.replace('0x08000000','0x08010000')
        if mode=='outside-ram':script=script.replace('0x20030000, LENGTH = 1K','0x20040000, LENGTH = 1K')
        if mode=='initialized-shared':script=script.replace('.mailbox (NOLOAD)', '.mailbox').replace('} > SHARED','} > SHARED AT> FLASH')
        (p/'flash.ld').write_text(script)
        if mode=='initialized-shared':
            f=p/'Core/Src/main.c';f.write_text(f.read_text().replace('mailbox;','mailbox=7;'))
        archive=root/(mode+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for x in p.rglob('*'):
                if x.is_file():z.write(x,x.relative_to(p))
        out=root/('out-'+mode)
        cmd=[sys.executable,str(ROOT/'tools/universal/build.py'),'--source',str(archive),'--engine','stm32cubeide-gcc','--native-target','STM32WB55RGV6','--work',str(root/('work-'+mode)),'--out',str(out),'--request-id','0'*32]
        run=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);print(run.stdout)
        if mode=='valid':
            run.check_returncode()
            m=json.loads((out/'manifest.json').read_text())['build']
            assert m['wbFullProject'] is True and m['memory']['flashKiB']==32 and m['wbFlashRanges'][0]['start']==0x08000000
            audit=m['wbMemoryAudit'];assert audit['layout']=='wb55-sram192-rm0434'
            assert any(s['area']=='sram2a' and s['loadStart'] is None and s['name']=='MAPPING_TABLE' and s['start']==0x20030000 for s in audit['sections'])
            print('WB_FULL_PROJECT_PASS custom shared RAM NOLOAD and CPU1 HEX + ELF audit')
        else:
            expected={'outside-budget':'WB HEX must contain only CPU1','outside-ram':'WB ELF allocation outside','initialized-shared':'WB shared SRAM requires'}[mode]
            assert run.returncode and expected in run.stdout,run.stdout
            print('WB_FULL_PROJECT_REJECT '+mode)
