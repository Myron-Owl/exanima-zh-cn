"""Build and verify the standalone patch without accessing or changing a game install."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

from build_support import ROOT, CATALOG_NAMES, ZIG_VERSION, find_zig, compiler_environment

COMPILE_STEPS = (
    'compile_item_names.py', 'compile_core.py', 'compile_ui_supplement.py',
    'compile_controller_manual.py', 'compile_maps.py', 'compile_runtime.py',
)
BUILD_STEPS = ('build_native.py', 'build_font_atlas.py', 'stage_preview.py')
VERIFY_STEPS = ('audit_batch.py', 'verify_font_coverage.py', 'verify_translations.py', 'verify_render_state.py')


def read_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key in {path}: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)


def check_inputs(zig):
    if sys.version_info < (3, 12):
        raise RuntimeError('Python 3.12 or later is required; the verified reference uses Python 3.12.')
    if os.name != 'nt':
        raise RuntimeError('The complete build runs native Windows tests and requires Windows x64.')
    if sys.maxsize <= 2**32:
        raise RuntimeError('Use 64-bit Python.')
    import PIL
    from PIL import features
    if PIL.__version__ != '12.3.0':
        raise RuntimeError(f'Use Pillow 12.3.0; installed version is {PIL.__version__}.')
    version = subprocess.run([str(zig), 'version'], capture_output=True, text=True, check=True,
                             env=compiler_environment()).stdout.strip()
    if version != ZIG_VERSION:
        raise RuntimeError(f'Use Zig {ZIG_VERSION}; selected compiler reports {version}.')
    required = ['native/proxy.c', 'native/runtime.c', 'native/unicode.c', 'native/unicode.h',
                'native/unicode_verify.c', 'native/render_state_verify.c', 'release/README.txt']
    required += ['tools/' + name for name in (*COMPILE_STEPS, *BUILD_STEPS, *VERIFY_STEPS, 'package_m1.py', 'font_cmap.py')]
    for relative in required:
        if not (ROOT / relative).is_file():
            raise FileNotFoundError(relative)
    catalogs = {}
    for name in CATALOG_NAMES:
        local = ROOT / 'build/catalog' / name
        source = local if local.exists() else ROOT / 'data/catalog' / name
        if not isinstance(read_json(source), list):
            raise ValueError(f'Catalog must contain a JSON list: {source}')
        catalogs[name] = str(source.relative_to(ROOT))
    translation_files = list((ROOT / 'translations').glob('*.json'))
    if not translation_files:
        raise FileNotFoundError('translations/*.json')
    for path in translation_files:
        read_json(path)
    provenance = read_json(ROOT / 'assets/fonts/provenance.json')
    expected_fonts = {'NotoSerifSC.ttf', 'NotoSerifLatin.ttf', 'OFL.txt', 'Latin-OFL.txt'}
    if set(provenance) != expected_fonts:
        raise ValueError('Font provenance must describe both fonts and both licenses.')
    for name, record in provenance.items():
        data = (ROOT / 'assets/fonts' / name).read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError(f'Font asset does not match pinned provenance: {name}')
    return {'python': sys.version.split()[0], 'pillow': PIL.__version__,
            'freetype': features.version('freetype2'), 'zig': str(zig), 'zig_version': version,
            'catalog_inputs': catalogs, 'translation_json_files': len(translation_files),
            'readme_sha256': hashlib.sha256((ROOT / 'release/README.txt').read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', metavar='PATH', help='Zig executable or its directory; overrides EXANIMA_ZIG.')
    parser.add_argument('--check-only', action='store_true', help='Check dependencies and source assets; create no build files.')
    args = parser.parse_args()
    try:
        zig = find_zig(args.zig)
        report = check_inputs(zig)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if args.check_only:
            print('Input and dependency checks passed; no build files were created.')
            return 0
        # Re-extracted catalogs take precedence. Only seed files which are absent.
        target = ROOT / 'build/catalog'
        target.mkdir(parents=True, exist_ok=True)
        for name in CATALOG_NAMES:
            if not (target / name).exists():
                shutil.copy2(ROOT / 'data/catalog' / name, target / name)
        env = dict(compiler_environment(), EXANIMA_ZIG=str(zig), PYTHONDONTWRITEBYTECODE='1')
        for step in (*COMPILE_STEPS, *BUILD_STEPS, *VERIFY_STEPS, 'package_m1.py'):
            print(f'Running {step}', flush=True)
            command = [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'tools' / step)]
            if step == 'package_m1.py':
                command += ['--profile', 'preview']
            subprocess.run(command, cwd=ROOT, env=env, check=True)
        print('Build complete: dist/Exanima-zh-CN-0.9.5.2.zip and its .sha256 file.')
        print('Automated checks passed. This does not replace visual verification in the game.')
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as error:
        print(f'Build stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
