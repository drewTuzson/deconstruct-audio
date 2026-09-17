from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import facts as f


class FactShapeTests(unittest.TestCase):
    def good(self, **over):
        kwargs = dict(value=80.7, unit='bpm', stem='drums',
                      method=['tempogram-peak'], confidence='KNOW',
                      suno_actionable='direct')
        kwargs.update(over)
        return f.fact(**kwargs)

    def test_a_complete_fact_carries_every_required_field(self):
        result = self.good()
        for key in ('value', 'unit', 'stem', 'band_hz', 'method',
                    'confidence', 'suno_actionable', 'note'):
            self.assertIn(key, result)

    def test_a_fact_without_a_method_is_an_error_not_a_gap(self):
        with self.assertRaises(f.FactError):
            self.good(method=[])

    def test_a_method_must_be_a_list_not_a_bare_string(self):
        with self.assertRaises(f.FactError):
            self.good(method='tempogram-peak')

    def test_an_unknown_confidence_grade_is_refused(self):
        with self.assertRaises(f.FactError):
            self.good(confidence='PROBABLY')

    def test_a_missing_value_is_only_allowed_when_the_grade_is_unknown(self):
        with self.assertRaises(f.FactError):
            self.good(value=None, confidence='INFER')
        self.assertIsNone(self.good(value=None, confidence='UNKNOWN')['value'])

    def test_an_unrecognised_actionable_class_is_refused(self):
        with self.assertRaises(f.FactError):
            self.good(suno_actionable='maybe')

    def test_a_band_is_a_pair_of_numbers_or_nothing(self):
        self.assertEqual(self.good(band_hz=[150, 2500])['band_hz'], [150, 2500])
        self.assertIsNone(self.good()['band_hz'])
        with self.assertRaises(f.FactError):
            self.good(band_hz=[150])

    def test_a_non_finite_value_is_not_a_measurement(self):
        for bad in (float('nan'), float('inf')):
            with self.assertRaises(f.FactError):
                self.good(value=bad)

    def test_a_container_holding_a_flag_is_still_a_measurement(self):
        # instrumentation carries one `active` per stem and a chord entry
        # carries `third_present`. Revision 2 rejected every boolean at every
        # depth and the sheet raised on its third builder for every track.
        result = self.good(value={'piano': {'rms_db': -58.29, 'active': False}})
        self.assertFalse(result['value']['piano']['active'])

    def test_a_bare_boolean_is_still_refused(self):
        with self.assertRaises(f.FactError):
            self.good(value=True)

    def test_a_numpy_scalar_is_coerced_so_json_can_serialise_it(self):
        import json
        import numpy as np
        result = self.good(value=np.float32(80.7))
        self.assertIsInstance(result['value'], float)
        json.dumps(result, allow_nan=False)


import tempfile


class StemAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def _write(self, names):
        for name in names:
            (self.dir / name).write_bytes(b'RIFF0000WAVEfake')

    def _six(self, template='1_Some Track_({}).wav'):
        return [template.format(n.title()) for n in
                ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')]

    def test_adopts_a_supplied_six_stem_folder(self):
        self._write(self._six())
        result = f.adopt_stems(self.dir)
        self.assertEqual(set(result), {'drums', 'bass', 'guitar',
                                       'piano', 'vocals', 'other'})
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))

    def test_adopts_plain_demucs_names(self):
        self._write([f'{n}.wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        self.assertEqual(set(f.adopt_stems(self.dir)),
                         {'drums', 'bass', 'guitar', 'piano', 'vocals', 'other'})

    def test_the_source_mix_sitting_beside_the_stems_is_ignored(self):
        self._write(self._six() + ['Some Track (Official Visualizer).mp3'])
        self.assertEqual(len(f.adopt_stems(self.dir)), 6)

    def test_a_partial_folder_is_an_error_not_a_partial_sheet(self):
        self._write(['1_x_(Drums).wav', '1_x_(Bass).wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        for missing in ('guitar', 'piano', 'vocals', 'other'):
            self.assertIn(missing, str(caught.exception))

    def test_two_files_using_the_same_tagged_form_is_an_error(self):
        self._write(self._six())
        self._write(['2_Some Track_(Drums).wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        self.assertIn('drums', str(caught.exception))

    def test_a_tagged_name_beats_a_loose_one_rather_than_being_ambiguous(self):
        # Deliberate: (Drums) is a more specific claim than a filename that
        # merely contains the word. Preferring it is the whole reason the
        # tagged pass runs first, and treating this as ambiguous would reject
        # a folder that is not actually ambiguous.
        self._write(self._six() + ['drums_scratch_take.wav'])
        result = f.adopt_stems(self.dir)
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))

    def test_two_untagged_files_claiming_one_stem_is_an_error(self):
        self._write([f'{n}.wav' for n in
                     ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other')])
        self._write(['drums take two.wav'])
        with self.assertRaises(f.StemAdoptionError) as caught:
            f.adopt_stems(self.dir)
        self.assertIn('drums', str(caught.exception))

    def test_other_does_not_swallow_a_filename_containing_the_word(self):
        self._write(self._six('1_Another Brother_({}).wav'))
        result = f.adopt_stems(self.dir)
        self.assertTrue(result['other'].name.endswith('(Other).wav'))


import json
import subprocess


def synth_track(path, seconds=32):
    """A click, a low drone and a mid tone. No copyrighted audio in the repo.

    32 seconds, not 16. measure.py sets k from duration // 15, so a 16 second
    fixture yields k = 1 and no section boundaries at all. That made
    test_section_boundaries_are_still_emitted read UNKNOWN when the code was
    right, and, more importantly, it left the intro snap branch with no test
    coverage whatsoever. The snap is the branch that produces the headline
    12.12, and it is on the axis that has been wrong in four consecutive
    versions.
    """
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', f'sine=frequency=110:duration={seconds}',
        '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}',
        '-f', 'lavfi', '-i', f'anoisesrc=d={seconds}:c=pink:a=0.3',
        '-filter_complex', '[0][1][2]amix=inputs=3',
        '-ar', '22050', '-ac', '1', str(path)], check=True)


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.audio = self.dir / 'track.wav'
        synth_track(self.audio)
        self.stems = self.dir / 'stems'
        self.stems.mkdir()
        for name in ('drums', 'bass', 'guitar', 'piano', 'vocals', 'other'):
            (self.stems / f'{name}.wav').write_bytes(self.audio.read_bytes())

    def sheet(self):
        return f.fact_sheet(self.audio, stems_dir=self.stems)

    def test_every_fact_carries_method_and_confidence(self):
        sheet = self.sheet()
        self.assertTrue(sheet['facts'])
        for axis, entry in sheet['facts'].items():
            self.assertTrue(entry['method'], f'{axis} has no method')
            self.assertIn(entry['confidence'], f.CONFIDENCE, axis)
            self.assertIn(entry['suno_actionable'], f.ACTIONABLE, axis)

    def test_the_sheet_names_its_schema_and_its_source(self):
        sheet = self.sheet()
        self.assertEqual(sheet['schema'], f.SCHEMA)
        self.assertEqual(len(sheet['source']['sha256']), 64)
        self.assertEqual(sheet['stems_from'], 'adopted')

    def test_the_whole_sheet_serialises_without_allow_nan(self):
        json.dumps(self.sheet(), allow_nan=False)

    def test_two_runs_on_the_same_audio_agree_apart_from_the_timestamp(self):
        first, second = self.sheet(), self.sheet()
        first.pop('generated_at')
        second.pop('generated_at')
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_an_unknown_axis_is_left_out_of_the_projection_not_passed_as_null(self):
        sheet = self.sheet()
        sheet['facts']['key'] = f.fact(None, 'name', 'guitar', ['chroma'],
                                       'UNKNOWN', 'direct')
        self.assertNotIn('key', f.scorable(sheet))

    def test_harmonic_rhythm_is_unknown_when_it_reports_its_own_floor(self):
        # A run length is an integer of at least 1, so a median of 1.0 means
        # the root changed in every bar. All three corpus tracks report exactly
        # that. An axis reporting its own floor has measured noise.
        entry = self.sheet()['facts']['harmonic_rhythm']
        if entry['confidence'] != 'UNKNOWN':
            self.assertNotEqual(entry['value']['median_chord_bars'], 1.0)
        else:
            self.assertIn('every bar', entry['note'])

    def test_section_count_is_unknown_and_says_why(self):
        entry = self.sheet()['facts']['section_count']
        self.assertEqual(entry['confidence'], 'UNKNOWN')
        self.assertIsNone(entry['value'])
        self.assertIn('generalise', entry['note'])

    def test_section_boundaries_are_still_emitted(self):
        entry = self.sheet()['facts']['section_boundaries']
        self.assertEqual(entry['confidence'], 'INFER')
        self.assertIsInstance(entry['value'], list)

    def test_a_silent_stem_is_reported_absent_rather_than_failing(self):
        import numpy as np
        import soundfile as sf
        y, sr = sf.read(self.stems / 'piano.wav')
        sf.write(self.stems / 'piano.wav', np.zeros_like(y), sr)
        entry = f.fact_sheet(self.audio, stems_dir=self.stems)['facts']['instrumentation']
        self.assertEqual(entry['confidence'], 'INFER')
        self.assertFalse(entry['value']['piano']['active'])

    def test_the_markdown_names_every_axis_and_its_grade(self):
        sheet = self.sheet()
        text = f.render_markdown(sheet)
        for axis in sheet['facts']:
            self.assertIn(axis, text)

    def test_a_partial_stem_folder_refuses_rather_than_emitting_a_partial_sheet(self):
        (self.stems / 'guitar.wav').unlink()
        with self.assertRaises(f.StemAdoptionError):
            f.fact_sheet(self.audio, stems_dir=self.stems)


if __name__ == '__main__':
    unittest.main()
