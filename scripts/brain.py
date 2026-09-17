#!/usr/bin/env python3
"""Compose a Suno prompt from the fact sheet, in the user's own Brain format.

No Brain text lives in this file. The rules are extracted from the user's own
Brain at runtime, so a Brain update changes the checks instead of silently
going unenforced while the tests keep passing.

A rule that cannot be found reports UNREADABLE. It never reports a pass. A
check that could not locate its rule is not a check that succeeded, and this
project exists because something once reported a result it had not earned.
"""
import math
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


# The Brain wants a trait excluded by naming the quality that should stand in
# its place, so this has to catch every way a writer reaches for the reverse
# instead. Three words do not cover that. Measured: 'absent', 'free of',
# 'never' and 'excluding' all passed a validator claiming to enforce it.
#
# Described rather than quoted, deliberately. An earlier version of this
# comment restated the rule close enough to the Brain's own sentence to share
# a run of its words, which put licensed wording in the history for no gain: a
# paraphrase of a rule is not what enforces it, the list below is.
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


def _facts(sheet):
    """The sheet's axes, or an empty mapping if it has none of the shape.

    read_facts guarantees the file is a JSON object; it does not guarantee that
    `facts` is one, or that each axis carries a Fact. A malformed sheet reached
    `entry.get` and raised a bare AttributeError, which the top level handler
    turns into 'Details suppressed to protect secrets': the exact unhelpful
    failure read_facts exists to stop. An axis that is not a Fact is UNUSABLE,
    which is a thing the command can say out loud.
    """
    facts = (sheet or {}).get('facts')
    return facts if isinstance(facts, dict) else {}


def _number(value):
    """A finite number, or None.

    facts.py owns the shape of every value and this module reads it, so the two
    can drift: the sections axis split into section_count and
    section_boundaries once already. A stale or hand edited sheet carrying a
    string tempo or a scalar register used to reach float() and raise a bare
    ValueError or TypeError, which the top level handler prints as 'Details
    suppressed to protect secrets' rather than naming the axis at fault.

    A field this module cannot use makes its axis UNUSABLE, which the command
    already knows how to say out loud, and which is the honest answer: the
    sheet did not supply a number, so no phrase is written from one.

    A bool is not a number here. `True` is an int in Python and would otherwise
    become a tempo of 1 BPM.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        # JSON carries integers of unbounded size and float() refuses the ones
        # past its range. Unusable is the honest answer; letting OverflowError
        # out reaches the user as 'Details suppressed to protect secrets'.
        return None
    # NaN and infinity are not measurements. write_json refuses them on the way
    # out; this refuses them on the way in.
    return number if math.isfinite(number) else None


def _numbers(value):
    """A list of finite numbers, or None if any element is not one."""
    if not isinstance(value, (list, tuple)):
        return None
    out = [_number(item) for item in value]
    return None if any(item is None for item in out) else out


def _text(value):
    """A non empty string, or None. A number is not a name."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _field(entry, key):
    """One numeric field out of a Fact's value mapping, or None."""
    value = entry.get('value')
    return _number(value.get(key)) if isinstance(value, dict) else None


def _text_field(entry, key):
    """One string field out of a Fact's value mapping, or None."""
    value = entry.get('value')
    return _text(value.get(key)) if isinstance(value, dict) else None


def _usable(sheet, axis):
    entry = _facts(sheet).get(axis)
    if not isinstance(entry, dict):
        return None
    if entry.get('confidence') == 'UNKNOWN' or entry.get('value') is None:
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


# A selected tempo has to match a measured one to within this many BPM.
#
# Chosen from two measured quantities, not from a round number.
#
# The floor: a fact sheet prints a tempo to one decimal and a prompt states it
# as a whole number, so `162 BPM` in the style has to resolve back to the
# 161.5 the tempogram reported, or the flag cannot be reused on a rerun of the
# command that produced it. That rounding is worth at most 0.5 BPM.
#
# The ceiling: the levels on the reference sheet are 64.6, 80.7, 107.7, 129.2
# and 161.5, so the gaps between neighbouring measured values are 16.1, 27.0,
# 21.5 and 32.3 BPM. The smallest is 16.1, which a window of plus or minus 0.5
# clears by a factor of sixteen, so no measured level can ever capture a value
# meant for its neighbour.
#
# 0.5 therefore admits every spelling of a measured value and nothing else:
# 161, 161.5 and 162 all resolve to the 2x member, and 160 resolves to nothing.
TEMPO_MATCH_BPM = 0.5

