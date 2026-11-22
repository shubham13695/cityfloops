"""Cityflo ops MCP server. Run: .venv/bin/python server.py  (stdio transport)."""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import analytics
import store

GUARDRAILS = (Path(__file__).parent / "guardrails.md").read_text()
mcp = FastMCP("cityflo-ops", instructions=GUARDRAILS)


@mcp.tool()
def load_trips(path: str, period: str) -> dict:
    """Validate a trips CSV and store it under data/trips/<period>/trips.csv.
    period is an ISO week such as 2026-W32. Missing ops_log / schedule_v2 files for the
    period get empty placeholders. Does not change the active dataset."""
    return store.load("trips", path, period)


@mcp.tool()
def load_ops_log(path: str, period: str) -> dict:
    """Store an ops log text file under data/ops_log/<period>/ops_log.txt (period like 2026-W32)."""
    return store.load("ops_log", path, period)


@mcp.tool()
def load_schedule_v2(path: str, period: str) -> dict:
    """Validate and store a revised-timetable CSV under data/schedule_v2/<period>/schedule_v2.csv."""
    return store.load("schedule_v2", path, period)


@mcp.tool()
def list_datasets() -> str:
    """List every loaded period as a table with row counts per file (0 if empty or missing)
    and a marker on the active period."""
    info = store.list_datasets()
    lines = ["| Period | Active | Trips | Ops log | Schedule v2 |",
             "|---|---|---|---|---|"]
    for d in info["datasets"]:
        lines.append(f"| {d['period']} | {'✔ active' if d['active'] else ''} | "
                     f"{d['trips']} | {d['ops_log']} | {d['schedule_v2']} |")
    if not info["datasets"]:
        lines.append("| (none loaded) |  | 0 | 0 | 0 |")
    return "\n".join(lines)


@mcp.tool()
def use_dataset(period: str) -> dict:
    """Make a period (e.g. 2026-W32) the active dataset. Switches trips, ops log and
    schedule together. Missing files get placeholders; the trips file is validated first."""
    return store.use_dataset(period)


@mcp.tool()
def late_routes_by_day(date: str | None = None, threshold_min: float = 5.0, rec114: str = "listed") -> str:
    """Routes that were late on each day of the active dataset (or one day, date=YYYY-MM-DD).
    A route is late on a day if its median lateness >= threshold_min.
    rec114: "listed" applies schedule_v2 to the routes in that file; "none" uses the export schedule only."""
    return analytics.late_routes_by_day(date, threshold_min, rec114)


@mcp.tool()
def route_lateness(rec114: str = "listed") -> str:
    """Weekly ranking of every route by median lateness, with mean, p90 and share of trips >= 10 min late."""
    return analytics.route_lateness(rec114)


@mcp.tool()
def worst_three(rec114: str = "none") -> str:
    """The 3 worst routes by median lateness (actual arrival minus scheduled departure + runtime), ties broken by
    % trips >5 min late then P90. Table with trips, median, mean, P90, max, >5/>15 min counts and %, early/on-time,
    low-sample flag, plus an evidence-only summary. rec114="none" uses the export runtimes; "listed" applies schedule_v2."""
    return analytics.worst_three(rec114)


@mcp.tool()
def route_detail(route: str, rec114: str = "listed") -> str:
    """Day-by-day and hour-by-hour lateness for one route (e.g. R-14), plus its worst trip ids."""
    return analytics.route_detail(route, rec114)


@mcp.tool()
def trip_detail(trip_id: str) -> str:
    """One trip: scheduled vs actual, lateness under the export and revised schedules, overlapping ops-log events."""
    return analytics.trip_detail(trip_id)


@mcp.tool()
def data_quality() -> str:
    """How many rows of the active dataset were excluded and why, plus revised-schedule coverage."""
    return analytics.data_quality()


@mcp.tool()
def manager_report(top: int = 15) -> str:
    """Manager-ready report for the active dataset: route lateness table (median, mean, p90, >5/>15 min,
    early/on-time), original vs schedule_v2 reconciliation, ops-log events checked against observed delay,
    recurring patterns, daily spikes, schedule discrepancies and data-quality caveats. All tables."""
    return analytics.manager_report(top)


if __name__ == "__main__":
    mcp.run()
