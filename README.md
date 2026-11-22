# Cityflo route-lateness MCP server

An MCP server that lets the Ops Lead ask which routes were late, which three were worst, and what the ops log says about them. Decisions and reasoning are in `DECISION.md`; the steering ledger is `decisions.jsonl`.

## Run

Requires Python 3.10+. The `mcp` package must be below version 2 (version 2 renamed `FastMCP` and breaks `server.py`).

```
python3 -m venv .venv
.venv/bin/pip install "mcp<2"
.venv/bin/python server.py        # stdio transport
```

Register it with Claude Code from this folder:

```
claude mcp add cityflo-ops -- "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

## Load data

Datasets are stored per ISO week under `data/{trips,ops_log,schedule_v2}/<period>/`. Sample files are in `demo/`.

1. `load_trips(path, period)`, `load_ops_log(path, period)`, `load_schedule_v2(path, period)` with a period such as `2026-W32`. Missing files for a period get empty placeholders.
2. `use_dataset(period)` activates a period for all three files. `list_datasets` shows row counts and the active period.

## Tools

`worst_three`, `route_lateness`, `late_routes_by_day`, `route_detail`, `trip_detail`, `data_quality`, `manager_report`, plus the loading tools above. All analysis output is tabular. Guardrails for agents are in `guardrails.md` and are served as the server's instructions.
