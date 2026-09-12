#!/usr/bin/env python3
"""Unit tests for settlement.verify_tx — exercises the 'settled' path with a
synthetic RPC response, plus every refusal path. No network needed: we
monkeypatch settlement._rpc. This is how we prove `settled:true` is only ever
emitted when the chain actually says the money moved.
"""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import settlement as S

PAY_TO = "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats"
MINT = S.USDC_MINT_SOLANA
FAILS = []
def check(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' — '+x) if x and not c else ''}")
    if not c: FAILS.append(n)

def tx(delta, ok=True, recipient=PAY_TO, mint=MINT):
    return {"result": {
        "slot": 1, "meta": {"err": None if ok else {"InstructionError": [0, "x"]},
            "preTokenBalances": [{"accountIndex": 0, "owner": recipient, "mint": mint,
                                  "uiTokenAmount": {"amount": "0"}}],
            "postTokenBalances": [{"accountIndex": 0, "owner": recipient, "mint": mint,
                                   "uiTokenAmount": {"amount": str(delta)}}]},
        "transaction": {"message": {"accountKeys": [recipient, "Other1111111111111111111111111111111111111"]}}}}

orig = S._rpc
try:
    S._rpc = lambda url, m, p, timeout=8: tx(100000)
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("confirmed exact payment -> settled", st == "settled", str(d))
    check("settled carries amount+mint", isinstance(d, dict) and d["amount_atomic"] == 100000)

    S._rpc = lambda url, m, p, timeout=8: tx(150000)
    st, _ = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("overpayment -> settled", st == "settled")

    S._rpc = lambda url, m, p, timeout=8: tx(99999)
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("underpayment -> unverified", st == "unverified", str(d))

    S._rpc = lambda url, m, p, timeout=8: tx(100000, ok=False)
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("failed tx -> unverified", st == "unverified", str(d))

    S._rpc = lambda url, m, p, timeout=8: {"result": None}
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("missing tx -> unverified", st == "unverified", str(d))

    S._rpc = lambda url, m, p, timeout=8: tx(100000, recipient="WrongRecipient111111111111111111111111111111")
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("wrong recipient -> unverified", st == "unverified", str(d))

    S._rpc = lambda url, m, p, timeout=8: tx(100000, mint="NotTheUSDMint11111111111111111111111111111111")
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("wrong mint -> unverified", st == "unverified", str(d))

    S._rpc = lambda url, m, p, timeout=8: {"error": {"code": -32000, "message": "nope"}}
    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url="http://x")
    check("rpc error -> unverified", st == "unverified", str(d))

    st, d = S.verify_tx("SIG", pay_to=PAY_TO, min_amount=100000, rpc_url=None)
    check("no rpc -> unverified", st == "unverified", str(d))
finally:
    S._rpc = orig

print()
if FAILS:
    print(f"RESULT: FAIL ({len(FAILS)}) -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")
