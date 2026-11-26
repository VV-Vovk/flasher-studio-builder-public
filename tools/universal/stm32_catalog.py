"""Resolve exact STM32 devices from maintained Open-CMSIS-Pack DFP descriptions.
No inference from density letters, flash algorithms or similar part numbers.
Only plain single-core internal-flash layouts are eligible for source-only builds.
"""
import argparse, hashlib, json, os, re, tempfile, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from functools import lru_cache

# Pin the ST firmware package separately from the hardware metadata snapshot.
CUBE_TAGS={'f7':'v1.17.3','h7':'v1.12.0','wb':'v1.24.0'}
CATALOG_FAMILIES=('c0','f0','f1','f2','f3','f4','f7','g0','g4','h7','l0','l4','h5','u5','wb','wl','l5')
CORES={'Cortex-M0':'cortex-m0','Cortex-M0+':'cortex-m0plus','Cortex-M3':'cortex-m3','Cortex-M4':'cortex-m4','Cortex-M7':'cortex-m7'}
LIMIT=12*1024*1024

def family_of(name):
    m=re.fullmatch(r'STM32([A-Z][0-9]|WB|WL)[A-Z0-9]{3,15}(?:TR)?',name.upper())
    if not m or m[1].lower() not in CATALOG_FAMILIES:raise ValueError('Unknown or incomplete STM32 part number: '+name)
    return m[1].lower()

def pack_name(family):
    if family not in CATALOG_FAMILIES:raise ValueError('Unknown STM32 DFP family')
    return 'STM32'+family.upper()+'xx_DFP'

def pack_urls(family):
    n=pack_name(family)
    return ('https://raw.githubusercontent.com/Open-CMSIS-Pack/'+n+'/main/Keil.'+n+'.pdsc', 'https://www.keil.com/pack/Keil.'+n+'.pdsc')

def xml_root(data,family):
    if len(data)>LIMIT or re.search(br'<!\s*(DOCTYPE|ENTITY)',data,re.I):raise ValueError('Unsafe or oversized DFP XML')
    r=ET.fromstring(data)
    if r.tag!='package' or r.findtext('name')!=pack_name(family) or r.findtext('vendor') not in ('Keil','STMicroelectronics'):raise ValueError('Unexpected DFP package identity')
    return r

def fetch(family):
    # Same runner-local snapshot shared by plan, provisioning and compilation.
    cache=Path(os.environ.get('FS_STM32_DFP_DIR') or (Path(os.environ['RUNNER_TEMP'])/'stm32-dfp' if 'RUNNER_TEMP' in os.environ else Path.home()/'.cache/flasher-stm32-dfp'))
    cache.mkdir(parents=True,exist_ok=True); path=cache/(pack_name(family)+'.pdsc'); provenance=path.with_suffix('.url')
    if path.is_file():
        data=path.read_bytes();xml_root(data,family)
        return data,provenance.read_text().strip() if provenance.is_file() else 'local DFP snapshot'
    if os.environ.get('FS_STM32_DFP_OFFLINE')=='1':raise ValueError('No local DFP snapshot for '+family)
    errors=[]
    for url in pack_urls(family):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Flasher-Studio-Builder'}),timeout=25) as response:data=response.read(LIMIT+1)
            xml_root(data,family)
            with tempfile.NamedTemporaryFile(dir=cache,delete=False) as out:out.write(data);tmp=Path(out.name)
            tmp.replace(path);provenance.write_text(url);return data,url
        except (OSError,ValueError,ET.ParseError) as e:errors.append(str(e))
    raise ValueError('Unable to obtain STM32 DFP '+family+': '+'; '.join(errors))

