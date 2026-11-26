"""PlatformIO dependency resolution: honor project config, only install unique header matches.
Replays exact library versions / public Git commits and verifies inventory. No fuzzy selection."""
import configparser,hashlib,json,os,re,subprocess
from pathlib import Path
from auto_libraries import missing_headers
from git_libraries import resolve
from flash_layout import pio_esp, idf_segments, copy_segments
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
SPEC=re.compile(r'([A-Za-z0-9_.-]+/[A-Za-z0-9 _+.-]+)\s*\n\s*(?:Official |Verified )?Library\s*[•|]\s*([A-Za-z0-9_.+-]+)',re.M)
GIT=re.compile(r'(?:(?P<alias>[A-Za-z0-9_. -]+)\s*=\s*)?(?:git\+)?(?P<url>https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:#(?P<ref>[A-Za-z0-9_./-]+))?')

def choose_match(text):
    text=ANSI.sub('',text);total=re.search(r'Found\s+(\d+)\s+packages?',text)
    matches=list(dict.fromkeys((n.strip(),v) for n,v in SPEC.findall(text)))
    if not total or int(total[1])!=1 or len(matches)!=1:return None
    return '@'.join(matches[0])

def string_list(value):
    if isinstance(value,list):return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value or '').splitlines() if x.strip()]

def pin_git(spec):
    # Support explicit GitHub dependency specifications; other VCS formats remain
    # under PlatformIO's control and are not advertised as reproducibly locked.
    m=GIT.fullmatch(spec)
    if not m:return spec
    url,ref,alias=m['url'],m['ref'],m['alias'];url=url if url.endswith('.git') else url+'.git'
    if ref and ref!='HEAD':commit=resolve(url,ref)
    else:
        raw=subprocess.run(['git','ls-remote',url,'HEAD'],capture_output=True,text=True,check=True,timeout=90).stdout.split()
        if not raw:raise ValueError('Git dependency HEAD not found')
        commit=raw[0]
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('Git dependency commit not resolved')
    return ((alias.strip()+'=') if alias else '')+url+'#'+commit

def digest_tree(path):
    h=hashlib.sha256()
    for p in sorted(path.rglob('*')):
        if p.is_symlink() or not p.is_file() or any(x in {'.git','.piopm','__pycache__'} for x in p.relative_to(path).parts):continue
        h.update(str(p.relative_to(path)).encode()+b'\0');h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()

def libraries_snapshot(project,environment):
    result=[]
    for path in sorted((project/'.pio'/'libdeps'/environment).glob('*')):
        if not path.is_dir():continue
        meta=path/'.piopm'
        if not meta.is_file():continue
        info=json.loads(meta.read_text());spec=info.get('spec') or {};name=info.get('name') or path.name;version=info.get('version');owner=spec.get('owner');uri=spec.get('uri')
        result.append({'folder':path.name,'name':name,'version':version,'owner':owner,'uri':uri,'sha256':digest_tree(path)})
    return result

def rewrite_ini(path,original,environment,overrides):
    parser=configparser.RawConfigParser(strict=False);parser.read_string(original)
    section='env:'+environment
    if not parser.has_section(section):parser.add_section(section)
    for k,v in overrides.items():parser.set(section,k,'\n'.join(v) if isinstance(v,list) else str(v))
    with path.open('w') as f:parser.write(f)


def package_snapshot(directory):
    items=[]
    for path in sorted(directory.glob('*')):
        if not (path/'.piopm').is_file():continue
        meta=json.loads((path/'.piopm').read_text());spec=meta.get('spec') or {}
        name=meta.get('name');version=meta.get('version')
        if not isinstance(name,str) or not isinstance(version,str):raise ValueError('Missing PlatformIO package metadata: '+path.name)
        items.append({'name':name,'version':version,'owner':spec.get('owner'),'uri':spec.get('uri')})
    return items


def comparable(items):
    return sorted((i['name'],i['version'],i.get('sha256','')) for i in items)


