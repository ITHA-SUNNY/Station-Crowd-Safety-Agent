"""Generate fake ZoneReading data so the agent and approval screen can be built
before the real vision pipeline exists.

Usage:  python3 generate_mock.py            -> writes the three scenarios below
Each output is JSON Lines: one ZoneReading per line, one line per zone per second.
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent
START = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

ZONES = [
    # camera, zone, type, area m2
    ("CAM-FOB2", "FOB2-STAIRS-DOWN", "stairs", 24.0),
    ("CAM-FOB2", "FOB2-DECK", "fob", 60.0),
    ("CAM-GATE1", "GATE1-ENTRY", "gate", 30.0),
    ("CAM-PF3", "PF3-EDGE", "platform_edge", 45.0),
]


def reading(t, cam, zone, ztype, area, density, turbulence, speed, conf=0.92, flags=None):
    density = max(0.0, density + random.uniform(-0.15, 0.15))
    return {
        "ts": (START + timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "camera_id": cam,
        "zone_id": zone,
        "zone_type": ztype,
        "area_m2": area,
        "people_count": round(density * area),
        "density_ppm2": round(density, 2),
        "turbulence": round(min(1.0, max(0.0, turbulence + random.uniform(-0.03, 0.03))), 2),
        "flow_speed_mps": round(max(0.0, speed + random.uniform(-0.05, 0.05)), 2),
        "confidence": round(conf, 2),
        "quality_flags": flags or [],
        "evidence_frame": f"mock/frames/{zone}_{t:04d}.jpg",
    }


def ramp(t, t0, t1, a, b):
    """Linear ramp from a (at t0) to b (at t1), flat outside."""
    if t <= t0:
        return a
    if t >= t1:
        return b
    return a + (b - a) * (t - t0) / (t1 - t0)


def scenario_normal(seconds=600):
    """10 minutes of an ordinary busy station. Should produce NO alerts."""
    rows = []
    for t in range(seconds):
        for cam, zone, ztype, area in ZONES:
            rows.append(reading(t, cam, zone, ztype, area, 1.2, 0.10, 1.1))
    return rows


def scenario_buildup(seconds=900):
    """15 minutes. A train arrives and FOB2 stairs fill up.
    Density on the stairs rises 1.5 -> 5.5 between minute 3 and minute 11,
    walking speed drops, and turbulence jumps after density passes ~4.5.
    The agent should warn early (rising), then recommend holding Gate 1 entry."""
    rows = []
    for t in range(seconds):
        for cam, zone, ztype, area in ZONES:
            if zone == "FOB2-STAIRS-DOWN":
                d = ramp(t, 180, 660, 1.5, 5.5)
                turb = 0.12 if d < 4.5 else ramp(t, 560, 720, 0.15, 0.7)
                speed = ramp(t, 180, 660, 1.1, 0.2)
                flags = ["too_dense_to_count"] if d >= 5.0 else []
                conf = 0.9 if d < 5.0 else 0.7
                rows.append(reading(t, cam, zone, ztype, area, d, turb, speed, conf, flags))
            elif zone == "FOB2-DECK":
                d = ramp(t, 240, 700, 1.2, 3.8)
                rows.append(reading(t, cam, zone, ztype, area, d, 0.15, ramp(t, 240, 700, 1.1, 0.5)))
            elif zone == "GATE1-ENTRY":
                rows.append(reading(t, cam, zone, ztype, area, ramp(t, 0, 600, 1.0, 2.5), 0.1, 1.0))
            else:
                rows.append(reading(t, cam, zone, ztype, area, 1.4, 0.1, 1.0))
    return rows


def scenario_bad_camera(seconds=600):
    """10 minutes. Platform 3 camera goes dark at minute 4 (low light, then no frame).
    Density readings become unreliable. The agent should say it cannot trust
    PF3-EDGE and ask a human to check, NOT report all clear."""
    rows = []
    for t in range(seconds):
        for cam, zone, ztype, area in ZONES:
            if zone == "PF3-EDGE" and t >= 240:
                if t < 360:
                    rows.append(reading(t, cam, zone, ztype, area, 0.4, 0.05, 0.3, 0.35, ["low_light"]))
                else:
                    rows.append(reading(t, cam, zone, ztype, area, 0.0, 0.0, 0.0, 0.0, ["no_frame"]))
            else:
                rows.append(reading(t, cam, zone, ztype, area, 1.3, 0.1, 1.1))
    return rows


def write(name, rows):
    path = OUT / f"{name}.jsonl"
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"{path.name}: {len(rows)} readings")


if __name__ == "__main__":
    random.seed(7)  # same fake data every run
    write("scenario_normal", scenario_normal())
    write("scenario_buildup", scenario_buildup())
    write("scenario_bad_camera", scenario_bad_camera())
