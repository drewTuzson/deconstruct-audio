#!/usr/bin/env python3
"""Score a candidate track against a reference on measured axes."""

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
}


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


def tempo_verdict(reference, candidate):
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
        elif gate['kind'] == 'percent':
            verdict, note, delta = tempo_verdict(ref, cand)
        else:
            delta = cand - ref
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
