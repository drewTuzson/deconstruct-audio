from pathlib import Path
import re
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


SHEET = {'facts': {
    'tempo': {'value': 80.7, 'confidence': 'KNOW'},
    'key': {'value': 'F# minor', 'confidence': 'KNOW'},
    'tuning': {'value': None, 'confidence': 'UNKNOWN'},
}}


class CollisionTests(unittest.TestCase):
    def _rec(self, *claims):
        return r.record('An Artist', 'A Song', list(claims))

    def test_a_disagreement_is_reported_with_the_measurement_authoritative(self):
        rec = self._rec(r.claim('tempo', 144, 'https://example.org/a', 'INFER'))
        rows = r.collisions(SHEET, rec)
        row = next(x for x in rows if x['axis'] == 'tempo')
        self.assertEqual(row['measured'], 80.7)
        self.assertEqual(row['researched'], 144)
        self.assertFalse(row['agrees'])
        self.assertEqual(row['authoritative'], 'measured')

    def test_an_agreement_is_still_reported_rather_than_dropped(self):
        rec = self._rec(r.claim('key', 'F# minor', 'https://example.org/b', 'KNOW'))
        row = next(x for x in r.collisions(SHEET, rec) if x['axis'] == 'key')
        self.assertTrue(row['agrees'])
        self.assertEqual(row['authoritative'], 'measured')

    def test_research_never_wins_even_against_an_unknown_measurement(self):
        rec = self._rec(r.claim('tuning', 'drop C', 'https://example.org/c', 'KNOW'))
        row = next(x for x in r.collisions(SHEET, rec) if x['axis'] == 'tuning')
        self.assertEqual(row['authoritative'], 'measured')
        self.assertIsNone(row['measured'])

    def test_a_claim_under_the_projected_axis_name_still_collides(self):
        # The agent gathering research reads scorable.json, which uses
        # compare's names, so it files claims as tempo_bpm rather than tempo.
        # Matching on the sheet's names alone let those four claims escape the
        # table and be relabelled as safe context, which inverts this file's
        # entire purpose.
        rec = self._rec(r.claim('tempo_bpm', 144, 'https://example.org/a', 'GUESS'))
        row = next(x for x in r.collisions(SHEET, rec) if x['axis'] == 'tempo_bpm')
        self.assertEqual(row['fact_axis'], 'tempo')
        self.assertEqual(row['measured'], 80.7)
        self.assertFalse(row['agrees'])
        self.assertEqual(row['authoritative'], 'measured')

    def test_a_claim_on_a_nested_field_collides_with_that_field(self):
        sheet = {'facts': {'loudness': {
            'value': {'integrated_lufs': -7.0, 'lra_lu': 4.1,
                      'true_peak_dbtp': -0.2},
            'confidence': 'KNOW'}}}
        rec = self._rec(r.claim('lra_lu', 9.0, 'https://example.org/b', 'GUESS'))
        row = next(x for x in r.collisions(sheet, rec) if x['axis'] == 'lra_lu')
        self.assertEqual(row['measured'], 4.1)
        self.assertFalse(row['agrees'])

    def test_a_row_does_not_alias_the_sheet(self):
        # collisions() never mutates, so the deepcopy-the-input test cannot
        # catch this. The danger is the caller: a row holding a reference to
        # the sheet's own value lets anyone editing a row edit the facts.
        sheet = {'facts': {'loudness': {
            'value': {'lra_lu': 4.1}, 'confidence': 'KNOW'}}}
        rec = self._rec(r.claim('loudness', {'lra_lu': 9.0},
                                'https://example.org/c', 'GUESS'))
        row = r.collisions(sheet, rec)[0]
        self.assertIsNot(row['measured'], sheet['facts']['loudness']['value'])
        row['measured']['lra_lu'] = 999
        self.assertEqual(sheet['facts']['loudness']['value']['lra_lu'], 4.1)

    def test_an_enormous_number_is_a_disagreement_not_a_crash(self):
        rec = self._rec(r.claim('tempo', 10 ** 400, 'https://example.org/d', 'GUESS'))
        row = next(x for x in r.collisions(SHEET, rec) if x['axis'] == 'tempo')
        self.assertFalse(row['agrees'])

    def test_a_claim_on_an_axis_nothing_measured_is_context_not_a_collision(self):
        rec = self._rec(r.claim('scene', 'midwest emo revival',
                                'https://example.org/d', 'INFER'))
        self.assertEqual([x for x in r.collisions(SHEET, rec)
                          if x['axis'] == 'scene'], [])

    def test_numeric_agreement_tolerates_a_small_drift(self):
        rec = self._rec(r.claim('tempo', 80.9, 'https://example.org/e', 'INFER'))
        row = next(x for x in r.collisions(SHEET, rec) if x['axis'] == 'tempo')
        self.assertTrue(row['agrees'])

    def test_the_sheet_is_not_mutated_by_building_the_table(self):
        import copy
        before = copy.deepcopy(SHEET)
        r.collisions(SHEET, self._rec(
            r.claim('tempo', 144, 'https://example.org/f', 'GUESS')))
        self.assertEqual(SHEET, before)

    def test_rendering_names_the_measurement_as_authoritative_in_words(self):
        rec = self._rec(r.claim('tempo', 144, 'https://example.org/g', 'GUESS'))
        text = r.render_markdown(SHEET, rec)
        self.assertIn('80.7', text)
        self.assertIn('144', text)
        self.assertIn('measured', text.lower())
        self.assertIn('https://example.org/g', text)


