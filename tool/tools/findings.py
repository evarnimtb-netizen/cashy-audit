#!/usr/bin/env python3
"""findings — turn a raw agent-state report into prioritized, honest findings.

A report of counts answers "what is there?". A buyer of an *audit* wants
"what looks wrong, how bad, and what should I check?". This produces that —
deterministically, with severities, and with an explicit statement of what it
CANNOT know. No network, no writes; pure function over the report dict.

Severity is deliberately conservative: anything we only *suspect* is `info`, not
`high`. A false alarm in an audit is a real cost to the buyer.
"""
from __future__ import annotations
from datetime import datetime, timezone

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def _rows(rep, table):
    t = (rep.get("tables") or {}).get(table)
    if isinstance(t, int):
        return t
    if not isinstance(t, dict):
        return None
    n = _as_int(t.get("rows"))
    if n is None:
        n = _as_int(t.get("count"))
    return n

def _spend(rep):
    """Best-effort total spend in cents across known cost tables."""
    total, seen = 0, False
    for name in ("inference_costs", "costs", "spend", "transactions"):
        t = (rep.get("tables") or {}).get(name)
        if not isinstance(t, dict):
            continue  # an int here is a row-count, not a spend record
        sums = t.get("sums") if isinstance(t.get("sums"), dict) else {}
        cc = sums.get("cost_cents")
        if isinstance(cc, dict):
            cc = cc.get("new")
        v = _as_int(cc)
        if v is None:
            v = _as_int(t.get("cost_cents"))
        if v is not None:
            total += v; seen = True
    return total if seen else None

def analyze(rep):
    """Return a list of finding dicts, sorted most-severe first."""
    out = []
    def add(sev, code, title, detail, check):
        out.append({"severity": sev, "code": code, "title": title, "detail": detail, "check": check})

    if not isinstance(rep, dict) or not rep:
        add("high", "empty-report", "Report is empty or unreadable",
            "No tables could be read from the state DB.",
            "Confirm the DB path and that it is a SQLite file.")
        return out

    tables = rep.get("tables") or {}
    if not tables:
        add("high", "no-tables", "No tables found in state DB",
            "The database opened but exposed no user tables.",
            "Verify this is the agent's state DB, not an empty template.")

    turns = next((v for k, v in tables.items() if "turn" in k), None)
    n_turns = _as_int((turns or {}).get("rows")) if isinstance(turns, dict) else None
    spend = _spend(rep)

    # spend with no ledger rows is the classic silent-billing gap
    costs = tables.get("inference_costs") or tables.get("costs")
    n_cost = _as_int((costs or {}).get("rows")) if isinstance(costs, dict) else None
    if spend and spend > 0 and (n_cost in (0, None)):
        add("high", "spend-without-rows", "Spend recorded but no cost rows",
            f"Reported spend is {spend} cents but the cost table has {n_cost} row(s).",
            "Check whether the ledger table is the right one, or rows were pruned.")

    if spend == 0 and n_turns and n_turns > 0 and n_cost is not None and n_cost > 0:
        add("info", "zero-cost-activity",
            "Activity with zero recorded cost",
            f"{n_turns} turn(s) and {n_cost} cost row(s) present, yet total recorded spend is 0.",
            "Confirm free/local inference; otherwise the cost column may not be populated.")

    if spend is not None and spend >= 100_000:  # >= $1000
        add("medium", "high-cumulative-spend", "Cumulative spend is large",
            f"Total recorded spend is {spend} cents (>= $1000).",
            "Verify each line against provider invoices; large totals are worth reconciling.")

    # goals with no recent turns => stall suspicion
    goals = tables.get("goals")
    n_goals = _as_int((goals or {}).get("rows")) if isinstance(goals, dict) else None
    if n_goals and n_goals > 0 and n_turns == 0:
        add("medium", "goals-without-turns", "Goals exist but no turns recorded",
            f"{n_goals} goal(s) present and 0 turns.",
            "The agent may be stalled at startup, or turns live in another table.")

    # any table that exists but is empty is cheap to flag as info
    empty = [k for k, v in tables.items()
             if isinstance(v, dict) and _as_int(v.get("rows")) == 0]
    if empty:
        add("info", "empty-tables", "One or more tables are empty",
            "Empty tables: " + ", ".join(sorted(empty)[:10]) + ("…" if len(empty) > 10 else ""),
            "Expected for a fresh agent; otherwise check ingestion.")

    if not any(f["severity"] in ("high", "medium") for f in out):
        add("info", "no-major-issues", "No high/medium findings",
            "Automated checks found nothing abnormal in the accessible tables.",
            "This is not a clean bill of health — see scope limits below.")

    out.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 9), f["code"]))
    return out

SCOPE_LIMITS = [
    "Reads only accessible SQLite tables; data in files, other DBs, or remote systems is invisible.",
    "Cannot confirm that recorded amounts match provider invoices.",
    "Absence of findings is not proof of correctness.",
]

def to_markdown(findings, include_scope=True):
    lines = ["## Findings", ""]
    if not findings:
        lines.append("_No findings._")
    for f in findings:
        lines.append(f"- **[{f['severity'].upper()}]** {f['title']} — {f['detail']}")
        lines.append(f"  - check: {f['check']}")
    if include_scope:
        lines += ["", "### Scope limits", ""] + [f"- {s}" for s in SCOPE_LIMITS]
    return "\n".join(lines) + "\n"

def _selftest():
    import sys
    fails = []
    def check(n, c):
        print(f"  [{'PASS' if c else 'FAIL'}] {n}")
        if not c: fails.append(n)
    r = analyze({"tables": {"inference_costs": {"rows": 1, "cost_cents": 500},
                            "turns": {"rows": 10}, "goals": {"rows": 2}}})
    check("normal report -> no high", not any(f["severity"] == "high" for f in r))
    r2 = analyze({"tables": {"costs": {"rows": 0, "cost_cents": 500}, "turns": {"rows": 5}}})
    check("spend-without-rows detected", any(f["code"] == "spend-without-rows" for f in r2))
    r3 = analyze({"tables": {"goals": {"rows": 3}, "turns": {"rows": 0}, "costs": {"rows": 0}}})
    check("goals-without-turns detected", any(f["code"] == "goals-without-turns" for f in r3))
    check("empty report is high", analyze({})[0]["severity"] == "high")
    check("sorted most-severe first",
          [f["severity"] for f in analyze({"tables": {"a": {"rows": 0}}})][0] in ("info", "high", "medium", "low"))
    r4 = analyze({"tables": {"turns": 7, "goals": 2}})  # int-valued tables must not crash
    check("int-valued tables don't crash", isinstance(r4, list))
    md = to_markdown(r)
    check("markdown has scope limits", "Scope limits" in md and "not proof" in md)
    print()
    if fails:
        print(f"RESULT: FAIL ({len(fails)}) -> {fails}"); sys.exit(1)
    print("RESULT: ALL PASS")

if __name__ == "__main__":
    _selftest()
