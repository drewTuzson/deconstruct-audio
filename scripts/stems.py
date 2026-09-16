#!/usr/bin/env python3
"""Source separation. Caches by source hash so repeat analysis is free."""
from pathlib import Path
import hashlib
import stat
import subprocess
import sys

STEM_NAMES = ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')
DEFAULT_MODEL = 'htdemucs_6s'

# Smallest size a stem file is allowed to have and still be believed.
#
# Chosen from both ends. Above: demucs writes 44.1 kHz stereo 16-bit PCM, about
# 176 kB per second, so 1 kB is under 6 ms of audio. No stem of a real track is
# that short, which means the threshold can never reject a genuine separation.
# Below: a canonical WAV header is 44 bytes, so every shape this is meant to
# catch (a zero-byte placeholder, a header-only file, a write interrupted in
# its first moments) sits far beneath it.
#
# 1024 is also the number this project already used for the same judgement.
# The real-separation integration test asserted each stem exceeded 1024 bytes
# before this constant existed; that test now reads the constant, so the two
# definitions of a usable stem cannot drift apart.
MIN_STEM_BYTES = 1024


class SeparationError(Exception):
    pass


def usable_stem(path):
    """Whether a stem file can be believed, rather than merely found.

    `Path.exists()` is true for a directory, for a zero-byte placeholder, and
    for a file an interrupted run left half-written. Treating any of those as
    a finished stem is what let one corrupt separation be served from cache
    forever, since the cache short-circuits before demucs is ever reached.
    """
    try:
        info = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size >= MIN_STEM_BYTES


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
    # Existence is not completeness. An interrupted run, a zero-byte
    # placeholder, or a directory sitting where a stem belongs all answer
    # `exists()` with yes, and the short-circuit below is the only gate
    # between that answer and a returned result. A cache that fails this
    # check is re-separated rather than reported: the files are the problem,
    # and the fix is to make them again.
    if all(usable_stem(p) for p in found.values()):
        return found
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        target.chmod(0o700)
        target.parent.chmod(0o700)
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
    # demucs exiting 0 is not proof it wrote usable audio. The same predicate
    # guards the fresh result, so a stem too small to be real is named here
    # rather than handed back and then trusted forever by the cache. The
    # unusable files stay on disk and the next call re-separates over them.
    unusable = [n for n, p in found.items() if not usable_stem(p)]
    if unusable:
        raise SeparationError(
            f'Separation left the {", ".join(unusable)} stem too small to be '
            'usable audio. The cache was not trusted; run the command again.')
    return found


if __name__ == '__main__':
    for name, path in separate(sys.argv[1], Path.cwd() / 'cache').items():
        print(f'{name}={path}')
