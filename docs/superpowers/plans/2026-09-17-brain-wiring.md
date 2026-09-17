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

    simple = re.search(
        rf'SIMPLE:.*?[Tt]arget\s+{NUMBER}\s+to\s+{NUMBER}\s+characters'
        rf'.*?cap\s+{NUMBER}', text, re.S)
    rules['budgets']['simple'] = (
        {'target': (_int(simple.group(1)), _int(simple.group(2))),
         'cap': _int(simple.group(3))} if simple
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    custom = re.search(
        rf'CUSTOM.*?limit\s+{NUMBER}\s+characters,\s+target\s+{NUMBER}\s+to\s+'
        rf'{NUMBER}', text, re.S)
    rules['budgets']['custom'] = (
        {'target': (_int(custom.group(2)), _int(custom.group(3))),
         'cap': _int(custom.group(1))} if custom
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    studio = re.search(rf'STUDIO:.*?[Ll]imit\s+{NUMBER}', text, re.S)
    rules['budgets']['studio'] = (
        {'target': None, 'cap': _int(studio.group(1))} if studio
        else {'target': UNREADABLE, 'cap': UNREADABLE})

    banned = re.search(r'[Ff]atigue words banned[^:]*:\s*([^\n.]+)', text)
    rules['banned_words'] = (
        tuple(w.strip().lower() for w in banned.group(1).split(',') if w.strip())
        if banned else UNREADABLE)

    phrases = re.findall(r'"([^"\n]{3,40})"', text)
    never = re.search(r'\bNever:\s*([^\n]+)', text)
    rules['banned_phrases'] = (
        tuple(p.strip().strip('"').lower()
              for p in re.findall(r'"([^"]+)"', never.group(1)))
        if never else UNREADABLE)

    exclude = re.search(rf'EXCLUDE:.*?[Tt]arget\s+{NUMBER}\s+to\s+{NUMBER}',
                        text, re.S)
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
Expected: PASS, 12 tests

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
NEGATION_WORDS = ('no', 'not', 'without')
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


def _fact_numbers(sheet):
    """Every number the sheet measured, as a set of rounded forms."""
    out = set()

    def add(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        out.add(round(float(value)))
        out.add(round(float(value) * 2))
        out.add(round(float(value) / 2))

    for entry in (sheet or {}).get('facts', {}).values():
        if entry.get('confidence') == 'UNKNOWN':
            continue
        value = entry.get('value')
        if isinstance(value, dict):
            for inner in value.values():
                add(inner)
        elif isinstance(value, list):
            for inner in value:
                add(inner)
        else:
            add(value)
    return out


def validate(style, exclude, sheet, rules, mode='custom', names=()):
    results = []
    style = style or ''
    exclude = exclude or ''
    body = style.lower()

    # Budget
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

    # Every number traces to a fact
    measured = _fact_numbers(sheet)
    quoted = {int(n) for n in re.findall(r'\b(\d{2,4})\b', style)}
    orphans = sorted(n for n in quoted if n not in measured)
    results.append(_result('numbers_trace', 'FAIL' if orphans else 'PASS',
                           ', '.join(str(n) for n in orphans)))

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
Expected: PASS, 29 tests

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


def slots(sheet):
    """Measurements to prompt phrases. An UNKNOWN never becomes a phrase."""
    out = {'moods': [], 'instruments': [], 'vocals': [], 'production': [],
           'direction': [], 'midi_only': [], 'unusable': []}
    for axis, entry in (sheet or {}).get('facts', {}).items():
        if entry.get('confidence') == 'UNKNOWN' or entry.get('value') is None:
            out['unusable'].append(axis)

    tempo = _usable(sheet, 'tempo')
    if tempo:
        out['moods'].append(f'{round(float(tempo["value"]))} BPM')

    tuning = _usable(sheet, 'tuning')
    if tuning:
        out['instruments'].append(
            f'{str(tuning["value"]).replace("#", " sharp")} tuned rhythm guitar'
            .replace('-', ' '))

    lead = _usable(sheet, 'lead_register')
    if lead:
        label = _band(float(lead['value']['median_midi']), REGISTER_BANDS,
                      'very high register')
        out['instruments'].append(f'{label} lead guitar figure')

    vocal = _usable(sheet, 'vocal_register')
    if vocal:
        label = _band(float(vocal['value']['median_midi']), REGISTER_BANDS,
                      'very high register')
        out['vocals'].append(f'{label} lead vocal')

    spectral = _usable(sheet, 'spectral_balance')
    if spectral:
        out['production'].append(
            _band(float(spectral['value']['low_end_share']), LOW_END_BANDS,
                  'dominant low end'))

    harmonic = _usable(sheet, 'harmonic_rhythm')
    if harmonic:
        out['production'].append(f'{harmonic["value"]["label"]} harmony')

    intro = _usable(sheet, 'intro_seconds')
    sections = _usable(sheet, 'sections')
    if intro:
        out['direction'].append(
            f'The song opens on roughly {round(float(intro["value"]))} seconds '
            f'of build before the full arrangement lands.')
    if sections:
        out['direction'].append(
            f'It moves through about {int(sections["value"]["count"])} distinct '
            f'sections and ends without a fade.')

    chords = _usable(sheet, 'chords')
    if chords:
        out['midi_only'].append('chord progression, supplied as MIDI')
    key = _usable(sheet, 'key')
    if key:
        out['midi_only'].append(f'key, {key["value"]}, supplied as MIDI')
    return out
```

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
Expected: PASS, 39 tests

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
    filled = brain_mod.slots(sheet)

    out = args.out or args.facts.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / 'slots.json').write_text(
        json.dumps(filled, indent=2, allow_nan=False), encoding='utf-8')
    print(f'SLOTS_WRITTEN={out / "slots.json"}')
    for rule in rules['unreadable']:
        print(f'RULE_UNREADABLE={rule}', file=sys.stderr)
    if filled['unusable']:
        print(f'UNUSABLE_AXES={",".join(sorted(filled["unusable"]))}')

    if not args.style:
        print('PROMPT_VERDICT=UNKNOWN')
        print('No style supplied, so nothing was checked. Compose from '
              'slots.json and rerun with --style to validate.', file=sys.stderr)
        return

    style = args.style.read_text(encoding='utf-8').strip()
    exclude = args.exclude.read_text(encoding='utf-8').strip() if args.exclude else ''
    results = brain_mod.validate(style, exclude, sheet, rules,
                                 mode=args.mode, names=tuple(args.name))
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

- [ ] **Step 3: Register and dispatch**

With the other parsers in `main()`:

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
