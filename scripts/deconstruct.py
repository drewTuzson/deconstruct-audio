#!/usr/bin/env python3
"""Portable audio deconstruction CLI. Secrets stay outside the skill package."""
from pathlib import Path
import argparse
import datetime as dt
import getpass
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import warnings

import stems
import tempo as tempo_mod

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = 'gemini-3.8-flash'

class SkillError(Exception):
    """A safe, user-facing error without provider response content."""


def config_dir():
    base = os.environ.get('DECONSTRUCT_AUDIO_CONFIG_DIR')
    if base:
        return Path(base).expanduser().resolve()
    return (Path.home() / '.config' / 'deconstruct-audio').resolve()

def config():
    p = config_dir() / 'config.json'
    if not p.exists():
        return {}
    try:
        value = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SkillError('Cannot read config.json. Move that settings file aside and rerun onboarding; keep credentials.json private and unchanged.') from None
    fields = {'model': str, 'brain_path': str, 'verified_model': str,
              'verified_key_digest': str, 'verified_at': str, 'onboarding_complete': bool}
    if not isinstance(value, dict) or any(
        key in value and not isinstance(value[key], kind) for key, kind in fields.items()
    ):
        raise SkillError('Invalid config.json settings. Move that settings file aside and rerun onboarding; keep credentials.json private and unchanged.')
    return value

def save_config(value):
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / 'config.json'
    fd, name = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def api_key():
    a, b = os.environ.get('GEMINI_API_KEY'), os.environ.get('GOOGLE_API_KEY')
    for value in (a, b):
        if value and (not value.strip() or any(c.isspace() for c in value.strip())):
            raise SkillError('An environment API key is blank or contains whitespace. Replace or unset that variable; never paste its value into chat.')
    a, b = a.strip() if a else None, b.strip() if b else None
    if a and b and a != b:
        raise SkillError('Two different API keys are set. Keep only the intended environment variable.')
    if a or b:
        return (a or b).strip()
    p = config_dir() / 'credentials.json'
    if p.exists():
        if os.name != 'nt' and p.stat().st_mode & 0o077:
            raise SkillError('Credential file permissions are too broad. Run chmod 600 on that file.')
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise SkillError('Cannot read credentials.json. Run set-key in your own terminal to replace it; never paste the file into chat.') from None
        value = data.get('api_key') if isinstance(data, dict) else None
        if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value.strip()):
            raise SkillError('Invalid credentials.json. Run set-key in your own terminal to replace it; never paste the file into chat.')
        return value.strip()
    raise SkillError('No API key configured. Follow references/onboarding.md. Never paste the key into chat.')

def set_key():
    if not sys.stdin.isatty():
        raise SkillError('Run set-key yourself in an interactive terminal. Hidden input requires a terminal.')
    cfg = config()
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        value = getpass.getpass('Gemini API key (hidden): ').strip()
    if not value or any(c.isspace() for c in value):
        raise SkillError('Key was empty or contained whitespace. Nothing saved.')
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'api_key': value}, f)
        os.replace(name, folder / 'credentials.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)
    cfg['onboarding_complete'] = False
    cfg.pop('verified_model', None)
    save_config(cfg)
    print('KEY_SAVED. Environment variables take precedence over this local key.')

def client():
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key(), http_options=types.HttpOptions(
        timeout=180000, retry_options=types.HttpRetryOptions(attempts=1)))

def selected_model(cfg=None):
    if cfg is None:
        cfg = config()
    value = os.environ.get('GEMINI_MODEL') or cfg.get('model') or DEFAULT_MODEL
    if not re.fullmatch(r'[A-Za-z0-9._-]+', value):
        raise SkillError('Invalid model ID. Use an exact Gemini model ID without a URL.')
    return value

def response_text(response):
    candidates = getattr(response, 'candidates', None) or []
    if not candidates:
        raise SkillError('Gemini returned no candidate. Check safety or account restrictions; no listening report completed.')
    c = candidates[0]
    reason = getattr(c.finish_reason, 'value', c.finish_reason)
    if reason != 'STOP':
        raise SkillError('Gemini response incomplete or blocked. Finish reason: ' + str(reason))
    parts = getattr(getattr(c, 'content', None), 'parts', None) or []
    text = '\n'.join(p.text for p in parts if getattr(p, 'text', None) and not getattr(p, 'thought', False)).strip()
    if not text:
        raise SkillError('Gemini returned no usable text.')
    return text

