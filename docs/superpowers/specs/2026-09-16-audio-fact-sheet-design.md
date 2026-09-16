# Audio fact sheet: design

Status: draft for review
Date: 2026-09-16

## Problem

A prompt-writing system that is good at its job still produces bad prompts when the
facts going into it are wrong. That is what this fixes.

The existing skill sends audio to a language model and treats the model's description
as analysis. Three passes on the same track returned three genres (metalcore,
electronic industrial, post-punk goth) and three tempos (144, 110, 130). The measured
tempo was 80.7. Every prompt built on that description missed, and each miss cost a
generation cycle to discover.

Meanwhile every number that came from measurement held up under recheck.

So the architecture inverts. Measurement produces facts. The language model is demoted
to prose impressions, clearly separated, never the source of a number.

### Evidence this is not a local quirk

CMI-Bench (ISMIR 2025) benchmarked audio language models against supervised systems.
Key detection: best model 8.55 against a supervised baseline of 74.3. Beat tracking:
23.69 against 88.3. MUSE tested Gemini specifically and found it strongest in its class
while still scoring 46.67% on meter identification and showing worse results when
prompted to reason step by step.

The conclusion is not "pick a better model." It is that this task class belongs to
purpose-built models.

## Goals

Produce, from an uploaded audio file:

1. A fact sheet of measured musical properties, each carrying its method and a
   confidence grade.
2. A chord MIDI file: the harmonic skeleton, aligned to the measured tempo and section
   timings.
3. A scorecard comparing any generated track back against a reference fact sheet.

The fact sheet is consumed by the user's prompt-writing system, which owns translation
into generator vocabulary. This project does not write prompts.

## Non-goals

- Writing prompts. A separate system already does that well.
- Melodic transcription. The MIDI emitter writes harmony, not riffs.
- Genre, era, or mood as facts. Those are impressions and are labeled as such.
- Real-time analysis. Batch only.
- Replacing the user's ear. The scorecard measures; it does not judge.

## Architecture

### Stage 1: separate

Demucs, six-stem model, producing drums, bass, guitar, piano, vocals, and other.

The six-stem variant is required rather than preferred. The default four-stem split
buries guitar inside an "other" bucket, and the guitar stem is what the register
measurement needs.

Known limitation: published evaluation (MoisesDB, ISMIR 2023) found guitar to be the
weakest separation category, well behind vocals, bass, and drums. The guitar stem is
therefore the noisiest input in the pipeline. This is an argument for confidence
grading, not for skipping the stem.

### Stage 2: measure each fact on the stem that carries it

| Fact | Stem | Band | Method |
|---|---|---|---|
| Tempo, downbeats, meter | drums | full | Beat This! plus tempogram plus inter-onset intervals |
| Key, chord vocabulary | guitar + bass | 150-2500 Hz | Essentia and Chordino, reconciled |
| Harmonic rhythm | guitar + bass | 150-2500 Hz | beat-synchronous chroma, run-length |
| Section boundaries and labels | full mix | full | All-In-One |
| Note density per section | guitar | 150-2500 Hz | onset rate normalized to beats |
| Lead figure register | guitar | 70-1400 Hz | pitch tracking, percentiles |
| Tuning inference | bass + guitar | low | lowest sustained fundamental against tuning templates |
| Loudness, range, true peak | full mix | full | pyloudnorm, ITU-R BS.1770-4 |
| Spectral balance | full mix | banded | sub-150 Hz share, centroid, above-5 kHz share |
| Dynamic arc | full mix | full | RMS per 4s, normalized to the track's own peak |
| Vocal register and density | vocals | 70-1200 Hz | pitch tracking, onset rate |

Each measurement declares the frequency band it reads. Testing on the reference guitar
stem showed band-limiting to 150-2500 Hz improved chord template fit from 0.680 to
0.695 and the decision margin between first and second chord candidate by about 11%.

The gain is small and the mechanism is bounded: band-limiting removes bleed from other
instruments, and cannot touch time-frequency smearing inside the target's own range,
which is most of what a separation artifact is. It is included because it is free and
because declaring the band makes each measurement's assumptions explicit.

### Stage 3: verify before emitting

No measurement leaves this stage as a bare number.

Every fact carries:

- **value**
- **method** that produced it
- **confidence**: KNOW (cross-validated by an independent second method), INFER (single
  method, or agreeing methods that share a known blind spot), UNKNOWN (attempted, not
  resolved)

Where methods disagree, both results are reported. Nothing is averaged.

**The tempo rule.** Tempo is emitted as a periodicity family, never a lone number, with
the ratio between members identified:

```
tempo:
  primary: 80.7          # strongest tempogram peak, drums stem
  family:
    - {bpm: 161.5, ratio: "2x"}
    - {bpm: 107.7, ratio: "4/3", note: "beat tracker reports this"}
  confidence: KNOW
  methods: [tempogram-peak, beat-track, inter-onset]
  disagreement: "beat tracker and tempogram peak differ by 4/3"
```

This exists because a 4/3 ratio, not the octave error everyone designs for, is what
produced a wrong tempo three times across three tracks from the same artist. On all
three, the drums tempogram peak landed at 76 to 81 while a beat tracker on the same stem
reported 103 to 112.

