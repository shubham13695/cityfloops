"""Lateness analytics over the active dataset. Lateness = actual runtime - scheduled runtime, minutes.

Rules (all overridable via tool parameters):
- A trip is usable only if both timestamps parse, tz_offset is +05:30, and arrival >= departure.
- rec114="listed": routes present in schedule_v2.csv are measured against revised_runtime_min;
  rec114="none": every trip uses its own scheduled_runtime_min.
- A route is "late" on a day if its median lateness that day >= threshold_min.
- Routes are ranked by median lateness, ties broken by share of trips >= 10 min late, then p90.
- Ops-log text is never returned; only a category and a fixed label are.
"""
import collections
import csv
import re
import statistics as st
from datetime import datetime, timedelta

import store

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LATE_TRIP_MIN = 10  # a single trip counts as "late" at this many minutes over


# ---------- loading ----------
def _week_monday(period: str) -> datetime:
    year, week = period.split("-W")
    return datetime.fromisocalendar(int(year), int(week), 1)


def load_active():
    period = store.active_period()
    if not period:
        raise ValueError("no active dataset; call use_dataset first")
    return load_period(period)


def load_period(period: str):
    excluded = collections.Counter()
    trips = []
    with open(store.path_for("trips", period), newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.strptime(r["scheduled_departure"], "%Y-%m-%d %H:%M")
                a = datetime.strptime(r["actual_arrival"], "%Y-%m-%d %H:%M")
                sched = float(r["scheduled_runtime_min"])
            except (ValueError, TypeError):
                excluded["unparseable timestamp"] += 1
                continue
            if r["tz_offset"] != "+05:30":
                excluded["non-IST tz offset"] += 1
                continue
            if a < d:
                excluded["arrival before departure"] += 1
                continue
            trips.append({"id": r["trip_id"], "route": r["route"], "series": r["vehicle_series"],
                          "dep": d, "arr": a, "dur": (a - d).total_seconds() / 60, "sched": sched})
    v2 = {}
    with open(store.path_for("schedule_v2", period), newline="") as f:
        for r in csv.DictReader(f):
            try:
                v2[r["route"]] = float(r["revised_runtime_min"])
            except (ValueError, TypeError):
                pass
    return {"period": period, "trips": trips, "v2": v2, "excluded": excluded,
            "events": parse_ops_log(period)}


def late(t, v2, rec114):
    s = v2[t["route"]] if rec114 == "listed" and t["route"] in v2 else t["sched"]
    return t["dur"] - s


# ---------- ops log ----------
# keyword -> (category, label, window rule). Labels are fixed strings, so raw log text never leaves.
_RULES = [
    (r"waterlog|flood", "weather / diversion", "Road waterlogging, diversion", "am"),
    (r"festival|crowd|surge", "crowd surge", "Crowd surge, city-wide slowdown", "evening"),
    (r"no-?show", "driver no-show", "Driver no-show", "evening"),
    (r"yard|depot", "depot delay", "Late departures from depot", "hour"),
    (r"complaint|swap", "vehicle swap", "Vehicle swap after a rider complaint", "midday"),
    (r"normal|good day", "normal", "Normal operations", "none"),
]


def parse_ops_log(period: str):
    base = _week_monday(period)
    events = []
    p = store.path_for("ops_log", period)
    if not p.exists():
        return events
    for line in p.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}):(\d{2})\s+(.*)$", line)
        if not m:
            continue
        day = base + timedelta(days=DAYS.index(m[1]))
        start = day.replace(hour=int(m[2]), minute=int(m[3]))
        text = m[4].lower()
        cat, label, rule = "other", "Unclassified note", "hour"
        for pat, c, lab, rl in _RULES:
            if re.search(pat, text):
                cat, label, rule = c, lab, rl
                break
        end = {"am": day.replace(hour=12), "evening": day + timedelta(days=1),
               "midday": day.replace(hour=15), "hour": start + timedelta(hours=3),
               "none": start}[rule]
        if rule == "midday":
            start = min(start, day.replace(hour=11))
        events.append({"day": m[1], "start": start, "end": end, "category": cat, "label": label})
    return events


def events_for(dt, events):
    return [e for e in events if e["category"] != "normal" and e["start"] <= dt < e["end"]]


