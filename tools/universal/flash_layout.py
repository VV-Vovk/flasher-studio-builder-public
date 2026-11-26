"""Extract addresses from build-produced metadata or self-addressed formats.
Never infer a BIN address from a filename or MCU family."""
import json, struct
from pathlib import Path

def ranges(parts):
    result=[]
    for start,end in sorted(parts):
        if not 0<=start<end<=2**32: raise ValueError('Invalid address range')
        if result and start<result[-1][1]: raise ValueError('Overlapping address records')
        if result and start==result[-1][1]:result[-1][1]=end
        else:result.append([start,end])
    return [{'start':a,'endExclusive':b,'size':b-a} for a,b in result]

def ihex(path):
    base=0;parts=[];eof=False
    for line in path.read_text('ascii').splitlines():
        if not line.strip():continue
        if eof or not line.startswith(':'):raise ValueError('Invalid HEX record order')
        r=bytes.fromhex(line[1:]);
        if len(r)<5 or len(r)!=r[0]+5 or sum(r)%256:raise ValueError('Invalid HEX checksum or size')
        n,addr,typ=r[0],int.from_bytes(r[1:3],'big'),r[3];data=r[4:-1]
        if typ==0:
            if addr+n>65536:raise ValueError('HEX record crosses segment')
            if n:parts.append((base+addr,base+addr+n))
        elif typ==1 and n==0 and addr==0:eof=True
        elif typ in (2,4) and n==2 and addr==0:base=int.from_bytes(data,'big')<<(4 if typ==2 else 16)
        elif typ in (3,5) and n==4 and addr==0:pass
        else:raise ValueError('Unsupported HEX record')
    if not eof or not parts:raise ValueError('Empty or incomplete HEX')
    return ranges(parts)

def uf2(path):
    data=path.read_bytes();parts=[];families=set();blocks=set();counts=set()
    if not data or len(data)%512:raise ValueError('Invalid UF2 length')
    for i in range(0,len(data),512):
        b=data[i:i+512];a,c,flags,address,n,index,total,family=struct.unpack_from('<8I',b)
        if (a,c,struct.unpack_from('<I',b,508)[0])!=(0x0A324655,0x9E5D5157,0x0AB16F30) or not 0<n<=476 or index>=total or index in blocks:raise ValueError('Invalid UF2 block')
        blocks.add(index);counts.add(total)
        if flags&0x1000:raise ValueError('UF2 file container is not a flash image')
        if flags&1:continue  # not main flash
        if flags&0x2000:families.add(family)
        parts.append((address,address+n))
    if counts!={len(blocks)} or not parts or len(families)>1:raise ValueError('Incomplete or multi-family UF2')
    return ranges(parts),next(iter(families),None)

def idf_segments(build):
    obj=json.loads((build/'flasher_args.json').read_text());mapping=obj.get('flash_files')
    if not isinstance(mapping,dict) or not mapping:raise ValueError('Missing ESP-IDF flash_files')
    parts=[];seen=set()
    for addr,name in mapping.items():
        p=build/name;resolved=p.resolve()
        if not resolved.is_relative_to(build.resolve()) or not p.is_file() or p.is_symlink() or p.suffix.lower()!='.bin' or p.name in seen:raise ValueError('Invalid ESP-IDF flash file')
        seen.add(p.name);offset=int(addr,0);size=p.stat().st_size
        parts.append({'file':p.name,'offset':offset,'size':size,'source':p})
    ranges([(p['offset'],p['offset']+p['size']) for p in parts])
    return sorted(parts,key=lambda p:p['offset']),{k:obj.get(k) for k in ('flash_settings','extra_esptool_args') if k in obj}

