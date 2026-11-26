"""Conservative importer for standard self-contained STM32CubeIDE GNU projects.
Reject custom/ambiguous builds rather than silently dropping flags or sources.
"""
import os,re,shlex,xml.etree.ElementTree as ET
from pathlib import Path

ENGINE='stm32cubeide-gcc'
EXT={'.c','.cpp','.cc','.cxx','.s','.S'}

def parse_xml(p):
    if p.stat().st_size>4*1024*1024:raise ValueError('CubeIDE XML too large')
    text=p.read_text();
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('CubeIDE XML entities not supported')
    return ET.fromstring(text)

def inside(p,raw,name):
    raw=raw.strip().strip('"').replace('\\','/')
    raw=raw.replace('${workspace_loc:/'+name+'}','.').replace('${ProjDirPath}','.').replace('${project_loc}','.')
    m=re.fullmatch(r'\$\{workspace_loc:/'+re.escape(name)+r'/(.*?)\}',raw)
    if m:raw=m[1]
    # Relative to standard Eclipse build subdirectory.
    if raw.startswith('../'):raw=raw[3:]
    if '$' in raw or ':' in raw or raw.startswith('/') or '..' in Path(raw).parts:raise ValueError('External or unresolved CubeIDE path: '+raw)
    result=(p/raw).resolve()
    if not result.is_relative_to(p.resolve()) or not result.exists():raise ValueError('CubeIDE path missing: '+raw)
    return result

def choose(p):
    root=parse_xml(p/'.cproject'); configs=[x for x in root.iter('configuration') if x.get('name') and x.find('folderInfo') is not None]
    if not configs:raise ValueError('No CubeIDE managed GNU build configuration')
    # Prefer Release, matching existing headless behavior, otherwise Debug or sole configuration.
    chosen=next((n for n in ('Release','Debug') if any(x.get('name')==n for x in configs)),None)
    if chosen:configs=[x for x in configs if x.get('name')==chosen]
    if len(configs)!=1:raise ValueError('Ambiguous CubeIDE build configuration')
    return configs[0]

def candidate(p):
    try:choose(p);return True
    except (OSError,ValueError,ET.ParseError):return False

