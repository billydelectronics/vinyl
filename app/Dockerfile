# ---------- Backend Dockerfile ----------
FROM python:3.11-slim

WORKDIR /app

# System deps:
# - curl for healthcheck
# - lib* runtime libs for Pillow / torch
# - git required for pip install from GitHub
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      git \
      libglib2.0-0 \
      libsm6 \
      libxrender1 \
      libxext6 \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps from your requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Extra deps for cover matching (CLIP + Torch + Pillow)
RUN pip install --no-cache-dir \
      torch \
      torchvision \
      pillow \
      "git+https://github.com/openai/CLIP.git"

# Copy backend source
COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/data

EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]