# ---------- stats ----------
def route_stats(vals):
    vals = sorted(vals)
    n = len(vals)
    return {"n": n, "median": st.median(vals), "mean": st.mean(vals), "p90": vals[min(int(.9 * n), n - 1)],
            "max": vals[-1], "late_share": sum(v >= LATE_TRIP_MIN for v in vals) / n}


def ranked(ds, rec114):
    by = collections.defaultdict(list)
    for t in ds["trips"]:
        by[t["route"]].append(late(t, ds["v2"], rec114))
    rows = {r: route_stats(v) for r, v in by.items()}
    order = sorted(rows, key=lambda r: (-rows[r]["median"], -rows[r]["late_share"], -rows[r]["p90"]))
    return order, rows


def _table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _empty(ds):
    return None if ds["trips"] else f"No usable trips in dataset {ds['period']}."


# ---------- tool bodies ----------
def late_routes_by_day(date=None, threshold_min=5.0, rec114="listed"):
    ds = load_active()
    if (m := _empty(ds)):
        return m
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for t in ds["trips"]:
        by[t["dep"].strftime("%Y-%m-%d")][t["route"]].append((t, late(t, ds["v2"], rec114)))
    days = [date] if date else sorted(by)
    header = ["Route", "Median late (min)", "Late trips (>=10 min)", "Trips",
              "Late departures (first-last)", "Worst trip", "Ops log"]
    out = [f"Dataset {ds['period']}, rec114={rec114}. A route is late on a day if its median lateness >= "
           f"{threshold_min} min. Sorted by median lateness, worst first. Same columns for every day."]
    for d in days:
        label = datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b") if d in by else d
        rows = []
        for r, pairs in by.get(d, {}).items():
            vals = [l for _, l in pairs]
            med = st.median(vals)
            if med < threshold_min:
                continue
            bad = sorted([(t, l) for t, l in pairs if l >= LATE_TRIP_MIN], key=lambda x: x[0]["dep"])
            worst = max(pairs, key=lambda x: x[1])
            window = f"{bad[0][0]['dep']:%H:%M}-{bad[-1][0]['dep']:%H:%M}" if bad else "-"
            hits = collections.Counter()
            for t, _ in bad:
                for e in events_for(t["dep"], ds["events"]):
                    hits[f"{e['label']} [{e['category']}]"] += 1
            ops = "; ".join(f"{k} ({c} of {len(bad)} late trips)" for k, c in hits.most_common()) or "-"
            rows.append((med, [r, f"{med:+.1f}", len(bad), len(pairs), window,
                               f"{worst[0]['id']} {worst[0]['dep']:%H:%M} ({worst[1]:+.0f})", ops]))
        rows.sort(key=lambda x: -x[0])
        body = [r for _, r in rows] or [["no late routes", "", "", "", "", "", ""]]
        out.append(f"\n**{label}**: {len(rows)} late route(s)\n" + _table(header, body))
    return "\n".join(out)


def route_lateness(rec114="listed", top=40):
    ds = load_active()
    if (m := _empty(ds)):
        return m
    order, rows = ranked(ds, rec114)
    _, base = ranked(ds, "none") if rec114 == "listed" else (None, None)
    table = []
    for i, r in enumerate(order[:top], 1):
        s = rows[r]
        note = ""
        if base and r in ds["v2"]:
            note = f"median vs export schedule: {base[r]['median']:.1f}"
        table.append((i, r, s["n"], f"{s['mean']:+.1f}", f"{s['median']:+.1f}", f"{s['p90']:+.0f}",
                      f"{s['max']:+.0f}", f"{s['late_share'] * 100:.0f}%", note))
    return (f"Dataset {ds['period']}, rec114={rec114}. Lateness in minutes. Ranked by median "
            f"(ties: share of trips >=10 min late, then p90).\n"
            + _table(["Rank", "Route", "Trips", "Mean", "Median", "P90", "Max late", ">=10 min late", "Note"], table))


