# Chord MIDI Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write the harmonic skeleton of a measured track to a MIDI file that a generator can be handed as an anchor, without the emitter inventing a single note it did not measure.

**Architecture:** One service module, `midi_emit.py`, that takes a fact sheet and returns a `mido.MidiFile`. One thin command on `deconstruct.py`. The module depends on the fact sheet's schema and on nothing else in this project, so it can be built in parallel with the fact sheet itself against a fixture.

**Tech Stack:** Python 3.10+, `mido` (pure Python, no compiled dependencies).

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

## Global Constraints

- Python 3.10 or newer.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`.
- Baseline is 97 tests on `f021646`, OK, one skipped. The fact sheet worktree adds to that count in parallel, so compare against your own branch point rather than against 97.
- Commands orchestrate. Service modules own the reusable how. Invariant from `AGENTS.md`.
- The emitter writes no pitch it cannot trace to a measured chord entry.
- No network call. No audio decoding. This module reads a dict and writes a file.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## The input contract

`midi_emit` consumes the fact sheet produced by the fact sheet plan. It reads
exactly three things and ignores the rest:

```python
sheet['facts']['tempo']['value']            # float, BPM
sheet['facts']['chords']['value']           # list of chord entries
sheet['facts']['chords']['confidence']      # KNOW | INFER | UNKNOWN
```

Each chord entry:

```python
{'start_s': 5.55, 'end_s': 8.52, 'root': 'F#', 'quality': 'power',
 'root_share': 0.31, 'root_margin': 1.42,
 'third_present': False, 'fifth_present': True}
```

**There is no `sections` fact.** An earlier draft of this plan named
`sheet['facts']['sections']['value']` as a fourth input and called the contract
frozen. It was not. The fact sheet emits `section_boundaries`, a bare list of
floats, and `section_count`, which is `None` at `UNKNOWN` by construction
because sixteen segmentation methods failed to resolve it. No real sheet has a
`sections` key at all.

The emitter never actually read it, so the code was right and the contract was
wrong. But an implementer building to the written contract would have hit a
`KeyError` on first integration while every unit test passed against a stale
fixture, which is the worst shape a defect can take.

Build against the fixture below, which matches the real shape, and run Task 5's
integration check before calling this done.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/midi_emit.py` (create) | Chord entries to a `mido.MidiFile`. Pure, no file reads. |
| `scripts/deconstruct.py` (modify) | The `midi` command. |
| `tests/test_midi.py` (create) | Note content, tempo header, the absent third rule, the low confidence rule. |
| `requirements.txt` (modify) | Adds `mido`. |
| `tests/fixtures/facts-sample.json` (create) | A hand written fact sheet so this plan has no dependency on the other worktree. |

---

### Task 1: The dependency and the fixture

**Files:**
- Modify: `requirements.txt`
- Create: `tests/fixtures/facts-sample.json`

**Interfaces:**
- Produces: a fixture fact sheet every later task reads.

- [ ] **Step 1: Add the dependency**

Append to `requirements.txt`:

```text
mido>=1.3,<2
```

- [ ] **Step 2: Install it**

```bash
/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m pip install "mido>=1.3,<2"
```

Expected: `Successfully installed mido-...`. `mido` is pure Python and pulls in
`packaging` only. If it tries to build anything, stop and report it rather than
installing a compiler toolchain.

- [ ] **Step 3: Write the fixture**

Create `tests/fixtures/facts-sample.json`. Four bars at 80 BPM in 4/4 makes each
bar exactly 3.0 seconds, which keeps every timing assertion in this plan an exact
integer of ticks rather than a rounding argument.

