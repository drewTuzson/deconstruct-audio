#!/usr/bin/env python3
"""Tempo as a periodicity family. A single number hides metrical ambiguity."""
import json
import sys

import librosa
import numpy as np

RATIOS = ((0.5, '0.5x'), (0.75, '3/4'), (1.0, '1x'),
          (4.0 / 3.0, '4/3'), (1.5, '1.5x'), (2.0, '2x'), (3.0, '3x'))
TOLERANCE = 0.04


def classify_ratio(primary, other):
    if primary <= 0:
        return None
    r = other / primary
    for value, label in RATIOS:
        if abs(r - value) / value <= TOLERANCE:
            return label
    return None


def grade(methods):
    """Turn per-method estimates into a family with an honest confidence."""
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
    if unrelated:
        confidence = 'UNKNOWN'
        disagreement = ('Methods disagree by no simple ratio: '
                        + ', '.join(unrelated) + f' against tempogram {primary:.1f}')
    elif ratios:
        confidence = 'INFER'
        disagreement = ('Methods differ by a non-octave ratio: '
                        + ', '.join(sorted(set(ratios))))
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
    peak = float(tempi[usable][int(np.argmax(strength[usable]))])
    tracked, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr)
    times = librosa.frames_to_time(beats, sr=sr)
    methods = {'tempogram': peak, 'beat_track': float(np.atleast_1d(tracked)[0])}
    if len(times) > 2:
        methods['ioi'] = float(60.0 / np.median(np.diff(times)))
    return grade(methods)


if __name__ == '__main__':
    print(json.dumps(tempo_family(sys.argv[1]), indent=2))
