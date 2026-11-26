#!/usr/bin/env python3
"""Compile an Arduino sketch and resolve *unambiguous* registry libraries on demand.

Does not fetch arbitrary, user-controlled git URLs or execute project-supplied commands.
A small allowlist can install libraries from pinned upstream GitHub releases if
the Arduino library registry index does not resolve their headers.
The host workflow installs ESP32 Arduino core and the library index first.
"""
import argparse
import os
import json
import re
import subprocess
import sys
from pathlib import Path

BOARD_FQBN = {
    'esp32c3-supermini': 'esp32:esp32:esp32c3',
    'esp32c3-devkit': 'esp32:esp32:esp32c3',
    'esp32-devkit': 'esp32:esp32:esp32',
    'esp32s3-devkit': 'esp32:esp32:esp32s3',
    'esp32c6-devkit': 'esp32:esp32:esp32c6',
}
MISSING_RE = re.compile(r'fatal error:\s*[<"\']?([\w.\-/]+\.(?:h|hpp|hh|hxx))[>"\']?:\s*No such file or directory', re.IGNORECASE)
# Defensive limits: capped installation attempts, no arbitrary install from URLs.
MAX_LIBS = 12
MAX_COMPILE_ATTEMPTS = 13

# Curated, pinned fallback recipes. These sources are NOT derived from uploaded
# project files. Only exact header names can trigger these installations.
# For libraries absent from Library Manager, pin a public upstream tag rather
# than silently installing a moving main branch.
TRUSTED_GIT_FALLBACK = {
    # Reviewed public fork of ESP32-BLE-Gamepad with composite mouse/keyboard HID.
    # Uses the tested NimBLE-Arduino series from the library README.
    # Upstream main is used for this prototype; pin to a commit after device QA.
    'BleController.h': {
        'name': 'ESP32-BLE-Controller@main',
        'url': 'https://github.com/black-ghost-off/ESP32-BLE-Controller.git#main',
        'dependencies': ('NimBLE-Arduino@2.2.1',),
    },

    'HijelHID_BLEMouse.h': {
        'name': 'HijelHID_BLEMouse@0.1.0',
        'url': 'https://github.com/HijelHub/HijelHID_BLEMouse.git#0.1.0',
        'dependencies': ('NimBLE-Arduino@2.3.9',),
    },
}


def install_trusted_git(header, attempted, runner=subprocess.run):
    recipe = TRUSTED_GIT_FALLBACK[header]
    name = recipe['name']
    if name in attempted:
        raise RuntimeError(f'Библиотека {name} установлена, но заголовок {header} всё ещё недоступен')
    if len(attempted) >= MAX_LIBS:
        raise RuntimeError('Превышен предел 12 автоматически устанавливаемых библиотек')
    print(f'[libraries] {header} не найден в индексе: доверенный источник {name}', flush=True)
    for dependency in recipe['dependencies']:
        outcome = runner(['arduino-cli', 'lib', 'install', '--no-overwrite', dependency], capture_output=True, text=True, timeout=240)
        if outcome.returncode != 0:
            print((outcome.stderr or outcome.stdout or '')[-1500:], flush=True)
            raise RuntimeError(f'Не удалось установить зависимость {dependency} для {name}')
    # Unsafe installs are enabled in this ephemeral CI job only. Never use this
    # branch for user-provided URLs or library names.
    outcome = runner(['arduino-cli', 'config', 'set', 'library.enable_unsafe_install', 'true'], capture_output=True, text=True, timeout=30)
    if outcome.returncode != 0:
        raise RuntimeError('Невозможно разрешить установку доверенной GitHub-библиотеки в Arduino CLI')
    outcome = runner(['arduino-cli', 'lib', 'install', '--git-url', recipe['url']], capture_output=True, text=True, timeout=240)
    if outcome.returncode != 0:
        print((outcome.stderr or outcome.stdout or '')[-1500:], flush=True)
        raise RuntimeError(f'Не удалось установить {name} из доверенного GitHub-репозитория')
    attempted.add(name)
    print(f'[libraries] Установлено {name}, зависимости: {", ".join(recipe["dependencies"])}', flush=True)


def missing_headers(log):
    return list(dict.fromkeys(match.group(1) for match in MISSING_RE.finditer(log)))