```json
{
  "schema": "deconstruct-audio/facts/1",
  "generated_at": "2026-09-17T00:00:00Z",
  "source": {"path": "fixture.wav", "sha256": "0", "duration_s": 16.0},
  "stems_from": "adopted",
  "facts": {
    "tempo": {"value": 80.0, "unit": "bpm", "stem": "drums", "band_hz": null,
              "method": ["tempogram-peak"], "confidence": "KNOW",
              "suno_actionable": "direct", "note": null},
    "section_boundaries": {"value": [0.0, 3.0, 9.0], "unit": "seconds",
                 "stem": "mix", "band_hz": null,
                 "method": ["agglomerative-clustering"], "confidence": "INFER",
                 "suno_actionable": "direct", "note": null},
    "section_count": {"value": null, "unit": "count", "stem": "mix",
                 "band_hz": null, "method": ["agglomerative-clustering"],
                 "confidence": "UNKNOWN", "suno_actionable": "none",
                 "note": "no method generalised across the corpus"},
    "chords": {"value": [
        {"start_s": 3.0, "end_s": 6.0, "root": "F#", "quality": "power",
         "root_share": 0.31, "root_margin": 1.55,
         "third_present": false, "fifth_present": true},
        {"start_s": 6.0, "end_s": 9.0, "root": "A", "quality": "major",
         "root_share": 0.28, "root_margin": 1.47,
         "third_present": true, "fifth_present": true},
        {"start_s": 9.0, "end_s": 12.0, "root": "E", "quality": "minor",
         "root_share": 0.26, "root_margin": 1.38,
         "third_present": true, "fifth_present": true},
        {"start_s": 12.0, "end_s": 15.0, "root": "B", "quality": "power",
         "root_share": 0.19, "root_margin": 1.04,
         "third_present": false, "fifth_present": false}],
      "unit": "sequence", "stem": "guitar", "band_hz": [150, 2500],
      "method": ["beat-sync-chroma"], "confidence": "INFER",
      "suno_actionable": "midi_only", "note": null}
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/fixtures/facts-sample.json
git commit -m "chore: mido and a fact sheet fixture for the MIDI emitter"
```

---

### Task 2: Pitch selection

**Files:**
- Create: `scripts/midi_emit.py`
- Create: `tests/test_midi.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `chord_pitches(entry, octave=3) -> list[int]`, `NOTES`, `root_midi(name, octave) -> int`, `MidiEmitError`.

The rule this task encodes: a chord whose third was not measured gets root and
fifth, not a guessed third. Most distorted guitar is genuinely ambiguous between
major and minor, and the reference track reads 35 percent major against 21
percent minor on the same root. Writing a third there would be the emitter
inventing information.

- [ ] **Step 1: Write the failing test**

Create `tests/test_midi.py`:

```python
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import midi_emit as m

FIXTURE = json.loads((ROOT / 'tests' / 'fixtures' / 'facts-sample.json')
                     .read_text(encoding='utf-8'))


def entry(**over):
    base = {'start_s': 0.0, 'end_s': 3.0, 'root': 'A', 'quality': 'minor',
            'root_share': 0.3, 'root_margin': 1.5,
            'third_present': True, 'fifth_present': True}
    base.update(over)
    return base


class PitchTests(unittest.TestCase):
    def test_a_minor_chord_is_root_minor_third_fifth(self):
        self.assertEqual(m.chord_pitches(entry(root='A', quality='minor')),
                         [57, 60, 64])

    def test_a_major_chord_is_root_major_third_fifth(self):
        self.assertEqual(m.chord_pitches(entry(root='A', quality='major')),
                         [57, 61, 64])

    def test_a_power_chord_is_root_and_fifth_with_no_third(self):
        pitches = m.chord_pitches(entry(root='A', quality='power',
                                        third_present=False))
        self.assertEqual(pitches, [57, 64])
        self.assertNotIn(60, pitches)
        self.assertNotIn(61, pitches)

    def test_an_absent_third_beats_a_quality_label_that_claims_one(self):
        # A sheet that says minor but measured no third still gets no third.
        pitches = m.chord_pitches(entry(quality='minor', third_present=False))
        self.assertEqual(len(pitches), 2)

    def test_an_absent_fifth_still_writes_the_fifth_for_a_power_chord(self):
        # Root alone is not a chord. A power chord names its fifth by definition.
        pitches = m.chord_pitches(entry(quality='power', third_present=False,
                                        fifth_present=False))
        self.assertEqual(pitches, [57, 64])

    def test_every_root_name_resolves_including_flats(self):
        for name in ('C', 'C#', 'Db', 'F#', 'Gb', 'A#', 'Bb', 'B'):
            self.assertIsInstance(m.root_midi(name, 3), int)

    def test_an_unknown_root_name_is_an_error_not_a_default(self):
        with self.assertRaises(m.MidiEmitError):
            m.root_midi('H', 3)

    def test_pitches_stay_inside_the_midi_range(self):
        for octave in (-1, 0, 8, 9):
            for p in m.chord_pitches(entry(), octave=octave):
                self.assertGreaterEqual(p, 0)
                self.assertLessEqual(p, 127)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_midi -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'midi_emit'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/midi_emit.py`:

```python
#!/usr/bin/env python3
"""The harmonic skeleton as MIDI.

Chord names in a text prompt are discarded by the target generator, which is
why this file exists: it is the channel that carries harmony when text cannot.

The emitter writes no pitch it did not measure. Where a third was not measured
it writes root and fifth, because most distorted guitar is genuinely ambiguous
between major and minor and a guessed third would be this tool inventing
information. That is the defect the whole project was built against.
"""
NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
FLATS = {'DB': 'C#', 'EB': 'D#', 'GB': 'F#', 'AB': 'G#', 'BB': 'A#'}
MAJOR_THIRD, MINOR_THIRD, FIFTH = 4, 3, 7
# How far the root must beat the second strongest pitch class before the bar
# gets a chord rather than a sustained root.
#
# An earlier draft thresholded on `strength`, the root's share of a normalised
# 12 bin chroma. That is not a confidence: its floor is 0.083 by construction,
# and at 0.12 the rule fired on 3 bars out of 163 across the whole corpus, so
# it was close to a no op wearing the name of a safeguard.
#
# 1.05, not 1.25. Measured across all three corpus fact sheets, 163 bars:
#
#   murder    45 bars  min 1.001  median 1.149  max 1.777
#   danger    65 bars  min 1.001  median 1.126  max 1.657
#   wrongturn 53 bars  min 1.001  median 1.183  max 3.144
#
# 1.25 sits ABOVE the median on every track and would turn 122 of 163 bars into
# sustained roots, 75 percent of the corpus. The constant it replaced fired on
# 3 bars of 163. Both were chosen without looking at the distribution and both
# are wrong, in opposite directions.
#
# 1.05 is set from what the number means rather than from a target hit rate. A
# margin of exactly 1.0 is a tie between two pitch classes, so 1.05 flags the
# bars where the winning root beat the runner up by less than five percent.
# That is the condition a sustained root is FOR.
#
# Task 3 Step 5 re-measures this against the real sheets, before Task 4 runs the
# command end to end. If the distribution argues for a different cut, use it and
# say why.
MIN_MARGIN = 1.05


