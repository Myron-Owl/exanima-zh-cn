"""Package the optional Windows font converter; do not rebuild/install the patch."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
import zipfile

from font_converter import ROOT, VERSION, default_characters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise RuntimeError('Windows x64 Python is required to build the Windows executable.')
    for package, expected in (('Pillow', '12.3.0'), ('pyinstaller', '6.16.0')):
        if importlib.metadata.version(package) != expected:
            raise RuntimeError(f'Use {package} {expected}; see requirements-font-tool.txt.')
    import PIL
    import PyInstaller
    from PIL import features
    run = ROOT / 'build/font-tool' / time.strftime('%Y%m%dT%H%M%S')
    run.mkdir(parents=True, exist_ok=False)
    charset = run / 'font-tool-charset.json'
    chars = default_characters()
    charset.write_text(json.dumps({'schema': 1, 'codepoints': sorted(map(ord, chars))}, indent=2) + '\n', encoding='utf-8')
    command = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
               '--windowed', '--name', 'ExanimaFontTool', '--distpath', str(run / 'app'),
               '--workpath', str(run / 'work'), '--specpath', str(run),
               '--paths', str(ROOT / 'tools'), '--exclude-module', 'stage_preview',
               '--exclude-module', 'numpy', '--exclude-module', 'pytest',
               '--add-data', f'{charset};.',
               '--add-data', f'{ROOT / "assets/fonts/NotoSerifLatin.ttf"};assets/fonts',
               str(ROOT / 'tools/font_converter.py')]
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(run / 'cache'))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    exe = run / 'app/ExanimaFontTool.exe'
    if not exe.is_file():
        raise FileNotFoundError(exe)
    # Keep redistributable runtime/font notices with the executable.
    notices = {}
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    notices['licenses/Python-LICENSE.txt'] = python_license.read_bytes()
    notices['licenses/NotoSerifLatin-OFL.txt'] = (ROOT / 'assets/fonts/Latin-OFL.txt').read_bytes()
    for package, prefix in (('Pillow', 'Pillow'), ('pyinstaller', 'PyInstaller')):
        distribution = importlib.metadata.distribution(package)
        found = False
        for relative in distribution.files or ():
            if '.dist-info/' in str(relative).replace('\\', '/') and 'license' in str(relative).lower():
                file = Path(distribution.locate_file(relative))
                if file.is_file():
                    notices[f'licenses/{prefix}-{file.name}'] = file.read_bytes()
                    found = True
        if not found:
            # Some Python bundles keep upstream notices alongside the package.
            candidates = [Path(PIL.__file__).parent / 'LICENSE', Path(PyInstaller.__file__).parent / 'COPYING.txt']
            candidate = candidates[0 if package == 'Pillow' else 1]
            notices[f'licenses/{prefix}-{candidate.name}'] = candidate.read_bytes()
    # Windows Python's binary distribution may omit the standalone Tcl/Tk notices.
    # Preserve copies from the corresponding upstream 8.6.12 source releases.
    for library in ('Tcl', 'Tk'):
        notices[f'licenses/{library}-license.terms'] = (ROOT / f'release/font-tool-{library}-license.terms').read_bytes()
    report = {'version': VERSION, 'platform': 'Windows x64', 'python': sys.version.split()[0],
              'pillow': PIL.__version__, 'freetype': features.version('freetype2'),
              'pyinstaller': PyInstaller.__version__, 'builtin_characters': len(chars),
              'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest()}
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    destination = dist / f'Exanima-Font-Tool-{VERSION}-Windows-x64.zip'
    if destination.exists():
        raise FileExistsError(f'Archive already exists; preserve it before rebuilding: {destination}')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(exe, 'ExanimaFontTool.exe')
        archive.write(ROOT / 'docs/FONT_TOOL.md', '使用说明.md')
        archive.writestr('build-info.json', json.dumps(report, indent=2) + '\n')
        for name, content in sorted(notices.items()):
            archive.writestr(name, content)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + '.sha256')
    checksum.write_text(f'{digest}  {destination.name}\n', encoding='ascii')
    (run / 'build-info.json').write_text(json.dumps({**report, 'zip': str(destination), 'zip_sha256': digest}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({**report, 'zip': str(destination), 'zip_sha256': digest}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
