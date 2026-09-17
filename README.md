# deconstruct-audio

An agent skill that turns a local audio file into a written breakdown of how it was made, and then into a reusable style description you can paste into a music generator such as Suno.

It works from two independent sources of evidence. Your computer measures the file with ffmpeg and librosa: loudness, true peak, tempo candidates, key candidates, a level map, and suggested section boundaries. Separately, Gemini listens to the audio and writes eleven sections on genre, groove, voice, instrumentation, bass, drums, mix, and arrangement. The model is deliberately not shown the measurements, so when the two agree you have corroboration rather than an echo of a number you fed it. Your agent then reconciles the disagreements in writing and produces the style line.

The skill ships no genre presets, no personal taste, and no artist references. The listening prompt asks for audible evidence across any musical tradition and forbids naming artists, bands, producers, or songs.

## What a run produces

Each analysis writes a timestamped folder containing four files:

| File | Contents |
|---|---|
| `measurements.json` | Every local number, plus a SHA-256 of the source audio and a `notes` array stating what each estimate can and cannot support |
| `listening.md` | Gemini's eleven sections, saved verbatim and never edited |
| `receipt.json` | Model used, UTC timestamp, source hash, what was sent, and a review status |
| `report.md` | The assembled document with two markers, `<!-- CONFLICTS -->` and `<!-- STYLEBOX -->`, for the agent to fill in |

The script stops at a draft on purpose. Reconciling a tempo the model heard as 85 against a histogram that peaked at 170, and deciding which one to write down, is judgment. The skill file tells the agent how to do that and how to mark the result reviewed.

## Requirements

- Python 3.10 or newer
- ffmpeg and ffprobe on PATH
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey), for `analyze` only. The measurement commands need no key
- For `separate`, and for `tempo --from-drums`, a Demucs and torch install of several gigabytes plus a model download on first use
- An agent host that can run local scripts, such as Claude Code or Codex

Uploading this folder into a chat window does not install anything or grant filesystem access. A chat-only assistant can read a finished report; it cannot run the analyzer.

## Install

Copy the `deconstruct-audio` folder into your host's skills directory, keeping `SKILL.md` at its top level:

```bash
cp -R deconstruct-audio ~/.claude/skills/
```

Codex uses `~/.codex/skills/` instead. Then start a session and ask the agent to set up the deconstruct-audio skill. It reads `SKILL.md`, runs the doctor check, and walks you through dependencies, key entry, and an API test, one step at a time. Full detail is in [INSTALL.md](INSTALL.md) and [references/onboarding.md](references/onboarding.md).

To install the dependencies yourself:

```bash
python3 scripts/setup.py
```

This creates a private `.venv` inside the skill folder and installs `requirements.txt` into it. Your system Python is left alone. Every command below uses that private interpreter, shown here as `.venv/bin/python` (`.venv/Scripts/python.exe` on Windows).

## Commands

```bash
.venv/bin/python scripts/deconstruct.py doctor
.venv/bin/python scripts/deconstruct.py set-key
.venv/bin/python scripts/deconstruct.py verify
.venv/bin/python scripts/deconstruct.py finish-setup
.venv/bin/python scripts/deconstruct.py analyze /path/to/track.wav --out /path/to/reports
.venv/bin/python scripts/deconstruct.py separate /path/to/track.wav
.venv/bin/python scripts/deconstruct.py tempo /path/to/track.wav --from-drums
.venv/bin/python scripts/deconstruct.py compare reference.json candidate.json
```

