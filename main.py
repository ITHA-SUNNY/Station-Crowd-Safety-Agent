"""
main.py
=======
Station Crowd Safety Agent — Unified System Entry Point

Provides a single master command to launch any part of the system:
- Full Operator Dashboard (with live CCTV video & Gemini AI Situation Briefs)
- Live Vision Pipeline processing on raw footage
- Rule engine verification tests

Usage Examples
--------------
1. Launch operator dashboard with simulated crowd crush buildup (10x speed):
    python main.py

2. Launch operator dashboard with real Indian railway CCTV platform footage:
    python main.py --scenario live

3. Process a new video with YOLO11 + optical flow, then open dashboard:
    python main.py --video crowd.mp4

4. Run all rule-engine test scenarios:
    python main.py --test

5. Verify Gemini 3.8 Flash connection & situational brief generation:
    python main.py --test-llm
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()


def run_tests() -> int:
    """Run all 3 rule-engine validation scenarios."""
    print("=" * 70)
    print("  RUNNING SAFETY AGENT VERIFICATION SUITE")
    print("=" * 70)
    runner = REPO_ROOT / "agent" / "run_scenario.py"
    return subprocess.call([sys.executable, str(runner)])


def run_llm_test() -> int:
    """Test Gemini 3.8 Flash enrichment layer."""
    print("=" * 70)
    print("  TESTING GEMINI 3.8 FLASH SITUATION BRIEF ENRICHER")
    print("=" * 70)
    enricher = REPO_ROOT / "agent" / "llm_enricher.py"
    return subprocess.call([sys.executable, str(enricher)])


def run_aws_test() -> int:
    """Test AWS S3 and SNS cloud bridge."""
    print("=" * 70)
    print("  TESTING AWS CLOUD BRIDGE (S3 Evidence Storage & SNS Broadcast)")
    print("=" * 70)
    bridge = REPO_ROOT / "cloud" / "aws_bridge.py"
    return subprocess.call([sys.executable, str(bridge)])


def run_vision_pipeline(video_path: str, profile: str = "platform") -> int:
    """Run the YOLO11 + Optical Flow vision pipeline on a video file."""
    print("=" * 70)
    print(f"  RUNNING VISION PIPELINE on {video_path} (profile={profile})")
    print("=" * 70)
    script = REPO_ROOT / "pipeline" / "vision_pipeline.py"
    cmd = [
        sys.executable,
        str(script),
        "--profile", profile,
        "--video", video_path,
        "--out", "live_readings.jsonl",
        "--save-video", "output_annotated.mp4",
    ]
    return subprocess.call(cmd)


def launch_dashboard(scenario: str, speed: float, port: int, host: str, no_browser: bool) -> None:
    """Start the FastAPI dashboard server and open the browser."""
    url = f"http://{host}:{port}"
    print("=" * 70)
    print("  STATION CROWD SAFETY AGENT — OPERATOR DASHBOARD")
    print(f"  Scenario : {scenario}")
    print(f"  Playback : {speed}x speed")
    print(f"  Server   : {url}")
    print(f"  AI Brief : {'Enabled (Gemini 3.8 Flash)' if os.environ.get('GEMINI_API_KEY') else 'Simulation Mode'}")
    print("=" * 70)

    if not no_browser:
        def open_browser():
            time.sleep(1.2)
            print(f"[main] Opening operator dashboard at {url} in browser...")
            webbrowser.open(url)

        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    # Pass control to dashboard/server.py
    sys.path.insert(0, str(REPO_ROOT / "dashboard"))
    sys.path.insert(0, str(REPO_ROOT / "agent"))
    import server

    # Inject arguments
    server._args = argparse.Namespace(
        scenario=scenario,
        speed=speed,
        host=host,
        port=port,
        loop=True,
    )

    import uvicorn
    try:
        uvicorn.run(server.app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n[main] Dashboard stopped safely.")


def main():
    parser = argparse.ArgumentParser(
        description="Station Crowd Safety Agent — Unified Master Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        choices=["buildup", "live", "normal", "bad_camera", "live_corridor"],
        default="buildup",
        help="Scenario to stream on the dashboard (default: buildup)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Playback speed multiplier (default: 1.0 for live, 10.0 for buildup/mock)",
    )
    parser.add_argument(
        "--video",
        type=str,
        default=None,
        help="Process a raw MP4 video through YOLO11 before opening the dashboard",
    )
    parser.add_argument(
        "--profile",
        choices=["platform", "corridor"],
        default="platform",
        help="Camera zone profile for vision pipeline (default: platform)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Dashboard server port (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Dashboard server bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the default browser tab",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run all verification test scenarios and exit",
    )
    parser.add_argument(
        "--test-llm",
        action="store_true",
        help="Test Gemini 3.8 Flash connection & summary generation and exit",
    )
    parser.add_argument(
        "--test-aws",
        action="store_true",
        help="Test AWS S3 evidence upload & SNS emergency dispatch and exit",
    )

    args = parser.parse_args()

    # Mode 1: Run tests
    if args.test:
        sys.exit(run_tests())

    # Mode 2: Test LLM
    if args.test_llm:
        sys.exit(run_llm_test())

    # Mode 3: Test AWS Cloud Bridge
    if args.test_aws:
        sys.exit(run_aws_test())

    # Mode 3: Process video first if requested
    if args.video:
        ret = run_vision_pipeline(args.video, args.profile)
        if ret != 0:
            print(f"[main] Vision pipeline exited with code {ret}", file=sys.stderr)
            sys.exit(ret)
        args.scenario = "live"

    # Default speed selection
    if args.speed is None:
        args.speed = 1.0 if args.scenario.startswith("live") else 10.0

    # Mode 4: Launch dashboard
    launch_dashboard(
        scenario=args.scenario,
        speed=args.speed,
        port=args.port,
        host=args.host,
        no_browser=args.no_browser,
    )


if __name__ == "__main__":
    main()

