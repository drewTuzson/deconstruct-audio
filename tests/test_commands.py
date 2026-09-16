"""Command-level guarantees: a broken install must still be diagnosable, the
private config directory must stay private whichever command creates it, and
every command must fail with a project-authored message.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import deconstruct as d
import stems

# The audio stack a broken install is missing. doctor exists to report on
# exactly this state, so importing the CLI must not depend on any of it.
AUDIO_STACK = ('librosa', 'numpy', 'soundfile', 'demucs', 'torch')

BLOCKER = '''
import sys

class _Blocked:
    """Refuse the audio stack the way an incomplete install refuses it."""

    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {names!r}:
            raise ModuleNotFoundError('No module named ' + repr(name.split('.')[0]))
        return None

sys.meta_path.insert(0, _Blocked())
sys.path.insert(0, {scripts!r})
'''


class BrokenInstallTests(unittest.TestCase):
    """Regression guard for the module-level `import tempo` that made every
    command, doctor included, die with a raw ModuleNotFoundError traceback
    before the top-level handler could turn it into an authored message.
    """

    def _run(self, body, env=None):
        preamble = BLOCKER.format(names=AUDIO_STACK, scripts=str(SCRIPTS))
        script = textwrap.dedent(preamble) + textwrap.dedent(body)
        environment = dict(os.environ)
        environment.pop('GEMINI_API_KEY', None)
        environment.pop('GOOGLE_API_KEY', None)
        if env:
            environment.update(env)
        return subprocess.run([sys.executable, '-c', script], capture_output=True,
                              text=True, timeout=180, env=environment)

    def test_importing_the_cli_does_not_load_the_audio_stack(self):
        done = self._run('''
            import json
            import deconstruct  # noqa: F401
            loaded = [m for m in {names!r} + ('tempo',) if m in sys.modules]
            print(json.dumps(loaded))
        '''.format(names=AUDIO_STACK))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout.strip()), [])

    def test_doctor_reports_instead_of_crashing_without_the_audio_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self._run('''
                import runpy
                sys.argv = ['deconstruct.py', 'doctor']
                runpy.run_path({script!r}, run_name='__main__')
            '''.format(script=str(SCRIPTS / 'deconstruct.py')),
                env={'DECONSTRUCT_AUDIO_CONFIG_DIR': str(Path(tmp) / 'private')})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        self.assertNotIn('ModuleNotFoundError', done.stderr)
        checks = json.loads(done.stdout)
        self.assertFalse(checks['librosa'])
        self.assertFalse(checks['numpy'])
        self.assertIn('python', checks)


@unittest.skipIf(os.name == 'nt', 'POSIX permission bits')
class ConfigDirPermissionTests(unittest.TestCase):
    """The configuration directory is a hard invariant at 0700: it holds
    credentials.json and the saved styles. mkdir(parents=True, mode=) sets the
    mode on the leaf only and no-ops on an existing directory, so whichever
    command creates it first decides its permissions for good.
    """

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name).resolve()
        self.private = self.tmp / 'private'  # deliberately does not exist yet
        env = patch.dict(os.environ,
                         {'DECONSTRUCT_AUDIO_CONFIG_DIR': str(self.private)})
        env.start()
        self.addCleanup(env.stop)

    def fake_demucs(self, audio):
        def run(cmd, **kwargs):
            out = (stems.stem_cache_dir(audio, d.config_dir() / 'cache')
                   / stems.DEFAULT_MODEL / audio.stem)
            out.mkdir(parents=True, exist_ok=True)
            for name in stems.STEM_NAMES:
                (out / f'{name}.wav').write_bytes(b'RIFF0000WAVEfake')

            class Done:
                returncode = 0
                stdout = ''
                stderr = ''
            return Done()
        return run

    def test_separate_creating_the_config_dir_still_leaves_it_private(self):
        audio = self.tmp / 'song.wav'
        audio.write_bytes(b'RIFF0000WAVEfake')
        args = SimpleNamespace(audio=audio, out=None)
        with patch('subprocess.run', self.fake_demucs(audio)):
            with contextlib.redirect_stdout(io.StringIO()):
                d.cmd_separate(args)
        self.assertEqual(d.config_dir().stat().st_mode & 0o777, 0o700)

    def test_an_existing_loose_config_dir_is_tightened_before_a_write(self):
        self.private.mkdir(parents=True)
        self.private.chmod(0o755)
        d.save_config({'model': 'gemini-3.8-flash'})
        self.assertEqual(d.config_dir().stat().st_mode & 0o777, 0o700)

    def test_the_styles_folder_does_not_leave_its_parent_loose(self):
        d.secure_styles_dir()
        self.assertEqual(d.config_dir().stat().st_mode & 0o777, 0o700)
        self.assertEqual(d.styles_dir().stat().st_mode & 0o777, 0o700)


class ErrorSurfaceTests(unittest.TestCase):
    """Every command fails through the project's own words. Library and
    subprocess output never reaches the user, because it carries local paths
    and, on the provider path, request data.
    """

    def run_cli(self, *argv):
        env = dict(os.environ)
        env['DECONSTRUCT_AUDIO_CONFIG_DIR'] = str(Path(self.tmp) / 'private')
        return subprocess.run([sys.executable, str(SCRIPTS / 'deconstruct.py'), *argv],
                              capture_output=True, text=True, timeout=300, env=env)

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = holder.name

    def test_tempo_on_a_missing_file_prints_no_library_warnings(self):
        missing = Path(self.tmp) / 'missing.wav'
        done = self.run_cli('tempo', str(missing))
        self.assertNotIn('Warning', done.stderr)
        self.assertNotIn('site-packages', done.stderr)
        self.assertNotIn('Traceback', done.stderr)


if __name__ == '__main__':
    unittest.main()
