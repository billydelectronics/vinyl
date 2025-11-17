# ---------- Backend Dockerfile (vinyl/main/app/Dockerfile) ----------
FROM python:3.11-slim

# App lives here in the image
WORKDIR /app

# Curl is used by the container healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps (requirements.txt is next to main.py)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend source (main.py, db.py, discogs.py, static/, etc.)
COPY . .

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Ensure a place for the DB if you're using VINYL_DB=/app/data/records.db
RUN mkdir -p /app/data

# Uvicorn will listen on 80 inside the container
EXPOSE 80

# Start FastAPI (main.py defines `app = FastAPI(...)`)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]