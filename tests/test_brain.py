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


if __name__ == '__main__':
    unittest.main()
