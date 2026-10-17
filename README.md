# Station Crowd Safety Agent

An early-stage OpenCV-based prototype exploring how computer vision can
help monitor crowd conditions in railway-station environments. The goal
is to turn video measurements into zone-level crowd information,
identify potentially concerning movement patterns, and present
recommendations for human review.

> **Project status:** Working prototype. The vision pipeline, risk agent
> and dashboard run end to end on a recorded video and on mock scenarios.
> Zone areas and the pixel-to-metre speed factor are **estimates, not a
> real calibration**, and nothing has been validated against labelled data.

## Project goals

-   Process recorded crowd video.
-   Detect people and estimate counts within configured zones.
-   Estimate people per square metre when camera perspective and
    real-world zone dimensions have been calibrated.
-   Explore movement/turbulence indicators using optical flow.
-   Produce explainable risk levels and recommended actions for an
    operator to review.
-   Present alerts and supporting evidence through a dashboard.

The system is intended to **support human decision-making**, not to
control railway infrastructure or replace trained safety personnel.

## Current status

### Implemented (prototype)

-   `pipeline/vision_pipeline.py`: YOLO person detection, hand-drawn zone
    polygons, per-zone counts and density, Farneback optical-flow
    turbulence and speed, quality flags, face-blurred evidence frames, and
    `ZoneReading` JSONL output.
