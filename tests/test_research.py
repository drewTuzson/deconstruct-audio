from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import research as r


class ClaimTests(unittest.TestCase):
    def good(self, **over):
        kwargs = dict(axis='era', value='2020s', source='https://example.org/page',
                      confidence='KNOW')
        kwargs.update(over)
        return r.claim(**kwargs)

    def test_a_claim_carries_axis_value_source_and_confidence(self):
        for key in ('axis', 'value', 'source', 'confidence', 'note'):
            self.assertIn(key, self.good())

    def test_a_claim_without_a_source_is_an_error(self):
        with self.assertRaises(r.ResearchError):
            self.good(source='')

    def test_a_claim_may_be_graded_guess_which_a_fact_may_not(self):
        self.assertEqual(self.good(confidence='GUESS')['confidence'], 'GUESS')

    def test_an_unrecognised_grade_is_refused(self):
        with self.assertRaises(r.ResearchError):
            self.good(confidence='CERTAIN')

    def test_a_record_names_what_was_searched_for(self):
        rec = r.record('An Artist', 'A Song', [self.good()])
        self.assertEqual(rec['schema'], r.SCHEMA)
        self.assertEqual(rec['query']['artist'], 'An Artist')
        self.assertEqual(rec['query']['title'], 'A Song')
        self.assertEqual(len(rec['claims']), 1)

    def test_a_record_with_no_name_is_an_error_because_the_branch_is_optional(self):
        with self.assertRaises(r.ResearchError):
            r.record('', '', [])

    def test_record_refuses_a_sourceless_claim_that_bypassed_claim(self):
        # record() accepting what claim() refuses would be a second door into
        # the same room. Today's only caller routes through claim(), but that
        # is a property of the caller, not of this function.
        raw = {'axis': 'era', 'value': '2020s', 'source': '  ',
               'confidence': 'KNOW', 'note': None}
        with self.assertRaises(r.ResearchError):
            r.record('An Artist', 'A Song', [raw])

    def test_record_refuses_an_unrecognised_grade_that_bypassed_claim(self):
        raw = {'axis': 'era', 'value': '2020s', 'source': 'https://example.org',
               'confidence': 'CERTAIN', 'note': None}
        with self.assertRaises(r.ResearchError):
            r.record('An Artist', 'A Song', [raw])


if __name__ == '__main__':
    unittest.main()
