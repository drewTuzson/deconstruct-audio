# Research Branch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user supplies an artist or song name, record scene and era research beside the fact sheet in a way that can never contaminate it, and make every collision between a researched claim and a measured fact visible with the measurement winning.

**Architecture:** One service module, `research.py`, holding the record shape and the collision detector. One thin command. The module makes no network call: the agent does the searching and the script owns the structure, which keeps `research` an offline command and keeps the project's standing split intact.

**Tech Stack:** Python 3.10+, standard library only.

**Spec:** `docs/superpowers/specs/2026-09-17-fact-sheet-emitter-design.md`

## Global Constraints

- Python 3.10 or newer.
- **Import `research` inside `cmd_research`, never at module level.** See the comment at `scripts/deconstruct.py:22`. `research.py` is standard library only today, so this costs nothing, but the rule is about the file it is being added to, not about this module's weight.
- **Wrap `ResearchError` in `SkillError`.** The top-level handler at `scripts/deconstruct.py:730` prints authored text only for `SkillError`; anything else becomes `ERROR: <TypeName> ... Details suppressed to protect secrets`. Without the wrap, the message "an unsourced claim is a memory" never reaches the user, which defeats the point of writing it.
- Run tests with the main checkout's interpreter: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`.
- Baseline is 97 tests, OK, one skipped. Any drop is a regression.
- `research.py` imports nothing outside the standard library and makes no network call.
- Nothing in this branch writes into `facts.json`. Ever.
- Measured facts outrank researched claims on every collision.
- No em dashes or en dashes in any file this plan creates, including code comments and commit messages.

## Why this shape

The temptation with a research branch is to let it fill gaps in the fact sheet.
That is precisely the failure the fact sheet replaced: a confident sentence
standing in for a measurement. So the branch is built so that filling a gap is
not expressible. Research claims live in their own file, carry their own source,
and the only place the two meet is a collision table that reports both and marks
the measured one authoritative.

A researched claim with no measured counterpart is still recorded. It is context,
labelled as context, and the prompt writer may use it for things no measurement
covers, such as the scene a sound belongs to. It never becomes a number.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/research.py` (create) | The claim shape, the record, the collision table, markdown rendering. |
| `scripts/deconstruct.py` (modify) | The `research` command. |
| `tests/test_research.py` (create) | Claim validation, collisions, the no-contamination guarantee. |

---

### Task 1: The claim and the record

**Files:**
- Create: `scripts/research.py`
- Create: `tests/test_research.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `claim(axis, value, source, confidence, note=None) -> dict`, `record(artist, title, claims) -> dict`, `ResearchError`, `SCHEMA = 'deconstruct-audio/research/1'`, `CONFIDENCE = ('KNOW', 'INFER', 'GUESS')`.

The grades differ from the fact sheet's on purpose. A fact sheet grades how well
a measurement resolved. A research claim grades how well a source supports a
statement, and `GUESS` is a grade a measurement is never allowed to carry but a
research note legitimately can.

- [ ] **Step 1: Write the failing test**

Create `tests/test_research.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_research -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'research'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/research.py`:

```python
#!/usr/bin/env python3
"""The optional research branch.

Runs only when a name is supplied, writes its own file, and never writes into
the fact sheet. The obvious thing to build here would let research fill a gap
the measurement could not resolve, which is exactly the defect the fact sheet
replaced: a confident sentence standing in for a number. So filling a gap is
not expressible in this module. The two sources meet in one place, the
collision table, and the measurement wins there by construction.
"""
import copy
import datetime as _dt
import math

SCHEMA = 'deconstruct-audio/research/1'
CONFIDENCE = ('KNOW', 'INFER', 'GUESS')


class ResearchError(Exception):
    pass


def claim(axis, value, source, confidence, note=None):
    if not isinstance(axis, str) or not axis.strip():
        raise ResearchError('a claim must name the axis it speaks to')
    if not isinstance(source, str) or not source.strip():
        raise ResearchError(
            f'the claim about {axis!r} carries no source. An unsourced claim is '
            f'a memory, and this file exists to keep memories out of the facts')
    if confidence not in CONFIDENCE:
        raise ResearchError(f'confidence must be one of {CONFIDENCE}, '
                            f'got {confidence!r}')
    return {'axis': axis.strip(), 'value': value, 'source': source.strip(),
            'confidence': confidence, 'note': note}


def record(artist, title, claims):
    artist = (artist or '').strip()
    title = (title or '').strip()
    if not artist and not title:
        raise ResearchError(
            'the research branch runs only when a name is supplied')
    for entry in claims:
        for key in ('axis', 'value', 'source', 'confidence'):
            if key not in entry:
                raise ResearchError(f'a claim is missing {key}')
        # The same line claim() holds. record() accepting a blank source while
        # claim() refuses one is a second door into the same room, and the fact
        # that today's only caller happens to go through claim() is not a
        # property of this function.
        if not str(entry.get('source') or '').strip():
            raise ResearchError(
                f'the claim about {entry["axis"]!r} carries no source')
        if entry.get('confidence') not in CONFIDENCE:
            raise ResearchError(
                f'the claim about {entry["axis"]!r} is graded '
                f'{entry.get("confidence")!r}, which is not one of {CONFIDENCE}')
    return {
        'schema': SCHEMA,
        'generated_at': _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
                           .isoformat().replace('+00:00', 'Z'),
        'query': {'artist': artist, 'title': title},
        'claims': list(claims),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_research -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/research.py tests/test_research.py
git commit -m "feat: a research claim that cannot exist without a source"
```