class MidiEmitError(Exception):
    pass


def root_midi(name, octave=3):
    """MIDI note number for a root name, C4 as 60."""
    if not isinstance(name, str) or not name.strip():
        raise MidiEmitError('a chord root must be a note name')
    token = name.strip().upper()
    token = FLATS.get(token, token)
    if token not in NOTES:
        raise MidiEmitError(f'{name!r} is not a note name')
    value = NOTES.index(token) + (octave + 1) * 12
    if not 0 <= value <= 127:
        raise MidiEmitError(f'{name}{octave} falls outside the MIDI range')
    return value


def chord_pitches(entry, octave=3):
    """Root position block chord. No inversions, no invented thirds."""
    octave = max(-1, min(8, int(octave)))
    root = root_midi(entry['root'], octave)
    while root + FIFTH > 127:
        root -= 12
    while root < 0:
        root += 12
    if not entry.get('third_present'):
        return [root, root + FIFTH]
    quality = entry.get('quality')
    if quality == 'major':
        third = MAJOR_THIRD
    elif quality == 'minor':
        third = MINOR_THIRD
    else:
        return [root, root + FIFTH]
    return [root, root + third, root + FIFTH]
```

Note the guard order: `third_present` is checked before `quality`. A sheet whose
quality label disagrees with its own measurement loses to the measurement.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_midi -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/midi_emit.py tests/test_midi.py
git commit -m "feat: chord pitches that write no third they did not measure"
```

---

### Task 3: The file

**Files:**
- Modify: `scripts/midi_emit.py`
- Modify: `tests/test_midi.py`

**Interfaces:**
- Consumes: `chord_pitches` from Task 2.
- Produces: `progression(sheet, octave=3, min_margin=MIN_MARGIN, ticks_per_beat=480, align=True) -> mido.MidiFile`, `low_confidence_bars(sheet, min_margin=MIN_MARGIN) -> list[int]`, `MIN_MARGIN`, `LOW_CONFIDENCE_NOTE`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_midi.py` before `if __name__`:

```python
import tempfile

import mido


