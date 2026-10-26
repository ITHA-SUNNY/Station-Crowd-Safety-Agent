# ==============================================================================
# Station Crowd Safety Agent — Dockerfile for AWS deployment
# Compatible with AWS ECS, AWS App Runner, and AWS EC2 (t3.medium or g4dn.xlarge)
# ==============================================================================

FROM python:3.11-slim

# Install system dependencies for OpenCV and video handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose FastAPI Dashboard port
EXPOSE 8000

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    AWS_REGION=ap-south-1 \
    AWS_S3_BUCKET=station-crowd-safety-evidence

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/info || exit 1

# Launch application
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]

