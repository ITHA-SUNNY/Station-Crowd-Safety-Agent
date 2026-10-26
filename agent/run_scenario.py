"""
run_scenario.py
===============
Test runner for the risk agent.

Feeds each of the three mock scenarios through the agent and prints
a summary showing:
  - every alert emitted (level, zone, time, trigger)
  - pass/fail verdict against the expected behaviour in contract/README.md

Usage:
    python agent/run_scenario.py

Or to test a single scenario and save the alert JSONL:
    python agent/run_scenario.py --scenario buildup --out alerts_buildup.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path

# Make sure the agent module is importable when run from the repo root
sys.path.insert(0, str(Path(__file__).parent))
from risk_agent import run_stream  # noqa: E402

# ---------------------------------------------------------------------------
# Expected-behaviour checklist (from contract/README.md)
# ---------------------------------------------------------------------------

SCENARIOS = {
    "normal": {
        "file": "crowd-agent-week2-start/mock/scenario_normal.jsonl",
        "description": "10 min of a normal busy station",
        "expect_no_alerts": True,
        "expect_levels": [],          # none expected
    },
    "buildup": {
        "file": "crowd-agent-week2-start/mock/scenario_buildup.jsonl",
        "description": (
            "Train arrives; FOB2 stairs go 1.5 -> 5.5 p/m2 between min 3-11, "
            "then turbulence jumps -> Watch -> Warning (min 7-9) -> Critical"
        ),
        "expect_no_alerts": False,
        "expect_levels": ["watch", "warning", "critical"],
        "expect_zone": "FOB2-STAIRS-DOWN",
    },
    "bad_camera": {
        "file": "crowd-agent-week2-start/mock/scenario_bad_camera.jsonl",
        "description": "Platform 3 camera goes dark at minute 4",
        "expect_no_alerts": False,
        "expect_levels": ["cant_trust"],
        "expect_zone": "PF3-EDGE",
    },
}

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_ts(iso: str) -> str:
    """Return HH:MM:SS from an ISO timestamp string."""
    return iso[11:19]


def run_one(scenario_key: str, verbose: bool = True, out_path: Path | None = None):
    cfg = SCENARIOS[scenario_key]
    jsonl_path = REPO_ROOT / cfg["file"]

    print(f"\n{'='*70}")
    print(f"  SCENARIO : {scenario_key.upper()}")
    print(f"  File     : {cfg['file']}")
    print(f"  Expected : {cfg['description']}")
    print(f"{'='*70}")

    if not jsonl_path.exists():
        print(f"  [ERROR] File not found: {jsonl_path}")
        print("  Run: python crowd-agent-week2-start/mock/generate_mock.py")
        return False

    # Run the agent, capture alert JSONL into a buffer
    with jsonl_path.open(encoding="utf-8") as src:
        buf = StringIO()
        n_alerts = run_stream(src, output=buf, verbose=False)

    alerts_raw = [
        json.loads(line)
        for line in buf.getvalue().splitlines()
        if line.strip()
    ]

    # ----------------------------------------------------------------
    # Print alert summary
    # ----------------------------------------------------------------
    if not alerts_raw:
        print("  No alerts emitted.")
    else:
        # Group by zone for readability
        by_zone: dict = defaultdict(list)
        for a in alerts_raw:
            by_zone[a["zone_id"]].append(a)

        for zone_id, zone_alerts in by_zone.items():
            print(f"\n  Zone: {zone_id}")
            level_seq: list[str] = []
            for a in zone_alerts:
                ts   = _short_ts(a["ts"])
                lvl  = a["level"].upper()
                trg  = ", ".join(a["triggered_by"])
                d    = a["density_ppm2"]
                trnd = a.get("density_trend_per_min", 0.0)
                print(f"    [{ts}] {lvl:12s}  density={d:.2f}  trend={trnd:+.2f}/min  triggers=[{trg}]")
                if verbose and lvl not in ("NORMAL",):
                    print(f"           > {a['recommendation'][:80]}")
                level_seq.append(a["level"])

    # ----------------------------------------------------------------
    # Verdict
    # ----------------------------------------------------------------
    print()
    passed = True
    levels_seen = {a["level"] for a in alerts_raw}
    zones_seen  = {a["zone_id"] for a in alerts_raw}

    if cfg["expect_no_alerts"]:
        if n_alerts == 0:
            print("  [PASS]  No alerts emitted -- as expected for a normal scenario.")
        else:
            print(f"  [FAIL]  Expected 0 alerts but got {n_alerts}.")
            passed = False
    else:
        for expected_level in cfg["expect_levels"]:
            if expected_level in levels_seen:
                print(f"  [PASS]  Level '{expected_level}' was seen.")
            else:
                print(f"  [FAIL]  Expected level '{expected_level}' was NOT seen.")
                passed = False
        if "expect_zone" in cfg:
            ez = cfg["expect_zone"]
            if ez in zones_seen:
                print(f"  [PASS]  Zone '{ez}' triggered alerts -- as expected.")
            else:
                print(f"  [FAIL]  Expected alerts on zone '{ez}' but none were seen.")
                passed = False

    # ----------------------------------------------------------------
    # Optional output file
    # ----------------------------------------------------------------
    if out_path and alerts_raw:
        out_path.write_text(
            "\n".join(json.dumps(a) for a in alerts_raw) + "\n",
            encoding="utf-8",
        )
        print(f"\n  Alert JSONL written to: {out_path}")

    print(f"\n  Total alerts: {n_alerts}")
    return passed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run mock scenarios through the risk agent and check results."
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()) + ["all"],
        default="all",
        help="Which scenario to run (default: all).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for alert JSONL (single-scenario mode only).",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-alert recommendation text.",
    )
    args = parser.parse_args()

    keys = list(SCENARIOS.keys()) if args.scenario == "all" else [args.scenario]
    out_path = Path(args.out) if args.out else None

    results: dict[str, bool] = {}
    for key in keys:
        results[key] = run_one(key, verbose=not args.quiet,
                                out_path=out_path if len(keys) == 1 else None)

    print(f"\n{'='*70}")
    print("  SUMMARY")
    all_passed = True
    for key, ok in results.items():
        status = "[PASS]" if ok else "[FAIL]"
        print(f"    {status}  {key}")
        if not ok:
            all_passed = False
    print(f"{'='*70}\n")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
