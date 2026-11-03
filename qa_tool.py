#!/usr/bin/env python3
"""QA checker and reference distance calculator for a labelled synthetic dataset."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

UTC = timezone.utc
LOCAL_TZ = timezone(timedelta(hours=9))
SYNTHETIC_LABEL = "SYNTHETIC_TEST_DATA_NOT_REAL"
ZONE_START_M = 2_000.0
ZONE_END_M = 6_000.0
MAX_OFFSET_M = 100.0
MAX_SPEED_KMH = 150.0
PING_INTERVAL_SECONDS = 10
ROUTE_STEP_M = 20.0
DATASET_FIELDS = (
    "dataset_label",
    "ping_id",
    "driver_id",
    "timestamp_utc",
    "route_m",
    "lateral_offset_m",
)


@dataclass(frozen=True)
class Ping:
    dataset_label: str
    ping_id: str
    driver_id: str
    timestamp: datetime
    route_m: float
    lateral_offset_m: float


def _format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def create_synthetic_dataset(path: Path) -> int:
    """Write four 500-ping traces and inject documented faults deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    start = datetime(2026, 10, 31, 14, 40, tzinfo=UTC)
    for driver_number in range(1, 5):
        driver_id = f"driver-{driver_number:02}"
        driver_rows: list[dict[str, str]] = []
        for index in range(500):
            route_m = index * ROUTE_STEP_M
            offset_m = 0.0
            if index == 150:
                offset_m = 125.0
            if index == 220:
                route_m += 1_000.0
            timestamp = start + timedelta(seconds=index * PING_INTERVAL_SECONDS)
            driver_rows.append(
                {
                    "dataset_label": SYNTHETIC_LABEL,
                    "ping_id": f"{driver_id}-ping-{index:04}",
                    "driver_id": driver_id,
                    "timestamp_utc": _format_timestamp(timestamp),
                    "route_m": f"{route_m:.1f}",
                    "lateral_offset_m": f"{offset_m:.1f}",
                }
            )

        # Keep the duplicate adjacent to its source so it is not also a late arrival.
        driver_rows.insert(301, dict(driver_rows[300]))
        late_ping = driver_rows.pop(250)
        rows.extend(driver_rows)
        rows.append(late_ping)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=DATASET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_pings(path: Path) -> list[Ping]:
    pings: list[Ping] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if tuple(reader.fieldnames or ()) != DATASET_FIELDS:
            raise ValueError(f"{path}: expected CSV columns {DATASET_FIELDS}")
        for line_number, row in enumerate(reader, start=2):
            if row["dataset_label"] != SYNTHETIC_LABEL:
                raise ValueError(f"{path}:{line_number}: unexpected dataset label")
            try:
                timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("timestamp has no UTC offset")
                timestamp = timestamp.astimezone(UTC)
                pings.append(
                    Ping(
                        dataset_label=row["dataset_label"],
                        ping_id=row["ping_id"],
                        driver_id=row["driver_id"],
                        timestamp=timestamp,
                        route_m=float(row["route_m"]),
                        lateral_offset_m=float(row["lateral_offset_m"]),
                    )
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: invalid ping: {error}") from error
    return pings


def _unique_chronological(pings: Iterable[Ping]) -> tuple[list[Ping], int]:
    unique: dict[tuple[str, datetime], Ping] = {}
    duplicate_count = 0
    for ping in pings:
        key = (ping.driver_id, ping.timestamp)
        if key in unique:
            duplicate_count += 1
        else:
            unique[key] = ping
    return sorted(unique.values(), key=lambda ping: (ping.driver_id, ping.timestamp)), duplicate_count


def issue_details(pings: list[Ping]) -> dict[str, list[str]]:
    details: dict[str, list[str]] = defaultdict(list)
    previous_by_driver: dict[str, datetime] = {}
    seen_timestamps: set[tuple[str, datetime]] = set()
    for ping in pings:
        key = (ping.driver_id, ping.timestamp)
        if key in seen_timestamps:
            details["duplicate"].append(f"{ping.ping_id} at {_format_timestamp(ping.timestamp)}")
        else:
            seen_timestamps.add(key)
        previous = previous_by_driver.get(ping.driver_id)
        if previous is not None and ping.timestamp < previous:
            details["out_of_order"].append(f"{ping.ping_id} at {_format_timestamp(ping.timestamp)}")
        previous_by_driver[ping.driver_id] = ping.timestamp
        if abs(ping.lateral_offset_m) > MAX_OFFSET_M:
            details["off_road"].append(
                f"{ping.ping_id} offset={ping.lateral_offset_m:+.1f} m"
            )

    unique, _ = _unique_chronological(pings)
    previous_valid: dict[str, Ping] = {}
    for ping in unique:
        if abs(ping.lateral_offset_m) > MAX_OFFSET_M:
            continue
        previous = previous_valid.get(ping.driver_id)
        if previous is not None:
            elapsed = (ping.timestamp - previous.timestamp).total_seconds()
            speed_kmh = abs(ping.route_m - previous.route_m) / elapsed * 3.6
            if speed_kmh > MAX_SPEED_KMH:
                details["over_speed"].append(
                    f"{ping.ping_id} implied_speed={speed_kmh:.1f} km/h"
                )
                continue
        previous_valid[ping.driver_id] = ping
    return dict(details)


def inspect_pings(pings: list[Ping]) -> Counter[str]:
    return Counter({issue: len(rows) for issue, rows in issue_details(pings).items()})


def _accepted_pings(pings: list[Ping]) -> tuple[dict[str, list[Ping]], Counter[str]]:
    unique, _ = _unique_chronological(pings)
    accepted: dict[str, list[Ping]] = defaultdict(list)
    issues: Counter[str] = Counter()
    previous_valid: dict[str, Ping] = {}
    for ping in unique:
        if abs(ping.lateral_offset_m) > MAX_OFFSET_M:
            issues["off_road"] += 1
            continue
        previous = previous_valid.get(ping.driver_id)
        if previous is not None:
            elapsed = (ping.timestamp - previous.timestamp).total_seconds()
            speed_kmh = abs(ping.route_m - previous.route_m) / elapsed * 3.6
            if speed_kmh > MAX_SPEED_KMH:
                issues["over_speed"] += 1
                continue
        accepted[ping.driver_id].append(ping)
        previous_valid[ping.driver_id] = ping
    return accepted, issues


def legacy_distance_report(
    pings: list[Ping], zone_start_m: float = ZONE_START_M, zone_end_m: float = ZONE_END_M
) -> dict[tuple[str, date], float]:
    """Intentionally flawed baseline: ingestion order, no validation, UTC day, whole segments."""
    by_driver: dict[str, list[Ping]] = defaultdict(list)
    for ping in pings:
        by_driver[ping.driver_id].append(ping)
    totals: dict[tuple[str, date], float] = defaultdict(float)
    for driver_id, driver_pings in by_driver.items():
        for previous, current in zip(driver_pings, driver_pings[1:]):
            if zone_start_m <= previous.route_m <= zone_end_m or zone_start_m <= current.route_m <= zone_end_m:
                totals[(driver_id, current.timestamp.date())] += abs(current.route_m - previous.route_m)
    return dict(totals)


def legacy_suspicious_segments(
    pings: list[Ping], zone_start_m: float = ZONE_START_M, zone_end_m: float = ZONE_END_M
) -> list[str]:
    by_driver: dict[str, list[Ping]] = defaultdict(list)
    for ping in pings:
        by_driver[ping.driver_id].append(ping)

    findings: list[str] = []
    for driver_id, driver_pings in by_driver.items():
        for previous, current in zip(driver_pings, driver_pings[1:]):
            if not (
                zone_start_m <= previous.route_m <= zone_end_m
                or zone_start_m <= current.route_m <= zone_end_m
            ):
                continue
            distance_m = abs(current.route_m - previous.route_m)
            elapsed = (current.timestamp - previous.timestamp).total_seconds()
            reasons: list[str] = []
            if elapsed < 0:
                reasons.append("out-of-order timestamp")
            elif elapsed == 0:
                reasons.append("duplicate timestamp")
            else:
                speed_kmh = distance_m / elapsed * 3.6
                if speed_kmh > MAX_SPEED_KMH:
                    reasons.append(f"implied speed {speed_kmh:.1f} km/h")
            if abs(previous.lateral_offset_m) > MAX_OFFSET_M:
                reasons.append(f"{previous.ping_id} off-road ({previous.lateral_offset_m:+.1f} m)")
            if abs(current.lateral_offset_m) > MAX_OFFSET_M:
                reasons.append(f"{current.ping_id} off-road ({current.lateral_offset_m:+.1f} m)")

            zone_fraction = _segment_fraction_in_zone(
                previous.route_m, current.route_m, zone_start_m, zone_end_m
            )
            eligible_m = (
                distance_m * (zone_fraction[1] - zone_fraction[0])
                if zone_fraction is not None
                else 0.0
            )
            if distance_m - eligible_m > 1e-9:
                reasons.append(f"whole-segment charging exceeds zone distance by {distance_m - eligible_m:.1f} m")

            if reasons:
                findings.append(
                    f"{driver_id}: {previous.ping_id} ({previous.route_m:.0f} m, "
                    f"{_format_timestamp(previous.timestamp)}) -> {current.ping_id} "
                    f"({current.route_m:.0f} m, {_format_timestamp(current.timestamp)}): "
                    f"baseline charges {distance_m:.1f} m; zone-clipped geometry "
                    f"{eligible_m:.1f} m; {', '.join(reasons)}"
                )
    return findings


def _segment_fraction_in_zone(route_start: float, route_end: float, zone_start: float, zone_end: float) -> tuple[float, float] | None:
    delta = route_end - route_start
    if delta == 0:
        return (0.0, 1.0) if zone_start <= route_start <= zone_end else None
    first = (zone_start - route_start) / delta
    second = (zone_end - route_start) / delta
    lower = max(0.0, min(first, second))
    upper = min(1.0, max(first, second))
    if lower >= upper:
        return None
    return lower, upper


def corrected_distance_report(
    pings: list[Ping],
    zone_start_m: float = ZONE_START_M,
    zone_end_m: float = ZONE_END_M,
) -> tuple[dict[tuple[str, date], float], Counter[str]]:
    accepted, rejected = _accepted_pings(pings)
    totals: dict[tuple[str, date], float] = defaultdict(float)
    for driver_id, driver_pings in accepted.items():
        for previous, current in zip(driver_pings, driver_pings[1:]):
            elapsed = (current.timestamp - previous.timestamp).total_seconds()
            if elapsed <= 0:
                continue
            zone_fraction = _segment_fraction_in_zone(
                previous.route_m, current.route_m, zone_start_m, zone_end_m
            )
            if zone_fraction is None:
                continue
            zone_start_time = previous.timestamp + timedelta(seconds=elapsed * zone_fraction[0])
            zone_end_time = previous.timestamp + timedelta(seconds=elapsed * zone_fraction[1])
            day_start = zone_start_time.astimezone(LOCAL_TZ).date()
            last_instant = zone_end_time - timedelta(microseconds=1)
            day_end = last_instant.astimezone(LOCAL_TZ).date()
            day = day_start
            while day <= day_end:
                local_start = datetime.combine(day, datetime.min.time(), LOCAL_TZ).astimezone(UTC)
                local_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL_TZ).astimezone(UTC)
                overlap_start = max(zone_start_time, local_start)
                overlap_end = min(zone_end_time, local_end)
                if overlap_end > overlap_start:
                    duration_fraction = (overlap_end - overlap_start).total_seconds() / elapsed
                    totals[(driver_id, day)] += abs(current.route_m - previous.route_m) * duration_fraction
                day += timedelta(days=1)
    return dict(totals), rejected


