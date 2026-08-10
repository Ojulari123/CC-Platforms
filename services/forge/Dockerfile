# Build context is the REPO ROOT (see docker-compose.yml), not services/forge,
# because Forge installs the shared crescent-core package from packages/core.
FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Shared package first, in its own layer — it changes rarely. Editable so a
# bind-mount of packages/core in dev is picked up by --reload.
COPY packages/core /packages/core
RUN pip install -e /packages/core

COPY services/forge/requirements.txt .
RUN pip install -r requirements.txt

COPY services/forge/ .

EXPOSE 8000

# Prod-safe default. Dev auto-reload is added by docker-compose.yml's command.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