# The shape tempo.py writes a competing level in. Ratio labels are '2x' style
# or '4/3' style; see RATIOS there.
_TEMPO_LEVEL = re.compile(
    r'([\d.]+x|\d+/\d+)\s+at\s+([\d.]+)\s+BPM'
    r'(?:\s*\(tempogram relative strength\s+([\d.]+)\))?')


def _decimal(token):
    r"""A number written as text, or None.

    The note is prose, so `[\d.]+` can hand back something like '1.2.3' that
    float() refuses. A number this cannot read is a level that is not offered,
    never a ValueError for the top level handler to suppress.
    """
    if not token:
        return None
    try:
        return _number(float(token))
    except (TypeError, ValueError):
        return None


def tempo_levels(entry):
    """Every BPM this tempo fact reported, with how the measurement labelled it.

    The selectable set, and the reason the flag can be trusted: a level is
    offered only because the measurement put it in this fact, never because a
    ratio of the primary would be plausible.

    It is recovered from the fact's `note`, which is where the family ends up.
    `tempo.grade` builds a structured family with a bpm, a ratio and a relative
    strength for each member, and `facts._tempo_fact` keeps only the primary
    and the prose, so the note is the only form of the family that reaches a
    fact sheet. Parsing our own generated sentence is the narrow reading of
    what the sheet actually contains; carrying the structured family through
    `fact()` instead would be better and is a change to facts.py rather than
    to this module.

    One branch of that prose names its ratios without their BPMs. Those levels
    are then not offered, which refuses a value the measurement did report.
    That is the safe direction, and `select_tempo_level` says so rather than
    implying the family was empty.
    """
    if not isinstance(entry, dict):
        return []
    primary = _number(entry.get('value'))
    if primary is None:
        # No primary means the axis is UNKNOWN, and a family hanging off an
        # unmeasured tempo is not a set anyone may select from. Offering one
        # would let a prompt state a BPM for a track whose tempo the sheet
        # declined to report.
        return []
    levels = [{'bpm': primary, 'source': 'primary', 'relative_strength': None}]
    seen = {primary}
    for ratio, bpm, strength in _TEMPO_LEVEL.findall(
            _text(entry.get('note')) or ''):
        value, rel = _decimal(bpm), _decimal(strength)
        if value is None or value in seen:
            continue
        seen.add(value)
        levels.append({'bpm': value, 'source': f'family {ratio}',
                       'relative_strength': rel})
    return levels


def select_tempo_level(entry, wanted):
    """The measured level a human chose, or a refusal naming every option.

    The whole rule of this flag: a value may be selected only because the
    measurement itself reported it. An unexplained BPM must not become a slot,
    because a slot is what the prompt is allowed to state and what
    `numbers_trace` will then certify as traced to the fact sheet.
    """
    target = _number(wanted)
    if target is None:
        raise BrainError(f'{wanted!r} is not a tempo in BPM.')
    levels = tempo_levels(entry)
    if not levels:
        raise BrainError(
            'This sheet reports no usable tempo, so there is no level to '
            'select. Compose without a BPM.')
    hits = sorted((abs(level['bpm'] - target), level) for level in levels
                  if abs(level['bpm'] - target) <= TEMPO_MATCH_BPM)
    if hits:
        return dict(hits[0][1])
    offered = ', '.join(f'{level["bpm"]} ({level["source"]})'
                        for level in levels)
    # Say WHY the set is thin, but only when it actually is: a note that names
    # ratios and no BPM has a family the sheet did not carry, which is a
    # different situation from a tempo that simply has no competing level.
    # Claiming the first whenever the set is small would be a confident
    # explanation of something that never happened.
    note = _text(entry.get('note')) or ''
    ratios_only = (len(levels) == 1
                   and re.search(r'[\d.]+x|\d+/\d+', note)
                   and not _TEMPO_LEVEL.search(note))
    thin = ('; this sheet\'s tempo note names its competing levels by ratio '
            'with no BPM, so the family did not reach the sheet and only the '
            'primary can be offered from it' if ratios_only else '')
    raise BrainError(
        f'{target} BPM is not a level this measurement reported. Selectable: '
        f'{offered}{thin}. Only a value the measurement itself reported may '
        f'be selected, because the prompt may only state what the fact sheet '
        f'measured.')


