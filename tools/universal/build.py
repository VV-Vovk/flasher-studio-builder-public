#!/usr/bin/env python3
"""Compile a real uploaded Arduino or PlatformIO project in an isolated CI job."""
import argparse, hashlib, json, os, re, shutil, stat, subprocess, sys, time, zipfile
from pathlib import Path, PurePosixPath
from auto_libraries import compile_project
from install_libraries import install_declared, LIBRARY_LINE
from dependencies import snapshot, read_lock, make_lock, verify_versions, properties
import git_libraries, flash_layout, stm32
from native import detect_native, native_build, native_config
from pio_build import build_pio
ROOT=Path(__file__).resolve().parents[2]
CORES=json.loads((ROOT/'profiles/arduino-cores.json').read_text())
FQBN_RE=re.compile(r'[A-Za-z0-9_]+:[A-Za-z0-9_]+:[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+=[A-Za-z0-9_.+-]+(?:,[A-Za-z0-9_.-]+=[A-Za-z0-9_.+-]+)*)?')
RID_RE=re.compile(r'[a-f0-9]{32}')
SUFFIXES={'.bin','.hex','.uf2','.elf','.map','.eep'}

# Retry only idempotent network-dependent setup operations, not compilation.
NETWORK_SETUP = {('core','update-index'), ('core','install'), ('lib','update-index'), ('lib','install')}
TRANSIENT = re.compile(r'(?i)(?:\b(?:502|503|504|429)\b|connection reset|connection refused|temporary failure|i/o timeout|context deadline exceeded|TLS handshake timeout|unexpected EOF|network is unreachable|timed out|timeout awaiting response headers)')

def run(*args, cwd=None, capture=False):
    cmd=list(map(str,args))
    retryable=cmd[0]=='arduino-cli' and tuple(cmd[1:3]) in NETWORK_SETUP
    for attempt in range(3 if retryable else 1):
        print('[command]', ' '.join(cmd),flush=True)
        if not retryable:
            result=subprocess.run(cmd,cwd=cwd,text=True,capture_output=capture,timeout=1200)
            if result.returncode and capture:
                if result.stdout:print(result.stdout,flush=True)
                if result.stderr:print(result.stderr,file=sys.stderr,flush=True)
            result.check_returncode()
            return result.stdout
        result=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True,timeout=1200)
        if result.stderr: print(result.stderr, file=sys.stderr, flush=True)
        if result.stdout and (not capture or result.returncode): print(result.stdout,flush=True)
        if not result.returncode:return result.stdout if capture else None
        if attempt==2 or not TRANSIENT.search((result.stdout or '')+'\n'+(result.stderr or '')):
            result.check_returncode()
        print('[network] Temporary download failure; retrying setup',flush=True)
        time.sleep(2 if attempt==0 else 5)


def unpack(source,dest):
    if source.stat().st_size>15*1024*1024: raise ValueError('Source exceeds 15 MiB')
    dest.mkdir(parents=True,exist_ok=False)
    if source.suffix=='.ino':
        shutil.copyfile(source,dest/'sketch.ino');return
    if source.suffix in {'.c','.cpp','.ioc'}:
        shutil.copyfile(source,dest/('main'+source.suffix if source.suffix!='.ioc' else 'project.ioc'));return
    if source.suffix!='.zip': raise ValueError('Expected ZIP, INO, C, CPP or IOC')
    with zipfile.ZipFile(source) as z:
        entries=z.infolist();seen=set()
        if len(entries)>12000 or sum(i.file_size for i in entries)>150*1024*1024: raise ValueError('Archive limits: 12000 entries / 150 MiB')
        for i in entries:
            p=PurePosixPath(i.filename); mode=(i.external_attr>>16)&0o170000
            if not p.parts or p.is_absolute() or '..' in p.parts or '\\' in i.filename or ':' in i.filename or mode not in (0,stat.S_IFREG,stat.S_IFDIR): raise ValueError('Unsafe archive member: '+i.filename)
            if any(x in {'.git','.github','.pio','__MACOSX','__pycache__'} for x in p.parts): continue
            if i.is_dir(): continue
            if p in seen: raise ValueError('Duplicate archive member: '+str(p))
            seen.add(p);target=dest.joinpath(*p.parts);target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(i) as src,target.open('xb') as out: shutil.copyfileobj(src,out)

