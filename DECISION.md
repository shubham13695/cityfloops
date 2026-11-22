# Decision record: route lateness, week 2026-W32 (Mon 3 to Sun 9 Aug)

For Priya, Ops Lead. All figures come from the MCP server tools (`worst_three`, `route_lateness`, `late_routes_by_day`, `manager_report`, `trip_detail`) on 5,249 valid trips. Lateness = actual arrival minus (scheduled departure + scheduled runtime), in minutes, on the original export schedule.

## The verdict

**Worst three: R-14, R-33, R-26.** R-35 is reported separately as a one-day incident.

| Route | Verdict | Evidence |
|---|---|---|
| R-14 | **Late, chronic** | Median +8.0, 85 of 118 trips (72%) over 5 min late, 8 over 15, daily median at least 5 min on 7 of 7 days |
| R-33 | **Late, chronic** | Median +5.0, 49 of 104 trips (47%) over 5 min late, daily median at least 5 min on 6 of 7 days |
| R-26 | **Late, watch** | Median +4.0, 44 of 103 trips (43%) over 5 min late, daily median at least 5 min on 4 of 7 days |
| R-35 | **One-day incident, Wed 5 Aug** | 19 of 19 trips that day late, median +52, other six days mean +0.8 |
| Other 36 routes | **On time** | Median at most +4, none late on more than 2 of 7 days (R-37 is nearest: median +4, 2 of 7 days) |

Verdict rules: *Late, chronic* = daily median at least 5 min over on at least 5 of 7 days. *Late, watch* = on 3 or 4 of 7 days. *One-day incident* = a route-day median at least 5 min above that route's other days. Anything else is *On time*. A stranger can re-run these on next week's data with the same tools.

---

## Call 1: Rank by median lateness on the original schedule

**The rule.** Rank routes by median lateness, highest first. Ties break on the share of trips over 5 min late, then P90. Early arrivals stay as negative values. Rows with unparseable timestamps, a non-IST offset, or arrival before departure are excluded.

**The case it breaks on.** R-35. Its mean is +8.1, tied with R-14, but its median is +2.0, so the rule ranks it 13th. Its 19 trips on Wed 5 Aug (`T1-04505` to `T1-04523`) averaged 51 min late, up to 61. A median hides that. I keep the rule because it reports R-35 separately (Call 3) instead of letting one day set a route's rank. The second weak spot is R-26 against R-37. Both have median +4.0, and R-26 wins on 42.7% against 40.0% of trips over 5 min late. That is a 2.7-point margin on about 100 trips each.

**The cost, and who pays.** If R-14 is flagged and the verdict is wrong, its depot head loses the on-time incentive. Evidence against that: 85 of 118 trips over 5 min late and 0 early. If R-14 is cleared and was late, riders on 85 late trips (8 over 15 min) sit in the refund queue. The R-26 versus R-37 call costs one of two depot heads a watch label on a thin margin.

**What would change my mind.** A second week in which R-37 beats R-26 on median would flip third place. A route whose median stays low but whose P90 sits above +30 in two weeks running would need a P90 rule, because the median would be hiding it.

---

## Call 2: Do not apply `schedule_v2.csv` as an override; show it beside the original

**The rule.** Verdicts use each trip's own `scheduled_runtime_min` from the export. For routes listed in `schedule_v2.csv`, the report prints original and revised results side by side. Nothing replaces the original.

**Why I am not applying REC-114 as written.** REC-114 says to use the revised timetable for the 4xx vehicle series. The data has no 4xx vehicle series (`vehicle_series` is two digits and matches the route number). The file lists R-14 and R-27, which are not 4xx. R-27's note says "no change", yet using its revised 45 min moves its median from +2.0 to +5.0. Export runtimes vary per trip (35 to 55 min on all 40 routes) and buses follow them, for example R-27 trips scheduled for 35 min took a median of 36 and those scheduled for 55 took 58. A flat per-route number makes short trips look late and long trips look early. I am treating this as a disclosed deviation from directive (b) for Priya to overrule.

**The case it breaks on.** `T1-01711` (R-14, Wed 5 Aug 08:39). On the original schedule it is Delayed (+10 min). On the revised 53 min it is Early (-8 min). Same trip, opposite verdict. I keep the original because the revised value (53) equals R-14's median actual runtime (53), so it absorbs the lateness; it does not show the route improving.

