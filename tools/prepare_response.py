#!/usr/bin/env python3
"""Create consumable, hash-checked chunks for GitHub Contents REST API.
Each chunk stays below the 1 MB JSON Contents API raw/blob limitation.
"""
import hashlib
import os
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

if len(sys.argv) not in (7, 8):
    sys.exit('Usage: prepare_response.py SKETCH OUTPUT REQUEST_ID BOARD NAME VERSION [BUILD_DIR]')
sketch, out, rid, board, name, version = Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:7]
build_root = Path(sys.argv[7]) if len(sys.argv) == 8 else None
if not re.fullmatch(r'[a-f0-9]{32}', rid):
    sys.exit('Invalid request ID')
profiles = {
    'esp32c3-supermini': 'esp32c3', 'esp32c3-devkit': 'esp32c3',
    'esp32-devkit': 'esp32', 'esp32s3-devkit': 'esp32s3', 'esp32c6-devkit': 'esp32c6'
}
if board not in profiles or not name.strip() or not version.strip():
    sys.exit('Invalid board/name/version')
chip = profiles[board]
# Arduino-ESP32 may emit merged binaries in --build-path or export them into
# SKETCH/build/<FQBN>/. Never assume they live directly in the sketch root.
def select_merged_binary(sketch_path, build_path):
    for root in (build_path, sketch_path):
        if root is None or not root.is_dir():
            continue
        candidates = sorted({x.resolve() for x in root.rglob('*.merged.bin') if x.is_file()})
        if len(candidates) == 1:
            print('Merged firmware located at:', candidates[0])
            return candidates[0]
        if len(candidates) > 1:
            sys.exit('Ambiguous merged firmware files in ' + str(root) + ': ' + ', '.join(str(x) for x in candidates))
    visible = []
    for root in (build_path, sketch_path):
        if root is not None and root.is_dir():
            visible.extend(str(f.relative_to(root)) for f in root.rglob('*.bin') if f.is_file())
    return None


def esp_image_valid(data, chip_name):
    if len(data) < 24 or data[0] != 0xE9:
        return False
    known_chip_ids = {'esp32': 0, 'esp32c3': 5, 'esp32s3': 9, 'esp32c6': 13}
    return (data[12] | (data[13] << 8)) == known_chip_ids[chip_name]


def discover_parts(build_path, sketch_path):
    """Use one *single* build directory; never mix files from different builds."""
    roots = [x for x in (build_path, sketch_path) if x is not None and x.is_dir()]
    observations = []
    for root in roots:
        for directory in [root] + sorted(p for p in root.rglob('*') if p.is_dir()):
            files = [f for f in directory.glob('*.bin') if f.is_file()]
            if not files:
                continue
            boot = [f for f in files if f.name.endswith('.bootloader.bin')]
            parts = [f for f in files if f.name.endswith('.partitions.bin')]
            apps = [f for f in files if f.name.endswith('.ino.bin') and not f.name.endswith('.merged.bin')]
            if boot or parts or apps:
                observations.append(f'{directory}: boot={len(boot)} partitions={len(parts)} app={len(apps)}')
            if len(boot) == len(parts) == len(apps) == 1:
                prefix = boot[0].name[:-len('.bootloader.bin')]
                if parts[0].name != prefix + '.partitions.bin' or apps[0].name != prefix + '.bin':
                    continue
                return boot[0], parts[0], apps[0]
    sys.exit('Cannot assemble merged BIN: complete bootloader/partitions/application trio not found in one build folder. Found: ' + '; '.join(observations[:20]))


def find_boot_app0():
    override = os.environ.get('ESP_BOOT_APP0_PATH')
    if override:
        path = Path(override)
        if path.is_file():
            return path
        sys.exit('ESP_BOOT_APP0_PATH points to missing file: ' + str(path))
    base = Path.home() / '.arduino15/packages/esp32/hardware/esp32/3.1.3/tools/partitions/boot_app0.bin'
    if not base.is_file():
        sys.exit('Arduino-ESP32 boot_app0.bin missing: ' + str(base))
    return base