def rows(root):
    def walk(node,processor,compile_,mem,alg,device=None,variants=()):
        processor=dict(processor);compile_=dict(compile_);mem=dict(mem);alg=dict(alg)
        for child in node:
            a=dict(child.attrib); key=a.get('Pname','')
            if child.tag=='processor':processor[key]={**processor.get(key,{}),**a}
            elif child.tag=='compile':compile_[key]={**compile_.get(key,{}),**a}
            elif child.tag=='memory':
                name=a.get('name') or a.get('id')
                if name:mem[(key,name)]={**mem.get((key,name),{}),**a}
            elif child.tag=='algorithm':
                name=a.get('name')
                if name:alg[(key,name)]={**alg.get((key,name),{}),**a}
        if node.tag=='device':device=node.get('Dname')
        if node.tag=='variant':variants=(node.get('Dvariant'),)
        if node.tag in ('device','variant') and device:
            yield {'name':variants[0] if variants else device,'base':device,'processor':processor,'compile':compile_,'memory':list(mem.values()),'algorithms':list(alg.values())}
        for child in node:
            if child.tag in ('family','subFamily','device','variant'):
                yield from walk(child,processor,compile_,mem,alg,device,variants)
    for family in root.findall('./devices/family'):
        yield from walk(family,{},{},{},{})

def integer(v):
    if not isinstance(v,str) or not re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)',v):raise ValueError('Invalid DFP memory integer')
    return int(v,16 if v.lower().startswith('0x') else 10)

def truth(v):return v in ('1','true','True')

def match_name(pattern,target):
    # CMSIS variant names use lowercase x for temperature/ordering wildcard.
    # All other characters are literal. Optional tape/reel TR only after exact match.
    if not pattern:return False
    regex=''.join('[A-Z0-9]' if c=='x' else re.escape(c.upper()) for c in pattern)
    return bool(re.fullmatch(regex,target.upper()) or (target.upper().endswith('TR') and re.fullmatch(regex,target.upper()[:-2])))

def fpu_flag(cpu,value):
    if value in ('0','false','NO_FPU','None','none'):return None
    if cpu in ('cortex-m0','cortex-m0plus','cortex-m0+','cortex-m3') and value is None:return None
    if cpu=='cortex-m4' and value in ('1','true','SP_FPU'):return 'fpv4-sp-d16'
    if cpu=='cortex-m7' and value=='SP_FPU':return 'fpv5-sp-d16'
    if cpu=='cortex-m7' and value=='DP_FPU':return 'fpv5-d16'
    raise ValueError('Unknown or ambiguous FPU metadata; use full project')

def modern_f1_define(base,legacy):
    # The old StdPeriph DFP groups multiple product lines by density. Translate
    # only known combinations, keeping memory exclusively from the DFP.
    m=re.fullmatch(r'STM32F(10[012357])[A-Z]([468BCDEFG])',base.upper())
    if not m:return legacy
    line,density=m.groups()
    groups={
      '100':{'STM32F10X_LD_VL':('46','B'),'STM32F10X_MD_VL':('8B','B'),'STM32F10X_HD_VL':('CDE','E')},
      '101':{'STM32F10X_LD':('46','6'),'STM32F10X_MD':('8B','B'),'STM32F10X_HD':('CDE','E'),'STM32F10X_XL':('FG','G')},
      '102':{'STM32F10X_LD':('46','6'),'STM32F10X_MD':('8B','B')},
      '103':{'STM32F10X_LD':('46','6'),'STM32F10X_MD':('8B','B'),'STM32F10X_HD':('CDE','E'),'STM32F10X_XL':('FG','G')},
      '105':{'STM32F10X_CL':('8BC','C')},'107':{'STM32F10X_CL':('8BC','C')},
    }
    valid=groups.get(line,{}).get(legacy)
    if valid and density in valid[0]:return 'STM32F'+line+'x'+valid[1]
    return legacy

