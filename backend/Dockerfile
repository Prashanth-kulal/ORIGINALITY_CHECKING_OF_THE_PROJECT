# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    FLASK_ENV=production \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/cache/sentence_transformers \
    TORCH_HOME=/app/cache/torch

WORKDIR /app
RUN mkdir -p /app/uploads /app/cache/huggingface /app/cache/sentence_transformers /app/cache/torch

# Install minimal system tools needed for runtime & C-extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 1. Install CPU-only PyTorch first (drastically reduces image size from ~3.5GB to ~850MB)
RUN pip install --no-cache-dir 'torch==2.9.1+cpu' --index-url https://download.pytorch.org/whl/cpu

# 2. Copy requirements and install remaining dependencies
COPY requirements.txt .
RUN printf 'torch==2.9.1+cpu\n' > /tmp/torch-constraints.txt && \
    pip install --no-cache-dir -r requirements.txt \
    -c /tmp/torch-constraints.txt

# 3. Pre-cache SentenceTransformer all-MiniLM-L6-v2 model weights into Docker image layer
# Eliminates runtime cold-start download delay (saves 30-60 seconds on boot)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', device='cpu')"

# 4. Copy backend source code
COPY . /app

# 5. Create storage directories for persistent uploads and cache
RUN mkdir -p /app/uploads /app/cache

EXPOSE 8080

# 6. Run with Gunicorn using gthread worker engine binding to 0.0.0.0:$PORT
CMD exec gunicorn --worker-class gthread \
                  --threads 8 \
                  --workers 1 \
                  --timeout 120 \
                  --bind 0.0.0.0:${PORT:-8080} \
                  app:app