def detect(root,target=''):
    pio=list(root.rglob('platformio.ini'))
    if len(pio)==1:return 'platformio'
    if len(pio)>1:raise ValueError('Several PlatformIO projects; upload one project')
    inos=[p for p in root.rglob('*.ino') if not any(x in {'libraries','lib','examples'} for x in p.relative_to(root).parts[:-1])]
    native=detect_native(root)
    if native and inos:raise ValueError('Multiple build systems detected; select engine explicitly')
    if native:return native
    if inos:return 'arduino'
    stm=stm32.detect(root,target)
    if stm:return stm
    raise ValueError('No supported project: expected INO, platformio.ini, or supported native SDK project')

def choose_sketch(root):
    inos=[p for p in root.rglob('*.ino') if not any(x in {'libraries','lib','examples'} for x in p.relative_to(root).parts[:-1])]
    parents={p.parent for p in inos}
    if len(parents)!=1:raise ValueError('Expected one Arduino sketch folder')
    parent=next(iter(parents));matching=[p for p in inos if p.stem==parent.name]
    if len(matching)==1:return parent,matching[0]
    if len(inos)==1:return parent,inos[0]
    raise ValueError('Several INO tabs: primary filename must match its folder')

def validate_fqbn(fqbn):
    if not FQBN_RE.fullmatch(fqbn):raise ValueError('Exact Arduino FQBN required')
    core=':'.join(fqbn.split(':')[:2])
    if core not in CORES:raise ValueError('Unsupported Arduino core: '+core)
    return core