def worst_three(rec114="none", n=3, min_trips=30):
    """Top-n routes by median lateness. Lateness = actual arrival - (scheduled departure + runtime), minutes.
    Ties: share of trips >5 min late, then P90. Early arrivals stay negative. Invalid rows are excluded."""
    ds = load_active()
    if (m := _empty(ds)):
        return m
    by = collections.defaultdict(list)
    for t in ds["trips"]:
        by[t["route"]].append(late(t, ds["v2"], rec114))
    rows = {}
    for r, v in by.items():
        b = _bucket(v)
        b["pct5"] = b["gt5"] / b["n"] * 100
        b["pct15"] = b["gt15"] / b["n"] * 100
        rows[r] = b
    order = sorted(rows, key=lambda r: (-rows[r]["median"], -rows[r]["pct5"], -rows[r]["p90"]))
    top = order[:n]
    all_vals = [l for v in by.values() for l in v]
    net_med, net_pct5 = st.median(all_vals), sum(x > 5 for x in all_vals) / len(all_vals) * 100
    basis = "original export runtimes" if rec114 == "none" else "schedule_v2 revised runtimes where listed"
    out = [f"Dataset {ds['period']}. Lateness = actual arrival - (scheduled departure + runtime), minutes, using {basis}. "
           f"Early = under 0, on-time = 0 to {ONTIME_MAX}. Ranked by median, then % trips >5 min late, then P90. "
           f"{len(ds['trips'])} valid trips; {sum(ds['excluded'].values())} invalid rows excluded."]
    out.append("\n**Top %d worst routes**\n" % n + _table(
        ["Rank", "Route", "Trips", "Median", "Mean", "P90", "Max", ">5 min", ">5 %", ">15 min", ">15 %",
         "Early", "On-time", "Sample"],
        [(i, r, rows[r]["n"], f"{rows[r]['median']:+.1f}", f"{rows[r]['mean']:+.1f}", f"{rows[r]['p90']:+.0f}",
          f"{rows[r]['max']:+.0f}", rows[r]["gt5"], f"{rows[r]['pct5']:.0f}%", rows[r]["gt15"],
          f"{rows[r]['pct15']:.0f}%", rows[r]["early"], rows[r]["ontime"],
          "LOW (<%d)" % min_trips if rows[r]["n"] < min_trips else "ok")
         for i, r in enumerate(top, 1)]))
    out.append(f"\n**Why they rank worst** (network median {net_med:+.1f} min, {net_pct5:.0f}% of all trips >5 min late)")
    for i, r in enumerate(top, 1):
        b = rows[r]
        day = collections.defaultdict(list)
        for t in by_route_trips(ds, r):
            day[t["dep"].date()].append(late(t, ds["v2"], rec114))
        days_late = sum(st.median(v) >= 5 for v in day.values())
        nxt = order[i] if i < len(order) else None
        tie = ""
        if nxt and abs(rows[nxt]["median"] - b["median"]) < 1e-9:
            tie = f" Tied on median with {nxt}; ordered by % >5 min late ({b['pct5']:.1f}% vs {rows[nxt]['pct5']:.1f}%)."
        low = " Low sample size, treat with caution." if b["n"] < min_trips else ""
        out.append(f"- **#{i} {r}**: median {b['median']:+.1f} min vs network {net_med:+.1f}; "
                   f"{b['pct5']:.0f}% of trips >5 min late vs {net_pct5:.0f}% network; P90 {b['p90']:+.0f}, worst trip {b['max']:+.0f}; "
                   f"daily median >=5 min on {days_late} of {len(day)} days; early arrivals (kept in the figures): {b['early']}.{tie}{low}")
    out.append("\nCauses are not determined by this ranking. It uses trip timestamps only, so no cause is claimed; "
               "use `manager_report` to compare ops-log events against the delay evidence.")
    return "\n".join(out)


def by_route_trips(ds, route):
    return [t for t in ds["trips"] if t["route"] == route]


def route_detail(route, rec114="listed"):
    ds = load_active()
    trips = [t for t in ds["trips"] if t["route"] == route]
    if not trips:
        return f"No usable trips for {route} in dataset {ds['period']}."
    ls = [(t, late(t, ds["v2"], rec114)) for t in trips]
    s = route_stats([l for _, l in ls])
    out = [f"{route} in {ds['period']} (rec114={rec114}). Lateness in minutes.",
           "\n**Summary**\n" + _table(["Trips", "Mean", "Median", "P90", "Max late", ">=10 min late"],
                                      [(s["n"], f"{s['mean']:+.1f}", f"{s['median']:+.1f}", f"{s['p90']:+.0f}",
                                        f"{s['max']:+.0f}", f"{s['late_share'] * 100:.0f}%")])]
    by_day = collections.defaultdict(list)
    for t, l in ls:
        by_day[t["dep"].strftime("%a %d")].append(l)
    out.append("\n**By day**\n" + _table(["Day", "Trips", "Median", "Mean", "Max late"],
                                          [(d, len(v), f"{st.median(v):+.1f}", f"{st.mean(v):+.1f}", f"{max(v):+.0f}")
                                           for d, v in sorted(by_day.items())]))
    by_h = collections.defaultdict(list)
    for t, l in ls:
        by_h[t["dep"].hour].append(l)
    out.append("\n**By departure hour**\n" + _table(["Hour", "Trips", "Median"],
                                                     [(f"{h:02d}:00", len(v), f"{st.median(v):+.1f}")
                                                      for h, v in sorted(by_h.items())]))
    out.append("\n**Worst trips**\n" + _table(
        ["Trip", "Departure", "Late (min)"],
        [(t["id"], f"{t['dep']:%a %d %b %H:%M}", f"{l:+.0f}") for t, l in sorted(ls, key=lambda x: -x[1])[:8]]))
    return "\n".join(out)


