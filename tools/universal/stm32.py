"""STM32 source-only, CubeMX and CubeIDE adapters. No ST proprietary binaries bundled."""
import json, os, re, shutil, xml.etree.ElementTree as ET
import stm32_middleware, stm32_git, cubeide_gcc, stm32_catalog, wb_project
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PROFILES=json.loads((ROOT/'profiles/stm32-bare.json').read_text())
ENGINES={'stm32-bare','stm32cubemx','stm32cubeide','stm32cubeide-gcc'}
SKIP={'Drivers','Middlewares','Debug','Release','build','examples','libraries','lib'}
SOURCE_SKIP={'Debug','Release','build','examples','.git','.pio','__MACOSX'}
CUBE_TAGS={'f0':'v1.11.4','f1':'v1.8.4',**{p['family']:p['cubeTag'] for p in PROFILES.values() if 'cubeTag' in p},**stm32_catalog.CUBE_TAGS}
SOURCE_EXT={'.c','.cpp','.cc','.cxx','.s','.S'}
HEADER_EXT={'.h','.hpp','.hh','.hxx'}

def source_files(root):
    return sorted(f for f in root.rglob('*') if f.is_file() and f.suffix in SOURCE_EXT|HEADER_EXT and not any(x in SOURCE_SKIP for x in f.relative_to(root).parts[:-1]))

def source_root(root,main):
    # The upload is one project. Common root includes sibling Inc/Src/lib trees.
    paths=source_files(root)+[f for name in ('flasher-native.json',stm32_git.MANIFEST,stm32_git.LOCK) for f in root.rglob(name)]
    return Path(os.path.commonpath([str(f.parent) for f in paths])) if paths else main.parent

def source_config(p,main=None):
    configs=[f for f in p.rglob('flasher-native.json') if not any(x in SOURCE_SKIP for x in f.relative_to(p).parts[:-1])]
    if len(configs)>1:raise ValueError('Several flasher-native.json files')
    obj=json.loads(configs[0].read_text()) if configs else {}
    if not isinstance(obj,dict):raise ValueError('Expected native configuration object')
    return obj

def driver_modes(paths,family):
    text='\n'.join(f.read_text(errors='replace') for f in paths if f.suffix in SOURCE_EXT|HEADER_EXT)
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    # Includes in user headers are scanned too; reject explicit other-family headers.
    found=set(re.findall(r'(?im)^\s*#\s*include\s*[<\"][^>\"\n]*?stm32([a-z][0-9]|wb|wl)xx(?:_[^>\"\n]*)?\.h[>\"]',text))
    if found - {family}:raise ValueError('STM32 header family differs from selected MCU: '+', '.join(sorted(found)))
    hal=bool(re.search(r'(?i)stm32'+family+r'xx_hal(?:_|\.h)|\b(?:__)?HAL_[A-Za-z0-9_]+',text))
    ll=bool(re.search(r'(?i)stm32'+family+r'xx_ll_|\bLL_[A-Za-z0-9_]+',text))
    return hal,ll


def files(root,pattern):
    return sorted(p for p in root.rglob(pattern) if p.is_file() and not any(x in SKIP for x in p.relative_to(root).parts[:-1]))

def ioc_fields(p):
    return dict(line.split('=',1) for line in p.read_text(errors='replace').splitlines() if '=' in line and not line.startswith('#'))

def detect(root,target=''):
    projects=[p for p in files(root,'.project') if (p.parent/'.cproject').is_file()]
    if projects:
        if len(projects)!=1:raise ValueError('Several CubeIDE projects; select one')
        return 'stm32cubeide-gcc' if cubeide_gcc.candidate(projects[0].parent) else 'stm32cubeide'
    iocs=files(root,'*.ioc')
    if iocs:
        if len(iocs)!=1:raise ValueError('Several CubeMX projects; select one')
        if any(k in ioc_fields(iocs[0]) for k in ('Mcu.Name','Mcu.CPN','Mcu.UserName')):return 'stm32cubemx'
        raise ValueError('Invalid .ioc: no MCU configuration')
    mains=files(root,'main.c')+files(root,'main.cpp')
    if len(mains)==1 and (target.upper().startswith('STM32') or any(root.rglob('flasher-native.json'))):return 'stm32-bare'
    return None

