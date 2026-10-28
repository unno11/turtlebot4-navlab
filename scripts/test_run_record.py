"""Unit tests for run_record.verdict / blocks_rerun.

These are the rules that decide whether a trial counts, so they get tested rather
than trusted. No ROS needed.
"""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    'run_record', Path(__file__).with_name('run_record.py'))
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)


def rec(**kw):
    base = {'state': 'finished', 'termination_reason': 'action_result',
            'action_status': 4, 'notes_start': ''}
    base.update(kw)
    return base


class VerdictTests(unittest.TestCase):
    def test_succeeded(self):
        self.assertEqual(rr.verdict(rec())[0], 'succeeded')
        self.assertTrue(rr.is_result(rec()))

    def test_aborted_is_a_failure(self):
        self.assertEqual(rr.verdict(rec(action_status=6))[0], 'failed')
        self.assertTrue(rr.is_result(rec(action_status=6)))

    def test_wall_timeout_is_not_a_navigation_result(self):
        r = rec(termination_reason='wall_timeout', action_status=5)
        self.assertEqual(rr.verdict(r)[0], 'invalid')
        self.assertFalse(rr.is_result(r))

    def test_recorder_that_never_got_a_status_is_invalid(self):
        r = rec(termination_reason='wall_timeout', action_status=None)
        self.assertEqual(rr.verdict(r)[0], 'invalid')

    def test_status_5_with_action_result_is_invalid_not_canceled_failure(self):
        # A cancel that the action itself confirmed still produced no result.
        self.assertEqual(rr.verdict(rec(action_status=5))[0], 'invalid')

    def test_unfinished_record(self):
        self.assertEqual(rr.verdict(rec(state='running'))[0], 'unfinished')
        self.assertFalse(rr.is_result(rec(state='running')))


class ControlArmTests(unittest.TestCase):
    def test_control_from_notes(self):
        self.assertEqual(rr.control_of(rec(notes_start='control=rpp')), 'rpp')
        self.assertEqual(rr.control_of(rec(notes_start=' a; control=graceful ;b')), 'graceful')

    def test_missing_note(self):
        self.assertEqual(rr.control_of(rec()), '')
        self.assertEqual(rr.control_of({'notes_start': None}), '')


class BlocksRerunTests(unittest.TestCase):
    def test_result_from_same_arm_blocks(self):
        self.assertTrue(rr.blocks_rerun(rec(notes_start='control=rpp'), 'rpp'))

    def test_result_from_another_arm_does_not_block(self):
        self.assertFalse(rr.blocks_rerun(rec(notes_start='control=rpp'), 'mppi'))

    def test_invalid_record_never_blocks(self):
        r = rec(termination_reason='wall_timeout', action_status=5,
                notes_start='control=rpp')
        self.assertFalse(rr.blocks_rerun(r, 'rpp'))

    def test_legacy_record_without_note_does_not_block_a_named_arm(self):
        # Records written before the controller switch existed cannot be assumed to
        # belong to the arm being run now.
        self.assertFalse(rr.blocks_rerun(rec(), 'mppi'))
        self.assertTrue(rr.blocks_rerun(rec(), ''))


if __name__ == '__main__':
    unittest.main()