def profile_from_row(row,family,source,digest):
    processors=row['processor']; named=[k for k in processors if k]
    if len(named)>1:raise ValueError('Multi-core device: use full project with explicit core and memory layout')
    corekey=named[0] if named else ''
    p={**processors.get('',{}),**processors.get(corekey,{})}
    cpu=CORES.get(p.get('Dcore'))
    if not cpu or p.get('Dtz') not in (None,'0','false','NO_TZ'):raise ValueError('Unsupported core or TrustZone: use full project')
    if p.get('Dendian') not in (None,'Little-endian','LittleEndian') and not (family=='wb' and cpu=='cortex-m4' and p.get('Dendian')=='Configurable'):raise ValueError('Unsupported CPU endianness')
    c={**row['compile'].get('',{}),**row['compile'].get(corekey,{})};define=c.get('define','')
    if family=='f1':define=modern_f1_define(row['base'],define)
    if not re.fullmatch(r'STM32[A-Za-z0-9]+',define) or not define.upper().startswith('STM32'+family.upper()):raise ValueError('No unambiguous CMSIS device macro in DFP')
    memory=[]
    for m in row['memory']:
        if m.get('Pname','') not in ('',corekey):continue
        if 'start' not in m or 'size' not in m:continue
        start,size=integer(m['start']),integer(m['size'])
        if size<=0 or start+size>2**32:raise ValueError('Invalid memory range')
        memory.append({'name':m.get('name') or m.get('id'),'start':start,'size':size,'access':m.get('access',''),'default':truth(m.get('default')),'startup':truth(m.get('startup'))})
    def unique_region(addr,flash):
        candidates=[m for m in memory if m['start']==addr and m['default'] and ((m['startup'] and ('x' in m['access'] or str(m['name']).startswith('IROM'))) if flash else ('w' in m['access'] or str(m['name']).startswith('IRAM')))]
        if len(candidates)!=1:raise ValueError('No unique default '+('internal flash' if flash else 'SRAM')+' region; use full project')
        return candidates[0]
    flash=unique_region(0x08000000,True)
    # The default SRAM can start above DTCM (F7), or in AXI SRAM (H7).
    # Use just one explicit ordinary SRAM region, never sum banks/aliases.
    try:ram=unique_region(0x20000000,False)
    except ValueError:
        if family not in ('f7','h7'):raise
        candidates=[m for m in memory if m['default'] and 'w' in m['access'] and str(m['name']).upper() in ('SRAM','SRAM1','AXI_SRAM','AXISRAM','RAM_D1') and (0x20000000<=m['start']<0x20100000 or 0x24000000<=m['start']<0x24100000)]
        if len(candidates)!=1:raise ValueError('No unique ordinary SRAM region for M7; use full project')
        ram=candidates[0]
    if flash['size']%1024 or ram['size']%1024:raise ValueError('Non-KiB memory region; use full project')
    if family=='wb':
        # The reviewed WB DFP describes CPU1 only (Cortex-M4, no named CPU2).
        # Only known RM0434/RM0473 parts, exact DFP sizes, never radio SRAM.
        base=row['base'].upper()
        m=re.fullmatch(r'STM32(WB55|WB50|WB35|WB30|WB5M|WB15|WB10|WB1M)[A-Z]([CEGY])[A-Z]X[A-Z]*',base)
        if not m or cpu!='cortex-m4' or corekey or ram['start']!=0x20000000:raise ValueError('WB requires reviewed CPU1 DFP')
        line,d=m.groups()
        allowed={'WB55':{'C':(256,64),'E':(512,192),'G':(1024,192),'Y':(640,192)},'WB50':{'G':(1024,64)},'WB35':{'C':(256,32),'E':(512,32)},'WB30':{'E':(512,32)},'WB5M':{'G':(1024,192)},'WB15':{'C':(320,12)},'WB10':{'C':(320,12)},'WB1M':{'C':(320,12)}}
        pair=allowed.get(line,{}).get(d)
        if not pair or flash['size']!=pair[0]*1024 or ram['size']<pair[1]*1024:raise ValueError('WB DFP geometry mismatch')
        ram={**ram,'size':pair[1]*1024}
        # DFP reports physical Flash, not the current CPU2 secure boundary.
        # Default source-only build is small; user may set wbAppFlashKiB to
        # their actual SFSA-derived app region. The flasher enforces live SFSA.
        physical=flash['size']//1024
        flash={**flash,'size':32*1024}
    # H7 dual-core and nonstandard boot configurations are not safe to infer.
    if family=='h7' and not re.match(r'STM32H7(?:23|25|30|33|35|42|43|50|53)',row['base'].upper()):raise ValueError('H7 core/boot layout requires explicit project')
    algorithms=[]
    for a in row['algorithms']:
        if a.get('Pname','') not in ('',corekey) or not all(k in a for k in ('start','size','name')):continue
        algorithms.append({'file':a['name'],'start':integer(a['start']),'size':integer(a['size']),'default':truth(a.get('default'))})
    result={'family':family,'define':define,'cpu':cpu,'flashKiB':flash['size']//1024,'ramKiB':ram['size']//1024,'ramOrigin':ram['start'],'memoryNote':'One default internal Flash and SRAM region only; other banks need explicit linker.', 'deviceCatalog':{'device':row['name'],'base':row['base'],'source':source,'sha256':digest,'regions':memory,'flashAlgorithms':algorithms,'programmingInterfaces':'not determined'}}
    if family=='wb':result.update({'physicalFlashKiB':physical,'wbApplicationOnly':True,'memoryNote':'CPU1 only; 32 KiB default app link limit, actual SFSA must be verified on device; no radio SRAM.'})
    fpu=fpu_flag(cpu,p.get('Dfpu'))
    if fpu:result['fpu']=fpu
    return result

def resolve_data(target,family,data,source):
    root=xml_root(data,family);digest=hashlib.sha256(data).hexdigest();matches=[r for r in rows(root) if match_name(r['name'],target)]
    if not matches and family=='f1':
        # Legacy F1 DFP lists exact package/density bases, without temperature suffixes.
        # Accept only the same base + standard two-character ordering suffix.
        matches=[r for r in rows(root) if re.fullmatch(re.escape(r['name'].upper())+r'[A-Z][0-9](?:TR)?',target.upper())]
    if not matches:raise ValueError('Exact device not found in DFP: '+target)
    profiles=[profile_from_row(r,family,source,digest) for r in matches]
    if any({k:v for k,v in r.items() if k!='deviceCatalog'}!={k:v for k,v in profiles[0].items() if k!='deviceCatalog'} for r in profiles[1:]):raise ValueError('Conflicting DFP device matches: '+target)
    return profiles[0]

@lru_cache(maxsize=256)
def resolve(target):
    family=family_of(target);data,source=fetch(family);return resolve_data(target,family,data,source)

def inventory(family,data,source,supported):
    root=xml_root(data,family);digest=hashlib.sha256(data).hexdigest();out=[]
    for row in rows(root):
        item={'name':row['name'],'base':row['base'],'family':family,'sourceOnly':False}
        try:
            if family not in supported:raise ValueError('Family SDK not provisioned')
            p=profile_from_row(row,family,source,digest);item.update({'sourceOnly':True,'profile':p})
        except ValueError as e:item['reason']=str(e)
        out.append(item)
    return {'family':family,'source':source,'sha256':digest,'devices':out}

if __name__=='__main__':
    import stm32
    a=argparse.ArgumentParser();a.add_argument('--family',action='append',choices=CATALOG_FAMILIES);a.add_argument('--output',type=Path,required=True);x=a.parse_args();catalog=[];errors={}
    for family in x.family or CATALOG_FAMILIES:
        try:
            data,source=fetch(family);catalog.append(inventory(family,data,source,stm32.CUBE_TAGS))
        except (OSError,ValueError,ET.ParseError) as e:errors[family]=str(e)
    x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps({'schema':1,'families':catalog,'errors':errors},indent=2)+'\n')
    if errors:raise SystemExit('Catalog incomplete: '+', '.join(errors))