def parse(p,exact_target=''):
    desc=parse_xml(p/'.project');name=desc.findtext('name','')
    if not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}',name):raise ValueError('Invalid CubeIDE project name')
    if desc.find('linkedResources') is not None and list(desc.find('linkedResources')):raise ValueError('CubeIDE linked resources need a complete portable Make/CMake export')
    cfg=choose(p)
    if any(cfg.get(k,'').strip() for k in ('prebuildStep','postbuildStep','preannouncebuildStep','postannouncebuildStep')) or list(cfg.iter('fileInfo')) or len(list(cfg.iter('folderInfo')))!=1:raise ValueError('CubeIDE custom build steps or per-file/folder settings require native IDE or Make/CMake export')
    tc=cfg.find('folderInfo/toolChain');
    if tc is None or 'stm32cube.ide.mcu.gnu' not in tc.get('superClass','').lower():raise ValueError('Expected standard STM32CubeIDE GNU toolchain')
    target=''; cpu=''; fpu=''; abi=''; ld=[]; global_defs=[]; tools={}
    cpu_map={'cortex-m0':'cortex-m0','cortex-m0plus':'cortex-m0plus','cortex-m0+':'cortex-m0plus','cortex-m3':'cortex-m3','cortex-m4':'cortex-m4','cortex-m7':'cortex-m7','cortex-m33':'cortex-m33'}
    # Toolchain common options store MCU, CPU/FPU and ABI. Recognize enum suffixes.
    for o in tc.findall('option'):
        key=o.get('superClass',o.get('id','')).lower();v=o.get('value','');low=v.lower()
        if key.endswith(('.mcu','.target_mcu')) and re.fullmatch(r'STM32[A-Za-z0-9]+',v):target=v.upper()
        if key.endswith(('.cpuid','.cpu','.core','.target_cpuid')):
            token=low.split('.')[-1];cpu=cpu_map.get(token,cpu)
            m=re.search(r'cortex-m(?:0plus|0\+|0|3|4|7|33)(?![\w+])',low)
            if m:cpu=cpu_map.get(m.group(),cpu)
        if 'fpu' in key:
            m=re.search(r'(fpv[45]-(?:sp-|dp-)?d16|fpv5-d16)',low)
            if m:fpu=m.group(1)
        if 'floatabi' in key or 'float.abi' in key:
            token=low.split('.')[-1];abi=token if token in ('hard','soft','softfp') else abi
    # Fallback to an exact known MCU profile, not family-based guesses.
    if target:
        import stm32
        try:recipe=stm32.profile(exact_target or (target[:-2] if target.endswith('X') and len(target)>11 else target))[1]
        except ValueError:recipe=None
        if recipe:
            if cpu and cpu!=recipe['cpu']:raise ValueError('CubeIDE MCU/CPU mismatch')
            cpu=cpu or recipe['cpu']
            # Standard CubeIDE hard float defaults require explicit ABI if metadata omitted.
            if recipe.get('fpu') and not (fpu or abi):raise ValueError('CubeIDE floating-point configuration absent; export Make/CMake')
    if not cpu:raise ValueError('CubeIDE CPU setting not recognized')
    if fpu and not abi:raise ValueError('CubeIDE FPU configured but float ABI not explicit')
    if abi in ('hard','softfp') and not fpu:raise ValueError('CubeIDE float ABI requires explicit FPU')
    arch=['-mcpu='+cpu,'-mthumb']+(['-mfpu='+fpu] if fpu else [])+(['-mfloat-abi='+abi] if abi else [])
    for t in tc.findall('tool'):
        ident=t.get('superClass','').lower();kind=next((k for k in ('compiler.cpp','compiler.c','assembler','linker.cpp','linker.c') if ident.endswith('.'+k) or ('.'+k+'.') in ident),None)
        # ST actual IDs use .cpp.compiler, .c.compiler, .c.linker, etc.
        if not kind:
            kind=next((k for suffix,k in [('cpp.compiler','compiler.cpp'),('c.compiler','compiler.c'),('assembler','assembler'),('cpp.linker','linker.cpp'),('c.linker','linker.c')] if '.'+suffix in ident),None)
        if not kind:continue
        if t.get('command') and t.get('command') not in {'arm-none-eabi-gcc','arm-none-eabi-g++','arm-none-eabi-as'}:raise ValueError('Custom CubeIDE tool command requires Make/CMake export')
        if kind in tools:raise ValueError('Several CubeIDE tools of same type')
        includes=[];defines=[];extra=[];libs=[];libdirs=[];local_ld=[]
        for o in t.findall('option'):
            key=o.get('superClass',o.get('id','')).lower();v=o.get('value','');typ=o.get('valueType','');values=[x.get('value','') for x in o.findall('listOptionValue')]
            if typ=='includePath' or key.endswith('.includepaths'):
                includes.extend(inside(p,x,name) for x in values)
            elif typ=='definedSymbols' or key.endswith('.definedsymbols'):
                for x in values:
                    if not re.fullmatch(r'[A-Za-z_]\w*(?:=[^\r\n]+)?',x):raise ValueError('Invalid CubeIDE macro')
                    defines.append(x)
            elif typ=='libPaths' or key.endswith('.directories'):libdirs.extend(inside(p,x,name) for x in values)
            elif typ=='libs' or key.endswith('.libraries'):
                if any(not re.fullmatch(r'[A-Za-z0-9_.+-]+',x) for x in values):raise ValueError('Unsupported CubeIDE library')
                libs.extend(values)
            elif 'script' in key and 'linker' in key and v:
                local_ld.append(inside(p,v,name))
            elif ('otherflags' in key or key.endswith('.flags') or 'misc' in key) and (v or values):
                opts=shlex.split(v) if v else values
                # Only simple known flags. Reject custom linker scripts, plugins, response files, etc.
                for flag in opts:
                    if not re.fullmatch(r'-(?:O[0123sgz]|g[0-3]?|std=[A-Za-z0-9+]+|f(?:no-)?(?:exceptions|rtti|common|strict-aliasing|short-enums|stack-usage|function-sections|data-sections)|W(?:all|extra|error|no-[a-z-]+)|u)',flag):raise ValueError('Unsupported CubeIDE custom flag: '+flag)
                extra.extend(opts)
            elif 'linker' in key and ('printf' in key or 'scanf' in key) and v=='true':
                extra.extend(['-u','_printf_float' if 'printf' in key else '_scanf_float'])
            elif 'optimization' in key and 'level' in key and v:
                val=v.rsplit('.',1)[-1].lower();m={'none':'0','optimize':'1','more':'2','most':'3','size':'s','debug':'g','optimizeforsize':'s','optimizefordebug':'g','fast':'3','o0':'0','o1':'1','o2':'2','o3':'3','os':'s','og':'g','ofast':'3'}.get(val)
                if m is not None:extra.append('-O'+m)
        tools[kind]={'includes':includes,'defines':defines,'flags':extra,'libs':libs,'libdirs':libdirs,'ld':local_ld}
    if 'compiler.c' not in tools:raise ValueError('CubeIDE C compiler options not found')
    # CDT source entries and exclusions; never recursively compile excluded code.
    entries=list(cfg.findall('sourceEntries/entry'))
    if not entries:raise ValueError('CubeIDE source entries missing')
    sources=set()
    for entry in entries:
        if entry.get('kind')!='sourcePath':raise ValueError('Unsupported CubeIDE source entry')
        base=inside(p,entry.get('name','.'),name);exclude=entry.get('excluding','').split('|')
        if any('*' in x or '?' in x or '$' in x or '..' in Path(x).parts for x in exclude):raise ValueError('Complex CubeIDE exclusions require Make/CMake export')
        for f in base.rglob('*'):
            rel=f.relative_to(base).as_posix()
            if f.is_file() and f.suffix in EXT and not any(part in {'Debug','Release','build','.git','.settings'} for part in f.relative_to(p).parts) and not any(x and (rel==x.rstrip('/') or rel.startswith(x.rstrip('/')+'/')) for x in exclude):sources.add(f)
    if not sources:raise ValueError('CubeIDE has no selected sources')
    cpp=any(f.suffix in ('.cpp','.cc','.cxx') for f in sources);lk=tools.get('linker.cpp' if cpp else 'linker.c')
    if lk is None:raise ValueError('CubeIDE linker options missing')
    if len(lk['ld'])!=1:raise ValueError('Expected exactly one CubeIDE linker script')
    return {'target':target or 'project-configured','configuration':cfg.get('name'),'arch':arch,'tools':tools,'sources':sorted(sources),'cpp':cpp,'linker':lk}