def _status(l):
    """Early < 0, On time 0..5, Delayed 6..15 (over 5 up to 15), Severely delayed > 15."""
    return "Early" if l < 0 else "On time" if l <= ONTIME_MAX else "Delayed" if l <= 15 else "Severely delayed"


def _raw_row(period, trip_id):
    """The stored row for a trip id, with the reason it is not analysable (None if it is fine)."""
    with open(store.path_for("trips", period), newline="") as f:
        for r in csv.DictReader(f):
            if r["trip_id"] != trip_id:
                continue
            try:
                d = datetime.strptime(r["scheduled_departure"], "%Y-%m-%d %H:%M")
                a = datetime.strptime(r["actual_arrival"], "%Y-%m-%d %H:%M")
                float(r["scheduled_runtime_min"])
            except (ValueError, TypeError):
                return r, "a timestamp or runtime cannot be parsed"
            if r["tz_offset"] != "+05:30":
                return r, f"arrival stamped with tz offset {r['tz_offset']} instead of +05:30"
            if a < d:
                return r, "actual arrival is before the scheduled departure"
            return r, None
    return None, None


def trip_detail(trip_id):
    ds = load_active()
    tid = (trip_id or "").strip()
    t = next((x for x in ds["trips"] if x["id"].lower() == tid.lower()), None)
    if not t:
        raw, reason = _raw_row(ds["period"], tid) if tid else (None, None)
        if raw is None:
            return (f"Trip '{trip_id}' was not found in dataset {ds['period']}. "
                    f"Check the id (format like T1-00001) or the active dataset with list_datasets.")
        rows = [("Route", raw["route"]), ("Vehicle series", raw["vehicle_series"]),
                ("Scheduled departure", raw["scheduled_departure"]),
                ("Scheduled runtime", f"{raw['scheduled_runtime_min']} min"),
                ("Actual arrival (as recorded)", f"{raw['actual_arrival']} (offset {raw['tz_offset']})"),
                ("Status", "Invalid record, excluded from all analysis"), ("Why", reason),
                ("Lateness", "not calculated")]
        return f"**{raw['trip_id']}**\n" + _table(["Field", "Value"], rows)
    exp_arr = t["dep"] + timedelta(minutes=t["sched"])
    l_o = late(t, ds["v2"], "none")
    rows = [("Route", t["route"]), ("Vehicle series", t["series"]),
            ("Scheduled departure", f"{t['dep']:%a %d %b %Y %H:%M}"),
            ("Scheduled runtime (original)", f"{t['sched']:.0f} min"),
            ("Expected arrival (original)", f"{exp_arr:%a %d %b %H:%M}"),
            ("Actual arrival", f"{t['arr']:%a %d %b %H:%M}"),
            ("Lateness (original)", f"{l_o:+.0f} min"), ("Status (original)", _status(l_o))]
    if t["route"] in ds["v2"]:
        rv = ds["v2"][t["route"]]
        l_v = late(t, ds["v2"], "listed")
        rows += [("Revised runtime (schedule_v2)", f"{rv:.0f} min"),
                 ("Expected arrival (revised)", f"{t['dep'] + timedelta(minutes=rv):%a %d %b %H:%M}"),
                 ("Lateness (revised)", f"{l_v:+.0f} min"), ("Status (revised)", _status(l_v))]
    else:
        rows.append(("Revised schedule", "not applicable: route is not listed in schedule_v2"))
    evs = [e for e in ds["events"] if e["category"] != "normal" and e["start"] <= t["arr"] and e["end"] > t["dep"]]
    rows.append(("Logged events during the trip",
                 "; ".join(f"{e['day']} {_win_txt(e)} {e['label']}" for e in evs)
                 if evs else "none logged for this time window"))
    note = ("Logged events are ops notes that overlap the trip's time window. The log names no routes or trips, "
            "so none of them is a confirmed cause of this delay." if evs else
            "No logged event overlaps this trip. That does not rule out a cause the log did not record.")
    return (f"**{t['id']}**: {_status(l_o)} ({l_o:+.0f} min vs original schedule)\n"
            + _table(["Field", "Value"], rows) + f"\n{note}\n"
            f"Status bands: Early < 0, On time 0-{ONTIME_MAX}, Delayed over {ONTIME_MAX} to 15, Severely delayed over 15 (minutes).")


