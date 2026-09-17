from pathlib import Path
from types import SimpleNamespace
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import stems
import deconstruct as d

# A stem the cache is allowed to trust. The old fixture wrote 16 bytes, which
# under the size contract is exactly what a truncated run leaves behind, so a
# fake producing it would be simulating a corrupt separation rather than a
# successful one.
STEM_BYTES = b'RIFF' + b'\0' * (stems.MIN_STEM_BYTES * 2)


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
                target = out / f'{name}.wav'
                # A planted directory stands where a stem file belongs in the
                # corrupt-cache tests. Real demucs would fail against it; the
                # property under test is that separation is re-attempted at
                # all, so clear the way and let the call complete.
                if target.is_dir():
                    shutil.rmtree(target)
                target.write_bytes(STEM_BYTES)

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


class CorruptCacheTests(unittest.TestCase):
    """A cached separation counted as complete when all six paths merely
    existed. A directory, a zero-byte file, or a file truncated by an
    interrupted run therefore came back as a successful result, and because
    the cache short-circuits before demucs is ever reached, it came back
    that way forever.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.audio = self.path / 'song.wav'
        self.audio.write_bytes(b'RIFF0000WAVEfake')
        self.runs = []

    def _run(self, produced=stems.STEM_NAMES):
        def run(cmd, **kwargs):
            self.runs.append(cmd)
            out = stems.stem_cache_dir(self.audio, self.path) / 'htdemucs_6s' / self.audio.stem
            out.mkdir(parents=True, exist_ok=True)
            for name in produced:
                target = out / f'{name}.wav'
                if target.is_dir():
                    shutil.rmtree(target)
                target.write_bytes(STEM_BYTES)

            class Done:
                returncode = 0
                stdout = ''
                stderr = ''
            return Done()
        return run

    def _populate(self):
        with patch('subprocess.run', self._run()):
            paths = stems.separate(self.audio, self.path)
        self.runs.clear()
        return paths

    def _assert_rerun_after(self, damage):
        paths = self._populate()
        damage(paths['bass'])
        with patch('subprocess.run', self._run()):
            result = stems.separate(self.audio, self.path)
        self.assertEqual(len(self.runs), 1,
                         'demucs was not re-run, so the corrupt cache was trusted')
        self.assertEqual(set(result), set(stems.STEM_NAMES))
        for path in result.values():
            self.assertTrue(stems.usable_stem(path))

    def test_a_zero_byte_stem_does_not_satisfy_the_cache(self):
        self._assert_rerun_after(lambda p: p.write_bytes(b''))

    def test_a_directory_named_like_a_stem_does_not_satisfy_the_cache(self):
        def to_directory(path):
            path.unlink()
            path.mkdir()
        self._assert_rerun_after(to_directory)

    def test_a_truncated_stem_does_not_satisfy_the_cache(self):
        # An interrupted write leaves a short but non-empty file. Header-only
        # WAV is 44 bytes, so existence and non-emptiness both say yes to it.
        self._assert_rerun_after(lambda p: p.write_bytes(b'RIFF' + b'\0' * 40))

    def test_the_predicate_rejects_each_unusable_shape(self):
        paths = self._populate()
        good = paths['drums']
        self.assertTrue(stems.usable_stem(good))
        empty = self.path / 'empty.wav'
        empty.write_bytes(b'')
        self.assertFalse(stems.usable_stem(empty))
        short = self.path / 'short.wav'
        short.write_bytes(b'RIFF' + b'\0' * 40)
        self.assertFalse(stems.usable_stem(short))
        folder = self.path / 'folder.wav'
        folder.mkdir()
        self.assertFalse(stems.usable_stem(folder))
        self.assertFalse(stems.usable_stem(self.path / 'absent.wav'))

    def test_a_truncated_fresh_stem_is_an_error_not_a_returned_result(self):
        # demucs exiting 0 is not proof it wrote usable audio. The same
        # predicate guards the fresh result, so a short stem is named rather
        # than handed back, and the next call re-runs instead of caching it.
        def run(cmd, **kwargs):
            self.runs.append(cmd)
            out = stems.stem_cache_dir(self.audio, self.path) / 'htdemucs_6s' / self.audio.stem
            out.mkdir(parents=True, exist_ok=True)
            for name in stems.STEM_NAMES:
                (out / f'{name}.wav').write_bytes(
                    b'' if name == 'vocals' else STEM_BYTES)

            class Done:
                returncode = 0
                stdout = ''
                stderr = ''
            return Done()

        with patch('subprocess.run', run):
            with self.assertRaises(stems.SeparationError) as ctx:
                stems.separate(self.audio, self.path)
        self.assertIn('vocals', str(ctx.exception))


class UnusableInputTests(unittest.TestCase):
    """Passing a directory reached source_hash and raised an uncaught
    IsADirectoryError, which escaped as a raw exception type instead of the
    project's authored-message contract. Unusable inputs are now named before
    anything is hashed or spawned, and only project-authored text reaches the
    user: an OS error string would leak system detail through the one channel
    the project controls.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()

    def _cases(self):
        missing = self.path / 'missing.wav'
        folder = self.path / 'a_folder'
        folder.mkdir()
        empty = self.path / 'empty.wav'
        empty.write_bytes(b'')
        cases = [('missing', missing, 'no such audio file'),
                 ('directory', folder, 'folder'),
                 ('empty', empty, 'empty')]
        if os.geteuid() != 0:  # root bypasses read permissions
            blocked = self.path / 'blocked.wav'
            blocked.write_bytes(b'RIFF0000WAVEfake')
            blocked.chmod(0o000)
            self.addCleanup(blocked.chmod, 0o600)
            cases.append(('unreadable', blocked, 'read'))
        return cases

    def test_every_unusable_input_gets_an_authored_message(self):
        def never(cmd, **kwargs):
            raise AssertionError('separation was spawned on an unusable input')

        for name, target, expected in self._cases():
            with self.subTest(input=name):
                with patch('subprocess.run', never):
                    with self.assertRaises(stems.SeparationError) as ctx:
                        stems.separate(target, self.path / 'cache')
                message = str(ctx.exception)
                self.assertIn(expected, message.lower())
                # Never a raw OS error string, never a bare exception class.
                for leak in ('IsADirectoryError', 'PermissionError', 'OSError',
                             'Errno', 'errno', 'Traceback'):
                    self.assertNotIn(leak, message,
                                     f'{leak!r} leaked into {message!r}')


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


@unittest.skipUnless(os.environ.get('DECONSTRUCT_AUDIO_RUN_SEPARATION') == '1',
                     'set DECONSTRUCT_AUDIO_RUN_SEPARATION=1 to run real separation')
class SeparationIntegrationTests(unittest.TestCase):
    def test_real_separation_produces_six_usable_stems(self):
        source = os.environ.get('DECONSTRUCT_AUDIO_TEST_TRACK')
        self.assertTrue(source, 'set DECONSTRUCT_AUDIO_TEST_TRACK to an audio file')
        with tempfile.TemporaryDirectory() as tmp:
            result = stems.separate(Path(source), Path(tmp))
            self.assertEqual(set(result), set(stems.STEM_NAMES))
            for name, path in result.items():
                # Reads the constant rather than repeating 1024, so this test
                # and stems.usable_stem cannot drift to different definitions
                # of a usable stem.
                self.assertTrue(stems.usable_stem(path), f'{name} stem is not usable')
                self.assertGreaterEqual(path.stat().st_size, stems.MIN_STEM_BYTES,
                                        f'{name} stem is empty')


if __name__ == '__main__':
    unittest.main()
