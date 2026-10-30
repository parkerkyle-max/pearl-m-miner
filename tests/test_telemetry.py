"""CPU-only display checks. No native imports, mining, pool or income claims."""
import json
import math
import unittest

from pearl_metal_miner.telemetry import Telemetry


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.telemetry = Telemetry(clock=lambda: self.now)

    def report(self, **overrides):
        values = dict(rolling_tiles_s=7_500_000, session_tiles_s=7_400_000,
                      work_per_tile=524_288, uptime_s=30.0,
                      submitted=3, accepted=2, rejected=0, pending=1)
        values.update(overrides)
        return self.telemetry.snapshot(**values)

    def test_protocol_units_do_not_become_pool_rate_or_income(self):
        report = self.report()
        self.assertEqual(report['local_rate']['rolling_hs'], 3_932_160_000_000)
        self.assertEqual(report['local_rate']['rolling_ths'], 3.93216)
        self.assertEqual(report['local_rate']['session_hs'], 3_879_731_200_000)
        self.assertIsNone(report['pool_effective_hs'])
        self.assertNotIn('income', report)
        self.assertEqual(report['shares'],
                         dict(submitted=3, accepted=2, rejected=0, pending=1))

    def test_first_native_snapshot_is_cumulative_without_invented_delta(self):
        report = self.report(native_stats={'scans': 400, 'gpu_s': 25.25})
        self.assertEqual(report['native']['cumulative']['scans'], 400)
        self.assertIsNone(report['native']['delta']['scans'])
        self.assertIsNone(report['native']['delta_window_seconds'])
        self.assertIsNone(report['native']['cumulative']['prepare_wall_s'])

    def test_native_delta_tracks_stale_work_and_overlapping_stages(self):
        self.report(native_stats={'gpu_s': 10.0, 'scan_wall_s': 12.0,
                    'completed_tiles': 1000, 'valid_returned_tiles': 900,
                    'stale_discarded_tiles': 100})
        self.now += 30
        report = self.report(native_stats={'gpu_s': 29.5, 'scan_wall_s': 34.0,
                    'completed_tiles': 1600, 'valid_returned_tiles': 1400,
                    'stale_discarded_tiles': 200})
        native = report['native']
        self.assertEqual(native['delta_window_seconds'], 30)
        self.assertEqual(native['delta']['gpu_s'], 19.5)
        self.assertEqual(native['delta']['scan_wall_s'], 22.0)
        self.assertEqual(native['delta']['completed_tiles'], 600)
        self.assertEqual(native['delta']['valid_returned_tiles'], 500)
        self.assertEqual(native['delta']['stale_discarded_tiles'], 100)
        self.assertTrue(native['timings_overlap'])

    def test_counter_reset_is_unknown_not_negative_or_cumulative_delta(self):
        self.report(native_stats={'scans': 90, 'gpu_s': 9.0})
        self.now += 30
        native = self.report(native_stats={'scans': 2, 'gpu_s': 0.2})['native']
        self.assertIsNone(native['delta']['scans'])
        self.assertEqual(set(native['counter_resets']), {'scans', 'gpu_s'})
        self.now += 30
        self.assertEqual(self.report(native_stats={'scans': 5})['native']['delta']['scans'], 3)

    def test_missing_or_invalid_measurements_remain_unknown_and_json_safe(self):
        for bad in (None, True, -1, math.nan, math.inf, '3.9', 10**1000):
            report = self.report(rolling_tiles_s=bad, native_stats={'gpu_s': bad})
            self.assertIsNone(report['local_rate']['rolling_hs'])
            self.assertIsNone(report['native']['cumulative']['gpu_s'])
            json.dumps(report, allow_nan=False)
        report = self.report(work_per_tile=0)
        self.assertIsNone(report['local_rate']['rolling_hs'])
        self.assertEqual(self.report(rolling_tiles_s=0)['local_rate']['rolling_hs'], 0)

    def test_missing_interval_is_not_bridged_with_a_fabricated_delta(self):
        self.report(native_stats={'scans': 3})
        self.now += 30
        self.report(native_stats=None)
        self.now += 30
        native = self.report(native_stats={'scans': 9})['native']
        self.assertIsNone(native['delta']['scans'])

    def test_nonforward_clock_invalidates_delta_and_recovers_next_window(self):
        self.report(native_stats={'scans': 10})
        self.assertIsNone(self.report(native_stats={'scans': 11})['native']['delta']['scans'])
        self.now = 90
        native = self.report(native_stats={'scans': 12})['native']
        self.assertIsNone(native['delta_window_seconds'])
        self.assertIsNone(native['delta']['scans'])
        self.now = 120
        self.assertEqual(self.report(native_stats={'scans': 15})['native']['delta']['scans'], 3)

    def test_report_cadence_is_bounded_and_does_not_catch_up_in_a_burst(self):
        self.assertFalse(self.telemetry.due())
        self.now = 130
        self.assertTrue(self.telemetry.due())
        self.report()
        self.assertFalse(self.telemetry.due())
        self.now = 900
        self.assertTrue(self.telemetry.due())
        self.report()
        self.assertFalse(self.telemetry.due())
        self.now = 929.9
        self.assertFalse(self.telemetry.due())
        self.now = 930
        self.assertTrue(self.telemetry.due())

    def test_job_counts_distinguish_received_repeats_from_adopted_updates(self):
        self.assertIsNone(self.report()['jobs']['last_received_age_seconds'])
        self.telemetry.job_received()
        self.telemetry.job_adopted()
        self.now += 2
        self.telemetry.job_received()  # duplicate notification, no job refresh
        self.now += 3
        jobs = self.report()['jobs']
        self.assertEqual(jobs['received_notifications'], 2)
        self.assertEqual(jobs['adopted_updates'], 1)
        self.assertEqual(jobs['last_received_age_seconds'], 3)
        self.assertEqual(jobs['last_adopted_age_seconds'], 5)

    def test_post_sweep_job_notice_survives_until_grid_is_ready(self):
        self.assertFalse(self.telemetry.take_job_notice())
        self.telemetry.job_received()
        self.telemetry.job_adopted()  # post-sweep adoption followed by continue
        self.now += 1
        self.report()  # reports do not consume the pending grid-ready notice
        self.assertTrue(self.telemetry.take_job_notice())
        self.assertFalse(self.telemetry.take_job_notice())  # ordinary nonce grid
        self.telemetry.job_adopted()
        self.telemetry.job_adopted()  # coalesced: only the final grid is prepared
        self.assertTrue(self.telemetry.take_job_notice())
        self.assertFalse(self.telemetry.take_job_notice())

    def test_clock_before_job_observation_reports_unknown_age(self):
        self.telemetry.job_received()
        self.telemetry.job_adopted()
        self.now -= 1
        jobs = self.report()['jobs']
        self.assertIsNone(jobs['last_received_age_seconds'])
        self.assertIsNone(jobs['last_adopted_age_seconds'])


if __name__ == '__main__':
    unittest.main()