def slots(sheet, hold_out=None, tempo_level=None):
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
    # An axis name nobody recognises is refused rather than ignored. Ignoring
    # it held nothing out while `held_out` still reported the name, so
    # HELD_OUT= printed a control that was never applied and the exit bar would
    # have scored a run it did not actually control. The CLI's own `choices`
    # stops this at the command line; this stops it for every other caller.
    if hold_out is not None and hold_out not in HOLD_OUT_CHOICES:
        raise BrainError(
            f'{hold_out!r} is not an axis that can be held out. Choose one of '
            f'{", ".join(HOLD_OUT_CHOICES)}, or pass none for no control.')
    # Holding the tempo axis out and choosing a value for it are contradictory
    # instructions. Honouring either one silently would print a control or a
    # selection that was not applied.
    if tempo_level is not None and hold_out == 'tempo':
        raise BrainError(
            'The tempo axis cannot be held out and selected at the same time. '
            'Hold it out to run a control, or select a level to answer the '
            'question the sheet asked, not both.')
    out = {'moods': [], 'instruments': [], 'vocals': [], 'production': [],
           'direction': [], 'midi_only': [], 'unusable': [], 'ask_first': [],
           'held_out': hold_out, 'tempo_selection': None}
    for axis, entry in _facts(sheet).items():
        if (not isinstance(entry, dict)
                or entry.get('confidence') == 'UNKNOWN'
                or entry.get('value') is None):
            out['unusable'].append(axis)

    tempo = None if hold_out == 'tempo' else _usable(sheet, 'tempo')
    if tempo_level is not None and not tempo:
        raise BrainError(
            'This sheet has no usable tempo to select a level from, so there '
            'is nothing to answer. Compose without a BPM.')
    # A selection replaces the primary, and it may only be a level the
    # measurement reported. select_tempo_level raises rather than falling back,
    # because a BPM that resolved to nothing must never reach a slot: a slot is
    # exactly what numbers_trace will later certify as traced to the sheet.
    chosen = select_tempo_level(tempo, tempo_level) if (
        tempo and tempo_level is not None) else None
    beats = _number(tempo.get('value')) if tempo else None
    if chosen is not None:
        beats = chosen['bpm']
        strength = ('' if chosen['relative_strength'] is None
                    else f', tempogram relative strength '
                         f'{chosen["relative_strength"]}')
        chosen['note'] = (
            f'{chosen["bpm"]} BPM selected by a human from the measured tempo '
            f'family, as the {chosen["source"]} member{strength}. The sheet '
            f'reports a primary of {_number(tempo.get("value"))} BPM.')
        out['tempo_selection'] = chosen
    if beats is not None:
        out['moods'].append(f'{round(beats)} BPM')
        # See THE TEMPO RULE in the plan. _usable already drops an UNKNOWN
        # tempo, so nothing reaches here without a value, but an INFER tempo
        # whose family holds a competing metrical level is a minority reading
        # and the agent must not silently turn it into a tag.
        #
        # A selection IS that answer, so it settles this question on its own.
        # Requiring --acknowledge as well would ask the user to confirm they
        # answered the question they have just answered. Any other ask_first
        # entry is untouched and still needs acknowledging.
        if tempo['confidence'] != 'KNOW' and chosen is None:
            out['ask_first'].append(
                f'tempo is graded {tempo["confidence"]}: {tempo.get("note")}')
    elif tempo:
        out['unusable'].append('tempo')

    tuning = None if hold_out == 'tuning' else _usable(sheet, 'tuning')
    name = _text(tuning.get('value')) if tuning else None
    if name:
        out['instruments'].append(
            f'{name.replace("#", " sharp")} tuned rhythm guitar'
            .replace('-', ' '))
    elif tuning:
        out['unusable'].append('tuning')

    lead = (None if hold_out == 'lead_register'
            else _usable(sheet, 'lead_register'))
    median = _field(lead, 'median_midi') if lead else None
    if median is not None:
        out['instruments'].append(
            f'{_band(median, REGISTER_BANDS, "very high register")} '
            f'lead guitar figure')
    elif lead:
        out['unusable'].append('lead_register')

    vocal = _usable(sheet, 'vocal_register')
    sung = _field(vocal, 'median_midi') if vocal else None
    if sung is not None:
        out['vocals'].append(
            f'{_band(sung, REGISTER_BANDS, "very high register")} lead vocal')
    elif vocal:
        out['unusable'].append('vocal_register')

    spectral = (None if hold_out == 'spectral_balance'
                else _usable(sheet, 'spectral_balance'))
    low_end = _field(spectral, 'low_end_share') if spectral else None
    if low_end is not None:
        out['production'].append(
            _band(low_end, LOW_END_BANDS, 'dominant low end'))
    elif spectral:
        out['unusable'].append('spectral_balance')

    harmonic = _usable(sheet, 'harmonic_rhythm')
    label = _text_field(harmonic, 'label') if harmonic else None
    if label:
        out['production'].append(f'{label} harmony')
    elif harmonic:
        out['unusable'].append('harmonic_rhythm')

    intro = (None if hold_out == 'intro_seconds'
             else _usable(sheet, 'intro_seconds'))
    opening = _number(intro.get('value')) if intro else None
    if opening is not None:
        out['direction'].append(
            f'The song opens on roughly {round(opening)} seconds '
            f'of build before the full arrangement lands.')
    elif intro:
        out['unusable'].append('intro_seconds')

    # section_count, not sections. The fact sheet split that axis: boundaries
    # are INFER and the count is UNKNOWN by construction, because sixteen
    # segmentation methods failed to generalise. Reading the old name returns
    # None silently, which cost the direction prose its second sentence while
    # the Brain requires two to three. The agent was then quietly expected to
    # invent one, which is the exact failure this whole pipeline exists to stop.
    sections = _usable(sheet, 'section_count')
    count = _number(sections.get('value')) if sections else None
    boundaries = _usable(sheet, 'section_boundaries')
    marks = _numbers(boundaries.get('value')) if boundaries else None
    # Neither sentence claims the track ends without a fade. The plan's wording
    # did, and it was wrong twice over: nothing in the sheet measures a fade,
    # and 'without' is a negation word the Brain bans outright, so the phrase
    # could not legally reach a prompt. A slot phrase the validator must reject
    # is worse than a missing one, because the agent's only escape is a drop it
    # cannot justify against the budget.
    if count is not None:
        out['direction'].append(
            f'It moves through about {int(count)} sections of its own.')
    elif marks and len(marks) >= 2:
        # The count is UNKNOWN, but the boundaries are real and the Brain needs
        # a second direction sentence. This says what was measured, the shape,
        # without stating a count nothing earned.
        longest = max(later - earlier
                      for earlier, later in zip(marks, marks[1:]))
        out['direction'].append(
            f'It changes texture several times, with its longest unbroken '
            f'stretch running about {round(longest)} seconds.')
    if sections and count is None:
        out['unusable'].append('section_count')
    if boundaries and not (marks and len(marks) >= 2):
        out['unusable'].append('section_boundaries')
    if len(out['direction']) < 2:
        out['unusable'].append('direction_prose_second_sentence')

    chords = _usable(sheet, 'chords')
    if chords:
        out['midi_only'].append('chord progression, supplied as MIDI')
    key = _usable(sheet, 'key')
    named = _text(key.get('value')) if key else None
    if named:
        out['midi_only'].append(f'key, {named}, supplied as MIDI')
    elif key:
        out['unusable'].append('key')
    return out


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


