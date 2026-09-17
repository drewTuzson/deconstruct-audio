# Brain Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compose a Suno prompt from the fact sheet alone, formatted to the user's own SunoGPT Brain, and refuse to emit one that the Brain's own final check would reject.

**Architecture:** One service module, `brain.py`, that reads the Brain from the path already saved in the config, extracts its rules from that text at runtime, fills slots from `facts.json`, and validates. One thin command. No Brain content is copied into this repository: the rules are read from the user's own files every run, so a Brain update changes the checks.

**Tech Stack:** Python 3.10+, standard library only.

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

## Global Constraints

- Python 3.10 or newer.
- **Import `brain` inside `cmd_prompt`, never at module level.** See the comment at `scripts/deconstruct.py:22`.
- **Wrap `BrainError` in `SkillError`.** The handler at `scripts/deconstruct.py:730` suppresses any other exception's message. See the research plan for the same rule.
- **`cmd_prompt` returns its exit code, it does not raise `SystemExit`.** Check how `cmd_compare` at `scripts/deconstruct.py:588` returns `COMPARE_EXIT` and follow that, so a FAIL verdict is a verdict rather than a crash.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`.
- Baseline is 97 tests, OK, one skipped. Any drop is a regression.
- **No Brain text in this repository.** Not in code, not in comments, not in a test fixture. The Brain is licensed third party material. Tests run against a synthetic fixture Brain the test writes itself.
- `brain.py` imports nothing outside the standard library and makes no network call.
- The composer reads `facts.json` and nothing else. Not `impressions.md`, not `listening.md`, not `report.md`.
- Never open `credentials.json`. Read `brain_path` through a narrow helper, as `references/brain.md` requires.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## Why the rules are read rather than written down

The obvious build hardcodes the Brain's banned word list and character budgets
into `brain.py`. That does two bad things: it copies licensed content into this
repository, and it freezes a moving target, so a Brain update silently stops
being enforced while the tests keep passing.

So `brain.py` extracts each rule from the Brain text at runtime by locating its
labelled line. When an extraction fails, that check reports `UNKNOWN` and the
command says which rule it could not read. It never silently passes. A check
that cannot find its rule is not a check that passed.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/brain.py` (create) | Reading the Brain, extracting rules, filling slots from facts, validating. |
| `scripts/deconstruct.py` (modify) | The `prompt` command. |
| `tests/test_brain.py` (create) | Rule extraction against a synthetic Brain, slot filling, every validator. |

---

### Task 1: Reading the Brain and extracting its rules

**Files:**
- Create: `scripts/brain.py`
- Create: `tests/test_brain.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `brain_sources(path) -> dict[str, str]`, `extract_rules(text) -> dict`, `BrainError`, `UNREADABLE`.

`extract_rules` returns:

```python
{'budgets': {'simple': {'target': (1800, 2600), 'cap': 3000},
             'custom': {'target': (850, 950), 'cap': 1000},
             'studio': {'target': None, 'cap': 1000}},
 'banned_words': ('velvet', ...),      # or UNREADABLE
 'banned_phrases': ('vibe of', ...),   # or UNREADABLE
 'exclude_budget': (180, 200),         # or UNREADABLE
 'unreadable': ['banned_words']}       # names of every rule it could not read
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_brain.py`. The fixture Brain is written by the test in the
wording a rules file of this kind uses, and contains no text from the user's
actual Brain.

```python
from pathlib import Path
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

    def _brain(self, **files):
        for name, text in files.items():
            (self.dir / name.replace('_', '-').replace('.txt', '') ).write_text('')
        return self.dir

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/brain.py`:

```python
#!/usr/bin/env python3
"""Compose a Suno prompt from the fact sheet, in the user's own Brain format.

No Brain text lives in this file. The rules are extracted from the user's own
Brain at runtime, so a Brain update changes the checks instead of silently
going unenforced while the tests keep passing.

A rule that cannot be found reports UNREADABLE. It never reports a pass. A
check that could not locate its rule is not a check that succeeded, and this
project exists because something once reported a result it had not earned.
"""
import re
from pathlib import Path


class BrainError(Exception):
    pass


class _Unreadable:
    """Sentinel for a rule the Brain text did not yield."""
    def __repr__(self):
        return 'UNREADABLE'
    def __bool__(self):
        return False


UNREADABLE = _Unreadable()

INSTRUCTION_FILES = ('SYSTEM-PROMPT-FULL.txt', 'INSTRUCTIONS.txt')
NUMBER = r'([\d,]+)'


def _int(token):
    return int(str(token).replace(',', ''))


MODE_WINDOW_LINES = 3
MODE_TOKENS = ('SIMPLE', 'CUSTOM', 'STUDIO', 'EXCLUDE')


def _near(text, token, pattern):
    """Search for `pattern` only in the lines belonging to `token`.

    Anchoring matters more than the pattern does, and two things have to be
    true for the anchor to hold.

    The token must be a WORD. A plain substring test matched `CUSTOMISE` and
    read the next mode's budget as CUSTOM's, returning cap 3000 where the
    answer is 1000, with nothing in `unreadable` to say so.

    The window must STOP at the next mode. A Brain that lists its modes before
    defining them puts `SIMPLE, CUSTOM, STUDIO` on one line, and a fixed three
    line window from `CUSTOM` then runs straight into SIMPLE's budget. Same
    wrong answer, same silence.

    Failing to UNREADABLE when a budget wraps beyond the window is the correct
    trade. An unreadable rule is reported and a human widens the pattern; a
    confidently wrong budget ships a prompt the Brain rejects after the
    generation is paid for.
    """
    lines = text.splitlines()
    boundary = re.compile(r'\b(' + '|'.join(MODE_TOKENS) + r')\b')
    word = re.compile(r'\b' + re.escape(token) + r'\b')
    for index, line in enumerate(lines):
        if not word.search(line):
            continue
        window = [line]
        for following in lines[index + 1:index + MODE_WINDOW_LINES]:
            other = boundary.search(following)
            if other and other.group(1) != token:
                break
            window.append(following)
        found = re.search(pattern, '\n'.join(window))
        if found:
            return found
    return None


def brain_sources(path):
    """Every readable source in a Brain folder, keyed by relative name."""
    folder = Path(path)
    if not folder.is_dir():
        raise BrainError(f'No Brain folder at {folder}')
    sources = {}
    for name in INSTRUCTION_FILES:
        target = folder / name
        if target.is_file():
            sources[name] = target.read_text(encoding='utf-8', errors='replace')
    if not sources:
        raise BrainError(
            f'{folder} holds none of {", ".join(INSTRUCTION_FILES)}. '
            f'Run connect-brain against the folder that does, rather than '
            f'letting this compose against rules it never read.')
    knowledge = folder / 'knowledge'
    if knowledge.is_dir():
        for target in sorted(knowledge.glob('*.md')):
            sources[f'knowledge/{target.name}'] = target.read_text(
                encoding='utf-8', errors='replace')
    return sources


