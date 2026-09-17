from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import brain as b

# A synthetic rules file. Invented for this test. Contains no third party text.
FIXTURE_INSTRUCTIONS = """
## FIRST: ASK THE MODE
- SIMPLE: one long style prompt ONLY. Target 1,800 to 2,600 characters
  (box cap 3,000).
- CUSTOM (Advanced): style prompt HARD limit 1,000 characters, target 850 to 950.
- STUDIO: one element only. Limit 1,000.

## BANNED AND SWAPPED WORDS
Fatigue words banned in styles AND lyrics: wibbly, frobnicate, sparkletastic.
Never: "in the manner of", "sort of like".

## VOCALS, NEGATION, EXCLUDE
EXCLUDE: positive keywords only. Target 180 to 200 characters.
"""


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_it_reads_a_folder_holding_an_instructions_file(self):
        (self.dir / 'INSTRUCTIONS.txt').write_text(FIXTURE_INSTRUCTIONS)
        sources = b.brain_sources(self.dir)
        self.assertIn('INSTRUCTIONS.txt', sources)
        self.assertIn('CUSTOM', sources['INSTRUCTIONS.txt'])

    def test_it_reads_a_full_system_prompt_when_present(self):
        (self.dir / 'SYSTEM-PROMPT-FULL.txt').write_text(FIXTURE_INSTRUCTIONS)
        self.assertIn('SYSTEM-PROMPT-FULL.txt', b.brain_sources(self.dir))

    def test_it_reads_the_knowledge_folder_too(self):
        (self.dir / 'INSTRUCTIONS.txt').write_text(FIXTURE_INSTRUCTIONS)
        knowledge = self.dir / 'knowledge'
        knowledge.mkdir()
        (knowledge / 'a-file.md').write_text('# a knowledge file')
        self.assertIn('knowledge/a-file.md', b.brain_sources(self.dir))

    def test_a_folder_with_no_instruction_file_is_an_error(self):
        with self.assertRaises(b.BrainError):
            b.brain_sources(self.dir)

    def test_a_missing_folder_is_an_error_not_an_empty_brain(self):
        with self.assertRaises(b.BrainError):
            b.brain_sources(self.dir / 'nowhere')


class SourceChoiceTests(unittest.TestCase):
    # The real Brain ships both instruction files and only the short one
    # carries the labelled rule lines, so a fixed preference for the full
    # prompt reported every rule unreadable against a Brain that parses.

    def test_it_extracts_from_whichever_source_carries_the_rules(self):
        name, rules = b.rules_from(
            {'SYSTEM-PROMPT-FULL.txt': 'an assembled document, no rule labels',
             'INSTRUCTIONS.txt': FIXTURE_INSTRUCTIONS})
        self.assertEqual(name, 'INSTRUCTIONS.txt')
        self.assertEqual(rules['unreadable'], [])

    def test_it_prefers_the_full_prompt_when_both_read_the_same(self):
        name, _ = b.rules_from({'SYSTEM-PROMPT-FULL.txt': FIXTURE_INSTRUCTIONS,
                                'INSTRUCTIONS.txt': FIXTURE_INSTRUCTIONS})
        self.assertEqual(name, 'SYSTEM-PROMPT-FULL.txt')

    def test_it_never_blends_two_sources_into_a_rule_set_neither_states(self):
        # Half the rules in each file. Taking the better of the two is still
        # one file, so the rules the chosen file lacks stay unreadable rather
        # than being quietly borrowed from the other.
        budgets_only, banned_only = FIXTURE_INSTRUCTIONS.split('## BANNED')
        _, rules = b.rules_from({'SYSTEM-PROMPT-FULL.txt': budgets_only,
                                 'INSTRUCTIONS.txt': '## BANNED' + banned_only})
        self.assertTrue(rules['unreadable'])

    def test_a_brain_with_no_instruction_source_is_an_error(self):
        with self.assertRaises(b.BrainError):
            b.rules_from({'knowledge/a-file.md': FIXTURE_INSTRUCTIONS})


