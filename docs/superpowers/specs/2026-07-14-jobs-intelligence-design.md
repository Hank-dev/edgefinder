# Jobs Intelligence — Design

Date: 2026-07-14
Status: approved by operator, pending spec review

## Goal

Turn the Talent Radar from a generic keyword-count page into a hunt-first job
intelligence surface for an Indøk + data profile: a relevance-ranked job feed
as the main view, with condensed skills-demand intelligence as support. All
seniority levels are collected and shown; internships, graduate roles, and
part-time student roles rank higher via the operator profile.

## Decisions made during brainstorming

- **Primary use:** job hunt first, market intelligence second.
- **Job types:** collect everything (internship, graduate, part-time, senior);
  seniority is a scoring dimension, never a hard filter.
- **New sources:** fix NAV paging (operator requests token), add Online and
  Abakus linjeforening APIs, add kode24, add Finn.no gated on a
  robots.txt/ToS check at implementation time.
- **Skills intelligence:** grouped taxonomy with canonical skills and merged
  synonyms. Required-vs-wanted parsing, trend-over-time, and co-occurrence are
  explicitly out of scope this round.
- **Relevance:** hybrid — deterministic profile scoring computed live, plus a
  weekly agent-picked shortlist with reasoning.
- **Structure:** new `src/edgefinder/jobs/` package; the talent route in
  `main.py` shrinks to a thin router.
- **Extra features:** cross-board dedupe, application tracker, deadline board,
  Telegram digest.

## Architecture

```
src/edgefinder/
  jobs/
    __init__.py
    taxonomy.py    # skill clusters + synonyms (data) + compiled matchers
    relevance.py   # profile loading, seniority classifier, 0-100 scoring
    service.py     # query + dedupe + rank + aggregate (no HTTP, no Jinja)
    routes.py      # APIRouter: /talent pages + tracker POSTs
  collectors/
    adapters.py    # + OnlineCollector, AbakusCollector, Kode24Collector,
                   #   FinnCollector; NavJobsCollector pages backward
  mcp_server.py    # + save_job_picks tool
  cli.py           # + `edgefinder digest` command
  main.py          # mounts jobs router; talent logic removed (-155 lines)
```

`main.py` keeps route registration only. `service.py` is pure
(session in, view models out) so scoring/dedupe/aggregation are unit-testable
without HTTP or templates.

## Sources & collection

All new sources register in `CORE_SOURCES` with `kind: "jobs"` so they flow
into the existing round-robin batching, dashboard health view, and talent
queries automatically.

| Source | Access | Notes |
| --- | --- | --- |
| NAV pam-stilling-feed | token (operator requests) | Walk feed pages backward from newest until the 7-day cutoff, capped at 10 pages/run. Stays visibly unavailable until `NAV_API_TOKEN` is set. |
| Online (NTNU informatics) | public JSON API | Career-opportunity endpoint; adapter shaped like Bindeleddet; carries real deadlines. |
| Abakus (NTNU data/komtek) | public JSON API | Joblistings endpoint; same shape; carries real deadlines. |
| kode24 | public board | Norwegian dev-job board; JSON if available, HTML otherwise. |
| Finn.no | **gated** | Implemented only if robots.txt permits automated access to job search/listing pages. Isolated collector, one request page per run, lowest quality weight (0.6). If disallowed, skip and document in README. |

Exact endpoint URLs and response shapes for Online, Abakus, and kode24 are
verified live during implementation; any endpoint that turns out dead or
non-public is skipped and documented in the README, never faked or stubbed.

Every collector extracts `deadline_at` where the source provides it
(søknadsfrist / expires fields) and sets `employer`, `municipality`,
`source_board`, and `status` metadata keys, matching the conventions the
existing job collectors use.

## Data model (one Alembic migration, 0003)

1. **`signals.fingerprint`** — nullable string, indexed. Computed at insert
   time by collectors' shared code path for job signals:
   `sha256(normalize(employer) + "|" + normalize(title))[:16]` where
   `normalize` lowercases, strips punctuation, collapses whitespace, and
   removes common suffixes (AS, ASA, "100% stilling", parenthesised location).
   Non-job signals leave it NULL. Backfill for existing job signals runs in
   the migration.
