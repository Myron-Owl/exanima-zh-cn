"""Project-local build configuration; never changes the user's environment."""
from pathlib import Path
import os
import shutil
import sys
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
ZIG_VERSION = '0.14.1'
CATALOG_NAMES = ('sources.json', 'resource-sources.json', 'dialogue-sources.json', 'map-sources.json')


def _executable(path):
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        for name in ('zig.exe', 'zig', 'ziglang/zig.exe', 'ziglang/zig'):
            child = candidate / name
            if child.is_file():
                return child.resolve()
    elif candidate.is_file():
        return candidate.resolve()
    return None


def find_zig(explicit=None):
    """Use an explicit override first, then virtualenv/local installs and PATH."""
    override = explicit or os.environ.get('EXANIMA_ZIG')
    if override:
        executable = _executable(override)
        on_path = shutil.which(str(override))
        if executable is None and on_path:
            executable = _executable(on_path)
        if executable:
            return executable
        raise FileNotFoundError(f'Zig override does not exist: {override}')
    candidates = [
        ROOT / '.venv/Scripts/zig.exe', ROOT / '.venv/Scripts/zig',
        ROOT / '.venv/bin/zig', ROOT / '.venv/bin/zig.exe',
        ROOT / '.venv/Lib/site-packages/ziglang/zig.exe',
        Path(sys.prefix) / 'Scripts/zig.exe', Path(sys.prefix) / 'bin/zig',
        Path(sys.prefix) / 'Lib/site-packages/ziglang/zig.exe',
        ROOT / 'toolchain/zig/ziglang/zig.exe', ROOT / 'toolchain/zig/ziglang/zig',
    ]
    for prefix in (ROOT / '.venv', Path(sys.prefix)):
        candidates.extend(prefix.glob('lib/python*/site-packages/ziglang/zig'))
    spec = importlib.util.find_spec('ziglang')
    if spec and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            candidates.extend((Path(location) / 'zig.exe', Path(location) / 'zig'))
    for candidate in candidates:
        executable = _executable(candidate)
        if executable:
            return executable
    on_path = shutil.which('zig') or shutil.which('zig.exe')
    if on_path:
        return Path(on_path).resolve()
    raise FileNotFoundError('Zig 0.14.1 not found. Use --zig PATH, EXANIMA_ZIG, or install ziglang in .venv.')


def compiler_environment():
    return dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ROOT / 'build/zig-cache'))
