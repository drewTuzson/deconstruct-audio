from pathlib import Path
from unittest.mock import patch
import json
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

    def test_a_folder_mixing_one_tagged_name_with_plain_ones_resolves(self):
        # One tagged file used to switch the WHOLE folder to tagged matching,
        # so five perfectly good plain-name stems beside a single `(Drums)`
        # file were reported missing. Each stem is resolved on its own now:
        # tagged when a tagged file claims it, loose when none does.
        self._write(['1_Some Track_(Drums).wav'])
        self._write([f'{n}.wav' for n in
                     ('bass', 'guitar', 'piano', 'vocals', 'other')])
        result = f.adopt_stems(self.dir)
        self.assertEqual(set(result), {'drums', 'bass', 'guitar',
                                       'piano', 'vocals', 'other'})
        self.assertTrue(result['drums'].name.endswith('(Drums).wav'))
        self.assertEqual(result['bass'].name, 'bass.wav')

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

    def test_a_tied_root_histogram_picks_the_same_winner_in_every_process(self):
        # Set iteration order depends on the hash seed, so max(set(roots), ...)
        # returned a different winner from process to process on a tied
        # histogram. That value decides the key fact's grade and its note, both
        # of which are written into facts.json for a person to read.
        #
        # This runs in subprocesses on purpose. Inside one interpreter the seed
        # is fixed, which is exactly why corpus_check's rerun gate reports
        # STABLE=yes for a value that is not stable: both of its passes share
        # one process.
        import os
        import subprocess
        script = (
            'import sys; sys.path.insert(0, %r); import facts; '
            "print(facts._most_common_root(['E','E','E','A','A','A','C#','B']))"
            % str(ROOT / 'scripts'))
        seen = set()
        for seed in ('1', '2', '3', '4'):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run([sys.executable, '-c', script], env=env,
                                 capture_output=True, text=True, check=True)
            seen.add(out.stdout.strip())
        self.assertEqual(len(seen), 1,
                         f'winner varied with the hash seed: {sorted(seen)}')

    def test_the_root_tie_break_is_the_pitch_name(self):
        self.assertEqual(f._most_common_root(['E', 'E', 'A', 'A']), 'A')
        self.assertEqual(f._most_common_root(['B', 'B', 'D', 'D']), 'B')
        self.assertEqual(f._most_common_root(['G', 'C', 'C']), 'C')
        self.assertIsNone(f._most_common_root([]))

    def test_loudness_needs_all_three_properties_to_claim_know(self):
        # loudness is the only axis the narrowed spec clause still lets reach
        # KNOW, on the grounds that BS.1770-4 fixes every parameter. That
        # argument covers a complete reading. Two thirds of one is a single
        # method with a gap in it, which is INFER.
        import measure as measure_mod
        real = measure_mod.measure

        def partial(path):
            local = dict(real(path))
            local['true_peak_dbtp'] = None
            return local

        measure_mod.measure = partial
        try:
            entry = f.fact_sheet(self.audio, stems_dir=self.stems)['facts']['loudness']
        finally:
            measure_mod.measure = real
        self.assertEqual(entry['confidence'], 'INFER')
        self.assertIn('true_peak_dbtp', entry['note'])
        self.assertIsNotNone(entry['value']['lra_lu'])

    def test_a_complete_loudness_reading_is_the_one_axis_that_knows(self):
        entry = self.sheet()['facts']['loudness']
        self.assertEqual(entry['confidence'], 'KNOW')
        for key in ('integrated_lufs', 'lra_lu', 'true_peak_dbtp'):
            self.assertIsNotNone(entry['value'][key], key)

    def test_the_projection_uses_compare_s_own_axis_names(self):
        import compare
        projected = f.scorable(self.sheet())
        self.assertTrue(projected)
        for axis in projected:
            self.assertIn(axis, compare.GATES, f'{axis} is not a compare axis')

    def test_a_partial_stem_folder_refuses_rather_than_emitting_a_partial_sheet(self):
        (self.stems / 'guitar.wav').unlink()
        with self.assertRaises(f.StemAdoptionError):
            f.fact_sheet(self.audio, stems_dir=self.stems)