def describe(out,files,meta):
    entries=[];warnings=[]
    offsets={p['file']:p for p in meta.get('flashSegments',[])}
    for file in files:
        path=out/file['file'];fmt=file['format']
        try:
            if file['file'] in offsets:
                p=offsets[file['file']]
                if p['size']!=file['size']:raise ValueError('Flash file size changed')
                entries.append({'file':path.name,'addressSpace':'flash-offset','ranges':ranges([(p['offset'],p['offset']+p['size'])]),'source':p.get('source','flasher_args.json'),'alternative':p.get('alternative',False)})
            elif fmt=='hex':
                entries.append({'file':path.name,'addressSpace':'image-address','ranges':ihex(path),'source':'Intel HEX'})
            elif fmt=='uf2':
                rs,family=uf2(path);entries.append({'file':path.name,'addressSpace':'image-address','ranges':rs,'familyId':family,'source':'UF2'})
            elif fmt=='bin':warnings.append(path.name+': address not supplied by build system')
            elif fmt=='eep':warnings.append(path.name+': EEPROM data, not a flash image')
        except (ValueError,OSError,UnicodeError) as e:warnings.append(path.name+': '+str(e))
    return {'entries':entries,'warnings':warnings,'completeForBinSet':bool(offsets) and set(offsets)=={f['file'] for f in files if f['format']=='bin'}}


def copy_segments(build, pairs, roots, source):
    """Only copy known build/core binaries; reject overlaps, collisions, absent files."""
    import shutil
    records=[];pending=[];names=set()
    for offset,path in pairs:
        path=Path(path);path=path if path.is_absolute() else build/path
        path=path.resolve()
        if not any(path.is_relative_to(r.resolve()) for r in roots) or not path.is_file() or path.suffix.lower()!='.bin' or path.name in names:raise ValueError('Missing or unsafe flash image: '+str(path))
        offset=int(str(offset),0);size=path.stat().st_size
        dest=build/path.name
        if dest.exists() and dest.resolve()!=path and dest.read_bytes()!=path.read_bytes():raise ValueError('Flash image name collision')
        names.add(path.name);records.append({'file':path.name,'offset':offset,'size':size,'source':source});pending.append((path,dest))
    if not records:raise ValueError('Empty flash map')
    ranges([(p['offset'],p['offset']+p['size']) for p in records])
    for path,dest in pending:
        if not dest.exists():shutil.copyfile(path,dest)
    return sorted(records,key=lambda p:p['offset'])


def arduino_esp(build,properties,core_root):
    """Use the actual expanded merge recipe and verify bytes against merged image."""
    import shlex,re
    for line in properties.splitlines():
        if not line.startswith('recipe.hooks.') or '=' not in line:continue
        cmd=shlex.split(line.split('=',1)[1]);merge=next((i for i,x in enumerate(cmd) if x in ('merge-bin','merge_bin')),None)
        if merge is None:continue
        args=cmd[merge+1:]
        if '--target-offset' in args or '--target_offset' in args:continue
        output=next((args[i+1] for i,x in enumerate(args[:-1]) if x in ('-o','--output')),None)
        if not output:continue
        merged=Path(output)
        if not merged.is_file() or merged.parent.resolve()!=build.resolve():continue
        image=merged.read_bytes();pairs=[]
        for i,x in enumerate(args[:-1]):
            if re.fullmatch('0x[0-9a-fA-F]+',x) and args[i+1].lower().endswith('.bin'):
                path=Path(args[i+1]);path=path if path.is_absolute() else build/path
                if not any(path.resolve().is_relative_to(r.resolve()) for r in (build,core_root)):raise ValueError('ESP image outside build/core')
                blob=path.read_bytes();offset=int(x,16)
                if not blob or image[offset:offset+len(blob)]!=blob:raise ValueError('Merged image does not match component bytes')
                pairs.append((x,path))
        if pairs:
            result=copy_segments(build,pairs,[build,core_root],'Arduino CLI merge recipe')
            result.append({'file':merged.name,'offset':0,'size':len(image),'source':'Arduino CLI merge recipe (alternative complete image)','alternative':True})
            return result
    raise ValueError('No verifiable expanded ESP merge recipe')


def pio_esp(build,metadata,packages):
    if not isinstance(metadata,dict):raise ValueError('Unexpected PlatformIO metadata')
    extra=metadata.get('extra') or metadata.get('extra_data') or metadata.get('integration_extra_data') or {}
    if 'application_offset' not in extra or not isinstance(extra.get('flash_images'),list):raise ValueError('No complete PlatformIO ESP flash metadata')
    prog=Path(metadata['prog_path']).with_suffix('.bin')
    pairs=[(extra['application_offset'],prog)]
    for item in extra['flash_images']:pairs.append((item['offset'],item['path']))
    return copy_segments(build,pairs,[build,packages],'PlatformIO project metadata')
