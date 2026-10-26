"""
agent/llm_enricher.py
=====================
LLM Enrichment Layer — Workstream 2

Calls Gemini (gemini-3.8-flash) to generate a plain-English operator-facing
incident brief for Warning, Critical and Can't trust alerts.

Safety contract (NON-NEGOTIABLE):
  - This module may ONLY write to alert["llm_summary"].
  - It can NEVER modify alert["level"], alert["recommendation"],
    alert["triggered_by"], or any other field set by the rule engine.
  - If the Gemini call fails or times out, the alert is emitted safely.
    A failed enrichment MUST NEVER block or drop the alert.

Usage
-----
Standalone test:
    python agent/llm_enricher.py

Imported by server.py:
    from llm_enricher import enrich_alert_async
    alert = await enrich_alert_async(alert)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# SDK check
# ---------------------------------------------------------------------------
try:
    from google import genai
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "gemini-3.8-flash"

# Only enrich high-priority alerts
ENRICH_LEVELS = {"warning", "critical", "cant_trust"}

# Timeout for a single Gemini call (seconds)
LLM_TIMEOUT_S = 6.0

# System instruction: concise, factual operator brief
_SYSTEM_INSTRUCTION = (
    "You are the safety explanation layer for an Indian Railway station crowd monitoring system. "
    "Your job is to provide a brief 2-sentence situational summary for the station controller. "
    "State what is happening, where it is occurring, and the specific crowd risk. "
    "Do NOT prescribe operational actions (those are set by standard operating rules). "
    "Do NOT use raw metrics like 'ppm2' or 'turbulence score' — translate them into clear operational English. "
    "Keep it calm, precise, and under 50 words."
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_alert_sync(alert: dict) -> dict:
    """
    Enrich an alert dictionary with `llm_summary`.
    Thread-safe and synchronous.
    """
    if alert.get("level") not in ENRICH_LEVELS:
        return alert

    api_key = os.environ.get("GEMINI_API_KEY")

    # If API key is present and SDK is available, call Gemini
    if _SDK_AVAILABLE and api_key:
        try:
            client = genai.Client()
            prompt = _build_prompt(alert)
            interaction = client.interactions.create(
                model=MODEL,
                system_instruction=_SYSTEM_INSTRUCTION,
                input=prompt,
                store=False,
            )
            summary = (interaction.output_text or "").strip()
            if summary:
                alert["llm_summary"] = summary
                alert["llm_source"] = "gemini-3.8-flash"
                return alert
        except Exception as exc:
            alert["llm_summary"] = f"[Gemini unavailable: {type(exc).__name__}]"
            alert["llm_source"] = "error"
            return alert

    # Graceful fallback: synthesize a crisp incident brief based on rule signals
    alert["llm_summary"] = _synthesize_fallback_summary(alert)
    alert["llm_source"] = "rule-synth" if not api_key else "offline"
    return alert


async def enrich_alert_async(alert: dict) -> dict:
    """
    Non-blocking async wrapper for FastAPI/asyncio event loops.
    """
    if alert.get("level") not in ENRICH_LEVELS:
        return alert

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, enrich_alert_sync, alert),
            timeout=LLM_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        alert["llm_summary"] = "[Incident brief timeout — dispatched with standard rule reason]"
        alert["llm_source"] = "timeout"
        return alert
    except Exception as exc:
        alert["llm_summary"] = f"[Incident brief error: {type(exc).__name__}]"
        alert["llm_source"] = "error"
        return alert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_prompt(alert: dict) -> str:
    level = alert.get("level", "unknown").upper()
    zone_id = alert.get("zone_id", "station zone")
    zone_type = alert.get("zone_type", "zone")
    density = alert.get("density_ppm2", 0.0)
    turb = alert.get("turbulence", 0.0)
    trend = alert.get("density_trend_per_min", 0.0)
    triggered = alert.get("triggered_by", [])

    crowd_flow = "turbulent and irregular" if turb >= 0.4 else "steady forward flow"

    return (
        f"Alert Level: {level}\n"
        f"Zone: {zone_id} ({zone_type.replace('_', ' ')})\n"
        f"Observed Density: {density:.2f} people/m2 (Trend: {trend:+.2f} people/min)\n"
        f"Flow Dynamic: {crowd_flow}\n"
        f"Triggered conditions: {', '.join(triggered)}\n\n"
        "Generate the concise operator situational summary:"
    )


def _synthesize_fallback_summary(alert: dict) -> str:
    level = alert.get("level", "normal")
    zone = alert.get("zone_id", "Monitored Zone")
    density = alert.get("density_ppm2", 0.0)
    turb = alert.get("turbulence", 0.0)
    triggered = alert.get("triggered_by", [])

    if level == "cant_trust":
        return f"Optical sensors on {zone} are reporting unreliable frames or misalignment. Physical confirmation required."

    if level == "critical":
        if turb >= 0.5:
            return f"Extreme crowd compaction detected at {zone} with erratic multidirectional motion. Severe crush risk if ingress continues."
        return f"Severe crowd buildup observed at {zone} exceeding {density:.1f} people/m². Structural bottleneck forming rapidly."

    if level == "warning":
        if "trend_rising_warning" in triggered:
            return f"Rapid density accumulation underway at {zone}. Crowd volume is accelerating toward critical capacity."
        return f"Elevated crowd concentration detected across {zone}. Flow velocity is tapering and approaching warning thresholds."

    return f"Elevated foot traffic at {zone}. Monitoring for continued buildup."


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = {
        "level": "critical",
        "zone_id": "FOB2-STAIRS-DOWN",
        "zone_type": "stairs",
        "density_ppm2": 5.4,
        "turbulence": 0.58,
        "density_trend_per_min": 1.2,
        "triggered_by": ["density_critical", "turbulence_critical"],
    }
    print("Testing enrich_alert_sync:")
    res = enrich_alert_sync(sample)
    print("Source :", res.get("llm_source"))
    print("Summary:", res.get("llm_summary"))
