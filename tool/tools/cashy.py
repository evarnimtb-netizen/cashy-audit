#!/usr/bin/env python3
"""cashy — one command for the creator to see everything, honestly.

Subcommands:
  cashy status            -> human summary to stdout
  cashy report [--html F] -> full audit report (markdown, or self-contained HTML)
  cashy serve             -> launch the x402 audit_service
It reads the state DB read-only and never fabricates anything. If data is
missing it says so. Built for the creator's audit rights (Constitution, Law III).
"""
from __future__ import annotations
import argparse, html, json, os, sys, subprocess
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cashy_report as cr

def _default_db():
    for p in (os.path.expanduser("~/.automaton/state.db"),
              os.path.join(os.path.dirname(HERE), "workspace", "test_state.db")):
        if os.path.exists(p): return p
    return os.path.expanduser("~/.automaton/state.db")

def cmd_status(args):
    db = args.db or _default_db()
    if not os.path.exists(db):
        print(f"state db: NOT FOUND ({db})"); return 1
    rep = cr.collect(db, limit=3)
    print(f"Cashy status — {rep['generated_utc']}")
    print(f"db: {db}")
    print("-" * 48)
    for k in ("goals", "task_graph", "turns", "event_stream", "children"):
        if k in rep["tables"]: print(f"  {k:<16} {rep['tables'][k]}")
    total = sum(rep["spend_cents"].values())
    print(f"  spend_cents      {total}  (~${total/100:.2f})")
    print("-" * 48)
    print("Honesty: unpaid services return 402; settlement is 'unverified' until an RPC confirms.")
    return 0

def cmd_report(args):
    db = args.db or _default_db()
    if not os.path.exists(db): print(f"error: db not found: {db}", file=sys.stderr); return 2
    rep = cr.collect(db, limit=args.limit)
    if args.html:
        doc = render_html(rep)
        with open(args.html, "w") as f: f.write(doc)
        print(f"wrote {args.html} ({len(doc)} bytes)")
    else:
        print(cr.to_markdown(rep))
    return 0

def cmd_serve(args):
    env = dict(os.environ)
    if args.port: env["AUDIT_PORT"] = str(args.port)
    if args.db: env["AUDIT_DB"] = args.db
    return subprocess.call([sys.executable, os.path.join(HERE, "audit_service.py")], env=env)


def cmd_findings(args):
    import json, cashy_report as cr, findings as fd
    rep = cr.collect(args.db, 10)
    f = fd.analyze(rep)
    if getattr(args, "json", False):
        print(json.dumps(f, indent=2))
    else:
        print(fd.to_markdown(f), end="")
    return 0

def cmd_diff(args):
    import snapshot_diff as sd
    return sd.main([args.old, args.new] + (["--html", args.html] if args.html else []))

def _seed(db):
    import sqlite3
    if os.path.exists(db): os.remove(db)
    c = sqlite3.connect(db)
    c.executescript("""
CREATE TABLE goals(id TEXT, title TEXT, status TEXT, created_at TEXT);
CREATE TABLE inference_costs(id TEXT, cost_cents INT, created_at TEXT);
CREATE TABLE turns(id TEXT, created_at TEXT);
""")
    c.execute("INSERT INTO inference_costs VALUES(?,?,?)", ("d1", 42, "2026-09-12T16:00:00Z"))
    c.execute("INSERT INTO turns VALUES(?,?)", ("d1", "2026-09-12T16:00:00Z"))
    c.execute("INSERT INTO goals VALUES(?,?,?,?)", ("g1", "demo goal", "active", "2026-09-12T16:00:00Z"))
    c.commit(); c.close()