class FileTests(unittest.TestCase):
    def setUp(self):
        self.mid = m.progression(FIXTURE)

    def test_the_header_carries_the_measured_tempo(self):
        tempos = [msg.tempo for track in self.mid.tracks for msg in track
                  if msg.type == 'set_tempo']
        self.assertEqual(len(tempos), 1)
        self.assertAlmostEqual(mido.tempo2bpm(tempos[0]), 80.0, places=1)

    def test_it_writes_one_chord_per_bar_for_every_measured_chord(self):
        starts = set()
        absolute = 0
        for msg in self.mid.tracks[0]:
            absolute += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                starts.add(absolute)
        self.assertEqual(len(starts), 4)

    def test_the_clip_starts_where_the_first_measured_chord_starts(self):
        first_on = None
        absolute = 0
        for msg in self.mid.tracks[0]:
            absolute += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                first_on = absolute
                break
        expected = int(round(3.0 * self.mid.ticks_per_beat * 80.0 / 60.0))
        self.assertEqual(first_on, expected)

    def test_a_zero_width_window_is_an_error_not_a_clamp(self):
        bad = json.loads(json.dumps(FIXTURE))
        bad['facts']['chords']['value'][1]['end_s'] = \
            bad['facts']['chords']['value'][1]['start_s']
        with self.assertRaises(m.MidiEmitError):
            m.progression(bad)

    def test_windows_that_run_backwards_are_an_error(self):
        bad = json.loads(json.dumps(FIXTURE))
        bad['facts']['chords']['value'][2]['start_s'] = 0.0
        with self.assertRaises(m.MidiEmitError):
            m.progression(bad)

    def test_the_clip_ends_where_the_last_measured_chord_ends(self):
        # The start was checked and the end was not, and the end is where a
        # uniform bar width accumulated 4.114 s of drift on a real track.
        last_end = float(FIXTURE['facts']['chords']['value'][-1]['end_s'])
        self.assertAlmostEqual(self.mid.length, last_end, delta=0.05)

    def test_alignment_can_be_turned_off(self):
        loose = m.progression(FIXTURE, align=False)
        first_on = None
        absolute = 0
        for msg in loose.tracks[0]:
            absolute += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                first_on = absolute
                break
        self.assertEqual(first_on, 0)

    def test_the_fourth_bar_is_a_sustained_root_because_its_margin_is_low(self):
        bar = self._notes_in_bar(3)
        self.assertEqual(len(bar), 1, f'expected a sustained root, got {bar}')

    def test_the_second_bar_is_a_full_major_triad(self):
        self.assertEqual(len(self._notes_in_bar(1)), 3)

    def test_the_first_bar_is_a_power_chord_with_no_third(self):
        notes = sorted(self._notes_in_bar(0))
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[1] - notes[0], 7)

    def test_every_note_on_has_a_matching_note_off(self):
        open_notes = {}
        for msg in self.mid.tracks[0]:
            if msg.type == 'note_on' and msg.velocity > 0:
                open_notes[msg.note] = open_notes.get(msg.note, 0) + 1
            elif msg.type == 'note_off' or (msg.type == 'note_on'
                                            and msg.velocity == 0):
                open_notes[msg.note] = open_notes.get(msg.note, 0) - 1
        self.assertTrue(all(v == 0 for v in open_notes.values()), open_notes)

    def test_it_survives_a_round_trip_through_a_real_midi_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'progression.mid'
            self.mid.save(str(path))
            reread = mido.MidiFile(str(path))
            self.assertEqual(reread.ticks_per_beat, self.mid.ticks_per_beat)
            self.assertEqual(sum(1 for t in reread.tracks for msg in t
                                 if msg.type == 'note_on' and msg.velocity > 0),
                             sum(1 for t in self.mid.tracks for msg in t
                                 if msg.type == 'note_on' and msg.velocity > 0))

    def test_no_chords_yields_an_error_rather_than_an_empty_file(self):
        empty = json.loads(json.dumps(FIXTURE))
        empty['facts']['chords']['value'] = []
        with self.assertRaises(m.MidiEmitError):
            m.progression(empty)

    def test_an_unknown_chords_grade_yields_an_error_not_a_silent_clip(self):
        unknown = json.loads(json.dumps(FIXTURE))
        unknown['facts']['chords']['confidence'] = 'UNKNOWN'
        unknown['facts']['chords']['value'] = None
        with self.assertRaises(m.MidiEmitError):
            m.progression(unknown)

    def test_a_missing_tempo_yields_an_error_rather_than_a_default_120(self):
        no_tempo = json.loads(json.dumps(FIXTURE))
        no_tempo['facts'].pop('tempo')
        with self.assertRaises(m.MidiEmitError):
            m.progression(no_tempo)

    def _notes_in_bar(self, index):
        """Note numbers whose note_on lands inside bar `index`, counted from
        the first sounding bar rather than from tick zero, because the clip is
        offset to the first measured chord's start time."""
        bar_ticks = 4 * self.mid.ticks_per_beat
        lead = int(round(3.0 * self.mid.ticks_per_beat * 80.0 / 60.0))
        low, high = lead + index * bar_ticks, lead + (index + 1) * bar_ticks
        out, absolute = [], 0
        for msg in self.mid.tracks[0]:
            absolute += msg.time
            if msg.type == 'note_on' and msg.velocity > 0 and low <= absolute < high:
                out.append(msg.note)
        return out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_midi -v`
Expected: FAIL, `AttributeError: module 'midi_emit' has no attribute 'progression'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/midi_emit.py`:

```python
import mido

