#!/usr/bin/env python3
"""Harmonic measurement over band limited stems.

Band limiting to 150 to 2500 Hz moved chord template fit from 0.680 to 0.695
on the reference guitar stem and the decision margin by about 11 percent. The
gain is small and bounded: it removes bleed from other instruments and cannot
touch time frequency smearing inside the target's own range. It is here
because it is free and because declaring the band makes the assumption
explicit.
"""
import math

import librosa
import numpy as np
from scipy import signal

NOTES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                            2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                            2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Lowest string fundamental an octave down, because this table reads the BASS
# stem, and in this material the bass doubles the lowest guitar string an
# octave below it. drop C# on a guitar is C#2 at 69.30 Hz; the entry below is
# C#1 at 34.65 Hz, which is what the bass actually plays.
#
# The guitar stem cannot be used for this. Its low band yin output is dominated
# by octave errors: on the reference track its strongest bin is F#1 at 17.0
# percent of frames, an octave below the musically real F#2. Revision 1 graded
# tuning KNOW when both stems agreed, and both stems agreed on the wrong answer.
#
# D standard is deliberately absent. Its lowest string is D, the same pitch as
# drop D's, so no measurement of a lowest fundamental can separate them, and
# revision 1's entry for it evaluated to 0.024 cents from standard E.
TUNINGS = {
    'standard E': 41.20,
    'Eb standard': 38.89,
    'drop D': 36.71,
    'drop C#': 34.65,
    'drop C': 32.70,
    'drop B': 30.87,
    'drop A#': 29.14,
}
# A semitone bin must hold this share of voiced frames to count as a played
# string rather than noise. Set by a sweep across all three corpus bass stems,
# not by the reference track alone. Revision 2 used 0.02, justified on the
# reference histogram only, and that value loses the axis entirely on Wrong
# Turn: a 2.6 percent sub bass artifact at 25.96 Hz clears the floor, sits 200
# cents from every table entry, and takes the whole axis to None while C#1 with
# 21.19 percent support sits four semitones above it.
#
#   floor   Murder She Wrote   Wrong Turn      The Danger of Caring
#   0.020   drop C# 34.65      None 25.96      drop C# 34.65
#   0.030   drop C# 34.65      drop C# 34.65   drop C# 34.65
#   0.040   drop C# 34.65      drop C# 34.65   drop C# 34.65
#   0.050   drop C# 34.65      drop C# 34.65   standard E 41.20
#   0.080   drop D  36.71      drop C# 34.65   standard E 41.20
#
# The three track agreement window is 0.03 to 0.04. 0.035 is its middle.
SUPPORT_FLOOR = 0.035
MAX_CENTS = 60.0
SILENCE = 1e-6


def band_limit(y, sr, low, high):
    """A fourth order Butterworth band pass, clamped to the usable range."""
    nyquist = sr / 2.0
    low = max(1.0, float(low))
    high = min(float(high), nyquist * 0.99)
    if low >= high:
        return np.asarray(y, dtype=np.float32)
    sos = signal.butter(4, [low / nyquist, high / nyquist], btype='band',
                        output='sos')
    return signal.sosfilt(sos, np.asarray(y, dtype=np.float64)).astype(np.float32)


def _summed(signals):
    stacked = [np.asarray(s, dtype=np.float32) for s in signals if s is not None]
    if not stacked:
        return None
    length = max(len(s) for s in stacked)
    out = np.zeros(length, dtype=np.float32)
    for s in stacked:
        out[:len(s)] += s
    return out