def extract_rules(text):
    """Locate each rule in the Brain text. Never guess one that is not there."""
    rules = {'budgets': {}, 'unreadable': []}

    # Every one of these is anchored to the MODE'S OWN LINES, never spanning
    # the document with `.*?` and re.S.
    #
    # The span version was measured wrong and, worse, wrong without saying so.
    # On a Brain that names its modes before defining them, the CUSTOM pattern
    # ran from the first `CUSTOM` token to the first budget clause it found
    # anywhere after it, and returned cap 3000 with target (2000, 2500) instead
    # of cap 1000 with target (850, 950). It did not appear in `unreadable`.
    # A 2400 character style then passes the budget check green and the Brain
    # rejects it after the generation is paid for.
    simple = _near(text, 'SIMPLE',
                   rf'[Tt]arget\s+{NUMBER}\s+to\s+{NUMBER}\s+characters'
                   rf'[^\n]*?cap\s+{NUMBER}')
    rules['budgets']['simple'] = (
        {'target': (_int(simple.group(1)), _int(simple.group(2))),
         'cap': _int(simple.group(3))} if simple
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    custom = _near(text, 'CUSTOM',
                   rf'limit\s+{NUMBER}\s+characters,\s+target\s+{NUMBER}'
                   rf'\s+to\s+{NUMBER}')
    rules['budgets']['custom'] = (
        {'target': (_int(custom.group(2)), _int(custom.group(3))),
         'cap': _int(custom.group(1))} if custom
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    studio = _near(text, 'STUDIO', rf'[Ll]imit\s+{NUMBER}')
    rules['budgets']['studio'] = (
        {'target': None, 'cap': _int(studio.group(1))} if studio
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    banned = re.search(r'[Ff]atigue words banned[^:]*:\s*([^\n.]+)', text)
    words = tuple(w.strip().lower()
                  for w in banned.group(1).split(',') if w.strip()) if banned else ()
    # An empty parse is UNREADABLE, never an empty tuple. A tuple of nothing
    # reports as a rule that was read cleanly and then passes every string,
    # which is a validator that has been switched off while showing a green
    # light. That is the single most dangerous shape a check can take.
    rules['banned_words'] = words if words else UNREADABLE

    never = re.search(r'\bNever:\s*([^\n]+)', text)
    found = tuple(p.strip().strip('"').lower()
                  for p in re.findall(r'"([^"]+)"', never.group(1))) if never else ()
    rules['banned_phrases'] = found if found else UNREADABLE

    exclude = _near(text, 'EXCLUDE',
                    rf'[Tt]arget\s+{NUMBER}\s+to\s+{NUMBER}')
    rules['exclude_budget'] = (
        (_int(exclude.group(1)), _int(exclude.group(2))) if exclude
        else UNREADABLE)

    for mode, budget in rules['budgets'].items():
        if budget['cap'] is UNREADABLE:
            rules['unreadable'].append(f'budgets.{mode}')
    for key in ('banned_words', 'banned_phrases', 'exclude_budget'):
        if rules[key] is UNREADABLE:
            rules['unreadable'].append(key)
    return rules
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Prove extraction against the real Brain**

The real Brain is at the path saved in the config. This step reads it and prints
what was extracted, so an extraction that silently fails on the real file is
caught now rather than at the exit bar.

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
.venv/bin/python -c "
import json, sys; sys.path.insert(0, 'scripts')
import brain
from pathlib import Path
path = json.loads(Path.home().joinpath('.config/deconstruct-audio/config.json')
                  .read_text())['brain_path']
rules = brain.extract_rules(brain.brain_sources(path)['INSTRUCTIONS.txt'])
print('budgets', rules['budgets'])
print('banned_words', rules['banned_words'])
print('exclude_budget', rules['exclude_budget'])
print('UNREADABLE:', rules['unreadable'])
"
```

Expected: a custom cap of 1000 with a target of (850, 950), a non-empty banned
word list, an exclude budget, and an empty `unreadable` list. If any rule comes
back `UNREADABLE`, widen that one regex and add a test for the wording it missed.
Do not paste the extracted banned word list into the repository. Report in the
pull request only the count and which rules read cleanly.

- [ ] **Step 6: Commit**

```bash
git add scripts/brain.py tests/test_brain.py
git commit -m "feat: read the Brain's rules from the Brain instead of copying them"
```

---

### Task 2: The validators

**Files:**
- Modify: `scripts/brain.py`
- Modify: `tests/test_brain.py`

**Interfaces:**
- Consumes: `extract_rules` output from Task 1.
- Produces: `validate(style, exclude, sheet, rules, mode='custom', names=()) -> list[dict]` where each entry is `{'check', 'verdict', 'detail'}` with `verdict` in `('PASS', 'FAIL', 'UNKNOWN')`. Also `HYPHEN_EXCEPTIONS`, `NEGATION_WORDS`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_brain.py` before `if __name__`:

```python
SHEET = {'facts': {
    'tempo': {'value': 80.7, 'unit': 'bpm', 'confidence': 'KNOW',
              'suno_actionable': 'direct'},
    'key': {'value': 'F# minor', 'unit': 'name', 'confidence': 'KNOW',
            'suno_actionable': 'direct'},
    'sections': {'value': {'count': 7, 'boundaries_s': []}, 'unit': 'count',
                 'confidence': 'INFER', 'suno_actionable': 'direct'},
}}

GOOD_STYLE = (
    'Rock, Post Hardcore, defiant, urgent, 81 BPM, downtuned rhythm guitar, '
    'thick distorted bass, punchy kick drum, group shout vocals, one lead '
    'vocalist only. The song opens on a long instrumental build before the '
    'full arrangement lands. It holds one harmonic centre while the drums '
    'thicken underneath. It ends on a stripped final phrase.')
GOOD_EXCLUDE = ('bright major key, clean jazz guitar, smooth crooner vocals, '
                'dance pop production, orchestral strings, spoken word')


def rules():
    return b.extract_rules(FIXTURE_INSTRUCTIONS)


def check(results, name):
    return next(r for r in results if r['check'] == name)


class ValidatorTests(unittest.TestCase):
    def run_it(self, style=GOOD_STYLE, exclude=GOOD_EXCLUDE, **kw):
        # The default declaration set is the judgement in GOOD_STYLE: the
        # genre pair, the moods and the vocal tags. Measured phrases are not
        # declared, because they must come from the slots or fail.
        kw.setdefault('declared', ('Rock', 'Post Hardcore', 'defiant', 'urgent',
                                   'group shout vocals',
                                   'one lead vocalist only',
                                   'thick distorted bass', 'punchy kick drum'))
        kw.setdefault('filled', b.slots(FULL_SHEET))
        return b.validate(style, exclude, SHEET, rules(), **kw)

    def test_a_clean_style_passes_every_check_it_can_run(self):
        results = self.run_it()
        failed = [r for r in results if r['verdict'] == 'FAIL']
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
        results = self.run_it(
            declared=('Rock', 'Post Hardcore', 'defiant', 'urgent',
                      'group shout vocals', 'one lead vocalist only',
                      'thick distorted bass', 'punchy kick drum'))
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
                      'hand cranked music box', 'The piece begins in a stairwell',
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
        # only `provenance` and proved nothing about the branch in context.
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        longest = max(every, key=len)
        kept = [p for p in every if p != longest]
        narrow = b.extract_rules(FIXTURE_INSTRUCTIONS.replace(
            'HARD limit 1,000 characters, target 850 to 950',
            'HARD limit 200 characters, target 150 to 200'))
        results = b.validate(', '.join(kept), GOOD_EXCLUDE, SHEET, narrow,
                             filled=filled, dropped=(longest,))
        self.assertEqual(check(results, 'provenance')['verdict'], 'PASS')

    def test_a_drop_larger_than_the_overflow_needs_is_refused(self):
        # Minimality is the whole rule. Dropping two phrases when one would
        # have brought the slots inside the cap is not forced, and the message
        # names the phrase that should have stayed.
        filled = b.slots(FULL_SHEET)
        every = [p for key in b.SLOT_KEYS for p in filled.get(key, [])]
        two_longest = sorted(every, key=len)[-2:]
        kept = [p for p in every if p not in two_longest]
        narrow = b.extract_rules(FIXTURE_INSTRUCTIONS.replace(
            'HARD limit 1,000 characters, target 850 to 950',
            'HARD limit 200 characters, target 150 to 200'))
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
        results = self.run_it(style='81 BPM, 81 BPM, 81 BPM. It opens. It ends.',
                              declared=('It opens', 'It ends'))
        detail = check(results, 'provenance')['detail']
        numbers = [int(n) for n in re.findall(r'(\d+) (?:from|declared|un)', detail)]
        self.assertEqual(sum(numbers[:4]), 5)

    def test_a_phrase_cannot_be_inverted_and_still_count_as_inherited(self):
        # The prefix match let 'roughly 12 seconds of build' and 'roughly 12
        # minutes of total silence' score as the same measurement.
        inverted = GOOD_STYLE.replace(
            'opens on a long instrumental build',
            'opens on a long instrumental silence')
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

    def test_the_default_control_is_one_of_the_choices(self):
        self.assertIn(b.HOLD_OUT_DEFAULT, b.HOLD_OUT_CHOICES)

    def test_a_held_out_axis_leaves_no_trace_in_the_slots(self):
        held = b.slots(FULL_SHEET, hold_out='lead_register')
        self.assertEqual(held['held_out'], 'lead_register')
        joined = ' '.join(held['instruments']).lower()
        self.assertNotIn('lead guitar figure', joined)
        kept = b.slots(FULL_SHEET)
        self.assertIn('lead guitar figure', ' '.join(kept['instruments']).lower())

    def test_an_unreadable_rule_reports_unknown_rather_than_pass(self):
        blind = b.extract_rules('a file with none of the labels')
        results = b.validate(GOOD_STYLE, GOOD_EXCLUDE, SHEET, blind)
        self.assertEqual(check(results, 'banned_words')['verdict'], 'UNKNOWN')
        self.assertEqual(check(results, 'budget')['verdict'], 'UNKNOWN')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: FAIL, `AttributeError: module 'brain' has no attribute 'validate'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/brain.py`:

```python
# The Brain's rule is that a ruled out trait becomes its positive opposite.
# Three words do not cover that. Measured: 'absent', 'free of', 'never' and
# 'excluding' all passed a validator claiming to enforce it.
#
# This list will never be complete, and the check is therefore a floor rather
# than a proof. It is still worth having, because every entry is a phrase a
# prompt writer actually reaches for.
NEGATION_WORDS = ('no', 'not', 'without', 'never', 'absent', 'lacking',
                  'excluding', 'except', 'minus', 'sans', 'devoid', 'neither',
                  'nor', 'none', 'avoid', 'omit', 'exclude', 'free of',
                  'free from', 'stripped of', 'rather than', 'instead of')
HYPHEN_EXCEPTIONS = re.compile(
    r'\b[A-Z]-[A-Za-z]+\b'          # letter prefix genres such as J-Pop
    r'|\[[^\]]*\]')                 # bracketed tags
INSTRUMENTAL_EXEMPTION = 'fully instrumental, no vocals'
SENTENCE = re.compile(r'[.!?](?:\s|$)')
PROSE_MIN_SENTENCES = 2
MOODS_FRACTION = 0.6   # BPM must appear inside the first 60 percent of the tags


def _result(name, verdict, detail=''):
    return {'check': name, 'verdict': verdict, 'detail': detail}


def _found_words(text, words):
    low = text.lower()
    return [w for w in words if re.search(rf'\b{re.escape(w)}\b', low)]


def slot_numbers(filled):
    """Every number that appears in a slot phrase.

    The traceable set is the SLOTS, not the facts. Three reasons, and the
    second one is a measured defect rather than a preference.

    The prompt is supposed to be written from slots.json. Tracing against the
    slots is therefore the same question as 'did this come from the fact
    sheet', which is the claim the exit bar makes and could not previously
    check.

    The earlier version traced against the facts AND blessed the double and the
    half of every one of them. On a track measured at 80.7 that made 161 a
    traceable number, which is the exact 2x metrical level this track reports
    at relative strength 0.90: the one wrong tempo most likely to be written,
    waved through by the check meant to catch it. Across the integers 10 to
    200, 19.45 percent traced by coincidence.

    And it skipped single digit numbers entirely, so a prompt could say
    '7 sections' on a sheet whose section count is UNKNOWN.
    """
    out = set()
    for key in SLOT_KEYS:
        for phrase in filled.get(key, []):
            for token in re.findall(r'\d+', str(phrase)):
                out.add(int(token))
    return out


# A boundary worth naming rather than discovering later. Tracing against the
# slots moves the trust boundary one step: a number the SLOT BUILDER invented
# now traces to itself. The fallback direction sentence is the live instance.
# It says "its longest unbroken stretch runs about 38 seconds", 38 is a
# difference between two measured boundaries rather than a measured value, and
# it appears nowhere in facts.json yet traces cleanly.
#
# That is acceptable and it is not nothing. The slot builder is code in this
# repository with tests, which is a different class of thing from a sentence an
# agent wrote. The check answers "did this come from the fact sheet, through
# code we own", not "is this number in facts.json". Anyone adding a slot phrase
# that computes a number is extending what the prompt may say, and should say
# so in the pull request.


SLOT_KEYS = ('moods', 'instruments', 'vocals', 'production', 'direction')


def _canonical(text):
    """One spelling for comparison. Not a prefix: a prefix match let a phrase
    be counted as inherited and then inverted, so 'roughly 12 seconds of build'
    and 'roughly 12 minutes of total silence' both scored as coming from the
    same measurement."""
    return ' '.join(str(text).lower().replace('.', ' ').split())


def _decompose(style):
    """The style as the Brain's own format defines it: a comma separated tag
    stack, then direction prose in sentences."""
    parts = [p for p in SENTENCE.split(style)]
    head = parts[0] if parts else ''
    tags = [t.strip() for t in head.split(',') if t.strip()]
    sentences = [s.strip() for s in parts[1:] if s.strip()]
    return tags, sentences


def validate(style, exclude, sheet, rules, mode='custom', names=(),
             filled=None, acknowledged=False, declared=(), dropped=()):
    # `dropped` is checked against a budget, not taken on trust. See the
    # allowance below.
    """Check a composed prompt against the Brain's own rules.

    `filled` is the slots dict the prompt was supposed to be written from. It
    is an argument rather than recomputed here so the caller checks the SAME
    slots it handed the agent, including any held out axis.
    """
    if filled is None:
        filled = slots(sheet)
    results = []
    style = style or ''
    exclude = exclude or ''
    body = style.lower()

    # Budget. `cap` is read here and reused by the provenance drop allowance
    # below, because a drop can only be justified against the cap that forced
    # it.
    budget = rules['budgets'].get(mode, {})
    cap, target = budget.get('cap'), budget.get('target')
    if cap is UNREADABLE or cap is None:
        results.append(_result('budget', 'UNKNOWN',
                               f'no budget for {mode} could be read from the Brain'))
    else:
        length = len(style)
        if length > cap:
            results.append(_result('budget', 'FAIL',
                                   f'{length} characters over the hard cap of {cap}'))
        elif target and target is not UNREADABLE and not target[0] <= length <= target[1]:
            results.append(_result(
                'budget', 'FAIL',
                f'{length} characters outside the target {target[0]} to {target[1]}'))
        else:
            results.append(_result('budget', 'PASS', f'{length} characters'))

    # Negation, in the style
    searchable = body.replace(INSTRUMENTAL_EXEMPTION, ' ')
    hits = _found_words(searchable, NEGATION_WORDS)
    results.append(_result('negation', 'FAIL' if hits else 'PASS',
                           ', '.join(hits)))

    # Negation, in the exclude field
    exclude_hits = _found_words(exclude, NEGATION_WORDS)
    results.append(_result('exclude_negation',
                           'FAIL' if exclude_hits else 'PASS',
                           ', '.join(exclude_hits)))

    # Hyphens
    stripped = HYPHEN_EXCEPTIONS.sub(' ', style)
    stray = re.findall(r'\b\w+-\w+\b', stripped)
    results.append(_result('hyphens', 'FAIL' if stray else 'PASS',
                           ', '.join(stray)))

    # Banned words and phrases
    for key, name in (('banned_words', 'banned_words'),
                      ('banned_phrases', 'banned_phrases')):
        rule = rules.get(key)
        if rule is UNREADABLE:
            results.append(_result(name, 'UNKNOWN',
                                   f'{name} could not be read from the Brain'))
            continue
        if key == 'banned_words':
            hits = _found_words(body, rule)
        else:
            hits = [p for p in rule if p in body]
        results.append(_result(name, 'FAIL' if hits else 'PASS', ', '.join(hits)))

    # Direction prose
    tail = style.split(',')[-1] if ',' in style else style
    sentences = [s for s in SENTENCE.split(style) if len(s.strip().split()) >= 5]
    results.append(_result(
        'direction_prose',
        'PASS' if len(sentences) >= PROSE_MIN_SENTENCES else 'FAIL',
        f'{len(sentences)} prose sentences of five words or more'))

    # BPM placement
    bpm_at = body.find('bpm')
    if bpm_at < 0:
        results.append(_result('bpm_placement', 'FAIL',
                               'no BPM anywhere in the style'))
    else:
        first_sentence = SENTENCE.split(style)[0]
        limit = len(first_sentence) * MOODS_FRACTION
        results.append(_result(
            'bpm_placement', 'PASS' if bpm_at <= limit else 'FAIL',
            f'BPM at character {bpm_at} of a {len(first_sentence)} character '
            f'tag stack'))

    # Every number traces to a slot phrase. Every number, including single
    # digits, which the earlier \d{2,4} pattern never looked at.
    traceable = slot_numbers(filled)
    quoted = {int(n) for n in re.findall(r'\d+', style)}
    orphans = sorted(n for n in quoted if n not in traceable)
    results.append(_result(
        'numbers_trace', 'FAIL' if orphans else 'PASS',
        f'orphans {orphans}' if orphans
        else f'{len(quoted)} numbers, all traced to a slot'))

    # Provenance, as a contract rather than a coincidence counter.
    #
    # The first version asked whether ANY slot phrase appeared in the style. A
    # style about a converted grain silo, sharing a single token with the
    # sheet, passed all thirteen checks including 'provenance 1 of 7 present'.
    # Worse, it was not independent: bpm_placement mandates the exact phrase
    # that satisfied it, so provenance certified what two other checks had
    # already required and added nothing.
    #
    # The rule now runs the other way. Every piece of the style must be
    # accounted for: it either matches a slot phrase, which means it came from
    # a measurement, or the agent declared it as its own judgement. Anything
    # else is undeclared content and the prompt fails.
    #
    # That makes the composer enumerate its judgement calls, which is the
    # point. A genre, a subgenre and an era are judgement and belong in
    # `declared`. A register, a tuning and a BPM are measurements and belong in
    # the slots. A prompt is then exactly slots plus declared additions, and
    # "written from the fact sheet alone" becomes a thing a reader can check.
    slot_phrases = {_canonical(p) for key in SLOT_KEYS
                    for p in filled.get(key, [])}
    spoken = {_canonical(d) for d in declared}
    tags, sentences = _decompose(style)
    pieces = [(t, _canonical(t)) for t in tags] + \
             [(s, _canonical(s)) for s in sentences]

    # Four buckets, and a piece lands in exactly one of them. The earlier
    # version had two and a membership test that ignored `spoken`, so a
    # DECLARED piece still counted as coming from a measurement. Declaring
    # every piece including the BPM then passed, because the BPM matched a slot
    # and the severance guard only fired when NOTHING matched. That is the
    # mirror of the defect it replaced: bpm_placement mandates a BPM that
    # traces to a slot, so `81 BPM` is in every passing prompt by construction,
    # and it was single handedly disabling the severance test.
    #
    # A declared piece is judgement BY THE AGENT'S OWN ACCOUNT. Taking that at
    # face value is the safe reading: an agent that disowns every measured
    # phrase has told you its prompt carries no measurements, and the check
    # should agree with it rather than overrule it.
    from_slots, contested, judgement, undeclared = [], [], [], []
    for raw, key in pieces:
        in_slots, was_declared = key in slot_phrases, key in spoken
        if in_slots and was_declared:
            contested.append(raw)
        elif in_slots:
            from_slots.append(raw)
        elif was_declared:
            judgement.append(raw)
        else:
            undeclared.append(raw)

    # The other direction. Accounting for every piece of the STYLE is only
    # half a contract: a prompt using one slot phrase and honestly declaring
    # four inventions satisfied it while leaving six measurements on the floor.
    # So every slot phrase must also be accounted for, by appearing in the
    # style or by being named in `dropped`.
    #
    # Dropping is legitimate and common: the Custom budget is 1000 characters
    # and the slots will not always fit. Naming what was dropped costs the
    # agent one flag and turns "the measurements did not reach the prompt" from
    # something a reader has to notice into something the check says.
    shed = {_canonical(d) for d in dropped}
    present = {key for _, key in pieces}
    unused = sorted(p for p in slot_phrases if p not in present and p not in shed)

    # A drop must be FORCED, and forced by the measurements alone.
    #
    # Without this, the obligation the dropped list creates is discharged by
    # restating it: paste every slot phrase into --dropped and an 859 character
    # prompt about a converted grain silo, carrying one number from the sheet
    # and fourteen declared inventions, passes all thirteen checks.
    #
    # The intuitive guard does not work and was tried first. "Would it have
    # fitted" reads as forced whenever the agent filled the budget with its own
    # prose before dropping anything: style 824 plus dropped 317 against a cap
    # of 1000 looks like an overflow and is nothing of the kind. Any rule that
    # measures the drop against the FINISHED style dies to the exact move that
    # creates the problem.
    #
    # So measurements have priority over declarations for the budget. The
    # allowance is what the slot phrases overflow the cap by, on their own,
    # before a single word of judgement is added. On this pipeline the slots
    # total about 325 characters against a Custom cap of 1000, so the allowance
    # is zero and no drop is ever justified. It becomes positive the day a
    # richer sheet genuinely does not fit, which is the case the flag exists
    # for.
    # A drop must be MINIMAL: putting any one dropped phrase back would still
    # overflow the cap.
    #
    # This replaces an allowance expressed in characters, which needed a model
    # of how phrases are joined and could never be spent exactly because drops
    # are whole phrases. Both problems go away when the question is asked one
    # phrase at a time: the separator only has to be right at a single phrase
    # margin, and there is no remainder to leave on the table.
    #
    # It keeps the property that made the allowance work, which is that the
    # measurement is taken from `filled` and never from the finished style. A
    # rule that measured the drop against what the agent actually wrote reads
    # as forced whenever the agent filled the budget with its own prose first,
    # and that is the exact move this is defending against.
    phrases = [p for key in SLOT_KEYS for p in filled.get(key, [])]

    def _rendered(items):
        # Tags join with ', ' and sentences with ' ', since a sentence already
        # carries its stop. Two is the wider of the two and this only has to be
        # right at a one phrase margin.
        return sum(len(i) for i in items) + max(0, len(items) - 1) * 2

    kept = [p for p in phrases if _canonical(p) not in shed]
    dropped_phrases = [p for p in phrases if _canonical(p) in shed]
    dropped_chars = sum(len(p) for p in dropped_phrases)
    if cap is UNREADABLE or cap is None:
        restorable = None
    else:
        restorable = [p for p in dropped_phrases
                      if _rendered(kept + [p]) <= int(cap)]

    measured_chars = sum(len(raw) for raw in from_slots)
    declared_chars = sum(len(raw) for raw in judgement)
    note = (f'{len(from_slots)} from measurements, {len(judgement)} declared '
            f'as judgement, {len(contested)} declared but matching a measured '
            f'slot, {len(undeclared)} unaccounted, {len(unused)} slot phrases '
            f'silently unused; {measured_chars} characters measured against '
            f'{declared_chars} declared')
    if undeclared:
        results.append(_result(
            'provenance', 'FAIL',
            f'{note}. Traces to neither a measurement nor a declared '
            f'judgement: {undeclared}'))
    elif not from_slots:
        results.append(_result(
            'provenance', 'FAIL',
            f'{note}. Not one piece came from a measurement the agent did not '
            f'also claim as its own, so nothing connects this prompt to the '
            f'fact sheet'
            + (f'. Declared but measured: {contested}' if contested else '')))
    elif unused:
        results.append(_result(
            'provenance', 'FAIL',
            f'{note}. Measured and left out without being dropped: {unused}'))
    elif dropped_phrases and restorable is None:
        results.append(_result(
            'provenance', 'FAIL',
            f'{note}. {dropped_chars} characters of measurement were dropped '
            f'and the budget could not be read, so nothing can justify them'))
    elif restorable:
        results.append(_result(
            'provenance', 'FAIL',
            f'{note}. The drop is not minimal: {restorable} would fit inside '
            f'the {cap} character cap alongside everything kept, so it was not '
            f'forced. Measurements have priority over judgement for this '
            f'budget'))
    else:
        results.append(_result('provenance', 'PASS', note))

    # An INFER tempo that nobody acknowledged must not reach a generation.
    pending = filled.get('ask_first') or []
    if pending and not acknowledged:
        results.append(_result(
            'ask_first', 'FAIL',
            '; '.join(pending) + '. Rerun with --acknowledge once the user has '
            'answered, or this prompt anchors the generation to a reading the '
            'sheet itself flagged as a minority.'))
    elif pending:
        results.append(_result('ask_first', 'PASS',
                               f'{len(pending)} acknowledged'))
    else:
        results.append(_result('ask_first', 'PASS', 'nothing to ask'))

    # No names
    both = f'{body} {exclude.lower()}'
    named = [n for n in names if n and n.lower() in both]
    results.append(_result('names', 'FAIL' if named else 'PASS',
                           ', '.join(named)))

    # Exclude budget
    rule = rules.get('exclude_budget')
    if rule is UNREADABLE:
        results.append(_result('exclude_budget', 'UNKNOWN',
                               'no exclude budget could be read from the Brain'))
    else:
        length = len(exclude)
        results.append(_result(
            'exclude_budget',
            'PASS' if rule[0] <= length <= rule[1] else 'FAIL',
            f'{length} characters against a target of {rule[0]} to {rule[1]}'))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: PASS, 50 tests

If `test_a_clean_style_passes_every_check_it_can_run` fails, read which check
failed and fix the validator, not the fixture, unless the fixture genuinely
breaks a Brain rule. `GOOD_EXCLUDE` is deliberately near the 180 to 200 band; if
it lands outside, adjust its wording to sit inside rather than widening the gate.

- [ ] **Step 5: Commit**

```bash
git add scripts/brain.py tests/test_brain.py
git commit -m "feat: validate a prompt against the Brain's own final check"
```

---

### Task 3: Slot filling from facts

**Files:**
- Modify: `scripts/brain.py`
- Modify: `tests/test_brain.py`

**Interfaces:**
- Consumes: a fact sheet.
- Produces: `slots(sheet) -> dict` with keys `moods` (list of str), `instruments` (list of str), `vocals` (list of str), `production` (list of str), `direction` (list of str), `midi_only` (list of str), `unusable` (list of str).

The composer does not choose a genre. That is judgment and stays with the agent.
What `slots` does is turn measurements into the phrases a prompt can use, and
refuse to turn an `UNKNOWN` into one.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_brain.py` before `if __name__`:

```python
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
        joined = ' '.join(self.slots['production'] + self.slots['direction']).lower()
        self.assertIn('static', joined)
        self.assertNotIn('f#', joined)

    def test_the_intro_length_reaches_the_direction_prose(self):
        joined = ' '.join(self.slots['direction']).lower()
        self.assertIn('12', joined)

    def test_a_chord_fact_is_midi_only_and_never_reaches_a_text_slot(self):
        text = ' '.join(self.slots['moods'] + self.slots['instruments']
                        + self.slots['vocals'] + self.slots['production']
                        + self.slots['direction'])
        self.assertNotIn('F#', text)
        self.assertTrue(self.slots['midi_only'])

    def test_an_unknown_axis_produces_no_tag_and_is_listed_as_unusable(self):
        self.assertIn('vocal_register', self.slots['unusable'])
        self.assertEqual(self.slots['vocals'], [])

    def test_a_low_end_share_becomes_a_production_cue_not_a_percentage(self):
        joined = ' '.join(self.slots['production']).lower()
        self.assertNotIn('16.4', joined)
        self.assertTrue(joined)

    def test_no_slot_phrase_contains_a_negation_word(self):
        every = sum((self.slots[k] for k in
                     ('moods', 'instruments', 'vocals', 'production', 'direction')),
                    [])
        for phrase in every:
            for word in b.NEGATION_WORDS:
                self.assertIsNone(re.search(rf'\b{word}\b', phrase.lower()),
                                  f'{phrase!r} contains {word!r}')

    def test_no_slot_phrase_contains_a_hyphen(self):
        every = sum((self.slots[k] for k in
                     ('moods', 'instruments', 'vocals', 'production', 'direction')),
                    [])
        for phrase in every:
            self.assertNotIn('-', phrase, phrase)
```

Add `import re` to the top of `tests/test_brain.py` if it is not already there.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: FAIL, `AttributeError: module 'brain' has no attribute 'slots'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/brain.py`:

```python
# MIDI note number bands, named the way a prompt names them. A prompt that
# says 42 says nothing; a prompt that says low register says the thing the
# number meant. This mapping is the whole reason lead_register is a fact:
# four generation cycles were spent discovering by ear that an intro had
# arrived an octave high.
REGISTER_BANDS = ((48, 'very low register'), (55, 'low register'),
                  (67, 'mid register'), (79, 'high register'))
LOW_END_BANDS = ((8.0, 'light low end'), (14.0, 'balanced low end'),
                 (22.0, 'heavy low end'), (100.0, 'dominant low end'))


def _band(value, bands, fallback):
    for limit, label in bands:
        if value < limit:
            return label
    return fallback


def _usable(sheet, axis):
    entry = (sheet or {}).get('facts', {}).get(axis)
    if not entry or entry.get('confidence') == 'UNKNOWN':
        return None
    if entry.get('value') is None:
        return None
    return entry


# The default control axis for the exit bar.
#
# A module level constant that nothing references is not a default, it is a
# comment, and this one was exactly that for two revisions while both the plan
# and the pre spend checklist said the default was lead_register.
#
# `deconstruct.py` cannot import this module at the top to read it, because of
# the lazy import rule at deconstruct.py:22, so its parser repeats the literal
# and a test asserts the two agree. A repeated literal with a test on it is
# honest duplication; a constant nothing reads is not.
HOLD_OUT_DEFAULT = 'lead_register'
HOLD_OUT_CHOICES = ('tempo', 'tuning', 'intro_seconds', 'lead_register',
                    'spectral_balance')


def slots(sheet, hold_out=None):
    """Measurements to prompt phrases. An UNKNOWN never becomes a phrase.

    `hold_out` names one measured axis to deliberately keep OUT of the prompt.
    It is the control for the exit bar.

    Without it, a generation matching the reference is consistent with the fact
    sheet doing the work and equally consistent with an agent writing a good
    prompt from prose, and the bar cannot tell those apart. With it, the axes
    that reached the prompt and the one that did not are scored separately. If
    the carried axes match and the held out one does not, the sheet is what
    carried the result. If everything matches equally well, something other
    than the prompt is driving it and the bar has told you so.

    `lead_register` is the default because the parent spec records four
    generation cycles lost to an intro arriving an octave high, which makes it
    the axis most likely to drift when nothing anchors it.
    """
    out = {'moods': [], 'instruments': [], 'vocals': [], 'production': [],
           'direction': [], 'midi_only': [], 'unusable': [], 'ask_first': [],
           'held_out': hold_out}
    for axis, entry in (sheet or {}).get('facts', {}).items():
        if entry.get('confidence') == 'UNKNOWN' or entry.get('value') is None:
            out['unusable'].append(axis)

    tempo = None if hold_out == 'tempo' else _usable(sheet, 'tempo')
    if tempo:
        out['moods'].append(f'{round(float(tempo["value"]))} BPM')
        # See THE TEMPO RULE below. _usable already drops an UNKNOWN tempo, so
        # nothing reaches here without a value, but an INFER tempo whose family
        # holds a competing metrical level is a minority reading and the agent
        # must not silently turn it into a tag.
        if tempo['confidence'] != 'KNOW':
            out['ask_first'].append(
                f'tempo is graded {tempo["confidence"]}: {tempo.get("note")}')

    tuning = None if hold_out == 'tuning' else _usable(sheet, 'tuning')
    if tuning:
        out['instruments'].append(
            f'{str(tuning["value"]).replace("#", " sharp")} tuned rhythm guitar'
            .replace('-', ' '))

    lead = None if hold_out == 'lead_register' else _usable(sheet, 'lead_register')
    if lead:
        label = _band(float(lead['value']['median_midi']), REGISTER_BANDS,
                      'very high register')
        out['instruments'].append(f'{label} lead guitar figure')

    vocal = _usable(sheet, 'vocal_register')
    if vocal:
        label = _band(float(vocal['value']['median_midi']), REGISTER_BANDS,
                      'very high register')
        out['vocals'].append(f'{label} lead vocal')

    spectral = (None if hold_out == 'spectral_balance'
                else _usable(sheet, 'spectral_balance'))
    if spectral:
        out['production'].append(
            _band(float(spectral['value']['low_end_share']), LOW_END_BANDS,
                  'dominant low end'))

    harmonic = _usable(sheet, 'harmonic_rhythm')
    if harmonic:
        out['production'].append(f'{harmonic["value"]["label"]} harmony')

    intro = None if hold_out == 'intro_seconds' else _usable(sheet, 'intro_seconds')
    # section_count, not sections. The fact sheet split that axis: boundaries
    # are INFER and the count is UNKNOWN by construction, because sixteen
    # segmentation methods failed to generalise. Reading the old name returns
    # None silently, which cost the direction prose its second sentence while
    # the Brain requires two to three. The agent was then quietly expected to
    # invent one, which is the exact failure this whole pipeline exists to stop.
    sections = _usable(sheet, 'section_count')
    boundaries = _usable(sheet, 'section_boundaries')
    if intro:
        out['direction'].append(
            f'The song opens on roughly {round(float(intro["value"]))} seconds '
            f'of build before the full arrangement lands.')
    if sections:
        out['direction'].append(
            f'It moves through about {int(sections["value"])} distinct '
            f'sections and ends without a fade.')
    elif boundaries and len(boundaries['value']) >= 2:
        # The count is UNKNOWN, but the boundaries are real and the Brain needs
        # a second direction sentence. This says what was measured, the shape,
        # without stating a count nothing earned.
        spans = [b - a for a, b in zip(boundaries['value'],
                                       boundaries['value'][1:])]
        longest = max(spans) if spans else 0
        out['direction'].append(
            f'It changes texture several times, with its longest unbroken '
            f'stretch running about {round(longest)} seconds, and ends without '
            f'a fade.')
    if len(out['direction']) < 2:
        out['unusable'].append('direction_prose_second_sentence')

    chords = _usable(sheet, 'chords')
    if chords:
        out['midi_only'].append('chord progression, supplied as MIDI')
    key = _usable(sheet, 'key')
    if key:
        out['midi_only'].append(f'key, {key["value"]}, supplied as MIDI')
    return out
```

## THE TEMPO RULE

`facts.scorable()` projects the tempo family's `primary`, and `tempo.grade()`
takes that primary from the tempogram unconditionally. The other two methods
can lower the confidence grade and can never change the value.

On the reference track all three methods agree and this is invisible. On Wrong
Turn the tempogram says 80.7 while beat tracking and inter onset intervals both
say 107.7, so the primary is a minority vote. The sheet reports it correctly:
grade `INFER`, 107.7 in the family labelled `4/3`, disagreement in the note.

`INFER` is a grade on the sheet. It is not a warning that survives the
projection, and a prompt is written from the projection.

So, before a BPM reaches the moods cluster:

1. `KNOW`: use the primary.
2. `INFER`: `slots` puts the grade and the note into `ask_first`. The agent
   surfaces it and asks which metrical level to use. It does not choose.
3. `UNKNOWN`: `_usable` drops it and no BPM is emitted at all. A tag stack
   without a BPM is a smaller failure than one that anchors the generation to
   the wrong metrical level.

**Do not fix this by filtering in `scorable()`.** That was considered and
rejected on measurement. The reference track's own tempo fact carries four
competing levels, one at relative strength 0.90, so any threshold low enough to
catch Wrong Turn also drops `tempo_bpm` on Murder She Wrote and fails the entry
bar. The projection is not the place. This is.

**One warning that belongs here rather than in the fact sheet.** The tuning
axis reports the lowest sustained semitone in the bass, and a sub octave pitch
tracking error can land inside the tuning table, be named with a margin of a
fraction of a cent, and look certain. The fact sheet does not prevent that. It
discloses it, by carrying every supported candidate and the best supported one
in the fact's note.

That disclosure reaches a human reading `facts.md` and nothing else. So `slots`
may turn `tuning` into an instrument tag, and the agent composing the prompt
must read the tuning note before it does. If this wiring is ever made
autonomous, with no human between the fact sheet and the generated prompt, the
tuning axis needs prevention rather than visibility and this plan needs
revisiting.

Note what `slots` does not do. It never emits a chord name or a key name into a
text slot, because those are `midi_only` and community evidence is consistent
that chord notation in a text prompt is discarded. It never emits a raw MIDI note
number or a raw percentage, because a prompt that says 42 says nothing. And it
never emits a phrase for an `UNKNOWN` axis, which is why `unusable` exists: the
agent can see what the sheet could not supply rather than wondering why a tag is
missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_brain -v`
Expected: PASS, 61 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/brain.py tests/test_brain.py
git commit -m "feat: turn measurements into prompt phrases, and UNKNOWN into nothing"
```

---

### Task 4: The prompt command

**Files:**
- Modify: `scripts/deconstruct.py`

**Interfaces:**
- Consumes: `brain.brain_sources`, `brain.extract_rules`, `brain.slots`, `brain.validate`, and the existing `config_dir`.
- Produces: CLI `prompt <facts.json> [--mode custom] [--style FILE] [--exclude FILE] [--name NAME]`, printing `SLOTS_WRITTEN=`, then one line per check, then `PROMPT_VERDICT=PASS|FAIL|UNKNOWN`.

The command has two jobs and does not confuse them. Without `--style` it prints
the slots for the agent to compose from. With `--style` it validates what the
agent wrote. Composition is judgment and stays with the agent; the script fills
and checks.

- [ ] **Step 1: Add a narrow config reader**

`references/brain.md` requires reading `brain_path` through a narrow helper and
never opening `credentials.json`. If `scripts/deconstruct.py` does not already
have one, add it beside the other config helpers:

```python
def brain_path():
    """Only brain_path, only from config.json. Never credentials.json."""
    target = config_dir() / 'config.json'
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding='utf-8')).get('brain_path')
    except (ValueError, OSError):
        return None
```

If one already exists, use it and skip this step.

- [ ] **Step 2: Add the command function**

Above `def main():`:

```python
def cmd_prompt(args):
    import brain as brain_mod
    sheet = json.loads(args.facts.read_text(encoding='utf-8'))
    path = brain_path()
    if not path:
        raise SkillError(
            'No Brain is connected. Run connect-brain, or compose without one '
            'and skip this command; it will not invent a format.')
    try:
        sources = brain_mod.brain_sources(path)
    except brain_mod.BrainError as exc:
        raise SkillError(str(exc)) from None
    text = sources.get('SYSTEM-PROMPT-FULL.txt') or sources['INSTRUCTIONS.txt']
    rules = brain_mod.extract_rules(text)
    # Resolved BEFORE slots.json is written, which is the order that stops an
    # axis being held out after someone has seen which one turned out
    # inconvenient.
    hold_out = None if args.hold_out == 'none' else args.hold_out
    filled = brain_mod.slots(sheet, hold_out=hold_out)

    out = args.out or args.facts.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / 'slots.json').write_text(
        json.dumps(filled, indent=2, allow_nan=False), encoding='utf-8')
    print(f'SLOTS_WRITTEN={out / "slots.json"}')
    # Printed unconditionally. Guarding it meant a run with no control emitted
    # no line at all, and the absence of the control was indistinguishable from
    # the line having scrolled past. The control is the single thing that turns
    # a matching generation into evidence rather than a coincidence, so its
    # absence has to be as loud as its presence.
    print(f'HELD_OUT={filled.get("held_out") or "none"}')
    for rule in rules['unreadable']:
        print(f'RULE_UNREADABLE={rule}', file=sys.stderr)
    if filled['unusable']:
        print(f'UNUSABLE_AXES={",".join(sorted(filled["unusable"]))}')
    for pending in filled.get('ask_first', []):
        print(f'ASK_FIRST={pending}')

    if not args.style:
        print('PROMPT_VERDICT=UNKNOWN')
        print('No style supplied, so nothing was checked. Compose from '
              'slots.json and rerun with --style to validate.', file=sys.stderr)
        return

    style = args.style.read_text(encoding='utf-8').strip()
    exclude = args.exclude.read_text(encoding='utf-8').strip() if args.exclude else ''
    results = brain_mod.validate(style, exclude, sheet, rules,
                                 mode=args.mode, names=tuple(args.name),
                                 filled=filled, acknowledged=args.acknowledge,
                                 declared=tuple(args.added),
                                 dropped=tuple(args.dropped))
    for entry in results:
        print(f'{entry["verdict"]:<8}{entry["check"]:<18}{entry["detail"]}')
    verdicts = [e['verdict'] for e in results]
    overall = 'FAIL' if 'FAIL' in verdicts else (
        'UNKNOWN' if 'UNKNOWN' in verdicts else 'PASS')
    (out / 'prompt-check.json').write_text(
        json.dumps({'mode': args.mode, 'verdict': overall, 'checks': results},
                   indent=2), encoding='utf-8')
    print(f'PROMPT_VERDICT={overall}')
    if overall == 'FAIL':
        # A FAIL is a verdict, not a crash, so it exits non-zero without the
        # error handler's suppression text. Wrapping scripts gate on this.
        return 2
