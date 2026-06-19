FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN python -m pip install -U pip setuptools wheel \
    && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=postgresql://odds:odds@db:5432/odds
