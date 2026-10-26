"""
dashboard/server.py
===================
FastAPI backend for the Station Crowd Safety operator dashboard.

Endpoints
---------
GET  /                     Serve the operator HTML page
GET  /api/stream           Server-Sent Events — live alert feed
GET  /api/zones            Current status of every known zone (JSON)
GET  /api/alerts           Recent alert history (JSON, last 200)
POST /api/approve/{id}     Operator approves a recommendation
POST /api/dismiss/{id}     Operator dismisses an alert

Usage
-----
    pip install fastapi uvicorn
    cd Station-Crowd-Safety-Agent
    python dashboard/server.py                        # buildup scenario, 10x speed
    python dashboard/server.py --scenario bad_camera  # camera-failure scenario
    python dashboard/server.py --scenario normal      # quiet station
    python dashboard/server.py --speed 5              # slower playback (5x)
    python dashboard/server.py --speed 0              # as fast as possible
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Make the agent importable
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
from risk_agent import RiskAgent, ZoneReading  # noqa: E402
from llm_enricher import enrich_alert_async  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent / "cloud"))
from aws_bridge import upload_evidence_to_s3, dispatch_sns_critical_alert  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent

SCENARIO_FILES: Dict[str, str] = {
    "live":       "live_readings.jsonl",            # alias of live_platform
    "live_platform": "live_readings.jsonl",
    "live_corridor": "live_readings_corridor.jsonl",
    "normal":     "crowd-agent-week2-start/mock/scenario_normal.jsonl",
    "buildup":    "crowd-agent-week2-start/mock/scenario_buildup.jsonl",
    "bad_camera": "crowd-agent-week2-start/mock/scenario_bad_camera.jsonl",
}

# Annotated videos produced by the vision pipeline (faces already blurred)
SCENARIO_VIDEOS: Dict[str, str] = {
    "live":          "output_annotated.mp4",
    "live_platform": "output_annotated.mp4",
    "live_corridor": "output_annotated_corridor.mp4",
    "buildup":       "output_annotated.mp4",
    "normal":        "output_annotated.mp4",
    "bad_camera":    "output_annotated.mp4",
}

ALERT_HISTORY_SIZE = 200

# ---------------------------------------------------------------------------
# Shared in-memory state (single-server, no DB needed for prototype)
# ---------------------------------------------------------------------------

alert_history: deque[dict] = deque(maxlen=ALERT_HISTORY_SIZE)
zone_status: Dict[str, dict] = {}       # zone_id -> most-recent alert dict
approved_ids: set[str] = set()
dismissed_ids: set[str] = set()

# Playback clock: how far into the scenario (simulated seconds) we are, so the
# video stream can follow the readings.
_clock = {"offset": 0.0, "updated": 0.0, "speed": 1.0, "running": False, "gen": 0}
_start_event: Optional[asyncio.Event] = None   # set when the first browser connects

# SSE subscriber queues — one asyncio.Queue per connected browser tab
_subscribers: List[asyncio.Queue] = []


def _broadcast(event_type: str, payload: dict) -> None:
    """Push an SSE message to every connected subscriber."""
    msg = json.dumps({"type": event_type, "data": payload})
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)


# ---------------------------------------------------------------------------
# Background playback task
# ---------------------------------------------------------------------------

async def _playback_loop(scenario: str, speed: float) -> None:
    """Replay the scenario forever when it has a video (a demo that keeps running)."""
    while True:
        await _playback(scenario, speed)
        if scenario not in SCENARIO_VIDEOS or not _args.loop:
            return
        await asyncio.sleep(3)
        alert_history.clear()
        zone_status.clear()
        approved_ids.clear()
        dismissed_ids.clear()
        _broadcast("playback_restart", {"scenario": scenario})


async def _playback(scenario: str, speed: float) -> None:
    """
    Reads the scenario JSONL line-by-line, passes each reading through the
    risk agent, and broadcasts any alert via SSE.

    `speed` is the playback multiplier:
        10  = 10 seconds of simulation per 1 real second
        0   = as fast as possible (useful for testing)
    """
    path = REPO_ROOT / SCENARIO_FILES[scenario]
    if not path.exists():
        print(f"[server] Scenario file not found: {path}", file=sys.stderr)
        print("[server] Run: python crowd-agent-week2-start/mock/generate_mock.py",
              file=sys.stderr)
        return

    # Wait for the first browser so the operator sees the run from the start
    if _start_event is not None:
        await _start_event.wait()

    agent = RiskAgent()
    prev_sim_ts: Optional[float] = None
    first_sim_ts: Optional[float] = None
    _clock.update(offset=0.0, updated=time.monotonic(), speed=speed or 1.0, running=True,
                  gen=_clock["gen"] + 1)

    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue

            try:
                d = json.loads(raw)
                reading = ZoneReading.from_dict(d)
            except Exception as e:
                print(f"[server] Skipping bad line: {e}", file=sys.stderr)
                continue

            # --- real-time pacing ---
            sim_ts = reading.ts.timestamp()
            if prev_sim_ts is not None and speed > 0:
                sim_gap = sim_ts - prev_sim_ts          # seconds in simulation
                real_gap = sim_gap / speed              # seconds to wait
                if real_gap > 0:
                    await asyncio.sleep(real_gap)
            prev_sim_ts = sim_ts
            if first_sim_ts is None:
                first_sim_ts = sim_ts
            _clock.update(offset=sim_ts - first_sim_ts, updated=time.monotonic())

            # --- run the risk agent ---
            alert = agent.process(reading)
            state = agent._get_state(reading.zone_id)

            current_status = alert or {
                "alert_id": str(uuid.uuid4()),
                "ts": reading.ts.isoformat(),
                "camera_id": reading.camera_id,
                "zone_id": reading.zone_id,
                "zone_type": reading.zone_type,
                "level": state.last_level,
                "density_ppm2": reading.density_ppm2,
                "turbulence": reading.turbulence,
                "density_trend_per_min": state.density_trend_per_min(),
                "triggered_by": ["normal"],
                "reason": f"Zone {reading.zone_id} operating normally.",
                "recommendation": "Normal monitoring.",
                "confidence": reading.confidence,
                "quality_flags": reading.quality_flags,
                "requires_approval": False,
                "evidence_frame": reading.evidence_frame
            }
            zone_status[reading.zone_id] = current_status

            if alert:
                alert = await enrich_alert_async(alert)
                # AWS Cloud Bridge: S3 evidence archive + SNS emergency broadcast
                if alert.get("evidence_frame"):
                    s3_meta = upload_evidence_to_s3(alert["evidence_frame"], alert["zone_id"], alert.get("alert_id", ""))
                    if s3_meta.get("s3_uri"):
                        alert["s3_evidence_uri"] = s3_meta["s3_uri"]
                if alert.get("level") == "critical":
                    sns_meta = dispatch_sns_critical_alert(alert)
                    alert["sns_broadcast"] = sns_meta.get("status") in ("published", "simulated_sent")
                alert_history.append(alert)
                _broadcast("alert", alert)
            else:
                _broadcast("zone_update", current_status)

    _clock["running"] = False
    # Signal playback complete
    _broadcast("playback_complete", {"scenario": scenario})
    print(f"[server] Playback complete: {scenario}", file=sys.stderr)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Station Crowd Safety Dashboard", version="0.1.0")

# Serve the static HTML file
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Serve annotated evidence frames
_pipeline_dir = REPO_ROOT / "pipeline"
if _pipeline_dir.exists():
    app.mount("/pipeline", StaticFiles(directory=str(_pipeline_dir)), name="pipeline")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = _static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard HTML not found.</h1>", status_code=404)


@app.get("/api/info")
async def get_info() -> dict:
    return {"scenario": _args.scenario, "has_video": _video_path() is not None}


def _video_path() -> Optional[Path]:
    name = SCENARIO_VIDEOS.get(_args.scenario)
    path = REPO_ROOT / name if name else None
    return path if path and path.exists() else None


def _mjpeg_frames(path: Path):
    """Yield MJPEG parts, showing the video frame that matches the readings, looping continuously."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cur = -1
    gen = _clock["gen"]
    try:
        while True:
            if _clock["gen"] != gen:                 # a new run started: rewind
                gen = _clock["gen"]
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                cur = -1
            off = _clock["offset"]
            if _clock["running"]:
                # interpolate between 1 Hz readings
                off += min((time.monotonic() - _clock["updated"]) * _clock["speed"], 1.0)
            target = int(off * fps) % total_frames
            if target < cur:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                cur = -1
            if target > cur and _clock["gen"] > 0:
                while cur < target:
                    if not cap.grab():
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        cur = -1
                        break
                    cur += 1
                ok, frame = cap.retrieve()
                if ok:
                    jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                           + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            time.sleep(1 / 20)
    finally:
        cap.release()


