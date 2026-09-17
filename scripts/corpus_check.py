#!/usr/bin/env python3
"""Run every corpus track twice and report whether the sheet held still.

Stability is a gate rather than an assumption because a fact sheet that moves
between runs cannot support a comparison. Note that a rerun here does NOT
re-exercise separation: the stems are cached by source hash, so the second
call reads the same stems. This gate proves the measurement layer is
deterministic, not the separation layer.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts as facts_mod

HOME = Path(os.path.expanduser('~'))
DESKTOP = HOME / 'Desktop' / 'mydaiarytoyou!'
# Axes every track must resolve. section_count is deliberately absent: it is
# UNKNOWN by construction on every track and always will be.
CORE_AXES = ('tempo', 'key', 'tuning', 'intro_seconds', 'loudness')

CORPUS = [
    {'name': 'Murder, She Wrote',
     'audio': HOME / 'Downloads' /
              'mydiarytoyou! - Murder, She Wrote (Official Visualizer).mp3',
     'stems': None},
    {'name': 'The Danger of Caring',
     'audio': DESKTOP / 'The Danger of Caring' /
              'mydiarytoyou! - The Danger of Caring (Official Visualizer).mp3',
     'stems': DESKTOP / 'The Danger of Caring'},
    {'name': 'Wrong Turn',
     'audio': DESKTOP / 'Wrong Turn' /
              'mydiarytoyou! - Wrong Turn (Official Visualizer).mp3',
     'stems': DESKTOP / 'Wrong Turn'},
]


def cache_root():
    """Honour DECONSTRUCT_AUDIO_CONFIG_DIR, which relocates the whole dir."""
    override = os.environ.get('DECONSTRUCT_AUDIO_CONFIG_DIR')
    base = Path(override) if override else HOME / '.config' / 'deconstruct-audio'
    return base / 'cache'


def stable(sheet_a, sheet_b):
    a, b = dict(sheet_a), dict(sheet_b)
    a.pop('generated_at', None)
    b.pop('generated_at', None)
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def slug(name):
    return name.lower().replace(',', '').replace(' ', '-')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rerun', action='store_true',
                        help='Measure each track twice and compare.')
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()

    held, checked, resolved = 0, 0, 0
    for track in CORPUS:
        if not track['audio'].exists():
            print(f'TRACK={track["name"]} STABLE=missing PATH={track["audio"]}')
            continue
        first = facts_mod.fact_sheet(track['audio'], stems_dir=track['stems'],
                                     cache_root=cache_root())
        if args.rerun:
            second = facts_mod.fact_sheet(track['audio'],
                                          stems_dir=track['stems'],
                                          cache_root=cache_root())
            ok = stable(first, second)
            checked += 1
            held += 1 if ok else 0
            state = 'yes' if ok else 'no'
        else:
            # Never print yes for something nothing compared. Revision 1 did,
            # and a run without the flag reported CORPUS_STABLE=3/3 having
            # compared nothing at all.
            state = 'unchecked'
        projected = facts_mod.scorable(first)
        unresolved = sorted(a for a, e in first['facts'].items()
                            if e['confidence'] == 'UNKNOWN')
        # A track that silently loses a core axis must not leave the gate green.
        # Revision 2 printed CORPUS_STABLE=3/3 and exit 0 for a corpus where one
        # track had lost its tuning axis entirely, because an axis that resolves
        # to UNKNOWN is perfectly stable across reruns.
        lost = [a for a in CORE_AXES if a in unresolved]
        resolved += 0 if lost else 1
        print(f'TRACK={track["name"]} STABLE={state} '
              f'CORE={"ok" if not lost else "lost:" + ",".join(lost)} '
              f'SCORABLE={json.dumps(projected, sort_keys=True)} '
              f'UNRESOLVED={",".join(unresolved) or "none"}')
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f'facts-{slug(track["name"])}.json').write_text(
                json.dumps(first, indent=2, allow_nan=False), encoding='utf-8')
            (args.out / f'scorable-{slug(track["name"])}.json').write_text(
                json.dumps(projected, indent=2, allow_nan=False),
                encoding='utf-8')
    print(f'CORPUS_RESOLVED={resolved}/{len(CORPUS)} CORE={",".join(CORE_AXES)}')
    if args.rerun:
        print(f'CORPUS_STABLE={held}/{len(CORPUS)}')
        return 0 if (held == len(CORPUS) and resolved == len(CORPUS)) else 2
    print(f'CORPUS_STABLE=unchecked/{len(CORPUS)}')
    return 0 if resolved == len(CORPUS) else 2


if __name__ == '__main__':
    raise SystemExit(main())
