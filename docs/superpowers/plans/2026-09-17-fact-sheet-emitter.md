# Fact Sheet Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an audio file plus its six stems into a fact sheet where every musical property carries the method that produced it and a confidence grade, and prove it on a three-track corpus against known ground truth.

**Architecture:** A new `facts.py` owns the `Fact` shape and assembles the sheet. A new `chords.py` owns the harmonic measurements that need band-limited stems. `compare.py` gains one axis. `deconstruct.py` gains one thin command. A `corpus_check.py` runs the whole corpus twice and diffs, which is how rerun stability becomes a gate rather than a hope.

**Tech Stack:** Python 3.10+, librosa, numpy, scipy, soundfile, ffmpeg, demucs (all installed).

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

**Revision:** This is revision 2. Revision 1 was reviewed by an independent critic
and returned LOSE: executed as written it missed three of six bar axes, broke five
existing tests, and violated two repo invariants. Every number in this revision
that fixes one of those was measured on the real corpus first, and the evidence
sits in `/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17/evidence/`:
`CRITIC-plan-review.md`, `MEASUREMENT-DECISIONS.md`, `SECTIONS-research.md`.

## Global Constraints

**Every declared test count in this plan has been wrong at least once.** Three
revisions in, the counts are the most frequently defective thing in the
document. They are kept because a count is a tripwire for a silently dropped
test, but treat them as a tripwire, not as truth: run the suite, and if your
number disagrees, say so in the pull request with the output rather than
editing a test to reach the number.


