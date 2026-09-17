#!/usr/bin/env python3
"""The fact sheet. Every number carries the method that produced it.

This module exists because the pipeline it replaces emitted bare numbers from
a language model and three passes on one track returned three tempos. A fact
that cannot say how it was measured is not a fact, so fact() raises rather
than emitting one.
"""
import math
import re
from pathlib import Path

import stems

CONFIDENCE = ('KNOW', 'INFER', 'UNKNOWN')
ACTIONABLE = ('direct', 'indirect', 'midi_only', 'none')
AUDIO_SUFFIXES = ('.wav', '.flac', '.mp3', '.aif', '.aiff')


class FactError(Exception):
    pass


class StemAdoptionError(Exception):
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


def _match(names, pattern):
    return {n: [p for p in names if pattern(n, p.name.lower())]
            for n in stems.STEM_NAMES}


def adopt_stems(folder):
    """Resolve an existing folder of six stems, however its files are named.

    Two passes, tagged first, resolved PER STEM rather than per folder. A name
    carrying `(Drums)` is claiming to be the drums stem; a name that merely
    contains the word might be the source mix, a scratch take, or a track
    called Another Brother. So a stem with a tagged claim uses it and never
    consults the loose pass, which is what keeps `Another Brother_(Other).wav`
    from reading as two claims on `other`, and what makes a tagged name beat a
    stray loose one.

    Per stem is the whole point. Deciding this once for the folder, on whether
    ANY file used the tagged form, meant a single `(Drums)` file sitting beside
    five perfectly good plain-name stems switched the entire folder to tagged
    matching and reported those five as missing.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise StemAdoptionError(f'Not a folder: {folder}')
    audio = [p for p in sorted(folder.iterdir())
             if p.suffix.lower() in AUDIO_SUFFIXES]
    if not audio:
        raise StemAdoptionError(f'No audio files in {folder}')

    tagged = _match(audio, lambda n, low: f'({n})' in low)
    loose = _match(audio, lambda n, low: re.search(rf'\b{n}\b', low) is not None)
    found, matched_by = {}, {}
    for name in stems.STEM_NAMES:
        found[name] = tagged[name] or loose[name]
        matched_by[name] = 'tagged' if tagged[name] else 'loose'

    missing = sorted(n for n, v in found.items() if not v)
    if missing:
        raise StemAdoptionError(
            f'{folder} yields no stem for: {", ".join(missing)}. Each stem is '
            f'matched by a parenthesised tag such as (Drums) where one exists, '
            f'and otherwise by the stem name appearing as a whole word in the '
            f'filename. A six stem folder is required; a partial one would '
            f'produce a partial fact sheet, which is worse than none.')
    ambiguous = sorted(n for n, v in found.items() if len(v) > 1)
    if ambiguous:
        detail = '; '.join(
            f'{n} (by {matched_by[n]} name): '
            + ', '.join(p.name for p in found[n]) for n in ambiguous)
        raise StemAdoptionError(
            f'More than one file claims these stems in {folder}: {detail}. '
            f'Rename or move the extras rather than letting the sheet pick one.')
    return {n: v[0] for n, v in found.items()}


import datetime as _dt
import hashlib

import librosa
import numpy as np

import chords as chords_mod
import measure as measure_mod
import stems as stems_mod
import tempo as tempo_mod

SCHEMA = 'deconstruct-audio/facts/1'
SR = 22050
LOW_END_HZ = 150.0
AIR_HZ = 5000.0
N_FFT = 2048
# A stem counts as present when its RMS is within this many dB of the loudest
# stem. Relative, not absolute, so it does not move with mastering level.
#
# Swept across all three corpus tracks, not just the reference. At 30 dB the
# `other` stem on Wrong Turn sits 0.62 dB from flipping to absent, and this
# axis is suno_actionable direct, so a flip changes what the prompt says the
# track contains. At 35 dB every `other` stem clears by at least 2.2 dB and
# both piano stems still read absent by at least 4.2 dB, which is correct:
# neither track has a piano.
PRESENCE_DB = 35.0
# Per second window threshold for the intro's arrangement density curve. The
# intro rule below returns the same answer at -35, -40 and -45 on the reference
# track, so this constant is not load bearing.
ACTIVE_DB = -40.0
INTRO_SNAP_S = 4.0
# An intro lives near the beginning. Without a window, a post breakdown re
# entry two thirds of the way through a track competes with it and wins.
# The working density of the mix, and how long it must be held to count.
#
# The percentile is 90, not the median and not 75. Any percentile at or below
# the share of the track the intro occupies makes the intro's own density the
# working density, and the no-intro guard then fires on exactly the tracks with
# the longest intros. The median failed at 50 percent, 75 failed on a track
# that is 77 percent sparse, 90 and 95 both pass every shape tested.
#
# The hold exists because a single touch is not an arrangement. A one second
# full band stab before the real entry is a genre commonplace, and a rule that
# ends the intro at the first window merely REACHING the working density is
# fooled by it in the same way the previous largest step rule was fooled by a
# large early step.
#
# Both constants are deliberately far from any edge: the rule returns the same
# answer on all three corpus tracks at percentile 90 and 95 and at hold 2, 3, 4
# and 5. A rule whose answer does not move across that range is reading the
# arrangement rather than its own constants.
INTRO_TYPICAL_PERCENTILE = 90
INTRO_HOLD = 3
# The winning beat grouping must beat the runner up by this ratio. Measured: on
# the reference track 3 scores 16526.6 against 4 at 14573.1, a ratio of 1.134,
# and the axis reads 3 on two of three tracks in a genre whose prior is
# overwhelmingly 4/4. Below this margin the axis says UNKNOWN rather than
# shipping a coin toss into a prompt as a statement.
METER_MARGIN = 1.15

# How many tonic rooted bars must carry a measured third before the mode half
# of the key cross check is allowed to support a KNOW. Measured: across 163
# corpus bars only five are tonic rooted AND carry a third, so on this material
# the check abstains on two tracks of three and caps the grade on the third.
# That is the intended behaviour: absent evidence caps, it does not promote.
MODE_EVIDENCE_MIN = 4

SECTION_COUNT_NOTE = (
    'Sixteen structure segmentation methods were run at one fixed '
    'configuration and none generalise across the three track corpus. The best '
    'candidate returns 7, 6 and 10, matches 4 of 6 known boundaries, and was '
    'selected by noticing which row of a table hit the known answer, which is '
    'selection on the one track that has one. Reporting a count that is about '
    'half likely to be wrong is worse than reporting none, because a stated '
    'number invites downstream use that a missing one does not. Boundaries are '
    'emitted separately. Note that the boundary hit rates in that study were '
    'scored against this pipeline\'s own incumbent boundaries rather than human '
    'annotation, because the known ground truth is a count and not a boundary '
    'list, so they measure agreement with the incumbent rather than correctness.')


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _load(path, sr=SR):
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y


def _rms_db(y):
    if len(y) == 0:
        return float('-inf')
    value = float(np.sqrt(np.mean(np.asarray(y, dtype=np.float64) ** 2)))
    return 20.0 * math.log10(value) if value > 0 else float('-inf')


def _beat_times(drums, sr, bpm):
    """A beat grid at the tempo the tempo family already chose.

    Seeding matters. An unseeded tracker picks its own metrical level, and on
    this corpus it lands on different levels for different tracks, reporting
    152 BPM for one stated at about 103. The tempo family has already made
    that decision with three methods and a published grade; re-deciding it
    here would silently override it with one method and no grade.
    """
    if not bpm or bpm <= 0:
        return np.array([])
    onset = librosa.onset.onset_strength(y=drums, sr=sr)
    _, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr,
                                       bpm=float(bpm), trim=False)
    return librosa.frames_to_time(beats, sr=sr)


def _holds(density, index, typical, hold=INTRO_HOLD):
    """True when the arrangement reaches the working density here and stays.

    One window at the working density is not an arrangement. It is a stab, a
    cymbal swell, or a sample. The hold is what separates the two, and it is
    the single change that closed four consecutive intro failures.

    The refusal at the end of the array is not a detail. An earlier version
    truncated the range with min(len(density), index + hold), so at the last
    index the range had length one and a SINGLE window satisfied a predicate
    whose entire purpose is to reject single windows. A track ending on a full
    band hit then reported almost its whole length as intro, and an identical
    two window run was rejected mid track and accepted at the end.

    The trade is deliberate and correct: an arrangement that arrives in the
    last two seconds of a track is not an intro ending.
    """
    if index + hold > len(density):
        return False
    return all(density[j] >= typical for j in range(index, index + hold))


def _most_common_root(roots):
    """The most frequent chord root, ties broken by pitch name, or None.

    `sorted` is load bearing and is not decoration. `max(set(roots), ...)`
    iterates a set, whose order depends on the interpreter's hash seed, so on
    a track where two roots tie on count the winner changed from process to
    process. Measured across eight seeds on a tied histogram it returned
    E,E,E,E,A,A,E,A.

    This value reaches the key fact's grade and its note, both of which are
    written into facts.json for a person to read, so the instability was
    emitted content rather than an internal detail.

    The rerun gate cannot see this. corpus_check runs both passes inside one
    process, which means both share one hash seed, so it reports STABLE=yes
    for a value that is not stable between runs. A gate blind to the very
    thing it exists to catch is worth closing even while no corpus track
    trips it, and the reference track is one bar away from a tie.
    """
    if not roots:
        return None
    return max(sorted(set(roots)), key=roots.count)


def _register(y, sr, fmin, fmax, stem, band, actionable):
    """Median and spread of a pitch track, in MIDI note numbers.

    A helper, not an axis builder. The two register axes wrap it.
    """
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-6:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', actionable,
                    band_hz=band, note='stem is silent')
    f0 = librosa.yin(y.astype(np.float64), fmin=fmin, fmax=fmax, sr=sr)
    f0 = f0[np.isfinite(f0) & (f0 > fmin) & (f0 < fmax)]
    if len(f0) < 16:
        return fact(None, 'midi', stem, ['yin'], 'UNKNOWN', actionable,
                    band_hz=band, note='no stable pitch track')
    midi = librosa.hz_to_midi(f0)
    value = {'median_midi': round(float(np.median(midi)), 2),
             'p10_midi': round(float(np.percentile(midi, 10)), 2),
             'p90_midi': round(float(np.percentile(midi, 90)), 2)}
    return fact(value, 'midi', stem, ['yin'], 'INFER', actionable, band_hz=band,
                note='single method pitch track over a separated stem, and yin '
                     'octave errors are common in this band')


def _tempo_fact(paths, loaded, mix, sr, local, built):
    result = tempo_mod.tempo_family(paths['drums'])
    note = result.get('disagreement')
    return fact(result['primary'], 'bpm', 'drums',
                ['tempogram-peak', 'beat-track', 'inter-onset'],
                result['confidence'], 'direct', note=note)


def _instrumentation_fact(paths, loaded, mix, sr, local, built):
    levels = {name: _rms_db(y) for name, y in loaded.items()}
    finite = [v for v in levels.values() if math.isfinite(v)]
    loudest = max(finite) if finite else float('-inf')
    value = {name: {'rms_db': (round(db, 2) if math.isfinite(db) else None),
                    'active': bool(math.isfinite(db) and db >= loudest - PRESENCE_DB)}
             for name, db in levels.items()}
    present = sorted(n for n, v in value.items() if v['active'])
    # INFER, not KNOW. PRESENCE_DB is a chosen parameter, and moving it from
    # 30 to 35 changed which stems this axis reports on two of three corpus
    # tracks. A declared parameter is not the same as no parameter.
    return fact(value, 'dbfs', 'all', ['stem-rms'], 'INFER', 'direct',
                note=f'present: {", ".join(present)}. A stem more than '
                     f'{PRESENCE_DB:g} dB below the loudest reads absent, which '
                     f'is a measurement of the arrangement, not a separation '
                     f'failure.')


def _key_fact(paths, loaded, mix, sr, local, built):
    result = chords_mod.key_estimate([loaded['guitar'], loaded['bass']], sr)
    band = [150, 2500]
    if result['key'] is None:
        return fact(None, 'name', 'guitar+bass', ['chroma-cqt-krumhansl'],
                    'UNKNOWN', 'direct', band_hz=band,
                    note='no key resolved')
    # The cross check, restored. Revision 1 required the margin AND agreement
    # with the chord sequence's most common root; revision 2 dropped the second
    # half and graded on margin alone. Measured cost of dropping it: Wrong Turn
    # scores C# minor at margin 0.0584 while its most common chord root is E,
    # its relative major, and that would have been graded KNOW. The check was
    # doing real work.
    sequence = (built.get('chords') or {}).get('value') or []
    roots = [e['root'] for e in sequence]
    common = _most_common_root(roots)
    tonic = result['key'].split()[0]
    agrees = common is not None and common == tonic
    # The mode check. The tonic check above validates WHICH note is home; it
    # cannot see major against minor at all. Measured across the corpus, only
    # five bars in 163 are rooted on their tonic and carry a measured third,
    # and on the one track where that evidence exists it contradicts the
    # reported mode three to nil.
    #
    # So the mode evidence caps the grade and never changes the answer. It can
    # only lower KNOW to INFER. Acting on three bars filtered through
    # THIRD_RATIO, a constant that has never seen a distorted guitar, would be
    # the tail wagging the dog.
    mode = result['key'].split()[-1]
    tonic_thirds = [e['quality'] for e in sequence
                    if e['root'] == tonic and e.get('third_present')]
    mode_agrees = (len(tonic_thirds) >= MODE_EVIDENCE_MIN
                   and tonic_thirds.count(mode) * 2 > len(tonic_thirds))
    grade = 'KNOW' if (result['margin'] >= 0.05 and agrees and mode_agrees) \
        else 'INFER'
    runner = result['scores'][1][0] if len(result['scores']) > 1 else 'none'
    return fact(result['key'], 'name', 'guitar+bass',
                ['chroma-cqt-krumhansl', 'chord-root-histogram'], grade,
                'direct', band_hz=band,
                note=f'margin {result["margin"]} over the runner up {runner}; '
                     f'most common chord root {common}, tonic {tonic}, '
                     f'{"agree" if agrees else "disagree"}; '
                     f'{len(tonic_thirds)} tonic rooted bars carry a third '
                     f'({tonic_thirds.count(mode)} of them {mode}), which is '
                     f'{"enough to support" if mode_agrees else "not enough to support"} '
                     f'the mode. These are template correlations, not '
                     f'probabilities, and the mode evidence can only lower this '
                     f'grade, never change the key.')


def _tuning_fact(paths, loaded, mix, sr, local, built):
    result = chords_mod.tuning_estimate(loaded['bass'], sr)
    band = [25, 200]
    if result['tuning'] is None:
        return fact(None, 'name', 'bass', ['yin-semitone-histogram'],
                    'UNKNOWN', 'direct', band_hz=band,
                    note=f'no semitone bin cleared the '
                         f'{chords_mod.SUPPORT_FLOOR:g} support floor')
    return fact(result['tuning'], 'name', 'bass', ['yin-semitone-histogram'],
                'INFER', 'direct', band_hz=band,
                note=f'lowest sustained semitone {result["lowest_hz"]} Hz with '
                     f'{result["support"]:.3f} frame support, '
                     f'{result["margin_cents"]} cents from the template. '
                     f'Every supported candidate: '
                     f'{", ".join(str(c) for c in result["candidates"])}. '
                     f'The best supported was '
                     f'{result["strongest_support_tuning"]} at '
                     f'{result["strongest_support"]:.3f}. Read from the bass '
                     f'only: the guitar stem is dominated by yin octave errors '
                     f'in this band and cannot corroborate it. A sub octave '
                     f'artifact landing inside the table is named with a small '
                     f'cents margin and is only visible in this list.')


def _chords_fact(paths, loaded, mix, sr, local, built):
    band = [150, 2500]
    tempo_entry = built.get('tempo') or {}
    beats = _beat_times(loaded['drums'], sr, tempo_entry.get('value'))
    if not len(beats):
        return fact(None, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                    'UNKNOWN', 'midi_only', band_hz=band,
                    note='no beat grid, so no bar windows to read chords over')
    sequence = chords_mod.chord_sequence(
        [loaded['guitar'], loaded['bass']], sr, beats)
    if not sequence:
        return fact(None, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                    'UNKNOWN', 'midi_only', band_hz=band,
                    note='no chord resolved in any bar window')
    powers = sum(1 for e in sequence if e['quality'] == 'power')
    return fact(sequence, 'sequence', 'guitar+bass', ['beat-sync-chroma'],
                'INFER', 'midi_only', band_hz=band,
                note=f'{len(sequence)} bars, {powers} with no measured third. '
                     f'Chord names are midi_only: text prompts discard them. '
                     f'root_share is a normalised chroma share with a 0.083 '
                     f'floor and is not a confidence; root_margin is.')


def _harmonic_rhythm_fact(paths, loaded, mix, sr, local, built):
    band = [150, 2500]
    sequence = (built.get('chords') or {}).get('value')
    if not sequence:
        return fact(None, 'bars', 'guitar+bass', ['chord-run-length'],
                    'UNKNOWN', 'indirect', band_hz=band,
                    note='no chord sequence to measure a rate over')
    result = chords_mod.harmonic_rhythm(sequence)
    if result['median_chord_bars'] == 1.0:
        # 1.0 is the FLOOR of this statistic. A run length is an integer of at
        # least 1, so a median of 1.0 means the measured root changed in every
        # single bar. An axis reporting its own floor across all of its
        # evidence has measured noise, not harmony, and all three corpus tracks
        # report exactly 1.0. Corroborated independently by the median
        # root_margin sitting near 1.13, meaning the winning pitch class barely
        # beat the runner up.
        return fact(None, 'bars', 'guitar+bass', ['chord-run-length'],
                    'UNKNOWN', 'indirect', band_hz=band,
                    note='the measured root changed in every bar, which is the '
                         'floor of this statistic rather than a harmonic rhythm')
    return fact(result, 'bars', 'guitar+bass', ['chord-run-length'],
                'INFER', 'indirect', band_hz=band,
                note='inherits the chord sequence\'s own uncertainty')


def _section_boundaries_fact(paths, loaded, mix, sr, local, built):
    boundaries = [float(t) for t in local.get('segment_boundaries_s') or []]
    if not boundaries:
        return fact(None, 'seconds', 'mix', ['agglomerative-clustering'],
                    'UNKNOWN', 'none', note='no boundaries resolved')
    return fact(boundaries, 'seconds', 'mix', ['agglomerative-clustering'],
                'INFER', 'direct',
                note='clustering suggestions, not verified verses and choruses')


def _section_count_fact(paths, loaded, mix, sr, local, built):
    return fact(None, 'count', 'mix',
                ['agglomerative-clustering', 'laplacian-segmentation',
                 'checkerboard-novelty', 'dp-bic-changepoint'],
                'UNKNOWN', 'none', note=SECTION_COUNT_NOTE)


def _intro_fact(paths, loaded, mix, sr, local, built):
    """How long before the arrangement reaches and holds its working density.

    Five versions of this axis have shipped a confidently wrong answer, each in
    a different direction, and the corpus passed every one of them. What the
    current rule is made of, and what each part is for:

    A working density taken at the 90th percentile, not the median. Any
    percentile at or below the share of the track the intro occupies makes the
    intro its own working density, and the no intro guard then fires on exactly
    the tracks with the longest intros. The median failed that at 50 percent
    and the 75th percentile failed on a track that is 77 percent sparse.

    A track may have no intro at all. The Danger of Caring is at density 5 in
    its first second and never rises again. An earlier version reported 123.41 s
    on that 205.8 s track, and graded it KNOW because a section boundary
    happened to sit 0.41 s away.

    Reaching the working density is not enough; it must be HELD. A one second
    full band stab before the real entry is a genre commonplace and defeats a
    single touch, exactly as a large early step defeated the version before.

    No search window. Under a first reach rule the first qualifying index is by
    construction the earliest, so a window can only turn a correct answer into
    UNKNOWN. It cost four of them and bought nothing.

    The grade is INFER in every branch, including when a section boundary
    confirms the position. Two methods agreeing on a position is not cross
    validation of a length.
    """
    window = int(sr)
    count = min(len(y) for y in loaded.values()) // window
    if count < 3:
        return fact(None, 'seconds', 'mix', ['stem-density-step'],
                    'UNKNOWN', 'direct', note='too short to read a density step')
    density = [sum(1 for y in loaded.values()
                   if _rms_db(y[i * window:(i + 1) * window]) > ACTIVE_DB)
               for i in range(count)]
    typical = float(np.percentile(np.asarray(density), INTRO_TYPICAL_PERCENTILE))
    if typical <= 0:
        return fact(None, 'seconds', 'mix', ['stem-density-step'], 'UNKNOWN',
                    'direct',
                    note='the working density of this mix is zero stems, which '
                         'means nothing was measured rather than that the intro '
                         'is zero seconds long')

    if _holds(density, 0, typical):
        return fact(0.0, 'seconds', 'mix', ['stem-density-step'], 'INFER',
                    'direct',
                    note=f'the arrangement is already at its working density of '
                         f'{typical:g} stems and holds it from the first window, '
                         f'so there is no intro to measure')

    # The first window that reaches the working density AND HOLDS it. Not the
    # largest step, which took the earliest of equal steps and so ended a 30 s
    # fade in at 5 s. Not the first window merely to touch it, which a one
    # second full band stab before the real entry defeats.
    #
    # There is no search window. An earlier version limited the search to the
    # first 60 s or 40 percent of the track, which under a first-reach rule can
    # only turn a correct answer into UNKNOWN, since the first qualifying index
    # is by construction the earliest one. It cost four correct answers and
    # bought nothing.
    reached = [i for i in range(count) if _holds(density, i, typical)]
    if not reached:
        return fact(None, 'seconds', 'mix', ['stem-density-step'], 'UNKNOWN',
                    'direct',
                    note=f'the arrangement never reaches and holds its working '
                         f'density of {typical:g} stems')
    raw = float(reached[0])
    size = int(density[reached[0]] - density[0])
    boundaries = (built.get('section_boundaries') or {}).get('value') or []
    near = [b for b in boundaries if abs(b - raw) <= INTRO_SNAP_S]
    if near:
        snapped = min(near, key=lambda b: abs(b - raw))
        return fact(round(float(snapped), 2), 'seconds', 'mix',
                    ['stem-density-step', 'agglomerative-clustering'],
                    'INFER', 'direct',
                    note=f'density rose by {size} stems at {raw:.0f} s out of a '
                         f'passage below the typical {typical:g}, and a section '
                         f'boundary sits at {snapped:.2f} s. Two methods agreeing '
                         f'on a position is not cross validation of a length, so '
                         f'this stays INFER.')
    return fact(raw, 'seconds', 'mix', ['stem-density-step'], 'INFER', 'direct',
                note=f'density rose by {size} stems at {raw:.0f} s, with no '
                     f'section boundary within {INTRO_SNAP_S:g} s to confirm it')


def _loudness_fact(paths, loaded, mix, sr, local, built):
    value = {'integrated_lufs': local.get('integrated_lufs'),
             'lra_lu': local.get('lra_lu'),
             'true_peak_dbtp': local.get('true_peak_dbtp')}
    if value['lra_lu'] is None:
        return fact(None, 'lu', 'mix', ['ebur128'], 'UNKNOWN', 'indirect',
                    note='ffmpeg returned no loudness summary')
    # KNOW requires all three. This is the only axis the narrowed spec clause
    # still admits to KNOW, on the grounds that BS.1770-4 fixes the gating,
    # the filter, the window and the aggregation, so a second method would
    # return the same numbers by construction. That argument is about a
    # COMPLETE reading. Grading the whole three property fact KNOW while two
    # of them are null claims the standard's authority for values the standard
    # never produced, and it does so on the one axis where an unearned KNOW
    # has nothing above it to catch the mistake.
    missing = sorted(k for k, v in value.items() if v is None)
    if missing:
        return fact(value, 'lu', 'mix', ['ebur128'], 'INFER', 'indirect',
                    note=f'ITU-R BS.1770-4 via ffmpeg, but ffmpeg returned no '
                         f'{", ".join(missing)}. An incomplete reading is one '
                         f'method with a gap in it, so this is INFER; the '
                         f'properties present are still the standard\'s own.')
    return fact(value, 'lu', 'mix', ['ebur128'], 'KNOW', 'indirect',
                note='ITU-R BS.1770-4 via ffmpeg, the one axis here where a '
                     'single method is genuinely authoritative. All three '
                     'properties are present, which is what the grade claims.')


def _spectral_fact(paths, loaded, mix, sr, local, built):
    S = np.abs(librosa.stft(mix, n_fft=N_FFT))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    per_frame = S.sum(axis=0)
    per_frame[per_frame == 0] = 1.0
    low = float(np.mean(S[freqs < LOW_END_HZ].sum(axis=0) / per_frame)) * 100
    air = float(np.mean(S[freqs > AIR_HZ].sum(axis=0) / per_frame)) * 100
    centroid = float(np.mean(librosa.feature.spectral_centroid(S=S, sr=sr)))
    value = {'low_end_share': round(low, 2), 'air_share': round(air, 2),
             'centroid_hz': round(centroid, 1)}
    # INFER, not KNOW. The crossover, the FFT size and the choice of magnitude
    # over power are all chosen, and eight readings of the same phrase span
    # 10.8 to 58.0 percent on one track.
    return fact(value, 'percent', 'mix', ['stft-band-share'], 'INFER', 'indirect',
                band_hz=[0, int(sr // 2)],
                note=f'low end is the per frame mean magnitude share below '
                     f'{LOW_END_HZ:g} Hz at n_fft {N_FFT}, sr {sr}, mono. The '
                     f'definition is pinned because the readings of "share of '
                     f'spectral energy" span 10.8 to 58.0 percent on one track '
                     f'depending on magnitude against power, global against per '
                     f'frame, and crossover. Both sides of a comparison must '
                     f'run through this same function.')


def _dynamic_arc_fact(paths, loaded, mix, sr, local, built):
    arc = local.get('rms_db_per_4s') or []
    usable = [v for _, v in arc if v is not None]
    if not usable:
        return fact(None, 'db', 'mix', ['rms-per-4s'], 'UNKNOWN', 'indirect',
                    note='no usable RMS windows')
    peak = max(usable)
    value = [[float(t), (None if v is None else round(float(v) - peak, 2))]
             for t, v in arc]
    # INFER, not KNOW. The 4 s window and the peak normalisation are choices.
    return fact(value, 'db', 'mix', ['rms-per-4s'], 'INFER', 'indirect',
                note='normalised to the track\'s own peak window, over a chosen '
                     '4 second window')


def _note_density_fact(paths, loaded, mix, sr, local, built):
    bpm = (built.get('tempo') or {}).get('value')
    guitar = loaded['guitar']
    if not bpm or bpm <= 0 or float(np.max(np.abs(guitar))) < 1e-6:
        return fact(None, 'onsets_per_beat', 'guitar', ['onset-rate'],
                    'UNKNOWN', 'indirect', band_hz=[150, 2500],
                    note='no tempo or a silent stem')
    band = chords_mod.band_limit(guitar, sr, 150, 2500)
    onsets = librosa.onset.onset_detect(y=band, sr=sr, units='time')
    seconds = len(band) / sr
    if seconds <= 0:
        return fact(None, 'onsets_per_beat', 'guitar', ['onset-rate'],
                    'UNKNOWN', 'indirect', band_hz=[150, 2500],
                    note='zero length stem')
    per_beat = (len(onsets) / seconds) / (float(bpm) / 60.0)
    return fact(round(float(per_beat), 3), 'onsets_per_beat', 'guitar',
                ['onset-rate'], 'INFER', 'indirect', band_hz=[150, 2500],
                note='onset rate normalised to the measured beat')


def _meter_fact(paths, loaded, mix, sr, local, built):
    bpm = (built.get('tempo') or {}).get('value')
    if not bpm or bpm <= 0:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='no tempo to group beats against')
    onset = librosa.onset.onset_strength(y=loaded['drums'], sr=sr)
    if not len(onset) or float(np.max(onset)) <= 1e-5:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='no onsets in the drums stem')
    hop = 512
    frames_per_beat = (60.0 / float(bpm)) * sr / hop
    ac = librosa.autocorrelate(onset - onset.mean())
    scores = {}
    for grouping in (3, 4):
        lag = int(round(frames_per_beat * grouping))
        scores[grouping] = float(ac[lag]) if 0 < lag < len(ac) else float('-inf')
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_score = ranked[1][1]
    detail = ', '.join(f'{k} scored {v:.3f}' for k, v in sorted(scores.items()))
    if not math.isfinite(best_score) or runner_score <= 0:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none', note='autocorrelation lag out of range')
    if best_score / runner_score < METER_MARGIN:
        return fact(None, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                    'UNKNOWN', 'none',
                    note=f'{detail}, a margin of '
                         f'{best_score / runner_score:.3f} which is under '
                         f'{METER_MARGIN}. Unnormalised autocorrelation at two '
                         f'lags cannot separate 3 from 4 on this material, and '
                         f'meter is suno_actionable direct, so a coin toss '
                         f'would reach the prompt as a statement.')
    return fact(best, 'beats_per_bar', 'drums', ['onset-autocorrelation'],
                'INFER', 'direct',
                note=f'{detail}. Published benchmarks put meter identification '
                     f'well below the other axes and this is one method.')


def _lead_register_fact(paths, loaded, mix, sr, local, built):
    band = chords_mod.band_limit(loaded['guitar'], sr, 70, 1400)
    return _register(band, sr, 70, 1400, 'guitar', [70, 1400], 'direct')


def _vocal_register_fact(paths, loaded, mix, sr, local, built):
    return _register(loaded['vocals'], sr, 70, 1200, 'vocals', [70, 1200],
                     'direct')


# Order matters and is load bearing in three places: chords reads tempo, key
# reads chords for its cross check, and intro_seconds reads section_boundaries.
BUILDERS = (
    ('tempo', _tempo_fact),
    ('meter', _meter_fact),
    ('instrumentation', _instrumentation_fact),
    ('tuning', _tuning_fact),
    ('chords', _chords_fact),
    ('key', _key_fact),
    ('harmonic_rhythm', _harmonic_rhythm_fact),
    ('section_boundaries', _section_boundaries_fact),
    ('section_count', _section_count_fact),
    ('intro_seconds', _intro_fact),
    ('note_density', _note_density_fact),
    ('lead_register', _lead_register_fact),
    ('vocal_register', _vocal_register_fact),
    ('loudness', _loudness_fact),
    ('spectral_balance', _spectral_fact),
    ('dynamic_arc', _dynamic_arc_fact),
)

PROJECTION = {
    'tempo': ('tempo_bpm', lambda v: v),
    'key': ('key', lambda v: v),
    'tuning': ('tuning', lambda v: v),
    'intro_seconds': ('intro_seconds', lambda v: v),
    'section_count': ('section_count', lambda v: v),
    'loudness': ('lra_lu', lambda v: v['lra_lu']),
    'spectral_balance': ('low_end_share', lambda v: v['low_end_share']),
    'lead_register': ('lead_register_midi', lambda v: v['median_midi']),
}


def fact_sheet(audio, stems_dir=None, cache_root=None):
    audio = Path(audio)
    if stems_dir is not None:
        paths = adopt_stems(stems_dir)
        origin = 'adopted'
    else:
        if cache_root is None:
            raise FactError('separating stems needs a cache_root')
        paths = stems_mod.separate(audio, cache_root)
        origin = 'separated'
    loaded = {name: _load(path) for name, path in paths.items()}
    mix = _load(audio)
    local = measure_mod.measure(str(audio))
    built = {}
    for name, builder in BUILDERS:
        built[name] = builder(paths, loaded, mix, SR, local, built)
    return {
        'schema': SCHEMA,
        'generated_at': _dt.datetime.now(_dt.timezone.utc)
                           .replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': {'path': str(audio), 'sha256': _sha256(audio),
                   'duration_s': local['duration_s']},
        'stems_from': origin,
        'facts': built,
    }


def scorable(sheet):
    """Project the sheet onto the axis names compare already scores.

    An UNKNOWN axis is omitted rather than passed as null. compare reports an
    absent axis as UNKNOWN and counts it under UNMEASURED, so omission gives
    the honest verdict and null would be a second way to say the same thing.

    This omission is also a hole, and Task 8 is what closes it: a sheet that
    graded its failing axes UNKNOWN would project only its passing ones and
    score PASS. The corpus gate therefore asserts how many axes were measured,
    not only the verdict.
    """
    out = {}
    for axis, (target, pick) in PROJECTION.items():
        entry = sheet['facts'].get(axis)
        if not entry or entry['confidence'] == 'UNKNOWN' or entry['value'] is None:
            continue
        try:
            out[target] = pick(entry['value'])
        except (KeyError, TypeError):
            continue
    return out


def render_markdown(sheet):
    lines = ['# Fact sheet', '',
             f'Source: `{sheet["source"]["path"]}`',
             f'Duration: {sheet["source"]["duration_s"]} s',
             f'Stems: {sheet["stems_from"]}',
             f'Generated: {sheet["generated_at"]}', '',
             '| Axis | Value | Unit | Stem | Band Hz | Confidence | Method | Suno |',
             '|---|---|---|---|---|---|---|---|']
    for axis, entry in sheet['facts'].items():
        band = '' if entry['band_hz'] is None else \
            f'{entry["band_hz"][0]} to {entry["band_hz"][1]}'
        value = entry['value']
        if isinstance(value, (list, dict)):
            shown = f'{len(value)} entries'
        else:
            shown = value
        lines.append(
            f'| {axis} | {shown} | {entry["unit"]} | {entry["stem"]} | '
            f'{band} | {entry["confidence"]} | {", ".join(entry["method"])} | '
            f'{entry["suno_actionable"]} |')
    notes = [(a, e['note']) for a, e in sheet['facts'].items() if e['note']]
    if notes:
        lines += ['', '## Notes', '']
        lines += [f'- **{a}**: {n}' for a, n in notes]
    return '\n'.join(lines) + '\n'