class RuleExtractionTests(unittest.TestCase):
    def setUp(self):
        self.rules = b.extract_rules(FIXTURE_INSTRUCTIONS)

    def test_it_reads_the_custom_budget_from_the_text(self):
        self.assertEqual(self.rules['budgets']['custom']['cap'], 1000)
        self.assertEqual(self.rules['budgets']['custom']['target'], (850, 950))

    def test_it_reads_the_simple_budget_from_the_text(self):
        self.assertEqual(self.rules['budgets']['simple']['target'], (1800, 2600))
        self.assertEqual(self.rules['budgets']['simple']['cap'], 3000)

    def test_it_reads_the_banned_words_from_the_text(self):
        self.assertIn('frobnicate', self.rules['banned_words'])
        self.assertIn('sparkletastic', self.rules['banned_words'])

    def test_it_reads_the_banned_phrases_from_the_text(self):
        self.assertIn('sort of like', self.rules['banned_phrases'])

    def test_it_reads_the_exclude_budget_from_the_text(self):
        self.assertEqual(self.rules['exclude_budget'], (180, 200))

    def test_a_mode_list_before_the_definitions_does_not_steal_a_budget(self):
        # The shape that defeated the first anchored version: the modes are
        # named on one line, so a fixed window from CUSTOM runs into SIMPLE's
        # budget and returns cap 3000 with nothing in unreadable.
        text = ('Ask the mode: SIMPLE, CUSTOM, STUDIO.\n'
                '- STUDIO: one element.\n'
                '- SIMPLE: Target 2,000 to 2,500 characters (box cap 3,000).\n'
                '- CUSTOM (Advanced): style prompt HARD limit 1,000 '
                'characters, target 850 to 950.')
        rules = b.extract_rules(text)
        self.assertEqual(rules['budgets']['custom']['cap'], 1000)
        self.assertEqual(rules['budgets']['custom']['target'], (850, 950))

    def test_a_longer_word_containing_a_mode_name_is_not_that_mode(self):
        text = ('You may CUSTOMISE the output.\n'
                '- SIMPLE: Target 2,000 to 2,500 characters (box cap 3,000).\n'
                '- CUSTOM (Advanced): style prompt HARD limit 1,000 '
                'characters, target 850 to 950.')
        self.assertEqual(b.extract_rules(text)['budgets']['custom']['cap'], 1000)

    def test_a_budget_wrapping_inside_its_own_window_is_still_read(self):
        # The wording the first implementation could not read. A rules file
        # hard wraps, so the target and the cap land on either side of a line
        # break, and the pattern that forbade a newline between them reported
        # UNREADABLE on the most ordinary shape there is. Widening it is safe
        # because the window is already bounded by the next mode; the case
        # below proves that boundary still holds.
        text = ('- SIMPLE: one long style prompt ONLY. Target 1,800 to 2,600 '
                'characters\n  (box cap 3,000).')
        rules = b.extract_rules(text)
        self.assertEqual(rules['budgets']['simple']['target'], (1800, 2600))
        self.assertEqual(rules['budgets']['simple']['cap'], 3000)
        self.assertNotIn('budgets.simple', rules['unreadable'])

    def test_a_budget_wrapped_beyond_the_window_is_unreadable_not_wrong(self):
        # The conservative half of the trade. An unreadable rule is reported
        # and a human widens the pattern. A confidently wrong budget ships a
        # prompt the Brain rejects after the generation is paid for.
        text = ('- CUSTOM (Advanced):\n  style prompt\n  HARD\n'
                '  limit 1,000 characters, target 850 to 950.')
        rules = b.extract_rules(text)
        self.assertIs(rules['budgets']['custom']['cap'], b.UNREADABLE)
        self.assertIn('budgets.custom', rules['unreadable'])

    def test_a_banned_list_that_parses_to_nothing_is_unreadable(self):
        # An empty tuple reports as a rule read cleanly and then passes every
        # string: a validator switched off behind a green light.
        rules = b.extract_rules('Fatigue words banned in styles AND lyrics: .')
        self.assertIs(rules['banned_words'], b.UNREADABLE)
        self.assertIn('banned_words', rules['unreadable'])

    def test_a_rule_it_cannot_find_is_unreadable_not_empty(self):
        rules = b.extract_rules('a rules file with none of the expected labels')
        self.assertIs(rules['banned_words'], b.UNREADABLE)
        self.assertIn('banned_words', rules['unreadable'])

    def test_an_unreadable_budget_is_not_quietly_defaulted(self):
        rules = b.extract_rules('nothing here')
        self.assertIs(rules['budgets']['custom']['cap'], b.UNREADABLE)
        self.assertIn('budgets.custom', rules['unreadable'])