def profile(target):
    name=target.upper()
    if name in PROFILES:return name,PROFILES[name]
    # Exact ordering code or a known base part; never extrapolate memory from a family.
    matches=[k for k in PROFILES if re.fullmatch(re.escape(k)+r'[A-Z][0-9](?:TR)?',name)]
    if len(matches)==1:return name,PROFILES[matches[0]]
    family=stm32_catalog.family_of(name)
    # Reject incomplete names before fetching a package. STM32 order codes have a package/density pair.
    if len(name)<11:raise ValueError('Incomplete STM32 part number: '+target)
    if family not in CUBE_TAGS:raise ValueError('No source-only SDK provisioned for '+family+'; use complete project')
    return name,stm32_catalog.resolve(name)

def config(root,engine,target='',version=''):
    if version and version!='system':raise ValueError('STM32 adapter uses provisioned tools; SDK version must be system')
    if engine=='stm32-bare':
        mains=files(root,'main.c')+files(root,'main.cpp')
        if len(mains)!=1:raise ValueError('Bare metal requires exactly one main.c or main.cpp')
        p=source_root(root,mains[0]); obj=source_config(root)
        if obj.get('engine',engine)!=engine:raise ValueError('Conflicting native engine')
        if 'wbOtaLayout' in obj:raise ValueError('WB OTA requires complete CubeIDE GNU project')
        declared=obj.get('target','')
        if target and declared and target.upper()!=declared.upper():raise ValueError('Conflicting STM32 targets')
        target,_=profile(target or declared)
    elif engine=='stm32cubemx':
        iocs=files(root,'*.ioc')
        if len(iocs)!=1:raise ValueError('Expected one .ioc')
        p=iocs[0].parent; values=ioc_fields(iocs[0]); declared=values.get('Mcu.CPN') or values.get('Mcu.UserName') or values.get('Mcu.Name','')
        if not declared or not re.fullmatch(r'STM32[A-Za-z0-9_()/-]{1,80}',declared):raise ValueError('Invalid .ioc MCU')
        if target and target.upper()!=declared.upper():raise ValueError('Target differs from .ioc; omit override')
        target=declared
        # Do not silently replace any existing user source. Full projects use CubeIDE/Make/CMake.
        if any(f.suffix.lower() in {'.c','.cpp','.h','.hpp','.s','.ld'} for f in root.rglob('*') if f.is_file()):raise ValueError('CubeMX generation accepts .ioc plus flasher-user-code.json only; compile existing source project without regeneration')
    else:
        projects=[f for f in files(root,'.project') if (f.parent/'.cproject').is_file()]
        if len(projects)!=1:raise ValueError('Expected one CubeIDE .project + .cproject')
        p=projects[0].parent
        if engine=='stm32cubeide-gcc' and target.upper().startswith('STM32WB'):
            target,recipe=profile(target)
            plan=cubeide_gcc.parse(p,exact_target=target)
            wb_project.validate_plan(plan,target,recipe)
            wb_project.budget(source_config(p),recipe)
        else:
            if target and target!='project-configured':raise ValueError('CubeIDE uses MCU from its project; omit target override')
            target='project-configured'
            if engine=='stm32cubeide-gcc':
                plan=cubeide_gcc.parse(p)
                if plan['target'].startswith('STM32WB'):raise ValueError('WB requires an exact selected target and explicit application budget')
    return p,target,'system'

