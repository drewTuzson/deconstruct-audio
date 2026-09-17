# Chord MIDI Emitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write the harmonic skeleton of a measured track to a MIDI file that a generator can be handed as an anchor, without the emitter inventing a single note it did not measure.

**Architecture:** One service module, `midi_emit.py`, that takes a fact sheet and returns a `mido.MidiFile`. One thin command on `deconstruct.py`. The module depends on the fact sheet's schema and on nothing else in this project, so it can be built in parallel with the fact sheet itself against a fixture.

**Tech Stack:** Python 3.10+, `mido` (pure Python, no compiled dependencies).

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

## Global Constraints

- Python 3.10 or newer.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`.
- Baseline is 97 tests, OK, one skipped. Any drop is a regression.
- Commands orchestrate. Service modules own the reusable how. Invariant from `AGENTS.md`.
- The emitter writes no pitch it cannot trace to a measured chord entry.
- No network call. No audio decoding. This module reads a dict and writes a file.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## The input contract

`midi_emit` consumes the fact sheet produced by the fact sheet plan. It reads
exactly four things and ignores the rest:

```python
sheet['facts']['tempo']['value']            # float, BPM
sheet['facts']['chords']['value']           # list of chord entries
sheet['facts']['chords']['confidence']      # KNOW | INFER | UNKNOWN
sheet['facts']['sections']['value']         # {'count': int, 'boundaries_s': [float]}
```

Each chord entry:

```python
{'start_s': 0.0, 'end_s': 2.97, 'root': 'F#', 'quality': 'power',
 'strength': 0.31, 'third_present': False, 'fifth_present': True}
```

This contract is frozen by the fact sheet plan's Task 4 and Task 5. Build against
the fixture below; do not wait for the other worktree.

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
  "source": {"path": "fixture.wav", "sha256": "0", "duration_s": 12.0},
  "stems_from": "adopted",
  "facts": {
    "tempo": {"value": 80.0, "unit": "bpm", "stem": "drums", "band_hz": null,
              "method": ["tempogram-peak"], "confidence": "KNOW",
              "suno_actionable": "direct", "note": null},
    "sections": {"value": {"count": 2, "boundaries_s": [0.0, 6.0]},
                 "unit": "count", "stem": "mix", "band_hz": null,
                 "method": ["agglomerative"], "confidence": "INFER",
                 "suno_actionable": "direct", "note": null},
    "chords": {"value": [
        {"start_s": 0.0, "end_s": 3.0, "root": "F#", "quality": "power",
         "strength": 0.31, "third_present": false, "fifth_present": true},
        {"start_s": 3.0, "end_s": 6.0, "root": "A", "quality": "major",
         "strength": 0.28, "third_present": true, "fifth_present": true},
        {"start_s": 6.0, "end_s": 9.0, "root": "E", "quality": "minor",
         "strength": 0.26, "third_present": true, "fifth_present": true},
        {"start_s": 9.0, "end_s": 12.0, "root": "B", "quality": "power",
         "strength": 0.09, "third_present": false, "fifth_present": false}],
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
            'strength': 0.3, 'third_present': True, 'fifth_present': True}
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
- Produces: `progression(sheet, octave=3, min_strength=0.12, ticks_per_beat=480) -> mido.MidiFile`, `LOW_CONFIDENCE_NOTE`.

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

    def test_the_fourth_bar_is_a_sustained_root_because_it_scored_low(self):
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
        """Note numbers whose note_on lands inside bar `index`."""
        beat = 60.0 / 80.0
        bar_ticks = int(round(4 * beat * (1 / beat) * self.mid.ticks_per_beat / 1))
        bar_ticks = 4 * self.mid.ticks_per_beat
        low, high = index * bar_ticks, (index + 1) * bar_ticks
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


def progression(sheet, octave=3, min_strength=0.12, ticks_per_beat=480):
    """One bar per measured chord, at the measured tempo, root position."""
    bpm = _require(sheet, 'tempo')
    sequence = _require(sheet, 'chords')
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        raise MidiEmitError(f'{bpm!r} is not a tempo')

    mid = mido.MidiFile(type=0, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo',
                                  tempo=mido.bpm2tempo(float(bpm)), time=0))
    track.append(mido.MetaMessage('time_signature', numerator=BEATS_PER_BAR,
                                  denominator=4, time=0))

    bar_ticks = BEATS_PER_BAR * ticks_per_beat
    cursor = 0
    for index, entry in enumerate(sequence):
        if float(entry.get('strength', 0.0)) < min_strength:
            pitches = [root_midi(entry['root'], octave)]
        else:
            pitches = chord_pitches(entry, octave)
        start = index * bar_ticks
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message('note_on', note=pitch, velocity=VELOCITY,
                                      time=(start - cursor) if offset == 0 else 0))
            if offset == 0:
                cursor = start
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message('note_off', note=pitch, velocity=0,
                                      time=bar_ticks if offset == 0 else 0))
        cursor = start + bar_ticks
    track.append(mido.MetaMessage('end_of_track', time=0))
    return mid


def low_confidence_bars(sheet, min_strength=0.12):
    """Bar indices that carry a sustained root, so the fact sheet can name them."""
    sequence = sheet.get('facts', {}).get('chords', {}).get('value') or []
    return [i for i, e in enumerate(sequence)
            if float(e.get('strength', 0.0)) < min_strength]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_midi -v`
Expected: PASS, 19 tests

If `test_every_note_on_has_a_matching_note_off` fails, the delta time bookkeeping
in the note_off loop is wrong, not the test. In a mido track every message's
`time` is a delta from the previous message, so only the first note_off in a
chord carries the bar length and the rest carry zero. Fix the emitter.

- [ ] **Step 5: Commit**

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
    midi_emit.progression(sheet, octave=args.octave).save(str(out))
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
`set_tempo` matching 80 BPM, and a length near 12 seconds. Paste this into the
pull request as the after evidence.

- [ ] **Step 4: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: the midi command"
```

---

### Task 5: Documentation

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

Section timings mirroring the measured grid is partially covered. The emitter
places one chord per bar from the chord sequence, and the chord sequence is built
on the measured beat grid by the fact sheet plan's Task 4, so the alignment is
inherited rather than recomputed. That is deliberate: recomputing it here would
be a second opinion on a grid that already exists, and two grids that disagree is
worse than one.

**Placeholders.** None. Every step carries its code. Task 5 step 4 points at
`SKILL.md`'s existing format rather than reproducing it, because that file's
conventions are visible in the file itself and copying them into a plan would
create a second source for them.

**Type consistency.** `chord_pitches` takes a chord entry dict and returns
`list[int]`, and `progression` is its only caller. `root_midi` returns `int` and
is called by both. `progression` returns `mido.MidiFile`, which Task 4 calls
`.save()` on. `low_confidence_bars` returns `list[int]` and uses the same
`min_strength` default as `progression`, which is a real coupling: if one is
changed the other must be, and the test for the fourth bar would catch a drift.
