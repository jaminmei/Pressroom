# OCR Engine Dockerfile
FROM python:3.12-slim

USER root

WORKDIR /app

# Install system dependencies for OpenCV (opencv-python)
RUN apt-get update && apt-get install -y \
    curl \
    libxkbcommon0 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    libegl1 \
    libgomp1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.lock requirements.lock

RUN pip install --no-cache-dir --default-timeout=180 --require-hashes -r requirements.lock

# Set the timezone
ENV TZ=Asia/Hong_Kong
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy application files
COPY gunicorn_config.py .
COPY app.py .

# Copy the OCR service src
COPY src/ src/

# Copy OCR models (if available locally)
COPY models/ models/

EXPOSE 8080

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Run with gunicorn using uvicorn workers for async support
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
