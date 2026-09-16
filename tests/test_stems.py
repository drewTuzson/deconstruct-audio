from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import stems
import deconstruct as d


class StemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.audio = self.path / 'song.wav'
        self.audio.write_bytes(b'RIFF0000WAVEfake')

    def _fake_run(self, produced):
        def run(cmd, **kwargs):
            out = stems.stem_cache_dir(self.audio, self.path) / 'htdemucs_6s' / self.audio.stem
            out.mkdir(parents=True, exist_ok=True)
            for name in produced:
                (out / f'{name}.wav').write_bytes(b'RIFF0000WAVEfake')

            class Done:
                returncode = 0
                stdout = ''
                stderr = ''
            return Done()
        return run

    def test_returns_all_six_stems(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            result = stems.separate(self.audio, self.path)
        self.assertEqual(set(result), set(stems.STEM_NAMES))
        for p in result.values():
            self.assertTrue(p.exists())

    def test_second_call_reuses_cache_without_rerunning(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            stems.separate(self.audio, self.path)
        calls = []

        def spy(cmd, **kwargs):
            calls.append(cmd)
            raise AssertionError('demucs should not run again')

        with patch('subprocess.run', spy):
            result = stems.separate(self.audio, self.path)
        self.assertEqual(calls, [])
        self.assertEqual(set(result), set(stems.STEM_NAMES))

    def test_missing_stem_is_an_error_not_a_silent_gap(self):
        with patch('subprocess.run', self._fake_run(('drums', 'bass'))):
            with self.assertRaises(stems.SeparationError):
                stems.separate(self.audio, self.path)

    def test_cache_dir_is_private(self):
        with patch('subprocess.run', self._fake_run(stems.STEM_NAMES)):
            stems.separate(self.audio, self.path)
        cache_dir = stems.stem_cache_dir(self.audio, self.path)
        leaf_mode = cache_dir.stat().st_mode & 0o777
        self.assertEqual(leaf_mode, 0o700)
        parent_mode = cache_dir.parent.stat().st_mode & 0o777
        self.assertEqual(parent_mode, 0o700)


class CommandErrorSurfaceTests(unittest.TestCase):
    """A SeparationError from stems.separate must reach the user with its own
    message via cmd_separate/cmd_tempo, not fall through to deconstruct.py's
    generic top-level handler, which would suppress it as 'SeparationError.
    Check setup, file access or network. Details suppressed to protect secrets.'
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.audio = self.path / 'missing.wav'  # deliberately does not exist

    def test_separate_command_surfaces_the_original_message(self):
        args = SimpleNamespace(audio=self.audio, out=self.path / 'cache')
        with patch('stems.separate', side_effect=stems.SeparationError(
                f'No such audio file: {self.audio}')):
            with self.assertRaises(d.SkillError) as ctx:
                d.cmd_separate(args)
        self.assertIn('No such audio file', str(ctx.exception))
        self.assertNotIn('SeparationError', str(ctx.exception))
        self.assertNotIn('Details suppressed', str(ctx.exception))

    def test_tempo_from_drums_surfaces_the_original_message(self):
        args = SimpleNamespace(audio=self.audio, from_drums=True)
        with patch('stems.separate', side_effect=stems.SeparationError(
                f'No such audio file: {self.audio}')):
            with self.assertRaises(d.SkillError) as ctx:
                d.cmd_tempo(args)
        self.assertIn('No such audio file', str(ctx.exception))
        self.assertNotIn('SeparationError', str(ctx.exception))
        self.assertNotIn('Details suppressed', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
