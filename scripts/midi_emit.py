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


import mido

BEATS_PER_BAR = 4
VELOCITY = 80
LOW_CONFIDENCE_NOTE = ('chord confidence below threshold, so this bar carries a '
                       'sustained root rather than a harmony nothing measured')


def _require(sheet, axis):
    entry = sheet.get('facts', {}).get(axis)
    if not entry:
        raise MidiEmitError(
            f'the fact sheet carries no {axis}, and this emitter will not '
            f'substitute a default for a measurement that was never made')
    if entry.get('confidence') == 'UNKNOWN' or entry.get('value') in (None, [], {}):
        raise MidiEmitError(
            f'{axis} is graded {entry.get("confidence")} with value '
            f'{entry.get("value")!r}; there is nothing here to write')
    return entry['value']


def progression(sheet, octave=3, min_margin=MIN_MARGIN, ticks_per_beat=480,
                align=True):
    """One bar per measured chord, at the measured tempo, root position."""
    bpm = _require(sheet, 'tempo')
    sequence = _require(sheet, 'chords')
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        raise MidiEmitError(f'{bpm!r} is not a tempo')

    mid = mido.MidiFile(type=0, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    # The header tempo is nominal and the bar widths are measured, so on a
    # track whose beat grid breathes the two disagree: on Wrong Turn 28 of 52
    # bar windows deviate from the nominal bar. That is the right trade for an
    # anchor clip, whose job is to land on the same timeline as the reference,
    # but it means the header is a label rather than a description. A tempo map
    # would describe it; nothing in the pipeline needs one yet.
    track.append(mido.MetaMessage('set_tempo',
                                  tempo=mido.bpm2tempo(float(bpm)), time=0))
    track.append(mido.MetaMessage('time_signature', numerator=BEATS_PER_BAR,
                                  denominator=4, time=0))

    bar_ticks = BEATS_PER_BAR * ticks_per_beat
    # Align to the measured timeline. The first measured chord on the reference
    # track begins at 5.55 s, not at zero, and an earlier draft wrote it at
    # tick 0 while its self review claimed section timings were mirrored. What
    # was actually inherited was the chord ORDER. A clip handed to a generator
    # as a timeline anchor that starts 5.55 s early is not an anchor.
    ticks_per_second = ticks_per_beat * float(bpm) / 60.0

    # Each bar is placed AND sized from its own measured window, not written at
    # a uniform width from tick zero.
    #
    # Two separate defects came from the uniform version. It started the clip
    # 5.55 s early on the reference track, because the first measured chord does
    # not begin at zero. And it drifted: the bar windows come from a tracked
    # beat grid whose spacing follows the performance, so on Wrong Turn 28 of 52
    # interior windows deviate from the nominal bar and the clip finished 4.114
    # seconds late. A clip that ends four seconds late is no more an anchor than
    # one that starts five seconds early, and an earlier self review blamed that
    # drift on a single partial bar, which the window data contradicts.
    cursor = 0
    for index, entry in enumerate(sequence):
        margin = entry.get('root_margin')
        if margin is None or float(margin) < min_margin:
            pitches = [root_midi(entry['root'], octave)]
        else:
            pitches = chord_pitches(entry, octave)
        if align:
            start = int(round(float(entry.get('start_s') or 0.0) * ticks_per_second))
            end = int(round(float(entry.get('end_s') or 0.0) * ticks_per_second))
            width = end - start
            # Validate here, not later. max(1, ...) looks like a safe clamp and
            # is not: a zero width window leaves cursor one tick ahead of the
            # next start, progression returns happily with a negative delta
            # time in the message, and mido raises ValueError inside .save().
            # That lands in the top level handler, which prints
            # "ERROR: ValueError ... Details suppressed to protect secrets"
            # for what is a data problem in a file the user supplied. No real
            # sheet has such a window, 0 in 163 bars, which is exactly why the
            # failure would be rare and baffling.
            if width <= 0:
                raise MidiEmitError(
                    f'bar {index} spans {entry.get("start_s")} to '
                    f'{entry.get("end_s")} seconds, which is not a duration. '
                    f'The chord sequence in this fact sheet is not ordered or '
                    f'not well formed; the emitter will not invent a width.')
            if start < cursor:
                raise MidiEmitError(
                    f'bar {index} starts at {entry.get("start_s")} s, before '
                    f'bar {index - 1} ended. Chord windows must not overlap or '
                    f'run backwards.')
        else:
            start = index * bar_ticks
            width = bar_ticks
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message(
                'note_on', note=pitch, velocity=VELOCITY,
                time=(start - cursor) if offset == 0 else 0))
            if offset == 0:
                cursor = start
        for offset, pitch in enumerate(pitches):
            track.append(mido.Message('note_off', note=pitch, velocity=0,
                                      time=width if offset == 0 else 0))
        cursor = start + width
    track.append(mido.MetaMessage('end_of_track', time=0))
    return mid


def low_confidence_bars(sheet, min_margin=MIN_MARGIN):
    """Bar indices that carry a sustained root, so the fact sheet can name them."""
    sequence = sheet.get('facts', {}).get('chords', {}).get('value') or []
    out = []
    for i, e in enumerate(sequence):
        margin = e.get('root_margin')
        if margin is None or float(margin) < min_margin:
            out.append(i)
    return out
