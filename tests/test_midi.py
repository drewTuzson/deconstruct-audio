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
        low, high = m.OCTAVE_RANGE
        for octave in range(low, high + 1):
            for name in m.NOTES:
                for p in m.chord_pitches(entry(root=name), octave=octave):
                    self.assertGreaterEqual(p, 0)
                    self.assertLessEqual(p, 127)

    def test_an_octave_outside_the_range_is_an_error_not_a_silent_clamp(self):
        """Both ends, both paths.

        chord_pitches used to clamp and the sustained root path did not, so
        --octave 9 depended on whether the sheet held a low margin bar. A clamp
        would also answer 9 with 8 and call it success, which is the silent
        substitution this module refuses everywhere else.
        """
        low, high = m.OCTAVE_RANGE
        for octave in (low - 1, high + 1, 99, -99):
            with self.subTest(octave=octave):
                # The chord path.
                with self.assertRaises(m.MidiEmitError):
                    m.chord_pitches(entry(third_present=True), octave=octave)
                # The sustained root path, reached by a margin below the cut.
                with self.assertRaises(m.MidiEmitError):
                    m.chord_pitches(entry(third_present=False), octave=octave)
                with self.assertRaises(m.MidiEmitError):
                    m.check_octave(octave)

    def test_both_ends_of_the_octave_range_are_usable_on_both_paths(self):
        low, high = m.OCTAVE_RANGE
        for octave in (low, high):
            with self.subTest(octave=octave):
                chord = m.chord_pitches(entry(third_present=True), octave=octave)
                self.assertEqual(len(chord), 3)
                dyad = m.chord_pitches(entry(third_present=False), octave=octave)
                self.assertEqual(len(dyad), 2)
                for p in chord + dyad + [m.root_midi('A', octave)]:
                    self.assertGreaterEqual(p, 0)
                    self.assertLessEqual(p, 127)

    def test_a_bad_octave_fails_the_same_way_whatever_the_music_says(self):
        """The regression this is really about.

        Two sheets differing only in one bar's root_margin. With the octave
        validated per bar instead of once, the first wrote a clip and the second
        raised, so the same command succeeded or failed depending on the music.
        """
        for margin in (1.50, 1.04):
            with self.subTest(margin=margin):
                sheet = json.loads(json.dumps(FIXTURE))
                for e in sheet['facts']['chords']['value']:
                    e['root_margin'] = 1.50
                sheet['facts']['chords']['value'][3]['root_margin'] = margin
                with self.assertRaises(m.MidiEmitError):
                    m.progression(sheet, octave=m.OCTAVE_RANGE[1] + 1)
                # And the same octave inside the range works on both sheets.
                self.assertGreater(m.progression(sheet, octave=3).length, 1.0)


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

    def test_the_third_bar_is_a_full_minor_triad(self):
        # Bar 2 carries root_margin 1.38 and a measured third. Without this
        # assertion nothing constrains its contents, and the admissible band for
        # MIN_MARGIN widens from (1.04, 1.38] to (1.04, 1.47], so a constant as
        # wrong as 1.45 would ship green.
        notes = sorted(self._notes_in_bar(2))
        self.assertEqual(len(notes), 3)
        self.assertEqual([n - notes[0] for n in notes], [0, 3, 7])

    def test_the_cut_sits_at_the_five_percent_it_documents(self):
        """MIN_MARGIN claims to flag bars where the root won by under five
        percent. The fixture alone only pins it to (1.04, 1.38], so this asserts
        the documented meaning directly and fails if the constant moves."""
        sheet = json.loads(json.dumps(FIXTURE))
        sheet['facts']['chords']['value'] = [
            dict(entry(root='A', start_s=0.0, end_s=3.0), root_margin=1.0499),
            dict(entry(root='A', start_s=3.0, end_s=6.0), root_margin=1.0501)]
        # Just under five percent is a sustained root; just over is a chord.
        self.assertEqual(m.low_confidence_bars(sheet), [0])

    def test_a_window_edge_that_is_not_a_number_is_an_authored_error(self):
        for field, bad in (('end_s', 'eight point five'), ('start_s', None),
                           ('end_s', [12.0]), ('start_s', {})):
            with self.subTest(field=field, bad=bad):
                sheet = json.loads(json.dumps(FIXTURE))
                sheet['facts']['chords']['value'][1][field] = bad
                with self.assertRaises(m.MidiEmitError) as caught:
                    m.progression(sheet)
                # The message has to name the bar and the field, or it is no
                # better than the ValueError it replaced.
                self.assertIn('bar 1', str(caught.exception))
                self.assertIn(field, str(caught.exception))

    def test_a_non_finite_window_edge_is_an_error_not_a_garbage_tick(self):
        # NaN survives arithmetic and compares false against every bound, so it
        # would slip past the zero width and backwards checks unnoticed.
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(bad=bad):
                sheet = json.loads(json.dumps(FIXTURE))
                sheet['facts']['chords']['value'][1]['end_s'] = bad
                with self.assertRaises(m.MidiEmitError):
                    m.progression(sheet)

    def test_a_first_bar_starting_before_zero_does_not_blame_bar_minus_one(self):
        sheet = json.loads(json.dumps(FIXTURE))
        sheet['facts']['chords']['value'][0]['start_s'] = -1.0
        with self.assertRaises(m.MidiEmitError) as caught:
            m.progression(sheet)
        self.assertNotIn('bar -1', str(caught.exception))
        self.assertIn('bar 0', str(caught.exception))

    def test_a_root_margin_that_is_not_a_number_is_an_authored_error(self):
        for bad in ('high', [1.2], {}, 'NaN-ish'):
            with self.subTest(bad=bad):
                sheet = json.loads(json.dumps(FIXTURE))
                sheet['facts']['chords']['value'][1]['root_margin'] = bad
                with self.assertRaises(m.MidiEmitError) as caught:
                    m.progression(sheet)
                self.assertIn('bar 1', str(caught.exception))
                self.assertIn('root_margin', str(caught.exception))
                # low_confidence_bars reads the same field and must agree.
                with self.assertRaises(m.MidiEmitError):
                    m.low_confidence_bars(sheet)

    def test_a_non_finite_root_margin_does_not_take_the_chord_path(self):
        """NaN compares false against every bound, so `margin < min_margin` was
        false and the bar got a full chord. An unusable measurement must not
        produce more notes than a usable one."""
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(bad=bad):
                sheet = json.loads(json.dumps(FIXTURE))
                sheet['facts']['chords']['value'][3]['root_margin'] = bad
                with self.assertRaises(m.MidiEmitError):
                    m.progression(sheet)

    def test_a_missing_root_margin_is_still_a_sustained_root(self):
        # Absent means no confidence, which is different from corrupt.
        sheet = json.loads(json.dumps(FIXTURE))
        sheet['facts']['chords']['value'][1]['root_margin'] = None
        self.assertIn(1, m.low_confidence_bars(sheet))
        self.assertEqual(len(m.progression(sheet).tracks[0][2].bytes()), 3)

    def test_the_printed_bars_describe_the_clip_that_was_written(self):
        """SUSTAINED_ROOT_BARS comes from low_confidence_bars and the notes come
        from progression. They used to decide low confidence separately, so this
        pins them to the same answer across the whole margin range."""
        for cut in (1.0, 1.05, 1.2, 1.4, 1.6):
            with self.subTest(min_margin=cut):
                named = set(m.low_confidence_bars(FIXTURE, cut))
                mid = m.progression(FIXTURE, min_margin=cut)
                bar_ticks = 4 * mid.ticks_per_beat
                lead = int(round(3.0 * mid.ticks_per_beat * 80.0 / 60.0))
                written, absolute = set(), 0
                counts = {}
                for msg in mid.tracks[0]:
                    absolute += msg.time
                    if msg.type == 'note_on' and msg.velocity > 0:
                        bar = (absolute - lead) // bar_ticks
                        counts[bar] = counts.get(bar, 0) + 1
                written = {b for b, n in counts.items() if n == 1}
                self.assertEqual(named, written)

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


if __name__ == '__main__':
    unittest.main()