BEATS_PER_BAR = 4
VELOCITY = 80
LOW_CONFIDENCE_NOTE = ('chord confidence below threshold, so this bar carries a '
                       'sustained root rather than a harmony nothing measured')


def _require(sheet, axis):
    entry = sheet.get('facts', {}).get(axis)
    if not entry:
        raise MidiEmitError(
            f'the fact sheet carries no {axis}, and this emitter will not '
            f'substitute a default for a measurement that was never made')
    if entry.get('confidence') == 'UNKNOWN' or entry.get('value') in (None, [], {}):
        raise MidiEmitError(
            f'{axis} is graded {entry.get("confidence")} with value '
            f'{entry.get("value")!r}; there is nothing here to write')
    return entry['value']


def progression(sheet, octave=3, min_margin=MIN_MARGIN, ticks_per_beat=480,
                align=True):
    """One bar per measured chord, at the measured tempo, root position."""
    bpm = _require(sheet, 'tempo')
    sequence = _require(sheet, 'chords')
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        raise MidiEmitError(f'{bpm!r} is not a tempo')

    mid = mido.MidiFile(type=0, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    # The header tempo is nominal and the bar widths are measured, so on a
    # track whose beat grid breathes the two disagree: on Wrong Turn 28 of 52
    # bar windows deviate from the nominal bar. That is the right trade for an
    # anchor clip, whose job is to land on the same timeline as the reference,
    # but it means the header is a label rather than a description. A tempo map
    # would describe it; nothing in the pipeline needs one yet.
    track.append(mido.MetaMessage('set_tempo',
                                  tempo=mido.bpm2tempo(float(bpm)), time=0))
    track.append(mido.MetaMessage('time_signature', numerator=BEATS_PER_BAR,
                                  denominator=4, time=0))

    bar_ticks = BEATS_PER_BAR * ticks_per_beat
    # Align to the measured timeline. The first measured chord on the reference
    # track begins at 5.55 s, not at zero, and an earlier draft wrote it at
    # tick 0 while its self review claimed section timings were mirrored. What
    # was actually inherited was the chord ORDER. A clip handed to a generator
    # as a timeline anchor that starts 5.55 s early is not an anchor.
    ticks_per_second = ticks_per_beat * float(bpm) / 60.0

    # Each bar is placed AND sized from its own measured window, not written at
    # a uniform width from tick zero.
    #
    # Two separate defects came from the uniform version. It started the clip
    # 5.55 s early on the reference track, because the first measured chord does
    # not begin at zero. And it drifted: the bar windows come from a tracked
    # beat grid whose spacing follows the performance, so on Wrong Turn 28 of 52
    # interior windows deviate from the nominal bar and the clip finished 4.114
    # seconds late. A clip that ends four seconds late is no more an anchor than
    # one that starts five seconds early, and an earlier self review blamed that
    # drift on a single partial bar, which the window data contradicts.
    cursor = 0
    for index, entry in enumerate(sequence):
        margin = entry.get('root_margin')
        if margin is None or float(margin) < min_margin:
            pitches = [root_midi(entry['root'], octave)]
        else:
            pitches = chord_pitches(entry, octave)
        if align:
            start = int(round(float(entry.get('start_s') or 0.0) * ticks_per_second))
            end = int(round(float(entry.get('end_s') or 0.0) * ticks_per_second))
            width = end - start
            # Validate here, not later. max(1, ...) looks like a safe clamp and
            # is not: a zero width window leaves cursor one tick ahead of the
            # next start, progression returns happily with a negative delta
            # time in the message, and mido raises ValueError inside .save().
            # That lands in the top level handler, which prints
            # "ERROR: ValueError ... Details suppressed to protect secrets"
            # for what is a data problem in a file the user supplied. No real
            # sheet has such a window, 0 in 163 bars, which is exactly why the
            # failure would be rare and baffling.
            if width <= 0:
                raise MidiEmitError(
                    f'bar {index} spans {entry.get("start_s")} to '
                    f'{entry.get("end_s")} seconds, which is not a duration. '
                    f'The chord sequence in this fact sheet is not ordered or '
                    f'not well formed; the emitter will not invent a width.')
            if start < cursor:
                raise MidiEmitError(
                    f'bar {index} starts at {entry.get("start_s")} s, before '
                    f'bar {index - 1} ended. Chord windows must not overlap or '
                    f'run backwards.')
        else:
            start = index * bar_ticks
            width = bar_ticks
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message(
                'note_on', note=pitch, velocity=VELOCITY,
                time=(start - cursor) if offset == 0 else 0))
            if offset == 0:
                cursor = start
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message('note_off', note=pitch, velocity=0,
                                      time=width if offset == 0 else 0))
        cursor = start + width
    track.append(mido.MetaMessage('end_of_track', time=0))
    return mid