def linker(profile):
    # ST GNU startup expects these symbols. Flash and RAM are verified per profile.
    wb_sections = ''
    if profile.get('wbApplicationOnly'):
        # ST CPU1 startup expects mailbox initializer bounds even without WPAN.
        # An empty range keeps startup from touching the radio/shared SRAM.
        # KEEP catches actual mailbox inputs even with --gc-sections: a wireless
        # application needs an explicit, reviewed shared-memory layout.
        wb_sections = '''
 _sMB_MEM2 = _ebss;
 _eMB_MEM2 = _sMB_MEM2;
 _siMB_MEM2 = _sidata;
 .wb_shared_forbidden (NOLOAD) : { KEEP(*(MAPPING_TABLE MAPPING_TABLE.* .MAPPING_TABLE .MAPPING_TABLE.* MB_MEM1 MB_MEM1.* .MB_MEM1 .MB_MEM1.* MB_MEM2 MB_MEM2.* .MB_MEM2 .MB_MEM2.*)) } > RAM
 ASSERT(SIZEOF(.wb_shared_forbidden) == 0, "WB shared radio memory requires a complete project")
'''
    return '''ENTRY(Reset_Handler)
MEMORY {
 FLASH (rx) : ORIGIN = 0x%08X, LENGTH = %dK
 RAM (xrw) : ORIGIN = 0x%08X, LENGTH = %dK
}
_estack = ORIGIN(RAM) + LENGTH(RAM);
SECTIONS {
 .isr_vector : { KEEP(*(.isr_vector)) } > FLASH
 .text : { *(.text*) *(.rodata*) KEEP(*(.init)) KEEP(*(.fini)) . = ALIGN(4); } > FLASH
 .ARM.extab : { *(.ARM.extab*) } > FLASH
 .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > FLASH
 .preinit_array : { PROVIDE_HIDDEN(__preinit_array_start = .); KEEP(*(.preinit_array*)) PROVIDE_HIDDEN(__preinit_array_end = .); } > FLASH
 .init_array : { PROVIDE_HIDDEN(__init_array_start = .); KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array*)) PROVIDE_HIDDEN(__init_array_end = .); } > FLASH
 .fini_array : { PROVIDE_HIDDEN(__fini_array_start = .); KEEP(*(SORT(.fini_array.*))) KEEP(*(.fini_array*)) PROVIDE_HIDDEN(__fini_array_end = .); } > FLASH
 _sidata = LOADADDR(.data);
 .data : { . = ALIGN(4); _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT> FLASH
 .bss (NOLOAD) : { . = ALIGN(4); _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
%s . = ALIGN(8); _end = .; end = .;
 ASSERT(_end + 256 <= _estack, "Insufficient RAM for minimum stack")
}
'''%(profile.get('flashOrigin',0x08000000),profile['flashKiB'],profile.get('ramOrigin',0x20000000),profile['ramKiB'],wb_sections)

