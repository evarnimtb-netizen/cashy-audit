#!/usr/bin/env python3
"""cashy_report — read-only, honest audit report over a Cashy/Automaton state DB.

Why: the creator holds full audit rights (Constitution, Law III). This turns an
opaque state.db into one readable summary. stdlib-only, strictly read-only,
degrades gracefully when tables/columns are missing.
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys
from datetime import datetime, timezone

DEFAULT_DB = os.path.expanduser("~/.automaton/state.db")
TABLES = {
    "goals": "id,title,status,created_at", "task_graph": "id,title,status",
    "event_stream": "id,type,created_at", "wake_events": "id,created_at",
    "inference_costs": "id,cost_cents,created_at", "spend_tracking": "id,amount_cents,created_at",
    "turns": "id,created_at", "heartbeat_history": "id,status,created_at",
    "transactions": "id,amount_cents,created_at", "children": "id,name,state",
}

def _exists(con, n):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (n,)).fetchone() is not None
def _cols(con, n):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{n}")')]
def _count(con, n):
    try: return con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
    except sqlite3.Error: return None
def _recent(con, n, cols, limit):
    have = _cols(con, n); use = [c for c in cols.split(",") if c in have]
    if not use: return []
    q = f'SELECT {",".join(use)} FROM "{n}"'
    order = "created_at" if "created_at" in have else ("id" if "id" in have else None)
    if order: q += f' ORDER BY "{order}" DESC'
    try: return [dict(zip(use, r)) for r in con.execute(q + f" LIMIT {int(limit)}")]
    except sqlite3.Error: return []
def _sum(con, n, col):
    if col not in _cols(con, n): return None
    try: return con.execute(f'SELECT SUM("{col}") FROM "{n}"').fetchone()[0]
    except sqlite3.Error: return None

def collect(db, limit=5):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rep = {"db": os.path.basename(str(db)), "generated_utc": datetime.now(timezone.utc).isoformat(),
           "tables": {}, "spend_cents": {}, "recent": {}}
    for n, cols in TABLES.items():
        if _exists(con, n):
            rep["tables"][n] = _count(con, n); rep["recent"][n] = _recent(con, n, cols, limit)
    for n, c in (("inference_costs","cost_cents"),("spend_tracking","amount_cents"),("transactions","amount_cents")):
        s = _sum(con, n, c)
        if s is not None: rep["spend_cents"][n] = s
    con.close(); return rep

def to_markdown(rep):
    import findings as _f
    _base = _to_markdown_base(rep)
    return _base + "\n" + _f.to_markdown(_f.analyze(rep))

def _to_markdown_base(rep):
    L = ["# Cashy audit report", f"_Generated: {rep['generated_utc']}_", f"DB: `{rep['db']}`", "", "## Table sizes"]
    L += [f"- **{k}**: {v}" for k, v in rep["tables"].items()] or ["_No known tables present._"]
    L += ["", "## Spend (cents)"]
    if rep["spend_cents"]:
        L += [f"- {k}: {v}" for k, v in rep["spend_cents"].items()]
        t = sum(rep["spend_cents"].values()); L.append(f"- **total: {t}** (~${t/100:.2f})")
    else: L.append("_No spend columns found._")
    L += ["", "## Recent activity"]
    for k, rows in rep["recent"].items():
        if rows:
            L.append(f"### {k}"); L += [f"- {json.dumps(r, default=str)}" for r in rows]
    return "\n".join(L)

def main(argv=None):
    ap = argparse.ArgumentParser(prog="cashy_report", description="Read-only audit report over a Cashy state DB.")
    ap.add_argument("--db", default=DEFAULT_DB); ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=5); a = ap.parse_args(argv)
    if not os.path.exists(a.db): print(f"error: db not found: {a.db}", file=sys.stderr); return 2
    rep = collect(a.db, a.limit)
    print(json.dumps(rep, indent=2, default=str) if a.json else to_markdown(rep)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