QUANTITY = re.compile(r'(\d+)\s*([A-Za-z]+)?')


def _quantities(text):
    """Every number in `text`, paired with the word that follows it.

    The unit is what makes a number a measurement, and a bare set of integers
    throws it away. With the tempo slot holding '81 BPM', a declared sentence
    saying '81 seconds of tape delay' passed this check and then passed
    provenance as judgement, so the command approved a duration the fact sheet
    never established. Pairing the number with its unit is the difference
    between 'this number appears in the sheet' and 'this measurement does'.

    ONE DOOR IS DELIBERATELY LEFT OPEN, and it is written down here so the
    next person finds it rather than discovers it. The unit is checked, the
    subject it attaches to is not. The intro slot says 'roughly 12 seconds of
    build', so '12 seconds of total silence' traces cleanly: same number, same
    unit, opposite claim about the music.

    That is disclosure rather than prevention, and it is the same position
    this pipeline takes on the tuning axis. Closing it would mean parsing what
    each phrase is about, which is judgement. Leaving it open costs nothing
    hidden, because provenance still forces that sentence into `--added`: it
    is not a slot phrase, so it fails unless the agent declares it, and it
    then sits in the declared list a human reads out before the money is
    spent. The check that catches it is a person, and the contract is what
    puts it in front of them.
    """
    return {(int(number), (unit or '').lower())
            for number, unit in QUANTITY.findall(str(text))}


