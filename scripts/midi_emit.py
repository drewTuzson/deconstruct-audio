#!/usr/bin/env python3
"""The harmonic skeleton as MIDI.

Chord names in a text prompt are discarded by the target generator, which is
why this file exists: it is the channel that carries harmony when text cannot.

The emitter writes no pitch it did not measure. Where a third was not measured
it writes root and fifth, because most distorted guitar is genuinely ambiguous
between major and minor and a guessed third would be this tool inventing
information. That is the defect the whole project was built against.
"""
NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
FLATS = {'DB': 'C#', 'EB': 'D#', 'GB': 'F#', 'AB': 'G#', 'BB': 'A#'}
MAJOR_THIRD, MINOR_THIRD, FIFTH = 4, 3, 7
# How far the root must beat the second strongest pitch class before the bar
# gets a chord rather than a sustained root.
#
# An earlier draft thresholded on `strength`, the root's share of a normalised
# 12 bin chroma. That is not a confidence: its floor is 0.083 by construction,
# and at 0.12 the rule fired on 3 bars out of 163 across the whole corpus, so
# it was close to a no op wearing the name of a safeguard.
#
# 1.05, not 1.25. Measured across all three corpus fact sheets, 163 bars:
#
#   murder    45 bars  min 1.001  median 1.149  max 1.777
#   danger    65 bars  min 1.001  median 1.126  max 1.657
#   wrongturn 53 bars  min 1.001  median 1.183  max 3.144
#
# 1.25 sits ABOVE the median on every track and would turn 122 of 163 bars into
# sustained roots, 75 percent of the corpus. The constant it replaced fired on
# 3 bars of 163. Both were chosen without looking at the distribution and both
# are wrong, in opposite directions.
#
# 1.05 is set from what the number means rather than from a target hit rate. A
# margin of exactly 1.0 is a tie between two pitch classes, so 1.05 flags the
# bars where the winning root beat the runner up by less than five percent.
# That is the condition a sustained root is FOR.
#
# Task 3 Step 5 re-measures this against the real sheets, before Task 4 runs the
# command end to end. If the distribution argues for a different cut, use it and
# say why.
MIN_MARGIN = 1.05


class MidiEmitError(Exception):
    pass


def root_midi(name, octave=3):
    """MIDI note number for a root name, C4 as 60."""
    if not isinstance(name, str) or not name.strip():
        raise MidiEmitError('a chord root must be a note name')
    token = name.strip().upper()
    token = FLATS.get(token, token)
    if token not in NOTES:
        raise MidiEmitError(f'{name!r} is not a note name')
    value = NOTES.index(token) + (octave + 1) * 12
    if not 0 <= value <= 127:
        raise MidiEmitError(f'{name}{octave} falls outside the MIDI range')
    return value


def chord_pitches(entry, octave=3):
    """Root position block chord. No inversions, no invented thirds."""
    octave = max(-1, min(8, int(octave)))
    root = root_midi(entry['root'], octave)
    while root + FIFTH > 127:
        root -= 12
    while root < 0:
        root += 12
    if not entry.get('third_present'):
        return [root, root + FIFTH]
    quality = entry.get('quality')
    if quality == 'major':
        third = MAJOR_THIRD
    elif quality == 'minor':
        third = MINOR_THIRD
    else:
        return [root, root + FIFTH]
    return [root, root + third, root + FIFTH]
