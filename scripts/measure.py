#!/usr/bin/env python3
"""Local measurements and explicitly uncertain musical estimates."""
import json
import math
import re
import subprocess
import sys
import warnings
warnings.filterwarnings('ignore')
import librosa
import numpy as np


def measure(path):
    p = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-nostdin', '-i', path,
        '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True, check=True, timeout=300)
    summary = p.stderr.split('Summary:')[-1]
    def grab(pattern):
        m = re.search(pattern, summary)
        if not m:
            return None
        v = float(m.group(1))
        return v if math.isfinite(v) else None
    y, sr = librosa.load(path, sr=22050, mono=True)
    if len(y) == 0:
        raise ValueError('Empty audio')
    duration = len(y) / sr
    result = {'duration_s': round(duration, 3),
        'integrated_lufs': grab(r'I:\s+(-?[\d.]+|-?inf) LUFS'),
        'lra_lu': grab(r'LRA:\s+(-?[\d.]+|-?inf) LU'),
        'true_peak_dbtp': grab(r'Peak:\s+(-?[\d.]+|-?inf) dBFS'),
        'bpm_histogram': [], 'bpm_ambiguous': True, 'key_top3': [],
        'segment_boundaries_s': [], 'rms_db_per_4s': [], 'notes': []}
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    for start in np.arange(0, duration, 4):
        values = rms[(times >= start) & (times < start + 4)]
        if len(values):
            v = float(np.mean(values))
            result['rms_db_per_4s'].append([round(float(start), 2), round(20 * math.log10(v), 2) if v > 0 else None])
    if duration < 2 or np.max(np.abs(y)) < 1e-6:
        result['notes'].append('Too short or silent for credible tempo, key or section estimates.')
        return result
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    if np.max(onset) > 1e-5:
        tempo = librosa.feature.tempo(onset_envelope=onset, sr=sr, aggregate=None)
        vals, counts = np.unique(np.round(tempo[np.isfinite(tempo)]), return_counts=True)
        top = sorted(zip(counts, vals), reverse=True)[:5]
        result['bpm_histogram'] = [[int(v), int(c)] for c, v in top]
        result['bpm_ambiguous'] = not top or bool(len(top) > 1 and top[1][0] > 0.25 * top[0][0])
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    avg = chroma.mean(axis=1)
    major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ['C','C#','D','Eb','E','F','F#','G','Ab','A','Bb','B']
    candidates = []
    if np.std(avg) > 1e-8:
        for i, note in enumerate(notes):
            for label, profile in [('major', major), ('minor', minor)]:
                score = float(np.corrcoef(avg, np.roll(profile, i))[0, 1])
                if math.isfinite(score):
                    candidates.append((score, note + ' ' + label))
    result['key_top3'] = [[name, round(score, 3)] for score, name in sorted(candidates, reverse=True)[:3]]
    # Downsample features before clustering to keep long inputs bounded.
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    features = np.vstack([chroma, mfcc])
    stride = max(1, math.ceil(features.shape[1] / 2000))
    features = features[:, ::stride]
    features = (features - features.mean(axis=1, keepdims=True)) / (features.std(axis=1, keepdims=True) + 1e-8)
    k = min(8, max(1, int(duration // 15)), features.shape[1])
    if k > 1:
        boundaries = librosa.segment.agglomerative(features, k=k)
        result['segment_boundaries_s'] = [round(float(v), 2) for v in librosa.frames_to_time(boundaries * stride, sr=sr)]
    result['notes'].extend([
        'Tempo is an onset-pattern estimate; half/double tempo and rubato can mislead it.',
        'Key scores are correlations, not confidence probabilities. Major/minor templates may not fit this music.',
        'Section boundaries are clustering suggestions, not verified verse/chorus labels.',
        'RMS is a mono analysis proxy; loudness and peak use the decoded audio via ffmpeg.'
    ])
    return result

if __name__ == '__main__':
    print(json.dumps(measure(sys.argv[1]), indent=2, allow_nan=False))