def low_confidence_bars(sheet, min_margin=MIN_MARGIN):
    """Bar indices that carry a sustained root, so the fact sheet can name them."""
    sequence = sheet.get('facts', {}).get('chords', {}).get('value') or []
    out = []
    for i, e in enumerate(sequence):
        margin = e.get('root_margin')
        if margin is None or float(margin) < min_margin:
            out.append(i)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_midi -v`
Expected: PASS, 23 tests

If `test_every_note_on_has_a_matching_note_off` fails, the delta time bookkeeping
in the note_off loop is wrong, not the test. In a mido track every message's
`time` is a delta from the previous message, so only the first note_off in a
chord carries the bar length and the rest carry zero. Fix the emitter.

- [ ] **Step 5: Measure the margin distribution and confirm MIN_MARGIN**

This runs BEFORE Task 4's end to end command, so the output pasted into the pull
request is the final behaviour rather than a value about to be replaced.

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
.venv/bin/python -c "
import json, statistics
from pathlib import Path
for path in sorted(Path('$DESK/evidence').glob('facts-*.json')):
    seq = json.loads(path.read_text())['facts']['chords']['value'] or []
    m = [e['root_margin'] for e in seq if e.get('root_margin') is not None]
    if not m:
        print(path.name, 'no margins'); continue
    for cut in (1.02, 1.05, 1.10, 1.25):
        flagged = sum(1 for x in m if x < cut)
        print(f'{path.name:40s} cut={cut:.2f} flagged={flagged:3d}/{len(m):3d} '
              f'({100*flagged/len(m):5.1f}%) median={statistics.median(m):.3f}')
"
```

Expected shape, not an exact number: 1.25 flags roughly three quarters of every
track, which is why it was rejected, and 1.05 flags a small tail. Put the table
in the pull request. If your measured distribution argues for a different cut,
change it and say why.

**What not to do.** Do not set it so a particular count of bars is flagged, and
do not set it so a test passes. One earlier constant fired on 3 bars in 163, a
safeguard that never fires wearing the name of one, and its replacement fired on
122, which is not a safeguard either.

- [ ] **Step 6: Commit**

```bash
git add scripts/midi_emit.py tests/test_midi.py
git commit -m "feat: write the measured progression to a real MIDI file"
```

---

### Task 4: The midi command

**Files:**
- Modify: `scripts/deconstruct.py`

**Interfaces:**
- Consumes: `midi_emit.progression`, `midi_emit.low_confidence_bars`.
- Produces: CLI `midi <facts.json> [--out FILE] [--octave N]`, printing `MIDI_WRITTEN=<path>`.

- [ ] **Step 1: Add the command function**

Above `def main():` in `scripts/deconstruct.py`:

```python
def cmd_midi(args):
    import midi_emit
    sheet = json.loads(args.facts.read_text(encoding='utf-8'))
    out = args.out or args.facts.parent / 'progression.mid'
    try:
        midi_emit.progression(sheet, octave=args.octave).save(str(out))
    except midi_emit.MidiEmitError as exc:
        raise SkillError(str(exc)) from None
    print(f'MIDI_WRITTEN={out}')
    sustained = midi_emit.low_confidence_bars(sheet)
    if sustained:
        print(f'SUSTAINED_ROOT_BARS={",".join(str(b) for b in sustained)}')
        print(midi_emit.LOW_CONFIDENCE_NOTE, file=sys.stderr)
```

Printing the sustained bars rather than hiding them is the point. A bar the
emitter could not resolve is visible in the output, not implied by a thinner
sounding clip.

- [ ] **Step 2: Register and dispatch**

With the other parsers in `main()`:

```python
    mp = sub.add_parser('midi')
    mp.add_argument('facts', type=Path)
    mp.add_argument('--out', type=Path, default=None)
    mp.add_argument('--octave', type=int, default=3)
```

With the other branches:

```python
    elif args.command == 'midi':
        cmd_midi(args)
```

- [ ] **Step 3: Verify the command end to end on the fixture**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
PY=.venv/bin/python
$PY scripts/deconstruct.py midi tests/fixtures/facts-sample.json --out /tmp/progression.mid
$PY -c "
import mido
m = mido.MidiFile('/tmp/progression.mid')
print('ticks_per_beat', m.ticks_per_beat, 'length_s', round(m.length, 2))
for msg in m.tracks[0][:8]:
    print(msg)
