FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system edgefinder && useradd --system --gid edgefinder --home /app edgefinder

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data /app/backups && chown -R edgefinder:edgefinder /app
USER edgefinder

EXPOSE 8787
CMD ["sh", "-c", "alembic upgrade head && exec edgefinder serve --host 0.0.0.0 --port 8787"]