2. **`job_status`** — `id`, `fingerprint` (indexed, unique), `status` enum
   (`interested` / `applied` / `dismissed`), `note` (nullable text),
   `created_at`, `updated_at`. Keyed on fingerprint rather than signal id so a
   dismissal covers every board carrying the same job.
3. **`job_pick`** — `id`, `run_id` FK, `signal_id` FK, `reasoning` (text),
   `created_at`. Written by the new MCP tool, read by the talent page.

## Dedupe

`service.py` groups active job signals by fingerprint. The primary row is the
signal whose source has the highest quality weight; other boards appear as
"also on …" chips. Aggregations (employer counts, skill counts, totals) count
each fingerprint once, using the primary signal's text. Signals without a
fingerprint (legacy rows the backfill could not attribute an employer to)
pass through undeduped.

## Taxonomy (`taxonomy.py`)

Data-only structure: `TAXONOMY: dict[cluster, dict[canonical_skill,
list[synonym]]]` with six clusters — Programming, Data & ML, Cloud & Infra,
Finance & Econ, Business & Methods, Languages. Synonyms cover
English/Norwegian variants (machine learning / maskinlæring / ML). Matching
compiles one word-boundary regex per canonical skill at import; this replaces
the current substring hacks (`" ai "`, `"go "`) and the duplicated `"excel"`
entry. The talent page's category tabs become these six clusters, replacing
the software/finance/economics trio. The skills panel shows clusters with
their top canonical skills and deduped counts; clicking a skill filters the
feed as today.

## Relevance (`relevance.py`)

Deterministic 0–100 score with a stored breakdown:

| Component | Weight | Signal |
| --- | --- | --- |
| Role match | 40 | profile `target_roles` phrases found in title (weighted double) or excerpt |
| Skill overlap | 30 | fraction of taxonomy skills in the ad that appear in profile `skills_have` (with partial credit for `skills_learning`) |
| Location | 15 | profile `locations` weight for the job's municipality; `remote` weight applies when the ad signals remote/hybrid; unknown municipality scores the profile's `default_location_weight` |
| Seniority fit | 15 | classifier bucket × profile `seniority` weight |

Seniority classifier: keyword rules over title + excerpt →
`internship` (sommerjobb, internship, praktikant), `graduate` (nyutdannet,
graduate, trainee), `junior`, `senior` (senior, lead, principal, leder,
direktør), else `unspecified`. `unspecified` uses the profile's
`unspecified_seniority_weight` (default 0.7) so unclassified ads are neither
buried nor boosted.

Profile lives in `profile.yaml` at a path from `JOBS_PROFILE_PATH` (default
`./profile.yaml`, gitignored; `profile.example.yaml` is committed):

```yaml
skills_have: [python, sql, excel, power bi]
skills_learning: [dbt, azure]
target_roles: [data engineer, analyst, business intelligence, konsulent]
locations: {Trondheim: 1.0, Oslo: 0.8, remote: 0.9}
default_location_weight: 0.5
seniority: {internship: 1.0, graduate: 1.0, junior: 0.9, senior: 0.3}
unspecified_seniority_weight: 0.7
```

Missing file → scoring degrades gracefully: every job scores 50 and the page
shows a "no profile configured" hint. Malformed file → startup fails loudly
(consistent with `assert_safe_production_config`).

## Web surface (`routes.py` + templates)

`/talent` becomes hunt-first:

- **Main column — ranked feed.** Per row: title, employer, municipality,
  source chip + dedupe chips, days-left badge when `deadline_at` is set,
  relevance score with breakdown on hover (title attribute — no JS), and
  three form buttons: Interested / Applied / Dismiss (POST
  `/talent/status/{fingerprint}`, CSRF-checked like opportunity feedback,
  303 back to the current filter view; posting again upserts, so
  Interested → Applied is one click). Dismissed fingerprints are excluded
  from feed and aggregates.