- Python 3.10 or newer. `ffmpeg` and `ffprobe` on `PATH`.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`. Worktrees do not build their own venv; `AGENTS.md` now says so.
- Baseline is 97 tests, OK, one skipped. Any drop is a regression.
- Commands orchestrate and print a machine-readable result line. Service modules own the reusable how. This split is an invariant in `AGENTS.md`.
- **Never import a librosa-pulling module at the top of `deconstruct.py`.** There is a comment at `scripts/deconstruct.py:22` explaining why: `doctor` exists to diagnose an incomplete install, and a module-level import makes it traceback before the handler that hides local paths. Import inside the command.
- **Use `secure_config_dir()`, not `config_dir()`, anywhere a directory gets created.** `scripts/deconstruct.py:67` documents the bug that made this necessary: `mkdir(parents=True, mode=)` sets the mode on the leaf only, so creating a cache underneath left the folder that later holds `credentials.json` at 0755 permanently.
- Every emitted measurement carries its method and a confidence grade of `KNOW`, `INFER`, or `UNKNOWN`. Construction raises otherwise.
- **`UNKNOWN` is for a method that genuinely could not resolve. It is never for a value that resolved and missed a gate.** The critic found that `scorable` omitting `UNKNOWN` axes, plus `compare` scoring only axes present on both sides, lets a sheet grade its failures `UNKNOWN` and print `VERDICT=PASS` having measured nothing. Task 8 closes that by asserting the measured count, not just the verdict.
- Every numeric value written into the sheet passes through `float()` or `int()`. `json.dumps(allow_nan=False)` raises on a stray `np.float32`, verified.
- No API key in a command line, log, error message, test fixture, or commit.
- No copyrighted audio in the repository. Tests use synthetic audio.
- Nothing in this plan makes a network call. `facts` is an offline command.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## The bar this plan is measured against

Five axes, each scored against ground truth established outside this pipeline:

| Axis | Known | Gate |
|---|---|---|
| `tempo_bpm` | 80.7 | within 5 percent |
| `key` | F# minor | exact |
| `tuning` | drop C# | exact |
| `intro_seconds` | 12.1 | within 3 s |
| `lra_lu` | 4.1 | within 1.5 LU |

Two axes the original bar named are deliberately **not** on it, each for a stated reason:

**`section_count`.** Sixteen segmentation methods were run at one fixed configuration declared before comparing against the answer key. None generalises across the three tracks. The best candidate returns 7, 6 and 10, matches only 4 of 6 known boundaries, and was selected by noticing which row of a table hit 7, which is selection on the one track that has an answer. It self-assessed at 50 percent confidence on a fresh track. The axis is graded `UNKNOWN` and the sheet emits boundaries without claiming a count. Evidence: `SECTIONS-research.md`.

**`low_end_share`.** The figure 16.4 percent could not be reproduced by any of eight readings of "share of spectral energy below 150 Hz", which span 10.83 to 58.01 depending on magnitude against power, global against per frame, and crossover. Rather than pick the reading that lands inside the gate, which would be choosing a definition to manufacture a pass, the definition is pinned and both sides are measured with it. The reference becomes this pipeline's own measurement of the reference track. Evidence: `MEASUREMENT-DECISIONS.md`.

Both of those, plus `lead_register_midi`, still matter at the **exit bar**, where a generated track is scored against this pipeline's own measurement of the reference. That is the parent spec's own rule, that both sides be measured the same way, and it is the only place a figure this pipeline cannot reproduce has no role.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/facts.py` (create) | The `Fact` constructor and its validation, stem adoption, sheet assembly, the projection onto compare's axes, markdown rendering. Knows nothing about the CLI. |
| `scripts/chords.py` (create) | Band limiting, key estimate, chord sequence, harmonic rhythm, tuning estimate. Pure measurement over arrays. |
| `scripts/compare.py` (modify) | One new axis, `tuning`. |
| `scripts/deconstruct.py` (modify) | The `facts` command. |
| `scripts/corpus_check.py` (create) | Runs the corpus, reruns it, diffs. |
| `tests/test_facts.py` (create) | Fact validation, stem adoption, projection, rerun stability. |
| `tests/test_chords.py` (create) | Band limiting, key, chords, tuning. |
| `tests/test_compare.py` (modify) | The tuning axis, and the four count assertions it moves. |

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

    def test_a_container_holding_a_flag_is_still_a_measurement(self):
        # instrumentation carries one `active` per stem and a chord entry
        # carries `third_present`. Revision 2 rejected every boolean at every
        # depth and the sheet raised on its third builder for every track.
        result = self.good(value={'piano': {'rms_db': -58.29, 'active': False}})
        self.assertFalse(result['value']['piano']['active'])

    def test_a_bare_boolean_is_still_refused(self):
        with self.assertRaises(f.FactError):
            self.good(value=True)

    def test_a_numpy_scalar_is_coerced_so_json_can_serialise_it(self):
        import json
        import numpy as np
        result = self.good(value=np.float32(80.7))
        self.assertIsInstance(result['value'], float)
        json.dumps(result, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
```

The last test exists because `json.dumps(..., allow_nan=False)` raises
`TypeError` on `np.float32` while accepting `np.float64`, so a single forgotten
`float()` in one axis builder crashes the whole command at write time. Coercing
in one place is cheaper than remembering fourteen times.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'facts'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/facts.py`:

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


def _plain(value):
    """A JSON-safe copy of value, with numpy scalars coerced.

    json.dumps(allow_nan=False) accepts np.float64 and raises TypeError on
    np.float32, so an axis that forgets one float() crashes the command at
    write time rather than where the mistake was made. Coercing once here
    costs nothing and removes fourteen chances to forget.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return int(value)
    return value


def _finite(value):
    """True when value is a real measurement rather than a placeholder.

    A boolean INSIDE a container is a flag, not a scalar posing as a
    measurement: `instrumentation` carries one `active` per stem and a chord
    entry carries `third_present`. Revision 2 rejected every boolean at every
    depth, which made the third builder raise on every track. A bare boolean
    is still refused, by fact() before this function is reached.
    """
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(v) for v in value)
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
    if isinstance(value, bool):
        raise FactError('a bare boolean is a flag, not a measurement')
    value = _plain(value)
    if value is not None and not _finite(value):
        raise FactError(f'{value!r} is not a measurement')
    if band_hz is not None:
        if not isinstance(band_hz, (list, tuple)) or len(band_hz) != 2:
            raise FactError('band_hz must be a [low, high] pair or None')
        band_hz = [_plain(band_hz[0]), _plain(band_hz[1])]
    return {'value': value, 'unit': unit, 'stem': stem, 'band_hz': band_hz,
            'method': list(method), 'confidence': confidence,
            'suno_actionable': suno_actionable, 'note': note}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 11 tests

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
- Consumes: `stems.STEM_NAMES`.
- Produces: `adopt_stems(folder) -> dict[str, Path]`, `StemAdoptionError`.

Why this exists: the two supplied corpus stem sets are named
`1_<title>_(Drums).wav`, which is not demucs output. Without adoption the corpus
is one track, and a pipeline validated on one track proves only that it was
tuned to that track.

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

    def _six(self, template='1_Some Track_({}).wav'):
        return [template.format(n.title()) for n in
                ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')]

    def test_adopts_a_supplied_six_stem_folder(self):
        self._write(self._six())
        result = f.adopt_stems(self.dir)
        self.assertEqual(set(result), {'drums', 'bass', 'guitar',
                                       'piano', 'vocals', 'other'})
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))

    def test_adopts_plain_demucs_names(self):
        self._write([f'{n}.wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        self.assertEqual(set(f.adopt_stems(self.dir)),
                         {'drums', 'bass', 'guitar', 'piano', 'vocals', 'other'})

    def test_the_source_mix_sitting_beside_the_stems_is_ignored(self):
        self._write(self._six() + ['Some Track (Official Visualizer).mp3'])
        self.assertEqual(len(f.adopt_stems(self.dir)), 6)

    def test_a_partial_folder_is_an_error_not_a_partial_sheet(self):
        self._write(['1_x_(Drums).wav', '1_x_(Bass).wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        for missing in ('guitar', 'piano', 'vocals', 'other'):
            self.assertIn(missing, str(caught.exception))

    def test_two_files_using_the_same_tagged_form_is_an_error(self):
        self._write(self._six())
        self._write(['2_Some Track_(Drums).wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        self.assertIn('drums', str(caught.exception))

    def test_a_tagged_name_beats_a_loose_one_rather_than_being_ambiguous(self):
        # Deliberate: (Drums) is a more specific claim than a filename that
        # merely contains the word. Preferring it is the whole reason the
        # tagged pass runs first, and treating this as ambiguous would reject
        # a folder that is not actually ambiguous.
        self._write(self._six() + ['drums_scratch_take.wav'])
        result = f.adopt_stems(self.dir)
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))

    def test_two_untagged_files_claiming_one_stem_is_an_error(self):
        self._write([f'{n}.wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        self._write(['drums take two.wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        self.assertIn('drums', str(caught.exception))

    def test_other_does_not_swallow_a_filename_containing_the_word(self):
        self._write(self._six('1_Another Brother_({}).wav'))
        result = f.adopt_stems(self.dir)
        self.assertTrue(result['other'].name.endswith('(Other).wav'))
```

Revision note. Revision 1 asserted that a stray `drums_alt.wav` beside a tagged
`(Drums)` file must raise. The critic proved that test fails against the
implementation, and on inspection the test was the thing that was wrong: a
parenthesised tag is a more specific claim than a filename that happens to
contain the word, and preferring it is exactly why the tagged pass runs first.
The two tests above now say that plainly, one for each pass.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL, `AttributeError: module 'facts' has no attribute 'adopt_stems'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/facts.py`:

```python
import re
from pathlib import Path

import stems

AUDIO_SUFFIXES = ('.wav', '.flac', '.mp3', '.aif', '.aiff')


class StemAdoptionError(Exception):
    pass


def _match(names, pattern):
    return {n: [p for p in names if pattern(n, p.name.lower())]
            for n in stems.STEM_NAMES}


def adopt_stems(folder):
    """Resolve an existing folder of six stems, however its files are named.

    Two passes, tagged first. A name carrying `(Drums)` is claiming to be the
    drums stem; a name that merely contains the word might be the source mix,
    a scratch take, or a track called Another Brother. When every stem
    resolves through the tagged form, the loose form never runs, which is what
    keeps `Another Brother_(Other).wav` from reading as two claims on `other`.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise StemAdoptionError(f'Not a folder: {folder}')
    audio = [p for p in sorted(folder.iterdir())
             if p.suffix.lower() in AUDIO_SUFFIXES]
    if not audio:
        raise StemAdoptionError(f'No audio files in {folder}')

    tagged = _match(audio, lambda n, low: f'({n})' in low)
    if any(tagged.values()):
        found, pass_name = tagged, 'tagged'
    else:
        found = _match(audio, lambda n, low: re.search(rf'\b{n}\b', low) is not None)
        pass_name = 'loose'

    missing = sorted(n for n, v in found.items() if not v)
    if missing:
        raise StemAdoptionError(
            f'{folder} yields no stem for: {", ".join(missing)} (matched by '
            f'{pass_name} name). A six stem folder is required; a partial one '
            f'would produce a partial fact sheet, which is worse than none.')
    ambiguous = sorted(n for n, v in found.items() if len(v) > 1)
    if ambiguous:
        detail = '; '.join(
            f'{n}: ' + ', '.join(p.name for p in found[n]) for n in ambiguous)
        raise StemAdoptionError(
            f'More than one file claims these stems in {folder}: {detail}. '
            f'Rename or move the extras rather than letting the sheet pick one.')
    return {n: v[0] for n, v in found.items()}
```

The `if any(tagged.values())` guard is the fix for the critic's B10a. Revision 1
required the tagged pass to be *complete* before using it, which meant one extra
untagged file could silently demote the whole folder to loose matching. Now the
tagged pass owns the folder as soon as any file uses that form, and an
incomplete tagged set reports which stems are missing rather than falling
through to a looser rule that would guess.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 19 tests

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
Expected: both print all six stem names. The critic verified this already
resolves cleanly on both real folders, including past the source mp3 sitting
beside the stems. Paste the output into the pull request.

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
- Produces: `band_limit(y, sr, low, high) -> np.ndarray`, `key_estimate(signals, sr, low=150, high=2500) -> dict` with keys `key`, `scores`, `margin`, `tuning_estimate(y, sr) -> dict` with keys `tuning`, `lowest_hz`, `support`, `margin_cents`, and `TUNINGS`, `SUPPORT_FLOOR`.

`key_estimate` takes a list of signals so the guitar and bass stems are summed
before analysis rather than analysed separately and argued about afterwards.
The critic verified this is load-bearing: the summed pair names F# minor with a
margin of 0.1429, while the guitar alone names C# minor.

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


def tone(freq, seconds=1.0, sr=SR, harmonics=True):
    """A note, not a sine. Templates key off harmonic content."""
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    y = np.sin(2 * np.pi * freq * t)
    if harmonics:
        y = y + 0.5 * np.sin(2 * np.pi * 2 * freq * t) \
              + 0.25 * np.sin(2 * np.pi * 3 * freq * t)
    return y.astype(np.float32)


def chord(freqs, seconds=1.0, harmonics=True):
    return sum(tone(f, seconds, harmonics=harmonics) for f in freqs) / len(freqs)


FS_MINOR = (185.0, 220.0, 277.2)
CS_MINOR = (138.6, 174.6, 207.7)
D_MAJOR = (146.8, 185.0, 220.0)
A_MAJOR = (220.0, 277.2, 329.6)


class BandLimitTests(unittest.TestCase):
    def test_it_removes_energy_outside_the_band(self):
        y = tone(60, harmonics=False) + tone(1000, harmonics=False)
        out = c.band_limit(y, SR, 150, 2500)
        spectrum = np.abs(np.fft.rfft(out))
        freqs = np.fft.rfftfreq(len(out), 1 / SR)
        low = spectrum[(freqs > 40) & (freqs < 90)].max()
        keep = spectrum[(freqs > 900) & (freqs < 1100)].max()
        self.assertLess(low, keep * 0.1)

    def test_it_keeps_energy_inside_the_band(self):
        y = tone(1000, harmonics=False)
        out = c.band_limit(y, SR, 150, 2500)
        self.assertGreater(np.abs(out).max(), 0.3 * np.abs(y).max())

    def test_a_band_wider_than_nyquist_is_clamped_not_an_error(self):
        y = tone(1000, harmonics=False)
        self.assertEqual(len(c.band_limit(y, SR, 20, 40000)), len(y))


class KeyTests(unittest.TestCase):
    def test_it_names_the_key_of_a_tonic_weighted_minor_loop(self):
        # F#m held twice as long as the others, which is what gives a minor
        # key its tonic. An equal-duration F#m A E B loop contains exactly the
        # E major scale with equal weight and correctly reads as E major; the
        # critic proved that, and the fixture was wrong, not the estimator.
        progression = [(FS_MINOR, 4.0), (D_MAJOR, 2.0),
                       (FS_MINOR, 4.0), (CS_MINOR, 2.0)]
        y = np.concatenate([chord(f, s) for f, s in progression] * 2)
        result = c.key_estimate([y], SR)
        self.assertEqual(result['key'], 'F# minor')
        self.assertGreater(result['margin'], 0.05)

    def test_it_reports_a_margin_between_the_first_two_candidates(self):
        y = np.concatenate([chord(A_MAJOR, 2.0)] * 4)
        result = c.key_estimate([y], SR)
        self.assertGreaterEqual(result['margin'], 0.0)
        self.assertGreaterEqual(len(result['scores']), 3)

    def test_silence_has_no_key_rather_than_a_default_one(self):
        self.assertIsNone(c.key_estimate([np.zeros(SR, dtype=np.float32)],
                                         SR)['key'])

    def test_two_stems_are_summed_not_analysed_separately(self):
        a = np.concatenate([chord(FS_MINOR, 4.0), chord(D_MAJOR, 2.0)] * 3)
        b = np.concatenate([tone(92.5, 4.0), tone(73.4, 2.0)] * 3)
        self.assertIsNotNone(c.key_estimate([a, b], SR)['key'])


class TuningTests(unittest.TestCase):
    """Tuning is the lowest SUSTAINED semitone, not the lowest sample.

    Revision 1 took the 10th percentile of the pitch track and returned
    `drop D` on the real bass stem, with a margin of 0.9 cents, which reads as
    near certain and is wrong. The histogram showed why: C#1 holds 6.3 percent
    of frames and D1 holds 29.0, so the 10th percentile lands inside D1.
    """

    def _held(self, freqs_and_weights, seconds=0.5):
        parts = []
        for freq, repeats in freqs_and_weights:
            parts.extend([tone(freq, seconds, harmonics=False)] * repeats)
        return np.concatenate(parts)

    def test_it_names_drop_c_sharp_from_its_lowest_sustained_semitone(self):
        y = self._held([(34.65, 6), (36.71, 20), (46.25, 14)])
        self.assertEqual(c.tuning_estimate(y, SR)['tuning'], 'drop C#')

    def test_a_brief_lower_transient_does_not_become_the_tuning(self):
        # One frame of A0 against many of C#1. A kick drum is not a string.
        y = self._held([(27.50, 1), (34.65, 20), (46.25, 14)])
        self.assertEqual(c.tuning_estimate(y, SR)['tuning'], 'drop C#')

    def test_it_names_standard_e_from_its_lowest_sustained_semitone(self):
        y = self._held([(41.20, 12), (61.74, 12)])
        self.assertEqual(c.tuning_estimate(y, SR)['tuning'], 'standard E')

    def test_it_distinguishes_neighbouring_tunings_a_semitone_apart(self):
        self.assertEqual(
            c.tuning_estimate(self._held([(36.71, 16)]), SR)['tuning'], 'drop D')
        self.assertEqual(
            c.tuning_estimate(self._held([(32.70, 16)]), SR)['tuning'], 'drop C')

    def test_the_table_holds_no_two_tunings_closer_than_a_semitone(self):
        import math
        values = sorted(c.TUNINGS.values())
        for a, b in zip(values, values[1:]):
            self.assertGreater(abs(1200 * math.log2(b / a)), 50.0,
                               f'{a} and {b} are closer than a semitone apart')

    def test_no_sustained_low_fundamental_yields_no_tuning(self):
        result = c.tuning_estimate(np.zeros(SR * 2, dtype=np.float32), SR)
        self.assertIsNone(result['tuning'])

    def test_an_unexplained_low_bin_is_skipped_rather_than_losing_the_axis(self):
        # Wrong Turn's bass carries a 2.6 percent artifact at 25.96 Hz, which
        # is 200 cents from every table entry, while C#1 above it holds 21
        # percent. Revision 2 returned None for that track.
        y = self._held([(25.96, 2), (34.65, 24), (46.25, 14)])
        result = c.tuning_estimate(y, SR, floor=0.02)
        self.assertEqual(result['tuning'], 'drop C#')
        self.assertTrue(result['skipped_hz'])

    def test_it_reports_the_support_that_earned_the_answer(self):
        y = self._held([(34.65, 6), (36.71, 20)])
        self.assertGreaterEqual(c.tuning_estimate(y, SR)['support'],
                                c.SUPPORT_FLOOR)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chords'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/chords.py`:

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

# Lowest string fundamental an octave down, because this table reads the BASS
# stem, and in this material the bass doubles the lowest guitar string an
# octave below it. drop C# on a guitar is C#2 at 69.30 Hz; the entry below is
# C#1 at 34.65 Hz, which is what the bass actually plays.
#
# The guitar stem cannot be used for this. Its low band yin output is dominated
# by octave errors: on the reference track its strongest bin is F#1 at 17.0
# percent of frames, an octave below the musically real F#2. Revision 1 graded
# tuning KNOW when both stems agreed, and both stems agreed on the wrong answer.
#
# D standard is deliberately absent. Its lowest string is D, the same pitch as
# drop D's, so no measurement of a lowest fundamental can separate them, and
# revision 1's entry for it evaluated to 0.024 cents from standard E.
TUNINGS = {
    'standard E': 41.20,
    'Eb standard': 38.89,
    'drop D': 36.71,
    'drop C#': 34.65,
    'drop C': 32.70,
    'drop B': 30.87,
    'drop A#': 29.14,
}
# A semitone bin must hold this share of voiced frames to count as a played
# string rather than noise. Set by a sweep across all three corpus bass stems,
# not by the reference track alone. Revision 2 used 0.02, justified on the
# reference histogram only, and that value loses the axis entirely on Wrong
# Turn: a 2.6 percent sub bass artifact at 25.96 Hz clears the floor, sits 200
# cents from every table entry, and takes the whole axis to None while C#1 with
# 21.19 percent support sits four semitones above it.
#
#   floor   Murder She Wrote   Wrong Turn      The Danger of Caring
#   0.020   drop C# 34.65      None 25.96      drop C# 34.65
#   0.030   drop C# 34.65      drop C# 34.65   drop C# 34.65
#   0.040   drop C# 34.65      drop C# 34.65   drop C# 34.65
#   0.050   drop C# 34.65      drop C# 34.65   standard E 41.20
#   0.080   drop D  36.71      drop C# 34.65   standard E 41.20
#
# The three track agreement window is 0.03 to 0.04. 0.035 is its middle.
SUPPORT_FLOOR = 0.035
MAX_CENTS = 60.0
SILENCE = 1e-6


def band_limit(y, sr, low, high):
    """A fourth order Butterworth band pass, clamped to the usable range."""
    nyquist = sr / 2.0
    low = max(1.0, float(low))
    high = min(float(high), nyquist * 0.99)
    if low >= high:
        return np.asarray(y, dtype=np.float32)
    sos = signal.butter(4, [low / nyquist, high / nyquist], btype='band',
                        output='sos')
    return signal.sosfilt(sos, np.asarray(y, dtype=np.float64)).astype(np.float32)


def _summed(signals):
    stacked = [np.asarray(s, dtype=np.float32) for s in signals if s is not None]
    if not stacked:
        return None
    length = max(len(s) for s in stacked)
    out = np.zeros(length, dtype=np.float32)
    for s in stacked:
        out[:len(s)] += s
    return out


def key_estimate(signals, sr, low=150, high=2500):
    """Correlate a summed, band limited chroma against major and minor templates.

    These are correlations against templates, not probabilities. Music built on
    other systems will not fit them, which is why the margin travels with the
    answer instead of being discarded.
    """
    summed = _summed(signals)
    if summed is None:
        return {'key': None, 'scores': [], 'margin': 0.0}
    y = band_limit(summed, sr, low, high)
    if np.max(np.abs(y)) < SILENCE:
        return {'key': None, 'scores': [], 'margin': 0.0}
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    avg = chroma.mean(axis=1)
    if np.std(avg) < 1e-8:
        return {'key': None, 'scores': [], 'margin': 0.0}
    scored = []
    for i, note in enumerate(NOTES):
        for label, profile in (('major', KRUMHANSL_MAJOR),
                               ('minor', KRUMHANSL_MINOR)):
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


def tuning_estimate(y, sr, high=200.0, floor=SUPPORT_FLOOR):
    """Name the tuning from the lowest SUSTAINED semitone in the bass.

    Sustained is the whole point. A single low transient is a kick drum
    bleeding through, not a string, so the estimate bins the pitch track to
    semitones and takes the lowest bin that holds at least `floor` of the
    voiced frames.
    """
    y = np.asarray(y, dtype=np.float32)
    empty = {'tuning': None, 'lowest_hz': None, 'support': None,
             'margin_cents': None, 'skipped_hz': None, 'candidates': []}
    if len(y) == 0 or np.max(np.abs(y)) < SILENCE:
        return empty
    low = band_limit(y, sr, 25.0, high)
    f0 = librosa.yin(low.astype(np.float64), fmin=25.0, fmax=high, sr=sr,
                     frame_length=4096)
    f0 = f0[np.isfinite(f0)]
    f0 = f0[(f0 > 25.0) & (f0 < high)]
    if len(f0) < 32:
        return empty
    bins = np.round(librosa.hz_to_midi(f0)).astype(int)
    values, counts = np.unique(bins, return_counts=True)
    share = counts / counts.sum()
    supported = sorted(int(v) for v in values[share >= floor])
    if not supported:
        return empty
    # Walk up. One sub bass artifact should not take the whole axis to None
    # when a bin with real support sits a few semitones above it. Each
    # candidate is tried against the table in pitch order and the first that
    # lands within MAX_CENTS wins, so a skipped bin is a bin no tuning
    # explains rather than a bin that was ignored.
    # Every supported bin that the table can name, in pitch order, with its
    # support. The lowest still wins, but the alternatives travel with the
    # answer instead of vanishing.
    #
    # This is the failure the walk up traded for: the table is a contiguous
    # chromatic run from MIDI 22 to 28, so a yin sub octave error on a bass
    # note anywhere from A#1 to E2 lands INSIDE it, is named with a margin near
    # zero cents, and skips nothing. The real string with six times the support
    # two semitones up never appears. Returning the whole supported set is what
    # makes that visible to a reader and to the note on the fact.
    skipped, candidates = [], []
    for midi in supported:
        lowest = float(librosa.midi_to_hz(midi))
        support = float(share[values == midi][0])
        ranked = sorted((abs(1200 * math.log2(lowest / hz)), name)
                        for name, hz in TUNINGS.items())
        best_cents, best_name = ranked[0]
        if best_cents <= MAX_CENTS:
            candidates.append({'tuning': best_name, 'hz': round(lowest, 2),
                               'support': round(support, 4),
                               'cents': round(best_cents, 1)})
        else:
            skipped.append(round(lowest, 2))
    if not candidates:
        return {'tuning': None, 'lowest_hz': skipped[0] if skipped else None,
                'support': None, 'margin_cents': None, 'skipped_hz': skipped,
                'candidates': []}
    chosen = candidates[0]
    strongest = max(candidates, key=lambda c: c['support'])
    return {'tuning': chosen['tuning'], 'lowest_hz': chosen['hz'],
            'support': chosen['support'], 'margin_cents': chosen['cents'],
            'skipped_hz': skipped or None, 'candidates': candidates,
            'strongest_support_tuning': strongest['tuning'],
            'strongest_support': strongest['support']}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Prove both estimators on the real reference stems**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
D="$HOME/.config/deconstruct-audio/cache/stems/3b1f4c21c62edd82/htdemucs_6s/mydiarytoyou! - Murder, She Wrote (Official Visualizer)"
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
import librosa, chords
g,_ = librosa.load('$D/guitar.wav', sr=22050, mono=True)
b,_ = librosa.load('$D/bass.wav',   sr=22050, mono=True)
print('key   ', chords.key_estimate([g, b], 22050))
print('tuning', chords.tuning_estimate(b, 22050))
"
```
Expected, both already verified this session:
`key` names `F# minor` with a margin near 0.1429, and `tuning` names `drop C#`
with `lowest_hz` 34.65 and `support` near 0.063. Paste both into the pull
request. These are two of the five entry bar axes.

- [ ] **Step 6: Commit**

```bash
git add scripts/chords.py tests/test_chords.py
git commit -m "feat: key from summed stems, tuning from the lowest sustained semitone"
```

---

### Task 4: Chord sequence and harmonic rhythm

**Files:**
- Modify: `scripts/chords.py`
- Modify: `tests/test_chords.py`

**Interfaces:**
- Consumes: `band_limit`, `_summed` from Task 3.
- Produces: `chord_sequence(signals, sr, beat_times, bars_per_chord=1, low=150, high=2500) -> list[dict]` where each entry is `{'start_s', 'end_s', 'root', 'quality', 'root_share', 'root_margin', 'third_present', 'fifth_present'}` with `quality` in `('major', 'minor', 'power')`, and `harmonic_rhythm(sequence) -> dict` with keys `chords_per_bar`, `median_chord_bars`, `label`.

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

    def test_a_held_chord_reports_a_static_harmonic_rhythm(self):
        y = chord((220.0, 261.6, 329.6), 8.0)
        seq = c.chord_sequence([y], SR, self._beats(16))
        self.assertEqual(c.harmonic_rhythm(seq)['label'], 'static')

    def test_a_chord_per_bar_reports_a_fast_harmonic_rhythm(self):
        y = np.concatenate([chord((220.0, 261.6, 329.6), 2.0),
                            chord((246.9, 293.7, 370.0), 2.0),
                            chord((164.8, 207.7, 246.9), 2.0),
                            chord((185.0, 220.0, 277.2), 2.0)])
        seq = c.chord_sequence([y], SR, self._beats(16))
        self.assertGreater(len(seq), 1)
        self.assertEqual(c.harmonic_rhythm(seq)['label'], 'fast')

    def test_every_label_is_reachable(self):
        # Revision 1 had four labels and 'fast' could never fire, because a run
        # length is an integer of at least 1 so the median was always at least
        # 1 and the 'moderate' branch always won first. Three labels, each with
        # a run length that produces it.
        def seq(runs):
            out, tick = [], 0
            for index, length in enumerate(runs):
                for _ in range(length):
                    out.append({'start_s': float(tick), 'end_s': float(tick + 1),
                                'root': c.NOTES[index % 12], 'quality': 'power',
                                'root_share': 0.3, 'root_margin': 1.5,
                                'third_present': False,
                                'fifth_present': True})
                    tick += 1
            return out
        self.assertEqual(c.harmonic_rhythm(seq([1, 1, 1, 1]))['label'], 'fast')
        self.assertEqual(c.harmonic_rhythm(seq([2, 2, 2]))['label'], 'slow')
        self.assertEqual(c.harmonic_rhythm(seq([4, 4]))['label'], 'static')

    def test_no_beats_yields_no_sequence_rather_than_a_guess(self):
        self.assertEqual(c.chord_sequence([tone(220.0, 2.0)], SR,
                                          np.array([])), [])

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
# The value a root with no runner up reports. Finite and large, because None
# would serialise as null and the MIDI emitter reads a missing margin as no
# confidence, which is the exact opposite of what an unbeatable root means.
MARGIN_CAP = 99.0
BEATS_PER_BAR = 4


def _bar_windows(beat_times, beats_per_bar=BEATS_PER_BAR, bars_per_chord=1):
    beat_times = np.asarray(beat_times, dtype=float)
    if len(beat_times) < 2:
        return []
    step = beats_per_bar * bars_per_chord
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
    summed = _summed(signals)
    if summed is None:
        return []
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
        # root_share is the root's share of a normalised 12 bin chroma, whose
        # floor is 0.083 by construction, so it is not a confidence and must
        # not be used as one. root_margin is: how far the winner beat the
        # runner up. A bar where two pitch classes tie has margin near 1.0
        # however healthy its share looks.
        ordered = np.sort(profile)[::-1]
        second = float(ordered[1]) if len(ordered) > 1 else 0.0
        # Capped, never None and never inf. An unbeatable root is the most
        # confident reading there is, and emitting None for it collides head on
        # with the MIDI emitter, which reads a missing margin as no confidence
        # and replaces the chord with a sustained root. The two would have meant
        # exact opposites through the same field.
        margin = (root_energy / second) if second > 0 else MARGIN_CAP
        out.append({'start_s': round(float(start), 3),
                    'end_s': round(float(end), 3),
                    'root': NOTES[root], 'quality': quality,
                    'root_share': round(root_energy, 4),
                    'root_margin': round(min(float(margin), MARGIN_CAP), 3),
                    'third_present': third_present,
                    'fifth_present': bool(fifth >= FIFTH_RATIO)})
    return out


def harmonic_rhythm(sequence):
    """How often the chord actually changes, in bars.

    Three labels, not four. A run length is an integer of at least 1, so a
    median below 1 is impossible and any label defined by that range can never
    fire. Revision 1 had one.
    """
    if not sequence:
        return {'chords_per_bar': None, 'median_chord_bars': None, 'label': None}
    runs, current = [], 1
    for previous, entry in zip(sequence, sequence[1:]):
        if (previous['root'] == entry['root']
                and previous['quality'] == entry['quality']):
            current += 1
        else:
            runs.append(current)
            current = 1
    runs.append(current)
    median = float(np.median(runs))
    label = 'static' if median >= 4 else ('slow' if median >= 2 else 'fast')
    return {'chords_per_bar': round(1.0 / median, 3),
            'median_chord_bars': round(median, 2), 'label': label}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_chords -v`
Expected: PASS, 22 tests

`THIRD_RATIO` at 0.55 is a starting value, not a measured one. If a synthetic
triad test fails, print the three ratios for that fixture and set the constant
from what you see, then record the observed numbers in a comment beside it. Do
not change the assertions. Then check what your new value does to the real
guitar plus bass pair and put that in the pull request, because a constant tuned
on sine triads that has never seen a distorted guitar is a constant on probation.

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
  "source": {"path": "...", "sha256": "...", "duration_s": 138.786},
  "stems_from": "separated|adopted",
  "facts": {"tempo": {...}, "key": {...}}
}
```

`generated_at` is the only field allowed to differ between two runs on the same
audio. That is what makes rerun stability testable.

**Three interface facts a builder needs, each a defect the critic found in
revision 1:**

1. **Beat times have no source.** `chord_sequence` needs them. `tempo_family`
   does not return them and neither does `measure.measure`, verified. So
   `facts.py` owns `_beat_times`, and it seeds the beat tracker with the
   already measured primary tempo rather than letting it choose a metrical
   level again. The tempo family has already made that decision; a second
   opinion here would silently override it, and the section specialist verified
   librosa's unseeded tracker sits at different metrical levels across this
   corpus, reporting 152 BPM on a track stated at about 103.
2. **`band_limit` takes `sr`.** Revision 1 called `band_limit(guitar, 70, 1400)`,
   which puts 70 where `sr` belongs and drops `high`. It is
   `chords_mod.band_limit(guitar, sr, 70, 1400)`.
3. **`_register` is a helper, not a builder.** Builders share one signature.
   The two register axes are thin wrappers over it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_facts.py` before `if __name__`:

```python
import json
import subprocess


def synth_track(path, seconds=16):
    """A click, a low drone and a mid tone. No copyrighted audio in the repo."""
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'sine=frequency=110:duration={seconds}',
        '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}',
        '-f', 'lavfi', '-i', f'anoisesrc=d={seconds}:c=pink:a=0.3',
        '-filter_complex', '[0][1][2]amix=inputs=3',
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
            (self.stems / f'{name}.wav').write_bytes(self.audio.read_bytes())

    def sheet(self):
        return f.fact_sheet(self.audio, stems_dir=self.stems)

    def test_every_fact_carries_method_and_confidence(self):
        sheet = self.sheet()
        self.assertTrue(sheet['facts'])
        for axis, entry in sheet['facts'].items():
            self.assertTrue(entry['method'], f'{axis} has no method')
            self.assertIn(entry['confidence'], f.CONFIDENCE, axis)
            self.assertIn(entry['suno_actionable'], f.ACTIONABLE, axis)

    def test_the_sheet_names_its_schema_and_its_source(self):
        sheet = self.sheet()
        self.assertEqual(sheet['schema'], f.SCHEMA)
        self.assertEqual(len(sheet['source']['sha256']), 64)
        self.assertEqual(sheet['stems_from'], 'adopted')

    def test_the_whole_sheet_serialises_without_allow_nan(self):
        json.dumps(self.sheet(), allow_nan=False)

    def test_two_runs_on_the_same_audio_agree_apart_from_the_timestamp(self):
        first, second = self.sheet(), self.sheet()
        first.pop('generated_at')
        second.pop('generated_at')
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_the_projection_uses_compare_s_own_axis_names(self):
        import compare
        projected = f.scorable(self.sheet())
        self.assertTrue(projected)
        for axis in projected:
            self.assertIn(axis, compare.GATES, f'{axis} is not a compare axis')

    def test_an_unknown_axis_is_left_out_of_the_projection_not_passed_as_null(self):
        sheet = self.sheet()
        sheet['facts']['key'] = f.fact(None, 'name', 'guitar', ['chroma'],
                                       'UNKNOWN', 'direct')
        self.assertNotIn('key', f.scorable(sheet))

    def test_section_count_is_unknown_and_says_why(self):
        entry = self.sheet()['facts']['section_count']
        self.assertEqual(entry['confidence'], 'UNKNOWN')
        self.assertIsNone(entry['value'])
        self.assertIn('generalise', entry['note'])

    def test_section_boundaries_are_still_emitted(self):
        entry = self.sheet()['facts']['section_boundaries']
        self.assertEqual(entry['confidence'], 'INFER')
        self.assertIsInstance(entry['value'], list)

    def test_a_silent_stem_is_reported_absent_rather_than_failing(self):
        import numpy as np
        import soundfile as sf
        y, sr = sf.read(self.stems / 'piano.wav')
        sf.write(self.stems / 'piano.wav', np.zeros_like(y), sr)
        entry = f.fact_sheet(self.audio, stems_dir=self.stems)['facts']['instrumentation']
        self.assertEqual(entry['confidence'], 'KNOW')
        self.assertFalse(entry['value']['piano']['active'])

    def test_the_markdown_names_every_axis_and_its_grade(self):
        sheet = self.sheet()
        text = f.render_markdown(sheet)
        for axis in sheet['facts']:
            self.assertIn(axis, text)

    def test_a_partial_stem_folder_refuses_rather_than_emitting_a_partial_sheet(self):
        (self.stems / 'guitar.wav').unlink()
        with self.assertRaises(f.StemAdoptionError):
            f.fact_sheet(self.audio, stems_dir=self.stems)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: FAIL, `AttributeError: module 'facts' has no attribute 'fact_sheet'`

- [ ] **Step 3: Write the shared helpers**

Append to `scripts/facts.py`:

```python
import datetime as _dt
import hashlib

import librosa
import numpy as np

import chords as chords_mod
import measure as measure_mod
import stems as stems_mod
import tempo as tempo_mod

SCHEMA = 'deconstruct-audio/facts/1'
SR = 22050
LOW_END_HZ = 150.0
AIR_HZ = 5000.0
N_FFT = 2048
# A stem counts as present when its RMS is within this many dB of the loudest
# stem. Relative, not absolute, so it does not move with mastering level.
#
# Swept across all three corpus tracks, not just the reference. At 30 dB the
# `other` stem on Wrong Turn sits 0.62 dB from flipping to absent, and this
# axis is suno_actionable direct, so a flip changes what the prompt says the
# track contains. At 35 dB every `other` stem clears by at least 2.2 dB and
# both piano stems still read absent by at least 4.2 dB, which is correct:
# neither track has a piano.
PRESENCE_DB = 35.0
# Per second window threshold for the intro's arrangement density curve. The
# intro rule below returns the same answer at -35, -40 and -45 on the reference
# track, so this constant is not load bearing.
ACTIVE_DB = -40.0
INTRO_SNAP_S = 4.0
# An intro lives near the beginning. Without a window, a post breakdown re
# entry two thirds of the way through a track competes with it and wins.
# INTRO_WINDOW_S is a count of one second windows, and the two coincide only
# because `window = int(sr)` below. If the window size ever changes, convert.
INTRO_WINDOW_S = 60.0
INTRO_WINDOW_FRACTION = 0.4
# The working density of the mix. Deliberately not the median: an intro that
# occupies half or more of the track makes the median equal to the intro's own
# density, and the no-intro guard then fires on the longest intros.
INTRO_TYPICAL_PERCENTILE = 75
# The winning beat grouping must beat the runner up by this ratio. Measured: on
# the reference track 3 scores 16526.6 against 4 at 14573.1, a ratio of 1.134,
# and the axis reads 3 on two of three tracks in a genre whose prior is
# overwhelmingly 4/4. Below this margin the axis says UNKNOWN rather than
# shipping a coin toss into a prompt as a statement.
METER_MARGIN = 1.15

SECTION_COUNT_NOTE = (
    'Sixteen structure segmentation methods were run at one fixed '
    'configuration and none generalise across the three track corpus. The best '
    'candidate returns 7, 6 and 10, matches 4 of 6 known boundaries, and was '
    'selected by noticing which row of a table hit the known answer, which is '
    'selection on the one track that has one. Reporting a count that is about '
    'half likely to be wrong is worse than reporting none, because a stated '
    'number invites downstream use that a missing one does not. Boundaries are '
    'emitted separately. Note that the boundary hit rates in that study were '
    'scored against this pipeline\'s own incumbent boundaries rather than human '
    'annotation, because the known ground truth is a count and not a boundary '
    'list, so they measure agreement with the incumbent rather than correctness.')


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _load(path, sr=SR):
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y


def _rms_db(y):
    if len(y) == 0:
        return float('-inf')
    value = float(np.sqrt(np.mean(np.asarray(y, dtype=np.float64) ** 2)))
    return 20.0 * math.log10(value) if value > 0 else float('-inf')


def _beat_times(drums, sr, bpm):
    """A beat grid at the tempo the tempo family already chose.

    Seeding matters. An unseeded tracker picks its own metrical level, and on
    this corpus it lands on different levels for different tracks, reporting
    152 BPM for one stated at about 103. The tempo family has already made
    that decision with three methods and a published grade; re-deciding it
    here would silently override it with one method and no grade.
    """
    if not bpm or bpm <= 0:
        return np.array([])
    onset = librosa.onset.onset_strength(y=drums, sr=sr)
    _, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr,
                                       bpm=float(bpm), trim=False)
    return librosa.frames_to_time(beats, sr=sr)


def _register(y, sr, fmin, fmax, stem, band, actionable):
    """Median and spread of a pitch track, in MIDI note numbers.

    A helper, not an axis builder. The two register axes wrap it.
    """
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-6:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', actionable,
                    band_hz=band, note='stem is silent')
    f0 = librosa.yin(y.astype(np.float64), fmin=fmin, fmax=fmax, sr=sr)
    f0 = f0[np.isfinite(f0) & (f0 > fmin) & (f0 < fmax)]
    if len(f0) < 16:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', actionable,
                    band_hz=band, note='no stable pitch track')
    midi = librosa.hz_to_midi(f0)
    value = {'median_midi': round(float(np.median(midi)), 2),
             'p10_midi': round(float(np.percentile(midi, 10)), 2),
             'p90_midi': round(float(np.percentile(midi, 90)), 2)}
    return fact(value, 'midi', stem, ['yin'], 'INFER', actionable, band_hz=band,
                note='single method pitch track over a separated stem, and yin '
                     'octave errors are common in this band')
```

- [ ] **Step 4: Write the axis builders**

Every builder takes the same six arguments and returns a `fact()`. Write them in
this order, running the suite after each so a break names its own axis.

```python
def _tempo_fact(paths, loaded, mix, sr, local, built):
    result = tempo_mod.tempo_family(paths['drums'])
    note = result.get('disagreement')
    return fact(result['primary'], 'bpm', 'drums',
                ['tempogram-peak', 'beat-track', 'inter-onset'],
                result['confidence'], 'direct', note=note)
```

The tempo axis carries `tempo_family`'s own grade straight through. That
grading already exists, is tested, and re-deriving it here would be a second
opinion nobody asked for.

```python
def _instrumentation_fact(paths, loaded, mix, sr, local, built):
    levels = {name: _rms_db(y) for name, y in loaded.items()}
    finite = [v for v in levels.values() if math.isfinite(v)]
    loudest = max(finite) if finite else float('-inf')
    value = {name: {'rms_db': (round(db, 2) if math.isfinite(db) else None),
                    'active': bool(math.isfinite(db) and db >= loudest - PRESENCE_DB)}
             for name, db in levels.items()}
    present = sorted(n for n, v in value.items() if v['active'])
    return fact(value, 'dbfs', 'all', ['stem-rms'], 'KNOW', 'direct',
                note=f'present: {", ".join(present)}. A stem more than '
                     f'{PRESENCE_DB:g} dB below the loudest reads absent, which '
                     f'is a measurement of the arrangement, not a separation '
                     f'failure.')
```

This axis exists because the parent spec's pipeline gate read "six stems, all
non-silent", and the reference track's piano stem measures -58.29 dBFS with a
peak of 0.0029. That is a correct separation of a track with no piano. A gate
that fails a correct measurement teaches the wrong lesson, so the near silent
stem becomes a measurement instead. It is also the axis a prompt needs in order
to name the instruments actually present rather than the six demucs always emits.

```python
def _key_fact(paths, loaded, mix, sr, local, built):
    result = chords_mod.key_estimate([loaded['guitar'], loaded['bass']], sr)
    band = [150, 2500]
    if result['key'] is None:
        return fact(None, 'name', 'guitar+bass', ['chroma-cqt-krumhansl'],
                    'UNKNOWN', 'direct', band_hz=band,
                    note='no key resolved')
    # The cross check, restored. Revision 1 required the margin AND agreement
    # with the chord sequence's most common root; revision 2 dropped the second
    # half and graded on margin alone. Measured cost of dropping it: Wrong Turn
    # scores C# minor at margin 0.0584 while its most common chord root is E,
    # its relative major, and that would have been graded KNOW. The check was
    # doing real work.
    sequence = (built.get('chords') or {}).get('value') or []
    roots = [e['root'] for e in sequence]
    common = max(set(roots), key=roots.count) if roots else None
    tonic = result['key'].split()[0]
    agrees = common is not None and common == tonic
    grade = 'KNOW' if (result['margin'] >= 0.05 and agrees) else 'INFER'
    runner = result['scores'][1][0] if len(result['scores']) > 1 else 'none'
    return fact(result['key'], 'name', 'guitar+bass',
                ['chroma-cqt-krumhansl', 'chord-root-histogram'], grade,
                'direct', band_hz=band,
                note=f'margin {result["margin"]} over the runner up {runner}; '
                     f'most common chord root {common}, tonic {tonic}, '
                     f'{"agree" if agrees else "disagree"}. These are template '
                     f'correlations, not probabilities.')
```

```python
def _tuning_fact(paths, loaded, mix, sr, local, built):
    result = chords_mod.tuning_estimate(loaded['bass'], sr)
    band = [25, 200]
    if result['tuning'] is None:
        return fact(None, 'name', 'bass', ['yin-semitone-histogram'],
                    'UNKNOWN', 'direct', band_hz=band,
                    note=f'no semitone bin cleared the '
                         f'{chords_mod.SUPPORT_FLOOR:g} support floor')
    return fact(result['tuning'], 'name', 'bass', ['yin-semitone-histogram'],
                'INFER', 'direct', band_hz=band,
                note=f'lowest sustained semitone {result["lowest_hz"]} Hz with '
                     f'{result["support"]:.3f} frame support, '
                     f'{result["margin_cents"]} cents from the template. '
                     f'Every supported candidate: '
                     f'{", ".join(str(c) for c in result["candidates"])}. '
                     f'The best supported was '
                     f'{result["strongest_support_tuning"]} at '
                     f'{result["strongest_support"]:.3f}. Read from the bass '
                     f'only: the guitar stem is dominated by yin octave errors '
                     f'in this band and cannot corroborate it. A sub octave '
                     f'artifact landing inside the table is named with a small '
                     f'cents margin and is only visible in this list.')
```

Graded `INFER`, never `KNOW`. Revision 1 graded it `KNOW` when both stems agreed
separately, and on the real track both stems agreed on `drop D`, which is wrong.
A rule that promotes a shared artifact to `KNOW` is worse than no rule.

```python
def _chords_fact(paths, loaded, mix, sr, local, built):
    band = [150, 2500]
    tempo_entry = built.get('tempo') or {}
    beats = _beat_times(loaded['drums'], sr, tempo_entry.get('value'))
    if not len(beats):
        return fact(None, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                    'UNKNOWN', 'midi_only', band_hz=band,
                    note='no beat grid, so no bar windows to read chords over')
    sequence = chords_mod.chord_sequence(
        [loaded['guitar'], loaded['bass']], sr, beats)
    if not sequence:
        return fact(None, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                    'UNKNOWN', 'midi_only', band_hz=band,
                    note='no chord resolved in any bar window')
    powers = sum(1 for e in sequence if e['quality'] == 'power')
    return fact(sequence, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                'INFER', 'midi_only', band_hz=band,
                note=f'{len(sequence)} bars, {powers} with no measured third. '
                     f'Chord names are midi_only: text prompts discard them. '
                     f'root_share is a normalised chroma share with a 0.083 '
                     f'floor and is not a confidence; root_margin is.')


def _harmonic_rhythm_fact(paths, loaded, mix, sr, local, built):
    band = [150, 2500]
    sequence = (built.get('chords') or {}).get('value')
    if not sequence:
        return fact(None, 'bars', 'guitar+bass', ['chord-run-length'],
                    'UNKNOWN', 'indirect', band_hz=band,
                    note='no chord sequence to measure a rate over')
    result = chords_mod.harmonic_rhythm(sequence)
    return fact(result, 'bars', 'guitar+bass', ['chord-run-length'],
                'INFER', 'indirect', band_hz=band,
                note='inherits the chord sequence\'s own uncertainty')
```

`built` is the accumulating dict, which is how a later axis reads an earlier
one. `tempo` is built before `chords`, and `chords` before `harmonic_rhythm`.

```python
def _section_boundaries_fact(paths, loaded, mix, sr, local, built):
    boundaries = [float(t) for t in local.get('segment_boundaries_s') or []]
    if not boundaries:
        return fact(None, 'seconds', 'mix', ['agglomerative-clustering'],
                    'UNKNOWN', 'none', note='no boundaries resolved')
    return fact(boundaries, 'seconds', 'mix', ['agglomerative-clustering'],
                'INFER', 'direct',
                note='clustering suggestions, not verified verses and choruses')


def _section_count_fact(paths, loaded, mix, sr, local, built):
    return fact(None, 'count', 'mix',
                ['agglomerative-clustering', 'laplacian-segmentation',
                 'checkerboard-novelty', 'dp-bic-changepoint'],
                'UNKNOWN', 'none', note=SECTION_COUNT_NOTE)
```

The count axis is `UNKNOWN` by construction and carries all four method families
that were tried, so a reader can see it was attempted rather than skipped. This
is the legitimate use of `UNKNOWN`: a method that genuinely cannot resolve.

```python
def _intro_fact(paths, loaded, mix, sr, local, built):
    """How long before the arrangement reaches its working density.

    Three guards, each closing a way this returned a confident wrong answer.

    The track may have no intro. The Danger of Caring is at density 5 in its
    first second and never rises again; its only density increases are a
    post breakdown re entry at 123 s and another at 151 s. Revision 2 returned
    123.41 s on a 205.8 s track and graded it KNOW.

    The step must be near the beginning. An intro is a position, not just a
    shape, and without a window any later re entry competes with it.

    The step must rise OUT of a thin passage. A step from an already typical
    density is an arrangement change, not the end of an intro.
    """
    window = int(sr)
    count = min(len(y) for y in loaded.values()) // window
    if count < 3:
        return fact(None, 'seconds', 'mix', ['stem-density-step'],
                    'UNKNOWN', 'direct', note='too short to read a density step')
    density = [sum(1 for y in loaded.values()
                   if _rms_db(y[i * window:(i + 1) * window]) > ACTIVE_DB)
               for i in range(count)]
    # The 75th percentile, not the median. With the median, an intro occupying
    # half or more of the windows IS the median, the no-intro guard fires, and
    # a 60 s track with a 35 s intro reports zero. The guard misfired exactly
    # on the tracks with the longest intros.
    typical = float(np.percentile(np.asarray(density), INTRO_TYPICAL_PERCENTILE))
    if typical <= 0:
        return fact(None, 'seconds', 'mix', ['stem-density-step'], 'UNKNOWN',
                    'direct',
                    note='the working density of this mix is zero stems, which '
                         'means nothing was measured rather than that the intro '
                         'is zero seconds long')

    if density[0] >= typical:
        return fact(0.0, 'seconds', 'mix', ['stem-density-step'], 'INFER',
                    'direct',
                    note=f'the arrangement is already at its working density of '
                         f'{typical:g} stems in the first window, so there is no '
                         f'intro to measure')

    # The first window that REACHES the working density, not the largest step
    # on the way there. A step rule takes the earliest of equal steps, so a
    # 30 s fade in through six equal steps reported 5 s, and a two second
    # flourish before the real entry beat the real entry.
    limit = max(1, int(min(INTRO_WINDOW_S, INTRO_WINDOW_FRACTION * count)))
    reached = [i for i in range(min(count, limit)) if density[i] >= typical]
    if not reached:
        return fact(None, 'seconds', 'mix', ['stem-density-step'], 'UNKNOWN',
                    'direct',
                    note=f'the arrangement never reaches its working density of '
                         f'{typical:g} stems within the first {limit} s')
    raw = float(reached[0])
    size = int(density[reached[0]] - density[0])
    boundaries = (built.get('section_boundaries') or {}).get('value') or []
    near = [b for b in boundaries if abs(b - raw) <= INTRO_SNAP_S]
    if near:
        snapped = min(near, key=lambda b: abs(b - raw))
        return fact(round(float(snapped), 2), 'seconds', 'mix',
                    ['stem-density-step', 'agglomerative-clustering'],
                    'INFER', 'direct',
                    note=f'density rose by {size} stems at {raw:.0f} s out of a '
                         f'passage below the typical {typical:g}, and a section '
                         f'boundary sits at {snapped:.2f} s. Two methods agreeing '
                         f'on a position is not cross validation of a length, so '
                         f'this stays INFER.')
    return fact(raw, 'seconds', 'mix', ['stem-density-step'], 'INFER', 'direct',
                note=f'density rose by {size} stems at {raw:.0f} s, with no '
                     f'section boundary within {INTRO_SNAP_S:g} s to confirm it')
```

Measured on all three corpus tracks AND on nine synthetic shapes before being
written here. The corpus alone cannot validate this axis: only one track has
ground truth, so a rule can fit that track and be wrong everywhere else, which
is what the two earlier versions did.

| Shape | Truth | Result |
|---|---|---|
| Murder, She Wrote, real | 12.1 | 12.12 after snap |
| Wrong Turn, real | unknown | 5, snapped to 4.18 |
| The Danger of Caring, real | no intro | 0.0 |
| 6 s at density 2, then 5 s at 5 | 6 | 6.0 |
| 35 s at 1, then 25 s at 5 | 35 | 35.0 |
| 20 s at 1, then 100 s at 5 | 20 | 20.0 |
| 40 s silent, then 20 s at 4 | 40 | 40.0 |
| fade 1 to 6 over 30 s, then 6 | 25 | 25.0 |
| 2 s flourish at 3, then 4 forever | 6 | 6.0 |
| 70 s at 1, then 80 s at 4 | 70 | 70.0 |

The three shapes in the middle are the ones that killed the previous version.
A median-based typical density reported 0.0 for the 35 s intro and for the
silent opening, and a largest-step rule reported 5 s for the fade and 1 s for
the flourish.

The grade is `INFER` in every branch. An earlier version granted `KNOW` when a
section boundary sat within 4 s, and on The Danger of Caring a boundary sat
0.41 s from a wrong answer. Two methods agreeing on a position is not cross
validation of a length.

```python
def _loudness_fact(paths, loaded, mix, sr, local, built):
    value = {'integrated_lufs': local.get('integrated_lufs'),
             'lra_lu': local.get('lra_lu'),
             'true_peak_dbtp': local.get('true_peak_dbtp')}
    if value['lra_lu'] is None:
        return fact(None, 'lu', 'mix', ['ebur128'], 'UNKNOWN', 'indirect',
                    note='ffmpeg returned no loudness summary')
    return fact(value, 'lu', 'mix', ['ebur128'], 'KNOW', 'indirect',
                note='ITU-R BS.1770-4 via ffmpeg, the one axis here where a '
                     'single method is genuinely authoritative')


def _spectral_fact(paths, loaded, mix, sr, local, built):
    S = np.abs(librosa.stft(mix, n_fft=N_FFT))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    per_frame = S.sum(axis=0)
    per_frame[per_frame == 0] = 1.0
    low = float(np.mean(S[freqs < LOW_END_HZ].sum(axis=0) / per_frame)) * 100
    air = float(np.mean(S[freqs > AIR_HZ].sum(axis=0) / per_frame)) * 100
    centroid = float(np.mean(librosa.feature.spectral_centroid(S=S, sr=sr)))
    value = {'low_end_share': round(low, 2), 'air_share': round(air, 2),
             'centroid_hz': round(centroid, 1)}
    return fact(value, 'percent', 'mix', ['stft-band-share'], 'KNOW', 'indirect',
                band_hz=[0, int(sr // 2)],
                note=f'low end is the per frame mean magnitude share below '
                     f'{LOW_END_HZ:g} Hz at n_fft {N_FFT}, sr {sr}, mono. The '
                     f'definition is pinned because the readings of "share of '
                     f'spectral energy" span 10.8 to 58.0 percent on one track '
                     f'depending on magnitude against power, global against per '
                     f'frame, and crossover. Both sides of a comparison must '
                     f'run through this same function.')


def _dynamic_arc_fact(paths, loaded, mix, sr, local, built):
    arc = local.get('rms_db_per_4s') or []
    usable = [v for _, v in arc if v is not None]
    if not usable:
        return fact(None, 'db', 'mix', ['rms-per-4s'], 'UNKNOWN', 'indirect',
                    note='no usable RMS windows')
    peak = max(usable)
    value = [[float(t), (None if v is None else round(float(v) - peak, 2))]
             for t, v in arc]
    return fact(value, 'db', 'mix', ['rms-per-4s'], 'KNOW', 'indirect',
                note='normalised to the track\'s own peak window')


def _note_density_fact(paths, loaded, mix, sr, local, built):
    bpm = (built.get('tempo') or {}).get('value')
    guitar = loaded['guitar']
    if not bpm or bpm <= 0 or float(np.max(np.abs(guitar))) < 1e-6:
        return fact(None, 'onsets_per_beat', 'guitar', ['onset-rate'],
                    'UNKNOWN', 'indirect', band_hz=[150, 2500],
                    note='no tempo or a silent stem')
    band = chords_mod.band_limit(guitar, sr, 150, 2500)
    onsets = librosa.onset.onset_detect(y=band, sr=sr, units='time')
    seconds = len(band) / sr
    if seconds <= 0:
        return fact(None, 'onsets_per_beat', 'guitar', ['onset-rate'],
                    'UNKNOWN', 'indirect', band_hz=[150, 2500],
                    note='zero length stem')
    per_beat = (len(onsets) / seconds) / (float(bpm) / 60.0)
    return fact(round(float(per_beat), 3), 'onsets_per_beat', 'guitar',
                ['onset-rate'], 'INFER', 'indirect', band_hz=[150, 2500],
                note='onset rate normalised to the measured beat')


def _meter_fact(paths, loaded, mix, sr, local, built):
    bpm = (built.get('tempo') or {}).get('value')
    if not bpm or bpm <= 0:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='no tempo to group beats against')
    onset = librosa.onset.onset_strength(y=loaded['drums'], sr=sr)
    if not len(onset) or float(np.max(onset)) <= 1e-5:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='no onsets in the drums stem')
    hop = 512
    frames_per_beat = (60.0 / float(bpm)) * sr / hop
    ac = librosa.autocorrelate(onset - onset.mean())
    scores = {}
    for grouping in (3, 4):
        lag = int(round(frames_per_beat * grouping))
        scores[grouping] = float(ac[lag]) if 0 < lag < len(ac) else float('-inf')
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_score = ranked[1][1]
    detail = ', '.join(f'{k} scored {v:.3f}' for k, v in sorted(scores.items()))
    if not math.isfinite(best_score) or runner_score <= 0:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='autocorrelation lag out of range')
    if best_score / runner_score < METER_MARGIN:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none',
                    note=f'{detail}, a margin of '
                         f'{best_score / runner_score:.3f} which is under '
                         f'{METER_MARGIN}. Unnormalised autocorrelation at two '
                         f'lags cannot separate 3 from 4 on this material, and '
                         f'meter is suno_actionable direct, so a coin toss '
                         f'would reach the prompt as a statement.')
    return fact(best, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                'INFER', 'direct',
                note=f'{detail}. Published benchmarks put meter identification '
                     f'well below the other axes and this is one method.')


def _lead_register_fact(paths, loaded, mix, sr, local, built):
    band = chords_mod.band_limit(loaded['guitar'], sr, 70, 1400)
    return _register(band, sr, 70, 1400, 'guitar', [70, 1400], 'direct')


def _vocal_register_fact(paths, loaded, mix, sr, local, built):
    return _register(loaded['vocals'], sr, 70, 1200, 'vocals', [70, 1200],
                     'direct')
```

- [ ] **Step 5: Write the assembler, the projection and the renderer**

```python
# Order matters and is load bearing in three places: chords reads tempo, key
# reads chords for its cross check, and intro_seconds reads section_boundaries.
BUILDERS = (
    ('tempo', _tempo_fact),
    ('meter', _meter_fact),
    ('instrumentation', _instrumentation_fact),
    ('tuning', _tuning_fact),
    ('chords', _chords_fact),
    ('key', _key_fact),
    ('harmonic_rhythm', _harmonic_rhythm_fact),
    ('section_boundaries', _section_boundaries_fact),
    ('section_count', _section_count_fact),
    ('intro_seconds', _intro_fact),
    ('note_density', _note_density_fact),
    ('lead_register', _lead_register_fact),
    ('vocal_register', _vocal_register_fact),
    ('loudness', _loudness_fact),
    ('spectral_balance', _spectral_fact),
    ('dynamic_arc', _dynamic_arc_fact),
)

PROJECTION = {
    'tempo': ('tempo_bpm', lambda v: v),
    'key': ('key', lambda v: v),
    'tuning': ('tuning', lambda v: v),
    'intro_seconds': ('intro_seconds', lambda v: v),
    'section_count': ('section_count', lambda v: v),
    'loudness': ('lra_lu', lambda v: v['lra_lu']),
    'spectral_balance': ('low_end_share', lambda v: v['low_end_share']),
    'lead_register': ('lead_register_midi', lambda v: v['median_midi']),
}


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
    loaded = {name: _load(path) for name, path in paths.items()}
    mix = _load(audio)
    local = measure_mod.measure(str(audio))
    built = {}
    for name, builder in BUILDERS:
        built[name] = builder(paths, loaded, mix, SR, local, built)
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

    This omission is also a hole, and Task 8 is what closes it: a sheet that
    graded its failing axes UNKNOWN would project only its passing ones and
    score PASS. The corpus gate therefore asserts how many axes were measured,
    not only the verdict.
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
             f'Stems: {sheet["stems_from"]}',
             f'Generated: {sheet["generated_at"]}', '',
             '| Axis | Value | Unit | Stem | Band Hz | Confidence | Method | Suno |',
             '|---|---|---|---|---|---|---|---|']
    for axis, entry in sheet['facts'].items():
        band = '' if entry['band_hz'] is None else \
            f'{entry["band_hz"][0]} to {entry["band_hz"][1]}'
        value = entry['value']
        if isinstance(value, (list, dict)):
            shown = f'{len(value)} entries'
        else:
            shown = value
        lines.append(
            f'| {axis} | {shown} | {entry["unit"]} | {entry["stem"]} | '
            f'{band} | {entry["confidence"]} | {", ".join(entry["method"])} | '
            f'{entry["suno_actionable"]} |')
    notes = [(a, e['note']) for a, e in sheet['facts'].items() if e['note']]
    if notes:
        lines += ['', '## Notes', '']
        lines += [f'- **{a}**: {n}' for a, n in notes]
    return '\n'.join(lines) + '\n'
```

- [ ] **Step 6: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_facts -v`
Expected: PASS, 30 tests

If `test_two_runs_on_the_same_audio_agree_apart_from_the_timestamp` fails, do not
round harder until it passes. Find which axis moved, name the stochastic step
inside it, and seed it. The critic checked `measure`, `tempo_family`,
`key_estimate` and `tuning_estimate` for non-determinism and found none, so a
failure here is most likely a new axis, not an inherited one.

- [ ] **Step 7: Commit**

```bash
git add scripts/facts.py tests/test_facts.py
git commit -m "feat: assemble the graded fact sheet"
```

---

### Task 6: The tuning axis on compare, and the four assertions it moves

**Files:**
- Modify: `scripts/compare.py`
- Modify: `tests/test_compare.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a `tuning` entry in `compare.GATES`, and `tuning_verdict(reference, candidate) -> tuple[str, str]`.

**Read this before you start.** Revision 1 claimed adding this gate would not
touch the existing tests. That was false. `tests/test_compare.py:10` defines
`REFERENCE` with seven axes and no `tuning` key, and four assertions count axes
or unmeasured axes. Adding an eighth gate changes all of them. Step 4 below
updates them, and that is part of this task, not a surprise you meet as four red
tests with no instruction.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compare.py` before `if __name__`:

```python
class TuningAxisTests(unittest.TestCase):
    def test_the_same_tuning_passes(self):
        result = c.score(REFERENCE, dict(REFERENCE))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'PASS')

    def test_an_enharmonic_spelling_is_the_same_tuning(self):
        result = c.score(REFERENCE, dict(REFERENCE, tuning='Drop Db'))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'PASS')

    def test_a_neighbouring_tuning_fails_rather_than_warning(self):
        result = c.score(REFERENCE, dict(REFERENCE, tuning='drop D'))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'FAIL')

    def test_an_unmeasured_tuning_is_unknown_not_a_pass(self):
        candidate = {k: v for k, v in REFERENCE.items() if k != 'tuning'}
        result = c.score(REFERENCE, candidate)
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'UNKNOWN')

    def test_a_tuning_that_is_not_a_string_is_unknown_not_a_crash(self):
        result = c.score(REFERENCE, dict(REFERENCE, tuning=7))
        axis = next(a for a in result['axes'] if a['axis'] == 'tuning')
        self.assertEqual(axis['verdict'], 'UNKNOWN')
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

