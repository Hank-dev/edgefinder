# Edgefinder

Edgefinder is a private opportunity-intelligence service for a Hermes Agent VPS. It collects public signals, preserves evidence and feedback, and exposes a constrained MCP surface for weekly multi-agent research. It never performs outreach or other external actions.

## Local development

Python 3.12 is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
# Set ENVIRONMENT=development and non-default tokens in .env
.venv/bin/alembic upgrade head
.venv/bin/edgefinder serve --host 127.0.0.1 --port 8787
```

Run collection and tests separately:

```bash
.venv/bin/edgefinder collect
.venv/bin/pytest
```

## VPS deployment

Copy `.env.example` to `.env`, set two different random tokens, and update the contact address in `COLLECTION_USER_AGENT`.

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8787/health
```

The Compose port is bound to loopback only. Publish it privately to the tailnet:

```bash
sudo tailscale serve --bg http://127.0.0.1:8787
tailscale serve status
```

Do not add a public reverse proxy or change the Compose bind to `0.0.0.0`.

For Hermes, merge [`hermes/config.example.yaml`](hermes/config.example.yaml) into the active profile and follow [`hermes/CRON.md`](hermes/CRON.md). Hermes officially supports remote HTTP MCP servers with bearer headers and per-tool allowlists.

## Operations

Collection isolates source failures and shows them on the dashboard. NAV collection remains visibly unavailable until a public-feed token is configured. Optional GitHub authentication improves public API rate limits.

Create or inspect a backup:

```bash
docker compose exec -T edgefinder edgefinder backup
docker compose exec -T edgefinder ls -lah /app/backups
```

Restore by stopping the service, preserving the current database, copying a verified backup into the data volume as `edgefinder.db`, and starting the service again. Always test restoration on a temporary volume first.

