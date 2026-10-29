FROM python:3.12-slim

# Install bubblewrap for the namespace-based production sandbox.
# bwrap provides mount/network/PID/IPC isolation without requiring a Docker daemon.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Use bubblewrap namespace sandbox in production on Render.
    # On Render and other cloud container platforms, Docker daemon is not available.
    # bwrap provides genuine OS-level isolation without Docker.
    FIXPROOF_SANDBOX_MODE=bwrap \
    # local execution is disabled; bwrap does not need this flag.
    FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=false

WORKDIR /app

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/pyproject.toml ./pyproject.toml
COPY evals /evals

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
