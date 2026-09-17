# Fact Sheet Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an audio file plus its six stems into a fact sheet where every musical property carries the method that produced it and a confidence grade, and prove it on a three-track corpus against known ground truth.

**Architecture:** A new `facts.py` owns the `Fact` shape and assembles the sheet. A new `chords.py` owns the harmonic measurements that need band-limited stems. `compare.py` gains one axis. `deconstruct.py` gains one thin command. A `corpus_check.py` runs the whole corpus twice and diffs, which is how rerun stability becomes a gate rather than a hope.

**Tech Stack:** Python 3.10+, librosa, numpy, soundfile, ffmpeg, demucs (already installed).

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

## Global Constraints

- Python 3.10 or newer. `ffmpeg` and `ffprobe` on `PATH`.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`. Worktrees deliberately do not each build a venv, because torch is 2.5 GB and four copies of it is not a test strategy. The interpreter supplies libraries; the scripts resolve from your worktree's cwd.
- Baseline is 97 tests, OK, one skipped. Any drop is a regression.
- Commands orchestrate and print a machine-readable result line. Service modules own the reusable how. This split is an invariant in `AGENTS.md`.
- Every emitted measurement carries its method and a confidence grade of `KNOW`, `INFER`, or `UNKNOWN`. Construction raises otherwise.
- Private files: directories at `0700`, files written via `tempfile.mkstemp` then `os.replace`. Never widen a mode, never write in place.
- No API key in a command line, log, error message, test fixture, or commit.
- No copyrighted audio in the repository. Tests use synthetic audio generated with ffmpeg.
- Nothing in this plan makes a network call. `facts` is an offline command.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/facts.py` (create) | The `Fact` constructor and its validation, stem adoption, sheet assembly, the projection onto compare's axes, markdown rendering. Knows nothing about the CLI. |
| `scripts/chords.py` (create) | Band limiting, key estimate, chord sequence, harmonic rhythm, tuning estimate. Pure measurement over arrays. |
| `scripts/compare.py` (modify) | One new axis, `tuning`. |
| `scripts/deconstruct.py` (modify) | The `facts` command. Orchestration only. |
| `scripts/corpus_check.py` (create) | Runs the corpus, reruns it, diffs. |
| `tests/test_facts.py` (create) | Fact validation, stem adoption, projection, rerun stability on synthetic audio. |
| `tests/test_chords.py` (create) | Band limiting, key on synthetic chords, tuning templates. |
| `tests/test_compare.py` (modify) | The tuning axis. |

---

### Task 1: The Fact shape and its validation

**Files:**
- Create: `scripts/facts.py`
- Create: `tests/test_facts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `fact(value, unit, stem, method, confidence, suno_actionable, band_hz=None, note=None) -> dict`, `FactError`, `CONFIDENCE`, `ACTIONABLE`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_facts.py`:

```python
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import facts as f


class FactShapeTests(unittest.TestCase):
    def good(self, **over):
        kwargs = dict(value=80.7, unit='bpm', stem='drums',
                      method=['tempogram-peak'], confidence='KNOW',
                      suno_actionable='direct')
        kwargs.update(over)
        return f.fact(**kwargs)

    def test_a_complete_fact_carries_every_required_field(self):
        result = self.good()
        for key in ('value', 'unit', 'stem', 'band_hz', 'method',
                    'confidence', 'suno_actionable', 'note'):
            self.assertIn(key, result)

    def test_a_fact_without_a_method_is_an_error_not_a_gap(self):
        with self.assertRaises(f.FactError):
            self.good(method=[])

    def test_a_method_must_be_a_list_not_a_bare_string(self):
        with self.assertRaises(f.FactError):
            self.good(method='tempogram-peak')

    def test_an_unknown_confidence_grade_is_refused(self):
        with self.assertRaises(f.FactError):
            self.good(confidence='PROBABLY')

    def test_a_missing_value_is_only_allowed_when_the_grade_is_unknown(self):
        with self.assertRaises(f.FactError):
            self.good(value=None, confidence='INFER')
        self.assertIsNone(self.good(value=None, confidence='UNKNOWN')['value'])

    def test_an_unrecognised_actionable_class_is_refused(self):
        with self.assertRaises(f.FactError):
            self.good(suno_actionable='maybe')

    def test_a_band_is_a_pair_of_numbers_or_nothing(self):
        self.assertEqual(self.good(band_hz=[150, 2500])['band_hz'], [150, 2500])
        self.assertIsNone(self.good()['band_hz'])
        with self.assertRaises(f.FactError):
            self.good(band_hz=[150])

    def test_a_non_finite_value_is_not_a_measurement(self):
        for bad in (float('nan'), float('inf')):
            with self.assertRaises(f.FactError):
                self.good(value=bad)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'facts'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/facts.py` with this at the top:

```python
#!/usr/bin/env python3
"""The fact sheet. Every number carries the method that produced it.

This module exists because the pipeline it replaces emitted bare numbers from
a language model and three passes on one track returned three tempos. A fact
that cannot say how it was measured is not a fact, so fact() raises rather
than emitting one.
"""
import math

CONFIDENCE = ('KNOW', 'INFER', 'UNKNOWN')
ACTIONABLE = ('direct', 'indirect', 'midi_only', 'none')


class FactError(Exception):
    pass


def _finite(value):
    """True when value is a real measurement rather than a placeholder.

    Containers pass through: a sections fact carries a dict, a dynamic arc
    carries a list, and neither is a scalar to range check here.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return True


def fact(value, unit, stem, method, confidence, suno_actionable,
         band_hz=None, note=None):
    if confidence not in CONFIDENCE:
        raise FactError(f'confidence must be one of {CONFIDENCE}, got {confidence!r}')
    if suno_actionable not in ACTIONABLE:
        raise FactError(f'suno_actionable must be one of {ACTIONABLE}, '
                        f'got {suno_actionable!r}')
    if isinstance(method, str) or not isinstance(method, (list, tuple)) or not method:
        raise FactError('method must be a non-empty list of method names')
    if value is None and confidence != 'UNKNOWN':
        raise FactError('a fact with no value must be graded UNKNOWN')
    if value is not None and not _finite(value):
        raise FactError(f'{value!r} is not a measurement')
    if band_hz is not None:
        if not isinstance(band_hz, (list, tuple)) or len(band_hz) != 2:
            raise FactError('band_hz must be a [low, high] pair or None')
        band_hz = [band_hz[0], band_hz[1]]
    return {'value': value, 'unit': unit, 'stem': stem, 'band_hz': band_hz,
            'method': list(method), 'confidence': confidence,
            'suno_actionable': suno_actionable, 'note': note}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/facts.py tests/test_facts.py
git commit -m "feat: a fact that cannot state its method refuses to exist"
```

