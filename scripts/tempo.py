#!/usr/bin/env python3
"""Tempo as a periodicity family. A single number hides metrical ambiguity."""
import json
import sys
import warnings

# measure.py runs as a captured subprocess, so its library warnings never
# reach a user. tempo runs in-process, which removed that isolation: librosa
# printed decoder warnings carrying absolute virtualenv paths straight to the
# terminal. Suppress before the import, the same way measure.py does.
warnings.filterwarnings('ignore')
import librosa  # noqa: E402
import numpy as np  # noqa: E402

RATIOS = ((0.5, '0.5x'), (0.75, '3/4'), (1.0, '1x'),
          (4.0 / 3.0, '4/3'), (1.5, '1.5x'), (2.0, '2x'), (3.0, '3x'))
TOLERANCE = 0.04

# Minimum tempogram strength a secondary peak must carry, relative to the
# primary peak's strength, to count as a competing metrical level. Measured
# against real audio: at tempos where the primary is correct (76, 80 BPM) every
# ratio candidate sits at ~0.0 relative strength (noise floor). At tempos where
# the tempogram peak is a half-tempo alias of the true tempo (120, 190, 192
# BPM) the true tempo's 2x candidate carries 0.73-0.89 relative strength. 0.15
# sits in the wide gap between those two populations with margin on both sides.
COMPETING_THRESHOLD = 0.15
COMPETING_WINDOW = 0.10


def _split(low_ratio, high_ratio):
    """The ratio equidistant from two neighbours in relative terms.

    Relative rather than absolute, because relative is how `classify_ratio`
    already measures closeness: the point where (r - a) / a equals (b - r) / b,
    which solves to the harmonic mean. Between 4/3 and 1.5 it falls at 1.41176.
    """
    return 2.0 / (1.0 / low_ratio + 1.0 / high_ratio)


def ratio_windows(window=COMPETING_WINDOW, ratios=RATIOS):
    """Each ratio's search interval, as (label, value, low, high) in ratio
    space, half-open on the right and provably disjoint.

    Every ratio gets its own +/- `window` band, clipped against a neighbour
    wherever two bands would otherwise overlap. The bands are not disjoint at
    0.10: 4/3 spans 1.2 to 1.4667 and 1.5x spans 1.35 to 1.65, so a peak at
    140 BPM against a primary of 100 fell inside both and was admitted twice
    under contradictory labels. Deduplicating on (ratio, bpm) in `grade`
    cannot catch that, because the whole point is that the ratios differ.

    Narrowing `window` would also remove the overlap, but only below 1/17
    (0.0588), the tightest constraint any adjacent pair imposes, which is the
    4/3 against 1.5x pair. That would nearly halve the search radius the
    octave protection depends on: the competing 2x peak that keeps a shared
    half-tempo alias out of KNOW is found by looking wide around the
    candidate, and a tempogram bin does not land exactly on 2x of the primary.
    Clipping leaves every band at full width except where two of them meet, so
    the octave check keeps its reach and a peak still gets exactly one label.

    The clip is computed from `window` rather than assumed from its present
    value, so widening the constant cannot reintroduce an overlap.
    """
    ordered = sorted(ratios)
    out = []
    for i, (value, label) in enumerate(ordered):
        low, high = value * (1 - window), value * (1 + window)
        if i > 0:
            low = max(low, _split(ordered[i - 1][0], value))
        if i + 1 < len(ordered):
            high = min(high, _split(value, ordered[i + 1][0]))
        out.append((label, value, low, high))
    return out


def classify_ratio(primary, other):
    if primary <= 0:
        return None
    r = other / primary
    for value, label in RATIOS:
        if abs(r - value) / value <= TOLERANCE:
            return label
    return None


def competing_peaks(tempi, strength, primary, primary_strength,
                     threshold=COMPETING_THRESHOLD):
    """Find secondary tempogram peaks at simple metrical ratios of the primary.

    `beat_track` and `ioi` are derived from the same onset envelope as the
    tempogram, so when all three "agree" that is not independent corroboration:
    an octave bias in the envelope shows up in all three together. The
    tempogram's own shape is the one place a competing metrical level can still
    be seen even when every method has locked onto the same wrong level. This
    walks each non-1x ratio of the primary, looks for a local strength maximum
    inside that ratio's interval, and reports it if its strength relative to
    the primary peak clears `threshold`.

    The intervals come from `ratio_windows`, which partitions ratio space so
    that no two of them overlap. Searching raw +/- COMPETING_WINDOW bands
    instead let one peak be filed under two contradictory labels at once.
    """
    if primary <= 0 or primary_strength <= 0 or len(tempi) == 0:
        return []
    tempi = np.asarray(tempi, dtype=float)
    strength = np.asarray(strength, dtype=float)
    # Ratio of every bin to the primary, so each bin is placed against the
    # partition once. A bin therefore belongs to exactly one ratio interval.
    ratio_of = tempi / primary
    found = []
    for label, value, low, high in ratio_windows():
        if label == '1x':
            continue
        candidate = primary * value
        if candidate < tempi.min() or candidate > tempi.max():
            continue
        window = (ratio_of >= low) & (ratio_of < high)
        if not np.any(window):
            continue
        window_idx = np.where(window)[0]
        local_idx = window_idx[int(np.argmax(strength[window_idx]))]
        local_bpm = float(tempi[local_idx])
        local_strength = float(strength[local_idx])
        relative = local_strength / primary_strength
        if relative >= threshold:
            found.append({'bpm': round(local_bpm, 1), 'ratio': label,
                          'relative_strength': round(relative, 3)})
    return found