**The cost, and who pays.** On the revised timetable R-14 has a median of +0.0, 37 of 118 trips over 5 min late (against 85), and falls from rank 1 to rank 34. R-27 rises from rank 16 to rank 1 (67 trips over 5 min late). If REC-114 is the intended basis, my verdict wrongly flags R-14's depot head and misses R-27. If it is not, applying it would clear R-14 and put R-27's depot head in the worst three on a route whose own note says "no change".

**What would change my mind.** Written confirmation from ops-automation that R-14's 53 min is the official timetable and that the 4xx wording is a typo. Then the worst three become R-33, R-27, R-26.

---

## Call 3: Report R-35's Wednesday as a separate incident, not as a chronic route and not as a weather casualty

**The rule.** A route-day whose median is at least 5 min above that route's median on its other days (at least 8 trips) is listed as a spike and excluded from the chronic ranking. An ops-log event is linked to a route only if the route's median in the event window is at least 5 min above its own median for the same clock window on other days (at least 4 trips in the window, 8 in the baseline).

**The case it breaks on.** `T1-04521` (R-35, Wed 12:21, +61 min). The waterlogging note says "all AM" and I set its window to end at 12:00, so this trip falls outside it, yet the route was late until 20:21. The log overlaps 7 of R-35's 19 late trips (waterlogging) and 3 (crowd surge), leaving 9 with no logged event; overlap is not proof of cause. I keep the rule rather than stretching the window to fit.

**The cost, and who pays.** Counting R-35 as chronic would put it in the worst three on one day and cost its depot head an incentive on a route that averaged +0.8 on the other six days. Excusing it as weather would hide 19 riders' delays of about 51 min each from the refund queue without evidence that the weather reached this route. I choose to report it neither way.

**What would change my mind.** Ops confirming that R-35 runs the SV Road corridor would let me attribute at least the morning trips to waterlogging. A second all-day R-35 spike in another week would make it chronic.

---

## Call 4: Exclude the 43 invalid rows rather than repair them

**The rule.** Exclude rows where a timestamp cannot be parsed (24 with `08:60`), the arrival offset is not +05:30 (1), or arrival is before departure (18, all exactly 5 min early). No repair is attempted.

**The case it breaks on.** `T1-02864` (R-23): arrival `01:32` with offset `+00:00`. Read as UTC that is 07:02 IST, which is 2 min early against a 50-min runtime, so it looks repairable. I still exclude it, because an offset-only repair would be a guess about one device, and ten of the `08:60` rows share one identical stamp, which points to a stuck unit. The 18 early rows are all exactly -5, which looks like a systematic clock fault.

**The cost, and who pays.** 43 of 5,292 rows (0.8%). R-27 loses the most with 4 rows. Their effect on any median is small, so the cost is mostly credibility if someone asks where the missing trips went.

**What would change my mind.** The device vendor confirming that `08:60` means 09:00 or that the -5 clock offset is fixed, in which case I would repair those rows and re-run.

---

## Call 5: "Late" means more than 5 min over; on-time means 0 to 5

**The rule.** Early is under 0, on time is 0 to 5, delayed is over 5 up to 15, severely delayed is over 15. A route's worst-three rank uses its median, not these bands.

**The case it breaks on.** R-33. Its median is exactly +5.0, which the bands call on time, yet it ranks second and has a daily median of at least 5 min on 6 of 7 days. 49 of its 104 trips (47%) are over 5 min late. I keep 5 min because it is a round figure ops can state, and it is the threshold that separates R-14 and R-33 (two routes at a median of 5 or more) from the network (12 routes at a median of 3 or more).

**The cost, and who pays.** A 3-min threshold would name 12 routes and their depot heads. A 7-min threshold would clear R-33 and leave only R-14, sending R-33 riders' 49 late trips to the refund queue unflagged.

**What would change my mind.** Ops stating the tolerated delay in the customer promise or incentive contract. If it is 3 min, 12 routes would be named; if it is 7, the verdict list is R-14 alone.

---

## The call I am least sure of

Call 2. It overrides a signed-off directive on my own reading of the data, and it decides whether R-14 (the single worst route on the original schedule) is flagged at all. Next to it, R-35 is the call with the most uncertainty about cause.

## Data-quality caveats

- 43 rows excluded; 59 (route, arrival) pairs repeat among valid trips and may be stuck devices.
- The ops log has 6 entries, names no routes, and one note says "all normal" with no time span. Event windows (for example "all AM" = until 12:00) are my assumptions from the wording.
- One week of data: patterns are indicative.
- No phone numbers or complaint text appear in any tool output.
