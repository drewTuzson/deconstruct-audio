from pathlib import Path
from types import SimpleNamespace as Obj
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import deconstruct as d

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        env = patch.dict(os.environ, {'DECONSTRUCT_AUDIO_CONFIG_DIR': str(self.path / 'private')})
        env.start(); self.addCleanup(env.stop)
        for name in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_MODEL'):
            os.environ.pop(name, None)

    def test_missing_key_and_conflicting_keys(self):
        with self.assertRaises(d.SkillError): d.api_key()
        os.environ['GEMINI_API_KEY'] = 'test-a'
        os.environ['GOOGLE_API_KEY'] = 'test-b'
        with self.assertRaises(d.SkillError): d.api_key()

    def test_config_is_external_and_merge_is_explicit(self):
        d.save_config({'model': 'example', 'brain_path': '/example'})
        self.assertEqual(d.config()['model'], 'example')
        self.assertFalse((ROOT / 'config.json').exists())
        if os.name != 'nt':
            self.assertEqual((d.config_dir() / 'config.json').stat().st_mode & 0o077, 0)

    def test_hidden_key_refuses_non_terminal(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaises(d.SkillError): d.set_key()
        self.assertFalse((d.config_dir() / 'credentials.json').exists())

    def test_key_storage_hides_value_and_invalidates_setup(self):
        d.save_config({'onboarding_complete': True, 'verified_model': 'example'})
        output = io.StringIO()
        with patch('sys.stdin.isatty', return_value=True), patch.object(d.getpass, 'getpass', return_value='synthetic-fixture-secret'), contextlib.redirect_stdout(output):
            d.set_key()
        self.assertNotIn('synthetic-fixture-secret', output.getvalue())
        self.assertEqual(d.api_key(), 'synthetic-fixture-secret')
        self.assertFalse(d.config()['onboarding_complete'])
        self.assertNotIn('verified_model', d.config())
        if os.name != 'nt':
            self.assertEqual((d.config_dir() / 'credentials.json').stat().st_mode & 0o077, 0)

    def test_doctor_explains_malformed_settings_and_credentials(self):
        private = d.config_dir(); private.mkdir(parents=True)
        for value in ('{', '[]', 'null', '{"model": null}', '{"onboarding_complete": "yes"}'):
            with self.subTest(config=value):
                (private / 'config.json').write_text(value, encoding='utf-8')
                output = io.StringIO()
                with contextlib.redirect_stdout(output): d.doctor()
                result = json.loads(output.getvalue())
                self.assertFalse(result['config_valid'])
                self.assertFalse(result['onboarding_complete'])
                self.assertIn('config.json', result['config_issue'])
        (private / 'config.json').unlink()
        for value in ('{', '[]', 'null', '{"api_key": null}', '{"api_key":" "}'):
            with self.subTest(credentials=value):
                path = private / 'credentials.json'
                path.write_text(value, encoding='utf-8'); path.chmod(0o600)
                output = io.StringIO()
                with contextlib.redirect_stdout(output): d.doctor()
                result = json.loads(output.getvalue())
                self.assertFalse(result['key_present_not_verified'])
                self.assertIn('set-key', result['key_issue'])
        os.environ['GEMINI_API_KEY'] = '   '
        with self.assertRaises(d.SkillError): d.api_key()

    def test_response_requires_complete_text_and_ignores_thoughts(self):
        c = Obj(finish_reason='STOP', content=Obj(parts=[Obj(text='internal', thought=True), Obj(text='heard', thought=False)]))
        self.assertEqual(d.response_text(Obj(candidates=[c])), 'heard')
        for reason in ('MAX_TOKENS', 'SAFETY', None):
            c.finish_reason = reason
            with self.assertRaises(d.SkillError): d.response_text(Obj(candidates=[c]))
        with self.assertRaises(d.SkillError): d.response_text(Obj(candidates=[]))

    def test_brain_connection_does_not_edit_source(self):
        brain = self.path / 'project' / 'Brain'; brain.mkdir(parents=True)
        source = brain / 'SYSTEM-PROMPT-FULL.txt'; source.write_text('Fixture instructions')
        before = d.file_hash(source)
        root, files = d.brain_sources(brain.parent)
        self.assertEqual(root, brain); self.assertEqual(files, [source])
        self.assertEqual(d.file_hash(source), before)
        with self.assertRaises(d.SkillError): d.brain_sources(self.path / 'absent')

    def test_no_upload_for_small_inline_and_cleanup_for_large_failure(self):
        small = self.path / 'audio.flac'; small.write_bytes(b'fake')
        response = Obj(candidates=[Obj(finish_reason='STOP', content=Obj(parts=[Obj(text='description', thought=False)]))])
        c = Obj(files=Obj())
        with patch.object(d, 'generate', return_value=response):
            self.assertEqual(d.listen(c, 'example', small, 'prompt'), 'description')
        with small.open('wb') as f: f.truncate(12_000_001)
        calls = []
        remote = Obj(name='files/test', uri='https://example.invalid/file', state='ACTIVE')
        c.files = Obj(upload=lambda **kw: remote, delete=lambda **kw: calls.append(kw['name']))
        with patch.object(d, 'generate', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError): d.listen(c, 'example', small, 'prompt')
        self.assertEqual(calls, ['files/test'])

    def test_model_failure_preserves_measurements_no_finished_report(self):
        os.environ['GEMINI_API_KEY'] = 'test-fixture'
        audio = self.path / 'source.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=0.2', str(audio)], check=True)
        class Context:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(d, 'client', return_value=Context()), patch.object(d, 'listen', side_effect=RuntimeError('mock')):
            with self.assertRaises(RuntimeError): d.run_analysis(audio, self.path / 'out')
        self.assertEqual(len(list((self.path / 'out').glob('*/measurements.json'))), 1)
        self.assertEqual(list((self.path / 'out').glob('*/report.md')), [])

    def test_local_only_twice_is_private_unique_and_valid_json(self):
        audio = self.path / 'private-name.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono', '-t', '0.3', str(audio)], check=True)
        with patch.object(d, 'client', side_effect=AssertionError('network forbidden')):
            a = d.run_analysis(audio, self.path / 'out', True)
            b = d.run_analysis(audio, self.path / 'out', True)
        self.assertNotEqual(a, b)
        data = json.loads((a / 'measurements.json').read_text())
        self.assertEqual(data['key_top3'], [])
        self.assertEqual(data['bpm_histogram'], [])
        self.assertNotIn('private-name', (a / 'measurements.json').read_text())
        self.assertFalse((a / 'report.md').exists())

    def test_musical_measurement_path_is_finite(self):
        import numpy as np
        import soundfile as sf
        from measure import measure
        sr = 22050
        t = np.arange(sr * 12) / sr
        audio = sum(0.1 * np.sin(2 * np.pi * f * t) for f in (261.63, 329.63, 392.0))
        for start in range(0, len(audio), sr // 2):
            n = min(300, len(audio) - start)
            audio[start:start+n] += 0.3 * np.exp(-np.arange(n) / 40)
        path = self.path / 'synthetic.wav'; sf.write(path, audio, sr)
        data = measure(str(path))
        json.dumps(data, allow_nan=False)
        self.assertEqual(len(data['key_top3']), 3)
        self.assertTrue(data['bpm_histogram'])
        self.assertTrue(any(abs(x[0] - 120) < 5 for x in data['bpm_histogram']))
        self.assertIsNotNone(data['integrated_lufs'])

    def test_client_configuration_can_be_constructed_offline(self):
        os.environ['GEMINI_API_KEY'] = 'synthetic-test-key'
        with d.client() as c:
            self.assertIsNotNone(c.models)

    def test_success_creates_reviewable_draft(self):
        os.environ['GEMINI_API_KEY'] = 'test-fixture'
        audio = self.path / 'clip.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=0.2', str(audio)], check=True)
        class Context:
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(d, 'client', return_value=Context()), patch.object(d, 'listen', return_value='## 1. Fixture listening: 音声'):
            run = d.run_analysis(audio, self.path / 'out')
        text = (run / 'report.md').read_text(encoding='utf-8')
        self.assertIn('音声', (run / 'listening.md').read_text(encoding='utf-8'))
        self.assertIn('<!-- CONFLICTS -->', text)
        self.assertIn('<!-- STYLEBOX -->', text)
        self.assertEqual(json.loads((run / 'receipt.json').read_text())['status'], 'draft_needs_agent_review')

if __name__ == '__main__': unittest.main()
