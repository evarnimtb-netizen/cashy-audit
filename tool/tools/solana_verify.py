#!/usr/bin/env python3
"""solana_verify — read-only verification of a Solana USDC (SPL) transfer.

Given a transaction signature, confirm the transfer actually moved at least
`min_atomic` of the given SPL mint to `pay_to`. Read-only JSON-RPC only: it
calls getTransaction and inspects the result. It NEVER signs and NEVER submits
a transaction.

The interesting part is the accounting: an SPL transfer shows up as a balance
change for the recipient's *associated token account*, so we must map token
accounts to their owner and sum pre/postTokenBalances for that owner+mint.
"""
from __future__ import annotations
import json, os, sys, urllib.request

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"

def rpc_url(): return os.environ.get("SOLANA_RPC_URL", DEFAULT_RPC)

def _call(method, params, timeout=12):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(rpc_url(), data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def owner_mint_delta(tx, pay_to, mint):
    """Sum the net token-balance change (atomic units) for `pay_to` on `mint`.

    Reads meta.preTokenBalances/postTokenBalances, matching by owner + mint.
    Returns an int (can be negative). Pure function -> unit-testable offline.
    """
    meta = (tx.get("meta") or {})
    if meta.get("err"):
        return 0
    totals = {}
    for key, sign in (("preTokenBalances", -1), ("postTokenBalances", +1)):
        for b in meta.get(key) or []:
            if b.get("mint") != mint:
                continue
            if b.get("owner") != pay_to:
                continue
            amt = (b.get("uiTokenAmount") or {}).get("amount")
            if amt is None:
                continue
            acct = b.get("accountIndex")
            totals[acct] = totals.get(acct, 0) + sign * int(amt)
    return sum(totals.values())

def verify_signature(sig, pay_to, min_atomic, mint=USDC_MINT, rpc=None):
    """Return (status, detail). status in {'settled','unverified'}.

    'settled' requires a confirmed, error-free tx whose net USDC delta to
    `pay_to` is >= min_atomic. Everything else is 'unverified' with a reason.
    """
    try:
        d = _call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                           "commitment": "confirmed"}])
    except Exception as e:
        return "unverified", f"rpc error: {type(e).__name__}"
    res = d.get("result")
    if res is None:
        return "unverified", "transaction not found (unconfirmed or unknown signature)"
    if (res.get("meta") or {}).get("err"):
        return "unverified", "transaction failed on-chain"
    delta = owner_mint_delta(res, pay_to, mint)
    if delta < int(min_atomic):
        return "unverified", f"insufficient confirmed amount: got {delta}, need {min_atomic}"
    return "settled", f"confirmed +{delta} atomic to {pay_to} on {mint[:4]}..{mint[-4:]}"

# ---- offline fixtures / tests ----
def _fixture(delta, err=None):
    pre = [{"accountIndex": 0, "mint": USDC_MINT, "owner": "PAYEE",
            "uiTokenAmount": {"amount": str(max(0, -delta))}}]
    post = [{"accountIndex": 0, "mint": USDC_MINT, "owner": "PAYEE",
             "uiTokenAmount": {"amount": str(max(0, delta))}}]
    return {"meta": {"err": err, "preTokenBalances": pre, "postTokenBalances": post}}

def _selftest():
    fails = []
    def check(n, c, x=""):
        print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' — '+x) if x and not c else ''}")
        if not c: fails.append(n)
    check("exact amount counts", owner_mint_delta(_fixture(1_000_000), "PAYEE", USDC_MINT) == 1_000_000)
    check("wrong owner ignored", owner_mint_delta(_fixture(1_000_000), "SOMEONE_ELSE", USDC_MINT) == 0)
    check("wrong mint ignored", owner_mint_delta(_fixture(1_000_000), "PAYEE", "OTHERMINT") == 0)
    check("failed tx yields 0", owner_mint_delta(_fixture(1_000_000, err={"InstructionError": [0, "x"]}), "PAYEE", USDC_MINT) == 0)
    # verify_signature with monkeypatched RPC
    global _call
    orig = _call
    _call = lambda m, p, timeout=12: {"result": _fixture(1_000_000)}
    check("settled when enough", verify_signature("sig", "PAYEE", 1_000_000)[0] == "settled")
    check("unverified when short", verify_signature("sig", "PAYEE", 5_000_000)[0] == "unverified")
    _call = lambda m, p, timeout=12: {"result": None}
    check("unverified when not found", verify_signature("sig", "PAYEE", 1)[0] == "unverified")
    _call = orig
    print()
    if fails:
        print(f"RESULT: FAIL ({len(fails)}) -> {fails}"); sys.exit(1)
    print("RESULT: ALL PASS")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif len(sys.argv) >= 4:
        status, detail = verify_signature(sys.argv[1], sys.argv[2], int(sys.argv[3]))
        print(f"{status}: {detail}")
        sys.exit(0 if status == "settled" else 3)
    else:
        print(__doc__); _selftest()
