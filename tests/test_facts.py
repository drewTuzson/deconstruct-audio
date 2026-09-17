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


if __name__ == '__main__':
    unittest.main()
