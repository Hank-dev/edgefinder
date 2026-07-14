# Edgefinder

Edgefinder is a private opportunity-intelligence service for a Hermes Agent VPS. It collects public signals, preserves evidence and feedback, and exposes a constrained MCP surface for weekly multi-agent research. It never performs outreach or other external actions.

## Local development

Python 3.12 or newer is required.

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

Collection isolates source failures and shows them on the dashboard. NAV collection reads the newest page of [pam-stilling-feed](https://navikt.github.io/pam-stilling-feed/) and stays visibly unavailable until `NAV_API_TOKEN` is set; the experimental public token at <https://pam-stilling-feed.nav.no/api/publicToken> rotates irregularly, so request a private token from NAV for unattended use. The feed only exposes forward pagination (`next_url`/`next_id`) from its oldest page toward the newest; the `?last=true` page returned by the collector has no backward link (no `previous_url`/`prev_id`) back toward older pages, so the collector stays single-page by design. This means NAV coverage of the 7-day window depends on collection running at least daily — running the collector less frequently than that risks missing postings that both appeared and moved off the newest page between runs. Optional GitHub authentication improves public API rate limits.

Procurement is covered in two bands: TED carries Norwegian notices above the EEA thresholds, and the Doffin collector reads Doffin's public search backend for national notices below them (skipping anything marked `sentToTed`) — the contract band a small operator can realistically win. The `funding` kind covers open Horizon Europe and Digital Europe calls from the EU Funding & Tenders portal. Signals from tenders and calls carry `deadline_at`, which flows through batches into published opportunities and the dashboard, so time-limited opportunities are visible before their window closes.

Reddit is deliberately not a core source: it rejects non-browser TLS fingerprints regardless of headers, so a reliable adapter needs Reddit OAuth credentials. Add other community feeds through `EXTRA_FEED_URLS`; feed collection retries once on HTTP 429. Sources removed from the configuration are disabled automatically on the next start instead of lingering red on the dashboard.

Signal batches interleave sources round-robin, so one high-volume feed (company registrations, the Official Journal) cannot crowd out sparse, high-value feeds (job ads, tenders) within a run's signal budget. The `get_signal_trends` MCP tool aggregates the collection window — employers hiring repeatedly, industries registering companies, recurring pain terms, upcoming deadlines — without consuming that budget.

Set `OPERATOR_PROFILE` to a short description of your skills, available hours, and capital. It is handed to the research agents with every run so they rank only opportunities you can actually execute, alongside a per-source track record of your validate/reject feedback.

The database schema is owned by Alembic. Run `alembic upgrade head` after every deploy or checkout before starting the service; the app refuses to start against an empty database instead of creating tables itself.

A crashed weekly research run expires automatically after `MAX_RUN_AGE_HOURS` (default 48), so the next scheduled run can start without manual cleanup.

Create or inspect a backup:

```bash
docker compose exec -T edgefinder edgefinder backup
docker compose exec -T edgefinder ls -lah /app/backups
```

Restore by stopping the service, preserving the current database, copying a verified backup into the data volume as `edgefinder.db`, and starting the service again. Always test restoration on a temporary volume first.

