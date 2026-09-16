#!/usr/bin/env python3
"""Source separation. Caches by source hash so repeat analysis is free."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys

STEM_NAMES = ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')
DEFAULT_MODEL = 'htdemucs_6s'


class SeparationError(Exception):
    pass


def source_hash(audio):
    h = hashlib.sha256()
    with open(audio, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def stem_cache_dir(audio, cache_root):
    return Path(cache_root) / 'stems' / source_hash(audio)


def separate(audio, cache_root, model=DEFAULT_MODEL):
    audio = Path(audio)
    if not audio.exists():
        raise SeparationError(f'No such audio file: {audio}')
    target = stem_cache_dir(audio, cache_root)
    produced = target / model / audio.stem
    found = {n: produced / f'{n}.wav' for n in STEM_NAMES}
    if all(p.exists() for p in found.values()):
        return found
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        target.chmod(0o700)
    except OSError:
        raise SeparationError('Stem cache folder permissions could not be tightened.') from None
    result = subprocess.run(
        [sys.executable, '-m', 'demucs', '-n', model, '-o', str(target), str(audio)],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise SeparationError(
            'Separation failed. Run scripts/setup.py to install demucs, then retry.')
    missing = [n for n, p in found.items() if not p.exists()]
    if missing:
        raise SeparationError(
            f'Separation produced no {", ".join(missing)} stem. '
            f'Model {model} must be a six-stem model.')
    return found


if __name__ == '__main__':
    for name, path in separate(sys.argv[1], Path.cwd() / 'cache').items():
        print(f'{name}={path}')