@app.get("/api/video")
async def video_stream() -> StreamingResponse:
    path = _video_path()
    if path is None:
        raise HTTPException(status_code=404, detail="No annotated video for this scenario.")
    return StreamingResponse(_mjpeg_frames(path),
                             media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/zones")
async def get_zones() -> dict:
    """Return the latest known status for every zone."""
    return {"zones": list(zone_status.values()), "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/alerts")
async def get_alerts(limit: int = 50) -> dict:
    """Return the most-recent alerts from history."""
    recent = list(alert_history)[-limit:]
    return {"alerts": recent, "total": len(alert_history)}


@app.post("/api/approve/{alert_id}")
async def approve_alert(alert_id: str) -> dict:
    approved_ids.add(alert_id)
    dismissed_ids.discard(alert_id)
    _broadcast("approved", {"alert_id": alert_id})
    return {"status": "approved", "alert_id": alert_id}


@app.post("/api/dismiss/{alert_id}")
async def dismiss_alert(alert_id: str) -> dict:
    dismissed_ids.add(alert_id)
    approved_ids.discard(alert_id)
    _broadcast("dismissed", {"alert_id": alert_id})
    return {"status": "dismissed", "alert_id": alert_id}


@app.get("/api/stream")
async def sse_stream() -> StreamingResponse:
    """
    Server-Sent Events endpoint.
    Each event is a JSON object: { "type": "<event_type>", "data": { ... } }
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.append(queue)
    if _start_event is not None:
        _start_event.set()

    async def generator() -> AsyncGenerator[str, None]:
        # Send a hello event so the client knows it's connected
        yield _sse("connected", {"message": "Connected to alert stream.",
                                 "scenario": _args.scenario,
                                 "has_video": _video_path() is not None})
        # Send current zone snapshot immediately
        if zone_status:
            yield _sse("snapshot", {"zones": list(zone_status.values())})
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    raw = json.loads(msg)
                    yield _sse(raw["type"], raw["data"])
                except asyncio.TimeoutError:
                    # Keep-alive comment to prevent proxy timeouts
                    yield ": keep-alive\n\n"
        finally:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event_type: str, data: Any) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Startup hook — launch playback as background task
# ---------------------------------------------------------------------------

_args: argparse.Namespace  # set before app starts


@app.on_event("startup")
async def startup():
    global _start_event
    _start_event = asyncio.Event()
    asyncio.create_task(_playback_loop(_args.scenario, _args.speed))
    print(f"[server] Playback started: scenario={_args.scenario}, speed={_args.speed}x",
          file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    global _args
    parser = argparse.ArgumentParser(description="Station Crowd Safety Dashboard server")
    parser.add_argument(
        "--scenario", choices=list(SCENARIO_FILES.keys()), default="buildup",
        help="Mock scenario to stream (default: buildup)",
    )
    parser.add_argument(
        "--speed", type=float, default=None,
        help="Playback speed multiplier (default: 1 for live_* scenarios so the video "
             "plays in real time, otherwise 10; 0 = max speed)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--no-loop", dest="loop", action="store_false",
                        help="Play a live_* scenario once instead of looping it")
    _args = parser.parse_args()
    if _args.speed is None:
        _args.speed = 1.0 if _args.scenario in SCENARIO_VIDEOS else 10.0

    print(f"[server] Starting on http://{_args.host}:{_args.port}", file=sys.stderr)
    uvicorn.run(app, host=_args.host, port=_args.port, log_level="warning")


if __name__ == "__main__":
    main()

