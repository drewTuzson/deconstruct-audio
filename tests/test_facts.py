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


if __name__ == '__main__':
    unittest.main()