Separation removes contamination. It does not resolve metrical level. Both facts are
load-bearing.

### Stage 4: emit

**`facts.json` and `facts.md`.** The same content, machine-readable and human-readable.

Each fact also carries `suno_actionable`, which encodes what the target generator
responds to:

| Value | Meaning |
|---|---|
| `direct` | State it plainly. Tempo, register, instrumentation |
| `indirect` | State the effect, never the fact. Harmonic rhythm becomes "static harmony" |
| `midi_only` | Text cannot carry this. It goes in the MIDI clip |
| `none` | Measured for verification only, never for a prompt |

Chord names are `midi_only`. Community evidence is consistent that chord-name notation
in a text prompt is discarded, and the most-cited workaround is supplying audio. The
MIDI channel is what replaces it.

**`progression.mid`.** Rules:

- One chord per bar, quantized, at the primary tempo written into the file header.
- Root position block chords. No invented voicings or inversions.
- **Where the third is absent, write root and fifth only.** Most distorted guitar is
  genuinely ambiguous between major and minor; the reference track reads 35% major and
  21% minor on the same root for this reason. Guessing a third would be the emitter
  inventing information.
- Sections below the confidence threshold get a sustained root, and the fact sheet names
  them.
- Section timings mirror the reference so the clip aligns on a timeline.
- No melody.

**`impressions.md`.** Language model prose, in its own file, never merged into facts.

### Stage 5: research, when a name is supplied

Optional branch. When the user supplies an artist or song name, scene and era research
runs alongside. Measured facts outrank researched claims on every collision.

### Stage 6: compare

Input: a generated track, and a reference fact sheet. Same pipeline, same stems, same
bands. Output: per-axis deltas.

Both sides must be measured the same way. An early draft of this spec compared low-end
share between a vocal-removed instrumental and a full mix, which is not a comparison at
all, since removing vocals raises the low-end share on its own.

## Gates

Two classes, with opposite philosophies.

### Pipeline gates: strict

These test our code against known truth and should be tight, because everything
downstream inherits a drift here.

| Gate | Threshold |
|---|---|
| Tempo on the reference track | 80.7 within 2% |
| Key on the reference track | F sharp minor |
| Methods disagree on a non-octave ratio | emits UNKNOWN, never picks one silently |
| Section count on the reference track | 7, within 1 |
| Separation produces six stems | all present, non-silent |
| Every emitted fact | carries method and confidence |

### Output gates: loose, and tightened later

These score a generation from a system we do not control. Set them tight now and
everything fails, which teaches nothing about whether a change helped.

| Axis | Gate | Reference |
|---|---|---|
| Tempo | within 5%, hard fail on octave or subdivision error | 80.7 |
| Key | exact passes, relative warns, other fails | F sharp minor |
| Intro length before full arrangement | within 3s | 12.1s |
| Loudness range | within 1.5 LU | 4.1 LU |
| Low end share | within 3 points, same stem type both sides | 16.4% |
| Section count | within 1 | 7 |
| Lead figure register | median within 5 semitones | F sharp 2 |

The register row exists because a generated intro kept arriving as a high fast lead when
the source riff sits at the bottom of the instrument. Four cycles were spent discovering
that by ear. This gate catches it on the first.

## Build order

Each step is useful on its own, so stopping after any of them still leaves something
better than today.

1. **Separation plus tempo family.** Fixes the worst defect alone.
2. **Compare.** Built second on purpose. Until it exists, progress is unmeasurable and
   every disagreement is a matter of opinion.
3. **Full fact sheet with confidence grading.**
4. **MIDI emitter.**
5. **Research branch.**

## Test corpus

Three tracks by one artist, each with six stems: the reference track plus two more from
the same release. A pipeline validated against a single song proves only that it was
tuned to that song.

Ground truth is established for the reference track (80.7 BPM, F sharp minor, confirmed
by three independent methods plus an external analyzer). Ground truth for the other two
is not yet established and is an open item.

## Open questions

1. Tempo on the two additional tracks. The tempogram peak suggests 76 and 81; beat
   trackers suggest 103 and 112. On the reference track the tempogram peak was correct.
   Needs human confirmation to promote from inference to rule.
2. Whether a programmatically generated block-chord MIDI meaningfully constrains
   generated harmony. Vendor documentation describes MIDI as an anchor that gets
   reinterpreted, and no first-hand account tests this specific case. The deterministic
   path, rendering the MIDI through a built-in synth, is unaffected either way.
3. Harsh vocal classification has no reliable tool. Currently out of scope; the fact
   sheet will emit UNKNOWN rather than guess.

## Why the odd rules exist

Several rules here look arbitrary without their history:

- Tempo as a family, not a number: three wrong tempos across three tracks, all from a
  4/3 ratio.
- Root and fifth when the third is absent: power chords are genuinely ambiguous.
- Register as a first-class fact: four cycles lost to an intro in the wrong octave.
- Compare built second: an entire working session spent arguing about "still off" with
  no way to see partial progress.
- Both sides measured identically: caught in this spec's own first draft.
