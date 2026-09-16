# Separation and Tempo Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract stems from a track, derive tempo as a periodicity family rather than a single number, and score any two tracks against each other on measured axes.

**Architecture:** Two new service modules own the reusable work (`stems.py`, `tempo.py`), a third owns scoring (`compare.py`), and `deconstruct.py` gains three thin commands that orchestrate them. Separation results are cached by source hash so repeat runs are free. No existing behavior changes.

**Tech Stack:** Python 3.10+, demucs (htdemucs_6s), PyTorch, librosa, numpy, ffmpeg.

**Spec:** `docs/superpowers/specs/2026-09-16-audio-fact-sheet-design.md`

## Global Constraints

- Python 3.10 or newer. ffmpeg and ffprobe on PATH.
- Run tests with the project venv: `.venv/bin/python -m unittest discover -s tests`. A bare system python fails on missing audio dependencies and that is not a regression.
- Private files: directories created at `0700`, files written via `tempfile.mkstemp` then `os.replace`. Never widen a mode, never write in place.
- No API key in a command line, log, error message, test fixture, or commit.
- Tests must not require the demucs model download. Separation is mocked by default; one integration test is opt-in behind `DECONSTRUCT_AUDIO_RUN_SEPARATION=1`.
- No copyrighted audio in the repository. Tempo tests generate synthetic click tracks with ffmpeg.
- Commands orchestrate, service modules own the reusable how. Follow `AGENTS.md`.
- Every emitted measurement carries its method and a confidence grade of `KNOW`, `INFER`, or `UNKNOWN`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/stems.py` (create) | Separation. Runs demucs, caches by source hash, returns stem paths. Knows nothing about tempo or config. |
| `scripts/tempo.py` (create) | Tempo family extraction from a single audio file. Pure measurement, no I/O beyond reading the file. |
| `scripts/compare.py` (create) | Scoring two measurement dicts against gate thresholds. Pure functions, no file reads. |
| `scripts/deconstruct.py` (modify) | Adds `separate`, `tempo`, and `compare` commands. Orchestration only. |
| `requirements.txt` (modify) | Adds demucs and torch. |
| `tests/test_stems.py` (create) | Separation contract, caching, failure handling. |
| `tests/test_tempo.py` (create) | Tempo family on synthetic click tracks, including the 4/3 trap. |
| `tests/test_compare.py` (create) | Gate thresholds and verdicts. |

---

### Task 1: Separation service

**Files:**
- Create: `scripts/stems.py`
- Create: `tests/test_stems.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `separate(audio: Path, cache_root: Path, model: str = 'htdemucs_6s') -> dict[str, Path]` returning keys `drums`, `bass`, `guitar`, `piano`, `vocals`, `other`. Also `STEM_NAMES: tuple[str, ...]` and `stem_cache_dir(audio, cache_root) -> Path`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stems.py`:

```python
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import stems


class StemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.audio = self.path / 'song.wav'
        self.audio.write_bytes(b'RIFF0000WAVEfake')

    def _fake_run(self, produced):
        def run(cmd, **kwargs):
            out = stems.stem_cache_dir(self.audio, self.path) / 'htdemucs_6s' / self.audio.stem
            out.mkdir(parents=True, exist_ok=True)
            for name in produced:
                (out / f'{name}.wav').write_bytes(b'RIFF0000WAVEfake')

            class Done:
                returncode = 0
                stdout = ''
                stderr = ''
            return Done()
        return run

    def test_returns_all_six_stems(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            result = stems.separate(self.audio, self.path)
        self.assertEqual(set(result), set(stems.STEM_NAMES))
        for p in result.values():
            self.assertTrue(p.exists())

    def test_second_call_reuses_cache_without_rerunning(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            stems.separate(self.audio, self.path)
        calls = []

        def spy(cmd, **kwargs):
            calls.append(cmd)
            raise AssertionError('demucs should not run again')

        with patch('subprocess.run', spy):
            result = stems.separate(self.audio, self.path)
        self.assertEqual(calls, [])
        self.assertEqual(set(result), set(stems.STEM_NAMES))

    def test_missing_stem_is_an_error_not_a_silent_gap(self):
        with patch('subprocess.run', self._fake_run(('drums', 'bass'))):
            with self.assertRaises(stems.SeparationError):
                stems.separate(self.audio, self.path)

    def test_cache_dir_is_private(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            stems.separate(self.audio, self.path)
        mode = stems.stem_cache_dir(self.audio, self.path).stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_stems -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stems'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/stems.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_stems -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Add the dependencies**

Append to `requirements.txt`:

```text
demucs>=4.0,<5
torch>=2.2
```

- [ ] **Step 6: Commit**

```bash
git add scripts/stems.py tests/test_stems.py requirements.txt
git commit -m "feat: six-stem separation with hash-keyed cache"
```

---

### Task 2: Tempo family extraction

**Files:**
- Create: `scripts/tempo.py`
- Create: `tests/test_tempo.py`

**Interfaces:**
- Consumes: nothing from Task 1. Takes any audio path, though callers should pass the drums stem.
- Produces: `tempo_family(audio: Path) -> dict` with keys `primary` (float), `family` (list of `{'bpm': float, 'ratio': str}`), `methods` (dict of method name to float), `confidence` (`'KNOW'`, `'INFER'`, or `'UNKNOWN'`), `disagreement` (str or None). Also `classify_ratio(primary: float, other: float) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tempo.py`:

```python
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tempo as t


def click_track(path, bpm, seconds=20):
    """A synthetic metronome. No copyrighted audio in the test corpus."""
    period = 60.0 / bpm
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'sine=frequency=1200:duration={seconds}',
        '-af', f'apulsator=mode=square:hz={1.0 / period}',
        '-ar', '22050', '-ac', '1', str(path)], check=True)


class RatioTests(unittest.TestCase):
    def test_classify_known_ratios(self):
        cases = [(80.0, 160.0, '2x'), (80.0, 40.0, '0.5x'),
                 (80.0, 106.7, '4/3'), (80.0, 60.0, '3/4'), (80.0, 80.4, '1x')]
        for primary, other, expected in cases:
            with self.subTest(other=other):
                self.assertEqual(t.classify_ratio(primary, other), expected)

    def test_unrelated_tempo_has_no_ratio(self):
        self.assertIsNone(t.classify_ratio(80.0, 97.0))


class FamilyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_detects_a_known_click_tempo(self):
        wav = self.path / 'click.wav'
        click_track(wav, 80)
        result = t.tempo_family(wav)
        self.assertLess(abs(result['primary'] - 80.0) / 80.0, 0.05)

    def test_emits_a_family_never_a_bare_number(self):
        wav = self.path / 'click.wav'
        click_track(wav, 80)
        result = t.tempo_family(wav)
        for key in ('primary', 'family', 'methods', 'confidence', 'disagreement'):
            self.assertIn(key, result)
        self.assertIn(result['confidence'], ('KNOW', 'INFER', 'UNKNOWN'))

    def test_non_octave_disagreement_lowers_confidence(self):
        result = t.grade({'tempogram': 80.0, 'beat_track': 106.7, 'ioi': 80.2})
        self.assertEqual(result['confidence'], 'INFER')
        self.assertIn('4/3', result['disagreement'])

    def test_unrelated_methods_are_unknown_not_a_pick(self):
        result = t.grade({'tempogram': 80.0, 'beat_track': 97.0, 'ioi': 131.0})
        self.assertEqual(result['confidence'], 'UNKNOWN')

    def test_agreeing_methods_are_known(self):
        result = t.grade({'tempogram': 80.0, 'beat_track': 80.5, 'ioi': 79.8})
        self.assertEqual(result['confidence'], 'KNOW')
        self.assertIsNone(result['disagreement'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_tempo -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tempo'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/tempo.py`:

```python
#!/usr/bin/env python3
"""Tempo as a periodicity family. A single number hides metrical ambiguity."""
import json
import sys

import librosa
import numpy as np

RATIOS = ((0.5, '0.5x'), (0.75, '3/4'), (1.0, '1x'),
          (4.0 / 3.0, '4/3'), (1.5, '1.5x'), (2.0, '2x'), (3.0, '3x'))
TOLERANCE = 0.04


def classify_ratio(primary, other):
    if primary <= 0:
        return None
    r = other / primary
    for value, label in RATIOS:
        if abs(r - value) / value <= TOLERANCE:
            return label
    return None


def grade(methods):
    """Turn per-method estimates into a family with an honest confidence."""
    primary = methods['tempogram']
    family, unrelated, ratios = [], [], []
    for name, bpm in methods.items():
        if name == 'tempogram':
            continue
        label = classify_ratio(primary, bpm)
        if label is None:
            unrelated.append(f'{name} {bpm:.1f}')
        elif label != '1x':
            family.append({'bpm': round(bpm, 1), 'ratio': label, 'method': name})
            ratios.append(label)
    if unrelated:
        confidence = 'UNKNOWN'
        disagreement = ('Methods disagree by no simple ratio: '
                        + ', '.join(unrelated) + f' against tempogram {primary:.1f}')
    elif ratios:
        confidence = 'INFER'
        disagreement = ('Methods differ by a non-octave ratio: '
                        + ', '.join(sorted(set(ratios))))
    else:
        confidence = 'KNOW'
        disagreement = None
    return {'primary': round(primary, 1), 'family': family,
            'methods': {k: round(v, 1) for k, v in methods.items()},
            'confidence': confidence, 'disagreement': disagreement}


def tempo_family(audio):
    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    if len(y) == 0:
        raise ValueError('Empty audio')
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tg = librosa.feature.tempogram(onset_envelope=onset, sr=sr)
    tempi = librosa.tempo_frequencies(tg.shape[0], sr=sr)
    strength = tg.mean(axis=1)
    usable = (tempi > 50) & (tempi < 220)
    peak = float(tempi[usable][int(np.argmax(strength[usable]))])
    tracked, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr)
    times = librosa.frames_to_time(beats, sr=sr)
    methods = {'tempogram': peak, 'beat_track': float(np.atleast_1d(tracked)[0])}
    if len(times) > 2:
        methods['ioi'] = float(60.0 / np.median(np.diff(times)))
    return grade(methods)


if __name__ == '__main__':
    print(json.dumps(tempo_family(sys.argv[1]), indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_tempo -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/tempo.py tests/test_tempo.py
git commit -m "feat: tempo as a periodicity family with graded confidence"
```

---

### Task 3: Wire the separate and tempo commands

**Files:**
- Modify: `scripts/deconstruct.py`

**Interfaces:**
- Consumes: `stems.separate`, `stems.STEM_NAMES`, `tempo.tempo_family`.
- Produces: CLI commands `separate <audio> [--out DIR]` and `tempo <audio> [--from-drums]`.

- [ ] **Step 1: Add the imports**

In `scripts/deconstruct.py`, below the existing imports:

```python
import stems
import tempo as tempo_mod
```

- [ ] **Step 2: Add the command functions**

Add above `def main():`:

```python
def cmd_separate(args):
    out = args.out or (config_dir() / 'cache')
    paths = stems.separate(args.audio, out)
    for name in stems.STEM_NAMES:
        print(f'STEM_{name.upper()}={paths[name]}')


def cmd_tempo(args):
    target = args.audio
    if args.from_drums:
        target = stems.separate(args.audio, config_dir() / 'cache')['drums']
        print(f'TEMPO_SOURCE={target}', file=sys.stderr)
    result = tempo_mod.tempo_family(target)
    print(json.dumps(result, indent=2))
```

- [ ] **Step 3: Register the parsers**

In `main()`, after the `set-model` parser line:

```python
    sp = sub.add_parser('separate')
    sp.add_argument('audio', type=Path)
    sp.add_argument('--out', type=Path, default=None)
    tp = sub.add_parser('tempo')
    tp.add_argument('audio', type=Path)
    tp.add_argument('--from-drums', action='store_true',
                    help='Separate first and measure the drums stem. Recommended.')
```

- [ ] **Step 4: Dispatch them**

In `main()`, alongside the other `elif args.command ==` branches:

```python
    elif args.command == 'separate':
        cmd_separate(args)
    elif args.command == 'tempo':
        cmd_tempo(args)
```

- [ ] **Step 5: Verify the commands exist**

Run: `.venv/bin/python scripts/deconstruct.py tempo --help`
Expected: usage text showing `--from-drums`

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK, no regressions in the existing tests

- [ ] **Step 7: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: separate and tempo commands"
```

---

### Task 4: Compare scoring

**Files:**
- Create: `scripts/compare.py`
- Create: `tests/test_compare.py`

**Interfaces:**
- Consumes: nothing. Takes two plain dicts.
- Produces: `score(reference: dict, candidate: dict) -> dict` with keys `axes` (list of `{'axis', 'reference', 'candidate', 'delta', 'verdict'}`) and `verdict` (`'PASS'`, `'WARN'`, or `'FAIL'`). Also `GATES: dict[str, dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_compare.py`:

```python
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import compare as c

REFERENCE = {'tempo_bpm': 80.7, 'key': 'F# minor', 'intro_seconds': 12.1,
             'lra_lu': 4.1, 'low_end_share': 16.4, 'section_count': 7,
             'lead_register_midi': 42}


class CompareTests(unittest.TestCase):
    def test_identical_tracks_pass_every_axis(self):
        result = c.score(REFERENCE, dict(REFERENCE))
        self.assertEqual(result['verdict'], 'PASS')
        self.assertTrue(all(a['verdict'] == 'PASS' for a in result['axes']))

    def test_octave_tempo_error_is_a_hard_fail(self):
        candidate = dict(REFERENCE, tempo_bpm=161.4)
        result = c.score(REFERENCE, candidate)
        tempo_axis = next(a for a in result['axes'] if a['axis'] == 'tempo_bpm')
        self.assertEqual(tempo_axis['verdict'], 'FAIL')
        self.assertIn('octave', tempo_axis['note'])

    def test_small_tempo_drift_passes(self):
        result = c.score(REFERENCE, dict(REFERENCE, tempo_bpm=83.0))
        tempo_axis = next(a for a in result['axes'] if a['axis'] == 'tempo_bpm')
        self.assertEqual(tempo_axis['verdict'], 'PASS')

    def test_relative_key_warns_rather_than_passing(self):
        result = c.score(REFERENCE, dict(REFERENCE, key='A major'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'WARN')

    def test_unrelated_key_fails(self):
        result = c.score(REFERENCE, dict(REFERENCE, key='D major'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'FAIL')

    def test_the_generation_we_actually_shipped_fails_on_low_end(self):
        candidate = dict(REFERENCE, low_end_share=4.9, lra_lu=2.3, intro_seconds=4.0)
        result = c.score(REFERENCE, candidate)
        failed = {a['axis'] for a in result['axes'] if a['verdict'] == 'FAIL'}
        self.assertIn('low_end_share', failed)
        self.assertIn('lra_lu', failed)
        self.assertIn('intro_seconds', failed)
        self.assertEqual(result['verdict'], 'FAIL')

    def test_missing_axis_is_reported_not_skipped(self):
        candidate = {k: v for k, v in REFERENCE.items() if k != 'lra_lu'}
        result = c.score(REFERENCE, candidate)
        lra = next(a for a in result['axes'] if a['axis'] == 'lra_lu')
        self.assertEqual(lra['verdict'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_compare -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'compare'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/compare.py`:

```python
#!/usr/bin/env python3
"""Score a candidate track against a reference on measured axes."""
import json
import sys

RELATIVE_SEMITONES = 3
NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

GATES = {
    'tempo_bpm': {'kind': 'percent', 'limit': 5.0, 'label': 'Tempo'},
    'key': {'kind': 'key', 'label': 'Key'},
    'intro_seconds': {'kind': 'absolute', 'limit': 3.0, 'label': 'Intro length'},
    'lra_lu': {'kind': 'absolute', 'limit': 1.5, 'label': 'Loudness range'},
    'low_end_share': {'kind': 'absolute', 'limit': 3.0, 'label': 'Low end share'},
    'section_count': {'kind': 'absolute', 'limit': 1, 'label': 'Section count'},
    'lead_register_midi': {'kind': 'absolute', 'limit': 5, 'label': 'Lead register'},
}


def parse_key(value):
    parts = str(value).strip().split()
    if len(parts) != 2 or parts[0] not in NOTES:
        return None
    return NOTES.index(parts[0]), parts[1].lower()


def key_verdict(reference, candidate):
    if reference == candidate:
        return 'PASS', 'exact match'
    a, b = parse_key(reference), parse_key(candidate)
    if a is None or b is None:
        return 'UNKNOWN', 'key not parseable'
    distance = (b[0] - a[0]) % 12
    if a[1] != b[1] and distance in (RELATIVE_SEMITONES, 12 - RELATIVE_SEMITONES):
        return 'WARN', 'relative major or minor, not the same tonal centre'
    return 'FAIL', 'unrelated key'


def tempo_verdict(reference, candidate):
    if reference <= 0:
        return 'UNKNOWN', 'no reference tempo', None
    delta = candidate - reference
    drift = abs(delta) / reference * 100
    for factor, name in ((2.0, 'octave'), (0.5, 'octave'),
                         (4.0 / 3.0, 'subdivision'), (0.75, 'subdivision')):
        if abs(candidate / reference - factor) / factor <= 0.04:
            return 'FAIL', f'{name} error, candidate is {factor:g}x the reference', delta
    if drift <= GATES['tempo_bpm']['limit']:
        return 'PASS', f'{drift:.1f}% drift', delta
    return 'FAIL', f'{drift:.1f}% drift exceeds 5%', delta


def score(reference, candidate):
    axes = []
    for axis, gate in GATES.items():
        ref, cand = reference.get(axis), candidate.get(axis)
        if ref is None or cand is None:
            axes.append({'axis': axis, 'label': gate['label'], 'reference': ref,
                         'candidate': cand, 'delta': None, 'verdict': 'UNKNOWN',
                         'note': 'not measured on both sides'})
            continue
        if gate['kind'] == 'key':
            verdict, note = key_verdict(ref, cand)
            delta = None
        elif gate['kind'] == 'percent':
            verdict, note, delta = tempo_verdict(ref, cand)
        else:
            delta = cand - ref
            within = abs(delta) <= gate['limit']
            verdict = 'PASS' if within else 'FAIL'
            note = f'delta {delta:+.2f} against limit {gate["limit"]}'
        axes.append({'axis': axis, 'label': gate['label'], 'reference': ref,
                     'candidate': cand, 'delta': delta, 'verdict': verdict, 'note': note})
    verdicts = [a['verdict'] for a in axes]
    overall = 'FAIL' if 'FAIL' in verdicts else ('WARN' if 'WARN' in verdicts else 'PASS')
    return {'axes': axes, 'verdict': overall}


if __name__ == '__main__':
    with open(sys.argv[1]) as f:
        reference = json.load(f)
    with open(sys.argv[2]) as f:
        candidate = json.load(f)
    print(json.dumps(score(reference, candidate), indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_compare -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/compare.py tests/test_compare.py
git commit -m "feat: score a candidate track against a reference"
```

---

### Task 5: Wire the compare command and prove it on real audio

**Files:**
- Modify: `scripts/deconstruct.py`
- Modify: `tests/test_stems.py`

**Interfaces:**
- Consumes: `compare.score`, `stems.separate`, `tempo.tempo_family`.
- Produces: CLI command `compare <reference.json> <candidate.json>`.

- [ ] **Step 1: Add the command function**

Add above `def main():` in `scripts/deconstruct.py`:

```python
def cmd_compare(args):
    import compare as compare_mod
    reference = json.loads(args.reference.read_text(encoding='utf-8'))
    candidate = json.loads(args.candidate.read_text(encoding='utf-8'))
    result = compare_mod.score(reference, candidate)
    for axis in result['axes']:
        print(f'{axis["verdict"]:<8}{axis["label"]:<18}{axis["note"]}')
    print(f'VERDICT={result["verdict"]}')
```

- [ ] **Step 2: Register and dispatch**

In `main()`, with the other parsers:

```python
    cp = sub.add_parser('compare')
    cp.add_argument('reference', type=Path)
    cp.add_argument('candidate', type=Path)
```

And with the other branches:

```python
    elif args.command == 'compare':
        cmd_compare(args)
```

- [ ] **Step 3: Add the opt-in integration test**

Append to `tests/test_stems.py`, before `if __name__`:

```python
@unittest.skipUnless(os.environ.get('DECONSTRUCT_AUDIO_RUN_SEPARATION') == '1',
                     'set DECONSTRUCT_AUDIO_RUN_SEPARATION=1 to run real separation')
class SeparationIntegrationTests(unittest.TestCase):
    def test_real_separation_produces_six_usable_stems(self):
        source = os.environ.get('DECONSTRUCT_AUDIO_TEST_TRACK')
        self.assertTrue(source, 'set DECONSTRUCT_AUDIO_TEST_TRACK to an audio file')
        with tempfile.TemporaryDirectory() as tmp:
            result = stems.separate(Path(source), Path(tmp))
            self.assertEqual(set(result), set(stems.STEM_NAMES))
            for name, path in result.items():
                self.assertGreater(path.stat().st_size, 1024, f'{name} stem is empty')
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests`
Expected: OK. The integration test reports as skipped.

- [ ] **Step 5: Prove it against the reference track**

Run, with a real track:

```bash
.venv/bin/python scripts/deconstruct.py tempo <reference-track> --from-drums
```

Expected: `primary` within 2% of the known tempo for that track, and a `family` listing the beat tracker's estimate with its ratio labelled. Record the output in the pull request as the after evidence.

- [ ] **Step 6: Commit**

```bash
git add scripts/deconstruct.py tests/test_stems.py
git commit -m "feat: compare command and opt-in separation integration test"
```

---

## Self-Review

**Spec coverage.** Stage 1 separation is Task 1. Stage 2 tempo measurement is Task 2, with the remaining measurement axes deferred to the phase 3 plan as the spec's build order intends. Stage 3 verification is Task 2's `grade`. Stage 6 compare is Tasks 4 and 5. The pipeline gates for tempo, for emitting UNKNOWN on non-octave disagreement, and for six non-silent stems are covered by tests in Tasks 1, 2, and 5. Fact sheet emission, the MIDI emitter, and the research branch are out of scope for this plan by design.

**Placeholders.** None. Every step carries the code it needs.

**Type consistency.** `separate` returns `dict[str, Path]` keyed by `STEM_NAMES` and is consumed that way in Task 3 and Task 5. `tempo_family` returns the dict graded by `grade`, and `grade` is tested directly in Task 2. `score` consumes plain dicts and is called that way in Task 5. `SeparationError` is defined in Task 1 and raised only there.

**One known gap.** Task 5 step 5 checks tempo against a track whose tempo you already know. That is a manual verification step rather than an automated gate, because the repository holds no audio. Once the phase 3 fact sheet lands, this becomes a fixture-based gate.