def normalized_name(name):
    """Treat `BleGamepad`, `BLE-Gamepad`, and `BLE Gamepad` alike."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


def header_tokens(header):
    """Split snake_case and camelCase into search terms, keeping acronyms."""
    stem = Path(header).stem
    tokens = re.findall(r'[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+|[A-Z]+',
                        stem.replace('-', ' ').replace('_', ' '))
    return [x.lower() for x in tokens if len(x) >= 3]


def library_includes(lib):
    latest = lib.get('latest') or {}
    return latest.get('provides_includes') or lib.get('provides_includes') or []


def library_arch_compatible(lib):
    latest = lib.get('latest') or {}
    arches = latest.get('architectures') or []
    return not arches or '*' in arches or os.environ.get('FS_ARCH', 'esp32').lower() in [a.lower() for a in arches]


def name_score(header, lib):
    """Conservative fallback for registry entries with incomplete `provides`.

    A header-to-package name is accepted automatically only with a very strong,
    unambiguous normalized match. We do not use unrestricted fuzzy guesses.
    """
    name = lib.get('name', '')
    if not name or not library_arch_compatible(lib):
        return 0
    filename = Path(header).name
    provided = library_includes(lib)
    if filename in provided or header in provided:
        return 120
    # If the index explicitly lists headers and this one is absent, never
    # infer a different provider from a similar name.
    if provided:
        return 0
    stem = normalized_name(Path(header).stem)
    libname = normalized_name(name)
    if len(stem) < 5:
        return 0
    if libname == stem:
        return 110
    if libname == stem + 'library':
        return 105
    for prefix in ('esp32', 'esp8266', 'arduino'):
        if libname == prefix + stem or libname == prefix + stem + 'library':
            return 102
    if (libname.endswith(stem) and len(libname)-len(stem) <= 14) or \
       (libname.startswith(stem) and libname.endswith('library')):
        return 92
    return 0


def find_name_candidates(data, header):
    """Rank exact filename providers and strong name equivalents only."""
    candidates = {}
    for lib in data.get('libraries', []) or []:
        if not isinstance(lib, dict):
            continue
        name = lib.get('name')
        score = name_score(header, lib)
        if score >= 90 and isinstance(name, str):
            candidates[name] = max(score, candidates.get(name, 0))
    return candidates


def name_search_terms(header):
    stem = Path(header).stem
    tokens = header_tokens(header)
    # The complete header stem may not occur literally in the registry name,
    # e.g. BleGamepad.h -> ESP32-BLE-Gamepad. Also search its long component.
    terms = [stem]
    if tokens:
        terms.extend(sorted((t for t in tokens if len(t) >= 5),
                            key=len, reverse=True)[:2])
    return list(dict.fromkeys(terms))[:3]


def cli_search(term, runner=subprocess.run):
    cmd = ['arduino-cli', 'lib', 'search', '--json',
           '--omit-releases-details', term]
    result = runner(cmd, capture_output=True, text=True, timeout=50)
    if result.returncode != 0:
        print(f'[libraries] Search failed for {term}: '
              f'{(result.stderr or result.stdout or "")[-240:]}', flush=True)
        return {'libraries': []}
    try:
        data = json.loads(result.stdout)
        return data if isinstance(data, dict) else {'libraries': []}
    except (ValueError, TypeError):
        print(f'[libraries] Search returned invalid JSON for {term}', flush=True)
        return {'libraries': []}


def registry_matches(header, runner=subprocess.run):
    """Find an unambiguous library using exact providers, then strong name matches.

    Some valid Library Manager packages have incomplete include metadata,
    making `provides=Header.h` return no results. The name fallback catches
    headers such as BleGamepad.h -> ESP32-BLE-Gamepad without hardcoded rules.
    """
    filename = Path(header).name
    scored = {}
    for query in (f'provides={filename}', f'provides:{filename}'):
        data = cli_search(query, runner)
        for lib in data.get('libraries', []) or []:
            if not isinstance(lib, dict) or not library_arch_compatible(lib):
                continue
            name = lib.get('name')
            if name and (filename in library_includes(lib) or
                         header in library_includes(lib)):
                scored[name] = max(scored.get(name, 0), 120)
            elif name and not library_includes(lib):
                # The CLI's provides qualifier itself may locate a provider
                # even if compact JSON omits include details. Never accept
                # an entry that explicitly lists OTHER headers.
                scored[name] = max(scored.get(name, 0), 115)
        if scored:
            break
    if not scored:
        for term in name_search_terms(header):
            data = cli_search(term, runner)
            for name, score in find_name_candidates(data, header).items():
                scored[name] = max(score, scored.get(name, 0))
    if not scored:
        print(f'[libraries] No confident Library Manager match for {header}',
              flush=True)
        return []
    best = max(scored.values())
    winners = sorted(k for k, v in scored.items() if v == best)
    print(f'[libraries] {header} candidate(s): '
          + ', '.join(f'{k}={scored[k]}' for k in sorted(scored)), flush=True)
    return winners

def resolve_missing_header(header, attempted, runner=subprocess.run, git_context=None):
    if not re.fullmatch(r'[\w.\-/]+\.(?:h|hpp|hh|hxx)', header) or '..' in header or header.startswith('/'):
        raise RuntimeError('Недопустимое имя заголовочного файла: '+header)
    candidates = registry_matches(header, runner)
    if not candidates:
        if os.environ.get('FS_ARCH', 'esp32') == 'esp32' and header in TRUSTED_GIT_FALLBACK:
            if git_context is None:
                return install_trusted_git(header, attempted, runner)
            from git_libraries import install_recipe
            local, records = git_context
            recipe=TRUSTED_GIT_FALLBACK[header]; url,ref=recipe['url'].split('#',1)
            for dependency in recipe['dependencies']:
                result=runner(['arduino-cli','lib','install','--no-overwrite',dependency],timeout=240)
                if result.returncode:raise RuntimeError('Git library dependency failed: '+dependency)
            install_recipe(url,ref,local/url.rsplit('/',1)[1][:-4],records,runner)
            attempted.add(recipe['name']);return
        raise RuntimeError(f'Библиотека для {header} не найдена в Arduino Library Manager или списке проверенных GitHub-библиотек. Для неизвестных библиотек добавь исходники в ZIP.')
    if len(candidates) > 1:
        raise RuntimeError(f'Неоднозначная библиотека для {header}: {", ".join(candidates[:8])}. Укажи нужное название в расширенных настройках проекта.')
    lib = candidates[0]
    if lib in attempted:
        raise RuntimeError(f'После установки «{lib}» заголовок {header} по-прежнему недоступен. Проверь совместимость библиотеки с выбранным ядром и версию.')
    if len(attempted) >= MAX_LIBS:
        raise RuntimeError('Слишком много зависимостей: остановка после 12 автоматических библиотек')
    print(f'[libraries] Найдено точное совпадение: {header} → {lib}', flush=True)
    # Arduino CLI installs transitive dependencies using library.properties.
    result = runner(['arduino-cli', 'lib', 'install', '--no-overwrite', lib], timeout=180)
    if result.returncode != 0:
        raise RuntimeError('Не удалось установить Arduino-библиотеку '+lib)
    attempted.add(lib)


def compile_project(sketch, build, profile, runner=subprocess.run, *, fqbn=None, local_libs=None, locked=False, git_context=None):
    if fqbn is None and profile not in BOARD_FQBN:
        raise RuntimeError('Неизвестный профиль платы')
    cmd = ['arduino-cli', 'compile', '--fqbn', fqbn or BOARD_FQBN[profile], '--build-path', str(build)]
    if local_libs:
        cmd.extend(['--libraries', str(local_libs)])
    cmd.append(str(sketch))
    installed = set()
    encountered = set()
    for attempt in range(MAX_COMPILE_ATTEMPTS):
        print(f'[compile] Попытка {attempt+1}/{MAX_COMPILE_ATTEMPTS}', flush=True)
        result = runner(cmd, capture_output=True, text=True, timeout=1200)
        output = (result.stdout or '') + '\n' + (result.stderr or '')
        # Keep logs useful but bounded to avoid enormous GitHub log entries.
        print('\n'.join(output.splitlines()[-110:]), flush=True)
        if result.returncode == 0:
            print('[compile] Сборка успешна. Автоматически установлено библиотек:', ', '.join(sorted(installed)) or '0', flush=True)
            return installed
        missing = missing_headers(output)
        if not missing:
            raise RuntimeError('Сборка завершилась с ошибкой не связанной с отсутствующей библиотекой. См. журнал выше.')
        if locked:
            raise RuntimeError('Locked dependencies are incomplete: '+', '.join(missing)+'. Update lockfile explicitly to resolve again.')
        fresh = [h for h in missing if h not in encountered]
        if not fresh:
            raise RuntimeError('Недостающий заголовок повторился после разрешения зависимостей: '+', '.join(missing))
        for header in fresh:
            encountered.add(header)
            if git_context is None:resolve_missing_header(header, installed, runner)
            else:resolve_missing_header(header, installed, runner, git_context)
    raise RuntimeError('Не удалось разрешить все библиотеки за 13 попыток; уточни зависимости в настройках проекта')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sketch', required=True, type=Path)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--profile', required=True)
    a=parser.parse_args()
    a.build.mkdir(parents=True, exist_ok=True)
    try:
        compile_project(a.sketch, a.build, a.profile)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        sys.exit('[ESP Flasher] '+str(e))

if __name__=='__main__':
    main()
