# Station Crowd Safety Agent

An early-stage OpenCV-based prototype exploring how computer vision can
help monitor crowd conditions in railway-station environments. The goal
is to turn video measurements into zone-level crowd information,
identify potentially concerning movement patterns, and present
recommendations for human review.

> **Project status:** In development. Basic video playback and
> YOLO-based person detection have been tested. Zone calibration,
> validated density measurement, turbulence analysis, risk rules,
> dashboard, and deployment should be treated as planned work until
> implemented and tested.

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

### Tested

-   Python/OpenCV environment setup.
-   Reading and playing a recorded video with OpenCV.
-   Basic person detection using Ultralytics YOLO.

### Planned / not yet confirmed complete

-   Zone polygons and camera/floor calibration.
-   Stable person tracking and smoothed zone counts.
-   Density calculation using calibrated physical area.
-   Optical-flow-based turbulence measurements.
-   Risk scoring, recommendations, and confidence checks.
-   Human approval interface, alert history, dashboard, and cloud
    deployment.
-   Quantitative evaluation against labelled data.

## Repository

``` text
Station-Crowd-Safety-Agent/
├── main.py
├── requirements.txt
├── .gitignore
└── README.md
```

The layout may expand as the vision, analytics, dashboard, and
deployment modules are added.

## Requirements

-   Windows, Linux, or macOS (commands below use Windows Command
    Prompt).
-   Python compatible with the installed packages.
-   Git.
-   Internet access for initial package installation and model download.

The current `requirements.txt` lists `opencv-python` and `ultralytics`.
Ultralytics may install additional dependencies, including PyTorch.
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
file is intentionally excluded from Git by `.gitignore`.

## Running the prototype

The exact command and options depend on the current contents of
`main.py`. From the project directory, first inspect the file or follow
the latest instructions added by the maintainers. If `main.py` is
configured to read `crowd.webm`, place a suitable, locally available
video at that path or update the video path in the code.

Example command:

``` cmd
python main.py
```

If the video does not open, check the video path, codec support, and
whether the file exists. Press the key specified by the script to close
the OpenCV window; the current key binding depends on the
implementation.

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