def data_quality():
    ds = load_active()
    bad = sum(ds["excluded"].values())
    out = [f"Dataset {ds['period']}",
           "\n**Rows**\n" + _table(["Total", "Usable", "Excluded"], [(len(ds["trips"]) + bad, len(ds["trips"]), bad)])]
    out.append("\n**Excluded rows by reason**\n" + _table(
        ["Reason", "Rows"], sorted(ds["excluded"].items(), key=lambda x: -x[1]) or [("none", 0)]))
    series4 = sorted({t["route"] for t in ds["trips"] if t["series"].startswith("4") and len(t["series"]) > 2})
    out.append("\n**Coverage**\n" + _table(
        ["Check", "Result"],
        [("Revised-schedule routes loaded", ", ".join(sorted(ds["v2"])) or "none"),
         ("Routes with a 3-digit 4xx vehicle series", ", ".join(series4) or "none"),
         ("Ops-log events parsed", len(ds["events"]))]))
    return "\n".join(out)


# ---------- manager report ----------
ONTIME_MAX = 5      # on-time: 0..5 min over; early: < 0; late: > 5
EVIDENCE_MIN = 5    # a route/day/event shows "evidence" only if it exceeds its own baseline by this many minutes


def _bucket(vals):
    s = route_stats(vals)
    return {**s, "early": sum(v < 0 for v in vals), "ontime": sum(0 <= v <= ONTIME_MAX for v in vals),
            "gt5": sum(v > 5 for v in vals), "gt15": sum(v > 15 for v in vals)}


def _tod(dt):
    return dt.hour * 60 + dt.minute


def _win_txt(e):
    end = "24:00" if e["end"].date() > e["start"].date() else f"{e['end']:%H:%M}"
    return f"{e['start']:%H:%M}-{end}"