class NestedUnknownTests(unittest.TestCase):
    """A nested axis under an UNKNOWN parent is still an axis that was measured.

    The parent exists in the sheet, so the axis was attempted and did not
    resolve, which is the same state a top-level UNKNOWN reports. Filing that
    claim as context would print it under the heading that says such claims are
    safe to use, which is the inversion the alias table exists to stop.
    """

    def _rec(self, *claims):
        return r.record('An Artist', 'A Song', list(claims))

    def test_a_nested_claim_under_an_unknown_parent_still_collides(self):
        sheet = {'facts': {'loudness': {'value': None, 'confidence': 'UNKNOWN'}}}
        rec = self._rec(r.claim('lra_lu', 9.0, 'https://example.org/h', 'GUESS'))
        row = next(x for x in r.collisions(sheet, rec) if x['axis'] == 'lra_lu')
        self.assertEqual(row['fact_axis'], 'loudness')
        self.assertIsNone(row['measured'])
        self.assertFalse(row['agrees'])
        self.assertEqual(row['authoritative'], 'measured')
        self.assertNotIn('## Context', r.render_markdown(sheet, rec))

    def test_a_nested_field_absent_from_a_measured_parent_still_collides(self):
        sheet = {'facts': {'loudness': {'value': {'integrated_lufs': -7.0},
                                        'confidence': 'KNOW'}}}
        rec = self._rec(r.claim('lra_lu', 9.0, 'https://example.org/i', 'GUESS'))
        row = next(x for x in r.collisions(sheet, rec) if x['axis'] == 'lra_lu')
        self.assertIsNone(row['measured'])
        self.assertFalse(row['agrees'])

    def test_an_axis_the_sheet_never_names_is_still_context(self):
        sheet = {'facts': {'tempo': {'value': 80.7, 'confidence': 'KNOW'}}}
        rec = self._rec(r.claim('scene', 'midwest emo revival',
                                'https://example.org/j', 'INFER'))
        self.assertEqual(r.collisions(sheet, rec), [])
        self.assertIn('## Context', r.render_markdown(sheet, rec))


class TableSafetyTests(unittest.TestCase):
    """A claim is hand written text and a table is delimited by pipes.

    A pipe opens a column and a newline opens a row. Either one separates a
    measured value from its label, in the one table whose whole job is to show
    which of the two is authoritative.
    """

    DELIMITER = re.compile(r'(?<!\\)\|')

    def _rec(self, *claims):
        return r.record('An Artist', 'A Song', list(claims))

    def test_a_pipe_or_a_newline_in_a_context_claim_keeps_four_columns(self):
        rec = self._rec(r.claim('scene', 'emo | revival\nand a second line',
                                'https://example.org/k?a=1|2', 'INFER'))
        rows = [ln for ln in r.render_markdown(SHEET, rec).splitlines()
                if 'revival' in ln]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.DELIMITER.findall(rows[0])), 5)

    def test_a_pipe_in_a_collision_claim_keeps_nine_columns(self):
        rec = self._rec(r.claim('tempo', '144 | or 72\nmaybe',
                                'https://example.org/l?a=1|2', 'GUESS'))
        rows = [ln for ln in r.render_markdown(SHEET, rec).splitlines()
                if 'or 72' in ln]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(self.DELIMITER.findall(rows[0])), 10)

    def test_the_escaping_does_not_lose_the_text(self):
        rec = self._rec(r.claim('scene', 'emo | revival',
                                'https://example.org/m', 'INFER'))
        text = r.render_markdown(SHEET, rec)
        self.assertIn(r'emo \| revival', text)


if __name__ == '__main__':
    unittest.main()
