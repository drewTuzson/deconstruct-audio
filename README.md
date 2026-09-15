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
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
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
| `connect-brain <folder>` | Saves a pointer to a local SunoGPT Brain folder |
| `disconnect-brain` | Removes that pointer without touching the Brain files |
| `forget-key` | Deletes the locally saved credential. Does not revoke the key at Google |
| `save-style <name> --style <text>` | Saves style text you liked. `--style -` reads it from stdin. Add `--notes`, `--source`, or `--overwrite` |
| `list-styles` | Lists every saved style with its slug, length, notes and source |
| `show-style <name>` | Prints one saved style as JSON |
| `edit-style <name>` | Changes `--style`, `--notes`, or both. An empty `--notes` clears them |
| `rename-style <old> <new>` | Renames a saved style, refusing to overwrite another one |
| `delete-style <name>` | Deletes a saved style. This cannot be undone |

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
- There is no stem separation, no plugin chain recovery, and no track count. The prompt forbids inventing them.
- One file per run, longer than zero seconds and up to 30 minutes. Longer recordings need an excerpt you choose; the script will not trim silently.
- Lyrics are not transcribed.

## Optional: SunoGPT Brain

If you already own SunoGPT's Brain, `connect-brain` saves a pointer to your local copy and the agent reads your own rules when formatting a Suno prompt. The analysis stays separate from the prompt formatting, and the reviewed report keeps the full evidence either way. This repository contains no Brain content, and the skill works standalone without it. See [references/brain.md](references/brain.md).

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The 13 tests cover credential handling, config validation, doctor output on malformed files, upload and cleanup branches, failure paths that retain measurements, and the finite-value guarantees on the measurement path. They run against mocks and synthetic audio. Passing tests say nothing about real API access, real key validity, or whether the musical description is any good.

The release in this repository is the revision its author ran end to end on macOS. The Windows and Linux code paths are written and covered by mocked tests, but have not been exercised on those operating systems.

`.gitignore` excludes `.venv/`, `.env`, `config.json`, `credentials.json`, and `reports/`. Keep it that way; none of those belong in a package.

Troubleshooting for blocked authentication, quota, unavailable models, and cleanup is in [references/troubleshooting.md](references/troubleshooting.md).

## License

MIT. See [LICENSE](LICENSE).
