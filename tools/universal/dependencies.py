"""Version snapshots for the isolated Arduino sketchbook; never guess a version."""
import json
import re

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _+.-]{0,99}')
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
MAX_LOCK_LIBS = 100


def properties(path):
    result = {}
    for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            result[k.strip()] = v.strip()
    return result


def snapshot(sketchbook):
    found = {}
    for file in sorted((sketchbook / 'libraries').glob('*/library.properties')):
        p = properties(file)
        name, version = p.get('name', ''), p.get('version', '')
        if not NAME.fullmatch(name) or not VERSION.fullmatch(version) or name in found:
            raise ValueError('Cannot lock library metadata: ' + str(file.parent.name))
        found[name] = version
    if len(found) > MAX_LOCK_LIBS:
        raise ValueError('Too many libraries for lockfile')
    return found


def read_lock(root, parent, fqbn, core_version):
    paths = [p/'flasher-lock.json' for p in [parent,*parent.parents] if p.is_relative_to(root) and (p/'flasher-lock.json').is_file()]
    if not paths:
        return None
    if len(paths) != 1 or paths[0].stat().st_size > 65536:
        raise ValueError('Expected one flasher-lock.json (max 64 KB)')
    obj = json.loads(paths[0].read_text(encoding='utf-8'))
    if not isinstance(obj, dict) or obj.get('schema') != 1 or obj.get('engine') != 'arduino' or obj.get('fqbn') != fqbn or obj.get('coreVersion') != core_version:
        raise ValueError('Lockfile target or core version differs; remove lockfile to resolve again')
    libs = obj.get('libraries')
    if not isinstance(libs, dict) or len(libs) > MAX_LOCK_LIBS or any(not isinstance(k,str) or not isinstance(v,str) or not NAME.fullmatch(k) or not VERSION.fullmatch(v) for k,v in libs.items()):
        raise ValueError('Invalid library lockfile')
    declared=obj.get('declared', [])
    if not isinstance(declared,list) or len(declared)>15 or any(not isinstance(n,str) or len(n)>100 for n in declared):
        raise ValueError('Invalid declared library list in lockfile')
    return libs, declared


def make_lock(fqbn, version, libraries, declared=()):
    return {'schema': 1, 'engine': 'arduino', 'fqbn': fqbn, 'coreVersion': version, 'libraries': libraries, 'declared': list(declared)}


def verify_versions(expected, actual, exact=False):
    mismatch = [f'{k}: required {v}, installed {actual.get(k, "missing")}' for k,v in expected.items() if actual.get(k) != v]
    if exact:
        mismatch.extend('unexpected: '+k for k in actual.keys()-expected.keys())
    if mismatch:
        raise RuntimeError('Dependency version conflict: ' + '; '.join(mismatch))
