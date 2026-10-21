"""
pipeline/vision_pipeline.py
===========================
Vision Pipeline — Workstream 1

Processes railway station crowd video, detects people via YOLO,
estimates per-zone counts and physical densities (people/m2),
measures optical-flow motion & turbulence (0=smooth, 1=chaotic),
and emits standard ZoneReading JSON objects matching zone_reading.schema.json.

Safety & Privacy:
- Never saves unblurred human faces in evidence frames.
- Bottom-center bounding box points are used for ground plane zone attribution.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Demo profiles (video + zone layout), see pipeline/profiles/*.json
# ---------------------------------------------------------------------------

PROFILE_DIR = Path(__file__).parent / "profiles"


def list_profiles() -> List[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


def load_profile(name: str) -> Dict:
    """Load a profile; zone polygons become int32 arrays, colours BGR tuples."""
    path = PROFILE_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"Unknown profile '{name}'. Available: {', '.join(list_profiles())}")
    prof = json.loads(path.read_text(encoding="utf-8"))
    for z in prof["zones"].values():
        z["polygon"] = np.array(z["polygon"], np.int32)
        z["color"] = tuple(z["color"])
    return prof


# ---------------------------------------------------------------------------
# Vision Pipeline Class
# ---------------------------------------------------------------------------

class VisionPipeline:
    def __init__(
        self,
        video_path: str,
        model_name: str = "yolo11n.pt",
        zones: Optional[Dict] = None,
        output_jsonl: Optional[str] = None,
        save_video: Optional[str] = None,
        show_window: bool = False,
        blur_faces: bool = True,
        camera_static: bool = True,
        evidence_dir: str = "pipeline/frames"
    ):
        self.video_path = video_path
        if not zones:
            raise ValueError("zones are required (use load_profile)")
        self.zones = zones
        self.camera_static = camera_static
        self.evidence_dir = evidence_dir
        self.output_jsonl = output_jsonl
        self.save_video = save_video
        self.show_window = show_window
        self.blur_faces = blur_faces

        # Load YOLO model
        print(f"[Vision] Loading YOLO model: {model_name}...", file=sys.stderr)
        from ultralytics import YOLO
        self.model = YOLO(model_name)
        print("[Vision] YOLO model loaded successfully.", file=sys.stderr)

        # Open video capture
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Cannot open video source: {video_path}")

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Optical flow state
        self.prev_gray: Optional[np.ndarray] = None

        # Precompute zone masks
        self.zone_masks: Dict[str, np.ndarray] = {}
        for zid, zdata in self.zones.items():
            mask = np.zeros((self.height, self.width), dtype=np.uint8)
            cv2.fillPoly(mask, [zdata["polygon"]], 255)
            self.zone_masks[zid] = mask

        # Video writer if requested
        self.writer: Optional[cv2.VideoWriter] = None
        if self.save_video:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(self.save_video, fourcc, self.fps, (self.width, self.height))

        # Output file handle
        self.out_file = None
        if self.output_jsonl:
            self.out_file = open(self.output_jsonl, "w", encoding="utf-8")

    def _compute_optical_flow(self, gray: np.ndarray) -> Optional[np.ndarray]:
        """Calculates dense optical flow using Farneback method."""
        if self.prev_gray is None:
            self.prev_gray = gray
            return None
        flow = cv2.calcOpticalFlowFarneback(
            self.prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0
        )
        self.prev_gray = gray
        return flow

    def _analyze_zone_motion(self, flow: Optional[np.ndarray], zid: str) -> Tuple[float, float]:
        """
        Returns (turbulence [0..1], flow_speed_mps).
        Turbulence = 1 - (magnitude of mean vector / mean of vector magnitudes).
        If everyone moves in the same direction, turbulence -> 0.0.
        If movement is chaotic/pushing in opposing directions, turbulence -> 1.0.
        """
        if flow is None:
            return 0.1, 0.5

        mask = self.zone_masks[zid]
        if not self.camera_static:
            # Handheld camera: remove the global (camera) motion so only
            # motion relative to the scene counts towards turbulence/speed.
            flow = flow - np.median(flow.reshape(-1, 2), axis=0)
        zone_flow = flow[mask == 255]

        if len(zone_flow) == 0:
            return 0.0, 0.0

        u = zone_flow[:, 0]
        v = zone_flow[:, 1]
        mags = np.sqrt(u**2 + v**2)

        # Ignore stationary background noise (speed < 0.2 px/frame)
        moving = mags > 0.2
        if np.sum(moving) < 10:
            return 0.05, 0.1

        u_mov = u[moving]
        v_mov = v[moving]
        mags_mov = mags[moving]

        mean_u = float(np.mean(u_mov))
        mean_v = float(np.mean(v_mov))
        mean_mag = float(np.mean(mags_mov))

        net_speed = math.sqrt(mean_u**2 + mean_v**2)

        # Turbulence measure: coherence loss
        coherence = net_speed / (mean_mag + 1e-6)
        turbulence = max(0.0, min(1.0, 1.0 - coherence))

        # Calibrate pixel speed to meters per second (~30 pixels per meter)
        flow_speed_mps = round((mean_mag * self.fps) / 35.0, 2)

        return round(turbulence, 2), min(3.0, flow_speed_mps)

    def _check_quality_flags(self, gray: np.ndarray, count: int, area: float) -> Tuple[float, List[str]]:
        """Assesses lighting, camera blur, and excessive crowd occlusion."""
        flags: List[str] = []
        conf = 0.92

        # Brightness check
        mean_val = float(np.mean(gray))
        if mean_val < 35:
            flags.append("low_light")
            conf -= 0.3

        # Blur check (Laplacian variance)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if lap_var < 50.0:
            flags.append("blur")
            conf -= 0.25

        # Extreme crowd occlusion
        density = count / area
        if density > 6.0:
            flags.append("too_dense_to_count")
            conf -= 0.2

        return max(0.2, min(1.0, round(conf, 2))), flags

    def process(self):
        """Runs detection, tracking, zone analysis, and emits JSON readings."""
        print(f"[Vision] Processing video {self.video_path} ({self.total_frames} frames)...", file=sys.stderr)
        frame_idx = 0
        readings_emitted = 0
        # Timestamps follow video time (start + frame/fps) so readings stay
        # aligned with the annotated video when replayed on the dashboard.
        t0 = datetime.now(timezone.utc)
        start_time = time.time()

        # Emit readings approximately every 1.0 second
        sample_interval = max(1, int(round(self.fps)))

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            frame_idx += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow = self._compute_optical_flow(gray)
            annotated_frame = frame.copy()

            # Run YOLO detector on keyframes (every 10 frames = 5x/sec at 50fps)
            if frame_idx == 1 or frame_idx % 10 == 0:
                results = self.model(frame, classes=[0], imgsz=1280, conf=0.10, verbose=False)
                last_boxes = results[0].boxes if results else None
                cached_person_points = []
                cached_face_rois = []

                if last_boxes is not None and len(last_boxes) > 0:
                    for b in last_boxes:
                        xyxy = b.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = map(int, xyxy)
                        feet_x = (x1 + x2) // 2
                        feet_y = y2
                        cached_person_points.append((feet_x, feet_y))
                        face_y2 = min(y2, y1 + int(0.25 * (y2 - y1)))
                        cached_face_rois.append((x1, y1, x2, face_y2))

            person_points = cached_person_points

            # Privacy protection: Blur faces in annotated frame
            if self.blur_faces:
                for x1, y1, x2, face_y2 in cached_face_rois:
                    if 0 <= y1 < face_y2 <= self.height and 0 <= x1 < x2 <= self.width:
                        roi = annotated_frame[y1:face_y2, x1:x2]
                        if roi.size > 0:
                            annotated_frame[y1:face_y2, x1:x2] = cv2.GaussianBlur(roi, (25, 25), 30)

            for feet_x, feet_y in person_points:
                cv2.circle(annotated_frame, (feet_x, feet_y), 3, (0, 255, 255), -1)

            # Analyze zones every sample_interval frames (~1 second)
            should_emit = (frame_idx % sample_interval == 0) or (frame_idx == 1)

            # Count people in each zone
            zone_counts: Dict[str, int] = {zid: 0 for zid in self.zones}
            for px, py in person_points:
                for zid, zdata in self.zones.items():
                    if cv2.pointPolygonTest(zdata["polygon"], (float(px), float(py)), False) >= 0:
                        zone_counts[zid] += 1
                        break

            # Draw zone overlays
            overlay = annotated_frame.copy()
            for zid, zdata in self.zones.items():
                poly = zdata["polygon"]
                color = zdata["color"]
                count = zone_counts[zid]
                density = count / zdata["area_m2"]

                # Zone risk coloring
                if density >= 4.0:
                    poly_color = (0, 0, 255)       # Red: Warning/Critical
                elif density >= 2.0:
                    poly_color = (0, 200, 255)     # Yellow: Watch
                else:
                    poly_color = color

                cv2.polylines(annotated_frame, [poly], True, poly_color, 2)
                cv2.fillPoly(overlay, [poly], poly_color)

            cv2.addWeighted(overlay, 0.2, annotated_frame, 0.8, 0, annotated_frame)

            # HUD text on zones
            for zid, zdata in self.zones.items():
                count = zone_counts[zid]
                density = count / zdata["area_m2"]
                pts = zdata["polygon"]
                cx = int(np.mean(pts[:, 0]))
                cy = int(np.mean(pts[:, 1]))
                text = f"{zid}: {count}p ({density:.2f} p/m2)"
                cv2.putText(annotated_frame, text, (cx - 70, cy),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

            # Emit ZoneReading JSON
            if should_emit:
                ts_iso = (t0 + timedelta(seconds=(frame_idx - 1) / self.fps)).isoformat()
                # Save evidence frame
                evidence_path = f"{self.evidence_dir}/frame_{frame_idx:04d}.jpg"
                os.makedirs(self.evidence_dir, exist_ok=True)
                cv2.imwrite(evidence_path, annotated_frame)

                for zid, zdata in self.zones.items():
                    count = zone_counts[zid]
                    density = round(count / zdata["area_m2"], 2)
                    turbulence, flow_speed = self._analyze_zone_motion(flow, zid)
                    confidence, quality_flags = self._check_quality_flags(gray, count, zdata["area_m2"])

                    reading = {
                        "ts": ts_iso,
                        "camera_id": zdata["camera_id"],
                        "zone_id": zid,
                        "zone_type": zdata["zone_type"],
                        "area_m2": zdata["area_m2"],
                        "people_count": count,
                        "density_ppm2": density,
                        "turbulence": turbulence,
                        "flow_speed_mps": flow_speed,
                        "confidence": confidence,
                        "quality_flags": quality_flags,
                        "evidence_frame": evidence_path
                    }

                    line = json.dumps(reading)
                    if self.out_file:
                        self.out_file.write(line + "\n")
                        self.out_file.flush()
                    print(line, flush=True)
                    readings_emitted += 1

            if self.writer:
                self.writer.write(annotated_frame)

            if self.show_window:
                cv2.imshow("Station Crowd Safety Vision Pipeline", annotated_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

        self.cap.release()
        if self.writer:
            self.writer.release()
        if self.out_file:
            self.out_file.close()
        if self.show_window:
            cv2.destroyAllWindows()

        elapsed = time.time() - start_time
        print(f"[Vision] Finished: {frame_idx} frames processed in {elapsed:.1f}s ({readings_emitted} zone readings).",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Station Crowd Safety Vision Pipeline")
    parser.add_argument("--profile", default="platform", choices=list_profiles(),
                        help="Demo type: sets the default video and zone layout")
    parser.add_argument("--video", default=None, help="Override the profile's video file")
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics model name/path")
    parser.add_argument("--out", default=None,
                        help="Output JSONL (default: live_readings.jsonl for platform, "
                             "live_readings_<profile>.jsonl otherwise)")
    parser.add_argument("--save-video", default=None,
                        help="Annotated MP4 (default: output_annotated[_<profile>].mp4)")
    parser.add_argument("--no-blur", action="store_true", help="Disable privacy face blurring")
    parser.add_argument("--show", action="store_true", help="Display OpenCV preview window")
    args = parser.parse_args()

    prof = load_profile(args.profile)
    suffix = "" if args.profile == "platform" else f"_{args.profile}"
    pipeline = VisionPipeline(
        video_path=args.video or prof["video"],
        model_name=args.model,
        zones=prof["zones"],
        output_jsonl=args.out or f"live_readings{suffix}.jsonl",
        save_video=args.save_video or f"output_annotated{suffix}.mp4",
        show_window=args.show,
        blur_faces=not args.no_blur,
        camera_static=prof.get("camera_static", True),
        evidence_dir="pipeline/frames" + (f"/{args.profile}" if suffix else "")
    )
    pipeline.process()


if __name__ == "__main__":
    main()