def _print_report(pings: list[Ping]) -> None:
    details = issue_details(pings)
    diagnostics = Counter({issue: len(rows) for issue, rows in details.items()})
    before = legacy_distance_report(pings)
    after, rejected = corrected_distance_report(pings)
    print(f"Dataset: {SYNTHETIC_LABEL}; {len(pings)} rows")
    print("Detected issues: " + ", ".join(f"{key}={diagnostics[key]}" for key in (
        "off_road", "over_speed", "duplicate", "out_of_order"
    )))
    for issue in ("off_road", "over_speed", "duplicate", "out_of_order"):
        if details.get(issue):
            print(f"  {issue}: " + "; ".join(details[issue]))
    print("\nSuspicious baseline segments:")
    for finding in legacy_suspicious_segments(pings):
        print(f"  {finding}")
    print(f"Rejected by corrected calculator: {dict(rejected)}")
    print("\nPer-driver, per-day distance (metres)")
    print("driver       day         flawed_before   corrected_after")
    keys = sorted(set(before) | set(after), key=lambda key: (key[0], key[1]))
    for driver_id, day in keys:
        print(
            f"{driver_id:<12} {day.isoformat()} {before.get((driver_id, day), 0.0):>13.1f}"
            f" {after.get((driver_id, day), 0.0):>17.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/synthetic_pings.csv"))
    parser.add_argument("--generate", action="store_true", help="generate the labelled synthetic CSV")
    args = parser.parse_args()
    if args.generate:
        count = create_synthetic_dataset(args.dataset)
        print(f"Wrote {count} labelled synthetic pings to {args.dataset}")
        return
    _print_report(load_pings(args.dataset))


if __name__ == "__main__":
    main()