def generate(c, model, contents):
    from google.genai import types
    return c.models.generate_content(model=model, contents=contents,
        config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=16384))

def listen(c, model, audio, prompt):
    from google.genai import types
    remote = None
    try:
        # Base64 adds roughly a third. Leave headroom below the 20 MB request limit.
        if audio.stat().st_size <= 12_000_000:
            part = types.Part.from_bytes(data=audio.read_bytes(), mime_type='audio/flac')
        else:
            with audio.open('rb') as f:
                remote = c.files.upload(file=f, config=types.UploadFileConfig(
                    mime_type='audio/flac', display_name='audio-reference'))
            deadline = time.monotonic() + 180
            while getattr(remote.state, 'name', remote.state) == 'PROCESSING':
                if time.monotonic() >= deadline:
                    raise SkillError('Upload processing timed out. No automatic rerun.')
                time.sleep(2)
                remote = c.files.get(name=remote.name)
            if getattr(remote.state, 'name', remote.state) != 'ACTIVE':
                raise SkillError('Uploaded file is not active.')
            part = types.Part.from_uri(file_uri=remote.uri, mime_type='audio/flac')
        return response_text(generate(c, model, [prompt, part]))
    finally:
        if remote is not None:
            try:
                c.files.delete(name=remote.name)
            except Exception:
                print('WARNING: Uploaded-file deletion failed. Remove file ' + str(remote.name)
                      + ' in AI Studio. Cleanup does not erase other provider records.', file=sys.stderr)

