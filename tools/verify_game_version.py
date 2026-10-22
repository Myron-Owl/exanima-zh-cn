"""Read-only verification of a supported Exanima EXE/Resource.rpk pair.

Checks exact hashes, hook signatures/function entries, layout addresses, and
canonical scoped dictionary strings. Never loads or executes a native module,
changes the manifest, or writes to the game directory. The JSON result is
printed and retained as build/version-verification-<profile-id>.json.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from verify_proxy import PE, require
from generate_version_profiles import render

ROOT = Path(__file__).resolve().parents[1]
HOOK_NAMES = {'draw', 'measure', 'label', 'batch', 'width', 'font_width',
              'center', 'clip', 'block', 'float_block', 'block_lines'}
LEAF_HOOKS = {'width', 'font_width'}
HELPERS = {'begin', 'end', 'uv', 'vertex', 'color'}
DATA_WIDTHS = {'font_slot': 8, 'batch_count': 4, 'gui_slot': 8, 'current_color': 4}
EXECUTE = 0x20000000


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def rva(value):
    require(not isinstance(value, bool), 'Boolean is not an RVA')
    result = int(value, 0) if isinstance(value, str) else int(value)
    require(0 < result < 2**32, f'Invalid RVA: {value!r}')
    return result


class GamePE(PE):
    """Add mapped ranges, executable flags and x64 exception entries to PE."""
    def __init__(self, path):
        super().__init__(path)
        require(self.machine == 0x8664 and self.is64, 'Expected an x64 PE32+ executable')
        header = self.unpack('<I', 0x3c)[0]
        count = self.unpack('<H', header + 6)[0]
        optional_size = self.unpack('<H', header + 20)[0]
        optional = header + 24
        self.image_size = self.unpack('<I', optional + 56)[0]
        self.mapped_sections = []
        for index in range(count):
            offset = optional + optional_size + index * 40
            name = self.data[offset:offset + 8].rstrip(b'\0').decode('ascii')
            virtual_size, address, raw_size, raw = self.unpack('<4I', offset + 8)
            flags = self.unpack('<I', offset + 36)[0]
            require(address + max(virtual_size, raw_size) <= self.image_size,
                    f'Section {name} exceeds SizeOfImage')
            require(raw_size == 0 or raw + raw_size <= len(self.data),
                    f'Section {name} exceeds file size')
            self.mapped_sections.append({'name': name, 'rva': address,
                                         'size': max(virtual_size, raw_size),
                                         'raw': raw, 'raw_size': raw_size, 'flags': flags})
        self.functions = {}
        address, size = self.directory(3)
        require(address and size and size % 12 == 0 and size <= 16 * 1024 * 1024,
                'Missing or invalid x64 exception directory')
        for start, end, unwind in struct.iter_unpack('<III', self.read(address, size)):
            require(0 < start < end <= self.image_size, 'Invalid .pdata function span')
            require(start not in self.functions, 'Duplicate .pdata function entry')
            self.functions[start] = (end, unwind)

    def section(self, address, size=1):
        require(size > 0 and 0 < address <= self.image_size - size,
                f'RVA 0x{address:x} is outside the mapped image')
        for section in self.mapped_sections:
            if section['rva'] <= address and address + size <= section['rva'] + section['size']:
                return section
        raise ValueError(f'RVA 0x{address:x} is outside mapped sections')

    def read(self, address, size):
        section = self.section(address, size)
        delta = address - section['rva']
        require(delta + size <= section['raw_size'],
                f'RVA 0x{address:x} has no complete file-backed range')
        offset = section['raw'] + delta
        return self.data[offset:offset + size]


def native_unescape(text):
    """Decode the native loader's byte escapes; high source bytes are Latin-1."""
    # Work on UTF-8 file bytes exactly as the native C loader does. Canonical
    # non-ASCII English bytes use \xNN, rather than literal UTF-8 characters.
    source = text.encode('utf-8')
    result = bytearray()
    index = 0
    escapes = {ord('n'): 10, ord('r'): 13, ord('t'): 9, ord('\\'): 92}
    while index < len(source):
        byte = source[index]
        index += 1
        if byte == 92:
            require(index < len(source), 'Trailing backslash in dictionary source')
            code = source[index]
            index += 1
            if code in escapes:
                byte = escapes[code]
            else:
                require(code == ord('x') and index + 2 <= len(source), 'Invalid dictionary escape')
                digits = source[index:index + 2]
                require(re.fullmatch(b'[0-9a-fA-F]{2}', digits) is not None, 'Invalid hex escape')
                byte = int(digits, 16)
                index += 2
        require(byte != 0, 'NUL is not permitted in dictionary text')
        result.append(byte)
    return bytes(result)


