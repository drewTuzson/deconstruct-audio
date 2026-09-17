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
             'static harmony', 'thick distorted bass', 'punchy kick drum',
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
    'HARD limit 1,000 characters, target 850 to 950',
    'HARD limit 150 characters, target 100 to 150')


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
                     'rhythm guitar, thick distorted bass, punchy kick drum, '
                     'group shout vocals, ') * 3
        results = self.run_it(style=tags_only)
        self.assertEqual(check(results, 'direction_prose')['verdict'], 'FAIL')

    def test_a_bpm_at_the_tail_fails_because_it_belongs_in_the_moods(self):
        tail = GOOD_STYLE.replace(', 81 BPM', '') + ' 81 BPM'
        results = self.run_it(style=tail)
        self.assertEqual(check(results, 'bpm_placement')['verdict'], 'FAIL')

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

    def test_a_supplied_name_anywhere_in_either_field_fails(self):
        results = self.run_it(style=GOOD_STYLE + ' like Placeholder Band',
                              names=('Placeholder Band',))
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


if __name__ == '__main__':
    unittest.main()