def ratio_candidates_in_range(tempi, primary):
    """Non-1x metrical levels of `primary` this tempogram could actually show.

    "No competing level was found" and "no competing level could be looked
    for" are different answers, and only the first one earns KNOW.
    """
    if primary <= 0 or tempi.size == 0:
        return []
    low, high = float(tempi.min()), float(tempi.max())
    return [label for value, label in RATIOS
            if label != '1x' and low <= primary * value <= high]


def usable_tempogram(tempi, strength, primary, primary_strength):
    """Whether the supplied evidence can carry a competing-level check."""
    return bool(
        primary > 0 and primary_strength > 0
        and tempi.size >= 2 and strength.size == tempi.size
        and np.all(np.isfinite(tempi)) and np.all(np.isfinite(strength))
        and float(tempi.max()) > float(tempi.min())
        and ratio_candidates_in_range(tempi, primary))


def grade(methods, tempi, strength, primary_strength):
    """Turn per-method estimates into a family with an honest confidence.

    The tempogram evidence is required and `grade` runs `competing_peaks`
    itself, so no signature exists that grades `methods` without also checking
    the metrical level they may all have inherited together. `beat_track` and
    `ioi` derive from the same onset envelope as the tempogram, so their
    agreement is not independent corroboration: an octave bias in the envelope
    shows up in all three at once, and the tempogram's own secondary-peak
    structure is the one place it stays visible.

    Requiring the argument would not be enough on its own, because a caller
    satisfies a required parameter with None or an empty list just as quietly.
    Evidence that cannot support the check therefore does not fall back to the
    unprotected path; it caps confidence at INFER.
    """
    primary = methods['tempogram']
    try:
        tempi = np.asarray(tempi, dtype=float).ravel()
        strength = np.asarray(strength, dtype=float).ravel()
        primary_strength = float(primary_strength)
    except (TypeError, ValueError):
        tempi = strength = np.zeros(0, dtype=float)
        primary_strength = 0.0
    checked = usable_tempogram(tempi, strength, primary, primary_strength)
    competing = (competing_peaks(tempi, strength, primary, primary_strength)
                 if checked else [])
    family, unrelated, ratios = [], [], []
    for name, bpm in methods.items():
        if name == 'tempogram':
            continue
        label = classify_ratio(primary, bpm)
        if label is None:
            unrelated.append(f'{name} {bpm:.1f}')
        elif label != '1x':
            family.append({'bpm': round(bpm, 1), 'ratio': label, 'method': name})
            ratios.append(label)

    competing_notes = []
    if competing:
        seen = {(entry['ratio'], entry['bpm']) for entry in family}
        for peak in competing:
            key = (peak['ratio'], peak['bpm'])
            if key not in seen:
                family.append({'bpm': peak['bpm'], 'ratio': peak['ratio'],
                                'method': 'tempogram',
                                'relative_strength': peak['relative_strength']})
                seen.add(key)
            competing_notes.append(
                f"{peak['ratio']} at {peak['bpm']:.1f} BPM "
                f"(tempogram relative strength {peak['relative_strength']:.2f})")

    if unrelated:
        confidence = 'UNKNOWN'
        disagreement = ('Methods disagree by no simple ratio: '
                        + ', '.join(unrelated) + f' against tempogram {primary:.1f}')
    elif ratios:
        confidence = 'INFER'
        disagreement = ('Methods differ by a non-octave ratio: '
                        + ', '.join(sorted(set(ratios))))
    elif competing_notes:
        confidence = 'INFER'
        disagreement = ('Methods agree but the tempogram shows a competing '
                        'metrical level with meaningful support: '
                        + '; '.join(competing_notes))
    elif not checked:
        confidence = 'INFER'
        disagreement = ('Methods agree, but the supplied tempogram cannot carry '
                        'a competing-level check, so an octave or subdivision '
                        'error shared by every method cannot be ruled out.')
    else:
        confidence = 'KNOW'
        disagreement = None
    return {'primary': round(primary, 1), 'family': family,
            'methods': {k: round(v, 1) for k, v in methods.items()},
            'confidence': confidence, 'disagreement': disagreement}


def tempo_family(audio):
    y, sr = librosa.load(str(audio), sr=22050, mono=True)
    if len(y) == 0:
        raise ValueError('Empty audio')
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    tg = librosa.feature.tempogram(onset_envelope=onset, sr=sr)
    tempi = librosa.tempo_frequencies(tg.shape[0], sr=sr)
    strength = tg.mean(axis=1)
    usable = (tempi > 50) & (tempi < 220)
    u_tempi, u_strength = tempi[usable], strength[usable]
    peak_idx = int(np.argmax(u_strength))
    peak = float(u_tempi[peak_idx])
    peak_strength = float(u_strength[peak_idx])
    tracked, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr)
    times = librosa.frames_to_time(beats, sr=sr)
    methods = {'tempogram': peak, 'beat_track': float(np.atleast_1d(tracked)[0])}
    if len(times) > 2:
        methods['ioi'] = float(60.0 / np.median(np.diff(times)))
    return grade(methods, u_tempi, u_strength, peak_strength)


if __name__ == '__main__':
    print(json.dumps(tempo_family(sys.argv[1]), indent=2))