"
```
Expected: `MIDI_WRITTEN=/tmp/progression.mid`, `SUSTAINED_ROOT_BARS=3`, a
`set_tempo` matching 80 BPM, a first `note_on` at tick **1920** rather than 0
because the fixture's first chord starts at 3.0 s, and a length near 15
seconds. Paste this into the pull request as the after evidence.

At 80 BPM a beat is 0.75 s, so 3.0 s is four beats and 4 x 480 ticks is 1920.
An earlier draft of this step said 1440, which is 2.25 s, and contradicted the
test two tasks above it that computes `round(3.0 * ticks_per_beat * 80.0 / 60)`.
The test was right. If a number in this plan's prose disagrees with a number the
plan's own code computes, the code is authoritative and the prose is the
defect.

- [ ] **Step 4: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: the midi command"
```

---

### Task 5: Integration against a real fact sheet, and the margin constant

**Files:**
- Modify: `tests/test_midi.py`

**Why this task exists.** Every test so far runs against a fixture this plan
wrote. An earlier draft's fixture encoded a `sections` fact that no real sheet
produces, and all eighteen tests passed while the written contract was broken.
A fixture can only ever prove the emitter agrees with its author.

**Interfaces:**
- Consumes: a real `facts.json` from the fact sheet worktree.
- Produces: nothing new. This task measures and verifies.

- [ ] **Step 1: Add the integration test**

Append to `tests/test_midi.py` before `if __name__`:

```python
import os


@unittest.skipUnless(os.environ.get('DECONSTRUCT_AUDIO_FACTS'),
                     'set DECONSTRUCT_AUDIO_FACTS to a real facts.json')
class RealSheetTests(unittest.TestCase):
    """The fixture proves the emitter agrees with its author. This proves it
    agrees with the fact sheet."""

    def setUp(self):
        self.sheet = json.loads(
            Path(os.environ['DECONSTRUCT_AUDIO_FACTS']).read_text(encoding='utf-8'))

    def test_the_sheet_carries_every_field_the_contract_names(self):
        facts = self.sheet['facts']
        self.assertIn('tempo', facts)
        self.assertIn('chords', facts)
        for entry in facts['chords']['value']:
            for key in ('start_s', 'end_s', 'root', 'quality',
                        'root_share', 'root_margin', 'third_present'):
                self.assertIn(key, entry)

    def test_it_writes_a_clip_from_a_real_sheet(self):
        mid = m.progression(self.sheet)
        self.assertGreater(mid.length, 1.0)

    def test_the_clip_starts_at_the_first_measured_chord(self):
        mid = m.progression(self.sheet)
        first_start = float(self.sheet['facts']['chords']['value'][0]['start_s'])
        absolute = 0
        for msg in mid.tracks[0]:
            absolute += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                break
        seconds = mido.tick2second(
            absolute, mid.ticks_per_beat,
            mido.bpm2tempo(float(self.sheet['facts']['tempo']['value'])))
        self.assertAlmostEqual(seconds, first_start, delta=0.05)
```

- [ ] **Step 2: Measure the margin distribution and set MIN_MARGIN**

`MIN_MARGIN = 1.25` is a starting value and this step replaces it. Run it across
all three corpus fact sheets, not just the reference:

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
.venv/bin/python -c "
import json, statistics, sys
from pathlib import Path
for path in sorted(Path('$DESK/evidence').glob('facts-*.json')):
    seq = json.loads(path.read_text())['facts']['chords']['value'] or []
    margins = [e['root_margin'] for e in seq if e.get('root_margin') is not None]
    if not margins:
        print(path.name, 'no margins'); continue
    q = statistics.quantiles(margins, n=10)
    print(f'{path.name:44s} n={len(margins):3d} min={min(margins):.3f} '
          f'p10={q[0]:.3f} median={statistics.median(margins):.3f} '
          f'max={max(margins):.3f}')
"
```

Set `MIN_MARGIN` from what you see, and put the table in the pull request with
one sentence saying what the number means. A defensible choice is the value
that flags the bars where the root genuinely ties with another pitch class,
which is a margin near 1.0, rather than a round number chosen in advance.

**What not to do.** Do not set it so that a particular count of bars is flagged,
and do not set it so that a test passes. The earlier draft's constant flagged
3 bars out of 163 across the whole corpus, which is a safeguard that never
fires wearing the name of one.

- [ ] **Step 3: Run the integration test against a real sheet**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
DECONSTRUCT_AUDIO_FACTS=$DESK/evidence/facts-murder-she-wrote.json \
  .venv/bin/python -m unittest tests.test_midi -v
```

