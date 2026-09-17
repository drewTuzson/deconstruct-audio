#!/usr/bin/env python3
"""The harmonic skeleton as MIDI.

Chord names in a text prompt are discarded by the target generator, which is
why this file exists: it is the channel that carries harmony when text cannot.

The emitter writes no pitch it did not measure. Where a third was not measured
it writes root and fifth, because most distorted guitar is genuinely ambiguous
between major and minor and a guessed third would be this tool inventing
information. That is the defect the whole project was built against.
"""
# mido at module level, unlike the deferred imports in deconstruct.py. That rule
# exists so every command, doctor included, still runs on an incomplete install,
# and doctor is what diagnoses that state. It does not apply here: this module
# cannot do anything at all without mido, so deferring the import only moves the
# same ImportError later and hides it from a reader of the file's head.
import math

import mido

NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
FLATS = {'DB': 'C#', 'EB': 'D#', 'GB': 'F#', 'AB': 'G#', 'BB': 'A#'}
MAJOR_THIRD, MINOR_THIRD, FIFTH = 4, 3, 7
# How far the root must beat the second strongest pitch class before the bar
# gets a chord rather than a sustained root.
#
# I ran the sweep in this file's plan across all three corpus fact sheets, 163
# bars, and these are those numbers rather than any inherited from a review:
#
#   track      bars   min    median   max      <1.05      <1.25
#   murder      45    1.001  1.149    1.777     8 (18%)   36 (80%)
#   danger      65    1.001  1.126    1.657    12 (19%)   52 (80%)
#   wrongturn   53    1.001  1.183    3.144    12 (23%)   34 (64%)
#   corpus     163    1.001  1.149    3.144    32 (20%)  122 (75%)
#
# That rules out both constants this one replaced. 1.25 sits above the median on
# every track and would turn three quarters of the corpus into sustained roots.
# The draft before it thresholded on `strength`, the root's share of a
# normalised 12 bin chroma, which is not a confidence at all: its floor is 0.083
# by construction, and at 0.12 it fired on 3 bars in 163, a safeguard that never
# fires wearing the name of one.
#
# What the sweep does NOT give is a cut. The distribution is smooth and has no
# cliff to sit in, so there is no value here that the data picks out. The
# constant therefore comes from what the number means: a margin of exactly 1.0
# is a tie between two pitch classes, and the corpus minimum is 1.001, so 1.05
# flags the bars where the winning root beat the runner up by less than five
# percent. That is the condition a sustained root is FOR. It fires on about one
# bar in five, which does real work without taking over the clip.
#
# `test_the_cut_sits_at_the_five_percent_it_documents` pins that meaning. Change
# this constant and that test fails, which is deliberate: the fixture's own bars
# only constrain it to (1.04, 1.38], so without the boundary test a constant as
# wrong as 1.30 would ship green.
#
# Reading the one-in-five rate as a fault in this threshold would be a mistake.
# All three tracks report harmonic_rhythm UNKNOWN because the measured root
# changes in every bar, so a fifth of bars being hard to call is a property of
# the chord axis on this material, not a threshold to loosen.
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
    # No range fixup after this point, and none is reachable. root_midi raises
    # unless 0 <= root <= 127, and the clamp above caps the octave at 8, so the
    # reachable roots run C-1 = 0 to B8 = 119 and the highest fifth is 126.
    # Checked against all 120: neither a low nor a high correction ever fired.
    # An untested fallback is a claim nobody checks, so it is gone rather than
    # left sitting there looking like it protects something.
    root = root_midi(entry['root'], octave)
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


def _window_value(entry, index, field):
    """One edge of a chord window, as a finite number or an authored error.

    Without this, a sheet carrying end_s as a string reaches float() and the
    ValueError lands in the top level handler, which prints "Details suppressed
    to protect secrets" for what is a data problem in a file the user supplied.
    That is the same failure read_facts already fixed one layer up, one field
    deeper. A NaN is worse than a string: it survives arithmetic, compares false
    against every bound, and would write a garbage delta time instead of raising.
    """
    raw = entry.get(field)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise MidiEmitError(
            f'bar {index} has {field}={raw!r}, which is not a number. Chord '
            f'window edges must be seconds, and the emitter will not guess one '
            f'it was not given.') from None
    if not math.isfinite(value):
        raise MidiEmitError(
            f'bar {index} has {field}={raw!r}, which is not a finite number of '
            f'seconds. The chord sequence in this fact sheet is not well formed.')
    return value


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
            start = int(round(_window_value(entry, index, 'start_s')
                               * ticks_per_second))
            end = int(round(_window_value(entry, index, 'end_s')
                            * ticks_per_second))
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
                # Bar 0 has no predecessor, so naming one would print "bar -1"
                # and send the reader looking for a window that does not exist.
                # It is reachable: a negative start_s lands here on the first bar.
                where = (f'before bar {index - 1} ended' if index
                         else 'before the start of the clip')
                raise MidiEmitError(
                    f'bar {index} starts at {entry.get("start_s")} s, {where}. '
                    f'Chord windows must not overlap, run backwards, or begin '
                    f'before zero.')
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
