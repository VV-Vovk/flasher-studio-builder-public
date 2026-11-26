"""Explicit, self-contained WB CPU1 GNU project; never fetch wireless components."""
import re, struct
from pathlib import Path
import flash_layout
BASE=0x08000000
OTA_BASE=0x08007000
OTA_LAYOUT='st-ble-app-0x7000'
OTA_MAGIC=0x94448A29

def match_target(declared,selected):
    # CubeIDE commonly uses a temperature wildcard in the part code.
    declared=declared.upper().removesuffix('TR')
    selected=selected.upper().removesuffix('TR')
    return bool(re.fullmatch(r'STM32WB[A-Z0-9]+',selected) and 'X' not in selected and re.fullmatch(r'STM32WB[A-Z0-9]+',declared) and re.fullmatch(re.escape(declared).replace('X','[0-9]'),selected))

def validate_plan(plan,target,recipe):
    if not recipe.get('wbApplicationOnly') or not match_target(plan['target'],target):
        raise ValueError('WB project MCU differs from exact selected target')
    if '-mcpu=cortex-m4' not in plan['arch']:
        raise ValueError('WB project must target CPU1 Cortex-M4')
    if recipe['define'] not in plan['tools']['compiler.c']['defines']:
        raise ValueError('WB project must define the selected CPU1 device macro')
    if any(re.search(r'(?:^|[_-])cm0(?:plus|p)?(?:[_.-]|$)',f.name,re.I) for f in plan['sources']):
        raise ValueError('WB CPU2 startup/source is not supported')

def budget(config,recipe):
    if 'wbAppFlashKiB' not in config:
        raise ValueError('WB full project requires flasher-native.json with wbAppFlashKiB from live SFSA')
    n=config['wbAppFlashKiB'];physical=recipe['physicalFlashKiB'];page=2 if physical==320 else 4
    if type(n) is not int or n<page or n%page or n>=physical:
        raise ValueError('WB application budget must be page aligned and below physical Flash')
    origin(config,recipe,n)
    return n

def origin(config,recipe,limit):
    layout=config.get('wbOtaLayout')
    if layout is None:return BASE
    if layout!=OTA_LAYOUT or recipe.get('define')!='STM32WB55xx' or recipe.get('ramKiB')!=192 or limit<=28:
        raise ValueError('WB OTA requires reviewed WB55 192 KiB SRAM1 and Flash budget above 28 KiB')
    return OTA_BASE

def verify_output(out,recipe,limit,origin=BASE):
    ranges=flash_layout.ihex(out/'firmware.hex')
    ceiling=BASE+limit*1024
    if origin not in (BASE,OTA_BASE) or ranges[0]['start']!=origin or any(not origin<=x['start']<x['endExclusive']<=ceiling for x in ranges):
        raise ValueError('WB HEX must contain only CPU1 application Flash within declared budget')
    # Read actual vector bytes from address-bearing HEX, not an unaddressed BIN.
    vectors={}
    image=bytearray(b'\xff')*(ranges[-1]['endExclusive']-origin) if origin==OTA_BASE else None
    base=0
    for line in (out/'firmware.hex').read_text('ascii').splitlines():
        if not line.strip():continue
        row=bytes.fromhex(line[1:]);addr=int.from_bytes(row[1:3],'big');typ=row[3];data=row[4:-1]
        if typ in (2,4):base=int.from_bytes(data,'big')<<(4 if typ==2 else 16)
        elif typ==0:
            for i,b in enumerate(data):
                a=base+addr+i
                if origin<=a<origin+8:vectors[a]=b
                if image is not None:image[a-origin]=b
    if len(vectors)!=8:raise ValueError('WB missing CPU1 vector table')
    sp,pc=struct.unpack('<II',bytes(vectors[origin+i] for i in range(8)))
    ram=recipe.get('ramOrigin',0x20000000)
    if sp%8 or not ram<sp<=ram+recipe['ramKiB']*1024 or not pc&1 or not any(x['start']<=(pc&~1)<x['endExclusive'] for x in ranges):
        raise ValueError('WB invalid CPU1 stack or reset vector')
    if image is not None:
        covered=lambda a,n:any(x['start']<=a and a+n<=x['endExclusive'] for x in ranges)
        if len(image)<0x148 or sp<=ram+4 or not covered(pc&~1,2) or not covered(origin+0x140,4):raise ValueError('WB OTA vector or tag pointer invalid')
        tag=struct.unpack_from('<I',image,0x140)[0]
        if tag%4 or tag<origin+0x144 or tag+4!=origin+len(image) or not covered(tag,4) or struct.unpack_from('<I',image,tag-origin)[0]!=OTA_MAGIC:raise ValueError('WB OTA end marker invalid')
        if origin+((len(image)+4095)//4096)*4096>ceiling:raise ValueError('WB OTA exceeds application budget')
        # Canonical erased-byte padding derived from verified addressed HEX.
        (out/'firmware.bin').write_bytes(image)
    return ranges