def dictionary_scopes(path):
    require(path.is_file(), f'Dictionary not found: {path}')
    data = path.read_bytes()
    require(len(data) <= 16 * 1024 * 1024 and b'\0' not in data, 'Invalid dictionary size or NUL byte')
    rows = {}
    for number, line in enumerate(data.decode('utf-8').split('\n'), 1):
        line = line.removesuffix('\r')
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        require(len(fields) in (2, 3) and fields[0] and fields[1],
                f'Malformed dictionary line {number}')
        if len(fields) == 3:
            require(re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]+', fields[2]) is not None,
                    f'Invalid dictionary scope at line {number}')
            legacy = int(fields[2], 16)
            require(0 < legacy < 2**32 and legacy not in rows,
                    f'Invalid or duplicate canonical scope at line {number}')
            rows[legacy] = {'source': native_unescape(fields[0]), 'line': number}
    return rows


def check_profile(pe, profile, dictionary):
    checks = {'hooks': [], 'layout': [], 'scopes': {}, 'errors': []}

    def attempt(category, row, check):
        try:
            check(row)
            row['passed'] = True
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            row.update(passed=False, error=str(error))
            checks['errors'].append(f'{category} {row.get("name", "")}: {error}')
        checks[category].append(row)

    hooks = profile['hooks']
    names = [str(hook['name']).removesuffix('_hook') for hook in hooks]
    require(len(hooks) == 11 and set(names) == HOOK_NAMES, 'Profile must contain the 11 distinct hooks')
    for hook, name in zip(hooks, names):
        def check_hook(row, hook=hook, name=name):
            address = rva(hook['rva'])
            signature = bytes.fromhex(hook['signature'])
            require(14 <= len(signature) <= 24, 'Hook signature must contain 14 to 24 bytes')
            section = pe.section(address, len(signature))
            require(section['name'] == '.text' and section['flags'] & EXECUTE,
                    'Hook is not fully inside executable .text')
            actual = pe.read(address, len(signature))
            row.update(rva=hex(address), signature_bytes=len(signature),
                       expected=signature.hex(' '), actual=actual.hex(' '))
            require(actual == signature, 'Hook signature mismatch')
            if address in pe.functions:
                end, _ = pe.functions[address]
                require(address + len(signature) <= end, 'Signature exceeds .pdata function')
                row['function_entry'] = {'kind': 'pdata', 'end_rva': hex(end)}
            else:
                require(name in LEAF_HOOKS, 'Hook has no matching .pdata entry')
                require(not any(start < address < end for start, (end, _) in pe.functions.items()),
                        'Leaf hook points inside another .pdata function')
                row['function_entry'] = {'kind': 'known_leaf_without_pdata'}
        attempt('hooks', {'name': name}, check_hook)

    layout = profile['layout']
    require(HELPERS | set(DATA_WIDTHS) <= set(layout), 'Profile is missing required layout fields')
    for name in sorted(HELPERS | set(DATA_WIDTHS)):
        def check_layout(row, name=name):
            address = rva(layout[name])
            section = pe.section(address, DATA_WIDTHS.get(name, 1))
            row.update(rva=hex(address), section=section['name'])
            if name in HELPERS:
                require(section['flags'] & EXECUTE, 'Layout helper is not executable')
                pe.read(address, 1)
                row['kind'] = 'executable_helper'
            else:
                require(not section['flags'] & EXECUTE, 'Layout data points into executable code')
                row.update(kind='mapped_data', byte_width=DATA_WIDTHS[name])
        attempt('layout', {'name': name}, check_layout)

    scopes = profile['scopes']
    require(isinstance(profile['remap_scopes'], bool), 'remap_scopes must be boolean')
    mapping = {rva(item['legacy_rva']): rva(item['current_rva']) for item in scopes}
    require(len(scopes) == len(mapping) == 9, 'Profile must contain nine distinct canonical scopes')
    require(len(set(mapping.values())) == 9, 'Profile contains duplicate target scopes')
    require(profile['remap_scopes'] or all(a == b for a, b in mapping.items()),
            'Profile remaps scopes while remap_scopes is false')
    if dictionary is None:
        checks['scopes'] = {'status': 'skipped', 'reason': 'No --dictionary and no staged dictionary found',
                            'declared_scope_count': len(mapping)}
    else:
        source_rows = dictionary_scopes(dictionary)
        require(set(source_rows) == set(mapping), 'Canonical dictionary scopes do not match the nine profile scopes')
        scope_results = []
        checks['scopes'] = {'status': 'checked', 'dictionary': str(dictionary),
                            'dictionary_sha256': digest(dictionary), 'entries': scope_results}
        for legacy, address in mapping.items():
            source = source_rows[legacy]['source']
            row = {'legacy_rva': hex(legacy), 'current_rva': hex(address),
                   'dictionary_line': source_rows[legacy]['line'],
                   'source_latin1': source.decode('latin-1'), 'expected_length': len(source)}
            try:
                declared = next(item for item in scopes if rva(item['legacy_rva']) == legacy).get('source_hex')
                require(declared is None or bytes.fromhex(declared) == source,
                        'Manifest source_hex differs from canonical dictionary source')
                require(address >= 8 and 0 < len(source) <= 65536, 'Invalid scoped string length or address')
                length = struct.unpack('<q', pe.read(address - 8, 8))[0]
                row['stored_length'] = length
                require(length == len(source), 'Source length prefix mismatch')
                require(pe.read(address, len(source) + 1) == source + b'\0', 'Source bytes or terminator mismatch')
                row['passed'] = True
            except ValueError as error:
                row.update(passed=False, error=str(error))
                checks['errors'].append(f'Scope {hex(legacy)}: {error}')
            scope_results.append(row)
        checks['scopes']['passed'] = all(row['passed'] for row in scope_results)
    return checks


