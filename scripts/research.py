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
