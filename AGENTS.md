# Agent workflow

Every task in this repo moves through the same four beats. Each one is
backed by a skill from [michaelshimeles/skills](https://github.com/michaelshimeles/skills).

## Workflow

1. **Isolate, `/new-feature`.** Branch a fresh worktree from `origin/main`
   under `.worktrees/` (gitignored), with an `agent/` branch prefix. Never
   build on `main`.
2. **Build, `/code-structure`.** Commands own the "why and when", helpers own
   the reusable "how". See [Architecture](#architecture) for how that maps
   onto `scripts/deconstruct.py`.
3. **Prove, `/evidence-driven-testing`.** Run the checks below and capture
   the before state while the problem still reproduces, which is when it is
   cheapest to record.
4. **Ship, `/before-and-after`, then `/greploop`.** Open the PR with the
   before and after pair in the body. This repo has no visible UI, so the
   evidence is command output pairs and measured numbers, not screenshots.
   Run `/greploop` until Greptile reports 5/5 with zero unresolved comments,
   then present the PR URL.

Run `/unslop` over anything a person reads before you post it: commit
messages, the PR title and body, and edits to these docs.

## Commands and checks

Setup. The main checkout owns the only `.venv/`:

```bash
python3 scripts/setup.py          # builds .venv, installs requirements.txt
```

A worktree does not build its own. `torch` alone is about 2.5 GB, and four
worktrees each holding a copy of it is not a test strategy. Run a worktree's
tests with the main checkout's interpreter by absolute path:

```bash
/Users/drewtuzson/Documents/Projects/deconstruct-audio/.venv/bin/python \
  -m unittest discover -s tests
```

The interpreter supplies the libraries; `discover -s tests` and the
`Path(__file__).parents[1]` in each test resolve against your worktree, so you
are testing your own code. A worktree that needs a dependency the main venv
lacks installs it into that venv, which every worktree then sees.

The full suite is the gate for every PR. Expect `Ran 97 tests ... OK
(skipped=1)` on `f021646`. The summary goes to stderr, so redirect if you are
capturing it.

Environment self-check, which prints dependency and config status as JSON:

```bash
.venv/bin/python scripts/deconstruct.py doctor
```

Running the tests under a bare system `python3` produces six failures that
have nothing to do with your change. They are missing `librosa`,
`soundfile` and `google-genai`. Always use the venv interpreter, and do not
report that baseline as a regression.

## Hard invariants

Break one of these and the PR does not ship, whatever else it fixes.

- **Private files stay private.** The config directory and the saved-styles
  folder are created at `0700`. Private files inside them are written
  through `tempfile.mkstemp`, which creates at `0600`, and moved into place
  with `os.replace`. `api_key` refuses to read `credentials.json` if any
  group or other bit is set. Never widen a mode, never write one of these
  files in place.
- **A key never leaves the machine.** No API key in a command line, a log
  line, an error message, a test fixture or a commit. `set-key` reads it
  from a terminal with hidden input.
- **A style name is an identity, not a path.** Names resolve through
  `style_slug`, which case-folds the name and turns every character that is
  not a letter or digit into a hyphen. Separators cannot survive that, so
  `../../etc/passwd` saves as `etc-passwd.json` inside the styles folder
  rather than escaping it. Any new name-to-file path goes through that slug.
- **Measured data outranks prose.** A model failure keeps
  `measurements.json` and refuses to write a finished report. The draft
  carries `status: draft_needs_agent_review` until an agent reconciles it.
  Applying a saved style never edits `report.md`, `measurements.json` or
  `listening.md`.
- **Judgment lives with the agent, not the script.** The script measures and
  records. Merging a style into a prompt, reconciling the draft and counting
  characters against a Brain's budget are agent work. See
  `references/styles.md`.
- **Uploaded audio is deleted.** Files over 12 MB go to the Files API and
  are deleted in a `finally` block. If deletion fails, the warning naming
  the remote file stays.

## Environment quick reference

- Python 3.10 or newer, plus `ffmpeg` and `ffprobe` on `PATH`. Verified on
  Python 3.14.3 with Homebrew ffmpeg.
- `DECONSTRUCT_AUDIO_CONFIG_DIR` relocates the whole private directory. The
  tests set it to a temp path, which is the only reason running them does
  not touch your real key, model choice or saved styles. Any new test that
  touches config must do the same.
- `GEMINI_API_KEY` and `GOOGLE_API_KEY` take precedence over
  `credentials.json`, which is read only when neither is set. Setting either
  one in a shell silently overrides the stored key, so unset them before you
  trust what `doctor` reports. Setting both to different values is an error.
- Default model is `gemini-3.8-flash`. `set-model` overrides it.
- Audio input is capped at 30 minutes, and duration must be finite and
  above zero.

## Shared resources a worktree does not isolate

- The private config directory is shared across every worktree, so `doctor`
  in your worktree reads your real key and Brain. Point
  `DECONSTRUCT_AUDIO_CONFIG_DIR` somewhere disposable before you experiment
  with `set-key`, `connect-brain` or the style commands.
- `.venv/` is shared too, by the rule above. Installing a dependency from one
  worktree changes what every other worktree sees, so say so in your PR.
- Every Gemini call spends real quota against that key.

## What cannot be tested locally

Model responses. The suite covers the offline paths: client construction,
the measurement pipeline, upload and cleanup behavior, failure handling and
all six style commands. It never calls Gemini. A change to the prompt body
or to response parsing needs a real `analyze` run against a short local
file, with the command and its output pasted into the PR.

## Architecture

`scripts/deconstruct.py` is the boundary. Each `cmd_*` function reads
arguments, decides what should happen and prints a machine-readable result
line such as `DRAFT_WRITTEN=` or `STYLE_SAVED`. Underneath sit the reusable
pieces: `config_dir`, `api_key`, `style_slug`, `check_text` and the atomic
writers. `scripts/measure.py` holds the local signal measurement and knows
nothing about Gemini or config. Keep new work on that split. A command
should not grow its own file-writing or validation logic when a helper
already owns it.

## Multi-agent rules

- Never commit to `main`, and never force-push anywhere. On your own branch,
  `--force-with-lease` only.
- One worktree and one branch per task. Never touch another agent's.
- Scope check before starting: `gh pr list`, then
  `gh pr diff <n> --name-only`. On overlap, stop and ask.
- Keep the worktree until the PR is merged or closed. Then:

  ```bash
  git worktree remove .worktrees/<task-name>
  git branch -D agent/<task-name>
  ```

  `-D` is expected after a squash merge.
- If a conflict resists a confident fix, stop and report it.

## After the merge

This repo is the source for a skill that gets installed by copying the
folder into a host's skills directory, usually `~/.claude/skills/` or
`~/.codex/skills/`. Merging to `main` does not update anyone's installed
copy. Sync it, then confirm there is no drift:

```bash
diff -rq --exclude=.git --exclude=.venv --exclude=__pycache__ \
  --exclude=.worktrees --exclude=.env --exclude=config.json \
  --exclude=credentials.json --exclude=reports --exclude=.DS_Store \
  <repo> <skills-dir>/deconstruct-audio
```