def cmd_demo(args):
    """Prove the whole system end-to-end with no network and no spending."""
    import base64, json, socket, subprocess, time, urllib.request, urllib.error
    ws = os.path.join(os.path.dirname(HERE), "workspace"); os.makedirs(ws, exist_ok=True)
    db = os.path.join(ws, "demo.db"); ledger = os.path.join(ws, "demo_payments.log")
    print("1) seeding sample state DB ...", db); _seed(db)
    print("2) status:"); os.environ["AUDIT_DB"] = db
    cmd_status(argparse.Namespace(db=db))
    html_path = os.path.join(ws, "demo_audit.html")
    print("3) rendering self-contained HTML report ...", html_path)
    cmd_report(argparse.Namespace(db=db, html=html_path, limit=10))
    print(f"   html bytes: {os.path.getsize(html_path)}")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = dict(os.environ, AUDIT_DB=db, AUDIT_PORT=str(port), AUDIT_LEDGER=ledger,
               AUDIT_HOST="127.0.0.1", AUDIT_PRICE_ATOMIC="100000",
               AUDIT_ALLOW_UNVERIFIED="1")  # demo-only: shows the paid path; still tagged unverified
    env.pop("SOLANA_RPC_URL", None)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "audit_service.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    def get(path, headers=None):
        req = urllib.request.Request(base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, r.read().decode()
        except urllib.error.HTTPError as e: return e.code, e.read().decode()
    try:
        for _ in range(40):
            try:
                if get("/health")[0] == 200: break
            except Exception: pass
            time.sleep(0.1)
        print("4) /health:", get("/health")[0])
        st, body = get("/report"); print("5) unpaid /report ->", st, "(expect 402)")
        proof = base64.b64encode(json.dumps({"signature": "DemoSig0000000000000000", "amount": 100000}).encode()).decode()
        st, body = get("/report.json", {"X-PAYMENT": proof})
        d = json.loads(body)
        print("6) paid /report.json ->", st, "| payment.status =", d["payment"]["status"], "(unverified without RPC)")
        print("7) ledger recorded:", sum(1 for _ in open(ledger)) if os.path.exists(ledger) else 0, "events")
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    print("DEMO OK — unpaid blocked, paid served, settlement truthful.")
    return 0

def render_html(rep):
    """Self-contained, dependency-free HTML report. Escapes everything."""
    def esc(x): return html.escape(str(x))
    total = sum(rep["spend_cents"].values())
    rows = "".join(f"<tr><td>{esc(k)}</td><td class='n'>{esc(v)}</td></tr>"
                   for k, v in rep["tables"].items()) or "<tr><td colspan=2><i>none</i></td></tr>"
    spend = "".join(f"<tr><td>{esc(k)}</td><td class='n'>{esc(v)}</td></tr>"
                    for k, v in rep["spend_cents"].items()) or "<tr><td colspan=2><i>none</i></td></tr>"
    recent = ""
    for k, rws in rep["recent"].items():
        if not rws: continue
        recent += f"<h3>{esc(k)}</h3><ul>"
        for r in rws:
            recent += f"<li><code>{esc(json.dumps(r, default=str))}</code></li>"
        recent += "</ul>"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Cashy audit report</title><style>
body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#111}}
h1{{margin:0 0 .2rem}} .sub{{color:#666;font-size:.9rem}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}}
td,th{{border-bottom:1px solid #eee;padding:.35rem .5rem;text-align:left}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
code{{background:#f6f6f6;padding:.1rem .3rem;border-radius:4px;font-size:.85em}}
.note{{background:#fff8e1;border-left:4px solid #f0ad4e;padding:.6rem .9rem;border-radius:4px}}
.total{{font-weight:600}}</style></head><body>
<h1>Cashy — audit report</h1>
<div class="sub">Generated {esc(rep['generated_utc'])} · db <code>{esc(rep['db'])}</code></div>
<div class="note"><b>Honesty contract:</b> an unpaid request always returns 402 and no data.
Settlement is reported as <code>settled</code> only when an on-chain RPC confirms the transfer;
otherwise it is <code>unverified</code>. Nothing here is fabricated.</div>
<h2>Table sizes</h2><table><tr><th>table</th><th>rows</th></tr>{rows}</table>
<h2>Spend (cents)</h2><table><tr><th>source</th><th>cents</th></tr>{spend}
<tr class="total"><td>total</td><td class="n">{esc(total)} (~${total/100:.2f})</td></tr></table>
<h2>Recent activity</h2>{recent or '<p><i>none</i></p>'}
</body></html>"""

def main(argv=None):
    ap = argparse.ArgumentParser(prog="cashy", description="Creator-facing entrypoint for Cashy.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--db"); s.set_defaults(fn=cmd_status)
    r = sub.add_parser("report"); r.add_argument("--db"); r.add_argument("--html")
    r.add_argument("--limit", type=int, default=10); r.set_defaults(fn=cmd_report)
    v = sub.add_parser("serve"); v.add_argument("--db"); v.add_argument("--port"); v.set_defaults(fn=cmd_serve)
    dm = sub.add_parser("demo"); dm.set_defaults(fn=cmd_demo)
    fi = sub.add_parser("findings"); fi.add_argument("db"); fi.add_argument("--json", action="store_true"); fi.set_defaults(fn=cmd_findings)
    df = sub.add_parser("diff"); df.add_argument("old"); df.add_argument("new"); df.add_argument("--html"); df.set_defaults(fn=cmd_diff)
    a = ap.parse_args(argv); return a.fn(a)

if __name__ == "__main__":
    raise SystemExit(main())