def slot_quantities(filled):
    """Every number in a slot phrase, with the unit it was measured in.

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
            out |= _quantities(phrase)
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


def _canonical(text):
    """One spelling for comparison.

    Not a prefix: a prefix match let a phrase be counted as inherited and then
    inverted, so 'roughly 12 seconds of build' and 'roughly 12 minutes of total
    silence' both scored as coming from the same measurement.
    """
    return ' '.join(str(text).lower().replace('.', ' ').split())


def _decompose(style):
    """The style as the Brain's own format defines it: a comma separated tag
    stack, then direction prose in sentences."""
    parts = list(SENTENCE.split(style))
    head = parts[0] if parts else ''
    tags = [t.strip() for t in head.split(',') if t.strip()]
    sentences = [s.strip() for s in parts[1:] if s.strip()]
    return tags, sentences


def validate(style, exclude, sheet, rules, mode='custom', names=(),
             filled=None, acknowledged=False, declared=(), dropped=()):
    """Check a composed prompt against the Brain's own rules.

    `filled` is the slots dict the prompt was supposed to be written from. It
    is an argument rather than recomputed here so the caller checks the SAME
    slots it handed the agent, including any held out axis.

    `dropped` is checked against a budget, not taken on trust. See the
    allowance below.
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
        results.append(_result(
            'budget', 'UNKNOWN',
            f'no budget for {mode} could be read from the Brain'))
    else:
        length = len(style)
        if length > cap:
            results.append(_result(
                'budget', 'FAIL',
                f'{length} characters over the hard cap of {cap}'))
        elif (target and target is not UNREADABLE
                and not target[0] <= length <= target[1]):
            results.append(_result(
                'budget', 'FAIL',
                f'{length} characters outside the target {target[0]} to '
                f'{target[1]}'))
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
    for key in ('banned_words', 'banned_phrases'):
        rule = rules.get(key)
        if rule is UNREADABLE:
            results.append(_result(
                key, 'UNKNOWN', f'{key} could not be read from the Brain'))
            continue
        if key == 'banned_words':
            hits = _found_words(body, rule)
        else:
            hits = [p for p in rule if p in body]
        results.append(_result(key, 'FAIL' if hits else 'PASS',
                               ', '.join(hits)))

    # Direction prose
    sentences = [s for s in SENTENCE.split(style)
                 if len(s.strip().split()) >= 5]
    results.append(_result(
        'direction_prose',
        'PASS' if len(sentences) >= PROSE_MIN_SENTENCES else 'FAIL',
        f'{len(sentences)} prose sentences of five words or more'))

    # BPM placement, but only when there is a BPM to place.
    #
    # slots() emits no BPM when the tempo axis is held out, absent, or graded
    # UNKNOWN, and the plan's own tempo rule wants exactly that: a tag stack
    # without a BPM is a smaller failure than one anchored to the wrong
    # metrical level. Demanding one unconditionally made those runs impossible
    # to pass, because numbers_trace rejects a BPM that is not in the slots and
    # this rejected a style that left it out. `--hold-out tempo`, the control
    # the exit bar leans on, could never have reached PASS.
    #
    # It does not become a check that passes for want of a rule. When the sheet
    # measured no tempo, a style that states one anyway FAILS here: that is a
    # tempo nobody measured, which is the failure this pipeline exists to stop,
    # and numbers_trace alone would miss a bare 'BPM' carrying no digits.
    measured_bpm = any('bpm' in str(phrase).lower()
                       for key in SLOT_KEYS for phrase in filled.get(key, []))
    bpm_at = body.find('bpm')
    if not measured_bpm:
        results.append(_result(
            'bpm_placement', 'FAIL' if bpm_at >= 0 else 'PASS',
            'the style states a BPM the fact sheet did not measure'
            if bpm_at >= 0
            else 'no tempo reached the slots, so the style states none'))
    elif bpm_at < 0:
        results.append(_result(
            'bpm_placement', 'FAIL',
            'a tempo was measured and never reached the style'))
    else:
        first_sentence = SENTENCE.split(style)[0]
        limit = len(first_sentence) * MOODS_FRACTION
        results.append(_result(
            'bpm_placement', 'PASS' if bpm_at <= limit else 'FAIL',
            f'BPM at character {bpm_at} of a {len(first_sentence)} character '
            f'tag stack'))

    # Every number traces to a slot phrase. Every number, including single
    # digits, which the earlier \d{2,4} pattern never looked at.
    # Both fields, not just the style. The exclude field is prompt content
    # like any other and it reaches the generator the same way, so
    # '909 drum machine, 1987 gated reverb' was quoting two numbers nothing
    # measured and passing, because only the style was ever read here.
    traceable = slot_quantities(filled)
    quoted = _quantities(style) | _quantities(exclude)
    orphans = sorted(f'{number} {unit}'.strip()
                     for number, unit in quoted
                     if (number, unit) not in traceable)
    results.append(_result(
        'numbers_trace', 'FAIL' if orphans else 'PASS',
        f'orphans {orphans}' if orphans
        else f'{len(quoted)} measurements across both fields, all traced to '
             f'a slot'))

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
    pieces = ([(t, _canonical(t)) for t in tags]
              + [(s, _canonical(s)) for s in sentences])

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
    unused = sorted(p for p in slot_phrases
                    if p not in present and p not in shed)

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
    # So a drop must be MINIMAL: putting any one dropped phrase back would
    # still overflow the cap. This replaces an allowance expressed in
    # characters, which needed a model of how phrases are joined and could
    # never be spent exactly because drops are whole phrases. Both problems go
    # away when the question is asked one phrase at a time: the separator only
    # has to be right at a single phrase margin, and there is no remainder to
    # leave on the table.
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
    # A whole term, not an arbitrary substring. `--name Rush` used to reject
    # 'brushed drums', which is a false FAIL on an honest prompt and the kind
    # of noise that trains an operator to stop reading the checks. The
    # lookarounds rather than \b so a name opening or closing on punctuation
    # still matches.
    named = [n for n in names if n and re.search(
        rf'(?<![0-9A-Za-z]){re.escape(n.lower())}(?![0-9A-Za-z])', both)]
    results.append(_result('names', 'FAIL' if named else 'PASS',
                           ', '.join(named)))

    # Exclude budget
    rule = rules.get('exclude_budget')
    if rule is UNREADABLE:
        results.append(_result(
            'exclude_budget', 'UNKNOWN',
            'no exclude budget could be read from the Brain'))
    else:
        length = len(exclude)
        results.append(_result(
            'exclude_budget',
            'PASS' if rule[0] <= length <= rule[1] else 'FAIL',
            f'{length} characters against a target of {rule[0]} to {rule[1]}'))
    return results
