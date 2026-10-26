# Evaluation

This is a small, honest evaluation of a prototype. It measures how the risk agent behaves on the contract scenarios and how fast the vision pipeline runs, and it records a manual spot check of the detector. It does **not** measure detection accuracy against labelled ground truth, false-alarm rates on real footage, or lead time on real incidents. Those were not done.

Reproduce the numbers below with `python tools/evaluate.py` (raw output: [`evaluation_results.json`](evaluation_results.json)).

## Setup

| Item | Value |
|---|---|
| OS | Windows 11 |
| CPU | Intel laptop CPU (Family 6 Model 186, 12 threads), **no GPU** |
| Python / OpenCV / Ultralytics / PyTorch | 3.14.7 / 5.0.0 / 8.4.180 / 2.14.1 (CPU build) |
| Detector | YOLO11n (`yolo11n.pt`), `imgsz=1280`, `conf=0.10`, run every 10th frame |
| Date | 2026-10-26 |

## 1. Risk agent on the contract scenarios

Scripted readings from `crowd-agent-week2-start/mock/`, run through `agent/risk_agent.py`. Times are from the start of each scenario. These are simulated inputs, so this tests the rule logic, not real-world detection.

| Scenario | Readings | Result |
|---|---|---|
| `normal` (10 min, 4 zones) | 2400 | **0 alerts**, as expected |
| `buildup` (FOB2 stairs 1.5 to 5.5 people/m²) | 3600 | FOB2-STAIRS-DOWN: Watch at 3:46, Warning at 7:45, Critical at 9:49. The contract expects Warning around minutes 7 to 9. |
| `bad_camera` (PF3 camera dark from minute 4) | 2400 | PF3-EDGE: Can't trust at 4:00, never reported as normal afterwards |

Also in `buildup`, GATE1-ENTRY and FOB2-DECK each raised one short Watch alert (about 4 to 11 seconds, then back to Normal). Those are brief threshold crossings in the scripted data and could count as minor false Watch alerts.

## 2. Vision-pipeline throughput

Measured on an otherwise idle machine, CPU only, on the bundled demo videos.

| Profile | Frames | Time | Throughput |
|---|---|---|---|
| `platform` (50 fps source, 5 zones) | 622 | 307 s | **2.0 fps** |
| `corridor` (30 fps source, 3 zones) | 736 | 367 s | **2.0 fps** |

An earlier, separate run of the corridor profile on the same laptop took 132 s (about 5.6 fps), so expect roughly **2 to 6 fps** on this hardware, with large run-to-run variation. This is **well below real time**. The pipeline is an offline, batch process here. The dashboard's "real time" playback replays readings that were computed ahead of time. Real-time operation would need a GPU or a lighter detection schedule; this was not tested.

## 3. Detection spot check (manual, not ground truth)

One frame from each demo video was inspected by eye against the detector's boxes. The exact number of people in each frame was not hand-counted, so no accuracy figure is claimed.

| Video | Detector count | Observation |
|---|---|---|
| `crowd.mp4` (platform, frame 120) | 65 | Clear **undercount**. The dense crowd far away on the left platform is mostly undetected, so the true count is far higher than 65. |
| `crowd_new.mp4` (corridor, frame 150) | 30 | Roughly consistent with the people visible, with a few duplicate boxes on overlapping people and some distant people missed. |

Consequence: in dense or distant scenes the measured density is a **lower bound**, and the live demos stay Normal partly for this reason. This is the main limitation of the current pipeline.

## Not evaluated

- Person-count error against labelled ground truth.
- False alarms and missed warnings on real footage (the only scenarios used are scripted).
- Warning lead time on real incidents.
- GPU throughput, camera-movement and low-light robustness, and the live Gemini and AWS paths.
- The 35 px/m speed factor and the zone areas are estimates and were not calibrated.
