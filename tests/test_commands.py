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

    def test_doctor_reports_the_separation_dependencies(self):
        # "demucs not installed" is the dominant first-run failure for this
        # branch's separate command, and doctor could not see it.
        with tempfile.TemporaryDirectory() as tmp:
            done = self._run('''
                import runpy
                sys.argv = ['deconstruct.py', 'doctor']
                runpy.run_path({script!r}, run_name='__main__')
            '''.format(script=str(SCRIPTS / 'deconstruct.py')),
                env={'DECONSTRUCT_AUDIO_CONFIG_DIR': str(Path(tmp) / 'private')})
        self.assertEqual(done.returncode, 0, done.stderr)
        checks = json.loads(done.stdout)
        self.assertIn('demucs', checks)
        self.assertIn('torch', checks)
        self.assertFalse(checks['demucs'])
        self.assertFalse(checks['torch'])


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

    def assert_authored(self, done, expected):
        self.assertIn(expected, done.stderr)
        self.assertNotIn('Details suppressed', done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        self.assertNotIn('site-packages', done.stderr)
        self.assertNotIn('Warning', done.stderr)

    def test_tempo_on_a_missing_file_prints_no_library_warnings(self):
        missing = Path(self.tmp) / 'missing.wav'
        done = self.run_cli('tempo', str(missing))
        self.assertNotIn('Warning', done.stderr)
        self.assertNotIn('site-packages', done.stderr)
        self.assertNotIn('Traceback', done.stderr)

    def test_the_three_commands_name_a_missing_audio_file_the_same_way(self):
        missing = Path(self.tmp) / 'missing.wav'
        for command in ('separate', 'tempo'):
            with self.subTest(command=command):
                done = self.run_cli(command, str(missing))
                self.assert_authored(done, f'ERROR: No such audio file: {missing}')
                self.assertEqual(done.returncode, 1)

    def test_tempo_on_an_undecodable_file_says_so_in_our_own_words(self):
        text = Path(self.tmp) / 'notes.txt'
        text.write_text('this is not audio', encoding='utf-8')
        done = self.run_cli('tempo', str(text))
        self.assert_authored(done, 'ERROR: Could not measure tempo from')
        self.assertEqual(done.returncode, 1)

    def test_compare_names_the_side_it_could_not_read(self):
        missing = Path(self.tmp) / 'nowhere.json'
        done = self.run_cli('compare', str(missing), str(missing))
        self.assert_authored(done, 'ERROR: Cannot read the reference fact sheet')

    def test_compare_rejects_malformed_and_non_object_fact_sheets(self):
        bad = Path(self.tmp) / 'bad.json'
        bad.write_text('not json at all', encoding='utf-8')
        self.assert_authored(self.run_cli('compare', str(bad), str(bad)),
                             'ERROR: The reference fact sheet is not valid JSON')
        array = Path(self.tmp) / 'array.json'
        array.write_text('[1, 2, 3]', encoding='utf-8')
        self.assert_authored(self.run_cli('compare', str(array), str(array)),
                             'ERROR: The reference fact sheet must be a JSON object')


REFERENCE_FACTS = {'tempo_bpm': 80.7, 'key': 'F# minor', 'intro_seconds': 12.1,
                   'lra_lu': 4.1, 'low_end_share': 16.4, 'section_count': 7,
                   'lead_register_midi': 42}


class CompareExitCodeTests(unittest.TestCase):
    """A wrapping script gates on the exit code. Parsing stdout for VERDICT=
    was the only way to tell a failing comparison from a passing one, and
    `compare` exited 0 either way.
    """

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.reference = self.write('reference', REFERENCE_FACTS)

    def write(self, name, facts):
        path = self.tmp / f'{name}.json'
        path.write_text(json.dumps(facts), encoding='utf-8')
        return path

    def compare(self, candidate):
        env = dict(os.environ)
        env['DECONSTRUCT_AUDIO_CONFIG_DIR'] = str(self.tmp / 'private')
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'deconstruct.py'), 'compare',
             str(self.reference), str(candidate)],
            capture_output=True, text=True, timeout=120, env=env)

    def test_the_exit_code_carries_the_verdict(self):
        cases = {
            'PASS': (0, dict(REFERENCE_FACTS)),
            'FAIL': (2, dict(REFERENCE_FACTS, low_end_share=4.9)),
            'WARN': (3, dict(REFERENCE_FACTS, key='A major')),
            'UNKNOWN': (4, {}),
        }
        for verdict, (code, facts) in cases.items():
            with self.subTest(verdict=verdict):
                done = self.compare(self.write(verdict.lower(), facts))
                self.assertIn(f'VERDICT={verdict}', done.stdout)
                self.assertEqual(done.returncode, code)

    def test_unknown_stays_distinguishable_from_fail(self):
        nothing_measured = self.compare(self.write('blank', {}))
        failing = self.compare(self.write('bad', dict(REFERENCE_FACTS, low_end_share=4.9)))
        self.assertNotEqual(nothing_measured.returncode, failing.returncode)
        # And neither collides with the code a command failure uses.
        self.assertNotIn(1, (nothing_measured.returncode, failing.returncode))

    def test_a_command_failure_still_exits_one(self):
        done = self.compare(self.tmp / 'nowhere.json')
        self.assertEqual(done.returncode, 1)

    def test_the_report_names_which_file_was_the_reference(self):
        # The two positionals are interchangeable at the shell and a swapped
        # pair still scores every axis, so the report says which was which.
        done = self.compare(self.write('candidate', dict(REFERENCE_FACTS)))
        self.assertIn(f'REFERENCE={self.reference}', done.stdout)
        self.assertIn(f"CANDIDATE={self.tmp / 'candidate.json'}", done.stdout)

    def test_the_help_text_names_both_positionals_and_the_exit_codes(self):
        done = subprocess.run(
            [sys.executable, str(SCRIPTS / 'deconstruct.py'), 'compare', '--help'],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0)
        self.assertIn('reference', done.stdout)
        self.assertIn('candidate', done.stdout)
        for fragment in ('0 PASS', '2 FAIL', '3 WARN', '4 UNKNOWN'):
            self.assertIn(fragment, done.stdout)


if __name__ == '__main__':
    unittest.main()