- [ ] **Step 4: Update the four assertions the new axis moves**

In `tests/test_compare.py`. Every number below was measured by scoring the
updated `REFERENCE` through an eight gate `compare`, not reasoned about:

| Edit | From | To |
|---|---|---|
| Add `'tuning': 'drop C#'` to `REFERENCE` | absent | present |
| `len(result['axes'])` | 7 | 8 |
| `result['unmeasured']` in the partial-measurement counts test | 5 | 6 |
| `verdicts.count('UNKNOWN')` in the all-axes test | 6 | 7 |
| both `result['measured']` assertions | 6 | 7 |
| both `result['unmeasured'] == 1` assertions | 1 | **unchanged, still 1** |

The last two rows are the ones that bite. Revision 2 told you to change the
`unmeasured == 1` assertions to 2 and said nothing about `measured` or the
`UNKNOWN` count. Both were wrong: adding a tuning axis that the candidate DOES
carry moves `measured` from 6 to 7 and leaves `unmeasured` at 1.

Derive each number from the test's own setup before you change it. Neither this
table nor the existing assertion is authoritative; the code is. If your reading
disagrees with this table, say so in the pull request with the output you got.

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK, with the count above the 97 baseline and nothing red.

- [ ] **Step 6: Commit**

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

**Three repo invariants this task must not break.** Each is a bug the repo
already fixed once and documents in a comment.

