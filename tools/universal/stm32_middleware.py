"""Select middleware from the same pinned ST Cube package. Board glue is never invented."""
import re
from pathlib import Path

def detect(paths):
    includes=set()
    for p in paths:
        if p.suffix.lower() not in ('.c','.cpp','.cc','.cxx','.h','.hpp','.hh','.hxx'):continue
        text=re.sub(r'/\*.*?\*/|//[^\n]*','',p.read_text(errors='replace'),flags=re.S)
        includes.update(Path(x).name.lower() for x in re.findall(r'(?m)^\s*#\s*include\s*[<"]([^>"\n]+)[>"]',text))
    names={p.name.lower() for p in paths}
    modes=set()
    if (includes|names)&{'freertos.h','freertosconfig.h','cmsis_os.h','cmsis_os2.h'}:modes.add('freertos')
    if (includes|names)&{'ff.h','ffconf.h','diskio.h','ff_gen_drv.h'}:modes.add('fatfs')
    if any(x.startswith('usbd_') and x.endswith('.h') for x in includes|names):modes.add('usb-device')
    return modes

def plan(paths,sdk,recipe,obj,modes):
    sources=[];dirs=[];flags=[];meta={};names={p.name.lower() for p in paths}; mw=sdk/'Middlewares'
    def need(name):
        if name.lower() not in names:raise ValueError('Middleware requires project-specific '+name+'; supply board configuration/glue')
    def add_src(p):
        if not p.is_file():raise ValueError('Middleware source missing in pinned Cube package: '+p.name)
        sources.append(p)
    def select_dir(candidates,label):
        for d in candidates:
            if d.is_dir():return d
        raise ValueError(label+' unavailable in pinned Cube package for selected STM32; use a complete project')
    def unique_check():
        existing=names&{p.name.lower() for p in sources}
        if existing:raise ValueError('Bundled middleware implementation conflicts with SDK: '+', '.join(sorted(existing)))
    if 'freertos' in modes:
        need('FreeRTOSConfig.h')
        root=select_dir([mw/'Third_Party/FreeRTOS/Source',mw/'Third_Party/FreeRTOS'],'FreeRTOS')
        port={'cortex-m0':'ARM_CM0','cortex-m0+':'ARM_CM0','cortex-m0plus':'ARM_CM0','cortex-m3':'ARM_CM3','cortex-m4':'ARM_CM4F'}.get(recipe['cpu'])
        if not port:raise ValueError('No FreeRTOS port configured for this CPU')
        portable=select_dir([root/'portable',root/'Portable'],'FreeRTOS portable');pd=portable/'GCC'/port
        add_src(pd/'port.c');dirs += [root/'include',pd]
        for name in ('tasks.c','queue.c','list.c','timers.c','event_groups.c','stream_buffer.c','croutine.c'):
            f=root/name
            if f.is_file():add_src(f)
            elif name in ('tasks.c','queue.c','list.c'):add_src(f)
        heap=obj.get('freertosHeap',4)
        if type(heap) is not int or heap not in (0,1,2,3,4,5):raise ValueError('freertosHeap must be 0 (custom/static) or 1..5')
        if heap:add_src(portable/'MemMang'/f'heap_{heap}.c')
        # ST wrappers are optional and only compiled when requested by headers.
        text='\n'.join(p.read_text(errors='replace') for p in paths if p.suffix.lower() in ('.c','.cpp','.h','.hpp'))
        for header,folder,source in [('cmsis_os.h','CMSIS_RTOS','cmsis_os.c'),('cmsis_os2.h','CMSIS_RTOS_V2','cmsis_os2.c')]:
            if re.search(r'#\s*include\s*[<"]'+re.escape(header)+r'[>"]',text):
                d=root/folder;add_src(d/source);dirs.append(d)
                if (d/'Include').is_dir():dirs.append(d/'Include')
        meta['freertos']={'port':port,'heap':heap,'note':'User supplies FreeRTOSConfig.h and interrupt/tick integration; HAL default tick disabled.'}
    if 'fatfs' in modes:
        need('ffconf.h')
        root=select_dir([mw/'Third_Party/FatFs/src',mw/'Third_Party/FatFs/source'],'FatFs');dirs.append(root);add_src(root/'ff.c')
        # Use ST's disk dispatch only when the user requests that API.
        text='\n'.join(p.read_text(errors='replace') for p in paths if p.suffix.lower() in ('.c','.cpp','.h','.hpp'))
        if re.search(r'(?i)\bff_gen_drv\.h\b',text):
            for name in ('ff_gen_drv.c','diskio.c'):
                if name not in names:add_src(root/name)
        # Otherwise user supplies direct disk I/O callbacks.
        for name in ('ffunicode.c','ffsystem.c'):
            if (root/name).is_file() and name not in names:add_src(root/name)
        # Older Cube packages include optional Unicode functions in option/.
        if not (root/'ffunicode.c').exists():
            for name in ('unicode.c','syscall.c'):
                if (root/'option'/name).is_file() and name not in names:add_src(root/'option'/name)
        meta['fatfs']={'note':'User supplies ffconf.h and disk I/O implementation; no SD/SPI assumptions.'}
    if 'usb-device' in modes:
        need('usbd_conf.h')
        root=select_dir([mw/'ST/STM32_USB_Device_Library'],'ST USB Device');dirs.append(root/'Core/Inc')
        for name in ('usbd_core.c','usbd_ctlreq.c','usbd_ioreq.c'):add_src(root/'Core/Src'/name)
        text='\n'.join(p.read_text(errors='replace') for p in paths if p.suffix.lower() in ('.c','.cpp','.h','.hpp'))
        supported={'cdc':'CDC','hid':'HID','customhid':'CustomHID','msc':'MSC','dfu':'DFU','audio':'AUDIO'}
        classes={k for k in supported if re.search(r'(?i)\busbd_'+k+r'\.h\b',text)}
        if len(classes)>1:raise ValueError('Multiple USB classes: supply complete composite USB project')
        for k in classes:
            d=root/'Class'/supported[k];dirs.append(d/'Inc');add_src(d/'Src'/('usbd_'+k+'.c'))
            if k=='msc':
                for name in ('usbd_msc_bot.c','usbd_msc_scsi.c','usbd_msc_data.c'):add_src(d/'Src'/name)
        meta['usb-device']={'classes':sorted(classes),'note':'User supplies descriptors, usbd_conf.h, low-level USB HAL and class callbacks.'}
    unique_check()
    return sources,dirs,flags,meta