```

- [ ] **Step 3: Extract the parser so it can be tested**

`main()` currently builds its parser inline. Split the construction out so a
test can parse real arguments through it without running a command:

```python
def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    ...                       # every existing sub.add_parser block, unchanged
    return p


def main():
    args = build_parser().parse_args()
    ...                       # the existing dispatch, unchanged
```

Move only the construction. Change no argument, no default and no dispatch
branch, and confirm the suite is unchanged before you add anything to it. This
is a refactor in service of a test, and a refactor that alters behaviour on the
way is worse than the test it enables.

- [ ] **Step 4: Register and dispatch**

With the other parsers in `build_parser()`:

```python
    pp = sub.add_parser('prompt')
    pp.add_argument('facts', type=Path)
    pp.add_argument('--mode', choices=('simple', 'custom', 'studio'),
                    default='custom')
    pp.add_argument('--style', type=Path, default=None,
                    help='A composed style prompt to validate.')
    pp.add_argument('--exclude', type=Path, default=None)
    pp.add_argument('--name', action='append', default=[],
                    help='A name that must not appear. Repeatable.')
    # These repeat brain.HOLD_OUT_DEFAULT and brain.HOLD_OUT_CHOICES rather
    # than importing them, because deconstruct.py must survive an incomplete
    # install for doctor's sake; see the comment at line 22. The duplication is
    # held honest by test_the_parser_agrees_with_the_module, which parses real
    # arguments through build_parser() instead of inspecting bytecode.
    pp.add_argument('--hold-out', default='lead_register',
                    choices=('tempo', 'tuning', 'intro_seconds',
                             'lead_register', 'spectral_balance', 'none'),
                    help='Keep one measured axis OUT of the prompt and score '
                         'it anyway. The control for the exit bar. Defaults to '
                         'lead_register; pass none to run without a control, '
                         'which is a weaker result at the same price.')
    pp.add_argument('--acknowledge', action='store_true',
                    help='The user has answered every ASK_FIRST question.')
    pp.add_argument('--added', action='append', default=[],
                    help='A tag or sentence in the style that is the agent\'s '
                         'own judgement rather than a measurement, for example '
                         'a genre or an era. Repeatable. Anything in the style '
                         'that is neither a slot phrase nor declared here '
                         'fails provenance.')
    pp.add_argument('--dropped', action='append', default=[],
                    help='A slot phrase deliberately left out of the style, '
                         'usually to fit the character budget. Repeatable. A '
                         'measured phrase that is neither used nor dropped '
                         'fails provenance, because a measurement that quietly '
                         'never reached the prompt is the thing this check '
                         'exists to surface.')
    pp.add_argument('--out', type=Path, default=None)
