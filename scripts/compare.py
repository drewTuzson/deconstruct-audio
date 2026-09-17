#!/usr/bin/env python3
"""Score a candidate track against a reference on measured axes.

Pure by design and deliberately import-free: score() takes two dicts and
returns a verdict, so nothing here depends on the state of the machine it
runs on. That includes the standard library. isfinite is spelled out below
rather than imported from math so that "this module imports nothing" stays a
property a reader can confirm at a glance.
"""

INFINITY = float('inf')
UNUSABLE_NOTE = 'so this axis was not scored'

RELATIVE_SEMITONES = 3
NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
VALID_MODES = {'major', 'minor'}
FLATS_TO_SHARPS = {
    'DB': 'C#', 'EB': 'D#', 'GB': 'F#', 'AB': 'G#', 'BB': 'A#',
}

GATES = {
    'tempo_bpm': {'kind': 'percent', 'limit': 5.0, 'label': 'Tempo'},
    'key': {'kind': 'key', 'label': 'Key'},
    'intro_seconds': {'kind': 'absolute', 'limit': 3.0, 'label': 'Intro length'},
    'lra_lu': {'kind': 'absolute', 'limit': 1.5, 'label': 'Loudness range'},
    'low_end_share': {'kind': 'absolute', 'limit': 3.0, 'label': 'Low end share'},
    'section_count': {'kind': 'absolute', 'limit': 1, 'label': 'Section count'},
    'lead_register_midi': {'kind': 'absolute', 'limit': 5, 'label': 'Lead register'},
    'tuning': {'kind': 'tuning', 'label': 'Tuning'},
}


