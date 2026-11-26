"""Native SDK adapters. Build only projects that provide their own build configuration."""
import json,os,re,shutil,subprocess
from pathlib import Path
from flash_layout import idf_segments
ENGINES={'esp-idf','stm32cube','zephyr','pico-sdk'}
DEFAULTS={'esp-idf':'v5.4.2','zephyr':'v4.1.0','pico-sdk':'2.1.1','stm32cube':'system'}
SKIP={'build','Debug','Release','.git','.pio','Drivers','Middlewares','lib','libraries','examples','managed_components'}

def candidates(root):
    found=[]
    for path in sorted(root.rglob('CMakeLists.txt')):
        if any(x in SKIP for x in path.relative_to(root).parts[:-1]):continue
        text=path.read_text(errors='replace')[:65536].lower()
        if 'idf_path' in text and 'project.cmake' in text:engine='esp-idf'
        elif re.search(r'find_package\s*\(\s*zephyr\b',text):engine='zephyr'
        elif 'pico_sdk_init' in text or 'pico_sdk_import.cmake' in text:engine='pico-sdk'
        elif ('stm32cubemx' in text or 'stm32cube' in text or (path.parent/'Core'/'Src').is_dir()) and re.search(r'\bproject\s*\(',text):engine='stm32cube'
        else:continue
        found.append((engine,path.parent))
    for p in root.rglob('Makefile'):
        if any(x in SKIP for x in p.relative_to(root).parts[:-1]):continue
        if (p.parent/'Core'/'Src').is_dir() and (list(p.parent.glob('*.ioc')) or 'arm-none-eabi' in p.read_text(errors='replace')[:65536]):found.append(('stm32cube',p.parent))
    return sorted(set(found),key=lambda x:(x[0],str(x[1])))

def detect_native(root):
    found=candidates(root)
    if len(found)>1:raise ValueError('Several native projects found; upload one project')
    return found[0][0] if found else None

def native_config(root,engine,target='',version=''):
    choices=[p for e,p in candidates(root) if e==engine]
    if len(choices)!=1:raise ValueError('Expected one complete '+engine+' project (not just .ioc or source files)')
    p=choices[0]; config=p/'flasher-native.json'
    obj=json.loads(config.read_text()) if config.is_file() else {}
    if not isinstance(obj,dict) or obj.get('engine',engine)!=engine:raise ValueError('Native project configuration does not match engine')
    project_version=obj.get('sdkVersion','');project_target=obj.get('target','')
    if version and project_version and str(version).removeprefix('v')!=str(project_version).removeprefix('v'):raise ValueError('SDK version conflicts with project configuration')
    if target and project_target and target!=project_target:raise ValueError('Native target conflicts with project configuration')
    version=version or project_version or DEFAULTS[engine];target=target or project_target
    if engine=='esp-idf':
        detected=set()
        for name in ('sdkconfig','sdkconfig.defaults'):
            f=p/name
            if f.is_file():detected.update(re.findall(r'^CONFIG_IDF_TARGET="(esp32[a-z0-9]*)"',f.read_text(errors='replace'),re.M))
        if len(detected)>1 or (target and detected and target not in detected):raise ValueError('Conflicting ESP-IDF targets')
        target=target or next(iter(detected),'')
        if target not in {'esp32','esp32s2','esp32s3','esp32c2','esp32c3','esp32c6','esp32h2','esp32p4'}:raise ValueError('Choose exact ESP-IDF target')
    elif engine=='pico-sdk':
        if not target:
            match=re.search(r'(?im)^\s*set\s*\(\s*PICO_BOARD\s+"?([a-zA-Z0-9_]+)',(p/'CMakeLists.txt').read_text());target=match[1] if match else ''
        if not target or not re.fullmatch(r'[A-Za-z0-9_]{1,80}',target):raise ValueError('Choose Pico SDK board (e.g. pico, pico_w, pico2)')
    elif engine=='zephyr':
        if not target or not re.fullmatch(r'[A-Za-z0-9_./-]{1,100}',target) or '..' in target:raise ValueError('Choose exact Zephyr board, including qualifiers')
        # Standard upstream Zephyr only. A custom west workspace needs separate provisioning.
        if list(root.rglob('west.yml')):raise ValueError('Custom west manifest/workspace not supported; use standard Zephyr project and declared SDK version')
    elif not target:target='project-configured'
    if engine=='stm32cube':
        if version!='system':raise ValueError('STM32Cube uses the runner ARM toolchain, bundled HAL/CMSIS and generated build files')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',target):raise ValueError('Invalid STM32 target')
    elif not re.fullmatch(r'v?\d+\.\d+\.\d+',version):raise ValueError('Use an exact SDK release version')
    if engine in {'esp-idf','zephyr'} and not version.startswith('v'):version='v'+version
    if engine=='pico-sdk':version=version.removeprefix('v')
    return p,target,version