```

With the other branches:

```python
    elif args.command == 'prompt':
        cmd_prompt(args)
```

- [ ] **Step 4: Prove it against the real Brain**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
PY=.venv/bin/python
DESK=/Users/drewtuzson/Documents/Projects/deconstruct-audio-desk-2026-09-17
$PY scripts/deconstruct.py prompt $DESK/evidence/facts-murder-she-wrote.json \
  --mode custom --out $DESK/evidence
cat $DESK/evidence/slots.json
```

Expected: `SLOTS_WRITTEN=`, no `RULE_UNREADABLE` lines, and
`PROMPT_VERDICT=UNKNOWN` because no style was supplied. If
`facts-murder-she-wrote.json` does not exist yet, it comes from the fact sheet
plan's Task 8. Use `tests/fixtures/facts-sample.json` instead and say so in the
pull request.

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: the prompt command"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `references/brain.md`

- [ ] **Step 1: Add `prompt` to the command table in `README.md`**

```markdown
| `prompt <facts.json>` | Fills your connected Brain's slots from the fact sheet alone and, when given a composed style, checks it against the Brain's own rules: budget, negation, hyphens, banned words, direction prose, BPM placement, and whether every number traces to a measurement |
```

- [ ] **Step 2: Add a section to `README.md`**

```markdown
## Writing the prompt from the facts

`prompt` reads `facts.json` and nothing else. Not the listening assessment, not
the impressions, not the report. If a prompt built only from measurements works,
the measurement path is what produced the result, which is the claim this whole
project makes.

The Brain's rules are read from your own Brain folder every run rather than
copied into this package, so updating your Brain updates the checks. A rule the
text does not yield is reported as `UNKNOWN`, never as a pass: a check that could
not find its rule is not a check that succeeded.

Composition stays with the agent. The command fills the slots and then checks
what was written, including whether every number in the prompt traces back to a
measured fact. A number that does not is the failure mode this tool was built
against, and it is a `FAIL`, not a warning.
```

