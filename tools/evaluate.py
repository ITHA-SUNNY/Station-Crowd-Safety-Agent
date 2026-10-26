"""
tools/evaluate.py
=================
Reproducible evaluation for the Station Crowd Safety Agent.

Measures, on the machine it runs on:
  1. Risk-agent behaviour on the three contract scenarios (alert levels and timing,
     false alerts on the normal scenario).
  2. Vision-pipeline throughput (frames per second) on each demo profile.

It does NOT measure detection accuracy: that needs labelled ground truth. See
docs/evaluation.md for the small manual spot check that was done instead.

Usage (from the repository root):
    python tools/evaluate.py                # scenarios + throughput, writes docs/evaluation_results.json
    python tools/evaluate.py --skip-bench   # scenarios only (fast)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
from risk_agent import RiskAgent, ZoneReading  # noqa: E402

SCENARIOS = {
    "normal": "crowd-agent-week2-start/mock/scenario_normal.jsonl",
    "buildup": "crowd-agent-week2-start/mock/scenario_buildup.jsonl",
    "bad_camera": "crowd-agent-week2-start/mock/scenario_bad_camera.jsonl",
}


def hardware() -> dict:
    import cv2
    info = {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "cpu_threads": os.cpu_count(),
        "python": platform.python_version(),
        "opencv": cv2.__version__,
    }
    try:
        import torch
        info["torch"] = torch.__version__
        info["cuda"] = bool(torch.cuda.is_available())
    except Exception:
        info["torch"] = None
    try:
        import ultralytics
        info["ultralytics"] = ultralytics.__version__
    except Exception:
        info["ultralytics"] = None
    return info


def run_scenario(name: str, rel_path: str) -> dict:
    """Feed a scenario through the agent; report first-alert offsets per zone and level."""
    agent = RiskAgent()
    first_ts = None
    first_alert: dict[str, dict[str, float]] = {}   # zone -> level -> seconds from start
    n_readings = 0
    n_alerts = 0
    with (ROOT / rel_path).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            reading = ZoneReading.from_dict(json.loads(line))
            n_readings += 1
            ts = reading.ts.timestamp()
            first_ts = ts if first_ts is None else first_ts
            alert = agent.process(reading)
            if alert:
                n_alerts += 1
                zone = first_alert.setdefault(alert["zone_id"], {})
                zone.setdefault(alert["level"], round(ts - first_ts, 1))
    return {
        "readings": n_readings,
        "alerts_emitted": n_alerts,
        "first_alert_seconds_from_start": first_alert,
    }


def run_throughput(profile: str) -> dict:
    """Run the pipeline on a profile's video and parse the frames-per-second it achieved."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            sys.executable, str(ROOT / "pipeline" / "vision_pipeline.py"),
            "--profile", profile,
            "--out", str(Path(tmp) / "readings.jsonl"),
            "--save-video", str(Path(tmp) / "annotated.mp4"),
        ]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        m = re.search(r"Finished: (\d+) frames processed in ([\d.]+)s \((\d+) zone readings\)", proc.stderr)
        if not m:
            return {"error": "pipeline did not finish", "stderr_tail": proc.stderr[-400:]}
        frames, secs, readings = int(m.group(1)), float(m.group(2)), int(m.group(3))
        return {
            "frames": frames,
            "seconds": secs,
            "fps": round(frames / secs, 2),
            "zone_readings": readings,
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-bench", action="store_true", help="skip the (slow) throughput benchmark")
    ap.add_argument("--out", default=str(ROOT / "docs" / "evaluation_results.json"))
    args = ap.parse_args()

    results: dict = {"date": datetime.now().isoformat(timespec="seconds"), "hardware": hardware()}
    print("Hardware:", json.dumps(results["hardware"]))

    results["scenarios"] = {}
    for name, rel in SCENARIOS.items():
        results["scenarios"][name] = run_scenario(name, rel)
        print(f"[scenario] {name}: {json.dumps(results['scenarios'][name])}")

    if not args.skip_bench:
        results["throughput"] = {}
        for profile in ("platform", "corridor"):
            print(f"[bench] running pipeline on profile '{profile}' (a couple of minutes)...", flush=True)
            results["throughput"][profile] = run_throughput(profile)
            print(f"[bench] {profile}: {json.dumps(results['throughput'][profile])}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
