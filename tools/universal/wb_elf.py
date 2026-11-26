"""Bounded ELF32 ARM allocation audit. Reviewed WB3x/5x SRAM layout; see AN5451 table 7.
RM0434 and AN5289: SRAM2a/b are shared and have live CPU2 security boundaries.
No code is executed; the result is a static allocation report, not a radio ABI proof.
"""
import struct
from pathlib import Path
BASE=0x08000000
RAM=0x20000000
A=0x20030000
B=0x20038000
END=0x20040000

def supported(recipe):
    return (recipe.get('define'),recipe.get('ramKiB')) in {('STM32WB55xx',64),('STM32WB55xx',192),('STM32WB50xx',64),('STM32WB35xx',32),('STM32WB30xx',32)}

def audit(path,recipe,limit,origin=BASE):
    if not supported(recipe):return None
    if origin not in (BASE,0x08007000):raise ValueError('WB unknown application origin')
    ram_start=RAM+4 if origin!=BASE else RAM
    ram_end=RAM+recipe['ramKiB']*1024
    if origin!=BASE and recipe['ramKiB']!=192:raise ValueError('WB OTA geometry not reviewed')
    data=Path(path).read_bytes()
    if not 52<=len(data)<=32*1024*1024 or data[:7]!=b'\x7fELF\x01\x01\x01':
        raise ValueError('WB ELF must be little-endian ELF32')
    typ,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,strings=struct.unpack_from('<HHIIIIIHHHHHH',data,16)
    if typ!=2 or machine!=40 or version!=1 or ehsize!=52 or phsize!=32 or shsize!=40 or not 1<=phnum<=128 or not 1<=shnum<=512 or not 0<strings<shnum or phoff<52 or shoff<52 or phoff+phsize*phnum>len(data) or shoff+shsize*shnum>len(data):
        raise ValueError('WB invalid executable ELF tables')
    ceiling=BASE+limit*1024
    def region(start,end):
        for label,lo,hi in [('flash',origin,ceiling),('sram1',ram_start,ram_end),('sram2a',A,B),('sram2b',B,END)]:
            if lo<=start<end<=hi:return label
        raise ValueError('WB ELF allocation outside reviewed CPU1 memory')
    loads=[]
    for i in range(phnum):
        kind,offset,va,pa,fs,ms,fl,align=struct.unpack_from('<8I',data,phoff+i*32)
        if kind!=1:continue
        if fs>ms or offset+fs>len(data):raise ValueError('WB invalid ELF load segment')
        if not ms:continue
        area=region(va,va+ms)
        if fs and not origin<=pa<pa+fs<=ceiling:raise ValueError('WB ELF load data outside application Flash')
        if area.startswith('sram2') and (fs or fl&1):raise ValueError('WB shared SRAM requires non-executable NOLOAD')
        loads.append((offset,va,pa,fs,ms))
    sections=[struct.unpack_from('<10I',data,shoff+i*40) for i in range(shnum)]
    st=sections[strings];off,size=st[4:6]
    if st[1]!=3 or off+size>len(data):raise ValueError('WB invalid ELF section names')
    names=data[off:off+size]
    result=[]
    for no,kind,flags,addr,offset,size,*_ in sections:
        if not flags&2 or not size:continue
        area=region(addr,addr+size)
        if no>=len(names) or b'\0' not in names[no:]:raise ValueError('WB invalid ELF section name')
        name=names[no:names.index(b'\0',no)].decode('ascii')
        if not name or len(name)>128:raise ValueError('WB invalid ELF section name')
        if kind==8:
            if area=='flash':raise ValueError('WB NOLOAD section in Flash')
            if not any(va<=addr<addr+size<=va+ms for _,va,_,_,ms in loads):raise ValueError('WB unmapped NOLOAD section')
            load=None
        else:
            if area.startswith('sram2') or offset+size>len(data):raise ValueError('WB initialized shared SRAM unsupported')
            matches=[pa+addr-va for po,va,pa,fs,ms in loads if va<=addr<addr+size<=va+fs and offset==po+addr-va]
            if len(matches)!=1 or not origin<=matches[0]<matches[0]+size<=ceiling:raise ValueError('WB section load address outside application Flash')
            load=matches[0]
        if area.startswith('sram2') and flags&4:raise ValueError('WB executable shared SRAM unsupported')
        result.append(dict(name=name,start=addr,endExclusive=addr+size,area=area,loadStart=load))
    result.sort(key=lambda x:x['start'])
    if not result or any(a['endExclusive']>b['start'] for a,b in zip(result,result[1:])):raise ValueError('WB overlapping allocated sections')
    if not any(x['area']=='flash' and x['start']<=entry&~1<x['endExclusive'] for x in result):raise ValueError('WB ELF entry outside application')
    return {'schema':1,'layout':('wb55-sram192-rm0434' if recipe['ramKiB']==192 else 'wb3x5x-sram%d-an5451'%recipe['ramKiB']),'sections':result}
