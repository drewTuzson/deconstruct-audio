from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tempo as t


def click_track(path, bpm, seconds=20, sr=22050):
    """A synthetic metronome. No copyrighted audio in the test corpus."""
    total = int(seconds * sr)
    y = np.zeros(total, dtype=np.float32)
    tick = int(sr * 0.02)
    envelope = np.exp(-np.arange(tick) / (sr * 0.004))
    click = (np.sin(2 * np.pi * 1800 * np.arange(tick) / sr) * envelope).astype(np.float32)
    period = int(round(sr * 60.0 / bpm))
    for start in range(0, total - tick, period):
        y[start:start + tick] += click
    sf.write(str(path), y, sr)


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

    def test_half_tempo_ambiguity_is_surfaced_not_hidden(self):
        wav = self.path / 'fast.wav'
        click_track(wav, 120)
        result = t.tempo_family(wav)
        reported = [result['primary']] + [entry['bpm'] for entry in result['family']]
        self.assertTrue(any(abs(bpm - 120.0) / 120.0 < 0.05 for bpm in reported),
                        f'120 BPM appears nowhere in {reported}')
        self.assertIn(result['confidence'], ('INFER', 'UNKNOWN'))


if __name__ == '__main__':
    unittest.main()
