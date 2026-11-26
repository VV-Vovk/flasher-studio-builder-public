"""Resolve public GitHub libraries to immutable commits; never use arbitrary URL schemes."""
import json, os, re, shutil, subprocess
from pathlib import Path
URL=re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git')
SHA=re.compile(r'[a-f0-9]{40}')
REF=re.compile(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,120}')

def resolve(url,ref,runner=subprocess.run):
    if not URL.fullmatch(url) or not REF.fullmatch(ref) or '..' in ref or '@{' in ref:raise ValueError('Only public HTTPS GitHub URLs and ordinary refs are accepted')
    if SHA.fullmatch(ref):return ref
    result=runner(['git','ls-remote','--exit-code',url,'refs/tags/'+ref+'^{}','refs/tags/'+ref,'refs/heads/'+ref],text=True,capture_output=True,check=True,timeout=90)
    found={name:sha for sha,name in (line.split() for line in result.stdout.splitlines())}
    tag=found.get('refs/tags/'+ref+'^{}',found.get('refs/tags/'+ref));branch=found.get('refs/heads/'+ref)
    if tag and branch and tag!=branch:raise ValueError('Git ref is ambiguous: '+ref)
    commit=tag or branch
    if not commit or not SHA.fullmatch(commit):raise ValueError('Unable to resolve Git ref: '+ref)
    return commit

def checkout(url,commit,dest,runner=subprocess.run):
    if not URL.fullmatch(url) or not SHA.fullmatch(commit):raise ValueError('Invalid pinned Git source')
    dest.mkdir(parents=True,exist_ok=False)
    for args in [('init','-q'),('fetch','--depth=1',url,commit),('checkout','--detach','FETCH_HEAD')]:
        runner(['git','-c','core.hooksPath=/dev/null',*args],cwd=dest,check=True,timeout=180)
    actual=runner(['git','rev-parse','HEAD'],cwd=dest,text=True,capture_output=True,check=True,timeout=30).stdout.strip()
    if actual!=commit:raise ValueError('Git checkout commit mismatch')
    if (dest/'.gitmodules').exists():raise ValueError('Git submodules not supported in Arduino Git libraries; bundle source instead')
    if any(p.is_symlink() for p in dest.rglob('*')):raise ValueError('Git library contains symlinks')
    shutil.rmtree(dest/'.git')

def install_recipe(url,ref,dest,records,runner=subprocess.run,expected=None):
    commit=expected or resolve(url,ref,runner)
    checkout(url,commit,dest,runner)
    if not (dest/'library.properties').is_file():raise ValueError('Git library has no library.properties: '+url)
    records.append({'url':url,'ref':ref,'commit':commit,'folder':dest.name})
    return commit

def read_declared(root,parent):
    files=[p/'flasher-git-libraries.json' for p in [parent,*parent.parents] if p.is_relative_to(root) and (p/'flasher-git-libraries.json').is_file()]
    if not files:return []
    if len(files)!=1 or files[0].stat().st_size>32768:raise ValueError('Expected one Git libraries manifest')
    obj=json.loads(files[0].read_text());return validate(obj,False)

def validate(obj,locked=True):
    if not isinstance(obj,list) or len(obj)>15:raise ValueError('Invalid Git libraries list')
    folders=set()
    for p in obj:
        if not isinstance(p,dict) or not all(isinstance(p.get(k),str) for k in ('url','ref','folder')) or not URL.fullmatch(p['url']) or not REF.fullmatch(p['ref']) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}',p['folder']) or p['folder'] in folders or (locked and (not isinstance(p.get('commit'),str) or not SHA.fullmatch(p['commit']))):raise ValueError('Invalid Git library entry')
        folders.add(p['folder'])
    return obj