| Command | What it does |
|---|---|
| `doctor` | Prints a JSON status of Python, ffmpeg, each module, key presence, model, and setup state. Offline, and never prints a key or a config file |
| `set-key` | Reads a key through a hidden terminal prompt and writes it to the private config directory with owner-only permissions. Refuses to run outside a terminal |
| `verify` | Sends a one-second generated 440 Hz tone, not your music, and confirms a complete audio response came back. May be billable |
| `set-model <id>` | Pins an exact Gemini model ID and requires a fresh `verify` |
| `finish-setup` | Marks onboarding complete, but only after a successful verification of the current key and model |
| `analyze <file>` | Runs the full pipeline and prints `DRAFT_WRITTEN=<path>` |
| `analyze <file> --local-only` | Measures without any network call. Produces no listening assessment and no style line |
| `separate <file>` | Splits the audio into six stems with Demucs and prints `STEM_<NAME>=<path>` for each. Cached by source hash, so a repeat run reuses them. `--out` puts the cache somewhere other than the configuration directory |
| `tempo <file>` | Reports tempo as a family of related candidates with a confidence grade, not a single number. Add `--from-drums` to separate first and measure the drums stem |
| `compare <reference> <candidate>` | Scores a candidate fact sheet against a reference one on the axes measured on both sides. Exit code carries the verdict |
| `midi <facts.json>` | Writes the measured chord progression to `progression.mid` at the measured tempo. One chord per bar, root position, root and fifth wherever no third was measured, a sustained root where confidence was too low to name a chord |
| `connect-brain <folder>` | Saves a pointer to a local SunoGPT Brain folder |
| `disconnect-brain` | Removes that pointer without touching the Brain files |
| `forget-key` | Deletes the locally saved credential. Does not revoke the key at Google |
| `save-style <name> --style <text>` | Saves style text you liked. `--style -` reads it from stdin. Add `--notes`, `--source`, or `--overwrite` |
| `list-styles` | Lists every saved style with its slug, length, notes and source |
| `show-style <name>` | Prints one saved style as JSON |
| `edit-style <name>` | Changes `--style`, `--notes`, or both. An empty `--notes` clears them |
| `rename-style <old> <new>` | Renames a saved style, refusing to overwrite another one |
| `delete-style <name>` | Deletes a saved style. This cannot be undone |

## Measuring instead of describing

`analyze` asks a model what it hears. These three commands do not ask anything; they measure, and they say how sure they are.

`separate` runs Demucs over the file and writes six stems: drums, bass, guitar, piano, vocals, other. The six-stem model is used rather than the default four-stem split because that one buries guitar inside an "other" bucket. Stems are cached under your configuration directory and keyed by a hash of the source, so analysing the same track twice separates it once.

`tempo` reports a periodicity family rather than a number, because the interesting failure is not noise, it is metrical level. Three tracks from one artist all read 76 to 81 on the drums tempogram while a beat tracker on the same stem said 103 to 112, a 4/3 ratio apart, and picking one silently is how a wrong tempo ships. The output carries a primary BPM, every related candidate with the ratio that relates it, each method's own reading, and a grade of `KNOW`, `INFER` or `UNKNOWN`. `INFER` means the tempogram still shows support for a competing metrical level, so the primary may be an octave or a subdivision off and the true value is in the family. `UNKNOWN` means the methods disagree by no simple ratio and none was chosen for you.

`compare` scores one fact sheet against another, axis by axis, against gates set deliberately loose so partial progress is visible rather than everything failing at once. It scores only the axes measured on both sides: the rest are counted as unmeasured and never assumed to pass, so `MEASURED=` and `UNMEASURED=` print above the verdict. The exit code is the verdict, which is what a wrapping script gates on: 0 PASS, 2 FAIL, 3 WARN, 4 UNKNOWN, and 1 if the command itself failed. The reference comes first and the pair cannot be told apart from the files, so the report echoes which path was which.

```
compare reference.json candidate.json
```

`midi` exists because chord names in a text prompt are discarded. Community
evidence is consistent on that, and the most cited workaround is supplying
audio, so the MIDI clip is the channel that carries harmony when text cannot.
The emitter writes nothing it did not measure: where the third was absent it
writes root and fifth rather than choosing between major and minor, and where
the chord itself scored below threshold it writes a sustained root and prints
which bars those were.

```
midi facts.json --out progression.mid
```

## Saved styles

When a generation comes out the way you wanted, keep the style text that produced it:

```
save-style "Warm Analog Soul" --style "neo-soul, warm analog tape saturation, dusty Rhodes, brushed drums" --notes "best chorus so far"
```

Styles are stored one JSON file per style in your configuration directory, beside `config.json` and outside this package. Saving and reuse are local file operations: they need no API key, no completed onboarding, and no prior analysis, so a style you typed from memory works the same as one lifted from a report. Ask the agent to apply a saved style to a prompt and it uses the stored text verbatim, tells you which parts of the result came from which source, and surfaces any conflict with measured evidence rather than quietly averaging the two. See [references/styles.md](references/styles.md).

