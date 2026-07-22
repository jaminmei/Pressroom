# engines/vlm/Dockerfile
FROM python:3.12-slim

USER root

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libxkbcommon0 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    libegl1 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
ADD ./requirements.lock requirements.lock

RUN pip install --no-cache-dir --default-timeout=180 \
    --require-hashes -r requirements.lock

# Set timezone
ENV TZ=Asia/Hong_Kong
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy application files
COPY gunicorn_config.py .
COPY app.py .
COPY src/ src/

EXPOSE 8080

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
