# Shared data format: vision pipeline → agent

The vision pipeline (Week 1) and the agent + approval screen (Week 2) only talk through this format. Agree on it once, then both sides can work in parallel.

## What the vision pipeline sends

About **once per second, one record per zone**, as JSON Lines (one JSON object per line). Full definition: `zone_reading.schema.json`.

```json
{"ts": "2026-10-12T09:10:00Z", "camera_id": "CAM-FOB2", "zone_id": "FOB2-STAIRS-DOWN",
 "zone_type": "stairs", "area_m2": 24.0, "people_count": 118, "density_ppm2": 4.92,
 "turbulence": 0.26, "flow_speed_mps": 0.3, "confidence": 0.7, "quality_flags": [],
 "evidence_frame": "mock/frames/FOB2-STAIRS-DOWN_0600.jpg"}
```

| Field | Meaning | Who fills it |
|---|---|---|
| `ts` | UTC time of the frame | pipeline |
| `camera_id`, `zone_id` | Which camera and which marked area | zone setup tool |
| `zone_type` | gate, stairs, platform_edge, concourse or fob — the agent picks actions by type | zone setup tool |
| `area_m2` | Real floor area after calibration | calibration |
| `people_count` | People counted in the zone | detector (Ultralytics YOLO) |
| `density_ppm2` | people_count ÷ area_m2 | pipeline |
| `turbulence` | 0 smooth flow → 1 chaotic pushing | optical flow |
| `flow_speed_mps` | Median walking speed | optical flow |
| `confidence` | 0–1, how much to trust this reading | quality checks |
| `quality_flags` | Why confidence is low (low_light, occluded, camera_moved, blur, too_dense_to_count, no_frame) | quality checks |
| `evidence_frame` | Optional annotated frame, faces blurred | pipeline |

## Starting rules for the agent (Week 2 — to tune)

The **rules make the safety call**; the language model only plans the next check and writes the explanation. It can never downgrade a rule's alert.

| Level | Trigger (per zone) | What the agent does |
|---|---|---|
| Normal | density < 2 and turbulence < 0.3 | Keep watching |
| Watch | density 2–4, or density rising > 0.5 per minute | Show on dashboard, no alert |
| Warning | density ≥ 4, or density rising fast toward 4 | Recommend an action, ask official to approve |
| Critical | density ≥ 5, or turbulence ≥ 0.5 with density ≥ 4 | Urgent recommendation, escalate if not approved in 60 s |
| Can't trust | confidence < 0.5 or flag `no_frame` / `camera_moved` | Ask a human to check the camera — never report "all clear" |

Danger threshold source: crush risk becomes deadly above roughly 4–5 people per m² (see problem statement).

Example actions by `zone_type`: stairs/fob → hold entry upstream (e.g. Gate 1), announce to use another FOB; gate → stagger entry, open overflow gate; platform_edge → hold platform entry, request train announcement.

## Fake data for testing now

`../mock/generate_mock.py` writes three scenarios that follow this format exactly:

| File | Story | Expected agent behaviour |
|---|---|---|
| `scenario_normal.jsonl` | 10 min of a normal busy station | No alerts at all |
| `scenario_buildup.jsonl` | Train arrives; FOB2 stairs go from 1.5 to 5.5 people/m² between minute 3 and 11, then turbulence jumps | Watch → Warning (around minute 7–9) → Critical, recommending to hold Gate 1 |
| `scenario_bad_camera.jsonl` | Platform 3 camera goes dark at minute 4 | "Can't trust PF3-EDGE" — ask a human, not all clear |

Run `python3 mock/generate_mock.py` to recreate them (same output every time).