def assemble_merged(sketch_path, build_path, chip_name):
    """Lay out Arduino-ESP32 3.1.3 flash images using the documented offsets.

    Keep the compiled bootloader image header unchanged (flash mode and size are
    configured by the board during Arduino build). Fill gaps with 0xFF, which is
    the erased flash byte. This does NOT compile or alter the firmware code.
    """
    boot, partitions, app = discover_parts(build_path, sketch_path)
    boot_bytes, part_bytes, app_bytes = (p.read_bytes() for p in (boot, partitions, app))
    if not esp_image_valid(boot_bytes, chip_name):
        sys.exit('Invalid or wrong-chip bootloader image: ' + str(boot))
    if not esp_image_valid(app_bytes, chip_name):
        sys.exit('Invalid or wrong-chip application image: ' + str(app))
    if not part_bytes.startswith(b'\xaa\x50'):
        sys.exit('Invalid ESP32 partition table signature: ' + str(partitions))
    boot_app0 = find_boot_app0()
    boot_app0_bytes = boot_app0.read_bytes()
    if not boot_app0_bytes or len(boot_app0_bytes) > 0x2000:
        sys.exit('Unexpected boot_app0.bin size')
    boot_addr = 0x1000 if chip_name == 'esp32' else 0x0
    segments = [
        (boot_addr, boot_bytes, 'bootloader'),
        (0x8000, part_bytes, 'partitions'),
        (0xE000, boot_app0_bytes, 'boot_app0'),
        (0x10000, app_bytes, 'application'),
    ]
    image = bytearray()
    max_flash = 4 * 1024 * 1024  # Current UI profiles declare a 4 MB minimum flash.
    for offset, payload, label in sorted(segments):
        if offset < len(image):
            sys.exit(f'Flash image overlap at {label}: 0x{offset:x} < 0x{len(image):x}')
        if offset + len(payload) > max_flash:
            sys.exit(f'{label} exceeds supported 4 MB flash layout')
        image.extend(b'\xff' * (offset - len(image)))
        image.extend(payload)
    path = (build_path if build_path is not None else sketch_path) / 'sketch.ino.merged.bin'
    path.write_bytes(image)
    print(f'Assembled verified merged BIN: {path}, {len(image)} bytes')
    print('  Bootloader: 0x%x; partitions: 0x8000; boot_app0: 0xe000; application: 0x10000' % boot_addr)
    return path

merged = select_merged_binary(sketch, build_root)
if merged is None:
    merged = assemble_merged(sketch, build_root, chip)
data = merged.read_bytes()
if len(data) > 12 * 1024 * 1024:
    sys.exit('Firmware exceeds 12 MB for browser retrieval')
boot_offset = 4096 if chip == 'esp32' else 0
chip_ids = {'esp32':0, 'esp32c3':5, 'esp32s3':9, 'esp32c6':13}
if len(data) < boot_offset + 24 or data[boot_offset] != 0xe9:
    sys.exit('Merged image has no ESP bootloader header at expected offset')
image_chip = data[boot_offset+12] | (data[boot_offset+13] << 8)
if image_chip != chip_ids[chip]:
    sys.exit(f'Image chip mismatch (found {image_chip}, expected {chip_ids[chip]})')
if len(name)>120 or len(version)>40:
    sys.exit('Release name or version too long')
out.mkdir(parents=True, exist_ok=True)
(out / 'firmware.bin').write_bytes(data)
size = len(data)
sha = hashlib.sha256(data).hexdigest()
release = {
    'schemaVersion': 1,
    'id': 'gh-' + rid,
    'name': name,
    'version': version,
    'createdAt': datetime.now(timezone.utc).isoformat(),
    'chip': chip,
    'boardId': board,
    'minFlashMB': 4,
    'layout': 'merged',
    'flashMode': 'dio',
    'flashFreq': '40m',
    'notes': 'Скомпилировано GitHub Actions · Arduino-ESP32 3.1.3',
    'images': [{'file': 'firmware.bin', 'offset': 0, 'size': size, 'sha256': sha}]
}
chunks = []
chunk_dir = out / 'chunks'
chunk_dir.mkdir(exist_ok=True)
CHUNK_BYTES = 512 * 1024
for i in range(0, size, CHUNK_BYTES):
    content = data[i:i+CHUNK_BYTES]
    filename = 'part-%03d.bin' % (i//CHUNK_BYTES)
    (chunk_dir / filename).write_bytes(content)
    chunks.append({'file': filename, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
response = {'schema':1, 'requestId':rid, 'release':release, 'sha256':sha, 'size':size, 'chunks':chunks}
(out / 'result.json').write_text(json.dumps(response, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
(out / 'README.txt').write_text(f'{name} v{version}\nBoard: {board}\nChip: {chip}\nFlash address: 0x0\nSHA256: {sha}\n', encoding='utf-8')
print('Compiled BIN:', size, 'bytes; chunks:', len(chunks), 'sha256:', sha)