- **Tabs.** All / six taxonomy clusters / Deadlines / Applied.
  - *Deadlines:* jobs with `deadline_at`, soonest first, days-left badges,
    relevance shown.
  - *Applied:* fingerprints with status `interested` or `applied`, grouped by
    status — the lightweight pipeline view.
- **Agent picks strip.** Above the feed: latest published run's `job_pick`
  rows (title, employer, one-line reasoning, link). Empty state hides the
  strip.
- **Sidebar.** Taxonomy clusters with top skills, top employers, top
  locations — all deduped counts, all clickable filters.
- The NOK 299/month alerts CTA is removed (the Telegram digest replaces it
  for the operator; a paid product is out of scope).

## MCP + Hermes

- New tool `save_job_picks(run_id, picks: list[{signal_id, reasoning}])` —
  validates the run is active and signal ids exist, replaces any previous
  picks for that run (idempotent re-runs), max 5 picks.
- `hermes/skills/edgefinder-research/SKILL.md` gains a step: from the week's
  job-kind signals, choose up to 5 best fits for `OPERATOR_PROFILE` and call
  `save_job_picks` with one-line reasoning each. The tool joins the existing
  per-run allowlist in `hermes/config.example.yaml`.

## Telegram digest

`edgefinder digest --hours 24` (CLI, cron-scheduled like `edgefinder collect`
per `hermes/CRON.md`):

- Selects job signals first observed in the window with relevance ≥
  `DIGEST_MIN_RELEVANCE` (default 60), deduped by fingerprint, dismissed
  excluded, sorted by relevance, capped at 15.
- Sends one message via Telegram Bot API `sendMessage`
  (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`) using plain httpx —
  no python-telegram-bot dependency, no inbound webhook.
- Missing config or an empty selection → exit 0 silently (cron-safe).
  Telegram API failure → non-zero exit with the error on stderr.
- Note the interaction with the profile: with no `profile.yaml`, every job
  scores 50, which sits below the default threshold of 60 — the digest then
  sends nothing by design. The command logs a one-line warning in that case
  so an unconfigured profile is diagnosable, not silent.
- README's "never performs outreach or other external actions" is amended to:
  no external actions except opt-in push notifications to the operator's own
  Telegram chat.

## Error handling

- Collector failures stay isolated per source (existing behavior); new
  collectors raise on structural surprises (missing keys) rather than
  emitting garbage rows.
- Fingerprinting never throws: unparseable employer/title yields NULL
  fingerprint, and the row passes through undeduped.
- Tracker POSTs validate fingerprint existence and status enum; unknown
  fingerprint → 404, bad CSRF → 403 (existing pattern).

## Testing

- **Unit:** taxonomy matching (synonym merge, word boundaries, Norwegian
  characters), seniority classifier, relevance scoring (each component +
  missing-profile fallback), fingerprint normalization, dedupe grouping.
- **Adapters:** fixture-based tests per new collector, matching
  `tests/test_adapters.py` conventions (recorded JSON/HTML, no live HTTP).
- **Routes:** talent feed renders with dedupe chips and score; tab filters;
  tracker POST happy path + 403/404; dismissed jobs excluded.
- **MCP:** `save_job_picks` validation + idempotent replace.
- **Digest:** selection logic + message formatting with mocked Telegram API;
  silent-exit paths.

## Out of scope (this round)

- Required-vs-wanted skill parsing, skill trends over time, co-occurrence.
- Paid alerts product / multi-user anything.
- LinkedIn, Karrierestart, or other sources beyond the table above.
- Inbound Telegram interactions.

## Implementation phases

1. **Foundations:** migration 0003, fingerprinting, jobs package skeleton,
   taxonomy, relevance + profile loading, service layer, unit tests.
2. **Sources:** NAV paging, Online, Abakus, kode24, Finn (gated), adapter
   tests, README source docs.
3. **Surface:** talent page rebuild (feed, tabs, sidebar, tracker), route
   tests.
4. **Hybrid + push:** `save_job_picks` MCP tool, Hermes skill/config update,
   agent-picks strip, Telegram digest CLI + cron docs.
