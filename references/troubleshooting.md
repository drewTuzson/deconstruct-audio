# Troubleshooting and maintenance

| Situation | Next action |
|---|---|
| Missing Python, ffmpeg, ffprobe or module | Run doctor, then the relevant onboarding dependency step using the private environment Python. |
| No key or conflicting environment keys | Use the host secret store or hidden set-key prompt. Keep only the intended environment key. Never paste it into chat. |
| Invalid config.json | Move only that settings file aside and rerun onboarding. Keep credentials.json private and unchanged. Local-only measurement can still run. |
| Invalid credentials.json or blank key | Use set-key in your own terminal to replace the saved key, or replace the relevant environment variable. Do not share the broken file or its contents. |
| 400, 401 or 403 | Check key, project access, current key restrictions, supported region and model. Do not automatically enable billing. |
| 404 or unavailable model | Check current Google model documentation. Use `set-model <exact-model-id>`, then verify. Do not silently substitute a more expensive model. |
| 429 | Check project quota and usage in AI Studio. Stop; retry manually after resolving the limit. |
| Network timeout or server error | Check network and service status. A timed-out request may still have been processed. No automatic retry. |
| Empty, blocked or truncated response | Retain measurements. No finished listening report exists. Do not invent the missing sections. |
| Short clip, silence, percussion-only, unusual tuning | Keep uncertainty. Tempo/key can be unavailable or misleading. Major/minor key templates are not universal. |
| Long or large file | Skill limit is 30 minutes and 1.9 GB decoded audio. Ask for an explicit excerpt; do not trim silently. Larger accepted files use Files API without lossy compression. |
| Remote cleanup warning | Delete only the named file from this run. Do not bulk-delete other project uploads. Provider retention rules still apply. |
| Brain folder moved or not recognized | Reconnect the correct path, use the manual handoff, or continue standalone with disclosure. |

## What gets saved

Run folder: measurements.json, listening.md, receipt.json and report.md. An optional suno-prompt.md is created by the agent. They contain analysis of user audio and should be treated as user content. Reports use a unique run ID, no source path or filename. Source hashes can still correlate recordings; remove them when anonymous sharing matters.

Private config directory: config.json stores onboarding state, model, verification time and optional Brain path. Optional credentials.json contains the local key. Temporary normalized audio is removed on ordinary completion and handled exceptions. Abrupt process termination can leave operating-system temporary files; remove only the applicable deconstruct temporary directory after confirming no run is using it.

## Change, reset or uninstall

Run set-key to replace the local key, then verify. Environment keys take precedence. Run forget-key to delete only the locally saved credential; revoke keys in AI Studio separately if needed. Removing the local file does not revoke the provider credential. Remove environment credentials through the system that configured them.

Use disconnect-brain to clear the saved Brain path. To reinstall, replace the skill's code and recreate its private environment; config and reports remain outside the package. To uninstall, remove the installed skill folder and, if desired, its specific private configuration folder and selected reports. Do not delete the Brain. Never package .venv, .env, credentials, reports or personal settings for distribution.

## Maintainer checks

Run tests with `python -m unittest discover -s tests -v` from the skill folder. Run the host's skill frontmatter validator if available. On a clean environment, run setup, doctor and verify, followed by a representative user-authorized recording. Offline/mocked tests cannot establish real API access or musical quality. Recheck current model availability, SDK compatibility and account behavior before claiming a new release is live-tested.

Official references, checked September 15, 2026:

- [Keys](https://ai.google.dev/gemini-api/docs/api-key)
- [Audio](https://ai.google.dev/gemini-api/docs/audio)
- [Generate content audio endpoint](https://ai.google.dev/gemini-api/docs/generate-content/audio)
- [Files and deletion](https://ai.google.dev/gemini-api/docs/files)
- [Models](https://ai.google.dev/gemini-api/docs/models)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing)
