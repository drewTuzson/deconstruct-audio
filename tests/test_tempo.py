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


def tempogram_with(primary, competing=None, relative=0.0,
                   low=50.0, high=220.0, step=0.5):
    """Synthetic tempogram evidence for grade(): one strong peak at `primary`,
    plus an optional second peak at `competing` carrying `relative` of the
    primary's strength. Everything else is the noise floor.
    """
    tempi = np.arange(low, high + step, step)
    strength = np.zeros_like(tempi)
    strength[int(np.argmin(np.abs(tempi - primary)))] = 1.0
    if competing is not None:
        strength[int(np.argmin(np.abs(tempi - competing)))] = relative
    return tempi, strength, 1.0


class RatioTests(unittest.TestCase):
    def test_classify_known_ratios(self):
        cases = [(80.0, 160.0, '2x'), (80.0, 40.0, '0.5x'),
                 (80.0, 106.7, '4/3'), (80.0, 60.0, '3/4'), (80.0, 80.4, '1x')]
        for primary, other, expected in cases:
            with self.subTest(other=other):
                self.assertEqual(t.classify_ratio(primary, other), expected)

    def test_unrelated_tempo_has_no_ratio(self):
        self.assertIsNone(t.classify_ratio(80.0, 97.0))


class RatioWindowTests(unittest.TestCase):
    """The competing-peak search must not be able to file one tempogram peak
    under two contradictory metrical labels.

    History: classify_ratio's TOLERANCE of 0.04 does give pairwise disjoint
    bands, and a reviewer verified that. COMPETING_WINDOW was introduced
    later, separately and much wider, and nobody rechecked disjointness
    against the new number. At 0.10 the 4/3 and 1.5x bands overlap, so a peak
    at 140 BPM against a primary of 100 was admitted twice under both labels,
    and grade()'s dedup key of (ratio, bpm) cannot see it because the ratios
    differ.
    """

    def _overlaps(self, windows):
        ordered = sorted(windows, key=lambda w: w[2])
        clashes = []
        for lower, upper in zip(ordered, ordered[1:]):
            if upper[2] < lower[3]:
                clashes.append(f'{lower[0]} [{lower[2]:.4f}, {lower[3]:.4f}] '
                               f'overlaps {upper[0]} [{upper[2]:.4f}, {upper[3]:.4f}]')
        return clashes

    def test_search_windows_are_pairwise_disjoint(self):
        # Computed from the constant, never hardcoded, so that widening
        # COMPETING_WINDOW cannot reintroduce the overlap silently.
        # The raw +/- COMPETING_WINDOW bands are asserted to overlap first,
        # so that this test keeps proving something. If a future change makes
        # the raw bands disjoint on their own, this precondition fails loudly
        # rather than letting the disjointness assertion below pass for a
        # reason that has nothing to do with the mechanism under test.
        raw = [(label, value, value * (1 - t.COMPETING_WINDOW),
                value * (1 + t.COMPETING_WINDOW)) for value, label in t.RATIOS]
        self.assertTrue(self._overlaps(raw),
                        'raw bands no longer overlap, so this test proves nothing')
        clashes = self._overlaps(t.ratio_windows())
        self.assertEqual(clashes, [], 'ratio search windows overlap: ' + '; '.join(clashes))

    def test_widening_the_constant_cannot_reintroduce_overlap(self):
        # The property must hold because of the mechanism, not because the
        # current number happens to be small enough.
        for window in (0.04, t.COMPETING_WINDOW, 0.15, 0.25, 0.4, 0.9):
            with self.subTest(window=window):
                clashes = self._overlaps(t.ratio_windows(window=window))
                self.assertEqual(clashes, [],
                                 f'windows overlap at {window}: ' + '; '.join(clashes))

    def test_one_peak_is_admitted_under_one_label_only(self):
        # The finding's own reproduction: primary 100, peak at 140. 140 sits
        # inside the raw 4/3 band (120.0-146.7) and the raw 1.5x band
        # (135.0-165.0) at the same time.
        result = t.grade({'tempogram': 100.0, 'beat_track': 100.0, 'ioi': 100.0},
                         *tempogram_with(100.0, competing=140.0, relative=0.85))
        at_140 = [e for e in result['family'] if abs(e['bpm'] - 140.0) < 0.6]
        self.assertEqual(len(at_140), 1,
                         f'140 BPM admitted under {[e["ratio"] for e in at_140]}')
        # 140/100 is 1.40. Relative distance to 4/3 is 0.050, to 1.5 is 0.067,
        # so the nearer candidate, and the only honest label, is 4/3.
        self.assertEqual(at_140[0]['ratio'], '4/3')

    def test_a_peak_past_the_split_takes_the_other_label(self):
        # 145/100 is 1.45, past the 1.4118 split, so it is 1.5x and nothing else.
        result = t.grade({'tempogram': 100.0, 'beat_track': 100.0, 'ioi': 100.0},
                         *tempogram_with(100.0, competing=145.0, relative=0.85))
        at_145 = [e for e in result['family'] if abs(e['bpm'] - 145.0) < 0.6]
        self.assertEqual(len(at_145), 1,
                         f'145 BPM admitted under {[e["ratio"] for e in at_145]}')
        self.assertEqual(at_145[0]['ratio'], '1.5x')


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
        result = t.grade({'tempogram': 80.0, 'beat_track': 106.7, 'ioi': 80.2},
                         *tempogram_with(80.0))
        self.assertEqual(result['confidence'], 'INFER')
        self.assertIn('4/3', result['disagreement'])

    def test_unrelated_methods_are_unknown_not_a_pick(self):
        result = t.grade({'tempogram': 80.0, 'beat_track': 97.0, 'ioi': 131.0},
                         *tempogram_with(80.0))
        self.assertEqual(result['confidence'], 'UNKNOWN')

    def test_agreeing_methods_are_known(self):
        result = t.grade({'tempogram': 80.0, 'beat_track': 80.5, 'ioi': 79.8},
                         *tempogram_with(80.0))
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

    def test_shared_octave_bias_is_surfaced_not_known(self):
        # At 190 BPM the tempogram peak, beat_track, and ioi all lock onto the
        # same half-tempo alias (~95.7 BPM) because beat_track and ioi derive
        # from the same onset envelope as the tempogram. "All methods agree"
        # must not become KNOW when the tempogram's own secondary-peak
        # structure still shows meaningful support for the true tempo.
        wav = self.path / 'fast190.wav'
        click_track(wav, 190)
        result = t.tempo_family(wav)
        reported = [result['primary']] + [entry['bpm'] for entry in result['family']]
        self.assertTrue(any(abs(bpm - 190.0) / 190.0 < 0.05 for bpm in reported),
                        f'190 BPM appears nowhere in {reported}')
        self.assertNotEqual(result['confidence'], 'KNOW')

    def test_grade_downgrades_know_when_tempogram_shows_competing_level(self):
        # Even when every method in `methods` agrees, a supported competing
        # tempogram peak must appear in the family and must prevent KNOW.
        # grade() finds it from the tempogram itself, not from a caller that
        # remembered to look.
        result = t.grade({'tempogram': 95.7, 'beat_track': 95.7, 'ioi': 95.7},
                         *tempogram_with(95.7, competing=191.4, relative=0.85))
        self.assertNotEqual(result['confidence'], 'KNOW')
        self.assertTrue(any(abs(entry['bpm'] - 191.4) / 191.4 < 0.01
                            for entry in result['family']),
                        f"191.4 BPM missing from {result['family']}")

    def test_grade_has_no_signature_that_skips_the_octave_check(self):
        # Inverted from a backward-compatibility test that asserted the
        # opt-in path still worked. That test was the thing standing in the
        # way of this fix: its name told a maintainer that grade(methods)
        # was a supported contract, when it was the shape of the original
        # Critical bug. Three correlated measurements agreeing on a tempo
        # wrong by an octave must not be able to reach KNOW by any call.
        with self.assertRaises(TypeError):
            t.grade({'tempogram': 80.0, 'beat_track': 80.5, 'ioi': 79.8})

    def test_unusable_tempogram_evidence_cannot_reach_know(self):
        # Merely requiring the argument would not be enough: a caller
        # satisfies a required parameter with None or [] just as quietly.
        agreeing = {'tempogram': 80.0, 'beat_track': 80.5, 'ioi': 79.8}
        narrow = (np.array([80.0, 80.5]), np.array([1.0, 0.0]), 1.0)
        cases = {
            'none': (None, None, 1.0),
            'empty': ([], [], 1.0),
            'single point': ([80.0], [1.0], 1.0),
            'mismatched lengths': ([80.0, 160.0], [1.0], 1.0),
            'no ratio candidate in range': narrow,
            'no peak strength': (*tempogram_with(80.0)[:2], 0.0),
        }
        for name, evidence in cases.items():
            with self.subTest(evidence=name):
                result = t.grade(agreeing, *evidence)
                self.assertEqual(result['confidence'], 'INFER')
                self.assertIn('competing-level check', result['disagreement'])


if __name__ == '__main__':
    unittest.main()
