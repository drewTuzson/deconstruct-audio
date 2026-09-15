# First-run onboarding

Guide one small step at a time in plain English. Do what the host can do, and ask only for the human steps. Do not ask about genre or personal preferences as a prerequisite.

For an explicit local-only request, use only step 1 and run analyze with --local-only. Missing credentials or incomplete Google onboarding do not block local measurement. Skip steps 2 through 5 until the user requests Gemini listening.

## 1. Explain the result and check the computer

Say: "This skill measures an audio file on your computer, asks Gemini to describe what it hears, and turns the evidence into a reusable style description. It can also use your existing SunoGPT Brain to prepare a Suno prompt."

Python 3.10+ and ffmpeg/ffprobe are required. Supported target environments are local agent hosts on macOS, Linux and Windows with Python and these programs on PATH. A chat-only host is a report consumer, not the executable analyzer. Network access is needed for package installation and Google API calls.

Run `scripts/deconstruct.py doctor`. Install missing system tools using the user's normal trusted package manager. Examples: Homebrew `brew install python ffmpeg`; Ubuntu/Debian `sudo apt install python3 python3-venv ffmpeg`. On Windows, use the Python installer and an ffmpeg build linked by https://ffmpeg.org/download.html, then confirm both executables are on PATH. Do not install a new package manager silently.

Run `python3 <SKILL_ROOT>/scripts/setup.py` (Windows: `py -3`). This creates a private `.venv` and installs requirements without modifying system Python packages. Subsequent commands use `<SKILL_ROOT>/.venv/bin/python`, or `.venv/Scripts/python.exe` on Windows. It is safe to rerun setup after a failed dependency installation.

## 2. Obtain and store a Gemini API key

Ask whether the user already has a Gemini API key configured. Detect only its presence through doctor. Never search unrelated files or ask them to paste a key into chat.

If needed, guide them to [Google AI Studio API keys](https://aistudio.google.com/apikey): sign in, complete any required terms, select or create the intended project, and create a key. If the account cannot create projects or keys, an account administrator must grant access. Check the current [official key guide](https://ai.google.dev/gemini-api/docs/api-key) if the UI differs. Gemini app subscriptions do not establish API project access or quota.

Explain before verification: audio and the analysis prompt go to Google. The full Brain, local source path and personal preferences are not sent by these scripts. Tags are removed from the uploaded copy, but voices and any personal information audible in the recording remain. Usage can incur charges. Review Google's [current pricing](https://ai.google.dev/gemini-api/docs/pricing), [terms and data handling](https://ai.google.dev/gemini-api/terms), and the project's quota before uploading confidential material. Do not enable billing for the user or promise free usage. Billing alerts are notifications, not a guaranteed spending cap.

Two credential routes:

- Existing host secret manager or environment: `GEMINI_API_KEY` or `GOOGLE_API_KEY`. If both differ, the script refuses to guess. Desktop hosts may need a restart to inherit a newly configured environment.
- Simple local fallback: the user runs `<private-python> <SKILL_ROOT>/scripts/deconstruct.py set-key` in their own interactive terminal and pastes into the hidden prompt. The agent must not collect the key or pass it through a tool argument. Input is not echoed or put in shell history. The helper writes `~/.config/deconstruct-audio/credentials.json` with owner-only permissions on POSIX. This is a local plaintext file, not an encrypted vault. On Windows, prefer the host secret manager; otherwise verify that the user's profile folder has a private ACL before local storage.

`DECONSTRUCT_AUDIO_CONFIG_DIR` can point to an absolute private location outside the skill/repository. Never bundle this directory. Environment keys take precedence over the saved local key. Do not print configuration files merely to check whether a key exists.

## 3. Verify the actual audio route

After the user agrees to the explained Google API use, run `verify`. It sends a one-second generated tone, not their recording, and checks for a complete audio response. This may be billable. The default model is configurable; it is not a promise of future availability. A successful test prints `AUDIO_API_VERIFIED` and saves the model and verification time. No retries or fallback to another model occur automatically.

If this fails, use troubleshooting. Do not mark setup complete. Local-only measurement remains available.

## 4. Optional Brain connection

Ask one question: "Do you already have SunoGPT's Brain set up locally, in a chat project, or not yet?"

- Local: ask for its folder, then follow [brain.md](brain.md). Do not search the user's whole disk or import their personal library.
- Chat project or Custom GPT: explain the report handoff described in brain.md. This is manual integration, not an API connection.
- No Brain: skip it. This skill works independently and does not include the Brain package.

The user may decline or postpone. Record only a selected local path, not inferred preferences. Never make Brain purchase or setup a requirement.

## 5. Finish with a first-use example

Run `finish-setup` only after successful API verification and after the Brain question has been answered or skipped. Say whether the state is standalone, local Brain path configured and sources read, or manual report handoff. Do not claim end-to-end song generation.

Explain that the user can attach a recording and ask for its sound breakdown, compare two independently analyzed recordings, or ask for a Suno prompt based on a reviewed analysis. Analysis supports one file per run, up to 30 minutes; longer inputs need an explicit excerpt. Normal runs save separate report folders and preserve the source audio. Ask for their first audio file if none is already supplied.

On later runs, skip the walkthrough when configured. Repeat only the failed or changed step. A new model or replaced credential should be verified again. `doctor` does not make network calls.
