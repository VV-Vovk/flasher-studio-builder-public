"""Explicit public Git dependencies for C/C++ STM32 projects, with immutable replay."""
import json,re
from pathlib import Path,PurePosixPath
import git_libraries

MANIFEST='flasher-stm32-libraries.json'; LOCK='flasher-stm32-lock.json'

def relative(root,raw):
    if not isinstance(raw,str) or '\\' in raw or ':' in raw:raise ValueError('Invalid Git library path')
    p=PurePosixPath(raw)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Git library path escapes repository')
    result=(root/str(p)).resolve()
    if not result.is_relative_to(root.resolve()):raise ValueError('Git library path escapes repository')
    return result

def entries(obj,locked=False):
    git_libraries.validate(obj,locked)
    for x in obj:
        for key in ('sources','includeDirs'):
            if not isinstance(x.get(key),list) or not x[key] or len(x[key])>200:raise ValueError('Specify nonempty '+key+' for STM32 Git library')
            if len(set(map(str,x[key])))!=len(x[key]):raise ValueError('Duplicate Git library path')
            for raw in x[key]:relative(Path('/virtual'),raw)
    return obj

def read(p,name):
    files=list(p.rglob(name))
    if not files:return None
    if len(files)!=1 or files[0].stat().st_size>65536:raise ValueError('Expected one small '+name)
    return json.loads(files[0].read_text())

def install(p,work):
    declared=read(p,MANIFEST);locked=read(p,LOCK)
    if declared is None and locked is None:return [],[],[]
    declared=entries(declared if declared is not None else locked,declared is None)
    if locked is not None:
        locked=entries(locked,True)
        if [{k:v for k,v in x.items() if k!='commit'} for x in declared]!=[{k:v for k,v in x.items() if k!='commit'} for x in locked]:raise ValueError('STM32 Git lock conflicts with manifest')
    base=work/'stm32-git';base.mkdir();sources=[];dirs=[];records=[]
    for i,x in enumerate(declared):
        commit=locked[i]['commit'] if locked is not None else git_libraries.resolve(x['url'],x['ref'])
        dest=base/x['folder'];git_libraries.checkout(x['url'],commit,dest)
        for raw in x['sources']:
            f=relative(dest,raw)
            if not f.is_file() or f.suffix not in ('.c','.cpp','.cc','.cxx','.s','.S'):raise ValueError('Expected explicit C/C++/ASM source in Git library: '+raw)
            sources.append(f)
        for raw in x['includeDirs']:
            d=relative(dest,raw)
            if not d.is_dir():raise ValueError('Git library include directory missing: '+raw)
            dirs.append(d)
        records.append({**x,'commit':commit})
    return sources,dirs,records
