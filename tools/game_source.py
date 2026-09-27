"""Read-only selection of verified Exanima 0.9.5.2 source files."""
import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys


EXPECTED_HASHES = {
    'Exanima.exe': '97a83509f1e230349126817adb8576a7725bceda120023f1173bb463b46cba6a',
    'Resource.rpk': 'e32dbf99663d648848a1dff3c777fc9a5a32d17c20576a7df69cfd60b39b751a',
}


@dataclass(frozen=True)
class GameFiles:
    directory: Path
    exe: Path
    rpk: Path


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def resolve_game_files(directory):
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f'Game directory does not exist or is not a directory: {directory}')
    selected = {}
    for name, expected in EXPECTED_HASHES.items():
        failures = []
        for candidate in (directory / name, directory / (name + '.exanima-zh-original')):
            if not candidate.is_file():
                failures.append(f'{candidate.name}: missing')
                continue
            actual = file_sha256(candidate)
            if actual != expected:
                failures.append(f'{candidate.name}: SHA256 mismatch ({actual})')
                continue
            selected[name] = candidate
            if candidate.name != name:
                print(f'Using verified original backup: {candidate}', file=sys.stderr)
            break
        else:
            raise ValueError(
                f'No verified Exanima 0.9.5.2 source for {name} in {directory}. '
                f'Expected SHA256: {expected}. ' + '; '.join(failures)
            )
    return GameFiles(directory, selected['Exanima.exe'], selected['Resource.rpk'])


def parse_game_files(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        '--game-dir', required=True, type=Path,
        help='Directory containing the original Exanima 0.9.5.2 EXE and RPK (read only).',
    )
    args = parser.parse_args()
    try:
        return resolve_game_files(args.game_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))
