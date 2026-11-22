"""Dataset storage: one folder per data type, one subfolder per ISO week (e.g. 2026-W32)."""
import csv
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "active.json"
PERIOD_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")

TRIPS_COLS = ["trip_id", "route", "vehicle_series", "scheduled_departure",
              "scheduled_runtime_min", "actual_arrival", "tz_offset", "scheduled_lateness_min"]
SCHED_COLS = ["route", "revised_runtime_min", "effective_date", "note"]

# type -> (folder, filename, header or None for plain text)
TYPES = {
    "trips": ("trips", "trips.csv", TRIPS_COLS),
    "ops_log": ("ops_log", "ops_log.txt", None),
    "schedule_v2": ("schedule_v2", "schedule_v2.csv", SCHED_COLS),
}
SENSITIVE_HINTS = ("phone", "mobile", "complaint", "comment", "message")


def check_period(period: str) -> str:
    if not PERIOD_RE.match(period or ""):
        raise ValueError(f"period must look like 2026-W32 (ISO week), got {period!r}")
    return period


def path_for(kind: str, period: str) -> Path:
    folder, name, _ = TYPES[kind]
    return DATA / folder / period / name


def ensure_period(period: str) -> list[str]:
    """Create an empty placeholder (header only for CSVs) for any missing file. Returns what was created."""
    created = []
    for kind, (_, _, header) in TYPES.items():
        p = path_for(kind, period)
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if header:
            with open(p, "w", newline="") as f:
                csv.writer(f).writerow(header)
        else:
            p.write_text("")
        created.append(kind)
    return created


def _is_placeholder(kind: str, p: Path) -> bool:
    if not p.exists():
        return True
    if TYPES[kind][2] is None:
        return p.stat().st_size == 0
    with open(p, newline="") as f:
        return sum(1 for _ in f) <= 1


def _count_rows(kind: str, p: Path) -> int:
    """Data rows in a stored file (CSV header excluded, blank lines ignored). 0 if missing or empty."""
    if not p.exists():
        return 0
    with open(p, newline="", errors="replace") as f:
        n = sum(1 for line in f if line.strip())
    return max(n - 1, 0) if TYPES[kind][2] else n


def validate_csv_columns(path: Path, required: list[str]) -> list[str]:
    with open(path, newline="") as f:
        header = next(csv.reader(f), [])
    missing = [c for c in required if c not in header]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}; found {header}")
    return header


def profile_trips(path: Path) -> dict:
    """Validation pass over a trips file. Counts problems; never returns row values."""
    header = validate_csv_columns(path, TRIPS_COLS)
    stats = {"rows": 0, "usable": 0, "unparseable_timestamp": 0,
             "arrival_before_departure": 0, "non_ist_offset": 0,
             "duplicate_trip_id": 0,
             "sensitive_columns_ignored": [c for c in header if any(h in c.lower() for h in SENSITIVE_HINTS)]}
    seen = set()
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            stats["rows"] += 1
            if r["trip_id"] in seen:
                stats["duplicate_trip_id"] += 1
            seen.add(r["trip_id"])
            try:
                d = datetime.strptime(r["scheduled_departure"], "%Y-%m-%d %H:%M")
                a = datetime.strptime(r["actual_arrival"], "%Y-%m-%d %H:%M")
                float(r["scheduled_runtime_min"])
            except (ValueError, TypeError):
                stats["unparseable_timestamp"] += 1
                continue
            if r["tz_offset"] != "+05:30":
                stats["non_ist_offset"] += 1
            elif a < d:
                stats["arrival_before_departure"] += 1
            else:
                stats["usable"] += 1
    return stats


def load(kind: str, src: str, period: str) -> dict:
    check_period(period)
    src_p = Path(src).expanduser()
    if not src_p.is_file():
        raise ValueError(f"file not found: {src}")
    _, _, header = TYPES[kind]
    result = {"type": kind, "period": period}
    if kind == "trips":
        result["validation"] = profile_trips(src_p)
    elif kind == "schedule_v2":
        validate_csv_columns(src_p, SCHED_COLS)
    else:
        result["lines"] = sum(1 for line in open(src_p, errors="replace") if line.strip())
    dest = path_for(kind, period)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_p, dest)
    result["placeholders_created"] = ensure_period(period)
    result["stored_at"] = str(dest.relative_to(DATA.parent))
    return result


def list_datasets() -> dict:
    periods = set()
    for kind, (folder, _, _) in TYPES.items():
        base = DATA / folder
        if base.is_dir():
            periods |= {d.name for d in base.iterdir() if d.is_dir() and PERIOD_RE.match(d.name)}
    current = active_period()
    out = []
    for p in sorted(periods, reverse=True):  # newest period first, same order every call
        files = {k: _count_rows(k, path_for(k, p)) for k in TYPES}
        out.append({"period": p, "active": p == current, **files})
    return {"active": current, "count": len(out), "datasets": out}


def active_period() -> str | None:
    if ACTIVE.exists():
        return json.loads(ACTIVE.read_text()).get("period")
    return None


def use_dataset(period: str) -> dict:
    check_period(period)
    created = ensure_period(period)
    trips = path_for("trips", period)
    validation = profile_trips(trips)  # raises if the columns are wrong, so a bad file can't become active
    ACTIVE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE.write_text(json.dumps({"period": period}))
    return {"active": period, "placeholders_created": created, "trips_validation": validation}
