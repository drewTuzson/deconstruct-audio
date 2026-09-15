# Install Deconstruct Audio

## Local agent with skill support

1. Extract the package. Put the `deconstruct-audio` folder in your host's skills directory. Common locations are `~/.claude/skills/` for Claude Code and `~/.codex/skills/` for Codex. Keep SKILL.md directly inside the folder. Back up an existing version before replacing it.
2. Start or refresh a session in that host and ask it to set up the deconstruct-audio skill. It should read SKILL.md and guide dependency installation, private Gemini key entry, an audio API check, and an optional SunoGPT Brain connection. If discovery fails, point the agent directly at SKILL.md.
3. Attach a local audio file and ask for a production breakdown or a Suno style translation.

Setup needs Python 3.10+, ffmpeg/ffprobe, an internet connection and a Gemini API project/key. Your host must allow local scripts. The installer does not include Python, ffmpeg, credentials, a Brain package, or a Suno connection. Review Google API pricing and data handling during onboarding.

## Chat-only environments

Uploading this folder as knowledge does not install its executable dependencies or grant filesystem/API access. Use a local agent to run the analysis, then upload the reviewed report to the chat where your Brain is configured. See references/brain.md.

## Direct commands

After dependencies have been installed with `python3 scripts/setup.py`, use the private environment Python. Replace the example paths with your installation's absolute paths. On Windows use `.venv/Scripts/python.exe`.

```text
<private-python> <skill-root>/scripts/deconstruct.py doctor
<private-python> <skill-root>/scripts/deconstruct.py set-key
<private-python> <skill-root>/scripts/deconstruct.py verify
<private-python> <skill-root>/scripts/deconstruct.py connect-brain <brain-folder>
<private-python> <skill-root>/scripts/deconstruct.py finish-setup
<private-python> <skill-root>/scripts/deconstruct.py analyze <audio-file> --out <report-folder>
```

Run set-key yourself in a terminal with hidden input. Never put a key in the command, chat, or package. The agent completes the draft's reconciliation and style translation after a successful analysis; the script alone produces a draft.
