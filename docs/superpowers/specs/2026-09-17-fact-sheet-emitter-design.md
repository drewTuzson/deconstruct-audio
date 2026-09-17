# Fact sheet, chord MIDI, research and Brain wiring: design

Status: draft for review
Date: 2026-09-17
Builds on: `docs/superpowers/specs/2026-09-16-audio-fact-sheet-design.md`
Baseline: `f021646`, 97 tests green

## What this covers

Stages 3 through 6 of the parent spec, which the first two phases left unbuilt:
the fact sheet emitter, the chord MIDI emitter, the research branch and the wiring
into the user's SunoGPT Brain. Separation, the tempo family and `compare` already
exist and are not redesigned here.

## The two bars this is measured against

**Entry bar, before any generation is bought.** The fact sheet returns correct,
rerun-stable values for all three corpus tracks, and the Murder She Wrote sheet
scored by the existing `compare` command against the known values returns PASS:
80.7 BPM, F sharp minor, drop C sharp, seven sections, 12.1 second intro,
16.4 percent low end.

**Exit bar.** One generation, whose prompt the Brain wrote from the fact sheet
alone, scores PASS on tempo, key and intro length, with low end share and loudness
range inside their limits.

## Corpus

Three tracks from one release, six stems each.

| Track | Source | Stems |
|---|---|---|
| Murder, She Wrote | `~/Downloads/mydiarytoyou! - Murder, She Wrote (Official Visualizer).mp3`, 138.8 s | demucs `htdemucs_6s`, cached under the config directory |
| The Danger of Caring | `~/Desktop/mydaiarytoyou!/The Danger of Caring/`, 205.8 s | supplied, six files named `1_<title>_(Drums).wav` and so on |
| Wrong Turn | `~/Desktop/mydaiarytoyou!/Wrong Turn/`, 153.8 s | supplied, same naming |

Ground truth exists for Murder She Wrote only. The other two are held to
rerun stability and to internal consistency, not to a known answer, because
inventing ground truth for them would be the exact failure this project exists
to stop.

The two supplied stem sets are not demucs output, so `facts` must be able to
adopt an existing folder rather than only its own cache. That is a requirement,
not a convenience: without it the corpus is one track and a pipeline validated
on one track proves only that it was tuned to that track.

## The Fact object

Every axis emits the same shape. Nothing in the fact sheet is a bare number.

```json
{
  "value": 80.7,
  "unit": "bpm",
  "stem": "drums",
  "band_hz": null,
  "method": ["tempogram-peak", "beat-track", "ioi"],
  "confidence": "KNOW",
  "suno_actionable": "direct",
  "note": null
}
```

| Field | Rule |
|---|---|
| `value` | The measurement. `null` only when `confidence` is `UNKNOWN` |
| `unit` | Named, so a reader never has to infer seconds from percent |
| `stem` | Which stem carried it, or `mix` |
| `band_hz` | `[low, high]` or `null` for full band. Declaring the band makes the assumption explicit |
| `method` | Every method that ran, not only the one that won |
| `confidence` | `KNOW` either cross-validated by an independent second method, or computed by a published standard whose parameters the standard itself fixes. `INFER` single method, a chosen parameter anywhere in the path, or agreeing methods sharing a blind spot. `UNKNOWN` attempted and unresolved |
| `suno_actionable` | `direct`, `indirect`, `midi_only`, `none` |
| `note` | Disagreement, caveat, or what the estimate cannot support |

Constructing a Fact without `value`, `method` and `confidence` raises. A fact
sheet cannot contain an ungraded number, because the pipeline this replaces
shipped exactly that.

Where two methods disagree, both results are reported and nothing is averaged.

The second clause of `KNOW` covers exactly one axis: `loudness`, which is
ITU-R BS.1770-4. The standard fixes the gating, the filter, the window and the
aggregation, so there is no parameter anyone could have chosen differently and
a second method would return the same number by construction.

A wider version of this clause was drafted and withdrawn. It also claimed
`instrumentation`, `spectral_balance` and `dynamic_arc` compute rather than
estimate, on the grounds that none has a free parameter. All three do, and the
disproof of the first arrived in the same commit as the claim:
`instrumentation`'s presence threshold moved from 30 dB to 35 dB, and that move
changed which stems the axis reports on two of the three corpus tracks.
`spectral_balance` has a crossover, an FFT size and a choice between magnitude
and power, which this project's own evidence shows span 10.83 to 58.01 percent
on a single track. `dynamic_arc` has a window length and a normalisation target.

A declared parameter is not the same as no parameter. Those three are `INFER`:
one method, with a choice in the path. The axes that estimate, which are tempo,
key, tuning, chords, meter and both registers, need the first clause.

The axis this distinction protects is `key`. It reaches `KNOW` only when its
template margin clears 0.05 **and** the measured chord sequence's most common
root is the key's tonic. Grading on the margin alone was tried, and it graded a
track `KNOW` whose tonic disagreed with its own chord histogram.

## Axes

The parent spec's stage 2 table, unchanged, plus tuning promoted to a scored axis.