def build(p,work,run,exact_target=''):
    plan=parse(p,exact_target=exact_target)
    if exact_target:
        import stm32,wb_project
        _,recipe=stm32.profile(exact_target)
        wb_project.validate_plan(plan,exact_target,recipe)
        limit=wb_project.budget(stm32.source_config(p),recipe)
    objdir=work/'cubeide-objects';objdir.mkdir();out=work/'native-output';out.mkdir();objects=[]
    for n,f in enumerate(plan['sources']):
        kind='compiler.cpp' if f.suffix in ('.cpp','.cc','.cxx') else 'assembler' if f.suffix in ('.s','.S') else 'compiler.c'
        t=plan['tools'].get(kind)
        if t is None and kind=='assembler':t=plan['tools']['compiler.c']
        if t is None:raise ValueError('Missing CubeIDE '+kind+' settings')
        obj=objdir/f'{n}.o';flags=[*plan['arch'],'-Os','-g','-ffunction-sections','-fdata-sections',*t['flags'],*['-D'+x for x in t['defines']],*['-I'+str(x) for x in t['includes']]]
        run('ccache','arm-none-eabi-g++' if kind=='compiler.cpp' else 'arm-none-eabi-gcc',*flags,*(['-x','assembler-with-cpp'] if kind=='assembler' else []),'-c',f,'-o',obj,cwd=p);objects.append(obj)
    lk=plan['linker'];elf=out/'firmware.elf'
    run('arm-none-eabi-g++' if plan['cpp'] else 'arm-none-eabi-gcc',*plan['arch'],'-T',lk['ld'][0],*lk['flags'],'--specs=nano.specs','--specs=nosys.specs','-Wl,--gc-sections','-Wl,-Map='+str(out/'firmware.map'),*objects,*['-L'+str(x) for x in lk['libdirs']],'-Wl,--start-group',*['-l'+x for x in lk['libs']],'-lc','-lm','-Wl,--end-group','-o',elf,cwd=p)
    run('arm-none-eabi-objcopy','-O','ihex',elf,out/'firmware.hex');run('arm-none-eabi-objcopy','-O','binary',elf,out/'firmware.bin')
    meta={'engine':ENGINE,'target':plan['target'],'configuration':plan['configuration'],'sdkVersion':'system','toolchain':run('arm-none-eabi-gcc','--version',capture=True).splitlines()[0],'note':'Standard CubeIDE GNU import; generated source and project settings required'}
    if exact_target:
        ranges=wb_project.verify_output(out,recipe,limit)
        meta.update(target=exact_target,memory=dict(recipe,flashKiB=limit),wbFullProject=True,wbFlashRanges=ranges,wbRadioStack='user-supplied; compatibility not verified')
    return out,meta