def arduino(root,work,fqbn,version,libraries):
    core=validate_fqbn(fqbn);recipe=CORES[core];version=version or recipe['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-.][A-Za-z0-9.-]+)?',version):raise ValueError('Invalid core version')
    os.environ['FS_ARCH']=core.split(':')[1]
    parent,primary=choose_sketch(root)
    # Preserve original primary filename and tab ordering, even for a ZIP wrapper.
    sketch_name=primary.stem if re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}',primary.stem) else 'sketch'
    sketch=work/'sketch'/sketch_name;shutil.copytree(parent,sketch)
    if sketch_name!=primary.stem:
        if (sketch/(sketch_name+'.ino')).exists():raise ValueError('Conflicting sketch name')
        (sketch/primary.name).rename(sketch/(sketch_name+'.ino'))
    local=work/'local-libraries';local.mkdir()
    # Copy only outermost libraries, not example libraries nested inside them.
    candidates={p.parent:p for p in root.rglob('library.properties')}
    # Arduino supports legacy libraries without metadata. Only accept explicitly
    # bundled directories, not arbitrary folders containing sketch headers.
    for owner in [parent, *parent.parents]:
        if not owner.is_relative_to(root): break
        for container in (owner/'libraries',owner/'lib'):
            if not container.is_dir():continue
            for library in container.iterdir():
                if not library.is_dir():continue
                if any(p.is_file() and p.suffix.lower() in {'.h','.hpp','.hh','.hxx'} for base in (library,library/'src') if base.is_dir() for p in base.iterdir()):
                    candidates.setdefault(library,None)
    copied=[];local_names=set()
    for library,manifest in sorted(candidates.items(),key=lambda item:(len(item[0].parts),str(item[0]))):
        if library==parent or library==root or any(x in {'examples','extras','tests'} for x in library.relative_to(root).parts) or any(library.is_relative_to(p) for p in copied):continue
        if parent.is_relative_to(library):continue
        name=properties(manifest).get('name',library.name) if manifest else library.name
        target=local/library.name
        if target.exists() or name in local_names:raise ValueError('Duplicate local library: '+name)
        shutil.copytree(library,target);copied.append(library);local_names.add(name)
    for p in ('libraries','lib'):
        d=sketch/p
        if d.is_dir():shutil.rmtree(d)
    # No installed user libraries leak between requests, even on a local runner.
    sketchbook=work/'sketchbook';sketchbook.mkdir()
    os.environ['ARDUINO_DIRECTORIES_USER']=str(sketchbook.resolve())
    lock_data=read_lock(root,parent,fqbn,version)
    locked, old_declared=lock_data if lock_data is not None else (None, [])
    git_records=[];declared_git=git_libraries.read_declared(root,parent)
    if locked is not None:
        lock_path=next(p/'flasher-lock.json' for p in [parent,*parent.parents] if p.is_relative_to(root) and (p/'flasher-lock.json').is_file())
        git_specs=git_libraries.validate(json.loads(lock_path.read_text()).get('gitLibraries',[]))
        if any(not any(all(d[k]==g[k] for k in ('url','ref','folder')) for g in git_specs) for d in declared_git):raise ValueError('Git dependency declaration differs from lock')
    else:git_specs=declared_git
    for spec in git_specs:
        git_libraries.install_recipe(spec['url'],spec['ref'],local/spec['folder'],git_records,expected=spec.get('commit') if locked is not None else None)
        name=properties(local/spec['folder']/'library.properties').get('name',spec['folder'])
        if name in local_names:raise ValueError('Duplicate Git library: '+name)
        local_names.add(name)
    run('arduino-cli','config','init','--overwrite')
    if recipe.get('url'):run('arduino-cli','config','add','board_manager.additional_urls',recipe['url'])
    run('arduino-cli','core','update-index');run('arduino-cli','core','install',core+'@'+version)
    if core=='adafruit:nrf52' and shutil.which('adafruit-nrfutil') is None:
        # Arduino Linux platform invokes this external executable during export.
        venv=work/'nrfutil-venv'
        run(sys.executable,'-m','venv',venv)
        run(venv/'bin/python','-m','pip','install','adafruit-nrfutil==0.5.3.post16')
        os.environ['PATH']=str(venv/'bin')+os.pathsep+os.environ.get('PATH','')
        run('adafruit-nrfutil','--help')
    run('arduino-cli','lib','update-index')
    run('arduino-cli','board','details','--fqbn',fqbn)
    names=[]
    for f in reversed([p/'libraries.txt' for p in [parent,*parent.parents] if p.is_relative_to(root)]):
        if f.is_file(): names.extend(f.read_text().splitlines())
    names.extend(libraries.splitlines());names=list(dict.fromkeys(x.strip() for x in names if x.strip() and not x.strip().startswith('#')))
    if len(names)>15 or any(len(n)>100 or not LIBRARY_LINE.fullmatch(n) for n in names):raise ValueError('Invalid declared libraries')
    requested_pins={}
    if locked is not None:
        if names and any(n not in old_declared and n not in locked and n.rpartition('@')[0] not in locked and n not in local_names for n in names):
            raise ValueError('Declared libraries differ from lockfile; remove lockfile to resolve again')
        for n in names:
            key,sep,v=n.rpartition('@')
            if n not in old_declared and sep and v.lower()!='latest' and locked.get(key)!=v:
                raise ValueError('Declared library version differs from lockfile: '+n)
        for name,ver in sorted(locked.items()):
            run('arduino-cli','lib','install','--no-deps',name+'@'+ver)
        verify_versions(locked,snapshot(sketchbook),exact=True)
    else:
        for name in names:
            key,sep,ver=name.rpartition('@')
            if (key if sep else name) in local_names:
                if sep and ver.lower()!='latest':
                    raise ValueError('Bundled library version is defined by its source: '+name)
                continue
            resolved=install_declared(name)
            key,sep,ver=resolved.rpartition('@')
            if sep and ver.lower()!='latest':
                if key in requested_pins and requested_pins[key]!=ver:raise ValueError('Conflicting declared versions: '+key)
                requested_pins[key]=ver
        if requested_pins:verify_versions(requested_pins,snapshot(sketchbook))
    build=work/'build';build.mkdir()
    added=compile_project(sketch,build,None,fqbn=fqbn,local_libs=local,locked=locked is not None,git_context=(local,git_records))
    actual=json.loads(run('arduino-cli','lib','list','--json',capture=True))
    meta={'engine':'arduino','fqbn':fqbn,'core':core,'coreVersion':version,'installedLibraries':actual,'bundledLibraries':[p.name for p in local.iterdir()]}
    try:
        versions=snapshot(sketchbook)
    except ValueError as exc:
        if locked is not None or requested_pins:raise
        meta['lockUnavailable']=str(exc)
    else:
        verify_versions(locked if locked is not None else requested_pins,versions,exact=locked is not None)
        if any('@' in n for n in (added or [])) and not git_records:
            meta['lockUnavailable']='Git fallback lacks verified commit metadata'
        else:
            meta['dependencyLock']=make_lock(fqbn,version,versions,names or old_declared)
            if git_records:meta['dependencyLock']['gitLibraries']=git_records
    if core=='esp32:esp32':
        try:
            props=run('arduino-cli','compile','--show-properties=expanded','--fqbn',fqbn,'--build-path',build,'--libraries',local,sketch,capture=True)
            data_dir=Path(os.environ.get('ARDUINO_DIRECTORIES_DATA',str(Path.home()/'.arduino15')))
            meta['flashSegments']=flash_layout.arduino_esp(build,props,data_dir/'packages')
        except (ValueError,OSError,TypeError,subprocess.SubprocessError) as e:
            meta['flashLayoutWarning']=str(e)
    return build,meta