- [ ] **Step 3: Note the split in `references/brain.md`**

Add a short paragraph stating that `prompt` composes from measured facts only,
that no Brain content is stored in this package, and that a `RULE_UNREADABLE`
line means the Brain's wording moved and the extraction needs widening.

- [ ] **Step 4: Add the rule to `SKILL.md`**

State that the agent composes the style from `slots.json` plus its own genre
judgment, never quotes a number the fact sheet did not measure, and reruns
`prompt --style` until the verdict is PASS before anything is generated.

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add README.md SKILL.md references/brain.md
git commit -m "docs: the prompt command"
```

---

---

## The exit bar

One generation, whose prompt the Brain wrote from the fact sheet alone, scoring
PASS on tempo, key and intro length with low end share and loudness range inside
their limits.

That was the bar as first stated, and it does not measure what it says. The
prompt is a free text file and nothing checked where its contents came from, so
a style written from `listening.md` prose passes every validator identically. A
PASS was equally consistent with the measurement path carrying the result and
with an agent writing a good prompt from prose. Two additions make the
difference observable.

**Provenance, as a contract that closes in both directions.** Every piece of
the style is accounted for: it matches a slot phrase, meaning it came from a
measurement, or the agent declared it through `--added` as its own judgement.
And every slot phrase is accounted for: it appears in the style, or the agent
named it in `--dropped`. Anything unaccounted on either side fails.

The style is then exactly what was measured plus what the agent admits it
added, and the measurements that did not reach the prompt are listed rather
than inferred from their absence. `numbers_trace` sits alongside it and is
genuinely independent: a declared judgement carrying a number passes provenance
and fails `numbers_trace`.

Three earlier versions of this check were theatre, which is worth recording
because each looked reasonable. The first asked whether ANY slot phrase
appeared, and a style about a converted grain silo sharing one tag passed; it
was also not independent, because `bpm_placement` mandates the phrase that
satisfied it. The second counted a DECLARED piece as coming from a measurement,
so declaring everything including the BPM passed. The third accounted for the
style but not for the slots, so one slot phrase plus four honest declarations
passed while six measurements sat unused.

**A held out axis.** `--hold-out` keeps one measured axis out of the prompt
while the scorer still measures it on both sides. The default is
`lead_register`, because the parent spec records four generation cycles lost to
an intro arriving an octave high, which makes it the axis most likely to drift
when nothing anchors it.

Read the result as a pair, not as one verdict:

| Carried axes | Held out axis | What it means |
|---|---|---|
| match | misses | The fact sheet carried the result. The outcome the project claims |
| match | also matches | Something other than the prompt is driving it: the genre's own prior landed an axis nothing anchored. The bar telling you the test is weak is worth more than a PASS |
| miss | misses | The prompt did not steer the generation. Nothing downstream is validated |
| miss | matches | The prompt steered the generation AWAY from the reference while the unanchored axis landed on its own. The worst result, and the only one that says a carried axis is actively harmful |
| any | UNKNOWN | Unreadable. `_register` returns UNKNOWN below sixteen voiced frames, which is exactly what a thin generated guitar produces, so the control can fail to report at all. Hold out a different axis and generate again, or accept that this run measured nothing about provenance |
| UNKNOWN | any | Also unreadable, and check this first. A carried axis coming back UNKNOWN on the generation means that axis was not compared at all, so read `MEASURED=` before reading the verdict. A thin generation can take several axes out at once |

The exit bar is met by the first row only.

The last row is not hypothetical and it is why the held out axis is a flag
rather than a constant: `lead_register` is the default because it is the axis
most likely to drift, and that is the same property that makes it most likely
to come back UNKNOWN on a sparse generation.

**What this still cannot do.** It cannot prove the agent never read
`listening.md`. It can only show that everything measurable in the style traces
to the slots. And the generator is not deterministic, so one generation is one
sample: a single PASS is evidence, not proof, and the report must say which.

### Before anything is spent

The generation costs the user money, so these come first, in this order.

1. Run `prompt` on the reference fact sheet with no style, and confirm zero
   `RULE_UNREADABLE` lines against the real Brain. A budget parsed wrong is a
   prompt the Brain rejects after the credits are gone.
2. Answer every `ASK_FIRST` line with the user, then rerun with
   `--acknowledge`. An `INFER` tempo carrying a competing metrical level at 0.90
   relative strength is the most expensive thing on this list to get wrong.
3. Compose the style from `slots.json`, then run `prompt --style` until
   `PROMPT_VERDICT=PASS`. Every individual check must read PASS. An `UNKNOWN`
   verdict means a rule could not be read, not that it passed.
4. Read the `provenance` detail line before anything else. It ends with the
   character split, `N characters measured against M declared`. Nothing
   enforces a ratio there and nothing should, because any threshold would be
   invented, but it is the number that tells you how much of the prompt was
   judgement. Read it aloud when you ask for the spend: disclosure instead of a
   threshold only works if the disclosure is spoken at the moment of the
   decision.

   What would earn a threshold later, so this reads as deferred rather than
   forgotten: once several generations exist, each carries a labelled outcome
   from the five row table above. Ask whether the ratio predicts the first row.
   Until then there is nothing to set a number from, which is the same reason
   every constant this project got wrong was wrong. Characters are also a poor
   proxy on their own: the two direction sentences are 198 of 311 slot
   characters, so a prompt carrying two of seven phrases can read as 64 percent
   measured. The line prints the count and the weight for that reason. A prompt carrying every measurement and six hundred characters of
   its own prose passes every check honestly and is still mostly the agent's
   taste. The held out axis is the control; this line is the context you read
   it in.
5. Only then ask the user to approve the spend, and say in the same breath
   which axis is held out, what each of the five outcomes above would mean, and
   that one generation is one sample so "inconclusive, generate again" is a
   real result.

## Self-Review

**Spec coverage.** "Reads the Brain from the configured path at runtime" is
Task 1 plus Task 4's narrow `brain_path` reader. "No Brain text in this
repository" is enforced by the synthetic fixture and stated in the global
constraints; the invented banned words `wibbly`, `frobnicate` and
`sparkletastic` exist so the extraction is tested without quoting anything real.
"Composes from facts.json alone" is Task 3's `slots`, whose only argument is the
sheet. The slot mapping table in the spec is Task 3's tests, one per row.
The seven mechanical checks are Task 2, one test each, plus
`test_an_unreadable_rule_reports_unknown_rather_than_pass` for the case that
would otherwise pass silently. "Choosing the subgenre remains judgment" is
Task 4's two-mode command.

**Placeholders.** None. Task 5 steps 3 and 4 point at existing files' own
conventions rather than reproducing them.

**Type consistency.** `brain_sources` returns `dict[str, str]`, consumed by
Task 4 which picks one value and passes it to `extract_rules`. `extract_rules`
returns the dict `validate` reads, and `UNREADABLE` is a single sentinel instance
compared with `is`, so a truthiness bug cannot make an unreadable rule look like
an empty tuple that passes. `slots` returns the dict the command serialises.
`validate` returns `list[dict]` with the three-key shape the command prints and
writes. `NEGATION_WORDS` is defined once in Task 2 and reused by Task 3's tests,
so the slot builder and the validator cannot drift apart on what a negation is.