def usable_number(value):
    """The value as a finite float, or None if it is not a number we can score.

    Fact sheets are hand-authored JSON and the loader accepts any object, so a
    quoted number or a null is an ordinary typo rather than an exotic input.
    Before this guard, score({'section_count': 7}, {'section_count': '7'})
    raised TypeError on the subtraction.

    Nothing is coerced. Reading '7' as 7 would turn a typo into a measurement,
    and this project exists because a pipeline reported musical facts it had
    not earned. UNKNOWN is the honest answer to a value nothing can score.

    Booleans are rejected even though bool subclasses int in Python, so True
    would otherwise arrive as 1.0 and be scored. It read as 'delta -3.10
    against limit 1.5' and returned FAIL: a confident verdict with a plausible
    number attached, from a value that measured nothing. A boolean in a
    numeric axis is an authoring mistake, not a measurement of any size.

    NaN and the infinities are rejected for the same reason: both reached the
    comparison and produced FAIL, which reads as a track that missed a gate
    rather than arithmetic running on a non-measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        # An int too large to be a float is not a measurement either.
        return None
    if value != value:  # NaN is the only value that is unequal to itself.
        return None
    if value == INFINITY or value == -INFINITY:
        return None
    return value


def unusable_sides(reference, candidate):
    """Which sides, if either, hold a value that cannot be scored."""
    return [name for name, value in (('reference', reference),
                                     ('candidate', candidate))
            if usable_number(value) is None]


def unusable_note(reference, candidate):
    sides = unusable_sides(reference, candidate)
    subject = ' and '.join(sides).capitalize()
    claim = ('values are not usable numbers' if len(sides) > 1
             else 'value is not a usable number')
    return f'{subject} {claim}, {UNUSABLE_NOTE}'


def parse_key(value):
    s = str(value).strip()
    # Handle space-separated or space-free input
    if ' ' in s:
        parts = s.split(' ', 1)
    else:
        # For no-space input like 'F#minor', extract first 1-2 chars as note
        if len(s) >= 2 and s[1] in ('#', 'b'):
            parts = [s[:2], s[2:]]
        elif len(s) >= 1:
            parts = [s[:1], s[1:]]
        else:
            return None
    if len(parts) != 2:
        return None
    note_str, mode_str = parts[0].upper(), parts[1].lower()
    # Map flats to sharps
    if note_str in FLATS_TO_SHARPS:
        note_str = FLATS_TO_SHARPS[note_str]
    if note_str not in NOTES:
        return None
    if mode_str not in VALID_MODES:
        return None
    return NOTES.index(note_str), mode_str


def key_verdict(reference, candidate):
    # Parse before comparing. Raw string equality made any sentinel identical
    # on both sides ('unknown', '', a placeholder) an earned PASS on an axis
    # nothing had measured, and score() then counted it among the measured
    # axes. Equal but unparseable is UNKNOWN; equal and parseable is PASS.
    a, b = parse_key(reference), parse_key(candidate)
    if a is None or b is None:
        return 'UNKNOWN', 'key not parseable'
    if a == b:
        return 'PASS', 'exact match'
    distance = (b[0] - a[0]) % 12
    if a[1] != b[1] and distance in (RELATIVE_SEMITONES, 12 - RELATIVE_SEMITONES):
        return 'WARN', 'relative major or minor, not the same tonal centre'
    return 'FAIL', 'unrelated key'


def normalise_tuning(value):
    """Canonical '<qualifier> <pitch>' form, or None when this names no tuning.

    The pitch is read from whichever END carries it, because the conventional
    names put it at either one: 'drop C#' finishes with it and 'Eb standard'
    opens with it. Folding the last token only made Eb and D# two spellings
    that scored FAIL against each other.

    A string with no note name at either end is not a tuning, and returning
    None for it is what stops 'unknown' matching 'unknown' and counting as a
    measured axis. key_verdict already learned this: any two identical strings
    compare equal, so a sentinel earned a PASS on an axis nothing measured.

    Only the ends are searched, never the middle. Every single letter from A to
    G is a note name, so scanning all tokens reads the article in 'not a
    tuning' as the pitch A and hands back 'not tuning A', which passes against
    itself and reopens the hole this function exists to close.
    """
    if not isinstance(value, str):
        return None
    tokens = value.strip().lower().split()
    if not tokens:
        return None

    def pitch_of(token):
        upper = token.upper()
        upper = FLATS_TO_SHARPS.get(upper, upper)
        return upper if upper in NOTES else None

    # Last first: 'drop C#' and 'standard E' are the common shapes.
    pitch = pitch_of(tokens[-1])
    rest = tokens[:-1]
    if pitch is None:
        pitch = pitch_of(tokens[0])
        rest = tokens[1:]
    if pitch is None:
        return None
    return f'{" ".join(rest) or "standard"} {pitch}'


def tuning_verdict(reference, candidate):
    a, b = normalise_tuning(reference), normalise_tuning(candidate)
    if a is None or b is None:
        return 'UNKNOWN', 'tuning not parseable'
    if a == b:
        return 'PASS', 'same tuning'
    return 'FAIL', f'{candidate} is not {reference}'


def tempo_verdict(reference, candidate):
    # Guarded here rather than only in score(), because tempo_verdict is
    # public and called directly, so the entry point has to be safe too.
    if unusable_sides(reference, candidate):
        return 'UNKNOWN', unusable_note(reference, candidate), None
    reference, candidate = usable_number(reference), usable_number(candidate)
    if reference <= 0:
        return 'UNKNOWN', 'no reference tempo', None
    delta = candidate - reference
    drift = abs(delta) / reference * 100
    for factor, name in ((2.0, 'octave'), (0.5, 'octave'),
                         (4.0 / 3.0, 'subdivision'), (0.75, 'subdivision')):
        if abs(candidate / reference - factor) / factor <= 0.04:
            return 'FAIL', f'{name} error, candidate is {factor:g}x the reference', delta
    if drift <= GATES['tempo_bpm']['limit']:
        return 'PASS', f'{drift:.1f}% drift', delta
    return 'FAIL', f'{drift:.1f}% drift exceeds 5%', delta


def score(reference, candidate):
    axes = []
    for axis, gate in GATES.items():
        ref, cand = reference.get(axis), candidate.get(axis)
        if ref is None or cand is None:
            axes.append({'axis': axis, 'label': gate['label'], 'reference': ref,
                         'candidate': cand, 'delta': None, 'verdict': 'UNKNOWN',
                         'note': 'not measured on both sides'})
            continue
        if gate['kind'] == 'key':
            verdict, note = key_verdict(ref, cand)
            delta = None
        elif gate['kind'] == 'tuning':
            verdict, note = tuning_verdict(ref, cand)
            delta = None
        elif gate['kind'] == 'percent':
            verdict, note, delta = tempo_verdict(ref, cand)
        elif unusable_sides(ref, cand):
            # Not a finite number where a number is required. UNKNOWN, with a
            # note that says the value was not usable, and no delta: there is
            # nothing to subtract and no verdict anything has earned.
            verdict, note, delta = 'UNKNOWN', unusable_note(ref, cand), None
        else:
            delta = usable_number(cand) - usable_number(ref)
            within = abs(delta) <= gate['limit']
            verdict = 'PASS' if within else 'FAIL'
            note = f'delta {delta:+.2f} against limit {gate["limit"]}'
        axes.append({'axis': axis, 'label': gate['label'], 'reference': ref,
                     'candidate': cand, 'delta': delta, 'verdict': verdict, 'note': note})
    verdicts = [a['verdict'] for a in axes if a['verdict'] != 'UNKNOWN']
    unknown_count = len(axes) - len(verdicts)
    measured_count = len(verdicts)
    if not verdicts:
        overall = 'UNKNOWN'
    else:
        overall = 'FAIL' if 'FAIL' in verdicts else ('WARN' if 'WARN' in verdicts else 'PASS')
    return {'axes': axes, 'verdict': overall, 'measured': measured_count, 'unmeasured': unknown_count}
