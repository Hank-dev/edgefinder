# Hermes schedules

Keep schedules disabled until seven days of collection and one manual dry-run have been reviewed.

## Before scheduling

1. Add `EDGEFINDER_AGENT_TOKEN=<same value as AGENT_TOKEN>` and `EDGEFINDER_INTERNAL_TOKEN=<same value as INTERNAL_TOKEN>` to `~/.hermes/.env`.
2. Merge `config.example.yaml` into `~/.hermes/config.yaml`, replacing the absolute skill path.
3. Run `hermes mcp test edgefinder` and confirm exactly nine Edgefinder tools are visible.
4. Start or restart the gateway with `hermes gateway install --system` as appropriate for the VPS.

## Jobs to create after the dry-run

Use Hermes chat or `/cron` so the installed version generates the current job schema:

- Daily collection at `05:15 Europe/Oslo`, no-agent mode: make an HTTP POST to `http://127.0.0.1:8787/internal/collect` with `Authorization: Bearer $EDGEFINDER_INTERNAL_TOKEN`. Deliver only failures.
- Daily backup at `03:15 Europe/Oslo`, no-agent mode: run `docker compose exec -T edgefinder edgefinder backup` from the Edgefinder project directory. Retain the command output in the cron history.
- Weekly research at `07:00 every Sunday Europe/Oslo`: attach the `edgefinder-research` skill, use a fresh session, enable web research and the Edgefinder MCP tools, and instruct it to run the complete weekly workflow. Do not attach terminal or filesystem toolsets.

Create the first weekly job paused. Trigger it manually, inspect the unpublished report and cost, then resume it.