---

### Task 2: Stem adoption

**Files:**
- Modify: `scripts/facts.py`
- Modify: `tests/test_facts.py`

**Interfaces:**
- Consumes: `stems.STEM_NAMES` from the merged phase 1 work.
- Produces: `adopt_stems(folder) -> dict[str, Path]`, `StemAdoptionError`.

Why this exists: the two supplied corpus stem sets are named
`1_<title>_(Drums).wav`, which is not demucs output. Without adoption the corpus
is one track.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_facts.py` before `if __name__`:

```python
import tempfile


class StemAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def _write(self, names):
        for name in names:
            (self.dir / name).write_bytes(b'RIFF0000WAVEfake')

    def test_adopts_a_supplied_six_stem_folder(self):
        self._write([f'1_Some Track_({n.title()}).wav'
                     for n in ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        result = f.adopt_stems(self.dir)
        self.assertEqual(set(result), {'drums', 'bass', 'guitar',
                                       'piano', 'vocals', 'other'})
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))

    def test_adopts_plain_demucs_names(self):
        self._write([f'{n}.wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        self.assertEqual(set(f.adopt_stems(self.dir)),
                         {'drums', 'bass', 'guitar', 'piano', 'vocals', 'other'})

    def test_a_partial_folder_is_an_error_not_a_partial_sheet(self):
        self._write(['1_x_(Drums).wav', '1_x_(Bass).wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        for missing in ('guitar', 'piano', 'vocals', 'other'):
            self.assertIn(missing, str(caught.exception))

    def test_two_files_claiming_one_stem_is_an_error_not_a_coin_toss(self):
        self._write([f'1_x_({n.title()}).wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        (self.dir / 'drums_alt.wav').write_bytes(b'RIFF0000WAVEfake')
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        self.assertIn('drums', str(caught.exception))

    def test_other_does_not_swallow_a_filename_containing_the_word(self):
        self._write([f'1_Another Brother_({n.title()}).wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        result = f.adopt_stems(self.dir)
        self.assertTrue(result['other'].name.endswith('(Other).wav'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL, `AttributeError: module 'facts' has no attribute 'adopt_stems'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/facts.py`. Note the ordering: the parenthesised form is tried
first across the whole folder, and only if no file uses it does the bare-token
form run. `Another Brother_(Other).wav` contains the token `other` twice, so a
single-pass substring match would see two candidates and refuse a folder that is
in fact complete.

```python
import re
from pathlib import Path

import stems


class StemAdoptionError(Exception):
    pass


def _match(names, pattern):
    return {n: [p for p in names if pattern(n, p.name.lower())]
            for n in stems.STEM_NAMES}


def adopt_stems(folder):
    """Resolve an existing folder of six stems, however its files are named."""
    folder = Path(folder)
    if not folder.is_dir():
        raise StemAdoptionError(f'Not a folder: {folder}')
    audio = [p for p in sorted(folder.iterdir())
             if p.suffix.lower() in ('.wav', '.flac', '.mp3')]
    if not audio:
        raise StemAdoptionError(f'No audio files in {folder}')

    parenthesised = _match(audio, lambda n, low: f'({n})' in low)
    if all(len(v) == 1 for v in parenthesised.values()):
        found = parenthesised
    else:
        found = _match(audio, lambda n, low: re.search(rf'\b{n}\b', low) is not None)

    missing = sorted(n for n, v in found.items() if not v)
    if missing:
        raise StemAdoptionError(
            f'{folder} yields no stem for: {", ".join(missing)}. '
            f'A six stem folder is required; a partial one would produce a '
            f'partial fact sheet, which is worse than none.')
    ambiguous = sorted(n for n, v in found.items() if len(v) > 1)
    if ambiguous:
        raise StemAdoptionError(
            f'More than one file claims these stems in {folder}: '
            f'{", ".join(ambiguous)}. Rename or remove the extras rather than '
            f'letting the sheet pick one.')
    return {n: v[0] for n, v in found.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Prove it against the real corpus folders**

```bash
/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
import facts
for d in ('$HOME/Desktop/mydaiarytoyou!/Wrong Turn',
          '$HOME/Desktop/mydaiarytoyou!/The Danger of Caring'):
    print(d, sorted(facts.adopt_stems(d)))
"
```
Expected: both print all six stem names. Paste the output into the pull request.

- [ ] **Step 6: Commit**

```bash
git add scripts/facts.py tests/test_facts.py
git commit -m "feat: adopt an existing six stem folder whatever its naming"
```

---

### Task 3: Band limiting, key and tuning

**Files:**
- Create: `scripts/chords.py`
- Create: `tests/test_chords.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `band_limit(y, sr, low, high) -> np.ndarray`, `key_estimate(y_list, sr) -> dict` with keys `key`, `scores`, `margin`, `tuning_estimate(y, sr) -> dict` with keys `tuning`, `lowest_hz`, `margin_cents`, `TUNINGS`.

`key_estimate` takes a list of signals so the guitar and bass stems are summed
before analysis rather than analysed separately and argued about afterwards.

- [ ] **Step 1: Write the failing test**

Create `tests/test_chords.py`:

```python
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import chords as c

SR = 22050


def tone(freq, seconds=1.0, sr=SR):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def chord(freqs, seconds=1.0):
    return sum(tone(f, seconds) for f in freqs) / len(freqs)


class BandLimitTests(unittest.TestCase):
    def test_it_removes_energy_outside_the_band(self):
        y = tone(60) + tone(1000)
        out = c.band_limit(y, SR, 150, 2500)
        spectrum = np.abs(np.fft.rfft(out))
        freqs = np.fft.rfftfreq(len(out), 1 / SR)
        low = spectrum[(freqs > 40) & (freqs < 90)].max()
        keep = spectrum[(freqs > 900) & (freqs < 1100)].max()
        self.assertLess(low, keep * 0.1)

    def test_it_keeps_energy_inside_the_band(self):
        y = tone(1000)
        out = c.band_limit(y, SR, 150, 2500)
        self.assertGreater(np.abs(out).max(), 0.3 * np.abs(y).max())

    def test_a_band_wider_than_nyquist_is_clamped_not_an_error(self):
        out = c.band_limit(tone(1000), SR, 20, 40000)
        self.assertEqual(len(out), len(tone(1000)))


class KeyTests(unittest.TestCase):
    def test_it_names_the_key_of_a_synthetic_minor_progression(self):
        # F# minor: F#m, A, E, B built from their triads.
        progression = [(185.0, 220.0, 277.2), (220.0, 277.2, 329.6),
                       (164.8, 207.7, 246.9), (246.9, 311.1, 370.0)]
        y = np.concatenate([chord(f, 2.0) for f in progression] * 2)
        result = c.key_estimate([y], SR)
        self.assertEqual(result['key'], 'F# minor')

    def test_it_reports_a_margin_between_the_first_two_candidates(self):
        y = np.concatenate([chord((220.0, 261.6, 329.6), 2.0)] * 4)
        result = c.key_estimate([y], SR)
        self.assertGreaterEqual(result['margin'], 0.0)
        self.assertGreaterEqual(len(result['scores']), 3)

    def test_silence_has_no_key_rather_than_a_default_one(self):
        result = c.key_estimate([np.zeros(SR, dtype=np.float32)], SR)
        self.assertIsNone(result['key'])

    def test_two_stems_are_summed_not_analysed_separately(self):
        a = np.concatenate([chord((185.0, 220.0, 277.2), 2.0)] * 4)
        b = np.concatenate([tone(92.5, 2.0)] * 4)
        result = c.key_estimate([a, b], SR)
        self.assertIsNotNone(result['key'])


class TuningTests(unittest.TestCase):
    def test_it_names_drop_c_sharp_from_its_lowest_fundamental(self):
        y = np.concatenate([tone(34.65, 3.0), tone(69.3, 3.0)])
        result = c.tuning_estimate(y, SR)
        self.assertEqual(result['tuning'], 'drop C#')

    def test_it_names_standard_e_from_its_lowest_fundamental(self):
        y = np.concatenate([tone(41.2, 3.0), tone(82.4, 3.0)])
        self.assertEqual(c.tuning_estimate(y, SR)['tuning'], 'standard E')

    def test_it_distinguishes_neighbouring_tunings_a_semitone_apart(self):
        drop_d = c.tuning_estimate(np.concatenate([tone(36.71, 3.0)]), SR)
        drop_c = c.tuning_estimate(np.concatenate([tone(32.70, 3.0)]), SR)
        self.assertEqual(drop_d['tuning'], 'drop D')
        self.assertEqual(drop_c['tuning'], 'drop C')

    def test_no_sustained_low_fundamental_yields_no_tuning(self):
        result = c.tuning_estimate(np.zeros(SR * 2, dtype=np.float32), SR)
        self.assertIsNone(result['tuning'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chords'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/chords.py`. The tuning table is the load-bearing part: each entry
is the frequency of the lowest string, and the match is on cents distance so a
neighbouring tuning a semitone away cannot win by rounding.

```python
#!/usr/bin/env python3
"""Harmonic measurement over band limited stems.

Band limiting to 150 to 2500 Hz moved chord template fit from 0.680 to 0.695
on the reference guitar stem and the decision margin by about 11 percent. The
gain is small and bounded: it removes bleed from other instruments and cannot
touch time frequency smearing inside the target's own range. It is here
because it is free and because declaring the band makes the assumption
explicit.
"""
import math

import librosa
import numpy as np
from scipy import signal

NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                            2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                            2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Lowest string fundamental, in Hz, for each tuning the corpus might use.
TUNINGS = {
    'standard E': 82.41 / 2,
    'Eb standard': 77.78 / 2,
    'drop D': 73.42 / 2,
    'D standard': 73.42 / 2 * 2 ** (2 / 12),
    'drop C#': 69.30 / 2,
    'drop C': 65.41 / 2,
    'drop B': 61.74 / 2,
    'drop A#': 58.27 / 2,
}
SILENCE = 1e-6


def band_limit(y, sr, low, high):
    """A fourth order Butterworth band pass, clamped to the usable range."""
    nyquist = sr / 2.0
    low = max(1.0, float(low))
    high = min(float(high), nyquist * 0.99)
    if low >= high:
        return np.asarray(y, dtype=np.float32)
    sos = signal.butter(4, [low / nyquist, high / nyquist], btype='band', output='sos')
    return signal.sosfilt(sos, np.asarray(y, dtype=np.float64)).astype(np.float32)


def key_estimate(signals, sr, low=150, high=2500):
    """Correlate a summed, band limited chroma against major and minor templates.

    These are correlations against templates, not probabilities. Music built on
    other systems will not fit them, which is why the margin travels with the
    answer instead of being discarded.
    """
    stacked = [np.asarray(s, dtype=np.float32) for s in signals if s is not None]
    if not stacked:
        return {'key': None, 'scores': [], 'margin': 0.0}
    length = max(len(s) for s in stacked)
    summed = np.zeros(length, dtype=np.float32)
    for s in stacked:
        summed[:len(s)] += s
    y = band_limit(summed, sr, low, high)
    if np.max(np.abs(y)) < SILENCE:
        return {'key': None, 'scores': [], 'margin': 0.0}
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    avg = chroma.mean(axis=1)
    if np.std(avg) < 1e-8:
        return {'key': None, 'scores': [], 'margin': 0.0}
    scored = []
    for i, note in enumerate(NOTES):
        for label, profile in (('major', KRUMHANSL_MAJOR), ('minor', KRUMHANSL_MINOR)):
            value = float(np.corrcoef(avg, np.roll(profile, i))[0, 1])
            if math.isfinite(value):
                scored.append((value, f'{note} {label}'))
    if not scored:
        return {'key': None, 'scores': [], 'margin': 0.0}
    scored.sort(reverse=True)
    margin = scored[0][0] - scored[1][0] if len(scored) > 1 else 0.0
    return {'key': scored[0][1],
            'scores': [[name, round(v, 4)] for v, name in scored[:5]],
            'margin': round(float(margin), 4)}


def tuning_estimate(y, sr, high=200.0):
    """Name the tuning from the lowest sustained fundamental.

    Sustained is the point. A single low transient is a kick drum bleeding
    through, not a string, so the estimate reads the median of the per frame
    minimum fundamental rather than the outright lowest sample.
    """
    y = np.asarray(y, dtype=np.float32)
    if len(y) == 0 or np.max(np.abs(y)) < SILENCE:
        return {'tuning': None, 'lowest_hz': None, 'margin_cents': None}
    low = band_limit(y, sr, 25.0, high)
    f0 = librosa.yin(low.astype(np.float64), fmin=25.0, fmax=high, sr=sr,
                     frame_length=4096)
    f0 = f0[np.isfinite(f0)]
    f0 = f0[(f0 > 25.0) & (f0 < high)]
    if len(f0) < 8:
        return {'tuning': None, 'lowest_hz': None, 'margin_cents': None}
    lowest = float(np.percentile(f0, 10))
    ranked = sorted(
        (abs(1200 * math.log2(lowest / hz)), name) for name, hz in TUNINGS.items())
    best_cents, best_name = ranked[0]
    if best_cents > 60.0:
        return {'tuning': None, 'lowest_hz': round(lowest, 2),
                'margin_cents': round(best_cents, 1)}
    return {'tuning': best_name, 'lowest_hz': round(lowest, 2),
            'margin_cents': round(best_cents, 1)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: PASS, 11 tests

If `key_estimate` names the relative major instead of `F# minor`, do not loosen
the assertion. `chroma_cqt` over pure sine triads has no timbre to lean on, so
the fix is to build the fixture from triads with a second harmonic added, which
is what a real instrument supplies. Change the fixture, keep the assertion.

If `scipy` is missing, add `scipy>=1.11` to `requirements.txt` and install it
into the main checkout's venv. librosa already depends on it, so this should be
a no-op.

- [ ] **Step 5: Commit**

```bash
git add scripts/chords.py tests/test_chords.py
git commit -m "feat: band limited key and tuning estimates"
```

---

### Task 4: Chord sequence and harmonic rhythm

**Files:**
- Modify: `scripts/chords.py`
- Modify: `tests/test_chords.py`

**Interfaces:**
- Consumes: `band_limit` from Task 3.
- Produces: `chord_sequence(signals, sr, beat_times, bars_per_chord=1) -> list[dict]` where each entry is `{'start_s', 'end_s', 'root', 'quality', 'strength', 'third_present'}` with `quality` in `('major', 'minor', 'power')`, and `harmonic_rhythm(sequence) -> dict` with keys `chords_per_bar`, `median_chord_bars`, `label`.

`quality` is `'power'` when the third is not present. That is not a fallback, it
is the measurement: most distorted guitar is genuinely ambiguous between major
and minor, and the reference track reads 35 percent major against 21 percent
minor on the same root.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chords.py` before `if __name__`:

```python
class ChordSequenceTests(unittest.TestCase):
    def _beats(self, count, period=0.5):
        return np.arange(count) * period

    def test_it_reads_a_minor_triad_as_minor(self):
        y = chord((220.0, 261.6, 329.6), 4.0)
        seq = c.chord_sequence([y], SR, self._beats(8))
        self.assertTrue(seq)
        self.assertEqual(seq[0]['root'], 'A')
        self.assertEqual(seq[0]['quality'], 'minor')
        self.assertTrue(seq[0]['third_present'])

    def test_it_reads_a_root_and_fifth_as_power_not_as_a_guessed_third(self):
        y = chord((220.0, 329.6), 4.0)
        seq = c.chord_sequence([y], SR, self._beats(8))
        self.assertEqual(seq[0]['root'], 'A')
        self.assertEqual(seq[0]['quality'], 'power')
        self.assertFalse(seq[0]['third_present'])

    def test_a_held_chord_reports_a_slow_harmonic_rhythm(self):
        y = chord((220.0, 261.6, 329.6), 8.0)
        seq = c.chord_sequence([y], SR, self._beats(16))
        rhythm = c.harmonic_rhythm(seq)
        self.assertEqual(rhythm['label'], 'static')

    def test_a_chord_per_bar_reports_a_moderate_harmonic_rhythm(self):
        y = np.concatenate([chord((220.0, 261.6, 329.6), 2.0),
                            chord((246.9, 293.7, 370.0), 2.0),
                            chord((164.8, 207.7, 246.9), 2.0),
                            chord((185.0, 220.0, 277.2), 2.0)])
        seq = c.chord_sequence([y], SR, self._beats(16))
        rhythm = c.harmonic_rhythm(seq)
        self.assertIn(rhythm['label'], ('moderate', 'fast'))
        self.assertGreater(len(seq), 1)

    def test_no_beats_yields_no_sequence_rather_than_a_guess(self):
        self.assertEqual(c.chord_sequence([tone(220.0, 2.0)], SR, np.array([])), [])

    def test_harmonic_rhythm_of_an_empty_sequence_is_unknown(self):
        self.assertIsNone(c.harmonic_rhythm([])['label'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: FAIL, `AttributeError: module 'chords' has no attribute 'chord_sequence'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/chords.py`:

```python
THIRD_RATIO = 0.55   # a third must reach this share of the root's chroma to count
FIFTH_RATIO = 0.35


def _bar_windows(beat_times, beats_per_bar=4, bars_per_chord=1):
    beat_times = np.asarray(beat_times, dtype=float)
    step = beats_per_bar * bars_per_chord
    if len(beat_times) < 2:
        return []
    edges = list(beat_times[::step])
    if edges[-1] < beat_times[-1]:
        edges.append(float(beat_times[-1]))
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)
            if edges[i + 1] > edges[i]]


def chord_sequence(signals, sr, beat_times, bars_per_chord=1,
                   low=150, high=2500):
    """One chord per bar window, with the third reported rather than assumed."""
    windows = _bar_windows(beat_times, bars_per_chord=bars_per_chord)
    if not windows:
        return []
    stacked = [np.asarray(s, dtype=np.float32) for s in signals if s is not None]
    if not stacked:
        return []
    length = max(len(s) for s in stacked)
    summed = np.zeros(length, dtype=np.float32)
    for s in stacked:
        summed[:len(s)] += s
    y = band_limit(summed, sr, low, high)
    if np.max(np.abs(y)) < SILENCE:
        return []
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr)
    out = []
    for start, end in windows:
        mask = (times >= start) & (times < end)
        if not mask.any():
            continue
        profile = chroma[:, mask].mean(axis=1)
        total = float(profile.sum())
        if total <= 0:
            continue
        profile = profile / total
        root = int(np.argmax(profile))
        root_energy = float(profile[root])
        if root_energy <= 0:
            continue
        major_third = float(profile[(root + 4) % 12]) / root_energy
        minor_third = float(profile[(root + 3) % 12]) / root_energy
        fifth = float(profile[(root + 7) % 12]) / root_energy
        if max(major_third, minor_third) >= THIRD_RATIO:
            quality = 'major' if major_third >= minor_third else 'minor'
            third_present = True
        else:
            quality = 'power'
            third_present = False
        out.append({'start_s': round(float(start), 3),
                    'end_s': round(float(end), 3),
                    'root': NOTES[root], 'quality': quality,
                    'strength': round(root_energy, 4),
                    'third_present': third_present,
                    'fifth_present': bool(fifth >= FIFTH_RATIO)})
    return out


def harmonic_rhythm(sequence):
    """How often the chord actually changes, in bars."""
    if not sequence:
        return {'chords_per_bar': None, 'median_chord_bars': None, 'label': None}
    runs, current = [], 1
    for previous, entry in zip(sequence, sequence[1:]):
        same = (previous['root'] == entry['root']
                and previous['quality'] == entry['quality'])
        if same:
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    median = float(np.median(runs))
    if median >= 4:
        label = 'static'
    elif median >= 2:
        label = 'slow'
    elif median >= 1:
        label = 'moderate'
    else:
        label = 'fast'
    return {'chords_per_bar': round(1.0 / median, 3),
            'median_chord_bars': round(median, 2), 'label': label}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: PASS, 17 tests

`THIRD_RATIO` at 0.55 is a starting value, not a measured one. If the synthetic
triad tests fail, print the three ratios for the fixture chords and set the
constant from what you see, then record the observed numbers in a comment beside
it. Do not change the assertions.

- [ ] **Step 5: Commit**

```bash
git add scripts/chords.py tests/test_chords.py
git commit -m "feat: chord sequence that reports a power chord instead of guessing a third"
```

---

### Task 5: Assemble the sheet

**Files:**
- Modify: `scripts/facts.py`
- Modify: `tests/test_facts.py`

**Interfaces:**
- Consumes: `fact`, `adopt_stems`, `chords.*`, `tempo.tempo_family`, `stems.separate`, `measure.measure`.
- Produces: `fact_sheet(audio, stems_dir=None, cache_root=None) -> dict`, `SCHEMA = 'deconstruct-audio/facts/1'`, `scorable(sheet) -> dict`, `render_markdown(sheet) -> str`.

The sheet's shape:

```json
{
  "schema": "deconstruct-audio/facts/1",
  "generated_at": "2026-09-17T00:00:00Z",
  "source": {"path": "...", "sha256": "...", "duration_s": 138.8},
  "stems_from": "separated|adopted",
  "facts": {"tempo": {...}, "key": {...}}
}
```

`generated_at` is the only field allowed to differ between two runs on the same
audio. That is what makes rerun stability testable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_facts.py` before `if __name__`:

```python
import json
import subprocess


def synth_track(path, seconds=12):
    """A click plus a sustained low tone. No copyrighted audio in the repo."""
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'sine=frequency=110:duration={seconds}',
        '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}',
        '-filter_complex', '[0][1]amix=inputs=2',
        '-ar', '22050', '-ac', '1', str(path)], check=True)


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.audio = self.dir / 'track.wav'
        synth_track(self.audio)
        self.stems = self.dir / 'stems'
        self.stems.mkdir()
        for name in ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other'):
            target = self.stems / f'{name}.wav'
            target.write_bytes(self.audio.read_bytes())

    def test_every_fact_carries_method_and_confidence(self):
        sheet = f.fact_sheet(self.audio, stems_dir=self.stems)
        self.assertTrue(sheet['facts'])
        for axis, entry in sheet['facts'].items():
            self.assertTrue(entry['method'], f'{axis} has no method')
            self.assertIn(entry['confidence'], f.CONFIDENCE, axis)
            self.assertIn(entry['suno_actionable'], f.ACTIONABLE, axis)

    def test_the_sheet_names_its_schema_and_its_source(self):
        sheet = f.fact_sheet(self.audio, stems_dir=self.stems)
        self.assertEqual(sheet['schema'], f.SCHEMA)
        self.assertEqual(len(sheet['source']['sha256']), 64)
        self.assertEqual(sheet['stems_from'], 'adopted')

    def test_two_runs_on_the_same_audio_agree_apart_from_the_timestamp(self):
        first = f.fact_sheet(self.audio, stems_dir=self.stems)
        second = f.fact_sheet(self.audio, stems_dir=self.stems)
        first.pop('generated_at')
        second.pop('generated_at')
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_the_projection_uses_compare_s_own_axis_names(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import compare
        sheet = f.fact_sheet(self.audio, stems_dir=self.stems)
        projected = f.scorable(sheet)
        self.assertTrue(projected)
        for axis in projected:
            self.assertIn(axis, compare.GATES, f'{axis} is not a compare axis')

    def test_an_unknown_axis_is_left_out_of_the_projection_not_passed_as_null(self):
        sheet = f.fact_sheet(self.audio, stems_dir=self.stems)
        sheet['facts']['key'] = f.fact(None, 'name', 'guitar', ['chroma'],
                                       'UNKNOWN', 'direct')
        self.assertNotIn('key', f.scorable(sheet))

    def test_the_markdown_names_every_axis_and_its_grade(self):
        sheet = f.fact_sheet(self.audio, stems_dir=self.stems)
        text = f.render_markdown(sheet)
        for axis in sheet['facts']:
            self.assertIn(axis, text)
        self.assertIn('KNOW', text + 'KNOW')

    def test_a_partial_stem_folder_refuses_rather_than_emitting_a_partial_sheet(self):
        (self.stems / 'guitar.wav').unlink()
        with self.assertRaises(f.StemAdoptionError):
            f.fact_sheet(self.audio, stems_dir=self.stems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL, `AttributeError: module 'facts' has no attribute 'fact_sheet'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/facts.py`. Every axis is one small function so a failure names
the axis it came from, and every one of them returns a `fact()`, which is what
makes the G2 gate structural rather than a review habit.

```python
import datetime as _dt
import hashlib

import numpy as np
import librosa
import soundfile as sf

import chords as chords_mod
import measure as measure_mod
import stems as stems_mod
import tempo as tempo_mod

SCHEMA = 'deconstruct-audio/facts/1'
LOW_END_HZ = 150.0
AIR_HZ = 5000.0
ACTIVE_DB = -40.0

PROJECTION = {
    'tempo': ('tempo_bpm', lambda v: v),
    'key': ('key', lambda v: v),
    'tuning': ('tuning', lambda v: v),
    'intro_seconds': ('intro_seconds', lambda v: v),
    'sections': ('section_count', lambda v: v['count']),
    'loudness': ('lra_lu', lambda v: v['lra_lu']),
    'spectral_balance': ('low_end_share', lambda v: v['low_end_share']),
    'lead_register': ('lead_register_midi', lambda v: v['median_midi']),
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _load(path, sr=22050):
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y


def _register(y, sr, fmin, fmax, stem, band):
    """Median and spread of a pitch track, in MIDI note numbers."""
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-6:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', 'direct',
                    band_hz=band, note='stem is silent')
    f0 = librosa.yin(y.astype(np.float64), fmin=fmin, fmax=fmax, sr=sr)
    f0 = f0[np.isfinite(f0) & (f0 > fmin) & (f0 < fmax)]
    if len(f0) < 16:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', 'direct',
                    band_hz=band, note='no stable pitch track')
    midi = librosa.hz_to_midi(f0)
    value = {'median_midi': round(float(np.median(midi)), 2),
             'p10_midi': round(float(np.percentile(midi, 10)), 2),
             'p90_midi': round(float(np.percentile(midi, 90)), 2)}
    return fact(value, 'midi', stem, ['yin'], 'INFER', 'direct', band_hz=band,
                note='single method pitch track over a separated stem')
```

The remaining axis builders follow the same pattern. Write them in this order,
running the suite after each so a break names its own axis:

`_tempo_fact` wraps `tempo_mod.tempo_family(paths['drums'])` and carries that
function's own `confidence` straight through, because that grading already
exists and re-deriving it here would be a second opinion nobody asked for.

`_key_fact` and `_chords_fact` call `chords_mod.key_estimate` and
`chords_mod.chord_sequence` on the guitar and bass signals, band 150 to 2500.
Grade `key` as `KNOW` when the margin is at least 0.05 and the chord sequence's
most common root agrees with the key's tonic, `INFER` when only one of those
holds, `UNKNOWN` when the estimate returned no key.

`_tuning_fact` calls `chords_mod.tuning_estimate` on the bass stem summed with
the guitar stem. Grade `KNOW` when `margin_cents` is under 25 and the result
agrees on both stems measured separately, otherwise `INFER`, and `UNKNOWN` when
the estimate returned no tuning.

`_sections_fact` reuses `measure_mod.measure`'s `segment_boundaries_s` on the
mix and emits `{'count': n, 'boundaries_s': [...]}`. Grade `INFER` always: these
are clustering suggestions, not verified verses and choruses, and the parent
spec is explicit that they must stay labelled that way.

`_intro_fact` is the one axis with no existing implementation to lean on. Its
definition: for each 1 second window, count the stems whose RMS exceeds
`ACTIVE_DB`; the intro ends at the first window where that count first reaches
its track wide maximum; snap that time to the nearest section boundary within
4 seconds if one exists. Grade `INFER` when the snap moved it, `KNOW` when the
density transition and a section boundary already agreed within 1 second.

`_loudness_fact` reuses `measure_mod.measure`'s `integrated_lufs`, `lra_lu` and
`true_peak_dbtp`, graded `KNOW`, method `['ebur128']`. These come from ffmpeg's
BS.1770 implementation and are the one place in this sheet where a single method
is genuinely authoritative.

`_spectral_fact` computes, on the mix, the share of total spectral energy below
`LOW_END_HZ`, the spectral centroid, and the share above `AIR_HZ`, as
`{'low_end_share': pct, 'centroid_hz': hz, 'air_share': pct}`, graded `KNOW`,
method `['stft-band-share']`.

`_dynamic_arc_fact` reuses `measure_mod.measure`'s `rms_db_per_4s`, normalised
to the track's own peak, graded `KNOW`, actionable `indirect`.

`_note_density_fact` is the guitar stem's onset rate divided by the primary
tempo's beats per second, graded `INFER`, actionable `indirect`.

`_meter_fact` autocorrelates the drums onset envelope at the beat period and
reports the strongest grouping of 3 or 4. Grade `INFER`; published benchmarks
put meter identification well below the other axes and this is one method.

`_vocal_register_fact` is `_register(vocals, sr, 70, 1200, 'vocals', [70, 1200])`
with actionable `direct`.

`_lead_register_fact` is `_register(band_limit(guitar, 70, 1400), sr, 70, 1400,
'guitar', [70, 1400])` with actionable `direct`. This axis exists because four
generation cycles were spent discovering by ear that an intro had arrived an
octave high.

Then the assembler:

```python
def fact_sheet(audio, stems_dir=None, cache_root=None):
    audio = Path(audio)
    if stems_dir is not None:
        paths = adopt_stems(stems_dir)
        origin = 'adopted'
    else:
        if cache_root is None:
            raise FactError('separating stems needs a cache_root')
        paths = stems_mod.separate(audio, cache_root)
        origin = 'separated'
    sr = 22050
    loaded = {name: _load(path, sr) for name, path in paths.items()}
    mix = _load(audio, sr)
    local = measure_mod.measure(str(audio))
    built = {}
    for name, builder in (
            ('tempo', _tempo_fact), ('meter', _meter_fact), ('key', _key_fact),
            ('chords', _chords_fact), ('harmonic_rhythm', _harmonic_rhythm_fact),
            ('sections', _sections_fact), ('intro_seconds', _intro_fact),
            ('note_density', _note_density_fact),
            ('lead_register', _lead_register_fact), ('tuning', _tuning_fact),
            ('loudness', _loudness_fact), ('spectral_balance', _spectral_fact),
            ('dynamic_arc', _dynamic_arc_fact),
            ('vocal_register', _vocal_register_fact)):
        built[name] = builder(paths, loaded, mix, sr, local, built)
    return {
        'schema': SCHEMA,
        'generated_at': _dt.datetime.now(_dt.timezone.utc)
                           .replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': {'path': str(audio), 'sha256': _sha256(audio),
                   'duration_s': local['duration_s']},
        'stems_from': origin,
        'facts': built,
    }


def scorable(sheet):
    """Project the sheet onto the axis names compare already scores.

    An UNKNOWN axis is omitted rather than passed as null. compare reports an
    absent axis as UNKNOWN and counts it under UNMEASURED, so omission gives
    the honest verdict and null would be a second way to say the same thing.
    """
    out = {}
    for axis, (target, pick) in PROJECTION.items():
        entry = sheet['facts'].get(axis)
        if not entry or entry['confidence'] == 'UNKNOWN' or entry['value'] is None:
            continue
        try:
            out[target] = pick(entry['value'])
        except (KeyError, TypeError):
            continue
    return out


def render_markdown(sheet):
    lines = ['# Fact sheet', '',
             f'Source: `{sheet["source"]["path"]}`',
             f'Duration: {sheet["source"]["duration_s"]} s',
             f'Stems: {sheet["stems_from"]}', '',
             '| Axis | Value | Unit | Stem | Band Hz | Confidence | Method | Suno |',
             '|---|---|---|---|---|---|---|---|']
    for axis, entry in sheet['facts'].items():
        band = '' if entry['band_hz'] is None else \
            f'{entry["band_hz"][0]} to {entry["band_hz"][1]}'
        lines.append(
            f'| {axis} | {entry["value"]} | {entry["unit"]} | {entry["stem"]} | '
            f'{band} | {entry["confidence"]} | {", ".join(entry["method"])} | '
            f'{entry["suno_actionable"]} |')
    notes = [(a, e['note']) for a, e in sheet['facts'].items() if e['note']]
    if notes:
        lines += ['', '## Notes', '']
        lines += [f'- **{a}**: {n}' for a, n in notes]
    return '\n'.join(lines) + '\n'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 20 tests

If `test_two_runs_on_the_same_audio_agree_apart_from_the_timestamp` fails, do not
round harder until it passes. Find which axis moved, name the stochastic step
inside it, and seed it. An axis that cannot be made stable is graded `UNKNOWN`
with a note saying why, which is a real answer. Silent rounding is not.

- [ ] **Step 5: Commit**

```bash
git add scripts/facts.py tests/test_facts.py
git commit -m "feat: assemble the graded fact sheet"
```

---

### Task 6: The tuning axis on compare

**Files:**
- Modify: `scripts/compare.py`
- Modify: `tests/test_compare.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a `tuning` entry in `compare.GATES`, and `tuning_verdict(reference, candidate) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compare.py` before `if __name__`:

```python
class TuningAxisTests(unittest.TestCase):
    def test_the_same_tuning_passes(self):
        result = c.score(dict(REFERENCE, tuning='drop C#'),
                         dict(REFERENCE, tuning='drop C#'))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'PASS')

    def test_an_enharmonic_spelling_is_the_same_tuning(self):
        result = c.score(dict(REFERENCE, tuning='drop C#'),
                         dict(REFERENCE, tuning='Drop Db'))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'PASS')

    def test_a_neighbouring_tuning_fails_rather_than_warning(self):
        result = c.score(dict(REFERENCE, tuning='drop C#'),
                         dict(REFERENCE, tuning='drop D'))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'FAIL')

    def test_an_unmeasured_tuning_is_unknown_not_a_pass(self):
        result = c.score(dict(REFERENCE, tuning='drop C#'), dict(REFERENCE))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'UNKNOWN')

    def test_the_existing_seven_axes_are_untouched(self):
        result = c.score(REFERENCE, dict(REFERENCE))
        self.assertEqual(result['verdict'], 'PASS')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_compare -v`
Expected: FAIL, `StopIteration` on the missing tuning axis

- [ ] **Step 3: Write minimal implementation**

In `scripts/compare.py`, add to `GATES`:

```python
    'tuning': {'kind': 'tuning', 'label': 'Tuning'},
```

Add beside `key_verdict`, keeping the module's no-import property intact:

```python
def normalise_tuning(value):
    """Fold spelling and enharmonics so drop C# and Drop Db are one answer."""
    if not isinstance(value, str):
        return None
    text = ' '.join(value.strip().split()).lower()
    if not text:
        return None
    parts = text.split()
    tail = parts[-1].upper()
    parts[-1] = FLATS_TO_SHARPS.get(tail, tail)
    return ' '.join(parts)


def tuning_verdict(reference, candidate):
    a, b = normalise_tuning(reference), normalise_tuning(candidate)
    if a is None or b is None:
        return 'UNKNOWN', 'tuning not parseable'
    if a == b:
        return 'PASS', 'same tuning'
    return 'FAIL', f'{candidate} is not {reference}'
```

And in `score`, beside the `key` branch:

```python
        elif gate['kind'] == 'tuning':
            verdict, note = tuning_verdict(ref, cand)
            delta = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests -v`
Expected: OK, no regression in the existing compare tests

- [ ] **Step 5: Commit**

```bash
git add scripts/compare.py tests/test_compare.py
git commit -m "feat: score tuning, the axis the bar named and compare could not read"
```

---

### Task 7: The facts command

**Files:**
- Modify: `scripts/deconstruct.py`

**Interfaces:**
- Consumes: `facts.fact_sheet`, `facts.scorable`, `facts.render_markdown`.
- Produces: CLI `facts <audio> [--stems DIR] [--out DIR]`, printing `FACTS_WRITTEN=<path>`.

- [ ] **Step 1: Add the import**

Below the existing imports in `scripts/deconstruct.py`:

```python
import facts as facts_mod
```

- [ ] **Step 2: Add the command function**

Above `def main():`:

```python
def cmd_facts(args):
    out = args.out or Path.cwd()
    out.mkdir(parents=True, exist_ok=True)
    sheet = facts_mod.fact_sheet(args.audio, stems_dir=args.stems,
                                 cache_root=config_dir() / 'cache')
    (out / 'facts.json').write_text(
        json.dumps(sheet, indent=2, allow_nan=False), encoding='utf-8')
    (out / 'facts.md').write_text(
        facts_mod.render_markdown(sheet), encoding='utf-8')
    (out / 'scorable.json').write_text(
        json.dumps(facts_mod.scorable(sheet), indent=2, allow_nan=False),
        encoding='utf-8')
    graded = {}
    for entry in sheet['facts'].values():
        graded[entry['confidence']] = graded.get(entry['confidence'], 0) + 1
    print(f'FACTS_WRITTEN={out / "facts.json"}')
    for grade in ('KNOW', 'INFER', 'UNKNOWN'):
        print(f'{grade}={graded.get(grade, 0)}')
```

- [ ] **Step 3: Register and dispatch**

With the other parsers in `main()`:

```python
    fp = sub.add_parser('facts')
    fp.add_argument('audio', type=Path)
    fp.add_argument('--stems', type=Path, default=None,
                    help='Adopt an existing six stem folder instead of separating.')
    fp.add_argument('--out', type=Path, default=None)
```

With the other branches:

```python
    elif args.command == 'facts':
        cmd_facts(args)
```

- [ ] **Step 4: Verify the command exists**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python scripts/deconstruct.py facts --help`
Expected: usage text showing `--stems`

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: the facts command"
```

---

### Task 8: The corpus check, and the entry bar

**Files:**
- Create: `scripts/corpus_check.py`
- Create: `<desk>/evidence/known-murder-she-wrote.json`

The desk is `/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17`.

**Interfaces:**
- Consumes: `facts.fact_sheet`, `facts.scorable`.
- Produces: a script printing one `TRACK=<name> STABLE=<yes|no>` line per track and a final `CORPUS_STABLE=<n>/3`.

- [ ] **Step 1: Write the known values file**

Create `<desk>/evidence/known-murder-she-wrote.json`:

```json
{
  "tempo_bpm": 80.7,
  "key": "F# minor",
  "tuning": "drop C#",
  "section_count": 7,
  "intro_seconds": 12.1,
  "low_end_share": 16.4
}
```

These are the user's known values. `lra_lu` and `lead_register_midi` are absent
on purpose: they are not among the known six, and inventing a reference figure
so that an axis reports PASS would be the exact defect this project exists to
stop. `compare` counts them under `UNMEASURED=` and that is the honest reading.

- [ ] **Step 2: Write the corpus script**

Create `scripts/corpus_check.py`:

```python
#!/usr/bin/env python3
"""Run every corpus track twice and report whether the sheet held still.

Stability is a gate rather than an assumption because two of the measurement
libraries have stochastic paths, and a fact sheet that moves between runs
cannot support a comparison.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts as facts_mod

HOME = Path(os.path.expanduser('~'))
CORPUS = [
    {'name': 'Murder, She Wrote',
     'audio': HOME / 'Downloads' /
              'mydiarytoyou! - Murder, She Wrote (Official Visualizer).mp3',
     'stems': None},
    {'name': 'The Danger of Caring',
     'audio': HOME / 'Desktop' / 'mydaiarytoyou!' / 'The Danger of Caring' /
              'mydiarytoyou! - The Danger of Caring (Official Visualizer).mp3',
     'stems': HOME / 'Desktop' / 'mydaiarytoyou!' / 'The Danger of Caring'},
    {'name': 'Wrong Turn',
     'audio': HOME / 'Desktop' / 'mydaiarytoyou!' / 'Wrong Turn' /
              'mydiarytoyou! - Wrong Turn (Official Visualizer).mp3',
     'stems': HOME / 'Desktop' / 'mydaiarytoyou!' / 'Wrong Turn'},
]
CACHE = HOME / '.config' / 'deconstruct-audio' / 'cache'


def stable(sheet_a, sheet_b):
    a, b = dict(sheet_a), dict(sheet_b)
    a.pop('generated_at', None)
    b.pop('generated_at', None)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rerun', action='store_true',
                        help='Measure each track twice and compare.')
    parser.add_argument('--out', type=Path, default=None,
                        help='Write each track\'s facts.json here.')
    args = parser.parse_args()

    held = 0
    for track in CORPUS:
        if not track['audio'].exists():
            print(f'TRACK={track["name"]} STABLE=no MISSING={track["audio"]}')
            continue
        first = facts_mod.fact_sheet(track['audio'], stems_dir=track['stems'],
                                     cache_root=CACHE)
        if args.rerun:
            second = facts_mod.fact_sheet(track['audio'],
                                          stems_dir=track['stems'],
                                          cache_root=CACHE)
            ok = stable(first, second)
        else:
            ok = True
        held += 1 if ok else 0
        print(f'TRACK={track["name"]} STABLE={"yes" if ok else "no"} '
              f'{json.dumps(facts_mod.scorable(first), sort_keys=True)}')
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            slug = track['name'].lower().replace(',', '').replace(' ', '-')
            (args.out / f'facts-{slug}.json').write_text(
                json.dumps(first, indent=2, allow_nan=False), encoding='utf-8')
            (args.out / f'scorable-{slug}.json').write_text(
                json.dumps(facts_mod.scorable(first), indent=2, allow_nan=False),
                encoding='utf-8')
    print(f'CORPUS_STABLE={held}/{len(CORPUS)}')
    return 0 if held == len(CORPUS) else 2


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 3: Run the corpus**

```bash
/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python scripts/corpus_check.py --rerun \
  --out /Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17/evidence
```
Expected: `CORPUS_STABLE=3/3`

- [ ] **Step 4: Score the reference against its known values**

```bash
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python scripts/deconstruct.py \
  compare $DESK/evidence/known-murder-she-wrote.json \
          $DESK/evidence/scorable-murder-she-wrote.json
```
Expected: `VERDICT=PASS`

This is the entry bar. If an axis fails, report the actual delta rather than
adjusting the gate. The gates in `compare` were set by the parent spec and
moving one to turn a failure into a pass is the single most damaging thing that
can be done to this project.

- [ ] **Step 5: Commit**

```bash
git add scripts/corpus_check.py
git commit -m "feat: run the corpus twice and prove the sheet holds still"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`

- [ ] **Step 1: Add `facts` to the command table in `README.md`**

In the command table, after the `tempo` row:

```markdown
| `facts <file>` | Measures every axis on the stem that carries it and writes a fact sheet where each value states its method, its frequency band and a confidence grade. `--stems DIR` adopts an existing six stem folder instead of separating |
```

And in the code block above the table:

```bash
.venv/bin/python scripts/deconstruct.py facts /path/to/track.wav --stems /path/to/stems
```

- [ ] **Step 2: Add a section to `README.md` under "Measuring instead of describing"**

```markdown
`facts` is the measurement path's output. It reads each property from the stem
that carries it, declares the frequency band it read, and grades every value
`KNOW`, `INFER` or `UNKNOWN`. A value the pipeline could not resolve is emitted
as `UNKNOWN` rather than filled in, and constructing a fact without a method or
a grade raises rather than producing one. `scorable.json` beside it projects the
sheet onto the axes `compare` scores, so a reference and a candidate go through
the same projection and cannot be compared on different terms by accident.
```

- [ ] **Step 3: Add the command to `SKILL.md`**

Follow the format the existing commands use in that file, describing `facts`,
its `--stems` flag, and the rule that the agent never promotes an `UNKNOWN` axis
to a stated fact when writing prose from the sheet.

- [ ] **Step 4: Run the full suite one more time**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add README.md SKILL.md
git commit -m "docs: the facts command"
```

---

## Self-Review

**Spec coverage.** The Fact object is Task 1. Stem adoption, which the corpus
needs, is Task 2. The axes table is Tasks 3, 4 and 5, with band declarations
carried on every fact. The projection onto compare is Task 5. The tuning axis
compare was missing is Task 6. The command is Task 7. The entry bar, meaning the
corpus rerun and the score against known values, is Task 8. Documentation is
Task 9.

Not covered here by design, because each has its own plan and its own worktree:
the MIDI emitter, the research branch and the Brain wiring.

**Placeholders.** Task 5 describes eleven axis builders in prose rather than
giving each one's body. That is a deliberate and declared boundary, not a
placeholder: each builder's interface, grading rule, stem, band and method list
is stated exactly, and the `fact()` contract from Task 1 makes a wrong one fail
loudly. The numeric thresholds that cannot be known before measuring real audio,
`THIRD_RATIO` in Task 4 and the intro density rule in Task 5, are called out as
measure-then-set steps with an explicit instruction not to loosen an assertion
instead.

**Type consistency.** `fact()` returns the dict every axis builder returns and
`render_markdown` and `scorable` read. `adopt_stems` returns `dict[str, Path]`,
the same shape `stems.separate` returns, so `fact_sheet` consumes either without
branching beyond the origin label. `chord_sequence` entries carry `third_present`,
which Task 4 tests and the MIDI plan consumes. `PROJECTION` targets are checked
against `compare.GATES` by a test rather than by eye.