def select_pair(directory, profiles, allow_backups):
    inspected = []
    suffixes = ['', '.original', '.exanima-zh-original'] if allow_backups else ['']
    for suffix in suffixes:
        exe, resource = directory / ('Exanima.exe' + suffix), directory / ('Resource.rpk' + suffix)
        row = {'exe': str(exe), 'resource': str(resource), 'backup_suffix': suffix or None}
        if not exe.is_file() or not resource.is_file():
            row.update(status='missing', missing=[str(p) for p in (exe, resource) if not p.is_file()])
            inspected.append(row)
            continue
        row.update(exe_sha256=digest(exe), rpk_sha256=digest(resource))
        matches = [profile for profile in profiles if profile['exe_sha256'].lower() == row['exe_sha256']
                   and profile['rpk_sha256'].lower() == row['rpk_sha256']]
        require(len(matches) <= 1, 'Manifest contains duplicate supported hash pairs')
        row['status'] = 'supported' if matches else 'unsupported'
        inspected.append(row)
        if matches:
            return matches[0], exe, not bool(suffix), inspected
    return None, None, False, inspected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', required=True, type=Path, help='Game directory; files are only read.')
    parser.add_argument('--dictionary', type=Path, help='Canonical ui.utf8; defaults to the staged dictionary when present.')
    parser.add_argument('--allow-original-backups', action='store_true',
                        help='Allow a matching pair of .original or .exanima-zh-original backups if active files are unsupported.')
    args = parser.parse_args()
    report = {'passed': False, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'profile_id': None, 'game_directory': str(args.game_dir.expanduser().resolve()),
              'active_game_files_verified': False, 'game_files_modified': False,
              'native_code_executed': False, 'game_rendering_verified': False, 'errors': []}
    report_id = 'unsupported'
    try:
        manifest = ROOT / 'data/versions.json'
        profiles = json.loads(manifest.read_text(encoding='utf-8'))['versions']
        require(isinstance(profiles, list) and profiles, 'No version profiles in manifest')
        for profile in profiles:
            require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', profile['id']) is not None,
                    'Invalid profile id')
            require(all(re.fullmatch(r'[0-9a-fA-F]{64}', profile[key]) for key in ('exe_sha256', 'rpk_sha256')),
                    'Invalid profile SHA256')
        require(len({profile['id'] for profile in profiles}) == len(profiles), 'Duplicate profile ids')
        header = ROOT / 'native/version_profiles.h'
        expected_header = render(profiles).encode('utf-8')
        require(header.is_file() and header.read_bytes() == expected_header,
                'Generated version header is stale; run tools/generate_version_profiles.py')
        report['generated_header'] = {'path': str(header), 'matches_manifest': True,
                                      'sha256': digest(header)}
        directory = args.game_dir.expanduser().resolve()
        require(directory.is_dir(), f'Game directory does not exist: {directory}')
        profile, exe, active, inspected = select_pair(directory, profiles, args.allow_original_backups)
        report['inspected_pairs'] = inspected
        require(profile is not None, 'Unsupported EXE/Resource.rpk hash pair; no address checks performed')
        report_id = profile['id']
        report.update(profile_id=report_id, selected_exe=str(exe), selected_pair_is_active=active,
                      manifest_sha256=digest(manifest))
        dictionary = args.dictionary.expanduser().resolve() if args.dictionary else None
        default_dictionary = ROOT / 'build/preview-package/ExanimaZh/translations/ui.utf8'
        if dictionary is None and default_dictionary.is_file():
            dictionary = default_dictionary
        pe = GamePE(exe)
        checks = check_profile(pe, profile, dictionary)
        report.update(checks=checks, image_size=hex(pe.image_size))
        report['errors'].extend(checks['errors'])
        report['passed'] = not report['errors']
        report['active_game_files_verified'] = active and report['passed']
        if not active:
            report['notice'] = 'Only original backups were verified. The active installed EXE/Resource.rpk pair is not supported.'
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        report['errors'].append(str(error))
    output = ROOT / 'build' / f'version-verification-{report_id}.json'
    report['report_path'] = str(output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError as error:
        report['passed'] = False
        report['errors'].append(f'Cannot save report: {error}')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
