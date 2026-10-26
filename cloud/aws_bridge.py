"""
cloud/aws_bridge.py
===================
AWS bridge for the Station Crowd Safety Agent.

Two AWS services are used:
1. Amazon S3 (evidence archive):
   - Uploads the annotated evidence frame attached to a Warning/Critical alert
     (faces are blurred best-effort by the vision pipeline before saving).
   - Each frame is uploaded once. No object-lock or integrity checks are
     configured by this code.
2. Amazon SNS (critical broadcast):
   - Publishes a message to an SNS topic when a Critical alert is raised.
     Who receives it depends on who is subscribed to the topic.
   - The dashboard limits this to one broadcast per zone per 5 minutes. It is
     sent when the Critical alert is raised, not after an approval timeout.

Dual-mode operation:
- Live mode: boto3 calls real AWS when credentials are found in the
  environment (AWS_ACCESS_KEY_ID, AWS_PROFILE, or ECS/App Runner container
  credentials) and the bucket / topic settings are provided. A plain EC2
  instance role is not detected by this check.
- Simulation mode: used otherwise. Nothing is sent to AWS; the bridge builds
  the same objects and logs what it would have done, so demos and tests run
  without an AWS account.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("aws_bridge")

# Check for boto3
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")  # Default: Mumbai (India)
S3_BUCKET = os.environ.get("AWS_S3_BUCKET", "station-crowd-safety-evidence")
SNS_TOPIC_ARN = os.environ.get("AWS_SNS_TOPIC_ARN", "")

# Are live AWS credentials present?
_HAS_CREDENTIALS = bool(
    os.environ.get("AWS_ACCESS_KEY_ID")
    or os.environ.get("AWS_PROFILE")
    or os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
)


def is_live_aws_enabled() -> bool:
    """Return True if real AWS calls can be made."""
    return _BOTO3_AVAILABLE and _HAS_CREDENTIALS


# ---------------------------------------------------------------------------
# 1. Amazon S3 Evidence Storage
# ---------------------------------------------------------------------------

def upload_evidence_to_s3(
    local_frame_path: str,
    zone_id: str,
    alert_id: str = "",
) -> Dict[str, str]:
    """
    Upload a blurred evidence frame to Amazon S3.
    Returns a dict with s3_uri, bucket, and key.
    """
    frame_name = Path(local_frame_path).name
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s3_key = f"evidence/{today}/{zone_id}/{alert_id or 'frame'}_{frame_name}"
    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

    if not is_live_aws_enabled():
        # Simulation mode: returns structured simulated cloud metadata
        return {
            "mode": "simulation",
            "s3_uri": s3_uri,
            "s3_bucket": S3_BUCKET,
            "s3_key": s3_key,
            "status": "simulated",
            "note": "Set AWS_ACCESS_KEY_ID to upload to real S3",
        }

    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        file_path = Path(local_frame_path)
        if not file_path.exists():
            return {"error": f"File not found: {local_frame_path}", "mode": "live"}

        s3_client.upload_file(
            str(file_path),
            S3_BUCKET,
            s3_key,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        return {
            "mode": "live",
            "s3_uri": s3_uri,
            "s3_bucket": S3_BUCKET,
            "s3_key": s3_key,
            "status": "uploaded",
        }
    except Exception as exc:
        return {
            "mode": "live",
            "s3_uri": s3_uri,
            "error": str(exc),
            "status": "failed",
        }


# ---------------------------------------------------------------------------
# 2. Amazon SNS Critical Alert Dispatch
# ---------------------------------------------------------------------------

def dispatch_sns_critical_alert(alert: dict) -> Dict[str, str]:
    """
    Publish an emergency alert notification to Amazon SNS.
    Reaches whoever is subscribed to the SNS topic (for example station staff).
    """
    level = alert.get("level", "WARNING").upper()
    zone_id = alert.get("zone_id", "STATION_ZONE")
    density = alert.get("density_ppm2", 0.0)
    rec = alert.get("recommendation", "Review zone immediately.")
    brief = alert.get("llm_summary", alert.get("reason", ""))

    subject = f"CRITICAL CROWD SAFETY ALERT: {zone_id} [{level}]"
    message_body = (
        f"*** EMERGENCY TRANSIT CROWD SAFETY ALERT ***\n"
        f"Zone: {zone_id}\n"
        f"Level: {level}\n"
        f"Observed Density: {density:.2f} people/m2\n"
        f"Time (UTC): {alert.get('ts', datetime.now(timezone.utc).isoformat())}\n\n"
        f"Action Required:\n{rec}\n\n"
        f"Situation Brief:\n{brief}\n\n"
        f"Dashboard: http://127.0.0.1:8000"
    )

    if not is_live_aws_enabled() or not SNS_TOPIC_ARN:
        # Simulation mode: log emergency dispatch without failing
        print(f"[AWS-SNS:Simulation] Emergency message generated for {zone_id}:", file=sys.stderr)
        print(f"  Subject: {subject}", file=sys.stderr)
        return {
            "mode": "simulation",
            "status": "simulated_sent",
            "topic_arn": SNS_TOPIC_ARN or f"arn:aws:sns:{AWS_REGION}:123456789012:railway-emergency-alerts",
            "subject": subject,
            "message": message_body,
        }

    try:
        sns_client = boto3.client("sns", region_name=AWS_REGION)
        resp = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],  # SNS Subject max 100 chars
            Message=message_body,
        )
        return {
            "mode": "live",
            "status": "published",
            "message_id": resp.get("MessageId", ""),
            "topic_arn": SNS_TOPIC_ARN,
        }
    except Exception as exc:
        return {
            "mode": "live",
            "status": "failed",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# CLI Test Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  AWS CLOUD BRIDGE TEST")
    print(f"  Boto3 Installed  : {_BOTO3_AVAILABLE}")
    print(f"  Live Credentials : {_HAS_CREDENTIALS}")
    print(f"  Target Region    : {AWS_REGION}")
    print(f"  S3 Bucket        : {S3_BUCKET}")
    print("=" * 60)

    # 1. Test S3 Evidence upload
    dummy_frame = Path(__file__).parent.parent / "frame_0.jpg"
    s3_res = upload_evidence_to_s3(
        str(dummy_frame) if dummy_frame.exists() else "frame_0.jpg",
        zone_id="FOB2-STAIRS-DOWN",
        alert_id="test-alert-001",
    )
    print("\n[1] Amazon S3 Evidence Upload:")
    print(json.dumps(s3_res, indent=2))

    # 2. Test SNS Critical Alert Dispatch
    test_alert = {
        "level": "critical",
        "zone_id": "FOB2-STAIRS-DOWN",
        "density_ppm2": 5.4,
        "recommendation": "URGENT: Immediately hold all entry at Gate 1. Deploy staff to stairhead.",
        "llm_summary": "Severe crowd crush risk detected on FOB 2 stairs. Density is surging past safety thresholds.",
    }
    sns_res = dispatch_sns_critical_alert(test_alert)
    print("\n[2] Amazon SNS Emergency Broadcast:")
    print(json.dumps(sns_res, indent=2))
    print("\nTest completed successfully.")

