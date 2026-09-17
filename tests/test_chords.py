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


if __name__ == '__main__':
    unittest.main()