if __name__ == '__main__':
    unittest.main()


class TempoAxisPairTests(unittest.TestCase):
    """The builder contract the two tempo axes share.

    tempo and tempo_family describe one measurement, so _tempo_fact takes it
    once and parks the family fact for the tempo_family builder to hand back.
    That makes the pair load bearing on BUILDERS order and on there being
    exactly one tempo_family() call, and nothing else in the suite would notice
    a reorder: every other test builds a family axis by hand.
    """

    RESULT = {'primary': 80.7, 'confidence': 'INFER',
              'disagreement': 'a competing metrical level',
              'family': [{'bpm': 161.5, 'ratio': '2x', 'method': 'tempogram',
                          'relative_strength': 0.9},
                         {'bpm': 107.7, 'ratio': '4/3',
                          'method': 'beat_track'}]}

    def build(self):
        """Run the BUILDERS in their real order, over one mocked measurement."""
        calls = []

        def fake_tempo_family(path):
            calls.append(path)
            return json.loads(json.dumps(self.RESULT))

        built, paths = {}, {'drums': 'drums.wav'}
        with patch.object(f.tempo_mod, 'tempo_family', fake_tempo_family):
            for name, builder in f.BUILDERS:
                if name not in ('tempo', 'tempo_family'):
                    continue
                built[name] = builder(paths, {}, None, 44100, {}, built)
        return built, calls

    def test_tempo_is_built_before_its_family(self):
        order = [name for name, _ in f.BUILDERS]
        self.assertLess(order.index('tempo'), order.index('tempo_family'))

    def test_one_measurement_produces_both_axes(self):
        # A second call would double the drums analysis and could disagree with
        # the first, leaving two axes describing one measurement out of step
        # inside a single sheet.
        built, calls = self.build()
        self.assertEqual(calls, ['drums.wav'])
        self.assertEqual(set(built), {'tempo', 'tempo_family'})

    def test_the_primary_axis_keeps_its_shape(self):
        built, _ = self.build()
        tempo = built['tempo']
        self.assertEqual(tempo['value'], 80.7)
        self.assertIsInstance(tempo['value'], float)
        self.assertEqual(tempo['unit'], 'bpm')
        self.assertEqual(tempo['suno_actionable'], 'direct')
        self.assertEqual(tempo['note'], 'a competing metrical level')

    def test_the_family_axis_carries_the_members_and_matches_the_grade(self):
        built, _ = self.build()
        tempo, family = built['tempo'], built['tempo_family']
        self.assertEqual(family['confidence'], tempo['confidence'])
        self.assertEqual(family['unit'], 'members')
        self.assertEqual(family['stem'], tempo['stem'])
        self.assertEqual(family['method'], tempo['method'])
        # 'none' because a level chosen here reaches a prompt through tempo.
        self.assertEqual(family['suno_actionable'], 'none')
        self.assertEqual([m['bpm'] for m in family['value']], [161.5, 107.7])
        self.assertEqual(family['value'][0]['relative_strength'], 0.9)
        # A member whose method supplies no strength still carries the key.
        self.assertIsNone(family['value'][1]['relative_strength'])

    def test_the_family_axis_is_not_projected_for_compare(self):
        self.assertNotIn('tempo_family', f.PROJECTION)

    def test_a_broken_builder_order_raises_rather_than_emitting_nothing(self):
        with self.assertRaises(f.FactError) as caught:
            f._tempo_family_fact({'drums': 'drums.wav'}, {}, None, 44100, {}, {})
        self.assertIn('after tempo', str(caught.exception))

    def test_an_empty_family_is_a_fact_rather_than_an_error(self):
        result = dict(self.RESULT, family=[], confidence='KNOW',
                      disagreement=None)
        entry = f._tempo_family_fact_from(result)
        self.assertEqual(entry['value'], [])
        self.assertEqual(entry['confidence'], 'KNOW')