1. `import facts` goes **inside** `cmd_facts`, never at module level. See the
   comment at `scripts/deconstruct.py:22`.
2. `secure_config_dir()`, never `config_dir()`, for the cache root. See the
   docstring at `scripts/deconstruct.py:67` and the existing call at line 549.
3. Wrap the module's own errors in `SkillError` so the authored message reaches
   the user. The top-level handler at line 730 prints authored text only for
   `SkillError`; anything else becomes `ERROR: <TypeName> ... Details
   suppressed to protect secrets`. `cmd_separate` wraps at line 552. Without
   this, `StemAdoptionError`'s carefully written message is dead text.

- [ ] **Step 1: Add the command function**

Above `def main():` in `scripts/deconstruct.py`:

```python
def cmd_facts(args):
    import facts as facts_mod
    out = args.out or (Path.cwd() / 'reports')
    out.mkdir(parents=True, exist_ok=True)
    try:
        sheet = facts_mod.fact_sheet(args.audio, stems_dir=args.stems,
                                     cache_root=secure_config_dir() / 'cache')
    except (facts_mod.FactError, facts_mod.StemAdoptionError) as exc:
        raise SkillError(str(exc)) from None
    write_json(out / 'facts.json', sheet)
    (out / 'facts.md').write_text(facts_mod.render_markdown(sheet),
                                  encoding='utf-8')
    write_json(out / 'scorable.json', facts_mod.scorable(sheet))
    graded = {}
    for entry in sheet['facts'].values():
        graded[entry['confidence']] = graded.get(entry['confidence'], 0) + 1
    print(f'FACTS_WRITTEN={out / "facts.json"}')
    print(f'SCORABLE_WRITTEN={out / "scorable.json"}')
    for grade in ('KNOW', 'INFER', 'UNKNOWN'):
        print(f'{grade}={graded.get(grade, 0)}')
    unknown = sorted(a for a, e in sheet['facts'].items()
                     if e['confidence'] == 'UNKNOWN')
    if unknown:
        print(f'UNRESOLVED={",".join(unknown)}')
```