def copy_outputs(src,out,recursive=False):
    out.mkdir();suffixes={'.bin','.hex','.elf','.uf2','.map','.eep'}
    paths=src.rglob('*') if recursive else src.iterdir()
    for p in sorted(paths):
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in suffixes or any(x in {'CMakeFiles','_deps','pico-sdk','pico-sdk-build','boot_stage2'} for x in p.relative_to(src).parts):continue
        dest=out/p.name
        if dest.exists():raise ValueError('Multiple build outputs named '+p.name)
        shutil.copyfile(p,dest)

def native_build(root,work,engine,target,version,run):
    p,target,version=native_config(root,engine,target,version)
    # SDKs installed by the trusted workflow before user code is executed.
    if os.environ.get('FS_NATIVE_ENGINE')!=engine or os.environ.get('FS_NATIVE_VERSION')!=version:raise ValueError('Native SDK not provisioned; run build-universal.yml or setup-native.sh')
    sdk=Path(os.environ.get('FS_SDK_PATH','/nonexistent'));build=work/'native-build';out=work/'native-output';meta={'engine':engine,'target':target,'sdkVersion':version}
    if engine!='stm32cube':meta['sdkCommit']=run('git','rev-parse','HEAD',cwd=sdk,capture=True).strip()
    if engine=='esp-idf':
        # The environment exports the exact SDK; target is checked against sdkconfig.
        run('bash','-c','source "$1/export.sh" >/dev/null && shift && exec idf.py "$@"','fs',sdk,'-B',build,'-D','IDF_TARGET='+target,'build',cwd=p)
        segments,settings=idf_segments(build);out.mkdir()
        for item in segments:shutil.copyfile(item['source'],out/item['file'])
        meta['flashSegments']=[{k:v for k,v in item.items() if k!='source'} for item in segments];meta['flashSettings']=settings
        for f in build.glob('*.elf'):shutil.copyfile(f,out/f.name)
        if (p/'dependencies.lock').is_file():meta['nativeDependencyLock']={'file':'dependencies.lock','text':(p/'dependencies.lock').read_text()}
    elif engine=='zephyr':
        run('west','build','-b',target,'-d',build,p,cwd=sdk.parent)
        copy_outputs(build/'zephyr',out)
        try:
            meta['westManifestFrozen']=run('west','manifest','--freeze',cwd=sdk.parent,capture=True)
        except (subprocess.CalledProcessError,OSError,subprocess.TimeoutExpired):
            # Narrow west update can omit inactive repositories; freeze expects
            # them all. Keep the successful firmware, record actual checkouts.
            meta['westManifestWarning']='Full manifest freeze unavailable; only checked-out project revisions recorded'
            projects=[]
            try:
                for line in run('west','list','-f','{name}\t{abspath}\t{revision}',cwd=sdk.parent,capture=True).splitlines():
                    fields=line.split('\t')
                    if len(fields)!=3:continue
                    name,path,revision=fields; path=Path(path)
                    if not (path/'.git').exists():continue
                    try:commit=run('git','rev-parse','HEAD',cwd=path,capture=True).strip()
                    except (subprocess.CalledProcessError,OSError,subprocess.TimeoutExpired):continue
                    if re.fullmatch(r'[0-9a-f]{40}',commit):projects.append({'name':name,'requestedRevision':revision,'commit':commit})
            except (subprocess.CalledProcessError,OSError,subprocess.TimeoutExpired):
                meta['westManifestWarning']='Full freeze and project inventory unavailable; SDK commit only'
            meta['westCheckedOutProjects']=projects
    elif engine=='pico-sdk':
        run('cmake','-S',p,'-B',build,'-G','Ninja','-DPICO_SDK_PATH='+str(sdk),'-DPICO_BOARD='+target,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER_LAUNCHER=ccache','-DCMAKE_CXX_COMPILER_LAUNCHER=ccache')
        run('cmake','--build',build,'--parallel','2');copy_outputs(build,out,True)
    elif engine=='stm32cube':
        if (p/'CMakeLists.txt').is_file():
            # CubeMX generated CMake usually includes a toolchain file in cmake/.
            toolchains=[f for f in (p/'cmake'/'gcc-arm-none-eabi.cmake',p/'cmake'/'arm-none-eabi-gcc.cmake',p/'cmake'/'arm-none-eabi.cmake') if f.is_file()]
            if len(toolchains)!=1:raise ValueError('Bundle the CubeMX GNU ARM CMake toolchain file under cmake/')
            run('cmake','-S',p,'-B',build,'-G','Ninja','-DCMAKE_TOOLCHAIN_FILE='+str(toolchains[0]),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER_LAUNCHER=ccache','-DCMAKE_CXX_COMPILER_LAUNCHER=ccache')
            run('cmake','--build',build,'--parallel','2');copy_outputs(build,out,True)
        else:
            run('make','-j2','BUILD_DIR='+str(build),cwd=p);copy_outputs(build,out,True)
        meta['toolchain']=run('arm-none-eabi-gcc','--version',capture=True).splitlines()[0]
        # Cube CMake may export ELF only. Derive self-addressed HEX with objcopy.
        for elf in out.glob('*.elf'):
            if not (out/(elf.stem+'.hex')).exists():run('arm-none-eabi-objcopy','-O','ihex',elf,out/(elf.stem+'.hex'))
    return out,meta
