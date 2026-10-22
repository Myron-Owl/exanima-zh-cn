"""Verify named WINMM imports, loader regression and safe system passthrough.

Only the compiled verification host is executed. Steam and game files are
never executed or modified. Each run is retained under build/proxy-verification.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
MIXER_NAMES = set('''mixerClose mixerGetControlDetailsA mixerGetControlDetailsW
mixerGetDevCapsA mixerGetDevCapsW mixerGetID mixerGetLineControlsA
mixerGetLineControlsW mixerGetLineInfoA mixerGetLineInfoW mixerGetNumDevs
mixerMessage mixerOpen mixerSetControlDetails'''.split())
EXISTING_NAMES = set('''timeGetTime timeBeginPeriod timeEndPeriod timeGetDevCaps
waveInGetNumDevs waveOutGetNumDevs waveInGetDevCapsW waveOutGetDevCapsW
waveInOpen waveOutOpen waveInAddBuffer waveInPrepareHeader waveInUnprepareHeader
waveOutPrepareHeader waveOutUnprepareHeader waveOutWrite waveInClose waveInReset
waveInStart waveInStop waveOutClose waveOutPause waveOutReset waveOutRestart
waveOutGetPosition waveInGetErrorTextW waveOutGetErrorTextW waveInMessage
waveOutMessage'''.split())
PROBE_NAMES = MIXER_NAMES | {'timeGetTime', 'timeGetDevCaps', 'timeBeginPeriod',
                             'timeEndPeriod', 'waveInGetNumDevs', 'waveOutGetNumDevs'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PE:
    """Small bounds-checked reader for names in ordinary/delay imports and exports."""
    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        require(self.data[:2] == b'MZ', f'Not a PE image: {path}')
        pe = self.unpack('<I', 0x3c)[0]
        require(self.data[pe:pe + 4] == b'PE\0\0', f'Invalid PE signature: {path}')
        self.machine, count = self.unpack('<HH', pe + 4)
        optional_size = self.unpack('<H', pe + 20)[0]
        optional = pe + 24
        magic = self.unpack('<H', optional)[0]
        require(magic in (0x10b, 0x20b), f'Unsupported PE format: {path}')
        self.is64 = magic == 0x20b
        self.width = 8 if self.is64 else 4
        self.image_base = self.unpack('<Q' if self.is64 else '<I', optional + (24 if self.is64 else 28))[0]
        self.header_size = self.unpack('<I', optional + 60)[0]
        directory_offset = 112 if self.is64 else 96
        directory_count = self.unpack('<I', optional + directory_offset - 4)[0]
        require(directory_count <= (optional_size - directory_offset) // 8,
                f'Data directories exceed optional header: {path}')
        self.directories = [self.unpack('<II', optional + directory_offset + i * 8)
                            for i in range(directory_count)]
        self.sections = []
        for i in range(count):
            virtual_size, virtual_address, raw_size, raw = self.unpack('<4I', optional + optional_size + i * 40 + 8)
            self.sections.append((virtual_address, virtual_size, raw, raw_size))

    def unpack(self, fmt, offset):
        require(0 <= offset <= len(self.data) - struct.calcsize(fmt), f'PE structure outside file: {self.path}')
        return struct.unpack_from(fmt, self.data, offset)

    def offset(self, rva):
        if 0 <= rva < min(self.header_size, len(self.data)):
            return rva
        for address, size, raw, raw_size in self.sections:
            if address <= rva < address + max(size, raw_size):
                delta = rva - address
                require(delta < raw_size and raw + delta < len(self.data), f'PE RVA has no file data: {self.path}')
                return raw + delta
        raise ValueError(f'Unmapped PE RVA 0x{rva:x}: {self.path}')

    def string(self, rva):
        offset = self.offset(rva)
        end = self.data.find(b'\0', offset, min(offset + 4096, len(self.data)))
        require(end != -1, f'Unterminated PE name: {self.path}')
        return self.data[offset:end].decode('ascii')

    def directory(self, number):
        return self.directories[number] if number < len(self.directories) else (0, 0)

    def exports(self):
        rva, size = self.directory(0)
        if not rva or not size:
            return set()
        offset = self.offset(rva)
        count = self.unpack('<I', offset + 24)[0]
        names = self.unpack('<I', offset + 32)[0]
        require(count <= 65536, f'Unreasonable export count: {self.path}')
        return {self.string(self.unpack('<I', self.offset(names + i * 4))[0]) for i in range(count)}

    def imports(self):
        result = []
        for number, kind, descriptor_size in ((1, 'normal', 20), (13, 'delay', 32)):
            rva, size = self.directory(number)
            if not rva or not size:
                continue
            terminated = False
            for relative in range(0, size, descriptor_size):
                require(relative + descriptor_size <= size, f'Partial {kind} descriptor: {self.path}')
                values = self.unpack('<' + 'I' * (descriptor_size // 4), self.offset(rva + relative))
                if not any(values):
                    terminated = True
                    break
                if kind == 'normal':
                    name, thunk, is_rva = values[3], values[0] or values[4], True
                else:
                    is_rva = bool(values[0] & 1)
                    name, thunk = values[1], values[4] or values[3]
                    if not is_rva:
                        name -= self.image_base
                        thunk -= self.image_base
                library = self.string(name)
                names, ordinals = [], []
                for index in range(65536):
                    value = self.unpack('<Q' if self.is64 else '<I', self.offset(thunk + index * self.width))[0]
                    if not value:
                        break
                    if value & (1 << (8 * self.width - 1)):
                        ordinals.append(value & 0xffff)
                    else:
                        names.append(self.string(value + 2 if is_rva else value - self.image_base + 2))
                else:
                    raise ValueError(f'Unterminated import thunk: {self.path}')
                result.append({'library': library, 'kind': kind, 'names': sorted(set(names)),
                               'ordinals': sorted(set(ordinals))})
            require(terminated, f'Unterminated {kind} import directory: {self.path}')
        return result


def winmm_imports(pe):
    return [item for item in pe.imports() if item['library'].lower() == 'winmm.dll']


def find_zig(explicit):
    requested = explicit or os.environ.get('EXANIMA_ZIG')
    if requested:
        path = Path(requested).expanduser().resolve()
        if path.is_dir():
            path /= 'zig.exe'
        require(path.is_file(), f'Zig executable not found: {path}')
        return path
    candidates = [ROOT / 'toolchain/zig/ziglang/zig.exe',
                  ROOT / '.venv/Lib/site-packages/ziglang/zig.exe',
                  Path(sys.prefix) / 'Lib/site-packages/ziglang/zig.exe']
    on_path = shutil.which('zig')
    if on_path:
        candidates.append(Path(on_path))
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise ValueError('Zig was not found; provide --zig PATH or EXANIMA_ZIG.')


def steam_inventory(directory, exports):
    if directory is None:
        return {'status': 'skipped', 'reason': '--steam-dir not supplied', 'files': [], 'missing_names': [], 'ordinals': []}
    require(directory.is_dir(), f'Steam directory does not exist: {directory}')
    files, missing, ordinals = [], set(), set()
    for name in ('steamclient64.dll', 'GameOverlayRenderer64.dll', 'steamclient.dll', 'GameOverlayRenderer.dll'):
        path = directory / name
        if not path.is_file():
            files.append({'file': name, 'status': 'absent'})
            continue
        pe = PE(path)
        selected = pe.machine == 0x8664
        imports = winmm_imports(pe)
        names = {name for item in imports for name in item['names']}
        ordinal_set = {value for item in imports for value in item['ordinals']}
        if selected:
            missing.update(names - exports)
            ordinals.update(ordinal_set)
        files.append({'file': name, 'sha256': sha256(path), 'machine': hex(pe.machine),
                      'selected_for_x64_coverage': selected, 'imports': imports,
                      'missing_names': sorted(names - exports) if selected else [],
                      'status': 'read_only_inventory'})
    selected_files = [file for file in files if file.get('selected_for_x64_coverage')]
    return {'status': 'checked' if selected_files else 'skipped',
            'reason': None if selected_files else 'No x64 Steamclient or overlay module found',
            'files': files, 'missing_names': sorted(missing), 'ordinals': sorted(ordinals)}


def compile_program(zig, source, destination, environment, shared=False):
    command = [str(zig), 'cc', '-target', 'x86_64-windows-gnu', '-O2', '-Wall', '-Wextra', '-Werror',
               str(ROOT / 'native' / source), '-o', str(destination)]
    if shared:
        command += ['-shared', '-lwinmm']
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    require(result.returncode == 0, f'Compile failed ({source}):\n{result.stdout}\n{result.stderr}')


def run_host(directory, *, baseline=False, startup=False):
    command = [str(directory / ('Exanima.exe' if startup else 'proxy_verify.exe'))]
    if baseline:
        command.append('--expect-missing')
    if startup:
        command.append('--startup')
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30)
    (directory / 'stdout.txt').write_text(result.stdout, encoding='utf-8')
    (directory / 'stderr.txt').write_text(result.stderr, encoding='utf-8')
    try:
        report = json.loads(result.stdout)
    except ValueError:
        report = {'passed': False, 'error': 'Native host did not return JSON'}
    report.update(exit_code=result.returncode, stderr=result.stderr)
    report['passed'] = result.returncode == 0 and report.get('passed') is True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', type=Path, default=ROOT / 'build/native/winmm.dll', help='Proxy to verify; defaults to build/native/winmm.dll.')
    parser.add_argument('--baseline', type=Path, help='Old proxy; its static-import load must fail with error 127.')
    parser.add_argument('--startup-baseline', type=Path, help='Timer-only proxy that must fail automatic startup without any WinMM calls.')
    parser.add_argument('--zig', help='Local Zig executable or its directory.')
    parser.add_argument('--steam-dir', type=Path, help='Read Steamclient/overlay imports without executing Steam.')
    args = parser.parse_args()
    try:
        require(os.name == 'nt' and sys.maxsize > 2**32, 'Run with 64-bit Python on Windows.')
        args.proxy = args.proxy.expanduser().resolve()
        require(args.proxy.is_file(), f'Proxy does not exist: {args.proxy}')
        if args.baseline:
            args.baseline = args.baseline.expanduser().resolve()
            require(args.baseline.is_file(), f'Baseline does not exist: {args.baseline}')
        if args.steam_dir:
            args.steam_dir = args.steam_dir.expanduser().resolve()
            require(args.steam_dir.is_dir(), f'Steam directory does not exist: {args.steam_dir}')
        zig = find_zig(args.zig)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    run = ROOT / 'build/proxy-verification' / stamp
    run.mkdir(parents=True, exist_ok=False)
    report = {'passed': False, 'run_directory': str(run), 'proxy': str(args.proxy),
              'proxy_sha256': sha256(args.proxy), 'steam_or_game_executed': False,
              'game_rendering_verified': False, 'errors': []}
    try:
        proxy_pe = PE(args.proxy)
        require(proxy_pe.machine == 0x8664, 'The proxy must be a Windows x64 DLL.')
        exports = proxy_pe.exports()
        missing = sorted((MIXER_NAMES | EXISTING_NAMES) - exports)
        report['exports'] = {'required_count': len(MIXER_NAMES | EXISTING_NAMES),
                             'actual_count': len(exports), 'missing_names': missing}
        if missing:
            report['errors'].append('Required proxy names are missing: ' + ', '.join(missing))
        report['steam'] = steam_inventory(args.steam_dir, exports)
        if report['steam']['missing_names'] or report['steam']['ordinals']:
            report['errors'].append('Specified x64 Steam modules contain uncovered WINMM imports; ordinal compatibility is not implemented by this test.')
        environment = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ROOT / 'build/zig-cache'),
                           ZIG_LOCAL_CACHE_DIR=str(run / 'zig-local-cache'))
        host, probe = run / 'proxy_verify.exe', run / 'proxy_import_probe.dll'
        compile_program(zig, 'proxy_verify.c', host, environment)
        compile_program(zig, 'proxy_import_probe.c', probe, environment, shared=True)
        probe_imports = winmm_imports(PE(probe))
        probe_names = {name for item in probe_imports for name in item['names']}
        require(PROBE_NAMES <= probe_names, 'The linker removed required static probe imports.')
        require(all(item['kind'] == 'normal' and not item['ordinals'] for item in probe_imports),
                'The probe must use static named imports, not delayed or ordinal imports.')
        require(not winmm_imports(PE(host)), 'The verification host must not preload WINMM through its own import table.')
        report['probe_static_imports'] = sorted(probe_names)

        if args.baseline:
            require(PE(args.baseline).machine == 0x8664, 'Baseline must be a Windows x64 DLL.')
            old = run / 'baseline'
            old.mkdir()
            for source, name in ((host, host.name), (probe, probe.name), (args.baseline, 'winmm.dll')):
                shutil.copy2(source, old / name)
            report['baseline'] = {'sha256': sha256(args.baseline), **run_host(old, baseline=True)}
            if not report['baseline']['passed']:
                report['errors'].append('Baseline did not reproduce Windows loader ERROR_PROC_NOT_FOUND (127).')
        else:
            report['baseline'] = {'status': 'skipped', 'reason': '--baseline not supplied'}

        current = run / 'current'
        current.mkdir()
        for source, name in ((host, host.name), (probe, probe.name), (args.proxy, 'winmm.dll')):
            shutil.copy2(source, current / name)
        runtime = args.proxy.parent / 'ExanimaZh.dll'
        has_runtime = runtime.is_file()
        if has_runtime:
            shutil.copy2(runtime, current / runtime.name)
            report['runtime_sha256'] = sha256(runtime)
        report['current'] = run_host(current)
        if not report['current']['passed']:
            report['errors'].append('Current proxy failed loader or system passthrough tests.')
        if has_runtime:
            startup = run / 'automatic-startup'
            startup.mkdir()
            for source, name in ((host, 'Exanima.exe'), (probe, probe.name), (args.proxy, 'winmm.dll'), (runtime, runtime.name)):
                shutil.copy2(source, startup / name)
            report['automatic_startup'] = run_host(startup, startup=True)
            if not report['automatic_startup']['passed']:
                report['errors'].append('Runtime did not initialize without any WinMM calls.')
            if args.startup_baseline:
                previous = run / 'timer-only-startup'
                previous.mkdir()
                for source, name in ((host, 'Exanima.exe'), (probe, probe.name), (args.startup_baseline, 'winmm.dll'), (runtime, runtime.name)):
                    shutil.copy2(source, previous / name)
                result = run_host(previous, startup=True)
                reproduced = result.get('runtime_loaded') is False and result['exit_code'] == 1
                report['startup_baseline'] = {'regression_reproduced': reproduced, **result}
                if not reproduced:
                    report['errors'].append('Timer-only baseline did not reproduce missing automatic startup.')
            log = startup / 'ExanimaZh/logs/latest.log'
            contents = log.read_text(encoding='utf-8') if log.exists() else ''
            host_hash = sha256(startup / 'Exanima.exe')
            refused = (f'Executable SHA256: {host_hash}' in contents and
                       'UNSUPPORTED VERSION: no hooks installed; English passthrough.' in contents and
                       'Verified ' not in contents)
            report['unsupported_host'] = {'passed': refused, 'host_sha256': host_hash,
                                          'fresh_log': str(log), 'text_unchanged': report['current'].get('host_text_unchanged', False)}
            if not refused:
                report['errors'].append('Fresh runtime log did not verify rejection of this unsupported host.')
        else:
            report['unsupported_host'] = {'status': 'skipped', 'reason': 'No ExanimaZh.dll beside the supplied proxy'}
        report['passed'] = not report['errors']
    except (OSError, ValueError, UnicodeError, struct.error, subprocess.SubprocessError) as error:
        report['errors'].append(str(error))
    finally:
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        (run / 'report.json').write_text(rendered, encoding='utf-8')
        (ROOT / 'build/proxy-verification/latest-report.json').write_text(rendered, encoding='utf-8')
        print(rendered, end='')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
