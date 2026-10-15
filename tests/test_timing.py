import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from devflow import config, metrics, state


class TimingTests(unittest.TestCase):
    def test_closed_run_and_old_task_missing_timestamp(self):
        run = {'created_at': '2026-01-01T00:00:00+00:00', 'updated_at': '2026-01-01T00:10:00+00:00',
               'closed_at': '2026-01-01T00:10:00+00:00',
               'status': 'completed', 'tasks': [{'task_id': 'a', 'role': 'tester', 'status': 'done',
                   'assigned_at': '2026-01-01T00:01:00+00:00'}]}
        result = state.elapsed_timing(run)
        self.assertEqual(result['elapsed_seconds'], 600)
        self.assertIsNone(result['tasks'][0]['elapsed_seconds'])
        run['tasks'][0]['result_recorded_at'] = '2026-01-01T00:02:00+00:00'
        self.assertEqual(state.elapsed_timing(run)['tasks'][0]['elapsed_seconds'], 60)

    def test_active_elapsed_includes_waiting_and_invalid_stays_unknown(self):
        run = {'created_at': '2026-01-01T00:00:00+00:00', 'status': 'active',
               'tasks': [{'assigned_at': 'invalid', 'status': 'pending'}]}
        result = state.elapsed_timing(run, dt.datetime(2026, 1, 1, 0, 3, tzinfo=dt.timezone.utc))
        self.assertEqual(result['elapsed_seconds'], 180)
        self.assertIsNone(result['tasks'][0]['elapsed_seconds'])

    def test_stats_wall_clock_does_not_invent_usage(self):
        record = {'mode': 'feature', 'status': 'completed', 'created_at': '2026-01-01T00:00:00+00:00',
                  'closed_at': '2026-01-01T00:10:00+00:00'}
        with patch.object(metrics, '_records', return_value=[('full', record)]):
            result = metrics.stats('.', all_repos=True)
        bucket = result['tasks']['full:feature']
        self.assertEqual(bucket['avg_wall_clock_elapsed_seconds'], 600)
        self.assertEqual(bucket['measured'], 0)
        self.assertEqual(result['roles'], {})
        self.assertIn('not agent compute', result['note'])

    def test_stats_role_task_elapsed_from_recorded_results_only(self):
        task = lambda tid, role, start, end: {'task_id': tid, 'role': role, 'status': 'done',
                                              'assigned_at': start, 'result_recorded_at': end}
        record = {'mode': 'error', 'status': 'completed', 'created_at': '2026-01-01T00:00:00+00:00',
                  'closed_at': '2026-01-01T00:20:00+00:00',
                  'tasks': [task('a', 'fixer', '2026-01-01T00:00:00+00:00', '2026-01-01T00:08:00+00:00'),
                            task('b', 'fixer', '2026-01-01T00:10:00+00:00', '2026-01-01T00:12:00+00:00'),
                            task('c', 'reviewer', '2026-01-01T00:12:00+00:00', None)],
                  'metrics': [{'role': 'reviewer', 'tokens': None, 'duration_ms': None, 'model': None}]}
        with patch.object(metrics, '_records', return_value=[('full', record)]):
            roles = metrics.stats('.', all_repos=True)['roles']
        self.assertEqual((roles['fixer']['task_elapsed_s'], roles['fixer']['avg_task_elapsed_s']), (600.0, 300.0))
        self.assertEqual(roles['fixer']['calls'], 0)
        self.assertIsNone(roles['reviewer']['avg_task_elapsed_s'])
        self.assertEqual(roles['reviewer']['calls'], 1)

    def test_cancelled_unfinished_task_stops_at_explicit_close_event(self):
        run = {'status': 'cancelled', 'created_at': '2026-01-01T00:00:00+00:00',
               'updated_at': '2026-01-02T00:00:00+00:00',
               'events': [{'event': 'close', 'at': '2026-01-01T00:01:00+00:00'},
                          {'event': 'Orca evidence account', 'at': '2026-01-02T00:00:00+00:00'}],
               'tasks': [{'status': 'active', 'assigned_at': '2026-01-01T00:00:30+00:00'}]}
        for day in (2, 3):
            result = state.elapsed_timing(run, dt.datetime(2026, 1, day, tzinfo=dt.timezone.utc))
            self.assertEqual(result['elapsed_seconds'], 60)
            self.assertEqual(result['tasks'][0]['elapsed_seconds'], 30)
            self.assertEqual(result['endpoint_source'], 'close_event')

    def test_historical_final_without_closure_endpoint_unknown(self):
        run = {'status': 'partial', 'created_at': '2026-01-01T00:00:00+00:00',
               'updated_at': '2026-01-01T00:01:00+00:00',
               'tasks': [{'status': 'pending', 'assigned_at': '2026-01-01T00:00:30+00:00'}]}
        result = state.elapsed_timing(run)
        self.assertIsNone(result['elapsed_seconds'])
        self.assertIsNone(result['tasks'][0]['elapsed_seconds'])
        self.assertEqual(result['endpoint_source'], 'unknown')

    def test_close_timestamp_unchanged_by_post_close_settle_account(self):
        for final in ('cancelled', 'partial'):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as folder:
                run = {'run_id': 'test-run', 'config_snapshot': config.defaults(), 'status': final,
                       'created_at': '2026-01-01T00:00:00+00:00', 'events': [],
                       'tasks': [{'status': 'active', 'assigned_at': '2026-01-01T00:00:30+00:00'}]}
                with patch.object(state, 'now', return_value='2026-01-01T00:01:00+00:00'):
                    state.save(folder, run, 'close')
                for event in ('Orca evidence settle', 'Orca evidence account'):
                    with patch.object(state, 'now', return_value='2026-01-02T00:00:00+00:00'):
                        state.save(folder, run, event)
                    self.assertEqual(run['closed_at'], '2026-01-01T00:01:00+00:00')
                    result = state.elapsed_timing(run)
                    self.assertEqual(result['elapsed_seconds'], 60)
                    self.assertEqual(result['tasks'][0]['elapsed_seconds'], 30)
                    self.assertEqual(result['endpoint_source'], 'closed_at')


if __name__ == '__main__':
    unittest.main()