def probe(audio):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'format=duration,bit_rate:stream=codec_name,sample_rate,channels',
        '-of', 'json', str(audio)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise SkillError('ffprobe could not decode this file. Supply a supported local audio file.')
    j = json.loads(r.stdout)
    if not j.get('streams'):
        raise SkillError('No audio stream found.')
    duration = float(j.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or duration <= 0 or duration > 1800:
        raise SkillError('This skill handles clips longer than zero and up to 30 minutes. Supply a shorter excerpt for longer recordings.')
    return j

def run_analysis(audio, out, local_only=False):
    audio = audio.expanduser().resolve()
    if not audio.is_file():
        raise SkillError('Audio file not found.')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise SkillError('Missing ' + tool + '. Follow onboarding.')
    meta = probe(audio)
    if not local_only:
        api_key()  # Fail before expensive measurement when setup is missing.
    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    run = out / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:10])
    run.mkdir()
    with tempfile.TemporaryDirectory(prefix='deconstruct-') as tmp:
        normalized = Path(tmp) / 'audio.flac'
        # Decode to FLAC without lossy compression, strip tags, omit source filename.
        result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-i', str(audio), '-map', '0:a:0', '-map_metadata', '-1', '-c:a', 'flac',
            str(normalized)], capture_output=True, timeout=180)
        if result.returncode:
            raise SkillError('Audio conversion failed. Original file was not modified.')
        if normalized.stat().st_size > 1_900_000_000:
            raise SkillError('Decoded audio exceeds this skill upload limit.')
        measured = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'measure.py'),
            str(normalized)], capture_output=True, text=True, timeout=900)
        if measured.returncode:
            raise SkillError('Local measurement failed. Check dependencies or try a standard WAV file.')
        measurements = json.loads(measured.stdout)
        measurements['source_audio'] = meta
        measurements['source_sha256'] = file_hash(audio)
        (run / 'measurements.json').write_text(json.dumps(measurements, indent=2, allow_nan=False), encoding='utf-8')
        if local_only:
            print('LOCAL_MEASUREMENTS=' + str(run / 'measurements.json'))
            return run
        model = selected_model()
        prompt = (ROOT / 'scripts' / 'prompt_body.txt').read_text(encoding='utf-8')
        # Blind first listen avoids feeding uncertain tempo/key/section guesses back to the model.
        try:
            with client() as c:
                heard = listen(c, model, normalized, prompt)
        except Exception:
            print('MEASUREMENTS_RETAINED=' + str(run / 'measurements.json'), file=sys.stderr)
            raise
        (run / 'listening.md').write_text(heard, encoding='utf-8')
        receipt = {'model': model, 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'source_sha256': measurements['source_sha256'], 'audio_sent': 'metadata-stripped FLAC of first audio stream',
            'local_measurements_sent': False, 'status': 'draft_needs_agent_review'}
        (run / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        report = '# Audio deconstruction\n\nStatus: DRAFT, awaiting reconciliation and style translation.\n\n'
        report += '## Local measurements\n\n| Metric | Value |\n|---|---|\n'
        for key, label in [('duration_s', 'Duration (seconds)'), ('integrated_lufs', 'Integrated loudness (LUFS)'), ('lra_lu', 'Loudness range (LU)'), ('true_peak_dbtp', 'True peak (dBTP)'), ('bpm_histogram', 'Tempo candidates (BPM, histogram count)'), ('key_top3', 'Key candidates (correlation, not probability)'), ('segment_boundaries_s', 'Suggested boundaries (seconds)')]:
            value = measurements.get(key)
            report += '| ' + label + ' | ' + (str(value) if value is not None else 'Unavailable') + ' |\n'
        report += '\nMethods: ffmpeg ebur128; librosa onset tempo, chroma profile correlations and feature clustering. Full data: measurements.json.\n\n'
        report += '\n'.join('- ' + n for n in measurements.get('notes', [])) + '\n\n'
        report += '## Gemini listening assessment\n\n' + heard
        report += '\n\n## Reconciliation\n\n<!-- CONFLICTS -->\n\n## Style box translation\n\n<!-- STYLEBOX -->\n'
        (run / 'report.md').write_text(report, encoding='utf-8')
        print('DRAFT_WRITTEN=' + str(run / 'report.md'))
        return run

def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def brain_sources(path):
    root = path.expanduser().resolve()
    if (root / 'Brain').is_dir():
        root = root / 'Brain'
    if (root / 'SYSTEM-PROMPT-FULL.txt').is_file():
        return root, [root / 'SYSTEM-PROMPT-FULL.txt']
    instructions = root / 'INSTRUCTIONS.txt'
    knowledge = sorted((root / 'knowledge').glob('*.md'))
    if instructions.is_file() and knowledge:
        return root, [instructions, *knowledge]
    raise SkillError('Brain layout not recognized. Supply its Brain folder or use the manual connection in references/brain.md.')

def doctor():
    checks = {'python': sys.version.split()[0], 'ffmpeg': bool(shutil.which('ffmpeg')),
              'ffprobe': bool(shutil.which('ffprobe'))}
    for module in ('numpy', 'librosa', 'soundfile', 'google.genai'):
        try:
            checks[module] = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            checks[module] = False
    try:
        checks['key_present_not_verified'] = bool(api_key())
    except SkillError as exc:
        checks['key_present_not_verified'] = False
        checks['key_issue'] = str(exc)
    try:
        cfg = config()
        checks['config_valid'] = True
    except SkillError as exc:
        cfg = {}
        checks['config_valid'] = False
        checks['config_issue'] = str(exc)
    try:
        checks['model'] = selected_model(cfg)
    except SkillError as exc:
        checks['model'] = None
        checks['model_issue'] = str(exc)
    checks['onboarding_complete'] = bool(cfg.get('onboarding_complete'))
    try:
        checks['onboarding_complete'] = checks['onboarding_complete'] and cfg.get('verified_key_digest') == hashlib.sha256(api_key().encode()).hexdigest() and cfg.get('verified_model') == checks['model']
    except SkillError:
        checks['onboarding_complete'] = False
    checks['brain_configured'] = bool(cfg.get('brain_path'))
    if cfg.get('brain_path'):
        try:
            brain_sources(Path(cfg['brain_path']))
            checks['brain_path_valid'] = True
        except SkillError:
            checks['brain_path_valid'] = False
    styles, broken = scan_styles()
    checks['saved_styles'] = len(styles)
    checks['unreadable_style_files'] = broken
    print(json.dumps(checks, indent=2))

MAX_STYLE_CHARS = 5000
MAX_NOTES_CHARS = 2000
STYLE_FIELDS = {'name': str, 'style': str, 'notes': str, 'source': str,
                'created_at': str, 'updated_at': str}

def styles_dir():
    return config_dir() / 'styles'

def style_slug(name):
    """Identity for a saved style. Filesystem-safe by construction, never a path."""
    if not isinstance(name, str):
        raise SkillError('Style name must be text.')
    text = unicodedata.normalize('NFC', name).strip()
    if not text:
        raise SkillError('Style name is empty.')
    if len(text) > 120:
        raise SkillError('Style name is too long. Use 120 characters or fewer.')
    # Unicode letters and digits are kept, so a name in any script keeps its own
    # identity instead of collapsing to the same slug as an unrelated name.
    # Everything else becomes a separator, so '..', '/', and absolute paths
    # cannot survive into a filename.
    slug = ''.join(c if c.isalnum() else '-' for c in text.casefold())
    slug = re.sub(r'-+', '-', slug).strip('-')
    if not slug:
        raise SkillError('Style name must contain at least one letter or number.')
    if len(slug.encode('utf-8')) > 200:
        raise SkillError('Style name is too long for a filename. Use a shorter name.')
    return slug

def style_path(name):
    return styles_dir() / (style_slug(name) + '.json')

def read_style(name):
    p = style_path(name)
    if not p.exists():
        raise SkillError('No saved style named ' + repr(name.strip()) + '. Run list-styles to see what is saved.')
    try:
        value = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SkillError('Cannot read that saved style file. Move it aside and save the style again.') from None
    if not valid_style(value):
        raise SkillError('That saved style file is not valid. Move it aside and save the style again.')
    return value

def valid_style(value):
    """Every field edit-style and write_style rely on, checked in one place."""
    return (
        isinstance(value, dict)
        and not any(key in value and not isinstance(value[key], kind)
                    for key, kind in STYLE_FIELDS.items())
        and isinstance(value.get('style'), str)
        # write_style slugs value['name'], so a record without a usable name is
        # readable but not editable unless it is rejected here too.
        and isinstance(value.get('name'), str) and value['name'].strip()
    )

def secure_styles_dir():
    """mode= only applies when mkdir creates the folder, so tighten an existing one."""
    folder = styles_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt' and folder.stat().st_mode & 0o077:
        try:
            folder.chmod(0o700)
        except OSError:
            raise SkillError('The saved styles folder is readable by other users and its permissions could not be tightened. Run chmod 700 on that folder.') from None
    return folder

def write_style(value):
    """Atomic replace so an interrupted write never truncates a saved style."""
    folder = secure_styles_dir()
    target = folder / (style_slug(value['name']) + '.json')
    fd, name = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return target

def scan_styles():
    """Returns (readable records, count of files skipped as unreadable or invalid).

    Never raises for a broken styles path: doctor reports local state precisely
    when that state is broken.
    """
    folder = styles_dir()
    out, broken = [], 0
    try:
        found = sorted(folder.glob('*.json')) if folder.is_dir() else []
    except OSError:
        return [], 0
    for p in found:
        try:
            value = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            broken += 1
            continue
        if valid_style(value):
            out.append(value)
        else:
            broken += 1
    return out, broken

def all_styles():
    return scan_styles()[0]

def check_text(label, text, limit):
    if not isinstance(text, str) or not text.strip():
        raise SkillError(label + ' is empty.')
    if len(text) > limit:
        raise SkillError(label + ' is too long. Use ' + str(limit) + ' characters or fewer.')
    return text.strip()

def read_style_text(value):
    """'-' reads stdin so a long style never has to survive shell quoting."""
    if value == '-':
        return sys.stdin.read()
    return value

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def cmd_save_style(args):
    slug = style_slug(args.name)
    existing = style_path(args.name).exists()
    if existing and not args.overwrite:
        raise SkillError('A style named ' + repr(slug) + ' already exists. Use edit-style, or pass --overwrite to replace it.')
    record = {
        'name': args.name.strip(),
        'style': check_text('Style text', read_style_text(args.style), MAX_STYLE_CHARS),
        'created_at': read_style(args.name).get('created_at', now()) if existing else now(),
        'updated_at': now(),
    }
    if args.notes:
        record['notes'] = check_text('Notes', args.notes, MAX_NOTES_CHARS)
    if args.source:
        record['source'] = str(args.source)
    write_style(record)
    print(('STYLE_REPLACED ' if existing else 'STYLE_SAVED ') + slug)

def cmd_list_styles(args):
    items = all_styles()
    if not items:
        print('NO_SAVED_STYLES. Save one with save-style.')
        return
    print(json.dumps([
        {'slug': style_slug(x['name']), 'name': x['name'],
         'chars': len(x['style']), 'updated_at': x.get('updated_at', ''),
         'notes': x.get('notes', ''), 'source': x.get('source', '')}
        for x in items], indent=2, ensure_ascii=False))

def cmd_show_style(args):
    print(json.dumps(read_style(args.name), indent=2, ensure_ascii=False))

def cmd_edit_style(args):
    if args.style is None and args.notes is None:
        raise SkillError('Nothing to change. Pass --style, --notes, or both.')
    record = read_style(args.name)
    if args.style is not None:
        record['style'] = check_text('Style text', read_style_text(args.style), MAX_STYLE_CHARS)
    if args.notes is not None:
        if args.notes.strip():
            record['notes'] = check_text('Notes', args.notes, MAX_NOTES_CHARS)
        else:
            # An empty --notes clears the field rather than failing.
            record.pop('notes', None)
    record['updated_at'] = now()
    write_style(record)
    print('STYLE_UPDATED ' + style_slug(record['name']))

def cmd_rename_style(args):
    record = read_style(args.name)
    old = style_path(args.name)
    new_slug = style_slug(args.new_name)
    if new_slug != style_slug(args.name) and style_path(args.new_name).exists():
        raise SkillError('A style named ' + repr(new_slug) + ' already exists. Choose another name.')
    record['name'] = args.new_name.strip()
    record['updated_at'] = now()
    write_style(record)
    if style_slug(args.name) != new_slug:
        old.unlink(missing_ok=True)
    print('STYLE_RENAMED ' + new_slug)

def cmd_delete_style(args):
    p = style_path(args.name)
    if not p.exists():
        raise SkillError('No saved style named ' + repr(args.name.strip()) + '. Nothing deleted.')
    p.unlink()
    print('STYLE_DELETED ' + style_slug(args.name) + '. This cannot be undone.')

def cmd_separate(args):
    out = args.out or (config_dir() / 'cache')
    try:
        paths = stems.separate(args.audio, out)
    except stems.SeparationError as e:
        raise SkillError(str(e)) from None
    for name in stems.STEM_NAMES:
        print(f'STEM_{name.upper()}={paths[name]}')


def cmd_tempo(args):
    target = args.audio
    if args.from_drums:
        try:
            target = stems.separate(args.audio, config_dir() / 'cache')['drums']
        except stems.SeparationError as e:
            raise SkillError(str(e)) from None
        print(f'TEMPO_SOURCE={target}', file=sys.stderr)
    result = tempo_mod.tempo_family(target)
    print(json.dumps(result, indent=2))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for cmd in ('doctor', 'set-key', 'verify', 'finish-setup', 'disconnect-brain', 'forget-key'):
        sub.add_parser(cmd)
    a = sub.add_parser('analyze')
    a.add_argument('audio', type=Path)
    a.add_argument('--out', type=Path, default=Path.cwd() / 'reports')
    a.add_argument('--local-only', action='store_true')
    b = sub.add_parser('connect-brain'); b.add_argument('path', type=Path)
    m = sub.add_parser('set-model'); m.add_argument('model')
    sp = sub.add_parser('separate')
    sp.add_argument('audio', type=Path)
    sp.add_argument('--out', type=Path, default=None)
    tp = sub.add_parser('tempo')
    tp.add_argument('audio', type=Path)
    tp.add_argument('--from-drums', action='store_true',
                    help='Separate first and measure the drums stem. Recommended.')
    sub.add_parser('list-styles')
    s = sub.add_parser('save-style')
    s.add_argument('name')
    s.add_argument('--style', required=True, help="Style text, or '-' to read it from stdin.")
    s.add_argument('--notes', default=None)
    s.add_argument('--source', default=None, help='Report path or other provenance for this style.')
    s.add_argument('--overwrite', action='store_true')
    for cmd in ('show-style', 'delete-style'):
        sub.add_parser(cmd).add_argument('name')
    e = sub.add_parser('edit-style')
    e.add_argument('name')
    e.add_argument('--style', default=None, help="New style text, or '-' to read it from stdin.")
    e.add_argument('--notes', default=None, help='New notes. Pass an empty string to clear them.')
    r = sub.add_parser('rename-style'); r.add_argument('name'); r.add_argument('new_name')
    args = p.parse_args()
    if args.command == 'doctor':
        doctor()
    elif args.command == 'set-key':
        set_key()
    elif args.command == 'forget-key':
        (config_dir() / 'credentials.json').unlink(missing_ok=True)
        print('LOCAL_KEY_REMOVED. Environment variables and provider keys are unchanged.')
    elif args.command == 'verify':
        # Synthetic tone verifies audio input without sending any user's recording.
        with tempfile.TemporaryDirectory() as tmp:
            tone = Path(tmp) / 'test.flac'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=1', str(tone)], check=True, capture_output=True)
            model = selected_model()
            with client() as c:
                listen(c, model, tone, 'Describe the supplied sound in one short sentence.')
            cfg = config(); cfg['verified_model'] = model
            cfg['verified_key_digest'] = hashlib.sha256(api_key().encode()).hexdigest()
            cfg['verified_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
            save_config(cfg)
            print('AUDIO_API_VERIFIED model=' + model)
    elif args.command == 'set-model':
        if not re.fullmatch(r'[A-Za-z0-9._-]+', args.model):
            raise SkillError('Invalid model ID.')
        cfg = config(); cfg['model'] = args.model; cfg['onboarding_complete'] = False
        save_config(cfg); print('MODEL_SAVED. Run verify before use.')
    elif args.command == 'separate':
        cmd_separate(args)
    elif args.command == 'tempo':
        cmd_tempo(args)
    elif args.command == 'connect-brain':
        root, sources = brain_sources(args.path)
        cfg = config(); cfg['brain_path'] = str(root); save_config(cfg)
        print('BRAIN_PATH_SAVED. Agent must read these sources before claiming integration:')
        for source in sources:
            print(source)
    elif args.command == 'disconnect-brain':
        cfg = config(); cfg.pop('brain_path', None); save_config(cfg)
        print('BRAIN_DISCONNECTED. Source files are unchanged.')
    elif args.command == 'finish-setup':
        cfg = config()
        if cfg.get('verified_model') != selected_model() or cfg.get('verified_key_digest') != hashlib.sha256(api_key().encode()).hexdigest():
            raise SkillError('Run verify successfully with the selected model first.')
        cfg['onboarding_complete'] = True; save_config(cfg)
        print('SETUP_COMPLETE')
    elif args.command == 'analyze':
        run_analysis(args.audio, args.out, args.local_only)
    elif args.command == 'save-style':
        cmd_save_style(args)
    elif args.command == 'list-styles':
        cmd_list_styles(args)
    elif args.command == 'show-style':
        cmd_show_style(args)
    elif args.command == 'edit-style':
        cmd_edit_style(args)
    elif args.command == 'rename-style':
        cmd_rename_style(args)
    elif args.command == 'delete-style':
        cmd_delete_style(args)

if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('Cancelled. No automatic retry.')
    except Exception as exc:
        # Provider exception bodies can contain request data. Never print them.
        code = getattr(exc, 'code', None)
        messages = {400: 'Request rejected. Check model, file format and key restrictions.',
                    401: 'Authentication failed. Replace the key through hidden input.',
                    403: 'Access denied. Check project permissions, region and key restrictions.',
                    404: 'Model or file unavailable. Check current model documentation; no silent fallback.',
                    429: 'Quota or rate limit reached. Check AI Studio usage. No automatic retry.'}
        if code:
            msg = messages.get(code, 'Provider request failed. Check service status before a manual retry.')
            print('ERROR ' + str(code) + ': ' + msg, file=sys.stderr)
        elif isinstance(exc, SkillError):
            print('ERROR: ' + str(exc), file=sys.stderr)
        else:
            print('ERROR: ' + type(exc).__name__ + '. Check setup, file access or network. Details suppressed to protect secrets.', file=sys.stderr)
        sys.exit(1)