---

### Task 2: The collision table

**Files:**
- Modify: `scripts/research.py`
- Modify: `tests/test_research.py`

**Interfaces:**
- Consumes: `record` from Task 1, and a fact sheet of the shape
  `{'facts': {axis: {'value': ..., 'confidence': ...}}}`.
- Produces: `collisions(sheet, rec) -> list[dict]` where each entry is
  `{'axis', 'measured', 'measured_confidence', 'researched', 'researched_confidence', 'source', 'agrees', 'authoritative'}`, and `authoritative` is always the string `'measured'`.

`authoritative` being a constant rather than a computed field is deliberate.
There is no input to this function that makes research win, and a reader can
confirm that at a glance rather than by tracing a branch.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research.py` before `if __name__`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_research -v`
Expected: FAIL, `AttributeError: module 'research' has no attribute 'collisions'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/research.py`:

```python
NUMERIC_TOLERANCE = 0.02   # 2 percent, the same band tempo drift is judged on


def _agrees(measured, researched):
    """Whether a claim and a measurement say the same thing.

    Wrapped in its own guard because the inputs are hand written JSON. A big
    enough integer literal raises OverflowError on the subtraction, which the
    CLI's top level handler turns into 'Details suppressed to protect secrets'
    for what is a typo in a claims file.
    """
    if measured is None:
        return False
    if isinstance(measured, bool) or isinstance(researched, bool):
        return measured == researched
    if isinstance(measured, (int, float)) and isinstance(researched, (int, float)):
        try:
            a, b = float(measured), float(researched)
        except (OverflowError, ValueError):
            return False
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        if a == 0:
            return b == 0
        return abs(b - a) / abs(a) <= NUMERIC_TOLERANCE
    return str(measured).strip().lower() == str(researched).strip().lower()


# This project has TWO names for the same measurement. The fact sheet calls it
# `tempo`; `compare` and `scorable.json` call it `tempo_bpm`. An agent gathering
# research reads scorable.json, so it files its claims under the second set.
#
# Matching on the sheet's names alone means a claim filed as `tempo_bpm: 144`
# finds no fact, is treated as an axis nothing measured, and is printed under
# the heading "Usable for what no measurement covers". The collision is never
# detected and the claim is relabelled as the one kind that is safe to use.
# Verified against a real sheet: tempo_bpm, lra_lu, low_end_share and
# lead_register_midi all escaped, and those four are exactly the projected set.
#
# So the alias table is not a convenience. It is the difference between the
# collision table working and inverting.
ALIASES = {
    'tempo_bpm': ('tempo', None),
    'key': ('key', None),
    'tuning': ('tuning', None),
    'intro_seconds': ('intro_seconds', None),
    'section_count': ('section_count', None),
    'lra_lu': ('loudness', 'lra_lu'),
    'integrated_lufs': ('loudness', 'integrated_lufs'),
    'true_peak_dbtp': ('loudness', 'true_peak_dbtp'),
    'low_end_share': ('spectral_balance', 'low_end_share'),
    'air_share': ('spectral_balance', 'air_share'),
    'centroid_hz': ('spectral_balance', 'centroid_hz'),
    'lead_register_midi': ('lead_register', 'median_midi'),
    'vocal_register_midi': ('vocal_register', 'median_midi'),
    'bpm': ('tempo', None),
    'beats_per_bar': ('meter', None),
}


def resolve_axis(sheet, axis):
    """The measured value a claim's axis name refers to, under either scheme.

    Returns (fact_axis, value, confidence) or None when nothing measured it.
    """
    facts = (sheet or {}).get('facts', {})
    fact_axis, field = ALIASES.get(axis, (axis, None))
    entry = facts.get(fact_axis)
    if entry is None:
        return None
    value = entry.get('value')
    if field is not None:
        if not isinstance(value, dict) or field not in value:
            return None
        value = value[field]
    return fact_axis, value, entry.get('confidence')


def collisions(sheet, rec):
    """Every axis both sides speak to, with the measurement authoritative.

    'authoritative' is the constant 'measured' rather than a computed field.
    No input to this function makes research win, and a reader can confirm
    that by looking rather than by tracing a branch.
    """
    rows = []
    for entry in rec.get('claims', []):
        resolved = resolve_axis(sheet, entry['axis'])
        if resolved is None:
            continue
        fact_axis, measured, confidence = resolved
        rows.append({
            'axis': entry['axis'],
            'fact_axis': fact_axis,
            # A copy. The row must not alias the sheet's own mutable value: a
            # caller editing a row would otherwise edit the fact sheet through
            # it. The no-mutation test uses deepcopy on the INPUT and cannot
            # catch that, because collisions() never mutates anything itself.
            'measured': copy.deepcopy(measured),
            'measured_confidence': confidence,
            'researched': copy.deepcopy(entry['value']),
            'researched_confidence': entry['confidence'],
            'source': entry['source'],
            'agrees': _agrees(measured, entry['value']),
            'authoritative': 'measured',
        })
    return rows


def render_markdown(sheet, rec):
    query = rec['query']
    name = ' - '.join(x for x in (query['artist'], query['title']) if x)
    lines = ['# Research', '', f'Query: {name}',
             f'Generated: {rec["generated_at"]}', '',
             'Measured facts outrank every claim on this page. Where the two',
             'meet, the collision table below names both and the measurement',
             'is authoritative. Nothing here is written into `facts.json`.', '']
    rows = collisions(sheet, rec)
    if rows:
        lines += ['## Collisions', '',
                  '| Claim axis | Fact axis | Measured | Grade | Researched | Grade | Agrees | Authoritative | Source |',
                  '|---|---|---|---|---|---|---|---|---|']
        for row in rows:
            lines.append(
                f'| {row["axis"]} | {row["fact_axis"]} | {row["measured"]} | '
                f'{row["measured_confidence"]} | {row["researched"]} | '
                f'{row["researched_confidence"]} | '
                f'{"yes" if row["agrees"] else "no"} | {row["authoritative"]} | '
                f'{row["source"]} |')
        lines.append('')
    context = [c for c in rec['claims'] if resolve_axis(sheet, c['axis']) is None]
    if context:
        lines += ['## Context', '',
                  'Claims on axes nothing measured. Usable for what no',
                  'measurement covers, such as the scene a sound belongs to.',
                  'Never usable as a number.', '',
                  '| Axis | Claim | Grade | Source |', '|---|---|---|---|']
        for entry in context:
            lines.append(f'| {entry["axis"]} | {entry["value"]} | '
                         f'{entry["confidence"]} | {entry["source"]} |')
        lines.append('')
    return '\n'.join(lines) + '\n'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest tests.test_research -v`
