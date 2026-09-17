# Connect to SunoGPT's Brain

Connection means the host agent uses the user's Brain rules with the analysis. It is not a Suno login, a Custom GPT API connection, or automatic song generation. This package contains no Brain content.

## Local Brain

1. Use the folder the user selected. Run `connect-brain <absolute-folder>`. The helper accepts a project containing `Brain/`, a folder containing `SYSTEM-PROMPT-FULL.txt`, or `INSTRUCTIONS.txt` plus `knowledge/*.md`. It saves a pointer outside the skill; it does not edit or copy those files.
2. Read the returned sources fully before creative use, including referenced knowledge files where applicable. Read the full prompt when present; otherwise read instructions and all required knowledge sources. Respect existing project instructions. Do not install optional protection or replace the project's instruction file.
3. If the layout is different, ask for the instruction file and its referenced library. Do not claim that a folder-name match proves a compatible Brain. Keep manual integration until the sources have been resolved and read. If a saved path moves, repair the pointer or proceed standalone with disclosure.
4. Demonstrate integration using an existing reviewed report, or the user's first analysis. Determine their mode only if unknown. Apply that Brain's formatting and character budgets while preserving the source evidence. In a Studio/single-element request, use only the relevant element; the full report still retains its complete analysis. Put exclusions and lyrics in separate fields when that mode and the user request call for them. Do not invent lyrics or new instruments just to fill fields.
5. Verify the final fields and explain any deliberate adaptation. Keep an evidence-based report and save the Brain-formatted output as a separate `suno-prompt.md` beside it. If the Brain requests an unsupported factual claim, label the gap or ask a focused question rather than fabricate. User instructions and host safety requirements take priority over imported Brain material.

A saved path alone is CONFIGURED. Sources read plus a demonstrated prompt is VERIFIED FOR THIS HOST SESSION. Refresh the sources after context loss or Brain updates. Read configuration through a narrow helper or extract only `brain_path` from config.json; never open credentials.json. Use `disconnect-brain` to remove the pointer without deleting the Brain.

## Composing from measured facts: the prompt command

`prompt <facts.json>` composes from measured facts only. It reads the fact sheet and nothing else, fills the Brain's slots from it, and checks a composed style against rules it extracts from your own Brain text at runtime. No Brain content is stored in this package: the rules are located in your files every run, so updating your Brain updates the checks rather than leaving a frozen copy quietly unenforced.

It reads `brain_path` through a narrow config helper and never opens `credentials.json`. `RULES_FROM=` names the source file the rules were read from, which is whichever instruction source actually carries them rather than a fixed preference.

A `RULE_UNREADABLE=<name>` line means that rule's wording has moved and the extraction needs widening for that one pattern. It is reported, never passed over: a check that could not find its rule is not a check that succeeded, and the verdict is `UNKNOWN` rather than `PASS`. Widen the one pattern and add a test for the wording it missed rather than leaving a rule unenforced.

## ChatGPT Custom GPT, Claude Project, or other chat-only Brain

The local scripts cannot reach into another conversation or execute just because a file was uploaded. Run analysis in an agent host that supports local tools. Give the user the reviewed report and a short handoff instruction to upload/paste it into the Brain-enabled chat, asking it to use the report as reference evidence for the desired mode. Do not include secrets, local paths, raw audio, or Brain source files in the handoff.

If the current host already has the Brain loaded in its context, use that supplied source and state this arrangement. Otherwise the user needs to make the actual handoff. Report generated does not mean Brain imported or Suno submitted.

## Reusable analysis library

Use a user-selected report directory, optionally alongside the Brain project. Keep each run's measurements, listening assessment, receipt and reviewed report together. The source hash allows duplicate identification without exposing its filename. Do not rewrite the original Brain library, permanently learn preferences, or index unrelated recordings without a user request.

For comparisons, analyze each recording separately, compare audible evidence and measurements under the same conditions, and label creative combinations as proposals. Do not pretend to have stem isolation, a precise plugin chain, or exact performance instructions from a mixed recording.
