#!/usr/bin/env python3
"""The fact sheet. Every number carries the method that produced it.

This module exists because the pipeline it replaces emitted bare numbers from
a language model and three passes on one track returned three tempos. A fact
that cannot say how it was measured is not a fact, so fact() raises rather
than emitting one.
"""
import math

CONFIDENCE = ('KNOW', 'INFER', 'UNKNOWN')
ACTIONABLE = ('direct', 'indirect', 'midi_only', 'none')


class FactError(Exception):
    pass


def _plain(value):
    """A JSON-safe copy of value, with numpy scalars coerced.

    json.dumps(allow_nan=False) accepts np.float64 and raises TypeError on
    np.float32, so an axis that forgets one float() crashes the command at
    write time rather than where the mistake was made. Coercing once here
    costs nothing and removes fourteen chances to forget.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, int):
        return int(value)
    return value


def _finite(value):
    """True when value is a real measurement rather than a placeholder.

    A boolean INSIDE a container is a flag, not a scalar posing as a
    measurement: `instrumentation` carries one `active` per stem and a chord
    entry carries `third_present`. Revision 2 rejected every boolean at every
    depth, which made the third builder raise on every track. A bare boolean
    is still refused, by fact() before this function is reached.
    """
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_finite(v) for v in value)
    return True


def fact(value, unit, stem, method, confidence, suno_actionable,
         band_hz=None, note=None):
    if confidence not in CONFIDENCE:
        raise FactError(f'confidence must be one of {CONFIDENCE}, got {confidence!r}')
    if suno_actionable not in ACTIONABLE:
        raise FactError(f'suno_actionable must be one of {ACTIONABLE}, '
                        f'got {suno_actionable!r}')
    if isinstance(method, str) or not isinstance(method, (list, tuple)) or not method:
        raise FactError('method must be a non-empty list of method names')
    if value is None and confidence != 'UNKNOWN':
        raise FactError('a fact with no value must be graded UNKNOWN')
    if isinstance(value, bool):
        raise FactError('a bare boolean is a flag, not a measurement')
    value = _plain(value)
    if value is not None and not _finite(value):
        raise FactError(f'{value!r} is not a measurement')
    if band_hz is not None:
        if not isinstance(band_hz, (list, tuple)) or len(band_hz) != 2:
            raise FactError('band_hz must be a [low, high] pair or None')
        band_hz = [_plain(band_hz[0]), _plain(band_hz[1])]
    return {'value': value, 'unit': unit, 'stem': stem, 'band_hz': band_hz,
            'method': list(method), 'confidence': confidence,
            'suno_actionable': suno_actionable, 'note': note}