Expected: the three `RealSheetTests` run rather than skip, and pass. If
`facts-murder-she-wrote.json` does not exist yet, the fact sheet worktree has
not landed Task 8. Say so in the pull request and mark this step outstanding
rather than deleting the test.

- [ ] **Step 4: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK, with `RealSheetTests` skipped when the environment variable is unset.

- [ ] **Step 5: Commit**

```bash
git add tests/test_midi.py scripts/midi_emit.py
git commit -m "test: prove the emitter against a real fact sheet, not only its own fixture"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`

- [ ] **Step 1: Add `midi` to the command table in `README.md`**

After the `facts` row:

```markdown
| `midi <facts.json>` | Writes the measured chord progression to `progression.mid` at the measured tempo. One chord per bar, root position, root and fifth wherever no third was measured, a sustained root where confidence was too low to name a chord |
```

- [ ] **Step 2: Add a paragraph to `README.md`**

Under "Measuring instead of describing":

```markdown
`midi` exists because chord names in a text prompt are discarded. Community
evidence is consistent on that, and the most cited workaround is supplying
audio, so the MIDI clip is the channel that carries harmony when text cannot.
The emitter writes nothing it did not measure: where the third was absent it
writes root and fifth rather than choosing between major and minor, and where
the chord itself scored below threshold it writes a sustained root and prints
which bars those were.
```

- [ ] **Step 3: Add the limit to the "Limits worth knowing" list in `README.md`**

```markdown
- **The MIDI is harmony, not a transcription.** No melody, no inversions, no
  voicings. A bar whose chord scored low is a sustained root, and the command
  names those bars rather than letting a thinner clip imply them.
```

- [ ] **Step 4: Add the command to `SKILL.md`** following the format the existing
commands use there, including the rule that the agent never describes the MIDI as
a transcription.

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add README.md SKILL.md
git commit -m "docs: the midi command"
```

---

## Self-Review

**Spec coverage.** The spec's MIDI rules are each a test: one chord per bar is
`test_it_writes_one_chord_per_bar_for_every_measured_chord`, the measured tempo
in the header is `test_the_header_carries_the_measured_tempo`, root position
block chords is Task 2's pitch tests, root and fifth where the third is absent is
`test_a_power_chord_is_root_and_fifth_with_no_third` plus
`test_an_absent_third_beats_a_quality_label_that_claims_one`, the sustained root
below threshold is `test_the_fourth_bar_is_a_sustained_root_because_it_scored_low`,
and naming those bars in the output is Task 4 step 1. No melody is structural:
nothing in the module can emit a pitch that is not a chord tone of a measured
entry.

Section timings mirroring the measured grid is now genuinely covered rather
than asserted, and it took two attempts.

The first draft wrote every bar at `index * bar_ticks` and its self review
called the alignment "inherited". What was inherited was the chord ORDER. The
first measured chord on the reference track begins at 5.55 s, so the clip
started 5.55 s early.

The second draft offset the first bar and claimed the remaining window variation
came from one partial bar at the end. The data says otherwise: on Wrong Turn 28
of 52 interior windows deviate from the nominal bar and the clip accumulates
4.114 s of drift, which one partial bar cannot produce. The cause is that the
bar windows come from a tracked beat grid whose spacing follows the performance,
while the clip was written at a constant nominal width.

Each bar is now placed at its own `start_s` and sized to its own `end_s`.
`test_the_clip_starts_at_the_first_measured_chord` and
`test_the_clip_ends_where_the_last_measured_chord_ends` cover both ends, and
`align=False` keeps the uniform behaviour for a caller that wants a quantised
clip rather than a timeline anchor.

**Placeholders.** None. Every step carries its code. Task 5 step 4 points at
`SKILL.md`'s existing format rather than reproducing it, because that file's
conventions are visible in the file itself and copying them into a plan would
create a second source for them.

**Type consistency.** `chord_pitches` takes a chord entry dict and returns
`list[int]`, and `progression` is its only caller. `root_midi` returns `int` and
is called by both. `progression` returns `mido.MidiFile`, which Task 4 calls
`.save()` on. `low_confidence_bars` returns `list[int]` and uses the same
`MIN_MARGIN` default as `progression`, which is a real coupling: if one is
changed the other must be, and the test for the fourth bar would catch a drift.
`root_margin` is produced by `chord_sequence` in the fact sheet plan's Task 4
and is the only field either function thresholds on.
