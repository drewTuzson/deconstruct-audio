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
        # The parent axis is present, so this axis was attempted. An UNKNOWN
        # parent carries value None rather than a dict, and a resolved one
        # carries the dict. Returning None here for the UNKNOWN case would file
        # the claim as context, printed under the heading that says such claims
        # are safe to use, which is the same inversion the alias table exists to
        # stop. A present parent that cannot yield the field therefore resolves
        # to a measured None: the claim lands in the collision table and the
        # measurement stays authoritative. Only an axis the sheet never names
        # is context.
        value = value.get(field) if isinstance(value, dict) else None
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


def _cell(value):
    """One markdown table cell, safe to sit between two pipes.

    Claim axes, values and sources are free form text out of a hand written
    file. A pipe opens a column and a newline opens a row, either of which
    separates a measured value from its label in the one table whose whole job
    is to show which of the two is authoritative. Runs of whitespace collapse
    to a single space so a multi line claim stays on its own row, and pipes and
    backslashes are escaped so the text still reads as it was written.
    """
    text = ' '.join(str(value).split())
    return text.replace('\\', '\\\\').replace('|', '\\|')


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
                f'| {_cell(row["axis"])} | {_cell(row["fact_axis"])} | '
                f'{_cell(row["measured"])} | {_cell(row["measured_confidence"])} | '
                f'{_cell(row["researched"])} | '
                f'{_cell(row["researched_confidence"])} | '
                f'{"yes" if row["agrees"] else "no"} | '
                f'{_cell(row["authoritative"])} | {_cell(row["source"])} |')
        lines.append('')
    context = [c for c in rec['claims'] if resolve_axis(sheet, c['axis']) is None]
    if context:
        lines += ['## Context', '',
                  'Claims on axes nothing measured. Usable for what no',
                  'measurement covers, such as the scene a sound belongs to.',
                  'Never usable as a number.', '',
                  '| Axis | Claim | Grade | Source |', '|---|---|---|---|']
        for entry in context:
            lines.append(f'| {_cell(entry["axis"])} | {_cell(entry["value"])} | '
                         f'{_cell(entry["confidence"])} | {_cell(entry["source"])} |')
        lines.append('')
    return '\n'.join(lines) + '\n'
