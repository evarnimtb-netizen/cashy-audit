#!/usr/bin/env python3
"""test_receipt_e2e.py — end-to-end: seller emission <-> buyer verification.

Starts the REAL audit_service in demo mode (AUDIT_ALLOW_UNVERIFIED=1, no RPC, so
settlement is honestly "unverified"), fetches /report.json and /report, then runs
tools/verify_receipt.py against each. Asserts:

  json mode    : integrity ok, settlement unverified, exit 2
  bytes mode   : integrity ok via X-RECEIPT header, exit 2
  tamper.json  : flip a byte -> integrity FAIL, exit 1
  tamper.md    : flip a byte -> integrity FAIL, exit 1
  no RPC       : settlement NEVER reported "settled"
"""
import base64, json, os, subprocess, sys, tempfile, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import audit_service as svc  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

FAIL = 0


def check(name, cond, extra=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAIL += 1


# --- demo config: no RPC, allow unverified so we exercise the 200 path ---
os.environ["AUDIT_ALLOW_UNVERIFIED"] = "1"
os.environ.pop("SOLANA_RPC_URL", None)
os.environ["AUDIT_HOST"] = "127.0.0.1"
os.environ["AUDIT_PORT"] = "8799"
svc.ALLOW_UNVERIFIED = True
svc.HOST, svc.PORT = "127.0.0.1", 8799

# a real state DB must exist for collect(); use the sandbox default or tmp
tmpdb = tempfile.mktemp(suffix=".db")
if not os.path.exists(svc.DB):
    # create a minimal sqlite so cashy_report.collect can read *something*
    import sqlite3
    con = sqlite3.connect(tmpdb)
    con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, detail TEXT)")
    con.execute("INSERT INTO events (ts,kind,detail) VALUES (0,'demo','e2e')")
    con.commit(); con.close()
    svc.DB = tmpdb

srv = ThreadingHTTPServer((svc.HOST, svc.PORT), svc.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = f"http://{svc.HOST}:{svc.PORT}"

# any non-empty signature; proof must carry amount >= PRICE
proof = base64.b64encode(json.dumps(
    {"signature": "3xDEMOsig111111111111111111111111111111111111",
     "amount": str(svc.PRICE)}).encode()).decode()
HDRS = {"X-PAYMENT": proof}


def get(path):
    req = urllib.request.Request(BASE + path, headers=HDRS)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, dict(r.headers), r.read()


print("test_receipt_e2e — seller emission <-> buyer verification")

# ---- json mode ----
st, _, body = get("/report.json")
check("json: 200", st == 200, f"got {st}")
d = tempfile.mkdtemp()
p_json = os.path.join(d, "report.json")
open(p_json, "wb").write(body)
obj = json.loads(body)
check("json: embedded receipt present", isinstance(obj.get("receipt"), dict))
check("json: receipt has signature",
      obj.get("receipt", {}).get("payment", {}).get("signature") == "3xDEMOsig111111111111111111111111111111111111")

rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_receipt.py"),
                     "--json-report", p_json, "--json"], capture_output=True, text=True)
v = json.loads(rc.stdout)
check("json: integrity ok", v["integrity"] == "ok", str(v["reasons"]))
check("json: settlement unverified (no RPC)", v["settlement"] == "unverified")
check("json: exit 2", rc.returncode == 2, f"got {rc.returncode}")

# ---- tamper json -> integrity fail ----
t_json = os.path.join(d, "tampered.json")
o2 = json.loads(body); o2["receipt"]["payment"]["amount_atomic"] = 999
# tamper the *report* content instead: change a real field
o2["turn_count"] = (o2.get("turn_count") or 0) + 12345
open(t_json, "w").write(json.dumps(o2))
rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_receipt.py"),
                     "--json-report", t_json, "--json"], capture_output=True, text=True)
v = json.loads(rc.stdout)
check("json tamper: integrity FAIL", v["integrity"] == "fail")
check("json tamper: exit 1", rc.returncode == 1, f"got {rc.returncode}")

# ---- bytes mode (markdown + X-RECEIPT header) ----
st, hdrs, body = get("/report")
check("md: 200", st == 200, f"got {st}")
check("md: X-RECEIPT header present", bool(hdrs.get("X-RECEIPT")))
p_md = os.path.join(d, "report.md")
open(p_md, "wb").write(body)
rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_receipt.py"),
                     "--report", p_md, "--receipt-from-header", hdrs.get("X-RECEIPT", ""),
                     "--json"], capture_output=True, text=True)
v = json.loads(rc.stdout)
check("md: integrity ok", v["integrity"] == "ok", str(v["reasons"]))
check("md: settlement unverified", v["settlement"] == "unverified")
check("md: exit 2", rc.returncode == 2, f"got {rc.returncode}")

# ---- tamper markdown -> integrity fail ----
p_md2 = os.path.join(d, "report_tampered.md")
open(p_md2, "wb").write(body + b"\ntampered line\n")
rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_receipt.py"),
                     "--report", p_md2, "--receipt-from-header", hdrs.get("X-RECEIPT", ""),
                     "--json"], capture_output=True, text=True)
v = json.loads(rc.stdout)
check("md tamper: integrity FAIL", v["integrity"] == "fail")
check("md tamper: exit 1", rc.returncode == 1, f"got {rc.returncode}")

# ---- schema endpoint ----
st, _, body = get("/receipt-schema")
check("schema endpoint: 200", st == 200)
check("schema endpoint: names buyer tool", b"verify_receipt.py" in body)

srv.shutdown()
if os.path.exists(tmpdb):
    try: os.unlink(tmpdb)
    except Exception: pass

print(f"RESULT: {'ALL PASS' if FAIL == 0 else str(FAIL) + ' FAIL'}")
raise SystemExit(1 if FAIL else 0)
