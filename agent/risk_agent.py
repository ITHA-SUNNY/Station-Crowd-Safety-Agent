"""
risk_agent.py
=============
Crowd Safety Risk Agent — Workstream 2

Reads a stream of ZoneReading JSON objects (one per line, from a file or
stdin) and emits CrowdAlert JSON objects whenever the risk level for a
zone changes, or whenever the level is Warning/Critical (re-emitted each
cycle so the dashboard always has a live pulse).

Rule table (from contract/README.md):
  Normal    : density < 2  AND turbulence < 0.3
  Watch     : density 2–4,  OR trend > +0.5 p/m²/min
  Warning   : density ≥ 4,  OR trend rising fast toward 4
  Critical  : density ≥ 5,  OR (turbulence ≥ 0.5 AND density ≥ 4)
  Can't trust: confidence < 0.5 OR quality_flag in {no_frame, camera_moved}

The rule engine makes the safety call; an optional LLM hook can enrich
the human-readable `reason` field but can never downgrade the level.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants — tune these without touching the logic
# ---------------------------------------------------------------------------

TREND_WINDOW_S          = 60      # seconds of history for trend calculation
TREND_WATCH_THRESHOLD   = 0.5    # p/m²/min  -> Watch (contract: rising > 0.5/min)
TREND_WARNING_THRESHOLD = 1.0    # p/m²/min  -> Warning if also projected to reach 4 within a minute
TREND_MIN_SAMPLES       = 30     # readings (~half the window) before the trend is trusted
# Hysteresis: once at a level, stay there until density drops below this value,
# so a zone hovering on a threshold doesn't flap between levels.
EXIT_DENSITY = {"watch": 1.8, "warning": 3.7, "critical": 4.7}
LEVEL_RANK   = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}

DENSITY_NORMAL_MAX   = 2.0
DENSITY_WATCH_MAX    = 4.0
DENSITY_WARNING_MIN  = 4.0
DENSITY_CRITICAL_MIN = 5.0

TURBULENCE_CRITICAL  = 0.5       # turbulence ≥ this AND density ≥ 4 → Critical
CONFIDENCE_MIN       = 0.5       # below this → cant_trust

ESCALATE_AFTER_S     = 60        # seconds before re-escalation if not approved

# ---------------------------------------------------------------------------
# Recommendation text by zone type and level
# ---------------------------------------------------------------------------

RECOMMENDATIONS: Dict[str, Dict[str, str]] = {
    "stairs": {
        "watch":      "Monitor the stairs closely. Density is rising.",
        "warning":    "Recommend: hold entry at Gate 1 to reduce stair flow. "
                      "Announce via PA to use the alternative FOB.",
        "critical":   "URGENT: Immediately hold all entry at Gate 1. "
                      "Deploy staff to stairhead. Announce alternative FOB now.",
        "cant_trust": "Camera issue on stairway zone — send staff to visually "
                      "check the area. Do not report all-clear until confirmed.",
    },
    "fob": {
        "watch":      "FOB deck density rising. Watch for queuing at stair entries.",
        "warning":    "Recommend: stagger entry through FOB gates. "
                      "Open overflow FOB if available.",
        "critical":   "URGENT: Close FOB entry gates temporarily. "
                      "Deploy staff to manage crowd. Open overflow FOB immediately.",
        "cant_trust": "Camera issue on FOB zone — visual inspection required.",
    },
    "gate": {
        "watch":      "Gate entry density rising. Monitor throughput.",
        "warning":    "Recommend: stagger entry timing. Open overflow gate if available.",
        "critical":   "URGENT: Pause entry flow through gate. "
                      "Open all overflow gates and request crowd dispersal.",
        "cant_trust": "Camera issue at gate — deploy staff for manual count.",
    },
    "platform_edge": {
        "watch":      "Platform edge density rising. Watch for crowding near the edge.",
        "warning":    "Recommend: hold platform entry. "
                      "Request train announcement to move away from edge.",
        "critical":   "URGENT: Stop platform entry immediately. "
                      "Request emergency train announcement. Deploy platform staff.",
        "cant_trust": "Camera issue on platform edge — send staff immediately. "
                      "This is safety-critical.",
    },
    "concourse": {
        "watch":      "Concourse density rising. Monitor flow directions.",
        "warning":    "Recommend: open additional concourse routes if available.",
        "critical":   "URGENT: Manage concourse entry. Deploy staff for crowd guidance.",
        "cant_trust": "Camera issue on concourse — visual inspection required.",
    },
}

def _get_recommendation(zone_type: str, level: str) -> str:
    if level == "normal":
        return "Zone has returned to normal. Keep watching."
    zone_recs = RECOMMENDATIONS.get(zone_type, {})
    return zone_recs.get(level, f"Review zone {zone_type} — level {level}.")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ZoneReading:
    ts: datetime
    camera_id: str
    zone_id: str
    zone_type: str
    area_m2: float
    people_count: int
    density_ppm2: float
    turbulence: float
    flow_speed_mps: float
    confidence: float
    quality_flags: List[str]
    evidence_frame: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ZoneReading":
        return cls(
            ts=datetime.fromisoformat(d["ts"].replace("Z", "+00:00")),
            camera_id=d["camera_id"],
            zone_id=d["zone_id"],
            zone_type=d["zone_type"],
            area_m2=d["area_m2"],
            people_count=d["people_count"],
            density_ppm2=d["density_ppm2"],
            turbulence=d["turbulence"],
            flow_speed_mps=d["flow_speed_mps"],
            confidence=d["confidence"],
            quality_flags=d.get("quality_flags", []),
            evidence_frame=d.get("evidence_frame"),
        )


@dataclass
class ZoneState:
    """Mutable state the agent keeps per zone across readings."""
    zone_id: str
    history: Deque[Tuple[datetime, float]] = field(default_factory=deque)
    last_level: str = "normal"

    def add_reading(self, ts: datetime, density: float) -> None:
        self.history.append((ts, density))
        # Evict readings older than TREND_WINDOW_S
        cutoff = ts.timestamp() - TREND_WINDOW_S
        while self.history and self.history[0][0].timestamp() < cutoff:
            self.history.popleft()

    def density_trend_per_min(self) -> float:
        """
        Linear regression slope (p/m²/min) over the rolling window.
        Returns 0.0 if fewer than 2 data points.
        """
        if len(self.history) < 2:
            return 0.0
        times   = [t.timestamp() for t, _ in self.history]
        densities = [d for _, d in self.history]
        n = len(times)
        t0 = times[0]
        xs = [(t - t0) for t in times]         # seconds from first sample
        mean_x = sum(xs) / n
        mean_y = sum(densities) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, densities))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0:
            return 0.0
        slope_per_sec = num / den
        return round(slope_per_sec * 60, 4)     # convert to per-minute


# ---------------------------------------------------------------------------
# Core rule engine
# ---------------------------------------------------------------------------

def classify_level(
    reading: ZoneReading,
    trend: float,
    history_len: int = 0,
) -> Tuple[str, List[str]]:
    """
    Returns (level, triggered_by_list).
    Rules are evaluated from most-severe to least-severe so the highest
    matching level wins.  The LLM must never downgrade this result.
    """
    flags = reading.quality_flags
    conf  = reading.confidence
    d     = reading.density_ppm2
    turb  = reading.turbulence

    triggered: List[str] = []

    # Only trust trend when we have enough history (avoids false positives
    # from the noisy regression over the first few readings).
    use_trend = history_len >= TREND_MIN_SAMPLES

    # --- Can't trust ---
    cant_trust_flags = {"no_frame", "camera_moved"}
    if conf < CONFIDENCE_MIN:
        triggered.append("low_confidence")
    if cant_trust_flags & set(flags):
        for f in cant_trust_flags & set(flags):
            triggered.append(f)
    if triggered:
        return "cant_trust", triggered

    # --- Critical ---
    if d >= DENSITY_CRITICAL_MIN:
        triggered.append("density_critical")
    if turb >= TURBULENCE_CRITICAL and d >= DENSITY_WARNING_MIN:
        triggered.append("turbulence_critical")
    if triggered:
        return "critical", triggered

    # --- Warning ---
    if d >= DENSITY_WARNING_MIN:
        triggered.append("density_warning")
    # "Rising fast toward 4": steep trend and on course to reach 4 within a minute
    if use_trend and trend >= TREND_WARNING_THRESHOLD and d + trend >= DENSITY_WARNING_MIN:
        triggered.append("trend_rising_warning")
    if triggered:
        return "warning", triggered

    # --- Watch ---
    if DENSITY_NORMAL_MAX <= d < DENSITY_WATCH_MAX:
        triggered.append("density_watch")
    if use_trend and trend > TREND_WATCH_THRESHOLD:
        triggered.append("trend_rising_watch")
    if triggered:
        return "watch", triggered

    # --- Normal ---
    return "normal", ["normal"]


def build_reason(reading: ZoneReading, trend: float, level: str, triggered: List[str]) -> str:
    """Produce a concise, factual reason string (no LLM needed for this)."""
    parts: List[str] = []
    d = reading.density_ppm2
    parts.append(f"Zone {reading.zone_id}: density={d:.2f} p/m², "
                 f"turbulence={reading.turbulence:.2f}, "
                 f"trend={trend:+.2f} p/m²/min, "
                 f"confidence={reading.confidence:.2f}.")

    if "density_critical" in triggered:
        parts.append(f"Density ≥ {DENSITY_CRITICAL_MIN} p/m² — crush risk.")
    if "turbulence_critical" in triggered:
        parts.append("High turbulence with elevated density — chaotic crowd movement.")
    if "density_warning" in triggered:
        parts.append(f"Density ≥ {DENSITY_WARNING_MIN} p/m² — approaching dangerous levels.")
    if "trend_rising_warning" in triggered:
        parts.append(f"Density rising at {trend:.2f} p/m²/min — will reach warning threshold soon.")
    if "density_watch" in triggered:
        parts.append("Density in watch band (2–4 p/m²).")
    if "trend_rising_watch" in triggered:
        parts.append(f"Density rising at {trend:.2f} p/m²/min.")
    if "hysteresis_hold" in triggered:
        parts.append("Density still near the threshold — holding the previous level.")
    if "low_confidence" in triggered:
        parts.append(f"Confidence {reading.confidence:.2f} < {CONFIDENCE_MIN} — reading unreliable.")
    if "no_frame" in triggered or "camera_moved" in triggered:
        parts.append(f"Quality flags: {reading.quality_flags} — camera issue.")

    return " ".join(parts)


def build_alert(reading: ZoneReading, state: ZoneState, level: str,
                triggered: List[str], trend: float) -> dict:
    requires_approval = level in ("warning", "critical")
    alert: dict = {
        "alert_id":              str(uuid.uuid4()),
        "ts":                    reading.ts.isoformat(),
        "camera_id":             reading.camera_id,
        "zone_id":               reading.zone_id,
        "zone_type":             reading.zone_type,
        "level":                 level,
        "density_ppm2":          reading.density_ppm2,
        "turbulence":            reading.turbulence,
        "density_trend_per_min": trend,
        "triggered_by":          triggered,
        "reason":                build_reason(reading, trend, level, triggered),
        "recommendation":        _get_recommendation(reading.zone_type, level),
        "confidence":            reading.confidence,
        "quality_flags":         reading.quality_flags,
        "requires_approval":     requires_approval,
    }
    if reading.evidence_frame:
        alert["evidence_frame"] = reading.evidence_frame
    if requires_approval:
        alert["escalate_after_s"] = ESCALATE_AFTER_S
    return alert


# ---------------------------------------------------------------------------
# Agent main loop
# ---------------------------------------------------------------------------

class RiskAgent:
    """
    Stateful agent.  Call `process(reading)` for each incoming ZoneReading.
    It returns a CrowdAlert dict when an alert should be emitted, or None
    when the zone is Normal and was already Normal (silent).
    """

    def __init__(self) -> None:
        self._zone_states: Dict[str, ZoneState] = {}

    def _get_state(self, zone_id: str) -> ZoneState:
        if zone_id not in self._zone_states:
            self._zone_states[zone_id] = ZoneState(zone_id=zone_id)
        return self._zone_states[zone_id]

    def process(self, reading: ZoneReading) -> Optional[dict]:
        state = self._get_state(reading.zone_id)
        state.add_reading(reading.ts, reading.density_ppm2)
        trend = state.density_trend_per_min()

        level, triggered = classify_level(reading, trend, history_len=len(state.history))
        prev_level = state.last_level

        if (prev_level in EXIT_DENSITY and level in LEVEL_RANK
                and LEVEL_RANK[level] < LEVEL_RANK[prev_level]
                and reading.density_ppm2 >= EXIT_DENSITY[prev_level]):
            level, triggered = prev_level, ["hysteresis_hold"]

        # Emit alert if:
        #   - level changed  (any direction — operator needs to know it cleared too)
        #   - level is warning/critical  (always pulse so dashboard stays live)
        #   - level is cant_trust  (always pulse — camera problem persists)
        emit = (
            level != prev_level
            or level in ("warning", "critical", "cant_trust")
        )

        state.last_level = level

        if emit and level != "normal":
            return build_alert(reading, state, level, triggered, trend)

        # Emit a "cleared" notice when dropping back to Normal
        if level == "normal" and prev_level != "normal":
            return build_alert(reading, state, level, ["normal"], trend)

        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_stream(source, output=sys.stdout, verbose: bool = False) -> int:
    """
    Process all ZoneReading lines from `source` (file-like or list of strings).
    Writes CrowdAlert JSON lines to `output`.
    Returns the number of alerts emitted.
    """
    agent = RiskAgent()
    alert_count = 0

    for raw_line in source:
        line = raw_line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[WARN] Skipping malformed line: {e}", file=sys.stderr)
            continue

        try:
            reading = ZoneReading.from_dict(d)
        except (KeyError, ValueError) as e:
            print(f"[WARN] Skipping invalid reading: {e}", file=sys.stderr)
            continue

        alert = agent.process(reading)
        if alert:
            print(json.dumps(alert), file=output)
            alert_count += 1
            if verbose:
                ts_short = reading.ts.strftime("%H:%M:%S")
                print(
                    f"  [{ts_short}] {alert['level'].upper():10s} "
                    f"{reading.zone_id:25s} "
                    f"density={reading.density_ppm2:.2f} "
                    f"trend={reading.density_trend_per_min():.2f}",
                    file=sys.stderr,
                )

    return alert_count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Station Crowd Safety Risk Agent — processes ZoneReading JSONL."
    )
    parser.add_argument(
        "input", nargs="?",
        help="Path to .jsonl file. Omit to read from stdin.",
    )
    parser.add_argument(
        "-o", "--output", default="-",
        help="Output file for alert JSONL. Default: stdout.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print a human-readable summary line to stderr for each alert.",
    )
    args = parser.parse_args()

    src = open(args.input, encoding="utf-8") if args.input else sys.stdin
    out = open(args.output, "w", encoding="utf-8") if args.output != "-" else sys.stdout

    try:
        n = run_stream(src, output=out, verbose=args.verbose)
        print(f"\n[Done] {n} alerts emitted.", file=sys.stderr)
    finally:
        if args.input:
            src.close()
        if args.output != "-":
            out.close()