Expected: PASS, 19 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/research.py tests/test_research.py
git commit -m "feat: a collision table where the measurement cannot lose"
```

---

### Task 3: The research command

**Files:**
- Modify: `scripts/deconstruct.py`

**Interfaces:**
- Consumes: `research.record`, `research.claim`, `research.collisions`, `research.render_markdown`.
- Produces: CLI `research <facts.json> [--artist NAME] [--title NAME] [--claims FILE]`, printing `RESEARCH_WRITTEN=<path>` and `COLLISIONS=<n>`.

`--claims` takes a JSON array of claim objects, which is how the agent hands its
search results to the script. Without it the command writes an empty record with
the query recorded, which is the honest output when nothing was found.

- [ ] **Step 1: Write the failing check**

There is no unit test for the command layer in this repo's existing style; the
commands are proved by running them. Confirm the current behaviour first:

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python scripts/deconstruct.py research --help`
Expected: FAIL, `invalid choice: 'research'`

- [ ] **Step 2: Add the command function**

Above `def main():` in `scripts/deconstruct.py`:

```python
def cmd_research(args):
    import research as research_mod
    # read_facts, not json.loads. A mistyped path through a bare json.loads
    # reaches the user as 'ERROR: FileNotFoundError ... Details suppressed to
    # protect secrets', which is the failure read_facts exists to stop. The
    # MIDI command shipped with the same defect and fixed it in 8d2a02b.
    sheet = read_facts(args.facts, 'facts')
    raw = []
    if args.claims:
        raw = json.loads(args.claims.read_text(encoding='utf-8'))
        if not isinstance(raw, list):
            raise SkillError('--claims must hold a JSON array of claim objects')
    try:
        claims = [research_mod.claim(
            c['axis'], c['value'], c['source'], c['confidence'], c.get('note'))
            for c in raw]
        rec = research_mod.record(args.artist, args.title, claims)
    except research_mod.ResearchError as exc:
        raise SkillError(str(exc)) from None
    except KeyError as exc:
        raise SkillError(f'a claim in {args.claims} is missing {exc}') from None
    out = args.out or args.facts.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / 'research.json').write_text(
        json.dumps(rec, indent=2, allow_nan=False), encoding='utf-8')
    (out / 'research.md').write_text(
        research_mod.render_markdown(sheet, rec), encoding='utf-8')
    rows = research_mod.collisions(sheet, rec)
    print(f'RESEARCH_WRITTEN={out / "research.md"}')
    print(f'COLLISIONS={len(rows)}')
    for row in rows:
        if not row['agrees']:
            print(f'DISAGREEMENT axis={row["axis"]} '
                  f'measured={row["measured"]} researched={row["researched"]} '
                  f'authoritative=measured')
```

