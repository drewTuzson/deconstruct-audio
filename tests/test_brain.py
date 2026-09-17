from pathlib import Path
import json
import os
import subprocess
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import brain as b

# A synthetic rules file. Invented for this test. Contains no third party text.
#
# The banned words, every heading and all of the connecting prose are made up.
# What is NOT made up, and cannot be, is the handful of label tokens the
# extractor keys on: the four mode names, `Target N to N characters`, `cap N`,
# `limit N characters, target N to N`, `Limit N`, `Fatigue words banned`, and
# `Never:`. Those same strings are the regexes in scripts/brain.py, because a
# parser for a document has to name the labels it parses. A fixture that
# reworded them would pass while proving nothing about the file this runs
# against, which is the shape of check this project exists to refuse.
#
# So the rule for editing this fixture is: the label tokens stay, everything
# around them is invented. An earlier version had the decoration copied too,
# and shared runs of six to nine words with the real Brain for no gain.
FIXTURE_INSTRUCTIONS = """
## STEP ONE: CHOOSE A MODE
- SIMPLE: one field, nothing else. Target 1,800 to 2,600 characters
  (outer cap 3,000).
- CUSTOM (Layered): the style field has a limit 1,000 characters, target 850 to 950.
- STUDIO: a lone element. Limit 1,000.

## WORDS THE FIXTURE REFUSES
Fatigue words banned anywhere a reader looks: wibbly, frobnicate, sparkletastic.
Never: "in the manner of", "sort of like".

## SINGING, OPPOSITES, THE EXCLUDE FIELD
EXCLUDE: name what you want there. Target 180 to 200 characters.
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
        marker = '## WORDS'
        budgets_only, banned_only = FIXTURE_INSTRUCTIONS.split(marker)
        _, rules = b.rules_from({'SYSTEM-PROMPT-FULL.txt': budgets_only,
                                 'INSTRUCTIONS.txt': marker + banned_only})
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
        text = ('Pick one of SIMPLE, CUSTOM, STUDIO.\n'
                '- STUDIO: a lone element.\n'
                '- SIMPLE: Target 2,000 to 2,500 characters (outer cap 3,000).\n'
                '- CUSTOM (Layered): the style field has a limit 1,000 '
                'characters, target 850 to 950.')
        rules = b.extract_rules(text)
        self.assertEqual(rules['budgets']['custom']['cap'], 1000)
        self.assertEqual(rules['budgets']['custom']['target'], (850, 950))

    def test_a_longer_word_containing_a_mode_name_is_not_that_mode(self):
        text = ('You may CUSTOMISE the output.\n'
                '- SIMPLE: Target 2,000 to 2,500 characters (outer cap 3,000).\n'
                '- CUSTOM (Layered): the style field has a limit 1,000 '
                'characters, target 850 to 950.')
        self.assertEqual(b.extract_rules(text)['budgets']['custom']['cap'], 1000)

    def test_a_budget_wrapping_inside_its_own_window_is_still_read(self):
        # The wording the first implementation could not read. A rules file
        # hard wraps, so the target and the cap land on either side of a line
        # break, and the pattern that forbade a newline between them reported
        # UNREADABLE on the most ordinary shape there is. Widening it is safe
        # because the window is already bounded by the next mode; the case
        # below proves that boundary still holds.
        text = ('- SIMPLE: one field, nothing else. Target 1,800 to 2,600 '
                'characters\n  (outer cap 3,000).')
        rules = b.extract_rules(text)
        self.assertEqual(rules['budgets']['simple']['target'], (1800, 2600))
        self.assertEqual(rules['budgets']['simple']['cap'], 3000)
        self.assertNotIn('budgets.simple', rules['unreadable'])

    def test_a_budget_wrapped_beyond_the_window_is_unreadable_not_wrong(self):
        # The conservative half of the trade. An unreadable rule is reported
        # and a human widens the pattern. A confidently wrong budget ships a
        # prompt the Brain rejects after the generation is paid for.
        text = ('- CUSTOM (Layered):\n  the style field\n  has a\n'
                '  limit 1,000 characters, target 850 to 950.')
        rules = b.extract_rules(text)
        self.assertIs(rules['budgets']['custom']['cap'], b.UNREADABLE)
        self.assertIn('budgets.custom', rules['unreadable'])

    def test_a_banned_list_that_parses_to_nothing_is_unreadable(self):
        # An empty tuple reports as a rule read cleanly and then passes every
        # string: a validator switched off behind a green light.
        rules = b.extract_rules('Fatigue words banned anywhere a reader looks: .')
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


    def test_a_malformed_axis_is_unusable_rather_than_a_crash(self):
        # read_facts guarantees the file is a JSON object, not that every axis
        # carries a Fact. Reaching entry.get on a non Fact raised a bare
        # AttributeError, which the top level handler turns into 'Details
        # suppressed to protect secrets'.
        for broken in (None, 'a string', 42, ['a', 'list']):
            filled = b.slots({'facts': {'tempo': broken}})
            self.assertIn('tempo', filled['unusable'], broken)
            self.assertEqual(filled['moods'], [], broken)

    def test_a_sheet_with_no_facts_mapping_is_empty_rather_than_a_crash(self):
        for broken in ({}, {'facts': None}, {'facts': []}, {'facts': 'text'}):
            self.assertEqual(b.slots(broken)['moods'], [], broken)

    def test_a_malformed_value_names_its_axis_rather_than_raising(self):
        # facts.py owns the shape of each value and this module reads it, so
        # the two can drift; the sections axis split once already. A string
        # tempo or a scalar register used to reach float() and raise, which the
        # top level handler prints as 'Details suppressed to protect secrets'.
        cases = {
            'tempo': {'value': 'eighty one', 'confidence': 'KNOW'},
            'tuning': {'value': 42, 'confidence': 'INFER'},
            'lead_register': {'value': {}, 'confidence': 'INFER'},
            'vocal_register': {'value': 55.0, 'confidence': 'INFER'},
            'spectral_balance': {'value': {'centroid_hz': 1800.0},
                                 'confidence': 'KNOW'},
            'harmonic_rhythm': {'value': {'median_chord_bars': 4.0},
                                'confidence': 'INFER'},
            'intro_seconds': {'value': 'twelve', 'confidence': 'INFER'},
            'section_count': {'value': [7], 'confidence': 'INFER'},
            'section_boundaries': {'value': [0.0, 'later'],
                                   'confidence': 'INFER'},
            'key': {'value': 7, 'confidence': 'KNOW'},
        }
        for axis, entry in cases.items():
            filled = b.slots({'facts': {axis: entry}})
            self.assertIn(axis, filled['unusable'], axis)
            self.assertEqual(_every_phrase(filled), [], axis)

    def test_a_non_finite_measurement_is_unusable(self):
        # write_json refuses a NaN on the way out. This refuses one on the way
        # in, rather than writing 'nan BPM' into a prompt.
        for broken in (float('nan'), float('inf')):
            filled = b.slots({'facts': {'tempo': {'value': broken,
                                                  'confidence': 'KNOW'}}})
            self.assertEqual(filled['moods'], [])
            self.assertIn('tempo', filled['unusable'])

    def test_an_integer_past_the_float_range_is_unusable(self):
        # JSON carries integers of unbounded size and float() refuses the ones
        # past its range, so this raised OverflowError where the axis should
        # simply have been unusable.
        filled = b.slots({'facts': {'tempo': {'value': 10 ** 400,
                                              'confidence': 'KNOW'}}})
        self.assertEqual(filled['moods'], [])
        self.assertIn('tempo', filled['unusable'])

    def test_a_boolean_is_not_a_measurement(self):
        # True is an int in Python and would otherwise become 1 BPM.
        filled = b.slots({'facts': {'tempo': {'value': True,
                                              'confidence': 'KNOW'}}})
        self.assertEqual(filled['moods'], [])
        self.assertIn('tempo', filled['unusable'])

    def test_an_axis_nobody_recognises_cannot_be_held_out(self):
        # Ignoring it held nothing out while held_out still reported the name,
        # so HELD_OUT= printed a control that was never applied.
        with self.assertRaises(b.BrainError):
            b.slots(FULL_SHEET, hold_out='lead_regsiter')
        for axis in b.HOLD_OUT_CHOICES:
            self.assertEqual(b.slots(FULL_SHEET, hold_out=axis)['held_out'],
                             axis)

    def test_an_unknown_tempo_produces_no_bpm_at_all(self):
        filled = b.slots(_sheet_with(tempo={
            'value': None, 'unit': 'bpm', 'confidence': 'UNKNOWN',
            'suno_actionable': 'direct'}))
        self.assertEqual(filled['moods'], [])
        self.assertEqual(filled['ask_first'], [])



# The note tempo.py writes when the tempogram shows a competing level. It is
# kept because a human reads it and the ASK_FIRST line quotes it, but nothing
# parses it any more: the family is its own axis now.
FAMILY_NOTE = ('Methods agree but the tempogram shows a competing metrical '
               'level with meaningful support: 3/4 at 64.6 BPM (tempogram '
               'relative strength 0.60); 4/3 at 107.7 BPM (tempogram relative '
               'strength 0.74); 1.5x at 129.2 BPM (tempogram relative '
               'strength 0.43); 2x at 161.5 BPM (tempogram relative strength '
               '0.90)')
INFER_TEMPO = {'value': 80.7, 'unit': 'bpm', 'confidence': 'INFER',
               'suno_actionable': 'direct', 'note': FAMILY_NOTE}
FAMILY_MEMBERS = [
    {'bpm': 64.6, 'ratio': '3/4', 'method': 'tempogram',
     'relative_strength': 0.6},
    {'bpm': 107.7, 'ratio': '4/3', 'method': 'tempogram',
     'relative_strength': 0.74},
    {'bpm': 129.2, 'ratio': '1.5x', 'method': 'tempogram',
     'relative_strength': 0.43},
    {'bpm': 161.5, 'ratio': '2x', 'method': 'tempogram',
     'relative_strength': 0.9},
]


def _family_axis(members=None, **over):
    entry = {'value': FAMILY_MEMBERS if members is None else members,
             'unit': 'members', 'confidence': 'INFER',
             'suno_actionable': 'none'}
    entry.update(over)
    return entry


def _family_sheet(members=None, tempo=None, **over):
    """FULL_SHEET with both tempo axes, the shape facts.py now writes."""
    axes = {'tempo': dict(tempo or INFER_TEMPO),
            'tempo_family': _family_axis(members)}
    axes.update(over)
    return _sheet_with(**axes)


class TempoLevelTests(unittest.TestCase):
    """Answering the question ASK_FIRST asks.

    The pipeline could raise an INFER tempo and could suppress the complaint,
    but it had no way to accept an answer: writing the chosen level into the
    style orphaned it on numbers_trace, because the only traceable BPM was the
    primary. The question was therefore advice, and the pre spend checklist's
    step 2 was decorative.

    The levels are read from the `tempo_family` axis. They used to be parsed
    out of `tempo`'s note, because the family reached a sheet only as prose,
    and on two of the three corpus tracks that prose names its ratios without
    their BPMs, so those levels could not be recovered at all.
    """

    def test_it_reads_every_level_the_measurement_reported(self):
        levels = b.tempo_levels(INFER_TEMPO, _family_axis())
        self.assertEqual(sorted(l['bpm'] for l in levels),
                         [64.6, 80.7, 107.7, 129.2, 161.5])
        self.assertIn('primary', [l['source'] for l in levels])

    def test_a_family_member_resolves_and_carries_its_label(self):
        chosen = b.select_tempo_level(INFER_TEMPO, _family_axis(), 161.5)
        self.assertEqual(chosen['bpm'], 161.5)
        self.assertEqual(chosen['source'], 'family 2x')
        self.assertEqual(chosen['relative_strength'], 0.9)

    def test_the_primary_resolves(self):
        chosen = b.select_tempo_level(INFER_TEMPO, _family_axis(), 80.7)
        self.assertEqual(chosen['bpm'], 80.7)
        self.assertEqual(chosen['source'], 'primary')

    def test_a_member_with_a_ratio_and_no_strength_is_still_selectable(self):
        # The non-octave-ratio branch: grade() builds these from a method's own
        # estimate, so they carry a bpm and a ratio but no tempogram strength.
        # These are exactly the levels the prose reader could not recover.
        members = [{'bpm': 101.3, 'ratio': '4/3', 'method': 'beat-track',
                    'relative_strength': None}]
        chosen = b.select_tempo_level(INFER_TEMPO, _family_axis(members), 101.3)
        self.assertEqual(chosen['bpm'], 101.3)
        self.assertEqual(chosen['source'], 'family 4/3')
        self.assertIsNone(chosen['relative_strength'])

    def test_the_whole_number_a_prompt_would_state_resolves(self):
        # The style says '162 BPM', not '161.5 BPM', so the integer has to
        # round trip or the flag cannot be reused on a rerun.
        family = _family_axis()
        self.assertEqual(
            b.select_tempo_level(INFER_TEMPO, family, 162)['bpm'], 161.5)
        self.assertEqual(
            b.select_tempo_level(INFER_TEMPO, family, 161)['bpm'], 161.5)

    def test_a_value_the_measurement_never_reported_is_refused(self):
        with self.assertRaises(b.BrainError) as caught:
            b.select_tempo_level(INFER_TEMPO, _family_axis(), 160)
        message = str(caught.exception)
        for value in ('64.6', '80.7', '107.7', '129.2', '161.5'):
            self.assertIn(value, message)

    def test_a_sheet_without_the_axis_says_so_rather_than_implying_no_family(self):
        # A sheet written before tempo_family existed carries no family at all.
        # That is a different situation from a tempo with no competing level,
        # and the refusal has to distinguish them or it sends someone looking
        # for a measurement problem that is really a stale sheet.
        with self.assertRaises(b.BrainError) as caught:
            b.select_tempo_level(INFER_TEMPO, None, 161.5)
        self.assertIn('no tempo_family axis', str(caught.exception))
        self.assertIn('Rerun facts', str(caught.exception))

    def test_an_axis_graded_unknown_is_not_reported_as_a_missing_axis(self):
        # Three situations look alike from the refusal and none may be guessed
        # at. An axis present but graded UNKNOWN was being reported as absent,
        # which sends someone to rerun facts over a sheet that is not stale.
        unknown = _family_axis(confidence='UNKNOWN')
        self.assertEqual([l['bpm'] for l in b.tempo_levels(INFER_TEMPO,
                                                           unknown)], [80.7])
        with self.assertRaises(b.BrainError) as caught:
            b.select_tempo_level(INFER_TEMPO, unknown, 161.5)
        message = str(caught.exception)
        self.assertIn('graded UNKNOWN', message)
        self.assertNotIn('no tempo_family axis', message)
        self.assertNotIn('Rerun facts', message)

    def test_an_unknown_axis_reaches_that_message_through_slots(self):
        sheet = _family_sheet()
        sheet['facts']['tempo_family']['confidence'] = 'UNKNOWN'
        with self.assertRaises(b.BrainError) as caught:
            b.slots(sheet, tempo_level=161.5)
        self.assertIn('graded UNKNOWN', str(caught.exception))

    def test_a_tempo_with_no_competing_level_offers_only_its_primary(self):
        plain = {'value': 80.7, 'unit': 'bpm', 'confidence': 'KNOW',
                 'suno_actionable': 'direct', 'note': None}
        empty = _family_axis([], confidence='KNOW')
        self.assertEqual([l['bpm'] for l in b.tempo_levels(plain, empty)],
                         [80.7])
        with self.assertRaises(b.BrainError) as caught:
            b.select_tempo_level(plain, empty, 161.5)
        self.assertNotIn('no tempo_family axis', str(caught.exception))

    def test_a_member_with_no_bpm_is_unselectable_and_counted(self):
        members = FAMILY_MEMBERS + [{'ratio': '3x', 'method': 'ioi',
                                     'relative_strength': 0.2}]
        family = _family_axis(members)
        self.assertEqual(len(b.tempo_levels(INFER_TEMPO, family)), 5)
        with self.assertRaises(b.BrainError) as caught:
            b.select_tempo_level(INFER_TEMPO, family, 200)
        self.assertIn('1 family member(s) carry no readable bpm',
                      str(caught.exception))

    def test_a_family_hanging_off_an_unmeasured_tempo_is_not_selectable(self):
        # No primary means the axis is UNKNOWN. Offering its levels would let a
        # prompt state a BPM for a track whose tempo the sheet declined to
        # report.
        self.assertEqual(
            b.tempo_levels({'value': None, 'confidence': 'UNKNOWN'},
                           _family_axis()), [])

    def test_a_mangled_member_is_skipped_rather_than_raising(self):
        # The family is data now, but a hand edited sheet is not bound by that.
        for members in ([{'bpm': 'fast', 'ratio': '2x'}],
                        [{'bpm': None, 'ratio': '2x'}],
                        ['not a member'], [{'bpm': float('nan')}]):
            levels = b.tempo_levels(INFER_TEMPO, _family_axis(members))
            self.assertEqual([l['bpm'] for l in levels], [80.7], members)

    def test_a_mangled_strength_costs_the_strength_not_the_level(self):
        # The BPM is the measurement and the relative strength is context, so
        # an unreadable strength must not discard a level the family names.
        levels = b.tempo_levels(
            INFER_TEMPO,
            _family_axis([{'bpm': 161.5, 'ratio': '2x',
                           'relative_strength': 'strong'}]))
        self.assertEqual([l['bpm'] for l in levels], [80.7, 161.5])
        self.assertIsNone(levels[1]['relative_strength'])

    def test_two_levels_equidistant_from_the_choice_do_not_crash(self):
        # Sorting (distance, level) tuples fell through to comparing the dicts
        # when the distances tied, which raises TypeError and reaches the user
        # as 'Details suppressed to protect secrets'.
        tied = _family_axis([{'bpm': 161.0, 'ratio': '2x'},
                             {'bpm': 162.0, 'ratio': '3x'}])
        self.assertEqual(abs(161.0 - 161.5), abs(162.0 - 161.5))
        chosen = b.select_tempo_level(INFER_TEMPO, tied, 161.5)
        self.assertEqual(chosen['bpm'], 161.0)
        self.assertEqual(b.select_tempo_level(INFER_TEMPO, tied, 161.5), chosen)

    def test_the_nearest_level_wins_when_two_are_in_range(self):
        near = _family_axis([{'bpm': 161.0, 'ratio': '2x'},
                             {'bpm': 161.8, 'ratio': '3x'}])
        self.assertEqual(
            b.select_tempo_level(INFER_TEMPO, near, 161.7)['bpm'], 161.8)
        self.assertEqual(
            b.select_tempo_level(INFER_TEMPO, near, 161.1)['bpm'], 161.0)

    def test_the_selection_reaches_the_moods_slot(self):
        filled = b.slots(_family_sheet(), tempo_level=161.5)
        self.assertEqual(filled['moods'], ['162 BPM'])
        self.assertNotIn('81 BPM', filled['moods'])

    def test_the_selected_number_traces(self):
        filled = b.slots(_family_sheet(), tempo_level=161.5)
        self.assertIn((162, 'bpm'), b.slot_quantities(filled))
        results = b.validate('162 BPM. It opens quietly. It ends loudly.',
                             GOOD_EXCLUDE, SHEET, rules(), filled=filled,
                             declared=('It opens quietly', 'It ends loudly'),
                             dropped=tuple(
                                 p for key in b.SLOT_KEYS
                                 for p in filled[key] if 'BPM' not in p))
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'PASS')

    def test_the_selection_records_who_chose_it_and_from_where(self):
        chosen = b.slots(_family_sheet(), tempo_level=161.5)['tempo_selection']
        self.assertEqual(chosen['bpm'], 161.5)
        self.assertEqual(chosen['source'], 'family 2x')
        self.assertEqual(chosen['relative_strength'], 0.9)
        self.assertIn('selected', chosen['note'].lower())
        self.assertIn('2x', chosen['note'])
        self.assertIn('0.9', chosen['note'])

    def test_selecting_a_level_answers_the_tempo_question_on_its_own(self):
        filled = b.slots(_family_sheet(), tempo_level=161.5)
        self.assertEqual(filled['ask_first'], [])
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, rules(),
                             filled=filled)
        self.assertEqual(check(results, 'ask_first')['verdict'], 'PASS')

    def test_another_question_still_needs_acknowledging(self):
        filled = b.slots(_family_sheet(), tempo_level=161.5)
        filled['ask_first'] = ['some other axis wants a human answer']
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, rules(),
                             filled=filled)
        self.assertEqual(check(results, 'ask_first')['verdict'], 'FAIL')

    def test_without_the_flag_nothing_changes(self):
        before = b.slots(_family_sheet())
        self.assertEqual(before['moods'], ['81 BPM'])
        self.assertIsNone(before['tempo_selection'])
        self.assertEqual(len(before['ask_first']), 1)
        self.assertEqual(before, b.slots(_family_sheet(), tempo_level=None))

    def test_the_family_axis_never_becomes_a_slot_phrase(self):
        # suno_actionable is 'none': it is read to resolve an ambiguity and
        # reaches a prompt only through tempo.
        filled = b.slots(_family_sheet(), tempo_level=161.5)
        every = ' '.join(_every_phrase(filled))
        for value in ('64.6', '107.7', '129.2', '161.5', '3/4', '4/3'):
            self.assertNotIn(value, every)

    def test_a_refused_level_stops_the_run_rather_than_guessing(self):
        with self.assertRaises(b.BrainError):
            b.slots(_family_sheet(), tempo_level=160)

    def test_a_held_out_tempo_cannot_also_be_selected(self):
        with self.assertRaises(b.BrainError):
            b.slots(_family_sheet(), hold_out='tempo', tempo_level=161.5)

    def test_an_unusable_tempo_cannot_be_selected(self):
        unknown = {'value': None, 'unit': 'bpm', 'confidence': 'UNKNOWN',
                   'suno_actionable': 'direct'}
        with self.assertRaises(b.BrainError):
            b.slots(_family_sheet(tempo=unknown), tempo_level=161.5)


SHEET = {'facts': {
    'tempo': {'value': 80.7, 'unit': 'bpm', 'confidence': 'KNOW',
              'suno_actionable': 'direct'},
    'key': {'value': 'F# minor', 'unit': 'name', 'confidence': 'KNOW',
            'suno_actionable': 'direct'},
    'sections': {'value': {'count': 7, 'boundaries_s': []}, 'unit': 'count',
                 'confidence': 'INFER', 'suno_actionable': 'direct'},
}}

# The style a compliant agent composes from FULL_SHEET's slots: every measured
# phrase, plus the judgement it declares. Built from its two halves rather than
# written out once, because the declared list has to name exactly the pieces
# that are not measurements, and a hand copied pair drifts the moment either
# side is edited. test_the_fixture_style_really_carries_every_slot_phrase keeps
# the measured half honest against slots() itself.
MEASURED_TAGS = ('81 BPM', 'drop C sharp tuned rhythm guitar',
                 'very low register lead guitar figure', 'heavy low end',
                 'static harmony')
MEASURED_SENTENCE = ('The song opens on roughly 12 seconds of build before the '
                     'full arrangement lands.')
# BPM sits inside the moods, near the head of the stack, as the Brain requires.
GOOD_TAGS = ('Rock', 'Post Hardcore', 'defiant', 'urgent', '81 BPM',
             'drop C sharp tuned rhythm guitar',
             'very low register lead guitar figure', 'heavy low end',
             'static harmony', 'thick distorted bass', 'blunt kick thud',
             'group shout vocals', 'one lead vocalist only',
             'wide room reverb', 'driving eighth note pulse',
             'raw analogue warmth', 'tight gated snare',
             'layered guitar harmonies', 'saturated tape bus',
             'live room drum bleed', 'blown out chorus energy',
             'restless forward momentum', 'anthemic final chorus',
             'dense midrange guitar wall', 'cutting pick attack',
             'urgent snare rolls', 'close mic vocal grit',
             'stacked backing shouts', 'muscular bass drive')
JUDGEMENT_SENTENCES = (
    'It holds one harmonic centre while the drums thicken underneath it.',
    'It ends on a stripped final phrase that lets the room ring out.',
    'The vocal stays front and centre through every chorus.')
GOOD_STYLE = (', '.join(GOOD_TAGS) + '. ' + MEASURED_SENTENCE + ' '
              + ' '.join(JUDGEMENT_SENTENCES))
GOOD_DECLARED = (tuple(t for t in GOOD_TAGS if t not in MEASURED_TAGS)
                 + JUDGEMENT_SENTENCES)
GOOD_EXCLUDE = ('bright major key, clean jazz guitar, smooth crooner vocals, '
                'dance pop production, orchestral strings, spoken word, lo fi '
                'tape hiss, swing rhythm, acoustic ballad arrangement, '
                'cheerful major melody')

# A cap that a real overflow can be measured against. The slot phrases render to
# 191 characters, so a cap of 150 genuinely forces one drop and admits the other
# five, while the plan's 200 forced nothing: restoring the dropped phrase fitted
# and the drop read as unjustified. The target starts at 100 so the kept style
# clears the budget check too, which is what makes the drop branch observable in
# context rather than behind an unrelated failure.
NARROW = FIXTURE_INSTRUCTIONS.replace(
    'limit 1,000 characters, target 850 to 950',
    'limit 150 characters, target 100 to 150')


def rules():
    return b.extract_rules(FIXTURE_INSTRUCTIONS)


def check(results, name):
    return next(r for r in results if r['check'] == name)


class ValidatorTests(unittest.TestCase):
    def run_it(self, style=GOOD_STYLE, exclude=GOOD_EXCLUDE, **kw):
        # The default declaration set is the judgement in GOOD_STYLE: the genre
        # pair, the moods, the vocal tags and the production taste. Measured
        # phrases are not declared, because they must come from the slots or
        # fail.
        kw.setdefault('declared', GOOD_DECLARED)
        kw.setdefault('filled', b.slots(FULL_SHEET))
        return b.validate(style, exclude, SHEET, rules(), **kw)

    def test_the_fixture_style_really_carries_every_slot_phrase(self):
        # The fixture's claim, checked rather than trusted. If slots() changes
        # its wording, this fails here instead of quietly turning the clean
        # style into one that no longer accounts for its measurements.
        filled = b.slots(FULL_SHEET)
        self.assertEqual(
            sorted(p for key in b.SLOT_KEYS for p in filled[key]),
            sorted(MEASURED_TAGS + (MEASURED_SENTENCE,)))

    def test_a_clean_style_passes_every_check_it_can_run(self):
        results = self.run_it()
        failed = [r for r in results if r['verdict'] != 'PASS']
        self.assertEqual(failed, [], failed)

    def test_a_negation_word_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' no falsetto')
        self.assertEqual(check(results, 'negation')['verdict'], 'FAIL')

    def test_negation_inside_a_longer_word_does_not_trip_it(self):
        results = self.run_it(style=GOOD_STYLE + ' nocturne, notation, without')
        detail = check(results, 'negation')['detail']
        self.assertNotIn('nocturne', detail)
        self.assertNotIn('notation', detail)
        self.assertIn('without', detail)

    def test_a_stray_hyphen_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' palm-muted')
        self.assertEqual(check(results, 'hyphens')['verdict'], 'FAIL')

    def test_a_letter_prefix_genre_keeps_its_hyphen(self):
        results = self.run_it(style='J-Pop, ' + GOOD_STYLE)
        self.assertEqual(check(results, 'hyphens')['verdict'], 'PASS')

    def test_a_banned_word_from_the_brain_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' sparkletastic pads')
        self.assertEqual(check(results, 'banned_words')['verdict'], 'FAIL')

    def test_a_banned_phrase_from_the_brain_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' sort of like a ballad')
        self.assertEqual(check(results, 'banned_phrases')['verdict'], 'FAIL')

    def test_over_the_hard_cap_fails(self):
        results = self.run_it(style='a, ' * 400)
        self.assertEqual(check(results, 'budget')['verdict'], 'FAIL')

    def test_under_the_target_fails_rather_than_passing_quietly(self):
        results = self.run_it(style='Rock, Post Hardcore, 81 BPM. It opens.')
        self.assertEqual(check(results, 'budget')['verdict'], 'FAIL')

    def test_a_style_with_no_direction_prose_fails(self):
        tags_only = ('Rock, Post Hardcore, defiant, urgent, 81 BPM, downtuned '
                     'rhythm guitar, thick distorted bass, blunt kick thud, '
                     'group shout vocals, ') * 3
        results = self.run_it(style=tags_only)
        self.assertEqual(check(results, 'direction_prose')['verdict'], 'FAIL')

    def test_a_bpm_at_the_tail_fails_because_it_belongs_in_the_moods(self):
        tail = GOOD_STYLE.replace(', 81 BPM', '') + ' 81 BPM'
        results = self.run_it(style=tail)
        self.assertEqual(check(results, 'bpm_placement')['verdict'], 'FAIL')

    def test_a_held_out_tempo_can_still_reach_a_clean_verdict(self):
        # The contradiction between the tempo rule and this check. slots emits
        # no BPM when tempo is held out, absent or UNKNOWN; numbers_trace then
        # rejects a BPM that is not in the slots, and bpm_placement used to
        # reject a style that left it out. --hold-out tempo, the control the
        # exit bar leans on, could never have passed.
        filled = b.slots(FULL_SHEET, hold_out='tempo')
        kept = tuple(t for t in GOOD_TAGS if t != '81 BPM')
        style = (', '.join(kept) + '. ' + MEASURED_SENTENCE + ' '
                 + ' '.join(JUDGEMENT_SENTENCES))
        results = b.validate(
            style, GOOD_EXCLUDE, SHEET, rules(), filled=filled,
            declared=tuple(t for t in kept if t not in MEASURED_TAGS)
            + JUDGEMENT_SENTENCES)
        self.assertEqual(check(results, 'bpm_placement')['verdict'], 'PASS')
        self.assertEqual([r for r in results if r['verdict'] != 'PASS'], [])

    def test_a_bpm_the_sheet_never_measured_fails(self):
        # The other half, so the relaxation above is not a way through. With no
        # tempo in the slots, a style that states one is quoting a number
        # nobody measured.
        filled = b.slots(FULL_SHEET, hold_out='tempo')
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, rules(),
                             filled=filled, declared=GOOD_DECLARED)
        entry = check(results, 'bpm_placement')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('did not measure', entry['detail'])

    def test_a_measured_tempo_left_out_of_the_style_fails(self):
        without = (', '.join(t for t in GOOD_TAGS if t != '81 BPM') + '. '
                   + MEASURED_SENTENCE + ' ' + ' '.join(JUDGEMENT_SENTENCES))
        results = self.run_it(style=without)
        entry = check(results, 'bpm_placement')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('never reached the style', entry['detail'])

    def test_a_number_that_traces_to_no_fact_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' 140 BPM')
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'FAIL')

    def test_a_number_that_rounds_from_a_fact_passes(self):
        results = self.run_it()
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'PASS')

    def test_a_single_digit_number_is_traced_too(self):
        # The earlier pattern looked only at runs of two to four digits, so a
        # prompt could state a section count on a sheet that measured none.
        results = self.run_it(style=GOOD_STYLE + ' 7 sections')
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'FAIL')

    def test_a_number_under_the_wrong_unit_does_not_trace(self):
        # The hole a bare set of integers left. The tempo slot holds '81 BPM',
        # so a declared sentence saying '81 seconds of tape delay' passed this
        # check and then passed provenance as judgement, and the command
        # approved a duration the fact sheet never established.
        sentence = '81 seconds of tape delay on the lead'
        results = self.run_it(
            style=GOOD_STYLE + ' ' + sentence + '.',
            declared=GOOD_DECLARED + (sentence,))
        entry = check(results, 'numbers_trace')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('81 seconds', entry['detail'])

    def test_the_same_number_under_its_own_unit_still_traces(self):
        results = self.run_it()
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'PASS')

    def test_a_number_in_the_exclude_field_is_traced_too(self):
        # The exclude field is prompt content like any other and reaches the
        # generator the same way, so a model number nobody measured was
        # passing because only the style was read.
        exclude = ('909 drum machine, 1987 gated reverb, bright major key, '
                   'clean jazz guitar, smooth crooner vocals, dance pop '
                   'production, orchestral strings, spoken word, swing rhythm')
        results = self.run_it(exclude=exclude)
        entry = check(results, 'numbers_trace')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('909', entry['detail'])
        self.assertIn('1987', entry['detail'])

    def test_a_measured_number_may_appear_in_the_exclude_field(self):
        # The rule is that a number traces, not that the exclude field is
        # barred from carrying one.
        exclude = GOOD_EXCLUDE.replace('swing rhythm', '81 bpm swing')
        results = self.run_it(exclude=exclude)
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'PASS')

    def test_a_supplied_name_anywhere_in_either_field_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' like Placeholder Band',
                              names=('Placeholder Band',))
        self.assertEqual(check(results, 'names')['verdict'], 'FAIL')

    def test_a_name_inside_a_longer_word_is_not_that_name(self):
        # `--name Rush` rejecting 'brushed drums' is a false FAIL on an honest
        # prompt, and noise like that trains an operator to stop reading the
        # checks before the spend.
        results = self.run_it(style=GOOD_STYLE + ' brushed drums',
                              names=('Rush',))
        self.assertEqual(check(results, 'names')['verdict'], 'PASS')

    def test_a_whole_name_beside_punctuation_still_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' (Rush), loud',
                              names=('Rush',))
        self.assertEqual(check(results, 'names')['verdict'], 'FAIL')

    def test_a_negation_in_the_exclude_field_fails(self):
        results = self.run_it(exclude='no bright major key, clean jazz guitar')
        self.assertEqual(check(results, 'exclude_negation')['verdict'], 'FAIL')

    def test_an_exclude_outside_its_budget_fails(self):
        results = self.run_it(exclude='strings')
        self.assertEqual(check(results, 'exclude_budget')['verdict'], 'FAIL')

    def test_an_invented_style_sharing_one_phrase_still_fails(self):
        # The defect this contract replaces. The previous check asked whether
        # ANY slot phrase appeared, so a style about a converted grain silo
        # that happened to carry one tag passed all thirteen checks.
        invented = ('81 BPM, converted grain silo reverb, hand cranked music '
                    'box, letterpress clatter. The piece begins in a stairwell '
                    'and never leaves it. It ends when the tape runs out.')
        results = self.run_it(style=invented)
        self.assertEqual(check(results, 'provenance')['verdict'], 'FAIL')

    def test_a_slot_sentence_carrying_a_comma_survives_decomposition(self):
        # The shape the real reference sheet produces. Its section count is
        # UNKNOWN, so the second direction sentence comes from the boundaries
        # branch and carries a comma. _decompose splits the tag stack on commas
        # and the prose on sentence ends, so a comma inside a slot SENTENCE
        # must not break it into pieces that then read as unaccounted. Nothing
        # covered this, and it would have surfaced at the expensive moment.
        sheet = _sheet_with(section_boundaries={
            'value': [0.0, 7.8, 12.1, 32.9, 57.5, 69.7, 107.8, 134.5],
            'unit': 's', 'confidence': 'INFER', 'suno_actionable': 'direct'})
        filled = b.slots(sheet)
        self.assertIn(',', filled['direction'][1])
        tags = [p for key in b.SLOT_KEYS for p in filled[key]
                if p not in filled['direction']]
        style = ', '.join(tags) + '. ' + ' '.join(filled['direction'])
        results = b.validate(style, GOOD_EXCLUDE, SHEET, rules(), filled=filled)
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'PASS', entry['detail'])
        self.assertIn('0 unaccounted', entry['detail'])
        self.assertIn('0 slot phrases silently unused', entry['detail'])
        self.assertEqual(check(results, 'numbers_trace')['verdict'], 'PASS')

    def test_declared_judgement_passes_and_is_counted_separately(self):
        results = self.run_it(declared=GOOD_DECLARED)
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'PASS')
        self.assertIn('declared as judgement', entry['detail'])

    def test_a_style_that_is_entirely_judgement_fails(self):
        # Declaring everything is the other way to sever the prompt from the
        # measurements, and it must not be a way through.
        tags = 'Rock, Post Hardcore, defiant. It opens quietly. It ends loudly.'
        results = self.run_it(style=tags,
                              declared=('Rock', 'Post Hardcore', 'defiant',
                                        'It opens quietly', 'It ends loudly'))
        self.assertEqual(check(results, 'provenance')['verdict'], 'FAIL')

    def test_declaring_the_measured_phrase_too_does_not_rescue_it(self):
        # The route that survived the first inversion. bpm_placement mandates a
        # BPM and numbers_trace mandates it trace to a slot, so '81 BPM' is in
        # every passing prompt by construction. Counting a DECLARED piece as
        # coming from a measurement let it disable the severance test single
        # handedly.
        invented = ('81 BPM, converted grain silo reverb, hand cranked music '
                    'box. The piece begins in a stairwell. It ends when the '
                    'tape runs out.')
        results = self.run_it(
            style=invented,
            declared=('81 BPM', 'converted grain silo reverb',
                      'hand cranked music box',
                      'The piece begins in a stairwell',
                      'It ends when the tape runs out'))
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('declared but matching a measured slot', entry['detail'])

    def test_a_measurement_left_out_without_being_dropped_fails(self):
        # The symmetric half. Accounting for the style is only half a contract:
        # one slot phrase plus four honest declarations satisfied the first
        # version while six measurements sat on the floor.
        invented = ('81 BPM, converted grain silo reverb, hand cranked music '
                    'box. The piece begins in a stairwell. It ends when the '
                    'tape runs out.')
        results = self.run_it(
            style=invented,
            declared=('converted grain silo reverb', 'hand cranked music box',
                      'The piece begins in a stairwell',
                      'It ends when the tape runs out'))
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('left out without being dropped', entry['detail'])

    def test_dropping_every_slot_does_not_discharge_the_obligation(self):
        # The attack that defeated the first symmetric version: paste the whole
        # slot list into --dropped and an 859 character prompt about a grain
        # silo, carrying one number from the sheet, passed all thirteen checks.
        # A drop must be FORCED, and the slots fit with room to spare.
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        kept = [p for p in every if 'BPM' in p]
        results = self.run_it(
            style=', '.join(kept) + '. It opens quietly. It ends loudly.',
            filled=filled,
            declared=('It opens quietly', 'It ends loudly'),
            dropped=tuple(p for p in every if p not in kept))
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('not forced', entry['detail'])

    def test_a_minimal_drop_forced_by_a_real_overflow_is_allowed(self):
        # The case the flag exists for, at a cap the rest of the checks can
        # still pass. An earlier version used a cap of 60, where the fixed tail
        # alone is 36 characters and `budget` could never pass, so it asserted
        # only `provenance` and proved nothing about the branch in context. A
        # later one used 200, which the slot phrases fit inside, so no drop was
        # ever forced and the branch under test was never reached.
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        longest = max(every, key=len)
        kept = [p for p in every if p != longest]
        narrow = b.extract_rules(NARROW)
        results = b.validate(', '.join(kept), GOOD_EXCLUDE, SHEET, narrow,
                             filled=filled, dropped=(longest,))
        self.assertEqual(check(results, 'provenance')['verdict'], 'PASS')
        self.assertEqual(check(results, 'budget')['verdict'], 'PASS')

    def test_a_drop_larger_than_the_overflow_needs_is_refused(self):
        # Minimality is the whole rule. Dropping two phrases when one would
        # have brought the slots inside the cap is not forced, and the message
        # names the phrase that should have stayed.
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        two_longest = sorted(every, key=len)[-2:]
        kept = [p for p in every if p not in two_longest]
        narrow = b.extract_rules(NARROW)
        results = b.validate(', '.join(kept), GOOD_EXCLUDE, SHEET, narrow,
                             filled=filled, dropped=tuple(two_longest))
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('not minimal', entry['detail'])

    def test_a_drop_with_an_unreadable_budget_cannot_be_justified(self):
        blind = b.extract_rules('a file with none of the labels')
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        results = b.validate('81 BPM. It opens quietly. It ends loudly.',
                             GOOD_EXCLUDE, SHEET, blind, filled=filled,
                             declared=('It opens quietly', 'It ends loudly'),
                             dropped=tuple(p for p in every if 'BPM' not in p))
        entry = check(results, 'provenance')
        self.assertEqual(entry['verdict'], 'FAIL')
        self.assertIn('could not be read', entry['detail'])

    def test_the_counts_in_the_note_add_up_to_the_pieces(self):
        # A reviewer reads this line immediately before approving a spend, and
        # the earlier version subtracted a set's length from a list's, so a
        # style repeating one tag reported judgement nobody declared.
        results = self.run_it(
            style='81 BPM, 81 BPM, 81 BPM. It opens. It ends.',
            declared=('It opens', 'It ends'))
        detail = check(results, 'provenance')['detail']
        numbers = [int(n)
                   for n in re.findall(r'(\d+) (?:from|declared|un)', detail)]
        self.assertEqual(sum(numbers[:4]), 5)

    def test_a_phrase_cannot_be_inverted_and_still_count_as_inherited(self):
        # The prefix match let 'roughly 12 seconds of build' and 'roughly 12
        # minutes of total silence' score as the same measurement.
        inverted = GOOD_STYLE.replace('roughly 12 seconds of build',
                                      'roughly 12 minutes of total silence')
        self.assertNotEqual(inverted, GOOD_STYLE)
        results = self.run_it(style=inverted)
        self.assertEqual(check(results, 'provenance')['verdict'], 'FAIL')

    def test_an_unacknowledged_ask_first_fails(self):
        filled = b.slots(FULL_SHEET)
        filled['ask_first'] = ['tempo is graded INFER: competing level at 4/3']
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, rules(),
                             filled=filled)
        self.assertEqual(check(results, 'ask_first')['verdict'], 'FAIL')

    def test_an_acknowledged_ask_first_passes(self):
        filled = b.slots(FULL_SHEET)
        filled['ask_first'] = ['tempo is graded INFER: competing level at 4/3']
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, rules(),
                             filled=filled, acknowledged=True)
        self.assertEqual(check(results, 'ask_first')['verdict'], 'PASS')

    def test_the_default_control_is_one_of_the_choices(self):
        self.assertIn(b.HOLD_OUT_DEFAULT, b.HOLD_OUT_CHOICES)

    def test_a_held_out_axis_leaves_no_trace_in_the_slots(self):
        held = b.slots(FULL_SHEET, hold_out='lead_register')
        self.assertEqual(held['held_out'], 'lead_register')
        joined = ' '.join(held['instruments']).lower()
        self.assertNotIn('lead guitar figure', joined)
        kept = b.slots(FULL_SHEET)
        self.assertIn('lead guitar figure',
                      ' '.join(kept['instruments']).lower())

    def test_an_unreadable_rule_reports_unknown_rather_than_pass(self):
        blind = b.extract_rules('a file with none of the labels')
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, blind)
        self.assertEqual(check(results, 'banned_words')['verdict'], 'UNKNOWN')
        self.assertEqual(check(results, 'budget')['verdict'], 'UNKNOWN')


class ParserTests(unittest.TestCase):
    def test_the_parser_agrees_with_the_module(self):
        # Behavioural, not bytecode. The first version of this test read
        # deconstruct.main.__code__.co_consts for the literal, and CPython only
        # folds a tuple of constants: putting one non literal into `choices`
        # unfolds it and the test silently passes on a broken default. The trap
        # was that the obvious next improvement, sourcing `choices` from
        # brain.HOLD_OUT_CHOICES, is exactly the change that disables it.
        import deconstruct
        parser = deconstruct.build_parser()
        args = parser.parse_args(['prompt', 'facts.json'])
        self.assertEqual(args.hold_out, b.HOLD_OUT_DEFAULT)
        for axis in b.HOLD_OUT_CHOICES:
            parsed = parser.parse_args(['prompt', 'facts.json',
                                        '--hold-out', axis])
            self.assertEqual(parsed.hold_out, axis)
        parsed = parser.parse_args(['prompt', 'facts.json',
                                    '--hold-out', 'none'])
        self.assertEqual(parsed.hold_out, 'none')

    def test_an_unknown_verdict_does_not_exit_zero(self):
        # The exit code layer of the same rule the validators enforce. A style
        # whose rules could not be read is not a style that passed, and a
        # wrapping script gating on the exit code would otherwise spend the
        # user's money on a prompt nothing checked.
        import deconstruct
        self.assertEqual(deconstruct.PROMPT_EXIT['PASS'], 0)
        self.assertNotEqual(deconstruct.PROMPT_EXIT['UNKNOWN'], 0)
        self.assertNotEqual(deconstruct.PROMPT_EXIT['FAIL'], 0)


class CommandTests(unittest.TestCase):
    """End to end, through a real process, because the exit code is the point.

    cmd_prompt returns its code rather than raising SystemExit, and main() has
    to hand that code back out. Checking the two halves separately would miss
    a dispatch branch that called the command and discarded what it returned,
    which is how the verdict gets lost between them.
    """

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.private = self.tmp / 'private'
        self.private.mkdir(mode=0o700)
        self.out = self.tmp / 'out'
        self.facts = self.tmp / 'facts.json'
        self.facts.write_text(json.dumps(FULL_SHEET), encoding='utf-8')
        self.style = self.tmp / 'style.txt'
        self.style.write_text(GOOD_STYLE, encoding='utf-8')
        self.exclude = self.tmp / 'exclude.txt'
        self.exclude.write_text(GOOD_EXCLUDE, encoding='utf-8')

    def connect(self, instructions=FIXTURE_INSTRUCTIONS):
        folder = self.tmp / 'brain'
        folder.mkdir(exist_ok=True)
        (folder / 'INSTRUCTIONS.txt').write_text(instructions, encoding='utf-8')
        (self.private / 'config.json').write_text(
            json.dumps({'brain_path': str(folder)}), encoding='utf-8')
        return folder

    def run_cli(self, *argv):
        env = dict(os.environ)
        env['DECONSTRUCT_AUDIO_CONFIG_DIR'] = str(self.private)
        env.pop('GEMINI_API_KEY', None)
        env.pop('GOOGLE_API_KEY', None)
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'deconstruct.py'), *argv],
            capture_output=True, text=True, timeout=120, env=env)

    def validated(self, *extra):
        return self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--style', str(self.style),
                            '--exclude', str(self.exclude),
                            '--hold-out', 'none', *extra)

    def test_with_no_style_it_writes_the_slots_and_checks_nothing(self):
        self.connect()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f'SLOTS_WRITTEN={self.out / "slots.json"}', done.stdout)
        self.assertIn('RULES_FROM=INSTRUCTIONS.txt', done.stdout)
        self.assertIn('HELD_OUT=lead_register', done.stdout)
        self.assertIn('PROMPT_VERDICT=UNKNOWN', done.stdout)
        self.assertNotIn('RULE_UNREADABLE', done.stderr)
        written = json.loads((self.out / 'slots.json').read_text())
        self.assertEqual(written['held_out'], 'lead_register')

    def test_the_held_out_line_is_printed_even_with_no_control(self):
        self.connect()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--hold-out', 'none')
        self.assertIn('HELD_OUT=none', done.stdout)

    def test_a_clean_style_passes_and_exits_zero(self):
        self.connect()
        added = [arg for piece in GOOD_DECLARED for arg in ('--added', piece)]
        done = self.validated(*added)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('PROMPT_VERDICT=PASS', done.stdout)
        check = json.loads((self.out / 'prompt-check.json').read_text())
        self.assertEqual(check['verdict'], 'PASS')
        self.assertEqual(check['mode'], 'custom')

    def test_a_failing_style_is_a_verdict_and_not_a_crash(self):
        # Exit 2, and no suppression text, because a FAIL must reach the user
        # as the check that failed rather than as a traceback the handler ate.
        self.connect()
        done = self.validated()
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn('PROMPT_VERDICT=FAIL', done.stdout)
        self.assertIn('FAIL    provenance', done.stdout)
        self.assertNotIn('Details suppressed', done.stderr)
        self.assertNotIn('Traceback', done.stderr)

    def test_a_brain_whose_rules_cannot_be_read_never_exits_zero(self):
        self.connect('a rules file with none of the expected labels')
        added = [arg for piece in GOOD_DECLARED for arg in ('--added', piece)]
        done = self.validated(*added)
        self.assertEqual(done.returncode, 4, done.stdout + done.stderr)
        self.assertIn('PROMPT_VERDICT=UNKNOWN', done.stdout)
        self.assertIn('RULE_UNREADABLE=banned_words', done.stderr)

    def test_an_unacknowledged_ask_first_reaches_the_user_and_fails(self):
        self.connect()
        infer = json.loads(json.dumps(FULL_SHEET))
        infer['facts']['tempo']['confidence'] = 'INFER'
        infer['facts']['tempo']['note'] = 'a competing metrical level at 4/3'
        self.facts.write_text(json.dumps(infer), encoding='utf-8')
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertIn('ASK_FIRST=tempo is graded INFER', done.stdout)

    def _family_facts(self, with_axis=True):
        sheet = json.loads(json.dumps(FULL_SHEET))
        sheet['facts']['tempo'] = dict(INFER_TEMPO)
        if with_axis:
            sheet['facts']['tempo_family'] = _family_axis()
        self.facts.write_text(json.dumps(sheet), encoding='utf-8')

    def test_a_selected_level_is_printed_and_reaches_the_slots(self):
        self.connect()
        self._family_facts()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--tempo-level', '161.5')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('TEMPO_LEVEL=161.5 SOURCE=family 2x', done.stdout)
        self.assertNotIn('ASK_FIRST=', done.stdout)
        written = json.loads((self.out / 'slots.json').read_text())
        self.assertEqual(written['moods'], ['162 BPM'])
        self.assertEqual(written['tempo_selection']['source'], 'family 2x')

    def test_a_level_the_measurement_never_reported_is_authored(self):
        self.connect()
        self._family_facts()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--tempo-level', '160')
        self.assertEqual(done.returncode, 1)
        self.assertIn('not a level this measurement reported', done.stderr)
        self.assertIn('161.5', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)
        self.assertNotIn('Traceback', done.stderr)

    def test_a_sheet_predating_the_family_axis_says_so(self):
        # The honest failure for a stale sheet: it names the missing axis and
        # what to do, rather than reporting a family that is simply absent.
        self.connect()
        self._family_facts(with_axis=False)
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--tempo-level', '161.5')
        self.assertEqual(done.returncode, 1)
        self.assertIn('no tempo_family axis', done.stderr)
        self.assertIn('Rerun facts', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)

    def test_without_the_flag_the_question_is_still_asked(self):
        self.connect()
        self._family_facts()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertIn('ASK_FIRST=tempo is graded INFER', done.stdout)
        self.assertNotIn('TEMPO_LEVEL=', done.stdout)
        written = json.loads((self.out / 'slots.json').read_text())
        self.assertEqual(written['moods'], ['81 BPM'])

    def test_an_unusable_axis_is_named_rather_than_left_to_be_noticed(self):
        self.connect()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertIn('UNUSABLE_AXES=', done.stdout)
        self.assertIn('vocal_register', done.stdout)

    def test_no_brain_connected_is_an_authored_message(self):
        (self.private / 'config.json').write_text('{}', encoding='utf-8')
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertEqual(done.returncode, 1)
        self.assertIn('No Brain is connected', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)

    def test_a_brain_error_survives_the_top_level_handler(self):
        # BrainError wrapped in SkillError, or the authored sentence is
        # replaced by 'Details suppressed to protect secrets'.
        (self.private / 'config.json').write_text(
            json.dumps({'brain_path': str(self.tmp / 'nowhere')}),
            encoding='utf-8')
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out))
        self.assertEqual(done.returncode, 1)
        self.assertIn('No Brain folder at', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)

    def test_a_mistyped_style_path_is_an_authored_message(self):
        self.connect()
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--style', str(self.tmp / 'missing.txt'))
        self.assertEqual(done.returncode, 1)
        self.assertIn('Cannot read the --style file', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)

    def test_an_unreadable_exclude_file_is_an_authored_message(self):
        self.connect()
        broken = self.tmp / 'exclude.bin'
        broken.write_bytes(b'\xff\xfe not utf 8 \xff')
        done = self.run_cli('prompt', str(self.facts), '--out', str(self.out),
                            '--style', str(self.style), '--exclude', str(broken))
        self.assertEqual(done.returncode, 1)
        self.assertIn('Cannot read the --exclude file', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)

    def test_a_mistyped_fact_sheet_path_is_an_authored_message(self):
        self.connect()
        done = self.run_cli('prompt', str(self.tmp / 'missing.json'),
                            '--out', str(self.out))
        self.assertEqual(done.returncode, 1)
        self.assertIn('Cannot read the input fact sheet', done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)


if __name__ == '__main__':
    unittest.main()
