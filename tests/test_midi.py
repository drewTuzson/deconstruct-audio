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
