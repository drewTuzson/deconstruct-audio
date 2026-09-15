# Saved styles

A saved style is style text the user already liked in a real Suno generation, kept so it can be reused. Styles are stored one JSON file per style in the user's configuration folder, outside this package, beside `config.json`. They never contain credentials and are never bundled into a release.

Saving and reuse are local file operations. They do not require Gemini, an API key, completed onboarding, or a prior deconstruction. A style typed from memory is as valid as one lifted from a report.

## Commands

| Intent | Command |
| --- | --- |
| Save | `save-style "<name>" --style "<text>" [--notes "<text>"] [--source <report>] [--overwrite]` |
| List | `list-styles` |
| Read one | `show-style "<name>"` |
| Change text or notes | `edit-style "<name>" [--style "<text>"] [--notes "<text>"]` |
| Rename | `rename-style "<old>" "<new>"` |
| Delete | `delete-style "<name>"` |

Pass `--style -` to read the style text from stdin. Prefer that for anything long or containing quotes, so shell quoting cannot corrupt what gets saved.

Names are matched by a slug, so `Warm Analog Soul`, `warm analog soul` and `WARM  ANALOG  SOUL` are the same style. A slug is a single lowercase token; a name that looks like a path is flattened into one, never followed. Saving over an existing name requires `--overwrite`. Deletion is immediate and cannot be undone, so confirm the exact name with `list-styles` before deleting, and never delete a style the user did not name.

`--source` is provenance only. Record the report folder when the style came from one. A missing or moved source does not invalidate the saved text.

## Applying a saved style

The scripts store and return styles; they never merge one into a prompt. Blending is a judgment call and stays with the agent.

1. Run `show-style` and use the returned `style` value verbatim as the starting text. Do not paraphrase a saved style or re-derive it from its notes.
2. Establish the target prompt. With a Brain configured, follow [brain.md](brain.md) and apply that user's mode, formatting and character budgets. Without one, produce the compact evidence-based translation described in SKILL.md.
3. Merge, and say plainly which parts came from the saved style and which from the new source. Where they genuinely conflict, ask which should win rather than silently averaging them. A saved style is a user preference, so it outranks an analysis interpretation, but it does not override a measured fact: if a style says half-time and the measurement says 148 BPM, surface the disagreement.
4. Count characters against the loaded Brain's rules, after merging. A saved style that fit on its own can push a combined prompt past that user's limit.
5. If the merged result is one the user likes, offer to save it as a new style. Do not overwrite the original without being asked.

Applying a style changes only the delivered prompt. Never edit the reviewed report, `measurements.json` or `listening.md` to match a saved style; the analysis records what was heard, not what the user prefers.
