# Layout Detection Engine Dockerfile
FROM python:3.12-slim

USER root

WORKDIR /app

# Install system dependencies for OpenCV and PaddlePaddle
RUN apt-get update && apt-get install -y \
    curl \
    libxkbcommon0 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    libegl1 \
    libgomp1 \
    libgfortran-12-dev \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.lock requirements.lock

RUN pip install --no-cache-dir --default-timeout=300 --require-hashes -r requirements.lock

# Set the timezone
ENV TZ=Asia/Hong_Kong
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Create application model metadata directory.
RUN mkdir -p /app/models

# Copy application files
COPY gunicorn_config.py .
COPY app.py .

# Copy the layout service src
COPY src/ src/

# Copy models configuration
COPY models/ models/

EXPOSE 8080

# Create a non-root user and a writable cache for PaddleOCR's fixed vendor models.
RUN useradd -m appuser \
    && mkdir -p /home/appuser/.paddleocr \
    && chown -R appuser:appuser /home/appuser/.paddleocr /app
USER appuser

# Run with gunicorn using uvicorn workers for async support
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
