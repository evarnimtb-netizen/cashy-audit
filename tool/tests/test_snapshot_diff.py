#!/usr/bin/env python3
import os, sqlite3, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import snapshot_diff as SD
FAILS = []
def check(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' — '+x) if x and not c else ''}")
    if not c: FAILS.append(n)

def mk(path, costs, turns, goal_status):
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE goals(id TEXT, status TEXT); CREATE TABLE inference_costs(id TEXT, cost_cents INT); CREATE TABLE turns(id TEXT);")
    for i, v in enumerate(costs): c.execute("INSERT INTO inference_costs VALUES(?,?)", (f"c{i}", v))
    for i in range(turns): c.execute("INSERT INTO turns VALUES(?)", (f"t{i}",))
    c.execute("INSERT INTO goals VALUES('g1',?)", (goal_status,)); c.commit(); c.close()

d = tempfile.mkdtemp()
old = os.path.join(d, "old.db"); new = os.path.join(d, "new.db")
mk(old, [10, 20], 3, "active"); mk(new, [10, 20, 30], 5, "complete")
r = SD.diff(old, new)
check("row delta computed", r["tables"]["turns"]["delta_rows"] == 2, str(r["tables"]["turns"]))
check("spend delta computed", r["tables"]["inference_costs"]["sums"]["cost_cents"]["delta"] == 30, str(r["tables"]["inference_costs"]))
check("goal status change detected", r["goals"]["g1"] == {"change": "status", "old": "active", "new": "complete"}, str(r["goals"]))
md = SD.to_markdown(r)
check("markdown mentions delta", "Δ+30" in md and "→" in md, md[:200])
# unchanged case
r2 = SD.diff(new, new)
check("identical DBs report unchanged", r2["tables"]["turns"]["status"] == "same" and not r2["goals"], str(r2))
# read-only proof: the tool must not alter either file
before = os.path.getmtime(old); SD.diff(old, new)
check("source DBs untouched", os.path.getmtime(old) == before)
print()
if FAILS:
    print(f"RESULT: FAIL ({len(FAILS)}) -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")