-   `agent/risk_agent.py`: rule engine (Normal / Watch / Warning /
    Critical / Can't trust) with density trend, hysteresis, and
    recommendations by zone type. Alerts follow `agent/alert.schema.json`.
-   `dashboard/`: FastAPI server with live stream, alert list, and
    approve/dismiss actions.
-   `crowd-agent-week2-start/`: the shared data contract and mock scenarios.

### Not yet done

-   Real camera/floor calibration (zone `area_m2` values are estimates).
-   Stable person tracking and smoothed counts.
-   `no_frame` / `camera_moved` detection in the pipeline (only the mock
    data exercises the Can't trust path for these).
-   Quantitative evaluation against labelled data.
-   Alert history persistence and cloud deployment.

## Repository

``` text
Station-Crowd-Safety-Agent/
├── pipeline/
│   ├── vision_pipeline.py           # video -> ZoneReading JSONL
│   └── profiles/                    # demo types: video + zone layout
├── agent/
│   ├── risk_agent.py                # ZoneReading -> CrowdAlert
│   ├── run_scenario.py              # runs agent on mock scenarios
│   └── alert.schema.json
├── dashboard/                       # FastAPI server + static UI
├── crowd-agent-week2-start/
│   ├── contract/                    # zone_reading schema + rules
│   └── mock/                        # scenario generator and JSONL files
├── requirements.txt
└── .gitignore
```

## Requirements

-   Windows, Linux, or macOS (commands below use Windows Command
    Prompt).
-   Python compatible with the installed packages.
-   Git.
-   Internet access for initial package installation and model download.

`requirements.txt` lists `opencv-python`, `ultralytics`, `fastapi` and
`uvicorn`. Ultralytics may install additional dependencies, including PyTorch.
Installation time and hardware requirements vary.

## Setup on Windows

### 1. Clone the repository

``` cmd
git clone https://github.com/ITHA-SUNNY/Station-Crowd-Safety-Agent.git
cd Station-Crowd-Safety-Agent
```

### 2. Create and activate a virtual environment

``` cmd
py -m venv .venv
.venv\Scripts\activate
```

If `py` is not available, try `python` instead.

### 3. Install dependencies

``` cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Obtain the YOLO model

The development prototype uses the `yolo11n.pt` model file. If it is not
present locally, one way to obtain it is to install Ultralytics and run:

``` cmd
python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
```

This requires internet access and may download model weights. Check the
model's applicable terms before redistributing the weights. The model
file is excluded from Git by `.gitignore`.

## Running the prototype

Run everything from the repository root.

**1. Vision pipeline.** Pick a demo type with `--profile`. Each profile
bundles a video and a zone layout (`pipeline/profiles/*.json`):

| Profile | Video | Camera | Zones |
|---|---|---|---|
| `platform` (default) | `crowd.mp4` | fixed | FOB stairs, two platform edges, two waiting areas |
| `corridor` | `crowd_new.mp4` (see licence note below) | handheld | far / mid / near footbridge bands |

``` cmd
python pipeline/vision_pipeline.py --profile platform
python pipeline/vision_pipeline.py --profile corridor
```

Output goes to `live_readings.jsonl` (platform) or
`live_readings_<profile>.jsonl`. Use `--video` to override a profile's
video. The `corridor` profile is a rough demo: the camera moves (camera
motion is subtracted from the optical flow) and zone areas are guesses.
To add a demo type, copy a profile JSON, edit the polygons, `zone_type`,
`area_m2` and `video`, and pass its name to `--profile`.

Other options: `--model`, `--out`, `--save-video`, `--no-blur`, `--show`
(press `q` to close the preview).

**2. Risk agent on the mock scenarios** (prints a PASS/FAIL summary):

``` cmd
python agent/run_scenario.py
python agent/risk_agent.py live_readings.jsonl -v
```

**3. Dashboard:**

``` cmd
python dashboard/server.py --scenario buildup --speed 10
```

`--scenario` is one of `live_platform`, `live_corridor` (replay the
pipeline output for that profile), `normal`, `buildup` or `bad_camera`. Then open http://127.0.0.1:8000. The `live_*` scenarios show the annotated
video (zones overlaid, faces blurred) beside the zone cards, kept in sync
with the readings; playback starts when the first browser connects and
runs in real time by default (`--speed` to change) and loops until
stopped (`--no-loop` to play once). Re-run the pipeline
first so the readings and annotated video exist.

If the video does not open, check the path, codec support, and that the
file exists.

## Team workstreams

The project is divided into three workstreams:

1.  **Vision pipeline:** video ingestion, person detection/tracking,
    zone configuration, calibration, per-zone counts, density,
    performance measurements.
2.  **Crowd analytics and risk agent:** optical flow, turbulence
    indicators, density trends, risk rules, reasons, recommendations,
    and scenario evaluation.
3.  **Dashboard and deployment:** backend/API, dashboard, alerts, event
    history, human approval, documentation, and possible cloud
    deployment.

Until the real pipeline is available, the analytics and dashboard
workstreams can use agreed sample JSON/mock data.

## Safety, privacy, and limitations

-   This is a prototype and has not been validated for operational
    railway safety use.
-   Person detectors may miss people in dense crowds, occlusion, poor
    lighting, or distant views.
-   Pixel measurements are not physical density measurements unless
    camera perspective and real-world floor dimensions are calibrated.
-   Risk thresholds and recommendations require testing; they should not
    be treated as validated safety rules.
-   Human review must remain in the loop. The prototype must not
    directly control real gates, trains, or other railway systems.
-   Avoid face recognition and unnecessary identification of
    individuals.
-   Use only video and datasets whose licences permit your intended
    testing, demonstration, and publication.
-   Blur faces in stored evidence where appropriate and permitted.
-   Do not commit API keys, passwords, private footage, or other
    sensitive information.

## Data and model files

Test footage candidate: "Crowd on Railway Station in India" by Footage
Democracy (https://youtu.be/r7-VchoIbG4), licensed Creative Commons
Attribution (CC BY). Credit the creator if you publish results or media.

Large videos and model weights are excluded from Git tracking by
`.gitignore`. Team members should obtain permitted test media separately
and document its source and licence. Do not upload third-party media or
model files to the public repository unless redistribution is allowed.

## Contributing

-   Create a feature branch for your assigned work.
-   Keep changes focused on your workstream.
-   Agree on shared JSON field names before changing the interface.
-   Test your module with sample/mock data.
-   Open a pull request for review before merging into `main`.
-   Do not commit credentials, private data, large generated outputs, or
    unlicensed media.

Suggested branches:

``` text
feature/vision-density
feature/risk-agent
feature/dashboard
```

## Evaluation plan

Planned evaluation measures include:

-   Person-count error against labelled/ground-truth data where
    available.
-   Whether the system gives warning before peak density in test videos.
-   False alarms and missed warnings on test scenarios.
-   Processing time / frames per second on documented hardware.
-   Failure cases caused by occlusion, poor lighting, dense crowds, or
    camera movement.

Results should be reported only after the tests have actually been run.

## Contributors

-   **Member 1:** Vision pipeline lead
-   **Member 2:** Crowd analytics and risk agent
-   **Member 3:** Dashboard, alerts, and deployment

## Licence

No licence is currently specified. Unless a licence is added, others do
not automatically receive broad permission to reuse, modify, or
redistribute the code. Third-party video, dataset, and model terms
remain separate.