| Fact | Stem | Band Hz | Method | `suno_actionable` |
|---|---|---|---|---|
| `tempo` | drums | full | tempogram, beat track, inter-onset | `direct` |
| `meter` | drums | full | beat grouping autocorrelation | `direct` |
| `key` | guitar + bass | 150 to 2500 | chroma against major and minor templates, reconciled | `direct` |
| `chords` | guitar + bass | 150 to 2500 | beat-synchronous chroma, template match | `midi_only` |
| `harmonic_rhythm` | guitar + bass | 150 to 2500 | run length over the chord sequence | `indirect` |
| `sections` | mix | full | feature clustering, boundaries and count | `direct` |
| `intro_seconds` | mix | full | first boundary where the arrangement reaches full density | `direct` |
| `note_density` | guitar | 150 to 2500 | onset rate normalized to beats | `indirect` |
| `lead_register` | guitar | 70 to 1400 | pitch tracking, percentiles, reported in MIDI note numbers | `direct` |
| `tuning` | bass + guitar | low | lowest sustained fundamental against tuning templates | `direct` |
| `loudness` | mix | full | ffmpeg `ebur128`, integrated, range, true peak | `indirect` |
| `spectral_balance` | mix | banded | share below 150 Hz, centroid, share above 5 kHz | `indirect` |
| `dynamic_arc` | mix | full | RMS per 4 s normalized to the track's own peak | `indirect` |
| `vocal_register` | vocals | 70 to 1200 | pitch tracking, onset rate | `direct` |

Harsh vocal classification stays out of scope and emits `UNKNOWN` rather than a
guess, as the parent spec requires.

## Modules

Commands orchestrate and print a machine-readable result line. Service modules own
the reusable how. That split is an invariant in `AGENTS.md` and this work does not
bend it.

| File | Responsibility | Depends on |
|---|---|---|
| `scripts/facts.py` | The `Fact` type, the per-axis measurement, `facts.json` and `facts.md` | `measure`, `stems`, `tempo`, `chords` |
| `scripts/chords.py` | Key, chord sequence and harmonic rhythm from a band-limited guitar and bass pair | librosa, numpy |
| `scripts/midi_emit.py` | `progression.mid` from a fact sheet | `mido` |
| `scripts/research.py` | The research record and the collision table | nothing |
| `scripts/brain.py` | Reading the Brain, filling slots from facts, validating the result | nothing at import time |
| `scripts/corpus_check.py` | Runs the corpus twice and diffs | `facts` |
| `scripts/scoreboard.py` | Renders the gate ledger to HTML | nothing |

New commands on `deconstruct.py`:

```
facts <audio> [--stems DIR] [--out DIR]
midi <facts.json> [--out FILE]
research <facts.json> --artist NAME --title NAME
prompt <facts.json> [--mode custom|simple|studio]
```

`--stems DIR` adopts an existing six-stem folder. Matching is case-insensitive on
the stem name appearing anywhere in the filename, so `1_Whatever_(Drums).wav`
resolves to `drums`. A folder that does not yield all six named stems is an error,
never a partial sheet, for the same reason `stems.separate` refuses a partial
separation today.

## Compare gains one axis

`compare.GATES` currently scores seven axes and has no tuning row, while the entry
bar names drop C sharp. It gains:

```python
'tuning': {'kind': 'tuning', 'label': 'Tuning'}
```

Scored by normalized string equality after enharmonic folding, so `drop C#` and
`drop Db` are the same answer and `drop D` is not. Unparseable on either side is
`UNKNOWN`, never a silent pass. No other gate changes: the loose output gates the
parent spec set are deliberate and tightening them now would hide partial progress.

## From fact sheet to compare

`compare.score()` takes two flat dicts of plain numbers and is deliberately
import-free. A `Fact` is a nested object. Something has to bridge them, and the
choice of which side moves matters.

`compare` does not change. `facts.py` grows `scorable(facts) -> dict`, which
projects the sheet down onto the axis names `compare.GATES` already uses:

| Fact axis | `compare` axis |
|---|---|
| `tempo.value` | `tempo_bpm` |
| `key.value` | `key` |
| `tuning.value` | `tuning` |
| `intro_seconds.value` | `intro_seconds` |
| `sections.value.count` | `section_count` |
| `loudness.value.lra_lu` | `lra_lu` |
| `spectral_balance.value.low_end_share` | `low_end_share` |
| `lead_register.value.median_midi` | `lead_register_midi` |

An axis graded `UNKNOWN` is omitted from the projection rather than passed as
`null`. `compare` already reports an absent axis as `UNKNOWN` and counts it under
`UNMEASURED=`, so omission produces the honest verdict while passing `null` would
add a second way to say the same thing.

The projection is what both sides of a comparison run through, reference and
candidate alike. The parent spec caught its own first draft comparing a
vocal-removed instrumental against a full mix, and one shared projection is how
that stays caught.

## MIDI rules

- One chord per bar, quantized, at the measured primary tempo written into the file
  header as a `set_tempo` message.
