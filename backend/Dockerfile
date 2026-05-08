FROM python:3.11-slim AS base

# Install system dependencies for GDAL, PostGIS drivers, WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libspatialindex-dev \
    libpq-dev \
    gcc \
    g++ \
    curl \
    # WeasyPrint dependencies
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libffi-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.3
RUN poetry config virtualenvs.create false

# Install dependencies (cached layer)
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --no-interaction

# ─── Development target ───────────────────────────────────────────────────────
FROM base AS dev
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ─── Production target ────────────────────────────────────────────────────────
FROM base AS prod
COPY . .
RUN poetry install --no-dev --no-root --no-interaction
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
