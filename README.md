# Synthetic GPS Ping Distance QA

A runnable, dependency-free Python reference project for finding and correcting distance-accounting errors in a fictional vehicle-advertising scenario.

> **Synthetic example only:** this project does not use real driver data and does not modify a live MUST product. Every CSV row is labelled `SYNTHETIC_TEST_DATA_NOT_REAL`.

## What it does

- Generates 2,004 synthetic GPS pings across four drivers.
- Injects off-road observations, over-speed points, duplicate timestamps, and late/out-of-order pings.
- Reports the affected ping IDs, measured offsets/speeds, and suspicious baseline segments.
- Compares a deliberately flawed legacy-style calculation with a corrected reference calculation per driver and UTC+9 reporting day.
- Tests filtering, ordering, deduplication, campaign-zone clipping, and the UTC+9 midnight boundary.

## Requirements

- Python 3.10 or later
- No third-party Python packages

## Quick start

Run these commands from the project directory:

```sh
python3 qa_tool.py --generate
python3 qa_tool.py
python3 -m unittest discover -s tests -v
```

The generator writes `data/synthetic_pings.csv`. Running it again deterministically replaces that generated fixture.

## Expected results

The QA report identifies four examples each of off-road, over-speed, duplicate, and out-of-order observations. It prints per-driver and per-day distances. With the generated fixture, the intentionally flawed baseline reports **10,980 m per driver** on UTC date `2026-10-31`. The corrected calculation reports:

| Driver | Corrected local 2026-10-31 | Corrected local 2026-11-01 |
|---|---:|---:|
| driver-01 | 400 m | 3,600 m |
| driver-02 | 400 m | 3,600 m |
| driver-03 | 400 m | 3,600 m |
| driver-04 | 400 m | 3,600 m |

The corrected calculation sorts pings by UTC timestamp, keeps the first row for each driver/timestamp pair, rejects observations more than 100 m off-road or implying speed above 150 km/h, clips distance to the campaign zone, and splits distance at the UTC+9 local-day boundary.

## Project files

- `qa_tool.py` — dataset generator, QA diagnostics, flawed baseline, and corrected reference calculator.
- `data/synthetic_pings.csv` — generated and clearly labelled synthetic fixture.
- `tests/test_qa_tool.py` — regression tests that assert baseline failures and corrected results.
- `intent.md` — ranked findings, effort, AI-use notes, and out-of-scope work.
- `Final directive.md` — requirements, run instructions, measured results, and handoff.

## Scope and limitations

This is a reference implementation, not a production billing fix. It models a straight synthetic route using along-route distance and lateral offset, assumes linear travel between valid observations, uses a fixed UTC+9 offset, and resolves conflicting duplicate payloads with first-row-wins. Real deployment would require validation against actual road geometry, telemetry quality, duplicate policy, and product/billing requirements.
