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


# The Brain's rule is that a ruled out trait becomes its positive opposite.
# Three words do not cover that. Measured: 'absent', 'free of', 'never' and
# 'excluding' all passed a validator claiming to enforce it.
#
# This list will never be complete, and the check is therefore a floor rather
# than a proof. It is still worth having, because every entry is a phrase a
# prompt writer actually reaches for.
#
# It also binds the slot builder. Every phrase `slots` emits is checked against
# this list by the suite, because a slot phrase carrying a banned word is a
# measurement the prompt is not allowed to state: the agent must either drop it
# and fail the drop test or keep it and fail the negation test.
NEGATION_WORDS = ('no', 'not', 'without', 'never', 'absent', 'lacking',
                  'excluding', 'except', 'minus', 'sans', 'devoid', 'neither',
                  'nor', 'none', 'avoid', 'omit', 'exclude', 'free of',
                  'free from', 'stripped of', 'rather than', 'instead of')

# MIDI note number bands, named the way a prompt names them. A prompt that
# says 42 says nothing; a prompt that says low register says the thing the
# number meant. This mapping is the whole reason lead_register is a fact:
# four generation cycles were spent discovering by ear that an intro had
# arrived an octave high.
REGISTER_BANDS = ((48, 'very low register'), (55, 'low register'),
                  (67, 'mid register'), (79, 'high register'))
LOW_END_BANDS = ((8.0, 'light low end'), (14.0, 'balanced low end'),
                 (22.0, 'heavy low end'), (100.0, 'dominant low end'))

SLOT_KEYS = ('moods', 'instruments', 'vocals', 'production', 'direction')


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
        # See THE TEMPO RULE in the plan. _usable already drops an UNKNOWN
        # tempo, so nothing reaches here without a value, but an INFER tempo
        # whose family holds a competing metrical level is a minority reading
        # and the agent must not silently turn it into a tag.
        if tempo['confidence'] != 'KNOW':
            out['ask_first'].append(
                f'tempo is graded {tempo["confidence"]}: {tempo.get("note")}')

    tuning = None if hold_out == 'tuning' else _usable(sheet, 'tuning')
    if tuning:
        out['instruments'].append(
            f'{str(tuning["value"]).replace("#", " sharp")} tuned rhythm guitar'
            .replace('-', ' '))

    lead = (None if hold_out == 'lead_register'
            else _usable(sheet, 'lead_register'))
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

    intro = (None if hold_out == 'intro_seconds'
             else _usable(sheet, 'intro_seconds'))
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
    # Neither sentence claims the track ends without a fade. The plan's wording
    # did, and it was wrong twice over: nothing in the sheet measures a fade,
    # and 'without' is a negation word the Brain bans outright, so the phrase
    # could not legally reach a prompt. A slot phrase the validator must reject
    # is worse than a missing one, because the agent's only escape is a drop it
    # cannot justify against the budget.
    if sections:
        out['direction'].append(
            f'It moves through about {int(sections["value"])} distinct '
            f'sections of its own.')
    elif boundaries and len(boundaries['value']) >= 2:
        # The count is UNKNOWN, but the boundaries are real and the Brain needs
        # a second direction sentence. This says what was measured, the shape,
        # without stating a count nothing earned.
        spans = [later - earlier
                 for earlier, later in zip(boundaries['value'],
                                           boundaries['value'][1:])]
        longest = max(spans) if spans else 0
        out['direction'].append(
            f'It changes texture several times, with its longest unbroken '
            f'stretch running about {round(longest)} seconds.')
    if len(out['direction']) < 2:
        out['unusable'].append('direction_prose_second_sentence')

    chords = _usable(sheet, 'chords')
    if chords:
        out['midi_only'].append('chord progression, supplied as MIDI')
    key = _usable(sheet, 'key')
    if key:
        out['midi_only'].append(f'key, {key["value"]}, supplied as MIDI')
    return out