- Root position block chords. No invented voicings, no inversions.
- Where the third is absent, root and fifth only. Most distorted guitar is genuinely
  ambiguous between major and minor, and the reference track reads 35 percent major
  against 21 percent minor on the same root for that reason. Writing a third there
  would be the emitter inventing information.
- A section whose chord confidence is below threshold gets a sustained root, and
  `facts.md` names that section so the gap is visible rather than implied.
- Section timings mirror the measured grid so the clip aligns on a timeline.
- No melody.

`mido` is added to `requirements.txt`. It is pure Python with no compiled
dependencies, and the round-trip test reads the file back with a real MIDI parser
rather than with the writer's own assumptions.

## Research branch

Optional, and only when a name is supplied. It writes `research.md` beside the fact
sheet and never into `facts.json`.

Every claim carries its source. `research.py` owns the collision table: given a
research claim and a measured fact on the same axis, it reports both and marks the
measured one authoritative. It never edits a fact.

The searching itself stays agent work. The script performs no network call, which
keeps `facts` and `research` offline commands and keeps the project's standing
split intact: the script measures and records, the agent judges.

## Brain wiring

`brain.py` reads the Brain from the path already saved in the config, at runtime.
No Brain text is copied into this repository, and the tests run against a synthetic
fixture Brain, because the real one is licensed third-party material.

It composes from `facts.json` alone. `impressions.md` and `listening.md` are not
inputs, which is the whole point: if a prompt built only from measured facts clears
the exit bar, the measurement path is carrying the result.

Slot filling maps `suno_actionable` onto the Brain's own format:

| Fact | Where it lands |
|---|---|
| `tempo` | The moods cluster, as the Brain requires, never at the tail |
| `lead_register`, `vocal_register` | Instrument and vocal tags, as register character |
| `sections`, `intro_seconds`, `dynamic_arc` | The song direction prose |
| `harmonic_rhythm`, `spectral_balance`, `loudness` | Production cues, stated as effect |
| `chords` | Nowhere in the text. It goes in the MIDI |
| `tuning` | Instrument tag |

Then it validates what can be checked mechanically, and fails loudly rather than
shipping a prompt the Brain's own final check would reject:

- Character budget for the mode. Custom is a hard 1,000 with a target of 850 to 950.
- No negation words anywhere in the style, tags or prose.
- No hyphens outside the Brain's stated exceptions.
- No banned fatigue word.
- No artist, band, song or album name in any field.
- Direction prose present. A style that is only tags is a failure by the Brain's
  own rule.
- Every number in the output traces to a fact in `facts.json`.

Choosing the subgenre remains judgment and stays with the agent. `brain.py` fills,
checks and reports; it does not pretend to have taste.

## Gates

Pipeline gates are strict because everything downstream inherits a drift. Output
gates stay loose, as the parent spec argued, so partial progress stays visible.

| Gate | Threshold |
|---|---|
| Tempo on the reference track | 80.7 within 2 percent |
| Key on the reference track | F sharp minor |
| Tuning on the reference track | drop C sharp |
| Section count on the reference track | 7, within 1 |
| Intro on the reference track | 12.1 s within 3 s |
| Low end share on the reference track | 16.4 percent within 3 points |
| Methods disagree on a non-octave ratio | emits `UNKNOWN`, never picks silently |
| Every emitted fact | carries value, method and confidence, or construction raises |
| Rerun on identical audio | identical `facts.json` once the run timestamp is excluded |

Rerun stability is a gate rather than an assumption because two of the measurement
libraries have stochastic paths, and a fact sheet that moves between runs cannot
support a comparison.

## Build order and seats

Each step is useful alone.

1. `facts.py` and `chords.py`, plus the compare tuning axis and `corpus_check.py`.
   This is the entry bar.
2. `midi_emit.py`. Depends only on the frozen fact schema, so it can run alongside
   step 1 once that schema lands.
3. `research.py`.
4. `brain.py`. This is the exit bar.

One controller, at most two builders at a time, one independent critic who scores
blind against the bars and never grades work it produced.

## Open questions carried forward

1. Ground truth for the two non-reference tracks is still unestablished. The
   tempogram peak suggests 76 and 81 while beat trackers suggest 103 and 112. Those
   tracks are held to rerun stability only until a human confirms.
2. Whether a programmatic block-chord MIDI meaningfully constrains generated
   harmony is untested by any first-hand account. The deterministic path, rendering
   the MIDI through a synth, is unaffected either way.
3. Harsh vocal classification has no reliable tool and emits `UNKNOWN`.

## Why the odd rules exist

- Facts carry their band because band-limiting to 150 to 2500 Hz moved chord
  template fit from 0.680 to 0.695 and the decision margin by about 11 percent. The
  gain is small; declaring the assumption is the real reason it is there.
- The MIDI writes no third it did not measure, because a power chord is genuinely
  ambiguous and a guessed third is the emitter inventing information.
- The Brain reads facts and nothing else, because a prompt built from prose is what
  this project replaced.
- Compare gained a tuning axis rather than the bar losing one, because a bar that
  quietly drops the axis it cannot score is not a bar.