- [ ] **Step 3: Register and dispatch**

With the other parsers in `main()`:

```python
    rp = sub.add_parser('research')
    rp.add_argument('facts', type=Path)
    rp.add_argument('--artist', default='')
    rp.add_argument('--title', default='')
    rp.add_argument('--claims', type=Path, default=None,
                    help='JSON array of claim objects gathered by the agent.')
    rp.add_argument('--out', type=Path, default=None)
```

With the other branches:

```python
    elif args.command == 'research':
        cmd_research(args)
```

- [ ] **Step 4: Prove it end to end**

```bash
cd /Users/drewtuzson/Documents/Projects/deconstruct-audio
PY=.venv/bin/python
cat > /tmp/claims.json <<'JSON'
[{"axis": "tempo", "value": 144, "source": "https://example.org/a",
  "confidence": "GUESS", "note": "a listener comment, not a measurement"},
 {"axis": "scene", "value": "midwest emo revival",
  "source": "https://example.org/b", "confidence": "INFER", "note": null}]
JSON
$PY scripts/deconstruct.py research tests/fixtures/facts-sample.json \
  --artist "An Artist" --title "A Song" --claims /tmp/claims.json --out /tmp/research
cat /tmp/research/research.md
```

Expected: `COLLISIONS=1`, a `DISAGREEMENT` line naming tempo with
`authoritative=measured`, a collision table in the markdown, and the scene claim
under Context rather than in the table. Paste this into the pull request.

If `tests/fixtures/facts-sample.json` does not exist in your worktree, it comes
from the chord MIDI plan's Task 1. Create the same file here rather than waiting;
identical fixtures in two branches merge cleanly and a plan that stalls on
another worktree is a plan that does not run.

- [ ] **Step 5: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add scripts/deconstruct.py
git commit -m "feat: the research command"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`

- [ ] **Step 1: Add `research` to the command table in `README.md`**

```markdown
| `research <facts.json>` | Records scene and era claims gathered for a supplied artist or song name, in their own file, and prints every collision with a measured fact. The measurement is authoritative on every collision |
```

- [ ] **Step 2: Add a section to `README.md`**

```markdown
## Research, when a name is supplied

The research branch is optional and runs only when you supply a name. It writes
`research.json` and `research.md` beside the fact sheet and never writes into
`facts.json`.

Every claim carries its source. A claim with no source raises rather than
saving, because an unsourced claim is a memory and this file exists to keep
memories out of the facts. Where a claim and a measurement speak to the same
axis, both are printed side by side and the measurement is authoritative. That
is a constant in the code, not a rule someone has to remember.

A claim on an axis nothing measured is kept as context. It is usable for what
no measurement covers, such as the scene a sound belongs to. It never becomes
a number.
```

- [ ] **Step 3: Add the rule to `SKILL.md`**

State that the agent performs the searching, passes results through `--claims`,
never promotes a research claim into a fact, and never quotes a researched tempo
or key when the fact sheet measured one.

- [ ] **Step 4: Run the whole suite**

Run: `/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add README.md SKILL.md
git commit -m "docs: the research branch"
```

---

## Self-Review

**Spec coverage.** "Runs only when a name is supplied" is `record`'s guard and
`test_a_record_with_no_name_is_an_error_because_the_branch_is_optional`. "Writes
its claims to a separate file" is Task 3's command, which writes `research.json`
and `research.md` and touches nothing else. "Loses to a measured fact on every
collision" is the `authoritative` constant plus
`test_research_never_wins_even_against_an_unknown_measurement`, which is the case
a computed field would most likely get wrong. "Every claim carries its source" is
`claim`'s guard. The no-contamination guarantee is
`test_the_sheet_is_not_mutated_by_building_the_table`.

**Placeholders.** None. Task 4 step 3 points at `SKILL.md`'s own conventions
rather than reproducing them, for the same reason the MIDI plan does.

**Type consistency.** `claim` returns the dict `record` validates and
`collisions` reads. `collisions` returns `list[dict]` consumed by both
`render_markdown` and the command. `_agrees` is the only comparison path and is
used by nothing else, so the 2 percent tolerance has exactly one definition.