FULL_SHEET = {'facts': {
    'tempo': {'value': 80.7, 'unit': 'bpm', 'confidence': 'KNOW',
              'suno_actionable': 'direct'},
    'key': {'value': 'F# minor', 'unit': 'name', 'confidence': 'KNOW',
            'suno_actionable': 'direct'},
    'tuning': {'value': 'drop C#', 'unit': 'name', 'confidence': 'INFER',
               'suno_actionable': 'direct'},
    'lead_register': {'value': {'median_midi': 42.0, 'p10_midi': 38.0,
                                'p90_midi': 55.0},
                      'unit': 'midi', 'confidence': 'INFER',
                      'suno_actionable': 'direct'},
    'vocal_register': {'value': None, 'unit': 'midi', 'confidence': 'UNKNOWN',
                       'suno_actionable': 'direct'},
    'harmonic_rhythm': {'value': {'label': 'static', 'median_chord_bars': 4.0},
                        'unit': 'bars', 'confidence': 'INFER',
                        'suno_actionable': 'indirect'},
    'intro_seconds': {'value': 12.1, 'unit': 's', 'confidence': 'INFER',
                      'suno_actionable': 'direct'},
    'sections': {'value': {'count': 7, 'boundaries_s': []}, 'unit': 'count',
                 'confidence': 'INFER', 'suno_actionable': 'direct'},
    'spectral_balance': {'value': {'low_end_share': 16.4, 'centroid_hz': 1800.0,
                                   'air_share': 4.0},
                         'unit': 'percent', 'confidence': 'KNOW',
                         'suno_actionable': 'indirect'},
    'chords': {'value': [{'root': 'F#', 'quality': 'power'}],
               'unit': 'sequence', 'confidence': 'INFER',
               'suno_actionable': 'midi_only'},
}}


def _sheet_with(**axes):
    """FULL_SHEET plus or minus a few axes, without mutating the fixture."""
    facts = dict(FULL_SHEET['facts'])
    for name, entry in axes.items():
        if entry is None:
            facts.pop(name, None)
        else:
            facts[name] = entry
    return {'facts': facts}


def _every_phrase(filled):
    return sum((filled[key] for key in b.SLOT_KEYS), [])


