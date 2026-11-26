#!/usr/bin/env python3
"""Safely materialize one arbitrary Arduino sketch uploaded by the phone.
Supports .ino or a ZIP containing one .ino plus accompanying source files.
"""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zipfile

BOARD_IDS = {'esp32c3-supermini', 'esp32c3-devkit', 'esp32-devkit', 'esp32s3-devkit', 'esp32c6-devkit'}
SUFFIXES = {'.ino', '.c', '.cpp', '.h', '.hpp', '.s', '.S', '.txt'}
MAX_UNPACKED = 5 * 1024 * 1024
MAX_FILES = 120


def check_env():
    rid = os.getenv('REQUEST_ID', '')
    fmt = os.getenv('INPUT_TYPE', '')
    board = os.getenv('BOARD_PROFILE', '')
    if not re.fullmatch(r'[a-f0-9]{32}', rid) or fmt not in {'zip', 'ino'} or board not in BOARD_IDS:
        sys.exit('Invalid request_id, input_type or board_profile')
    return rid, fmt


def extract_zip(data_path: Path, dest: Path):
    if data_path.stat().st_size > 950_000:
        sys.exit('Source ZIP too large for this starter version (950 KB)')
    with zipfile.ZipFile(data_path) as zf:
        infos = [x for x in zf.infolist() if not x.is_dir()]
        if not infos or len(infos) > MAX_FILES or sum(x.file_size for x in infos) > MAX_UNPACKED:
            sys.exit('Archive exceeds file-count or uncompressed-size limit')
        parsed = []
        for info in infos:
            name = info.filename
            p = PurePosixPath(name)
            if ('\\' in name or p.is_absolute() or '..' in p.parts or '\x00' in name or
                    not p.parts or any(piece.startswith('.') for piece in p.parts) or
                    (info.external_attr >> 16) & 0o170000 == 0o120000):
                sys.exit(f'Unsafe ZIP path: {name}')
            if p.suffix not in SUFFIXES:
                # Ignore IDE clutter and binary data. Do not execute content from the archive.
                continue
            parsed.append((info, p))
        ino = [(info,p) for info,p in parsed if p.suffix.lower() == '.ino']
        if len(ino) != 1:
            sys.exit('ZIP must contain exactly one primary .ino sketch')
        main_ino = ino[0][1]
        # Arduino CLI requires the primary sketch filename to match its folder.
        prefix = main_ino.parts[:-1]
        # In a ZIP with MySketch/MySketch.ino, copy its tree to sketch/.
        for info,p in parsed:
            if p.parts[:len(prefix)] != prefix:
                continue
            rel = p.parts[len(prefix):]
            if not rel or len(rel) > 12:
                continue
            if p == main_ino:
                out = dest / 'sketch.ino'
            else:
                out = dest.joinpath(*rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(info))
        if not (dest / 'sketch.ino').is_file():
            sys.exit('Could not find primary sketch in ZIP')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rid, fmt = check_env()
    source = args.source_root / rid / ('source.' + fmt)
    if not source.is_file() or source.stat().st_size == 0:
        sys.exit(f'Input file missing: requests/{rid}/source.{fmt}')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if fmt == 'ino':
        if source.stat().st_size > 950_000:
            sys.exit('INO exceeds 950 KB')
        (output / 'sketch.ino').write_bytes(source.read_bytes())
    else:
        extract_zip(source, output)
    declared = os.getenv('REQUESTED_LIBRARIES', '').replace('\r', '')
    previous = (output / 'libraries.txt').read_text(encoding='utf-8') if (output / 'libraries.txt').is_file() else ''
    (output / 'libraries.txt').write_text(previous + '\n' + declared + '\n', encoding='utf-8')
    print('Source sketch unpacked. Board:', os.getenv('BOARD_PROFILE'), 'Files:', sum(1 for p in output.rglob('*') if p.is_file()))

if __name__ == '__main__':
    main()