def build_pio(root,environment,run):
    configs=list(root.rglob('platformio.ini'))
    if len(configs)!=1:raise ValueError('Expected one platformio.ini')
    project=configs[0].parent
    raw=json.loads(run('pio','project','config','--json-output',cwd=project,capture=True));sections={k:dict(v) for k,v in dict(raw).items()}
    envs=[k[4:] for k in sections if k.startswith('env:')]
    if not environment:
        defaults=sections.get('platformio',{}).get('default_envs',[])
        if isinstance(defaults,str):defaults=[x.strip() for x in defaults.split(',') if x.strip()]
        if len(defaults)==1:environment=defaults[0]
        elif len(envs)==1:environment=envs[0]
        else:raise ValueError('Choose PlatformIO environment: '+', '.join(envs))
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',environment) or environment not in envs or environment in {'.','..'}:raise ValueError('Unknown PlatformIO environment')
    cfg=sections.get('env:'+environment,{})
    os.environ['PLATFORMIO_BUILD_DIR']=str(project/'.pio'/'build');os.environ['PLATFORMIO_LIBDEPS_DIR']=str(project/'.pio'/'libdeps');os.environ['PLATFORMIO_NO_ANSI']='true'
    os.environ['PLATFORMIO_PLATFORMS_DIR']=str(project/'.pio'/'platforms');os.environ['PLATFORMIO_PACKAGES_DIR']=str(project/'.pio'/'packages')
    # Isolate lock from source config, verify configuration identity before replay.
    config_sha=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
    locks=[p/'flasher-lock.json' for p in [project,*project.parents] if p.is_relative_to(root) and (p/'flasher-lock.json').is_file()]
    if len(locks)>1:raise ValueError('Multiple PlatformIO lockfiles')
    lock=json.loads(locks[0].read_text()) if locks else None
    if lock is not None and (lock.get('engine')!='platformio' or lock.get('environment')!=environment or lock.get('configurationSha256')!=config_sha or lock.get('schema')!=1):raise ValueError('PlatformIO lockfile configuration changed; regenerate explicitly')
    deps=[pin_git(d) for d in string_list(cfg.get('lib_deps'))] if lock is None else lock['libDeps']
    if not isinstance(deps,list) or len(deps)>100 or any(not isinstance(x,str) or len(x)>500 or '\n' in x for x in deps):raise ValueError('Invalid PlatformIO lock dependencies')
    initial_platform=cfg.get('platform');initial_tools=string_list(cfg.get('platform_packages'))
    pinned_platform=lock.get('platform') if lock else pin_git(initial_platform) if isinstance(initial_platform,str) else initial_platform
    pinned_tools=lock.get('platformPackages',[]) if lock else [pin_git(d) for d in initial_tools]
    original=configs[0].read_text()
    attempted=set()
    for attempt in range(13):
        # Modify only an isolated copy of the original INI, preserving other settings.
        if deps!=string_list(cfg.get('lib_deps')) or lock or pinned_platform!=initial_platform or pinned_tools!=initial_tools:
            overrides={'lib_deps':deps}
            if pinned_platform:overrides['platform']=pinned_platform
            if pinned_tools:overrides['platform_packages']=pinned_tools
            rewrite_ini(configs[0],original,environment,overrides)
            resolved=json.loads(run('pio','project','config','--json-output',cwd=project,capture=True));actual=dict(dict(resolved)['env:'+environment])
            if string_list(actual.get('lib_deps'))!=deps:raise ValueError('Additional INI files override resolved lib_deps; declare dependencies in the selected environment')
            if pinned_platform and actual.get('platform')!=pinned_platform:raise ValueError('Additional INI files override locked platform')
            if pinned_tools and string_list(actual.get('platform_packages'))!=pinned_tools:raise ValueError('Additional INI files override locked platform packages')
        result=subprocess.run(['pio','run','--environment',environment],cwd=project,text=True,capture_output=True,timeout=1200)
        log=(result.stdout or '')+'\n'+(result.stderr or '');print(log,flush=True)
        if not result.returncode:break
        missing=missing_headers(log)
        if lock or not missing:raise RuntimeError('PlatformIO build failed; see compiler diagnostics')
        for header in missing:
            if header in attempted or len(attempted)>=12 or not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:h|hpp|hh|hxx)',header):raise RuntimeError('Cannot safely resolve PlatformIO header '+header)
            attempted.add(header)
            query='type:library header:"'+header+'"'
            # Arduino-only automatic search for now; other frameworks must declare dependencies.
            frameworks=string_list(cfg.get('framework'))
            if frameworks!=['arduino']:raise RuntimeError('Declare missing native dependency in platformio.ini: '+header)
            result=run('pio','pkg','search',query+' framework:arduino',cwd=project,capture=True)
            spec=choose_match(result)
            # Canonical ArduinoJson provider is known; a fork with the same header
            # should not make the official library impossible to resolve.
            if not spec and header=='ArduinoJson.h':spec=choose_match(run('pio','pkg','search',query+' framework:arduino owner:bblanchon',cwd=project,capture=True))
            if not spec:raise RuntimeError('No unique compatible PlatformIO library for '+header+'; specify lib_deps')
            if spec in deps:raise RuntimeError('Library already selected: '+spec)
            print('[dependencies] '+header+' -> '+spec,flush=True);deps.append(spec)
    else:raise RuntimeError('PlatformIO dependency retry limit')
    meta={'engine':'platformio','environment':environment,'configuration':cfg,'autoDependencies':sorted(attempted)}
    # The CLI report is supplementary. Package metadata is the lock's stable source.
    meta['packageReport']=run('pio','pkg','list','--environment',environment,cwd=project,capture=True)
    libs=libraries_snapshot(project,environment)
    platforms=package_snapshot(project/'.pio'/'platforms');tools=package_snapshot(project/'.pio'/'packages')
    inventory={'platforms':platforms,'tools':tools}
    if not platforms:raise ValueError('PlatformIO installed platform metadata missing; cannot create verified lock')
    if lock:
        if comparable(libs)!=comparable(lock['libraries']) or any(comparable(inventory[k])!=comparable(lock['inventory'][k]) for k in inventory):raise RuntimeError('PlatformIO locked dependency inventory differs')
        meta['dependencyLock']=lock
    else:
        resolved=list(deps)
        for lib in libs:
            owner,name,ver,uri=(lib[k] for k in ('owner','name','version','uri'))
            if name and ver and not uri:
                key=(owner+'/' if owner else '')+name
                resolved=[x for x in resolved if x.split('@',1)[0].strip() not in {key,name}]
                resolved.append(key+'@'+ver)
        platform=pinned_platform;tool_specs=list(pinned_tools)
        if len(platforms)==1 and not platforms[0]['uri']:
            item=platforms[0];platform=(item['owner']+'/' if item['owner'] else '')+item['name']+'@'+item['version']
        for item in tools:
            if item['uri']:continue
            key=(item['owner']+'/' if item['owner'] else '')+item['name']
            tool_specs=[x for x in tool_specs if x.split('@',1)[0].strip() not in {key,item['name']}]
            tool_specs.append(key+'@'+item['version'])
        meta['dependencyLock']={'schema':1,'engine':'platformio','environment':environment,'configurationSha256':config_sha,'libDeps':resolved,'libraries':libs,'inventory':inventory,'platform':platform,'platformPackages':tool_specs}
    output=project/'.pio'/'build'/environment
    if 'espressif32' in str(cfg.get('platform','')):
        try:
            if (output/'flasher_args.json').is_file():
                segments,settings=idf_segments(output)
                meta['flashSegments']=copy_segments(output,[(s['offset'],s['source']) for s in segments],[output],'ESP-IDF flasher_args.json');meta['flashSettings']=settings
            else:
                data=json.loads(run('pio','project','metadata','--environment',environment,'--json-output',cwd=project,capture=True))
                meta['flashSegments']=pio_esp(output,data.get(environment,data),project/'.pio'/'packages')
        except (ValueError,OSError,TypeError,KeyError,subprocess.SubprocessError) as e:meta['flashLayoutWarning']=str(e)
    return output,meta
