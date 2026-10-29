FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # In the Render production container, use hardened LocalSandbox with process limits
    FIXPROOF_SANDBOX_MODE=local \
    FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true

WORKDIR /app

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/pyproject.toml ./pyproject.toml
COPY evals /evals

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
