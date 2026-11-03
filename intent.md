# Intent

## What existed before

Nothing: the provided workspace was empty. This submission creates a small, runnable Python reference project; it does not modify or claim to fix a live MUST system.

## Problems found and impact ranking

The supplied assessment scenario describes the rules but includes no real telemetry or production calculation. I therefore generated a clearly labelled synthetic fixture and added a deliberately flawed baseline so each finding is reproducible rather than presented as a claim about a real service.

| Rank | Problem | Advertiser impact | Driver impact | How it was found |
|---|---|---|---|---|
| 1 | The baseline walks ingestion order and counts the whole distance between adjacent points whenever either endpoint is in the campaign zone. A late point creates a false long segment; a speed spike and off-road point can also inflate it. | High: overbilled campaign distance and unreliable daily totals. | High: incorrect earnings attribution and disputes. | Compared per-driver totals against the fixture's known 4,000 m in-zone path; diagnostic counts identify four late pings, four speed spikes and four off-road pings. |
| 2 | Duplicate `(driver, timestamp)` observations are not removed. | Medium: duplicate movement can be charged more than once if values differ. | Medium: duplicated records can distort credited distance. | Grouped rows by driver and timestamp; the fixture contains one repeated timestamp per driver. |
| 3 | UTC calendar dates are used instead of the required UTC+9 reporting day. | Medium: distance is assigned to the wrong campaign day despite possibly correct total distance. | Medium: daily earnings appear on the wrong day. | Compared UTC date grouping with the local midnight at 15:00 UTC; the fixture intentionally straddles that boundary. |
| 4 | Zone inclusion is endpoint-based instead of clipping the travelled segment to the zone boundary. | Medium: distance outside the campaign can be charged. | Medium: out-of-zone movement can be credited. | A regression case travels from route position 0 m to 200 m while the zone is 50–150 m; only 100 m is eligible. |
| 5 | Off-road points and implied speeds above 150 km/h are accepted by the baseline. | High when they occur in or near a campaign: noise can create large false distances. | High: can cause incorrect pay and reduce trust. | The checker applies the stated 100 m lateral-offset and 150 km/h limits and reports the injected violations. |

## First problem chosen

I solved the distance-accounting root cause first: calculate in timestamp order, deduplicate by driver/timestamp, reject invalid observations, clip each accepted route segment to the zone, and split eligible distance at local-day boundaries. This addresses the largest measurable overcount and makes each required rule explicit in one reference implementation. The fixture's stable expected result is 400 m per driver on 2026-10-31 and 3,600 m per driver on 2026-11-01.

## Scope and effort

Actual effort in this workspace: created a deterministic 2,004-row synthetic CSV, a command-line QA/report tool, a flawed comparison baseline, corrected calculation, and focused regression tests that independently assert the flawed baseline's wrong answer for each rule. No production service, map-matching system, database, or real driver data was available or changed. The chosen road is a straight synthetic route represented by along-route metres and lateral offset, so the narrow implementation can be audited without external data or dependencies.

## AI use and correction

AI was used to author the tool, generated fixture, tests, and handoff. An initial calculation approach treated zone membership as a property of the sampled endpoints; that would miss a segment that crosses the zone between two outside endpoints, and would over-credit a segment that only partly lies in the zone. I corrected the implementation to interpolate the route crossing fractions and added the 0→200 m / 50→150 m regression case. I also made the UTC+9 cut an explicit test at 15:00 UTC rather than relying on the fixture's aggregate alone.

I also reviewed the baseline-versus-fix assertions for test strength: a general "reports differ" check alone would not prove which requirements were fixed. I added focused cases comparing the intentionally flawed baseline with the corrected reference for off-road rejection, speed rejection, conflicting same-time duplicates, late arrival ordering, zone clipping, and the UTC+9 daily cut. The tests explicitly assert the incorrect baseline value and the expected corrected value for each case.

## Left out

- Production ingestion, billing integration, driver identity, authentication, deployment, and persistence.
- Road-network map matching or curved-road geometry; this synthetic reference uses a one-dimensional route coordinate and lateral offset.
- Resolving conflicting duplicate payloads: this implementation retains the first row for a `(driver, timestamp)` key, as documented in the directive.
- Sensor uncertainty, GPS drift inside the 100 m threshold, missing-ping interpolation policies, and dispute workflows.
- Daylight-saving time; the assessment specifies fixed UTC+9, which this tool models explicitly.