def driver_plan(p,work,recipe,sdk,git_sources=(),git_dirs=()):
    paths=list(dict.fromkeys(source_files(p)+list(git_sources)+[f for d in git_dirs for f in d.rglob('*') if f.is_file() and f.suffix in HEADER_EXT])); family=recipe['family']; prefix='stm32'+family+'xx'
    source=[f for f in paths if f.suffix in SOURCE_EXT]
    if any(f.name.lower().startswith(('startup_','system_stm32')) for f in source) or any(p.rglob('*.ld')):raise ValueError('Source-only mode supplies startup/system/linker; use full project for custom files')
    if any(re.fullmatch(r'stm32(?:[a-z][0-9]|wb|wl)xx_(?:hal|ll)(?:_.*)?\.c',f.name.lower()) for f in source):raise ValueError('Bundled ST driver implementation: use full project rather than mixing SDK versions')
    hal,ll=driver_modes(paths,family)
    mw=stm32_middleware.detect(paths)
    if family=='wb' and mw:raise ValueError('WB automatic middleware provisioning disabled pending component license review; supply a complete licensed project')
    if 'usb-device' in mw:hal=True
    core=sdk/'Drivers'/'CMSIS'/'Include';device=sdk/'Drivers'/'CMSIS'/'Device'/'ST'/('STM32'+family.upper()+'xx');driver=sdk/'Drivers'/('STM32'+family.upper()+'xx_HAL_Driver');templates=device/'Source'/'Templates'
    startup=templates/'gcc'/('startup_'+recipe['define'].lower()+('_cm4.s' if family=='wb' else '.s')); system=templates/('system_'+prefix+'.c')
    if not all(x.exists() for x in (core,device/'Include',startup,system)):raise ValueError('STM32Cube CMSIS SDK missing or incompatible')
    if 'deviceCatalog' in recipe:
        header=device/'Include'/(prefix+'.h')
        if not header.is_file() or not re.search(r'\b'+re.escape(recipe['define'])+r'\b',header.read_text(errors='replace')):raise ValueError('DFP macro not present in pinned STM32Cube SDK; use full project')
    dirs=sorted({p,*[f.parent for f in paths if f.suffix in HEADER_EXT]})+list(git_dirs)+[core,device/'Include']
    extra=[]; flags=[]; generated=False
    obj=source_config(p);hse=obj.get('hseHz')
    if hse is not None:
        if type(hse) is not int or not 1_000_000<=hse<=50_000_000:raise ValueError('hseHz must be an integer between 1000000 and 50000000')
        flags.append('-DHSE_VALUE='+str(hse)+'U')
    if hal or ll:
        inc=driver/'Inc'; src=driver/'Src'
        if not inc.is_dir() or not src.is_dir():raise ValueError('STM32Cube HAL/LL package missing')
        dirs.extend([inc,inc/'Legacy'])
        flags.append('-DUSE_FULL_LL_DRIVER')
        # HAL can call LL functions; compile both sets when HAL is selected.
        if hal:
            flags.append('-DUSE_HAL_DRIVER')
        # Some LL sources (notably ll_usb.c) include the HAL header even in LL-only builds.
        if hal or ll:
            name=prefix+'_hal_conf.h';configs=[f for f in paths if f.name==name]
            if len(configs)>1:raise ValueError('Several HAL configuration headers')
            if not configs:
                generated=True; gen=work/'generated-config';gen.mkdir();template=inc/(prefix+'_hal_conf_template.h')
                shutil.copyfile(template,gen/name);dirs.insert(0,gen)
                print('[stm32] Using ST default HAL config; set HSE_VALUE or supply hal_conf.h for your board',flush=True)
            else:
                dirs=[configs[0].parent]+[d for d in dirs if d!=configs[0].parent]
        usb_ll=ll and any(re.search(r'(?i)(?:'+prefix+r'_ll_usb\.h|\bUSB_(?:[A-Z]|LL_))', f.read_text(errors='replace')) for f in paths if f.suffix in SOURCE_EXT|HEADER_EXT)
        for f in sorted(src.glob('*.c')):
            # Timebase and MSP templates must never override user handlers.
            if 'template' in f.name.lower():continue
            if f.name.startswith(prefix+'_ll_') or ((hal or usb_ll) and (f.name==prefix+'_hal.c' or f.name.startswith(prefix+'_hal_'))):extra.append(f)
        # ST weak default IRQ goes to Default_Handler. Supply a fallback only
        # with HAL, before startup object; user strong handler takes precedence.
        if (hal or usb_ll) and 'freertos' not in mw:
            tick=work/'hal_default_tick.c';tick.write_text('#include "'+prefix+'_hal.h"\n__attribute__((weak)) void SysTick_Handler(void) { HAL_IncTick(); }\n');extra.append(tick)
    ms,mi,mf,mm=stm32_middleware.plan(paths,sdk,recipe,obj,mw)
    return [*source,*extra,*ms,startup,system],list(dict.fromkeys([*dirs,*mi])),[*flags,*mf],{'hal':hal,'ll':ll,'generatedHalConfig':generated,'hseHzOverride':hse,'middleware':mm}

def cpu_flags(recipe):
    return ['-mcpu='+('cortex-m0plus' if recipe['cpu']=='cortex-m0+' else recipe['cpu']),'-mthumb']+(['-mfpu='+recipe['fpu'],'-mfloat-abi=hard'] if recipe.get('fpu') else [])

# Only the actual FS10 package geometry is supported, never arbitrary user offsets.
RECOVERY_LAYOUT={'id':'fs10-stm32f103c8','applicationOffset':0x08004000,'maxAppBytes':47*1024,'metadataOffset':0x0800fc00}
def recovery_profile(p,target,recipe):
    value=source_config(p).get('recoveryLayout')
    if value is None:return recipe,None
    if value!=RECOVERY_LAYOUT['id'] or target.upper()!='STM32F103C8T6' or recipe['flashKiB']!=64 or recipe['ramKiB']!=20:
        raise ValueError('FS10 Recovery requires exact STM32F103C8T6 and known 64 KiB Flash')
    return dict(recipe,flashOrigin=RECOVERY_LAYOUT['applicationOffset'],flashKiB=47),dict(RECOVERY_LAYOUT)

