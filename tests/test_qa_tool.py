import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from qa_tool import (
    SYNTHETIC_LABEL,
    Ping,
    corrected_distance_report,
    create_synthetic_dataset,
    inspect_pings,
    legacy_distance_report,
    legacy_suspicious_segments,
    load_pings,
)

UTC = timezone.utc


def ping(ping_id: str, timestamp: datetime, route_m: float, offset_m: float = 0.0) -> Ping:
    return Ping(SYNTHETIC_LABEL, ping_id, "driver-test", timestamp, route_m, offset_m)


class DistanceReferenceTests(unittest.TestCase):
    def test_synthetic_fixture_contains_required_faults_and_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pings.csv"
            row_count = create_synthetic_dataset(path)
            pings = load_pings(path)

        self.assertGreaterEqual(row_count, 2_000)
        self.assertTrue(all(item.dataset_label == SYNTHETIC_LABEL for item in pings))
        issues = inspect_pings(pings)
        self.assertEqual(issues["off_road"], 4)
        self.assertEqual(issues["over_speed"], 4)
        self.assertEqual(issues["duplicate"], 4)
        self.assertEqual(issues["out_of_order"], 4)

    def test_fix_sorts_deduplicates_rejects_noise_and_reports_local_days(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pings.csv"
            create_synthetic_dataset(path)
            pings = load_pings(path)
        report, rejected = corrected_distance_report(pings)

        self.assertEqual(rejected["off_road"], 4)
        self.assertEqual(rejected["over_speed"], 4)
        for driver_number in range(1, 5):
            driver = f"driver-{driver_number:02}"
            self.assertAlmostEqual(report[(driver, date(2026, 10, 31))], 400.0)
            self.assertAlmostEqual(report[(driver, date(2026, 11, 1))], 3_600.0)

    def test_regression_legacy_result_is_wrong_and_corrected_result_matches_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pings.csv"
            create_synthetic_dataset(path)
            pings = load_pings(path)
        old_report = legacy_distance_report(pings)
        corrected, _ = corrected_distance_report(pings)

        self.assertNotEqual(old_report, corrected)
        self.assertGreater(old_report[("driver-01", date(2026, 10, 31))], 4_000.0)
        self.assertEqual(corrected[("driver-01", date(2026, 10, 31))], 400.0)
        self.assertEqual(corrected[("driver-01", date(2026, 11, 1))], 3_600.0)

    def test_zone_segment_is_clipped_and_split_at_utc_plus_nine_midnight(self) -> None:
        pings = [
            ping("before-cut", datetime(2026, 10, 31, 14, 59, 50, tzinfo=UTC), 0),
            ping("after-cut", datetime(2026, 10, 31, 15, 0, 10, tzinfo=UTC), 200),
        ]
        report, _ = corrected_distance_report(pings, zone_start_m=50, zone_end_m=150)

        self.assertAlmostEqual(report[("driver-test", date(2026, 10, 31))], 50.0)
        self.assertAlmostEqual(report[("driver-test", date(2026, 11, 1))], 50.0)

    def test_duplicate_timestamp_counts_once_and_out_of_order_is_sorted(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("later", start + timedelta(seconds=20), 40),
            ping("first", start, 0),
            ping("duplicate", start, 0),
            ping("middle", start + timedelta(seconds=10), 20),
        ]
        report, _ = corrected_distance_report(pings, zone_start_m=0, zone_end_m=40)

        self.assertAlmostEqual(report[("driver-test", date(2026, 1, 1))], 40.0)

    def test_baseline_fails_off_road_rule_and_corrected_joins_valid_points(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("valid-start", start, 0),
            ping("off-road", start + timedelta(seconds=10), 100, offset_m=101),
            ping("valid-end", start + timedelta(seconds=20), 20),
        ]
        old = legacy_distance_report(pings, zone_start_m=0, zone_end_m=100)
        corrected, rejected = corrected_distance_report(pings, zone_start_m=0, zone_end_m=100)

        self.assertAlmostEqual(old[("driver-test", date(2026, 1, 1))], 180.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 1, 1))], 20.0)
        self.assertEqual(rejected["off_road"], 1)

    def test_baseline_fails_speed_rule_and_corrected_rejects_spike(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("valid-start", start, 0),
            ping("speed-spike", start + timedelta(seconds=1), 1_000),
            ping("valid-end", start + timedelta(seconds=10), 20),
        ]
        old = legacy_distance_report(pings, zone_start_m=0, zone_end_m=1_000)
        corrected, rejected = corrected_distance_report(
            pings, zone_start_m=0, zone_end_m=1_000
        )

        self.assertAlmostEqual(old[("driver-test", date(2026, 1, 1))], 1_980.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 1, 1))], 20.0)
        self.assertEqual(rejected["over_speed"], 1)

    def test_baseline_fails_conflicting_duplicate_rule(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("start", start, 0),
            ping("first-at-time", start + timedelta(seconds=10), 10),
            ping("conflicting-duplicate", start + timedelta(seconds=10), 30),
            ping("end", start + timedelta(seconds=20), 20),
        ]
        old = legacy_distance_report(pings, zone_start_m=0, zone_end_m=40)
        corrected, _ = corrected_distance_report(pings, zone_start_m=0, zone_end_m=40)

        self.assertAlmostEqual(old[("driver-test", date(2026, 1, 1))], 40.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 1, 1))], 20.0)

    def test_baseline_fails_late_ping_order_rule(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("late-arrival", start + timedelta(seconds=20), 40),
            ping("first", start, 0),
            ping("middle", start + timedelta(seconds=10), 20),
        ]
        old = legacy_distance_report(pings, zone_start_m=0, zone_end_m=40)
        corrected, _ = corrected_distance_report(pings, zone_start_m=0, zone_end_m=40)

        self.assertAlmostEqual(old[("driver-test", date(2026, 1, 1))], 60.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 1, 1))], 40.0)

    def test_baseline_fails_zone_clipping_rule(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        pings = [
            ping("outside-start", start, 0),
            ping("outside-end", start + timedelta(seconds=10), 200),
        ]
        old = legacy_distance_report(pings, zone_start_m=50, zone_end_m=150)
        corrected, _ = corrected_distance_report(pings, zone_start_m=50, zone_end_m=150)

        self.assertEqual(old.get(("driver-test", date(2026, 1, 1)), 0.0), 0.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 1, 1))], 100.0)

    def test_baseline_fails_utc_plus_nine_day_assignment(self) -> None:
        pings = [
            ping("before-cut", datetime(2026, 10, 31, 14, 59, 50, tzinfo=UTC), 50),
            ping("after-cut", datetime(2026, 10, 31, 15, 0, 10, tzinfo=UTC), 150),
        ]
        old = legacy_distance_report(pings, zone_start_m=0, zone_end_m=200)
        corrected, _ = corrected_distance_report(pings, zone_start_m=0, zone_end_m=200)

        self.assertAlmostEqual(old[("driver-test", date(2026, 10, 31))], 100.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 10, 31))], 50.0)
        self.assertAlmostEqual(corrected[("driver-test", date(2026, 11, 1))], 50.0)

    def test_baseline_diagnostics_identify_exact_inflated_fixture_segments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pings.csv"
            create_synthetic_dataset(path)
            pings = load_pings(path)
        details = legacy_suspicious_segments(pings)
        joined = "\n".join(details)

        self.assertIn("driver-01-ping-0499", joined)
        self.assertIn("driver-01-ping-0250", joined)
        self.assertIn("baseline charges 4980.0 m", joined)
        self.assertIn("implied speed 367.2 km/h", joined)
        self.assertIn("whole-segment charging exceeds zone distance by 20.0 m", joined)


if __name__ == "__main__":
    unittest.main()
