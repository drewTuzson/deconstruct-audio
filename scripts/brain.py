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


def rules_from(sources):
    """Extract from whichever instruction source actually carries the rules.

    Returns `(name, rules)` so the caller can print which file was parsed.

    Measured, not assumed. The first version of the command took
    `SYSTEM-PROMPT-FULL.txt` when present and fell back to `INSTRUCTIONS.txt`.
    On a real Brain that is backwards: the full prompt is an assembled
    document about eleven times the size that carries none of the labelled
    rule lines, while the short instructions file carries all of them. That
    preference produced six RULE_UNREADABLE lines and a verdict that could
    never reach PASS, against a Brain whose rules parse cleanly.

    Choosing by how many rules a source yields cannot manufacture a pass.
    Whatever stays unreadable is still reported, and only one source is used,
    so two files can never be blended into a rule set neither of them states.
    A tie keeps the earlier entry in `INSTRUCTION_FILES`, which is the full
    prompt, matching what references/brain.md asks a reader to prefer.
    """
    candidates = [name for name in INSTRUCTION_FILES if name in sources]
    if not candidates:
        raise BrainError(
            f'No Brain instruction source to read rules from. Expected one of '
            f'{", ".join(INSTRUCTION_FILES)}.')
    best_name, best_rules = None, None
    for name in candidates:
        rules = extract_rules(sources[name])
        if best_rules is None or len(rules['unreadable']) < len(
                best_rules['unreadable']):
            best_name, best_rules = name, rules
    return best_name, best_rules


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
    # `[\s\S]*?` rather than `[^\n]*?` between the target and the cap. A rules
    # file hard wraps its prose, and this budget's two halves routinely land on
    # either side of a line break: the version that forbade a newline here read
    # UNREADABLE on the ordinary wrapped wording. Crossing a line is safe
    # because `_near` has already bounded the search to this mode's own window
    # and stopped it at the next mode, which is the anchoring that matters. It
    # is not the document spanning `.*?` with `re.S` that this deliberately
    # avoids.
    simple = _near(text, 'SIMPLE',
                   rf'[Tt]arget\s+{NUMBER}\s+to\s+{NUMBER}\s+characters'
                   rf'[\s\S]*?cap\s+{NUMBER}')
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
                  for w in banned.group(1).split(',')
                  if w.strip()) if banned else ()
    # An empty parse is UNREADABLE, never an empty tuple. A tuple of nothing
    # reports as a rule that was read cleanly and then passes every string,
    # which is a validator that has been switched off while showing a green
    # light. That is the single most dangerous shape a check can take.
    rules['banned_words'] = words if words else UNREADABLE

    never = re.search(r'\bNever:\s*([^\n]+)', text)
    found = tuple(p.strip().strip('"').lower()
                  for p in re.findall(r'"([^"]+)"',
                                      never.group(1))) if never else ()
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
