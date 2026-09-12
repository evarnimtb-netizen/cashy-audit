#!/usr/bin/env python3
"""End-to-end test for audit_service + cashy_report + settlement.

Asserts the honesty contract:
  1. /health is free and 200.
  2. /report without payment is 402 and leaks no report body.
  3. The 402 body carries a real x402 `accepts` block with payTo/network/price.
  4. FAIL-CLOSED: an unverified proof (no RPC, so settlement can't be
     confirmed) is NOT served the report -- it gets 402 back. Serving an
     unverified/forged proof would be a real leak, so the default is closed.
  4b. With AUDIT_ALLOW_UNVERIFIED=1 (explicit demo mode only) the paid path is
     served (200) and truthfully tagged payment.status == "unverified".
  5. settlement.verify_tx refuses to claim "settled" without an RPC.
  6. The ledger records every 402 and every paid hit.
Runs on a private port, writes only inside the sandbox dir, cleans up after.
"""
import base64, json, os, socket, sqlite3, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import settlement  # noqa: E402

FAILS = []
def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra and not cond else ''}")
    if not cond: FAILS.append(name)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def make_db(path):
    c = sqlite3.connect(path)
    c.executescript("""
CREATE TABLE IF NOT EXISTS inference_costs(id TEXT, cost_cents INT, created_at TEXT);
CREATE TABLE IF NOT EXISTS turns(id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS goals(id TEXT, title TEXT, status TEXT, created_at TEXT);
""")
    c.execute("INSERT INTO inference_costs VALUES(?,?,?)", ("a", 7, "2026-09-12T15:00:00Z"))
    c.execute("INSERT INTO inference_costs VALUES(?,?,?)", ("b", 5, "2026-09-12T15:05:00Z"))
    c.execute("INSERT INTO turns VALUES(?,?)", ("t1", "2026-09-12T15:00:00Z"))
    c.commit(); c.close()

def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def main():
    stamp = str(int(time.time()))
    db = os.path.join(ROOT, "workspace", f"test_{stamp}.db")
    ledger = os.path.join(ROOT, "workspace", f"payments_{stamp}.log")
    make_db(db)
    port = free_port()
    env = dict(os.environ, AUDIT_DB=db, AUDIT_PORT=str(port), AUDIT_LEDGER=ledger,
               AUDIT_HOST="127.0.0.1", AUDIT_PRICE_ATOMIC="100000")
    env.pop("SOLANA_RPC_URL", None)
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "audit_service.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(40):
            try:
                if get(base + "/health")[0] == 200: break
            except Exception: pass
            time.sleep(0.1)

        st, body = get(base + "/health")
        check("health is 200 and free", st == 200, f"got {st}")

        st, body = get(base + "/report")
        check("unpaid report -> 402", st == 402, f"got {st}")
        check("402 body leaks no report", "Cashy audit report" not in body)

        acc = json.loads(body)["accepts"][0]
        check("accepts has payTo", bool(acc.get("payTo")))
        check("accepts network == solana", acc.get("network") == "solana")
        check("accepts price == 100000", acc.get("maxAmountRequired") == "100000")

        proof = base64.b64encode(json.dumps(
            {"signature": "SmokeSigABCDEF1234567890", "amount": 100000}).encode()).decode()
        # FAIL-CLOSED default: unverified proof must NOT receive the report.
        st, body = get(base + "/report.json", {"X-PAYMENT": proof})
        check("unverified proof fails closed (402, not 200)", st == 402, f"got {st}")
        check("unverified proof leaks no report", "Cashy audit report" not in body and "spend_cents" not in body)
        # DEMO MODE: an explicit AUDIT_ALLOW_UNVERIFIED=1 opt-in serves the paid
        # path (so the offline demo can show 402->200), still tagged unverified.
        dport = free_port()
        denv = dict(env, AUDIT_ALLOW_UNVERIFIED="1", AUDIT_PORT=str(dport))
        dproc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "audit_service.py")],
                                 env=denv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dbase = f"http://127.0.0.1:{dport}"
        try:
            for _ in range(40):
                try:
                    if get(dbase + "/health")[0] == 200: break
                except Exception: pass
                time.sleep(0.1)
            st, dbody = get(dbase + "/report.json", {"X-PAYMENT": proof})
            check("demo flag serves report -> 200", st == 200, f"got {st}")
            dd = json.loads(dbody)
            check("demo serve tagged unverified (no RPC)", dd["payment"]["status"] == "unverified",
                  f"got {dd.get('payment')}")
            check("report contains spend", dd.get("spend_cents", {}).get("inference_costs") == 12,
                  f"got {dd.get('spend_cents')}")
        finally:
            dproc.terminate()
            try: dproc.wait(timeout=5)
            except Exception: dproc.kill()

        status, detail = settlement.verify_tx("ABC", pay_to="X", min_amount=1, rpc_url=None)
        check("settlement refuses to claim settled without RPC", status == "unverified")

        st, _ = get(base + "/report")  # another unpaid, to log
        log = open(ledger).read() if os.path.exists(ledger) else ""
        check("ledger logs the 402", '"kind": "402"' in log)
        check("ledger logs the paid hit", '"kind": "paid"' in log)
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()

    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)}) -> {FAILS}"); return 1
    print("RESULT: ALL PASS"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