def key_estimate(signals, sr, low=150, high=2500):
    """Correlate a summed, band limited chroma against major and minor templates.

    These are correlations against templates, not probabilities. Music built on
    other systems will not fit them, which is why the margin travels with the
    answer instead of being discarded.
    """
    summed = _summed(signals)
    if summed is None:
        return {'key': None, 'scores': [], 'margin': 0.0}
    y = band_limit(summed, sr, low, high)
    if np.max(np.abs(y)) < SILENCE:
        return {'key': None, 'scores': [], 'margin': 0.0}
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    avg = chroma.mean(axis=1)
    if np.std(avg) < 1e-8:
        return {'key': None, 'scores': [], 'margin': 0.0}
    scored = []
    for i, note in enumerate(NOTES):
        for label, profile in (('major', KRUMHANSL_MAJOR),
                               ('minor', KRUMHANSL_MINOR)):
            value = float(np.corrcoef(avg, np.roll(profile, i))[0, 1])
            if math.isfinite(value):
                scored.append((value, f'{note} {label}'))
    if not scored:
        return {'key': None, 'scores': [], 'margin': 0.0}
    scored.sort(reverse=True)
    margin = scored[0][0] - scored[1][0] if len(scored) > 1 else 0.0
    return {'key': scored[0][1],
            'scores': [[name, round(v, 4)] for v, name in scored[:5]],
            'margin': round(float(margin), 4)}


def tuning_estimate(y, sr, high=200.0, floor=SUPPORT_FLOOR):
    """Name the tuning from the lowest SUSTAINED semitone in the bass.

    Sustained is the whole point. A single low transient is a kick drum
    bleeding through, not a string, so the estimate bins the pitch track to
    semitones and takes the lowest bin that holds at least `floor` of the
    voiced frames.
    """
    y = np.asarray(y, dtype=np.float32)
    empty = {'tuning': None, 'lowest_hz': None, 'support': None,
             'margin_cents': None, 'skipped_hz': None, 'candidates': []}
    if len(y) == 0 or np.max(np.abs(y)) < SILENCE:
        return empty
    low = band_limit(y, sr, 25.0, high)
    f0 = librosa.yin(low.astype(np.float64), fmin=25.0, fmax=high, sr=sr,
                     frame_length=4096)
    f0 = f0[np.isfinite(f0)]
    f0 = f0[(f0 > 25.0) & (f0 < high)]
    if len(f0) < 32:
        return empty
    bins = np.round(librosa.hz_to_midi(f0)).astype(int)
    values, counts = np.unique(bins, return_counts=True)
    share = counts / counts.sum()
    supported = sorted(int(v) for v in values[share >= floor])
    if not supported:
        return empty
    # Walk up. One sub bass artifact should not take the whole axis to None
    # when a bin with real support sits a few semitones above it. Each
    # candidate is tried against the table in pitch order and the first that
    # lands within MAX_CENTS wins, so a skipped bin is a bin no tuning
    # explains rather than a bin that was ignored.
    # Every supported bin that the table can name, in pitch order, with its
    # support. The lowest still wins, but the alternatives travel with the
    # answer instead of vanishing.
    #
    # This is the failure the walk up traded for: the table is a contiguous
    # chromatic run from MIDI 22 to 28, so a yin sub octave error on a bass
    # note anywhere from A#1 to E2 lands INSIDE it, is named with a margin near
    # zero cents, and skips nothing. The real string with six times the support
    # two semitones up never appears. Returning the whole supported set is what
    # makes that visible to a reader and to the note on the fact.
    skipped, candidates = [], []
    for midi in supported:
        lowest = float(librosa.midi_to_hz(midi))
        support = float(share[values == midi][0])
        ranked = sorted((abs(1200 * math.log2(lowest / hz)), name)
                        for name, hz in TUNINGS.items())
        best_cents, best_name = ranked[0]
        if best_cents <= MAX_CENTS:
            candidates.append({'tuning': best_name, 'hz': round(lowest, 2),
                               'support': round(support, 4),
                               'cents': round(best_cents, 1)})
        else:
            skipped.append(round(lowest, 2))
    if not candidates:
        return {'tuning': None, 'lowest_hz': skipped[0] if skipped else None,
                'support': None, 'margin_cents': None, 'skipped_hz': skipped,
                'candidates': []}
    chosen = candidates[0]
    strongest = max(candidates, key=lambda c: c['support'])
    return {'tuning': chosen['tuning'], 'lowest_hz': chosen['hz'],
            'support': chosen['support'], 'margin_cents': chosen['cents'],
            'skipped_hz': skipped or None, 'candidates': candidates,
            'strongest_support_tuning': strongest['tuning'],
            'strongest_support': strongest['support']}
