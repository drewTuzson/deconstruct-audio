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
    near that candidate frequency, and reports it if its strength relative to
    the primary peak clears `threshold`.
    """
    if primary <= 0 or primary_strength <= 0 or len(tempi) == 0:
        return []
    found = []
    for value, label in RATIOS:
        if label == '1x':
            continue
        candidate = primary * value
        if candidate < tempi.min() or candidate > tempi.max():
            continue
        window = ((tempi >= candidate * (1 - COMPETING_WINDOW))
                  & (tempi <= candidate * (1 + COMPETING_WINDOW)))
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


def grade(methods, competing=None):
    """Turn per-method estimates into a family with an honest confidence.

    `competing` is optional tempogram evidence (see `competing_peaks`) for a
    metrical level none of `methods` disagrees about but that the tempogram's
    own shape still supports. Its presence must not be silently absorbed into
    KNOW just because beat_track and ioi, which share the tempogram's onset
    envelope, happened to inherit the same bias.
    """
    primary = methods['tempogram']
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
    competing = competing_peaks(u_tempi, u_strength, peak, peak_strength)
    return grade(methods, competing=competing)


if __name__ == '__main__':
    print(json.dumps(tempo_family(sys.argv[1]), indent=2))
