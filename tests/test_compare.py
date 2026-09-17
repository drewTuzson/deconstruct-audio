from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import compare as c

GATES_AXES = tuple(c.GATES)
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

    def test_partial_measurement_shows_counts_with_pass(self):
        candidate = {'tempo_bpm': 80.7, 'key': 'F# minor'}
        result = c.score(REFERENCE, candidate)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['measured'], 2)
        self.assertEqual(result['unmeasured'], 5)
        # Counts must be present alongside verdict at top level
        self.assertIn('measured', result)
        self.assertIn('unmeasured', result)

    def test_unparseable_key_like_banana_is_unknown_not_fail(self):
        candidate = dict(REFERENCE, key='banana')
        result = c.score(REFERENCE, candidate)
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'UNKNOWN')

    def test_identical_unparseable_keys_are_unknown_not_a_pass(self):
        # A sentinel or garbage value identical on both sides is not evidence
        # that the key matched. Raw string equality made it an earned PASS and
        # counted the axis as measured, so a fact sheet carrying 'unknown' on
        # both sides printed MEASURED=7 UNMEASURED=0 VERDICT=PASS.
        for value in ('unknown', 'n/a', '', 'banana'):
            with self.subTest(value=value):
                result = c.score(dict(REFERENCE, key=value), dict(REFERENCE, key=value))
                key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
                self.assertEqual(key_axis['verdict'], 'UNKNOWN')
                self.assertEqual(result['measured'], 6)
                self.assertEqual(result['unmeasured'], 1)

    def test_key_verdict_parses_before_declaring_a_match(self):
        self.assertEqual(c.key_verdict('unknown', 'unknown')[0], 'UNKNOWN')
        self.assertEqual(c.key_verdict('F# minor', 'F# minor')[0], 'PASS')
        self.assertEqual(c.key_verdict('Gb minor', 'F# minor')[0], 'PASS')

    def test_valid_but_unrelated_key_still_fails(self):
        candidate = dict(REFERENCE, key='D major')
        result = c.score(REFERENCE, candidate)
        key_axis = next(a for a in result['axes'] if a['axis'] == 'key')
        self.assertEqual(key_axis['verdict'], 'FAIL')


class UnusableValueTests(unittest.TestCase):
    """Fact sheets are hand-authored JSON and the loader accepts any object,
    so a quoted number or a null is an ordinary typo rather than an exotic
    input. score({'section_count': 7}, {'section_count': '7'}) raised
    TypeError: unsupported operand type(s) for -: 'str' and 'int'.

    A value that is not a finite number where a number is required yields
    UNKNOWN and says the value was not usable. It is never coerced, because
    reading '7' as 7 would turn a typo into a measurement, and this project
    exists because a pipeline reported confidently wrong musical facts.
    """

    NUMERIC_AXES = ('tempo_bpm', 'intro_seconds', 'lra_lu', 'low_end_share',
                    'section_count', 'lead_register_midi')
    UNUSABLE = {'quoted number': '7', 'non-numeric string': 'banana',
                'empty string': '', 'boolean true': True,
                'boolean false': False, 'nan': float('nan'),
                'infinity': float('inf'), 'negative infinity': float('-inf'),
                'list': [7], 'dict': {'value': 7},
                'int too large for a float': 10 ** 400}

    def test_an_unusable_value_is_unknown_on_either_side(self):
        for axis in self.NUMERIC_AXES:
            for label, value in self.UNUSABLE.items():
                for side in ('candidate', 'reference'):
                    with self.subTest(axis=axis, value=label, side=side):
                        pair = {'reference': dict(REFERENCE),
                                'candidate': dict(REFERENCE)}
                        pair[side][axis] = value
                        result = c.score(pair['reference'], pair['candidate'])
                        got = next(a for a in result['axes'] if a['axis'] == axis)
                        self.assertEqual(got['verdict'], 'UNKNOWN')
                        self.assertIsNone(got['delta'])
                        self.assertIn('not a usable number', got['note'])
        # A JSON null means the axis was not measured, which is a different
        # sentence from a value that could not be used. Both are UNKNOWN and
        # neither crashes, and the note keeps saying which happened.
        null = c.score(REFERENCE, dict(REFERENCE, lra_lu=None))
        got = next(a for a in null['axes'] if a['axis'] == 'lra_lu')
        self.assertEqual(got['verdict'], 'UNKNOWN')
        self.assertIn('not measured', got['note'])

    def test_an_unusable_axis_is_not_counted_as_measured(self):
        # An axis nothing could score must not inflate MEASURED, which is
        # what the fact sheet prints as evidence of how much was checked.
        result = c.score(REFERENCE, dict(REFERENCE, section_count='7'))
        self.assertEqual(result['measured'], 6)
        self.assertEqual(result['unmeasured'], 1)

    def test_a_quoted_number_is_never_coerced_into_a_match(self):
        # '7' against 7 is the same number to a reader and no measurement at
        # all to this tool. Silently coercing would print PASS for a typo.
        result = c.score({'section_count': 7}, {'section_count': '7'})
        axis = next(a for a in result['axes'] if a['axis'] == 'section_count')
        self.assertEqual(axis['verdict'], 'UNKNOWN')
        self.assertEqual(result['verdict'], 'UNKNOWN')
        self.assertEqual(result['measured'], 0)

    def test_a_boolean_is_not_a_usable_number(self):
        # bool is a subclass of int in Python, so True would arrive as 1.0
        # and be scored. Before this fix, {'lra_lu': True} against 4.1 read
        # as 'delta -3.10 against limit 1.5' and returned FAIL: a confident
        # verdict, with a plausible number attached, from a value that
        # measured nothing. A boolean in a numeric axis is an authoring
        # mistake, and the honest answer to a mistake is UNKNOWN.
        for value in (True, False):
            with self.subTest(value=value):
                result = c.score(REFERENCE, dict(REFERENCE, lra_lu=value))
                axis = next(a for a in result['axes'] if a['axis'] == 'lra_lu')
                self.assertEqual(axis['verdict'], 'UNKNOWN')

    def test_nan_and_infinity_are_not_measurements(self):
        # Both used to reach the comparison and produce FAIL. A delta of nan
        # or inf is the arithmetic working on a non-measurement, not a track
        # that missed the gate.
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=value):
                result = c.score(REFERENCE, dict(REFERENCE, tempo_bpm=value))
                axis = next(a for a in result['axes'] if a['axis'] == 'tempo_bpm')
                self.assertEqual(axis['verdict'], 'UNKNOWN')

    def test_tempo_verdict_is_safe_at_its_own_entry_point(self):
        # tempo_verdict is public and called directly by tests and callers,
        # so the guard cannot live only inside score().
        for value in ('80.7', None, True, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.assertEqual(c.tempo_verdict(80.7, value)[0], 'UNKNOWN')
                self.assertEqual(c.tempo_verdict(value, 80.7)[0], 'UNKNOWN')

    def test_an_unusable_value_never_crashes_any_axis(self):
        # The blunt version of the whole finding: nothing in UNUSABLE, on any
        # axis, on either side, may raise.
        for axis in GATES_AXES:
            for label, value in self.UNUSABLE.items():
                with self.subTest(axis=axis, value=label):
                    c.score(dict(REFERENCE, **{axis: value}),
                            dict(REFERENCE, **{axis: value}))


if __name__ == '__main__':
    unittest.main()