`write_json` is whatever atomic JSON writer this file already uses for
`measurements.json`. Find it and use it rather than adding a second one; if the
existing writer is not reusable, use `json.dumps(..., indent=2,
allow_nan=False)` through the same `tempfile.mkstemp` then `os.replace` pattern
the module already has, and say in the pull request which you did.

The default output is `./reports`, matching `analyze`, because `.gitignore`
already excludes `reports/` and defaulting to the bare working directory would
drop three untracked files into the repo root.

- [ ] **Step 2: Register and dispatch**

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

- [ ] **Step 3: Verify the command exists and doctor still survives a broken install**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
.venv/bin/python scripts/deconstruct.py facts --help
python3 scripts/deconstruct.py doctor
```

Expected: usage text showing `--stems`, and then `doctor` printing its JSON
under the bare system interpreter, which has no librosa. That second command is
the actual test of the lazy import rule, and the unit suite cannot perform it
because the suite runs with librosa installed.

- [ ] **Step 4: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Commit**

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
- Produces: a script printing one `TRACK=... STABLE=...` line per track and a final `CORPUS_STABLE=<n>/3`.

- [ ] **Step 1: Write the known values file**

Create `<desk>/evidence/known-murder-she-wrote.json`:

```json
{
  "tempo_bpm": 80.7,
  "key": "F# minor",
  "tuning": "drop C#",
  "intro_seconds": 12.1,
  "lra_lu": 4.1
}
```

Five axes, each with ground truth established outside this pipeline. What is
absent, and why, matters as much as what is present:

- `section_count` is absent because no method resolved it. Sixteen were tried.
  See `SECTIONS-research.md`.
- `low_end_share` is absent because 16.4 percent could not be reproduced by any
  of eight readings, which span 10.8 to 58.0 on this track. Putting a figure
  here that this pipeline cannot produce would make the axis fail forever;
  putting this pipeline's own figure here would make it pass forever. Neither
  is a measurement. The axis is scored at the exit bar, where both sides run
  through the same function.
- `lead_register_midi` is absent for the same reason in the other direction:
  the parent spec names F sharp 2, nothing in this pipeline has validated that,
  and the yin octave errors documented on the guitar stem make it likely to be
  wrong. It is measured and reported, and it becomes a gate at the exit bar.

- [ ] **Step 2: Write the corpus script**

Create `scripts/corpus_check.py`:

```python
#!/usr/bin/env python3
"""Run every corpus track twice and report whether the sheet held still.

Stability is a gate rather than an assumption because a fact sheet that moves
between runs cannot support a comparison. Note that a rerun here does NOT
re-exercise separation: the stems are cached by source hash, so the second
call reads the same stems. This gate proves the measurement layer is
deterministic, not the separation layer.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts as facts_mod

HOME = Path(os.path.expanduser('~'))
DESKTOP = HOME / 'Desktop' / 'mydaiarytoyou!'
# Axes every track must resolve. section_count is deliberately absent: it is
# UNKNOWN by construction on every track and always will be.
CORE_AXES = ('tempo', 'key', 'tuning', 'intro_seconds', 'loudness')

CORPUS = [
    {'name': 'Murder, She Wrote',
     'audio': HOME / 'Downloads' /
              'mydiarytoyou! - Murder, She Wrote (Official Visualizer).mp3',
     'stems': None},
    {'name': 'The Danger of Caring',
     'audio': DESKTOP / 'The Danger of Caring' /
              'mydiarytoyou! - The Danger of Caring (Official Visualizer).mp3',
     'stems': DESKTOP / 'The Danger of Caring'},
    {'name': 'Wrong Turn',
     'audio': DESKTOP / 'Wrong Turn' /
              'mydiarytoyou! - Wrong Turn (Official Visualizer).mp3',
     'stems': DESKTOP / 'Wrong Turn'},
]


def cache_root():
    """Honour DECONSTRUCT_AUDIO_CONFIG_DIR, which relocates the whole dir."""
    override = os.environ.get('DECONSTRUCT_AUDIO_CONFIG_DIR')
    base = Path(override) if override else HOME / '.config' / 'deconstruct-audio'
    return base / 'cache'


def stable(sheet_a, sheet_b):
    a, b = dict(sheet_a), dict(sheet_b)
    a.pop('generated_at', None)
    b.pop('generated_at', None)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def slug(name):
    return name.lower().replace(',', '').replace(' ', '-')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rerun', action='store_true',
                        help='Measure each track twice and compare.')
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()

    held, checked, resolved = 0, 0, 0
    for track in CORPUS:
        if not track['audio'].exists():
            print(f'TRACK={track["name"]} STABLE=missing PATH={track["audio"]}')
            continue
        first = facts_mod.fact_sheet(track['audio'], stems_dir=track['stems'],
                                     cache_root=cache_root())
        if args.rerun:
            second = facts_mod.fact_sheet(track['audio'],
                                          stems_dir=track['stems'],
                                          cache_root=cache_root())
            ok = stable(first, second)
            checked += 1
            held += 1 if ok else 0
            state = 'yes' if ok else 'no'
        else:
            # Never print yes for something nothing compared. Revision 1 did,
            # and a run without the flag reported CORPUS_STABLE=3/3 having
            # compared nothing at all.
            state = 'unchecked'
        projected = facts_mod.scorable(first)
        unresolved = sorted(a for a, e in first['facts'].items()
                            if e['confidence'] == 'UNKNOWN')
        # A track that silently loses a core axis must not leave the gate green.
        # Revision 2 printed CORPUS_STABLE=3/3 and exit 0 for a corpus where one
        # track had lost its tuning axis entirely, because an axis that resolves
        # to UNKNOWN is perfectly stable across reruns.
        lost = [a for a in CORE_AXES if a in unresolved]
        resolved += 0 if lost else 1
        print(f'TRACK={track["name"]} STABLE={state} '
              f'CORE={"ok" if not lost else "lost:" + ",".join(lost)} '
              f'SCORABLE={json.dumps(projected, sort_keys=True)} '
              f'UNRESOLVED={",".join(unresolved) or "none"}')
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f'facts-{slug(track["name"])}.json').write_text(
                json.dumps(first, indent=2, allow_nan=False), encoding='utf-8')
            (args.out / f'scorable-{slug(track["name"])}.json').write_text(
                json.dumps(projected, indent=2, allow_nan=False),
                encoding='utf-8')
    print(f'CORPUS_RESOLVED={resolved}/{len(CORPUS)} CORE={",".join(CORE_AXES)}')
    if args.rerun:
        print(f'CORPUS_STABLE={held}/{len(CORPUS)}')
        return 0 if (held == len(CORPUS) and resolved == len(CORPUS)) else 2
    print(f'CORPUS_STABLE=unchecked/{len(CORPUS)}')
    return 0 if resolved == len(CORPUS) else 2


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 3: Run the corpus**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
.venv/bin/python scripts/corpus_check.py --rerun --out $DESK/evidence
```
Expected, both lines:

```
CORPUS_RESOLVED=3/3 CORE=tempo,key,tuning,intro_seconds,loudness
CORPUS_STABLE=3/3
```

`CORPUS_RESOLVED` is not decoration either. Revision 2's gate printed
`CORPUS_STABLE=3/3` and exited 0 for a corpus in which Wrong Turn had lost its
tuning axis completely, because an axis that resolves to `UNKNOWN` is perfectly
stable across reruns. A sheet can hold still and still say nothing.

- [ ] **Step 4: Score the reference against its known values. This is the entry bar.**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
.venv/bin/python scripts/deconstruct.py compare \
  $DESK/evidence/known-murder-she-wrote.json \
  $DESK/evidence/scorable-murder-she-wrote.json
```

Expected, **both lines**:

```
MEASURED=5 UNMEASURED=3
VERDICT=PASS
```

**`MEASURED=5` is not decoration and it is not optional.** `compare` computes
its verdict only from axes present on both sides, and `scorable` omits any axis
graded `UNKNOWN`. Without this assertion, a sheet that graded tempo, key,
tuning and intro `UNKNOWN` would project nothing, `compare` would find nothing
to disagree about, and `VERDICT=PASS` would print over a sheet that measured
nothing. The critic demonstrated this against the repo's own existing test. If
you see `VERDICT=PASS` with `MEASURED` below 5, the bar is not met and the
correct report is that it is not met.

The three unmeasured axes are `section_count`, `low_end_share` and
`lead_register_midi`, each absent from the known values for a reason stated in
Step 1.

**If an axis fails, report the actual delta. Do not move a gate, do not
re-grade the axis `UNKNOWN`, and do not change the measurement definition until
the number lands inside an existing gate.** All three are ways of manufacturing
a pass, and the third is the one this project came closest to doing: the low end
axis had a reading available that cleared the gate by 0.14 points and it was
rejected for exactly that reason.

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

After the `tempo` row:

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
`KNOW`, `INFER` or `UNKNOWN`. Constructing a fact without a method or a grade
raises rather than producing one, so an ungraded number cannot reach the sheet.

`UNKNOWN` means a method was tried and did not resolve, and the note says which
methods. Section count is the standing example: sixteen segmentation methods
were run against a three track corpus and none generalised, so the sheet emits
section boundaries and refuses to state a count. A number that is about half
likely to be wrong is worse than no number, because a stated number invites
downstream use that a missing one does not.

`scorable.json` beside the sheet projects it onto the axes `compare` scores, so
a reference and a candidate go through the same projection and cannot be
compared on different terms by accident. An `UNKNOWN` axis is left out of that
projection, which means a `PASS` from `compare` must always be read next to its
`MEASURED=` count.
```

- [ ] **Step 3: Add two entries to the "Limits worth knowing" list in `README.md`**

```markdown
- **Section count is not measured.** Boundaries are. Sixteen structure
  segmentation methods failed to generalise across a three track corpus, so the
  sheet reports `UNKNOWN` for the count rather than a number it has not earned.
- **Low end share is a pinned definition, not a universal one.** It is the per
  frame mean magnitude share below 150 Hz at `n_fft` 2048, mono, 22050 Hz. Eight
  defensible readings of the same phrase span 10.8 to 58.0 percent on one track,
  so a figure from another tool is not comparable to this one. Both sides of a
  comparison run through this function or the comparison means nothing.
```

- [ ] **Step 4: Add the command and its rules to `SKILL.md`**

Follow the format the existing commands use in that file. State the `--stems`
flag, and state the rule that binds the agent: never promote an `UNKNOWN` axis
to a stated fact when writing prose from the sheet, and always read a `compare`
verdict next to its `MEASURED` count.

- [ ] **Step 5: Run the full suite one more time**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add README.md SKILL.md
git commit -m "docs: the facts command"
```

---

## Self-Review

**Spec coverage.** The Fact object is Task 1. Stem adoption is Task 2. The
measurement axes are Tasks 3, 4 and 5, with the band declared on every fact that
reads one. The projection onto compare is Task 5. The tuning axis compare was
missing, and the four existing assertions it moves, are Task 6. The command is
Task 7. The entry bar is Task 8. Documentation is Task 9.

Two spec axes changed shape and both are argued in the plan body rather than
quietly dropped: `section_count` is `UNKNOWN` with its evidence, and
`low_end_share` has a pinned definition and moves from the entry bar to the exit
bar. One axis was added that the spec did not have, `instrumentation`, because
the parent spec's "six stems, all non-silent" gate would fail a correct
separation of a track with no piano.

Not covered here by design, each with its own plan and worktree: the MIDI
emitter, the research branch, the Brain wiring.

**Placeholders.** Task 5 gives every axis builder's body. Revision 1 described
eleven of them in prose and the critic found that one, `_harmonic_rhythm_fact`,
was called but never specified at all, and that `_register` did not match the
calling convention it was wired into. Both are written out here. The two
numeric constants that cannot be known before measuring real audio,
`THIRD_RATIO` and `ACTIVE_DB`, are called out as measure-then-set with an
explicit instruction not to loosen an assertion instead, and `ACTIVE_DB` is
additionally shown to be insensitive across a 10 dB spread.

**Type consistency.** Every axis builder has the signature
`(paths, loaded, mix, sr, local, built) -> dict` and is invoked through
`BUILDERS`, so a wrong arity is a `TypeError` at the first run rather than a
silent miswire. `_register` is a helper with its own signature and is called
only by the two register builders. `band_limit` is always reached as
`chords_mod.band_limit(y, sr, low, high)`; revision 1 called it with three
arguments and no `sr`. `adopt_stems` and `stems.separate` both return
`dict[str, Path]`, so `fact_sheet` consumes either without branching beyond the
origin label. `chord_sequence` entries carry `third_present`, which Task 4 tests
and the MIDI plan consumes. `PROJECTION` targets are checked against
`compare.GATES` by a test rather than by eye. `built` is read by four builders
and each guards for a missing or `UNKNOWN` predecessor rather than assuming one.