def platformio(root,environment):
    return build_pio(root,environment,run)

def package(build,out,meta,rid):
    if not build.is_dir():raise ValueError('Build output missing')
    # Only actual top-level build products, not library objects or unrelated assets.
    paths=sorted(p for p in build.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUFFIXES)
    if not any(p.suffix.lower() in {'.bin','.hex','.uf2'} and p.stat().st_size>0 for p in paths):raise ValueError('No flashable build output found')
    if sum(p.stat().st_size for p in paths)>64*1024*1024:raise ValueError('Artifacts exceed 64 MB')
    out.mkdir(parents=True,exist_ok=False);files=[]
    for p in paths:
        shutil.copyfile(p,out/p.name);data=(out/p.name).read_bytes()
        files.append({'file':p.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'format':p.suffix.lower()[1:]})
    if 'dependencyLock' in meta:
        lock=out/'flasher-lock.json';lock.write_text(json.dumps(meta['dependencyLock'],ensure_ascii=False,indent=2)+'\n')
        meta['lockFileSha256']=hashlib.sha256(lock.read_bytes()).hexdigest()
    native_locks={}
    if meta.get('stm32GitLibraries'):
        path=out/'flasher-stm32-lock.json';path.write_text(json.dumps(meta['stm32GitLibraries'],indent=2)+'\n');native_locks[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if 'nativeDependencyLock' in meta:
        lock=meta.pop('nativeDependencyLock');path=out/'dependencies.lock';path.write_text(lock['text']);native_locks[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if 'westManifestFrozen' in meta:
        path=out/'west-frozen.yml';path.write_text(meta.pop('westManifestFrozen'));native_locks[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if native_locks:meta['nativeDependencyFiles']=native_locks
    (out/'manifest.json').write_text(json.dumps({'schema':2,'requestId':rid,'build':meta,'files':files,'flashLayout':flash_layout.describe(out,files,meta),'automaticFlashingAllowed':False},ensure_ascii=False,indent=2))

def main():
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--work',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--engine',choices=['auto','arduino','platformio','esp-idf','stm32cube','zephyr','pico-sdk','stm32-bare','stm32cubemx','stm32cubeide','stm32cubeide-gcc'],default='auto');a.add_argument('--fqbn',default='');a.add_argument('--core-version',default='');a.add_argument('--environment',default='');a.add_argument('--libraries',default='');a.add_argument('--request-id',required=True);a.add_argument('--native-target',default='');a.add_argument('--sdk-version',default='');x=a.parse_args()
    if not RID_RE.fullmatch(x.request_id):raise ValueError('Invalid request ID')
    x.work=x.work.resolve();x.out=x.out.resolve();x.source=x.source.resolve()
    x.work.mkdir(parents=True,exist_ok=True);root=x.work/'input';unpack(x.source,root)
    engine=detect(root,x.native_target) if x.engine=='auto' else x.engine
    if engine=='arduino':build,meta=arduino(root,x.work,x.fqbn,x.core_version,x.libraries)
    elif engine=='platformio':
        if x.libraries.strip():raise ValueError('Use lib_deps in platformio.ini')
        build,meta=platformio(root,x.environment)
    elif engine in stm32.ENGINES:
        if x.libraries.strip():raise ValueError('Use project source dependencies for STM32')
        p,target,version=stm32.config(root,engine,x.native_target,x.sdk_version)
        if engine=='stm32-bare':
            if os.environ.get('FS_NATIVE_ENGINE')!=engine:raise ValueError('Bare-metal SDK not provisioned')
            build,meta=stm32.bare_build(p,x.work,target,run)
        elif engine=='stm32cubeide-gcc':
            if os.environ.get('FS_NATIVE_ENGINE')!=engine:raise ValueError('CubeIDE GNU environment not provisioned')
            build,meta=stm32.cubeide_gcc.build(p,x.work,run,exact_target=target if target.startswith('STM32WB') else '')
        else:
            from native import copy_outputs
            build,meta=stm32.proprietary_build(p,x.work,engine,target,run,copy_outputs)
    else:
        if x.libraries.strip():raise ValueError('Use native project dependency manifests')
        build,meta=native_build(root,x.work,engine,x.native_target,x.sdk_version,run)
    meta['sourceSha256']=hashlib.sha256(x.source.read_bytes()).hexdigest()
    package(build,x.out,meta,x.request_id)

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,subprocess.SubprocessError,OSError,zipfile.BadZipFile) as e:sys.exit('[Flasher Studio] '+str(e))
