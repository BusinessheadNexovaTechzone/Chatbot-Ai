# ─────────────────────────────────────────────
# Stage 1: Builder — install dependencies only
# ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /install

# System deps needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (cache-friendly)
COPY requirements.txt .

# Install all packages into a target folder (keeps final image clean)
RUN pip install --upgrade pip && \
    pip install --prefix=/install/packages --no-cache-dir -r requirements.txt

# Install Playwright browser (needed for web scraping)
RUN pip install playwright --no-cache-dir && \
    playwright install chromium --with-deps || true

# ─────────────────────────────────────────────
# Stage 2: Final image
# ─────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install/packages /usr/local

# Copy application source code only (NOT .venv, NOT test files)
COPY app/ ./app/
COPY requirements.txt .

# Download spaCy model (used for query processing)
RUN python -m spacy download en_core_web_sm || true

# Download TextBlob corpora
RUN python -m textblob.download_corpora || true

# Create a non-root user for security
RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose the app port (matches docker-compose.yml)
EXPOSE 8081

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8081/v1/health || exit 1

# Start the FastAPI app with Gunicorn + Uvicorn workers
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8081", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--log-level", "info"]
