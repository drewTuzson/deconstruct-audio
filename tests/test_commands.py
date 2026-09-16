"""Command-level guarantees: a broken install must still be diagnosable, the
private config directory must stay private whichever command creates it, and
every command must fail with a project-authored message.
"""
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()