## What gets sent, and what it costs

Running `analyze` uploads your audio to Google. Before it does, ffmpeg decodes the file to FLAC with `-map_metadata -1`, which drops the tags and takes only the first audio stream. The filename is never sent. Neither are the local measurements, the Brain path, or your configuration.

Everything audible in the recording still goes to Google, including voices and anything personal that was said. Read Google's [pricing](https://ai.google.dev/gemini-api/docs/pricing) and [terms and data handling](https://ai.google.dev/gemini-api/terms) before uploading material you care about. The skill never enables billing for you, never retries a possibly billable request on its own, and never silently switches to a different model.

Files at or under 12 MB are sent inline. Larger ones go through the Files API and are deleted afterward; if that deletion fails, the script prints the file ID so you can remove it in AI Studio yourself.

Credentials live outside the package, in `~/.config/deconstruct-audio/` or wherever `DECONSTRUCT_AUDIO_CONFIG_DIR` points. `GEMINI_API_KEY` and `GOOGLE_API_KEY` in the environment take precedence over the saved file. If both are set to different values, the script refuses to guess rather than picking one. Provider error bodies are never printed, since they can contain request data.

## Limits worth knowing before you trust the output

- **Tempo is an onset-pattern estimate.** Half time, double time, and rubato mislead it. The report gives a histogram of candidates, not a single answer.
- **Key scores are correlations against major and minor templates, not probabilities.** Music built on other systems will not fit those templates, and the report says so.
- **Section boundaries come from feature clustering.** They are suggestions, not verified verses and choruses.
- **Genre and perceived era are interpretations**, and the skill instructs the agent to keep them labeled that way.
- **A tempo family is not a tempo.** `tempo` grades itself, and an `INFER` primary can be an octave or a subdivision away from the true reading, which is then sitting in the family beside it. Read the grade before quoting the number.
- **`compare` scores only what both sides measured**, against loose gates. A `PASS` above a high `UNMEASURED` count means little was checked, not that little was wrong.
- `analyze` does no stem separation; `separate` is a separate command and needs a multi-gigabyte Demucs and torch install. There is still no plugin chain recovery and no track count, and the prompt forbids inventing them.
- One file per run, longer than zero seconds and up to 30 minutes. Longer recordings need an excerpt you choose; the script will not trim silently.
- **The MIDI is harmony, not a transcription.** No melody, no inversions, no
  voicings. A bar whose chord scored low is a sustained root, and the command
  names those bars rather than letting a thinner clip imply them.
- Lyrics are not transcribed.

## Optional: SunoGPT Brain

If you already own SunoGPT's Brain, `connect-brain` saves a pointer to your local copy and the agent reads your own rules when formatting a Suno prompt. The analysis stays separate from the prompt formatting, and the reviewed report keeps the full evidence either way. This repository contains no Brain content, and the skill works standalone without it. See [references/brain.md](references/brain.md).

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The 80 tests cover credential handling, config validation, doctor output on malformed files and on a missing audio stack, upload and cleanup branches, failure paths that retain measurements, the finite-value guarantees on the measurement path, stem caching and cache permissions, the tempo family's confidence grading, and the comparison gates and exit codes. They run against mocks and synthetic audio. One test performs a real separation and is skipped unless `DECONSTRUCT_AUDIO_RUN_SEPARATION=1` and `DECONSTRUCT_AUDIO_TEST_TRACK` are set. Passing tests say nothing about real API access, real key validity, or whether the musical description is any good.

The release in this repository is the revision its author ran end to end on macOS. The Windows and Linux code paths are written and covered by mocked tests, but have not been exercised on those operating systems.

`.gitignore` excludes `.venv/`, `.env`, `config.json`, `credentials.json`, and `reports/`. Keep it that way; none of those belong in a package.

Troubleshooting for blocked authentication, quota, unavailable models, and cleanup is in [references/troubleshooting.md](references/troubleshooting.md).

## License

MIT. See [LICENSE](LICENSE).
