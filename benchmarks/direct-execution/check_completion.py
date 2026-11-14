#!/usr/bin/env python3
"""Replay completion decisions without launching OFFBEAT or a language model."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('case_completion',ROOT/'lib/mandifuel_run/case.py')
case_api=importlib.util.module_from_spec(spec);spec.loader.exec_module(case_api)


class CompletionChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='mandifuel-completion-')
        self.case=Path(self.temporary.name);(self.case/'system').mkdir()

    def tearDown(self):self.temporary.cleanup()

    def fixture(self,end='100',step='1',times=('0','100'),code=0,terminal=True,receipt=None):
        (self.case/'system/controlDict').write_text(f'endTime {end};\ndeltaT {step};\n')
        for name in times:(self.case/name).mkdir(exist_ok=True)
        (self.case/'log.offbeat').write_text('Time = 100 seconds\nExecutionTime = 0.2 s\n'+('End\n' if terminal else 'FOAM FATAL IO ERROR\n'))
        (self.case/'log.run-status').write_text(str(code))
        if receipt is not None:(self.case/case_api.RECEIPT).write_text(json.dumps(receipt))
        return case_api.inspect_case(self.case)

    def test_exact_completion(self):
        r=self.fixture();self.assertEqual(r['status'],'completed');self.assertEqual(r['time_match']['method'],'exact')

    def test_roundoff_retains_real_directory(self):
        r=self.fixture(end='17735.41',step='17.73541',times=('0','17735.410000000229'))
        self.assertEqual(r['status'],'completed');self.assertEqual(r['final_time'],'17735.410000000229');self.assertEqual(r['time_match']['method'],'roundoff')

    def test_small_negative_roundoff(self):
        r=self.fixture(times=('0','99.99999999999999'));self.assertEqual(r['status'],'completed')

    def test_rounded_log_is_not_completion(self):
        r=self.fixture(end='17735.41',step='17.73541',times=('0','17735.4'))
        self.assertEqual(r['status'],'incomplete');self.assertIsNone(r['final_time'])

    def test_missing_step_is_not_roundoff(self):
        r=self.fixture(end='100',step='1e-11',times=('0','99.99999999999'))
        self.assertEqual(r['status'],'incomplete')

    def test_saved_spacing_also_caps_tolerance(self):
        r=self.fixture(end='100',step='$computedStep',times=('0','99.99999999998','99.99999999999'))
        self.assertEqual(r['status'],'incomplete')

    def test_exact_tiny_target(self):
        r=self.fixture(end='1e-15',step='1e-16',times=('0','1e-15'));self.assertEqual(r['status'],'completed')

    def test_zero_is_not_a_tiny_target(self):
        r=self.fixture(end='1e-15',step='1e-16',times=('0',));self.assertEqual(r['status'],'incomplete')

    def test_nonzero_exit_remains_failed(self):
        r=self.fixture(code=1,times=('0','100.000000000001'));self.assertEqual(r['status'],'failed')

    def test_missing_terminal_marker_not_completed(self):
        r=self.fixture(terminal=False);self.assertEqual(r['status'],'incomplete')

    def test_known_failure_not_overridden(self):
        r=self.fixture(receipt={'status':'failed','exit_code':0,'error':'invalid input'})
        self.assertEqual(r['status'],'failed')

    def test_interrupted_receipt_not_overridden(self):
        r=self.fixture(receipt={'status':'interrupted','exit_code':0});self.assertEqual(r['status'],'failed')

    def test_live_receipt_not_completed(self):
        r=self.fixture(receipt={'status':'running','exit_code':None});self.assertEqual(r['status'],'running')

    def test_legacy_false_failure_is_reconciled_without_write_or_launch(self):
        receipt={'status':'failed','exit_code':0,'error':case_api.COMPLETION_ERROR,'end_time':'17735.41'}
        self.fixture(end='17735.41',step='17.73541',times=('0','17735.410000000229'),receipt=receipt)
        before=(self.case/case_api.RECEIPT).read_bytes()
        with patch.object(case_api.subprocess,'Popen',side_effect=AssertionError('must not launch')):
            result=case_api.run_case(self.case)
        self.assertEqual(result['status'],'completed');self.assertTrue(result['completion_reconciled'])
        self.assertIsNone(result['error']);self.assertEqual((self.case/case_api.RECEIPT).read_bytes(),before)

    def test_archived_c04_receipt_replay(self):
        original=ROOT/'runs/candidate-pairs-20261112-04/C04/skill/workspace/clad-oxide-17735.41d'
        if not original.exists():self.skipTest('archived C04 input unavailable')
        shutil.copy2(original/'system/controlDict',self.case/'system/controlDict')
        shutil.copy2(original/'log.offbeat',self.case/'log.offbeat')
        receipt=json.loads((original/case_api.RECEIPT).read_text())
        self.assertEqual(receipt['status'],'failed');self.assertEqual(receipt['exit_code'],0)
        (self.case/case_api.RECEIPT).write_text(json.dumps(receipt))
        for name in receipt['times']:(self.case/name).mkdir()
        with patch.object(case_api.subprocess,'Popen',side_effect=AssertionError('must not launch')):
            result=case_api.run_case(self.case)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['final_time'],'17735.410000000229')
        self.assertEqual(result['solver_steps'],1000)


if __name__=='__main__':unittest.main(verbosity=2)
