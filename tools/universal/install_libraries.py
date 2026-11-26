#!/usr/bin/env python3
"""Install optional named libraries, resolving mismatched package/header names.

Source code also goes through auto_libraries.py even when this list is empty.
This script only accepts registry names / headers and never arbitrary URLs.
"""
import re
import subprocess
import sys
from pathlib import Path

from auto_libraries import registry_matches

MAX_EXPLICIT = 15
LIBRARY_LINE = re.compile(r'[A-Za-z0-9 _+.-]+(?:@[A-Za-z0-9_.-]+)?')
HEADER = re.compile(r'[A-Za-z0-9_+.-]+\.(?:h|hpp)', re.I)


def candidate_header(name):
    if HEADER.fullmatch(name):
        return name
    # A user may type "BleGamepad" even though the package name is
    # "ESP32-BLE-Gamepad". Guess ONLY a header name, then use the registry's
    # exact `provides=<header>` query to find the actual package.
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9_+.-]{1,69}', name):
        return name + '.h'
    return None


def install_declared(lib, runner=subprocess.run, matcher=registry_matches):
    print(f'[libraries] Requested: {lib}', flush=True)
    if lib.lower().endswith('@latest'):
        lib = lib[:-7]
    result = runner(['arduino-cli', 'lib', 'install', '--no-overwrite', lib],
                    capture_output=True, text=True, timeout=180)
    if result.returncode == 0:
        print(f'[libraries] Installed: {lib}', flush=True)
        return lib
    name, sep, version = lib.rpartition('@')
    if not sep:
        name, version = lib, ''
    # In Arduino CLI 'latest' is normally expressed by omitting @VERSION.
    if version.lower() == 'latest':
        version = ''
    header = candidate_header(name)
    matches = matcher(header, runner) if header else []
    if len(matches) == 1:
        resolved = matches[0] + (('@' + version) if version else '')
        print(f'[libraries] Header {header} belongs to registry package {matches[0]}', flush=True)
        final = runner(['arduino-cli', 'lib', 'install', '--no-overwrite', resolved],
                       capture_output=True, text=True, timeout=180)
        if final.returncode == 0:
            print(f'[libraries] Installed: {resolved}', flush=True)
            return resolved
        raise RuntimeError(f'Package {resolved} was found but installation failed: '
                           + (final.stderr or final.stdout or '')[-800:])
    if len(matches) > 1:
        raise RuntimeError(f'Ambiguous library for {header}: ' + ', '.join(matches[:10]))
    raise RuntimeError(f'Library {lib} was not found. Try the exact Arduino Library Manager name, '
                       f'or leave the field empty for header-based auto detection. '
                       f'CLI: ' + (result.stderr or result.stdout or '')[-400:])


def main():
    if len(sys.argv) != 2:
        sys.exit('Usage: install_libraries.py <libraries.txt>')
    path = Path(sys.argv[1])
    if not path.exists():
        return
    seen = set()
    libraries = []
    for line in path.read_text(encoding='utf-8').splitlines():
        lib = line.strip()
        if not lib or lib.startswith('#'):
            continue
        if len(lib) > 100 or not LIBRARY_LINE.fullmatch(lib):
            sys.exit('Invalid libraries.txt entry: ' + lib[:70])
        if lib not in seen:
            libraries.append(lib)
            seen.add(lib)
    if len(libraries) > MAX_EXPLICIT:
        sys.exit('Too many libraries (maximum 15)')
    try:
        for lib in libraries:
            install_declared(lib)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        sys.exit('[ESP Flasher] ' + str(error))
    print('[libraries] Explicit packages installed:', len(libraries))


if __name__ == '__main__':
    main()
