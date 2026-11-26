"""Guard public development from accidental request, SDK and binary publication.
Paths/CI policy only; not a substitute for human license and content review.
"""
import subprocess
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
def validate(paths):
    for name in paths:
        p=PurePosixPath(name);parts={s.lower() for s in p.parts}
        if parts&{'requests','build-results','recovery-results','drivers','middlewares','stm32wb_copro_wireless_binaries','stm32_wpan','vendor-sdk'} or p.suffix.lower() in {'.bin','.hex','.elf','.uf2','.zip','.a','.lib','.dll','.exe','.so','.o','.7z','.tar','.gz'}:
            raise ValueError('Public repository must not contain user requests or vendor/compiled payloads: '+name)
        if name.startswith('.github/workflows/') and name!='.github/workflows/stm32-catalog.yml':
            if 'actions/upload-artifact@' in (ROOT/name).read_text():raise ValueError('Public firmware artifact upload requires review: '+name)
    return len(paths)
if __name__=='__main__':
    raw=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT)
    paths=[s.decode('utf-8') for s in raw.split(b'\0') if s]
    print('PUBLIC_TREE_POLICY_PASS',validate(paths))
