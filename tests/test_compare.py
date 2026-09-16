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

    def test_empty_candidate_returns_unknown_not_pass(self):
        result = c.score(REFERENCE, {})
        self.assertEqual(result['verdict'], 'UNKNOWN')
        self.assertTrue(all(a['verdict'] == 'UNKNOWN' for a in result['axes']))

    def test_partial_measurement_shows_all_axes_but_verdict_from_compared(self):
        candidate = {'tempo_bpm': 83.0}  # only tempo measured
        result = c.score(REFERENCE, candidate)
        self.assertEqual(result['verdict'], 'PASS')
        # All 7 axes present in result
        self.assertEqual(len(result['axes']), 7)
        # One PASS (tempo), six UNKNOWN (not measured)
        verdicts = [a['verdict'] for a in result['axes']]
        self.assertEqual(verdicts.count('PASS'), 1)
        self.assertEqual(verdicts.count('UNKNOWN'), 6)

    def test_flat_key_matches_sharp_equivalent_exactly(self):
        result = c.score(dict(REFERENCE, key='Gb minor'), dict(REFERENCE, key='F# minor'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'PASS')

    def test_lowercase_key_normalizes(self):
        result = c.score(REFERENCE, dict(REFERENCE, key='f# minor'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'PASS')

    def test_no_space_key_normalizes(self):
        result = c.score(REFERENCE, dict(REFERENCE, key='F#minor'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'PASS')

    def test_unparseable_key_becomes_unknown(self):
        result = c.score(REFERENCE, dict(REFERENCE, key='xyz invalid'))
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
