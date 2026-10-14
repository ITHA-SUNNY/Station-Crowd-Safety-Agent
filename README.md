# IBM Z Datathon — Station Crowd Safety Agent

**AI-powered station crowd safety and anomaly detection**

> Project developed for the IBM Z Datathon. The goal is to explore how AI, policy enforcement, auditability, and a monitoring interface can support safer station environments.

## 1. Project Overview

The Station Crowd Safety Agent aims to identify potentially unsafe crowd situations in railway or transit stations by analyzing crowd-related data and detecting unusual patterns.

The system is designed around a modular pipeline that combines data generation, machine learning, policy enforcement, audit logging, and a monitoring application.

The project explores how IBM Z / LinuxONE can support secure, reliable, and auditable AI workloads.

## 2. Problem Statement

Busy stations can experience crowd congestion, unusual movement patterns, and potentially dangerous situations. Detecting these conditions early can help operators investigate risks and make informed decisions.

Traditional monitoring approaches may depend heavily on manual observation or predefined rules. This project explores an AI-assisted approach that identifies anomalous patterns and passes its outputs through a policy layer before recording and presenting relevant events.

## 3. Proposed Solution

The proposed system follows a modular processing pipeline:

1. **Data generation:** Generate or prepare crowd-related input data.
2. **Anomaly detection:** Analyze the input using a machine learning model.
3. **Policy enforcement:** Evaluate model outputs against defined rules and policies.
4. **Audit logging:** Record relevant decisions and events for traceability.
5. **Monitoring application:** Present the processed results through a demo interface.

The implementation and evaluation of each component will determine the system's final capabilities.

## 4. System Architecture

```text
Crowd Data / Generator
          |
          v
    ML Model
          |
          v
   Policy Engine
          |
          v
     Audit Logs
          |
          v
 Monitoring App
```

The integration entry point is planned as `run_demo.py`, which will coordinate the components and support an end-to-end demonstration.

## 5. Repository Structure

```text
IBM/
├── data/        # Input data and data-generation code
├── model/       # Machine learning model and inference code
├── policy/      # Policy rules and enforcement logic
├── audit/       # Audit logging and event records
├── app/         # Monitoring interface and demo application
├── docs/        # Architecture, contracts, and documentation
├── run_demo.py  # End-to-end integration entry point
└── README.md    # Project overview and instructions
```

## 6. Technology and Platform

- **Programming language:** Python for the integration pipeline, where applicable.
- **Machine learning:** Crowd anomaly detection; the final model and dependencies will be documented after integration.
- **Data processing:** Crowd-related input data and generated scenarios.
- **Policy layer:** Rule-based evaluation of model outputs.
- **Audit layer:** Traceable recording of relevant events and decisions.
- **Target platform:** IBM Z / LinuxONE, subject to the final deployment and demonstration environment.

## 7. Setup and Execution

### Prerequisites

- Python 3.10 or another version compatible with the final dependencies.
- Git.
- The dependencies required by the integrated project components.

### Clone the repository

```bash
git clone https://github.com/ITHA-SUNNY/IBM.git
cd IBM
```

### Create a virtual environment

**Windows:**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

Once the project dependency file is available:

```bash
pip install -r requirements.txt
```

### Run the demo

The planned entry point is:

```bash
python run_demo.py
```

**Note:** These are intended setup and execution instructions. The demo can be considered runnable only after `run_demo.py`, the required modules, and the dependency file have been committed and tested.

## 8. Evaluation

The project will be evaluated using relevant measurements from the completed implementation, potentially including:

- Anomaly detection performance.
- Precision, recall, and F1-score, where appropriate.
- End-to-end pipeline functionality.
- Policy enforcement behavior.
- Audit-log completeness and traceability.
- Demo reliability and execution performance.

Final metrics, test evidence, and screenshots will be added after evaluation. No performance figures are claimed in this README.

## 9. Team Collaboration

The repository is organized to allow team members to develop separate components and integrate them into a common pipeline.

| Component | Responsibility |
|---|---|
| Data | Input data and generation |
| Model | Machine learning and inference |
| Policy | Policy rules and enforcement |
| Audit | Event recording and traceability |
| App | Monitoring interface and demo |
| Integration | Pipeline coordination, documentation, presentation, and submission |

Update these responsibilities to match the team's final member assignments.

## 10. IBM Z / LinuxONE Relevance

The project investigates the relevance of IBM Z / LinuxONE to an AI-assisted safety workflow, particularly around secure processing, operational reliability, and auditability.

The final presentation will explain the platform-specific design decisions and distinguish demonstrated capabilities from proposed benefits.

## 11. Project Status

**Status: In development for the datathon.**

The repository and modular integration workflow are being prepared. Individual components, end-to-end testing, platform deployment, and evaluation results will be documented as they become available.

## 12. Disclaimer

This is a prototype project intended for experimentation and demonstration. It is not a certified safety system and must not be relied upon as the sole means of preventing crowd-related incidents.

---

**Event:** IBM Z Datathon  
**Repository:** https://github.com/ITHA-SUNNY/IBM