def manager_report(top=15):
    ds = load_active()
    if (m := _empty(ds)):
        return m
    trips, v2, events = ds["trips"], ds["v2"], ds["events"]
    L = {t["id"]: late(t, v2, "none") for t in trips}      # original (export) schedule
    LV = {t["id"]: late(t, v2, "listed") for t in trips}   # revised timetable where listed
    by_route = collections.defaultdict(list)
    for t in trips:
        by_route[t["route"]].append(t)
    stats = {r: _bucket([L[t["id"]] for t in ts]) for r, ts in by_route.items()}
    order = sorted(stats, key=lambda r: (-stats[r]["median"], -stats[r]["gt15"], -stats[r]["p90"]))
    out = [f"# Route lateness report: {ds['period']}",
           f"Lateness = actual runtime minus scheduled runtime (minutes), on the **original export schedule**. "
           f"Early = under 0, on-time = 0 to {ONTIME_MAX}, late = over {ONTIME_MAX}. "
           f"{len(trips)} usable trips, {sum(ds['excluded'].values())} excluded."]

    # 1. route table
    out.append(f"\n## 1. Routes ranked by median lateness (top {min(top, len(order))} of {len(order)})\n" + _table(
        ["Rank", "Route", "Trips", "Median", "Mean", "P90", ">5 min", ">15 min", "Early", "On-time"],
        [(i, r, stats[r]["n"], f"{stats[r]['median']:+.1f}", f"{stats[r]['mean']:+.1f}", f"{stats[r]['p90']:+.0f}",
          stats[r]["gt5"], stats[r]["gt15"], stats[r]["early"], stats[r]["ontime"])
         for i, r in enumerate(order[:top], 1)]))

    # 2. reconciliation with schedule_v2 (both shown, original never replaced)
    rec_rows = []
    rank_exp = {r: i for i, r in enumerate(order, 1)}
    order_v = sorted(by_route, key=lambda r: -_bucket([LV[t["id"]] for t in by_route[r]])["median"])
    rank_v = {r: i for i, r in enumerate(order_v, 1)}
    for r in sorted(v2):
        if r not in by_route:
            continue
        for basis, src, rk in (("Original (per-trip export runtime)", L, rank_exp),
                               (f"Revised ({v2[r]:.0f} min flat, schedule_v2)", LV, rank_v)):
            b = _bucket([src[t["id"]] for t in by_route[r]])
            rec_rows.append((r, basis, f"{b['median']:+.1f}", f"{b['mean']:+.1f}", f"{b['p90']:+.0f}",
                             b["gt5"], b["gt15"], b["early"], b["ontime"], f"#{rk[r]}"))
    out.append("\n## 2. Original vs schedule_v2 (both shown; the original is not replaced)\n" + _table(
        ["Route", "Schedule basis", "Median", "Mean", "P90", ">5 min", ">15 min", "Early", "On-time", "Rank"],
        rec_rows or [("none", "", "", "", "", "", "", "", "", "")]))

    # 3. events vs observed delay (evidence only)
    ev_rows = []
    for e in events:
        s0, s1 = _tod(e["start"]), (1440 if e["end"].date() > e["start"].date() else _tod(e["end"]))
        in_win = [t for t in trips if t["dep"].date() == e["start"].date() and s0 <= _tod(t["dep"]) < s1]
        base = [t for t in trips if t["dep"].date() != e["start"].date() and s0 <= _tod(t["dep"]) < s1]
        if not in_win or not base:
            ev_rows.append((f"{e['start']:%a %d %b}", e["label"], _win_txt(e), len(in_win), "-", "-", "-", "no trips to compare"))
            continue
        net_in = st.median(L[t["id"]] for t in in_win)
        net_base = st.median(L[t["id"]] for t in base)
        hit = []
        for r in sorted({t["route"] for t in in_win}):
            ri = [L[t["id"]] for t in in_win if t["route"] == r]
            rb = [L[t["id"]] for t in base if t["route"] == r]
            if len(ri) >= 4 and len(rb) >= 8 and st.median(ri) - st.median(rb) >= EVIDENCE_MIN:
                hit.append(f"{r} ({st.median(ri):+.0f} vs {st.median(rb):+.0f}, n={len(ri)})")
        verdict = ", ".join(hit) if hit else "no route shows a measurable effect"
        ev_rows.append((f"{e['start']:%a %d %b}", e["label"], _win_txt(e), len(in_win),
                        f"{net_in:+.1f}", f"{net_base:+.1f}", f"{net_in - net_base:+.1f}", verdict))
    out.append("\n## 3. Ops-log events vs observed delay\n"
               f"The log names no routes, so an event is linked to a route only if that route's median in the event window "
               f"is at least {EVIDENCE_MIN} min above its own median for the same clock window on other days "
               f"(min 4 trips in the window, 8 baseline trips).\n" + _table(
        ["Date", "Event", "Window", "Trips", "Network median", "Same window other days", "Delta", "Routes with evidence"],
        ev_rows or [("-", "no events parsed", "", "", "", "", "", "")]))

    # 4. recurring patterns
    day_med = collections.defaultdict(dict)
    for r, ts in by_route.items():
        dd = collections.defaultdict(list)
        for t in ts:
            dd[t["dep"].date()].append(L[t["id"]])
        for d, v in dd.items():
            day_med[r][d] = st.median(v)
    n_days = len({t["dep"].date() for t in trips})
    chronic = sorted(((r, sum(m >= 5 for m in dm.values())) for r, dm in day_med.items()),
                     key=lambda x: -x[1])
    chronic = [(r, c) for r, c in chronic if c >= max(3, n_days // 2)]
    out.append("\n## 4. Recurring delay patterns\n**Routes late (day median >= 5 min) on most days**\n" + _table(
        ["Route", f"Days late (of {n_days})", "Week median", "Week mean"],
        [(r, c, f"{stats[r]['median']:+.1f}", f"{stats[r]['mean']:+.1f}") for r, c in chronic]
        or [("none", "", "", "")]))
    bands = [("06-09", 6, 9), ("09-12", 9, 12), ("12-15", 12, 15), ("15-18", 15, 18), ("18-21", 18, 21), ("21+", 21, 25)]
    brow = []
    for name, a, b in bands:
        v = [L[t["id"]] for t in trips if a <= t["dep"].hour < b]
        if v:
            brow.append((name, len(v), f"{st.median(v):+.1f}", f"{st.mean(v):+.1f}", sum(x > 15 for x in v)))
    out.append("\n**Network by departure hour**\n" + _table(
        ["Departure hours", "Trips", "Median", "Mean", ">15 min"], brow))

    # 5. unusual daily spikes
    spikes = []
    for r, dm in day_med.items():
        for d, med in dm.items():
            others = [m for dd, m in dm.items() if dd != d]
            if len(others) < 3:
                continue
            ds_trips = [t for t in by_route[r] if t["dep"].date() == d]
            if len(ds_trips) < 8:
                continue
            delta = med - st.median(others)
            if delta >= EVIDENCE_MIN:
                spike_trips = [t for t in ds_trips if L[t["id"]] > 15] or [t for t in ds_trips if L[t["id"]] > 5]
                linked = collections.Counter(e["label"] for t in spike_trips for e in events_for(t["dep"], events))
                spikes.append((delta, (r, f"{d:%a %d %b}", f"{med:+.1f}", f"{st.median(others):+.1f}", f"{delta:+.1f}",
                                       len(spike_trips),
                                       "; ".join(f"{k} ({c} of {len(spike_trips)} trips)" for k, c in linked.most_common())
                                       or "none logged")))
    spikes.sort(key=lambda x: -x[0])
    out.append(f"\n## 5. Unusual daily spikes (route-day median >= {EVIDENCE_MIN} min above the route's other days)\n" + _table(
        ["Route", "Date", "Day median", "Other-days median", "Delta", "Late trips", "Logged event overlapping those trips"],
        [r for _, r in spikes] or [("none", "", "", "", "", "", "")]))

    # 6. schedule discrepancies
    srows = []
    for r in sorted(v2):
        if r not in by_route:
            continue
        ts = by_route[r]
        vals = sorted({t["sched"] for t in ts})
        srows.append((r, f"{len(vals)} values ({vals[0]:.0f}-{vals[-1]:.0f})", f"{v2[r]:.0f}",
                      f"{st.median(t['dur'] for t in ts):.0f}", f"{st.median(L[t['id']] for t in ts):+.1f}",
                      f"{st.median(LV[t['id']] for t in ts):+.1f}"))
    all_vals = {r: len({t["sched"] for t in ts}) for r, ts in by_route.items()}
    series4 = sorted({t["route"] for t in trips if len(t["series"]) > 2 and t["series"].startswith("4")})
    out.append("\n## 6. Schedule discrepancies\n" + _table(
        ["Route", "Export runtimes in the week", "Revised runtime", "Median actual runtime",
         "Median late vs export", "Median late vs revised"], srows or [("none", "", "", "", "", "")]))
    out.append("\n" + _table(["Check", "Finding"], [
        ("Routes where export runtime varies per trip", f"{sum(1 for v in all_vals.values() if v > 1)} of {len(all_vals)}"),
        ("Revised file vs trips", "gives one runtime per route; actual runtimes track each trip's own export runtime, "
                                   "so a flat override shifts short trips late and long trips early"),
        ("REC-114 targets (4xx series)", f"routes with a 3-digit 4xx vehicle series in data: {', '.join(series4) or 'none'}; "
                                          f"routes in schedule_v2: {', '.join(sorted(v2)) or 'none'}"),
        ("R-27 note in file", "'no change', yet its revised value (45) differs from its per-trip export runtimes"
         if "R-27" in v2 else "-")]))

    # 7. caveats
    pairs = collections.Counter((t["route"], t["arr"]) for t in trips)
    dup = sum(1 for c in pairs.values() if c > 1)
    out.append("\n## 7. Data-quality caveats\n" + _table(["Caveat", "Evidence"], [
        ("Rows excluded", "; ".join(f"{k}: {v}" for k, v in ds["excluded"].items()) or "none"),
        ("Possible repeated device stamps", f"{dup} (route, arrival time) pairs appear more than once among usable trips"),
        ("Ops log is thin and names no routes", f"{len(events)} events parsed; windows are assumed from wording (e.g. 'all AM' = until 12:00)"),
        ("Median hides rare large delays", "see P90 and >15 min columns; one-day spikes are listed in section 5"),
        ("Single week of data", f"{n_days} days; patterns are indicative, not proven")]))
    return "\n".join(out)
