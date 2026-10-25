import argparse
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('ledger', Path(__file__).with_name('experiment_log.py'))
ledger = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)


class LedgerTests(unittest.TestCase):
    def test_navigation_metrics_and_status(self):
        import navigation_run as nav
        m = nav.Metrics()
        self.assertIsNone(m.values()['path_length_m'])
        m.odom(0, 0, 'odom', 1)
        m.odom(3, 4, 'odom', 2)
        self.assertEqual(m.values()['path_length_m'], 5)
        m.odom(3, 4, 'odom', 1)
        self.assertIsNone(m.values()['path_length_m'])
        self.assertEqual(nav.outcome_for_status(4), 'succeeded')
        self.assertEqual(nav.outcome_for_status(5), 'canceled')
        for status in [0, 1, 2, 3, 6, 99]:
            self.assertEqual(nav.outcome_for_status(status), 'failed')

    def test_finish_is_recoverable_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger.RUNS = Path(tmp) / 'runs'
            ledger.SUMMARY = Path(tmp) / 'summary.csv'
            a = argparse.Namespace(goal_id='unit-test', trial=1, launch_log='', notes='SIMULATED TEST ONLY')
            record = ledger.start(a)
            self.assertIsInstance(record, dict)
            ledger.checkpoint(record['run_id'], {'nav_time_sim_s': 2.5, 'path_length_m': 1.2})
            finish_args = argparse.Namespace(run_id=record['run_id'], outcome='failed',
                nav_time_sim=None, remaining_distance=None, recoveries=None, collisions=None,
                path_length=None, gazebo_rtf=None, notes='test only')
            ledger.finish(finish_args)
            ledger.finalize(record['run_id'], 'failed', {'termination_reason': 'test_only'})
            with ledger.SUMMARY.open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(list(rows[0]), ledger.FIELDS)
            data = json.loads((ledger.RUNS / record['run_id'] / 'run.json').read_text())
            self.assertIsNone(data['collisions'])
            self.assertIsNone(data['gazebo_rtf'])
            self.assertEqual(data['nav_time_sim_s'], 2.5)
            self.assertEqual(data['path_length_m'], 1.2)
            ledger.SUMMARY.unlink()
            ledger.finalize(record['run_id'], 'succeeded')
            with ledger.SUMMARY.open() as f:
                restored = list(csv.DictReader(f))
            self.assertEqual(restored[0]['outcome'], 'failed')

    def test_run_id_cannot_escape(self):
        with self.assertRaises(ValueError):
            ledger.run_dir_for('..')


if __name__ == '__main__':
    unittest.main()
