#!/usr/bin/env python3
"""snapshot_diff — compare two agent state DBs and report what changed.

Why: an audit report answers "what is the state now?" A diff answers the more
useful operational question "what changed since yesterday, and did it cost
anything?" Fully read-only; both DBs are opened immutable so neither can be
modified by the tool.

Usage:
    python3 tools/snapshot_diff.py OLD.db NEW.db [--json]
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys

def _ro(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

def _tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

def _count(conn, t):
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    except sqlite3.Error:
        return None

def _scalar(conn, t, col):
    try:
        v = conn.execute(f'SELECT COALESCE(SUM("{col}"),0) FROM "{t}"').fetchone()[0]
        return int(v) if v is not None else 0
    except sqlite3.Error:
        return None

def _goals(conn):
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT id, status FROM goals")}
    except sqlite3.Error:
        return {}

def diff(old_path, new_path, spend_cols=("cost_cents",)):
    a, b = _ro(old_path), _ro(new_path)
    out = {"old": old_path, "new": new_path, "tables": {}, "goals": {}, "warnings": []}
    ta, tb = _tables(a), _tables(b)
    for t in sorted(ta | tb):
        if t not in ta:
            out["tables"][t] = {"status": "added", "new_rows": _count(b, t)}; out["warnings"].append(f"table {t} added")
        elif t not in tb:
            out["tables"][t] = {"status": "removed", "old_rows": _count(a, t)}; out["warnings"].append(f"table {t} removed")
        else:
            ca, cb = _count(a, t), _count(b, t)
            entry = {"status": "changed" if ca != cb else "same",
                     "old_rows": ca, "new_rows": cb, "delta_rows": (cb - ca) if None not in (ca, cb) else None}
            sums = {}
            for col in spend_cols:
                sa, sb = _scalar(a, t, col), _scalar(b, t, col)
                if sa is not None and sb is not None:
                    sums[col] = {"old": sa, "new": sb, "delta": sb - sa}
            if sums:
                entry["sums"] = sums
            out["tables"][t] = entry
    ga, gb = _goals(a), _goals(b)
    for gid in sorted(set(ga) | set(gb)):
        if gid not in ga: out["goals"][gid] = {"change": "added", "status": gb[gid]}
        elif gid not in gb: out["goals"][gid] = {"change": "removed", "status": ga[gid]}
        elif ga[gid] != gb[gid]: out["goals"][gid] = {"change": "status", "old": ga[gid], "new": gb[gid]}
    a.close(); b.close()
    return out

def to_markdown(d):
    L = ["# State diff", f"_old: `{d['old']}`_", f"_new: `{d['new']}`_", "", "## Tables"]
    for t, e in d["tables"].items():
        if e["status"] == "same" and not e.get("sums"):
            L.append(f"- **{t}**: unchanged ({e['new_rows']} rows)")
            continue
        bits = [f"**{t}**: {e['status']}"]
        if e.get("delta_rows") is not None:
            bits.append(f"rows {e['old_rows']}→{e['new_rows']} (Δ{e['delta_rows']:+d})")
        for col, s in (e.get("sums") or {}).items():
            bits.append(f"{col} {s['old']}→{s['new']} (Δ{s['delta']:+d})")
        L.append("- " + "; ".join(bits))
    if d["goals"]:
        L += ["", "## Goal changes"]
        for gid, ch in d["goals"].items():
            if ch["change"] == "status": L.append(f"- `{gid}`: {ch['old']} → {ch['new']}")
            else: L.append(f"- `{gid}`: {ch['change']} ({ch.get('status')})")
    if d["warnings"]:
        L += ["", "## Warnings"] + [f"- {w}" for w in d["warnings"]]
    L += ["", "_Read-only comparison. No settlement or revenue is implied by row counts._"]
    return "\n".join(L) + "\n"

def main(argv=None):
    ap = argparse.ArgumentParser(prog="snapshot_diff", description="Read-only diff of two agent state DBs.")
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="PATH")
    a = ap.parse_args(argv)
    d = diff(a.old, a.new)
    if a.json:
        print(json.dumps(d, indent=2))
    else:
        print(to_markdown(d), end="")
    if a.html:
        md = to_markdown(d)
        open(a.html, "w").write("<!doctype html><meta charset=utf-8><title>State diff</title><pre>"
                                + md.replace("&","&amp;").replace("<","&lt;") + "</pre>")
        print(f"wrote {a.html}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