class SlotTests(unittest.TestCase):
    def setUp(self):
        self.slots = b.slots(FULL_SHEET)

    def test_the_tempo_becomes_a_mood_tag_rounded_to_a_whole_bpm(self):
        self.assertTrue(any('81 BPM' in m for m in self.slots['moods']))

    def test_the_tuning_becomes_an_instrument_tag(self):
        joined = ' '.join(self.slots['instruments']).lower()
        self.assertIn('drop c', joined)

    def test_a_low_lead_register_becomes_a_low_register_tag_not_a_midi_number(self):
        joined = ' '.join(self.slots['instruments']).lower()
        self.assertIn('low', joined)
        self.assertNotIn('42', joined)

    def test_static_harmony_becomes_an_effect_not_a_chord_name(self):
        joined = ' '.join(self.slots['production']
                          + self.slots['direction']).lower()
        self.assertIn('static', joined)
        self.assertNotIn('f#', joined)

    def test_the_intro_length_reaches_the_direction_prose(self):
        joined = ' '.join(self.slots['direction']).lower()
        self.assertIn('12', joined)

    def test_a_chord_fact_is_midi_only_and_never_reaches_a_text_slot(self):
        text = ' '.join(_every_phrase(self.slots))
        self.assertNotIn('F#', text)
        self.assertTrue(self.slots['midi_only'])

    def test_an_unknown_axis_produces_no_tag_and_is_listed_as_unusable(self):
        self.assertIn('vocal_register', self.slots['unusable'])
        self.assertEqual(self.slots['vocals'], [])

    def test_a_low_end_share_becomes_a_production_cue_not_a_percentage(self):
        joined = ' '.join(self.slots['production']).lower()
        self.assertNotIn('16.4', joined)
        self.assertTrue(joined)

    def test_a_measured_section_count_reaches_the_direction_prose(self):
        filled = b.slots(_sheet_with(section_count={
            'value': 7, 'unit': 'count', 'confidence': 'INFER',
            'suno_actionable': 'direct'}))
        self.assertTrue(any('7' in s for s in filled['direction']))
        self.assertNotIn('direction_prose_second_sentence', filled['unusable'])

    def test_boundaries_give_a_second_sentence_without_stating_a_count(self):
        # The real sheet's shape: section_count is UNKNOWN by construction and
        # the boundaries are real, so the shape is sayable and the count is not.
        filled = b.slots(_sheet_with(section_boundaries={
            'value': [0.0, 7.8, 12.1, 32.9, 57.5, 69.7, 107.8, 134.5],
            'unit': 's', 'confidence': 'INFER', 'suno_actionable': 'direct'}))
        self.assertEqual(len(filled['direction']), 2)
        self.assertNotIn('direction_prose_second_sentence', filled['unusable'])
        second = filled['direction'][1]
        self.assertIn('38', second)          # the longest span, 107.8 to 69.7
        self.assertNotIn('8', second.split('38')[0])   # never the count

    def test_a_sheet_that_cannot_fill_the_second_sentence_says_so(self):
        self.assertIn('direction_prose_second_sentence', self.slots['unusable'])

    def test_no_slot_phrase_contains_a_negation_word(self):
        # Every branch, not only the ones FULL_SHEET reaches. The direction
        # sentences are the long ones and the likeliest to carry a banned word.
        for filled in (self.slots,
                       b.slots(_sheet_with(section_count={
                           'value': 7, 'unit': 'count', 'confidence': 'INFER',
                           'suno_actionable': 'direct'})),
                       b.slots(_sheet_with(section_boundaries={
                           'value': [0.0, 7.8, 12.1, 32.9, 57.5],
                           'unit': 's', 'confidence': 'INFER',
                           'suno_actionable': 'direct'}))):
            for phrase in _every_phrase(filled):
                for word in b.NEGATION_WORDS:
                    self.assertIsNone(
                        re.search(rf'\b{word}\b', phrase.lower()),
                        f'{phrase!r} contains {word!r}')

    def test_no_slot_phrase_contains_a_hyphen(self):
        for phrase in _every_phrase(self.slots):
            self.assertNotIn('-', phrase, phrase)

    def test_an_infer_tempo_is_asked_about_rather_than_silently_tagged(self):
        filled = b.slots(_sheet_with(tempo={
            'value': 80.7, 'unit': 'bpm', 'confidence': 'INFER',
            'suno_actionable': 'direct',
            'note': 'a competing metrical level at 4/3'}))
        self.assertTrue(filled['ask_first'])
        self.assertIn('4/3', filled['ask_first'][0])

    def test_a_known_tempo_asks_nothing(self):
        self.assertEqual(self.slots['ask_first'], [])

    def test_an_unknown_tempo_produces_no_bpm_at_all(self):
        filled = b.slots(_sheet_with(tempo={
            'value': None, 'unit': 'bpm', 'confidence': 'UNKNOWN',
            'suno_actionable': 'direct'}))
        self.assertEqual(filled['moods'], [])
        self.assertEqual(filled['ask_first'], [])


if __name__ == '__main__':
    unittest.main()