def recovery_system_source(work):
    p=work/'flasher_recovery_system.c'
    p.write_text('#include "stm32f1xx.h"\nextern void FlasherOriginalSystemInit(void);\nvoid SystemInit(void) { FlasherOriginalSystemInit(); SCB->VTOR = 0x08004000UL; __DSB(); __ISB(); }\n')
    return p

def wb_application_recipe(p,recipe):
    if not recipe.get('wbApplicationOnly'):return recipe
    value=source_config(p).get('wbAppFlashKiB',32)
    # Caller supplies a verified application budget, never a request to
    # disable protection. Reserve at least a page for secure radio area.
    page=2 if recipe['physicalFlashKiB']==320 else 4
    if type(value) is not int or value<page or value%page or value>recipe['physicalFlashKiB']-page:
        raise ValueError('wbAppFlashKiB must be page aligned and below physical Flash; read SFSA on target')
    return dict(recipe,flashKiB=value)

def bare_build(p,work,target,run):
    _,recipe=profile(target);recipe=wb_application_recipe(p,recipe);sdk=Path(os.environ.get('FS_SDK_PATH','/nonexistent'))
    # Fetch declared Git sources outside upload tree; scan their headers for HAL/LL/MW too.
    git_sources,git_dirs,git_records=stm32_git.install(p,work)
    source,dirs,driver_flags,mode=driver_plan(p,work,recipe,sdk,git_sources,git_dirs)
    link_recipe,recovery=recovery_profile(p,target,recipe)
    if recovery:source.append(recovery_system_source(work))
    flags=[*cpu_flags(recipe),'-D'+recipe['define'],'-Os','-g','-ffunction-sections','-fdata-sections',*driver_flags,*['-I'+str(d) for d in dirs]]
    objdir=work/'bare-objects';objdir.mkdir();out=work/'native-output';out.mkdir();ld=work/'bare.ld';ld.write_text(linker(link_recipe));objects=[]
    cpp=False
    for n,f in enumerate(source):
        iscpp=f.suffix in {'.cpp','.cc','.cxx'};cpp|=iscpp;compiler='arm-none-eabi-g++' if iscpp else 'arm-none-eabi-gcc';obj=objdir/f'{n}.o'
        run('ccache',compiler,*flags,*(['-DSystemInit=FlasherOriginalSystemInit'] if recovery and f.name=='system_stm32f1xx.c' else []),*(['-std=gnu++17','-fno-exceptions','-fno-rtti'] if iscpp else ['-std=gnu11'] if f.suffix=='.c' else []),'-c',f,'-o',obj);objects.append(obj)
    elf=out/'firmware.elf';run('arm-none-eabi-g++' if cpp else 'arm-none-eabi-gcc',*cpu_flags(recipe),'-T',ld,'--specs=nano.specs','--specs=nosys.specs','-Wl,--gc-sections','-Wl,-Map='+str(out/'firmware.map'),*objects,'-o',elf)
    run('arm-none-eabi-objcopy','-O','ihex',elf,out/'firmware.hex');run('arm-none-eabi-objcopy','-O','binary',elf,out/'firmware.bin')
    meta={'engine':'stm32-bare','target':target,'sdkVersion':'system','memory':recipe,'drivers':mode,'cubeTag':CUBE_TAGS[recipe['family']], 'cubeCommit':run('git','rev-parse','HEAD',cwd=sdk,capture=True).strip(),'toolchain':run('arm-none-eabi-gcc','--version',capture=True).splitlines()[0]}
    if recovery:meta['recoveryLayout']=recovery
    if git_records:meta['stm32GitLibraries']=git_records
    return out,meta

