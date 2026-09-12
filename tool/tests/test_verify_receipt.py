#!/usr/bin/env python3
"""test_verify_receipt.py — buyer-side receipt verifier must be fail-closed.

Cases:
  1. matching hash + no RPC          -> integrity ok, settlement unverified, exit 2
  2. tampered report                 -> integrity fail, exit 1
  3. matching hash + confirmed tx    -> settled, ok, exit 0  (verify_tx stubbed)
  4. receipt missing sha256          -> integrity fail
  5. missing payment fields + no RPC -> settlement unverified (never claimed settled)
"""
import hashlib, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import verify_receipt as vr  # noqa: E402

FAIL = 0


def check(name, cond, extra=""):
    global FAIL
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAIL += 1


def write_report(text):
    fd, p = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return p


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


print("test_verify_receipt — buyer-side, fail-closed")

rep = write_report("# Audit report\nbalance: 0\ntruthful: yes\n")
good_hash = sha(rep)
PAY_TO = "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats"

# 1. integrity ok, no RPC -> unverified (honest)
rcpt = {"report": {"sha256": good_hash},
        "payment": {"signature": "SIG", "pay_to": PAY_TO, "amount_atomic": 100000}}
v = vr.verify(rcpt, rep, rpc_url=None)
check("1 integrity ok", v["integrity"] == "ok")
check("1 settlement unverified (no RPC)", v["settlement"] == "unverified")
check("1 not ok overall", v["ok"] is False)

# 2. tampered report -> integrity fail
bad = write_report("# Audit report\nbalance: 0\ntruthful: NO (tampered)\n")
v = vr.verify(rcpt, bad, rpc_url=None)
check("2 tampered -> integrity fail", v["integrity"] == "fail")

# 3. confirmed settlement (stub verify_tx)
orig = vr.verify_tx
vr.verify_tx = lambda sig, **kw: ("settled", {"signature": sig, "amount_atomic": 100000})
v = vr.verify(rcpt, rep, rpc_url="http://stub")
check("3 settled", v["settlement"] == "settled")
check("3 ok", v["ok"] is True)
vr.verify_tx = orig

# 4. receipt without sha256 -> integrity fail
v = vr.verify({"payment": {}}, rep, rpc_url=None)
check("4 missing sha256 -> fail", v["integrity"] == "fail")

# 5. missing payment fields -> unverified, never settled
v = vr.verify({"report": {"sha256": good_hash}}, rep, rpc_url="http://stub")
check("5 missing payment -> unverified", v["settlement"] == "unverified")
check("5 ok is False", v["ok"] is False)

# 6. exit codes
for txt, args, want, label in [
        (rep, ["--receipt", "-", "--report", rep], 2, "no-RPC exit 2"),
        (bad, ["--receipt", "-", "--report", bad], 1, "tampered exit 1")]:
    rc = rcpt if txt is rep else rcpt
    import io
    stdin = io.StringIO(json.dumps(rc))
    old = sys.stdin
    sys.stdin = stdin
    try:
        code = vr.main(args)
    finally:
        sys.stdin = old
    check(f"6 {label}", code == want, f"got {code}")

for p in (rep, bad):
    os.unlink(p)

print(f"RESULT: {'ALL PASS' if FAIL == 0 else str(FAIL) + ' FAIL'}")
raise SystemExit(1 if FAIL else 0)
