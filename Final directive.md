# Final directive

## Objective

Provide a runnable, auditable reference QA tool that makes the stated synthetic telemetry faults visible, demonstrates the flawed result, calculates corrected campaign distance per driver and local day, and locks the requirements in regression tests.

## Scope

- The project is standalone Python 3 and uses only the standard library.
- The fixture is synthetic, deterministic, and labelled `SYNTHETIC_TEST_DATA_NOT_REAL` on every row.
- `route_m` is distance along a straight synthetic road; `lateral_offset_m` is distance from that road.
- Campaign zone is the inclusive route interval 2,000–6,000 m.
- Reporting uses fixed UTC+9 local days; 00:00 local is 15:00 UTC.
- The intentionally flawed baseline is included only for comparison and must not be used for billing.

## Requirements and implementation decisions

1. Ignore a point when its absolute lateral offset is greater than 100 m.
2. Ignore a point when its implied speed from the previous accepted point in timestamp order is greater than 150 km/h. A rejected point does not become the next speed anchor.
3. Keep the first encountered row for a `(driver_id, UTC timestamp)` duplicate key; later rows with the same key are ignored.
4. Sort by each ping's own UTC timestamp before calculating distance; source/file order does not determine movement order.
5. Interpolate each accepted segment and count only the part inside the inclusive campaign route interval.
6. Split eligible segment distance at UTC+9 midnight, including a segment that itself crosses midnight.
7. Fail loudly on unexpected CSV columns, non-synthetic labels, or malformed rows.

## Completion criteria

- A fresh checkout can generate the fixture and run the report without installing packages.
- Dataset contains at least 2,000 labelled rows and includes off-road, over-speed, duplicate, and late/out-of-order examples.
- Report shows the problem counts and before/after distance per driver per day.
- Tests explicitly assert an incorrect baseline result and the corrected result for noise, speed, conflicting duplicates, late arrivals, zone clipping, and UTC+9 day assignment, as well as fixture-level fault counts and known totals.
- The documented run commands and output below match the checked-in implementation.

## Run and verify

From the project directory:

```sh
python3 qa_tool.py --generate
python3 qa_tool.py
python3 -m unittest discover -s tests -v
```

The generator writes [data/synthetic_pings.csv](./data/synthetic_pings.csv). The runnable checker and reference calculations are in [qa_tool.py](./qa_tool.py); regression coverage is in [tests/test_qa_tool.py](./tests/test_qa_tool.py).

## Results and handoff

**Actual fixture:** 2,004 synthetic rows: 4 drivers × 500 nominal pings, plus one duplicate per driver. Each trace also contains one off-road point, one over-speed point, and one late-arriving ping. These injected conditions overlap in a deterministic, intentional way.

**Checker findings:** 4 off-road points, 4 over-speed points, 4 duplicate rows, and 4 out-of-order arrivals. The CLI identifies the affected ping IDs and prints each offset or implied speed, not just aggregate counts. It also lists suspect baseline segments with both ping IDs, timestamps, route coordinates, charged distance, zone-clipped distance, and reason. Root cause is in the intentionally flawed `legacy_distance_report`: it pairs rows in file order, accepts invalid/noisy observations, assigns distance to the current ping's UTC date, and charges the full pairwise distance if either endpoint is in-zone. The late in-zone arrival therefore creates a large false segment. `corrected_distance_report` is the reference fix: it uses validated, deduplicated chronological points, clips to zone crossings, and splits the result by local day.

**Distance result (metres):** the legacy baseline puts its result on UTC date 2026-10-31; the corrected report uses local dates. Correct expected corrected result is 400 m per driver on 2026-10-31 and 3,600 m per driver on 2026-11-01. Exact baseline values from the runnable report:

| Driver | Legacy baseline, UTC 2026-10-31 | Corrected, local 2026-10-31 | Corrected, local 2026-11-01 |
|---|---:|---:|---:|
| driver-01 | 10,980 m | 400 m | 3,600 m |
| driver-02 | 10,980 m | 400 m | 3,600 m |
| driver-03 | 10,980 m | 400 m | 3,600 m |
| driver-04 | 10,980 m | 400 m | 3,600 m |

**Exact baseline overcount (driver-01; same trace for each driver):** the 10,980 m baseline is 6,980 m above the correct total 4,000 m. Its file-order segment diagnostics expose the contributions:

- Zone-entry segment ping-0099 (1,980 m) → ping-0100 (2,000 m) is charged as 20 m though only the boundary point is in-zone: **+20 m**.
- Zone-exit segment ping-0300 (6,000 m) → ping-0301 (6,020 m) is charged as 20 m though no positive-length part is inside the zone: **+20 m**.
- The injected speed spike creates two segments, 4,380→5,400 m (1,020 m) and 5,400→4,420 m (980 m), both in 10 seconds. Baseline charges 2,000 m; after rejecting the 367.2 km/h spike, the valid 4,380→4,420 m movement is 40 m: **+1,960 m**.
- The final file-order pair is ping-0499 (9,980 m at 16:03:10Z) → late ping-0250 (5,000 m at 15:21:40Z). Baseline charges **4,980 m** despite time moving backwards; this contributes a false extra segment. The chronological path already accounts for ping-0250's neighborhood.

These explain the delta exactly: 20 + 20 + (2,000 − 40) + 4,980 = **6,980 m**; 4,000 + 6,980 = **10,980 m**. The report's ping/segment diagnostics make these cases directly inspectable. Off-road and duplicate observations are also named in the issue report; their effect is covered independently by regression cases.

**Regression check:** the tests compare the old baseline directly with corrected outcomes for every major rule, rather than only asserting that aggregate reports differ. Examples: an off-road observation yields 180 m in the baseline versus 20 m corrected; an over-speed point yields 1,980 m versus 20 m; a conflicting duplicate yields 40 m versus 20 m; a late-arriving point yields 60 m versus 40 m; zone clipping yields 0 m versus 100 m; and the UTC+9 test assigns all 100 m to one UTC date instead of splitting 50/50 across local dates. The fixture-level regression also asserts the corrected 400/3,600 m daily totals. A further crossing case checks a segment from 0 to 200 m against a 50–150 m zone across local midnight and asserts exactly 50 m on each local day. A report-level check asserts the known suspicious segment IDs and inflated 4,980 m late segment. Verified with `python3 -m unittest discover -s tests -v`: all 12 tests passed.

**Known limitations:** this is a reference implementation, not a production fix. It assumes straight-road route coordinates, fixed UTC+9, linear movement between valid pings, and first-row-wins duplicate handling. It does not map-match real roads, model uncertainty below/at the threshold, infer missing telemetry, or settle conflicts between duplicate payloads. Validate those policies against actual product and billing requirements before deployment.
