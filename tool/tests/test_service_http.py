#!/usr/bin/env python3
"""test_service_http — real HTTP integration test for audit_service.

Unit tests call handlers directly. This boots the *actual* service on a
localhost port and speaks HTTP to it, so it catches bugs that direct calls
can't: wrong status codes on the wire, malformed JSON, missing headers, and
an unpaid/unverified request accidentally returning report bytes.

Read-only and local-only: binds 127.0.0.1, makes no on-chain call.

Honesty contract under test (fail-closed):
  * no X-PAYMENT header            -> 402, no report bytes
  * malformed / missing-signature   -> 402, no report bytes
  * amount below price              -> 402, no report bytes
  * FORGED signature, valid amount  -> 402, no report bytes  (the key regression)
  * settlement confirmed 'settled'  -> 200 with report        (happy path, monkeypatched)
  * unverified + AUDIT_ALLOW_UNVERIFIED=1 (explicit demo) -> 200, labelled unverified
"""
import base64, json, os, socket, sys, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import audit_service as S

fails = []
def check(name, cond, xtra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {xtra}" if xtra and not cond else ""))
    if not cond:
        fails.append(name)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def get(path, headers=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)

def _is_json(b):
    try: json.loads(b); return True
    except Exception: return False

def proof_header(payload):
    return {"X-PAYMENT": base64.b64encode(json.dumps(payload).encode()).decode()}

def leaks_report(body):
    return b"## " in body or b"Findings" in body or b"Audit" in body

def main():
    global PORT
    PORT = free_port()
    db = os.path.join(ROOT, "workspace", "_http_test.db")
    if os.path.exists(db): os.remove(db)
    import sqlite3
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE goals(id TEXT,status TEXT); CREATE TABLE turns(id TEXT);")
    c.execute("INSERT INTO goals VALUES('g1','active')"); c.execute("INSERT INTO turns VALUES('t1')")
    c.commit(); c.close()
    S.DB = db

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), S.H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        # 1) health
        st, body, hdrs = get("/health")
        check("health endpoint responds without 5xx", st < 500, f"status={st}")

        # 2) unpaid report -> MUST be 402
        st, body, hdrs = get("/report")
        check("unpaid /report returns 402", st == 402, f"status={st}")
        check("402 body is valid JSON", _is_json(body), body[:80].decode(errors="replace"))
        j = json.loads(body) if _is_json(body) else {}
        check("402 advertises payment requirements", bool(j.get("accepts")), str(j)[:80])
        acc = (j.get("accepts") or [{}])[0]
        check("requirements name a payTo", bool(acc.get("payTo")), str(acc)[:80])
        check("requirements name the USDC mint", "assetMint" in json.dumps(acc))
        check("402 leaks no report content", not leaks_report(body))

        # 3) malformed header -> 402, no report
        st, body, _ = get("/report", {"X-PAYMENT": "!!!not-base64!!!"})
        check("malformed proof -> 402", st == 402, f"status={st}")
        check("malformed proof leaks no report", not leaks_report(body))

        # 4) well-formed but NO signature -> 402, no report
        st, body, _ = get("/report", proof_header({"amount": S.PRICE}))
        check("missing signature -> 402", st == 402, f"status={st}")
        check("missing signature leaks no report", not leaks_report(body))

        # 5) amount below price -> 402, no report
        st, body, _ = get("/report", proof_header({"signature": "a"*64, "amount": max(0, S.PRICE - 1)}))
        check("amount below price -> 402", st == 402, f"status={st}")
        check("underpayment leaks no report", not leaks_report(body))

        # 6) THE REGRESSION: forged signature with a *valid* amount must NOT be honored
        st, body, _ = get("/report", proof_header({"signature": "FORGED_" + "0"*60, "amount": S.PRICE}))
        check("forged proof w/ valid amount rejected (402/403, not 200)", st in (402, 403), f"status={st}")
        check("forged proof leaks no report", not leaks_report(body))

        # 7) happy path: settlement confirmed 'settled' -> 200 with report (no network)
        real_settle = S.settle
        S.settle = lambda proof: ("settled", "test-confirmed")
        st, body, _ = get("/report.json", proof_header({"signature": "test", "amount": S.PRICE}))
        check("confirmed settlement -> 200", st == 200, f"status={st}")
        jb = json.loads(body) if _is_json(body) else {}
        check("confirmed settlement labelled settled", jb.get("payment", {}).get("status") == "settled", str(jb.get("payment")))
        S.settle = real_settle

        # 8) unverified by default -> 402 (fail-closed); only explicit demo allows serve
        S.settle = lambda proof: ("unverified", "no-rpc")
        S.ALLOW_UNVERIFIED = False
        st, body, _ = get("/report", proof_header({"signature": "x", "amount": S.PRICE}))
        check("unverified + default policy -> 402 (fail closed)", st == 402, f"status={st}")
        check("unverified default leaks no report", not leaks_report(body))
        # explicit demo opt-in still serves, truthfully labelled
        S.ALLOW_UNVERIFIED = True
        st, body, _ = get("/report.json", proof_header({"signature": "x", "amount": S.PRICE}))
        check("unverified + explicit demo flag -> 200", st == 200, f"status={st}")
        jb = json.loads(body) if _is_json(body) else {}
        check("demo serve still labelled unverified", jb.get("payment", {}).get("status") == "unverified")
        S.ALLOW_UNVERIFIED = False
        S.settle = real_settle
    finally:
        srv.shutdown(); srv.server_close()
        if os.path.exists(db): os.remove(db)

    print()
    if fails:
        print(f"RESULT: FAIL ({len(fails)}) -> {fails}")
        return 1
    print("RESULT: ALL PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