BLOCK=re.compile(r'(/\* USER CODE BEGIN ([^*\r\n]+?) \*/)(.*?)(/\* USER CODE END \2 \*/)',re.S)
def apply_user_code(root,manifest):
    if not manifest.is_file():return
    obj=json.loads(manifest.read_text());pending=[]
    if not isinstance(obj,dict):raise ValueError('Expected mapping of generated files to USER CODE blocks')
    for rel,blocks in obj.items():
        path=(root/rel).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix not in {'.c','.h','.cpp','.hpp'} or not isinstance(blocks,dict):raise ValueError('Invalid USER CODE path: '+rel)
        text=path.read_text();found={}
        for m in BLOCK.finditer(text):found[m[2]]=found.get(m[2],0)+1
        if any(found.get(k)!=1 or not isinstance(v,str) or 'USER CODE BEGIN' in v or 'USER CODE END' in v for k,v in blocks.items()):raise ValueError('Unknown, duplicate or invalid USER CODE block in '+rel)
        pending.append((path,BLOCK.sub(lambda m:m[1]+'\n'+blocks[m[2]]+'\n'+m[4] if m[2] in blocks else m[0],text)))
    for path,text in pending:path.write_text(text)

def tool(name):
    value=os.environ.get(name,'');p=Path(value)
    if not value or not p.is_absolute() or not p.is_file() or not os.access(p,os.X_OK):raise ValueError('Provision licensed ST tool and set '+name)
    return p

def mx_script(ioc,generated):
    for p in (ioc,generated):
        if any(c in str(p) for c in '\n\r"'):raise ValueError('Invalid CubeMX path')
    return '\n'.join([f'config load "{ioc}"','project name FlasherGenerated','project toolchain Makefile','SetCopyLibrary "copy only"',f'project path "{generated}"','project generate','exit',''])

def proprietary_build(p,work,engine,target,run,copy_outputs):
    out=work/'native-output'
    if engine=='stm32cubemx':
        exe=tool('FS_CUBEMX_EXECUTABLE');generated=work/'generated';generated.mkdir();script=work/'cubemx-script.txt';script.write_text(mx_script(next(p.glob('*.ioc')),generated))
        run('xvfb-run','-a',exe,'-q',script,cwd=exe.parent)
        makefiles=list(generated.rglob('Makefile'))
        if len(makefiles)!=1:raise ValueError('CubeMX did not generate one Makefile; check firmware pack, version and license')
        project=makefiles[0].parent
        if not any((project/rel).is_file() for rel in ('Core/Src/main.c','Src/main.c')) or not list(project.rglob('*.ld')):raise ValueError('Generated project incomplete')
        apply_user_code(project,p/'flasher-user-code.json');build=work/'native-build';run('make','-j2','BUILD_DIR='+str(build),cwd=project);copy_outputs(build,out,True)
    else:
        exe=tool('FS_CUBEIDE_EXECUTABLE');name=ET.parse(p/'.project').findtext('name','')
        if not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',name):raise ValueError('Invalid CubeIDE project name')
        config=ET.parse(p/'.cproject');names={x.get('name') for x in config.iter('configuration') if x.get('name')}
        chosen='Release' if 'Release' in names else 'Debug' if 'Debug' in names else next(iter(names)) if len(names)==1 else ''
        if chosen in {'.','..'} or not re.fullmatch(r'[A-Za-z0-9_. -]{1,80}',chosen):raise ValueError('Ambiguous CubeIDE build configuration')
        # Remove previous generated products; never package a stale binary.
        folder=p/chosen
        if folder.exists():shutil.rmtree(folder)
        run('xvfb-run','-a',exe,'--launcher.suppressErrors','-nosplash','-application','org.eclipse.cdt.managedbuilder.core.headlessbuild','-data',work/'workspace','-import',p,'-cleanBuild',name+'/'+chosen,'-no-indexer','-printErrorMarkers',cwd=exe.parent)
        copy_outputs(folder,out,True)
    for elf in out.glob('*.elf'):
        if not (out/(elf.stem+'.hex')).exists():run('arm-none-eabi-objcopy','-O','ihex',elf,out/(elf.stem+'.hex'))
    return out,{'engine':engine,'target':target,'sdkVersion':'system','toolchain':run('arm-none-eabi-gcc','--version',capture=True).splitlines()[0] if engine=='stm32cubemx' else 'CubeIDE managed project; see log'}
