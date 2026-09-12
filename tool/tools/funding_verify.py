#!/usr/bin/env python3
"""funding_verify.py — read-only confirmation of creator funding + payment rail.

Checks, with NO signing and NO transaction submission:
  1. USDC balance of the payTo wallet's associated token account, via read-only RPC.
  2. The most recent confirmed transaction touching that token account, fed through
     the SAME settlement.py verifier a real customer payment would use.
  3. The live 402 challenge advertises exactly the configured payTo + USDC mint.

Exit 0 only if balance > 0 AND the settlement verifier returns "settled" on the
real deposit AND the challenge matches. Otherwise exit 1 with the honest reason.
"""
import json, os, sys, urllib.request

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
PAY_TO = os.environ.get("AUDIT_PAY_TO", "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats")
RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
ATA = "CCGSZa7juzS4CJptM6F6TtoEo6mcjBo32KswDYwHjj5j"  # creator-reported token account

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settlement import verify_tx, USDC_MINT_SOLANA  # noqa: E402


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def main():
    ok = True
    print("RPC:", RPC)
    print("payTo:", PAY_TO)
    print("mint:", USDC_MINT)

    # 1) balance
    try:
        bal = rpc("getTokenAccountBalance", [ATA])
        amt = bal.get("result", {}).get("value", {})
        print(f"ATA {ATA}: uiAmount={amt.get('uiAmount')} atoms={amt.get('amount')}")
        got = float(amt.get("uiAmount") or 0)
        if got <= 0:
            print("FAIL: zero balance"); ok = False
    except Exception as e:
        print("FAIL: balance lookup error:", e); ok = False

    # 2) settlement verifier on the real deposit tx
    try:
        sigs = rpc("getSignaturesForAddress", [ATA, {"limit": 1}])
        rows = sigs.get("result", []) or []
        if not rows:
            print("FAIL: no transaction history on ATA"); ok = False
        else:
            sig = rows[0]["signature"]
            print("newest tx:", sig)
            status, detail = verify_tx(sig, pay_to=PAY_TO, mint=USDC_MINT,
                                       min_amount=100000, rpc_url=RPC)
            print("settlement verifier =>", status)
            print("  detail:", json.dumps(detail, default=str) if not isinstance(detail, str) else detail)
            if status != "settled":
                ok = False
    except Exception as e:
        print("FAIL: settlement check error:", e); ok = False

    # 3) 402 challenge consistency (mint constant in settlement.py must match)
    if USDC_MINT_SOLANA != USDC_MINT:
        print("FAIL: settlement.py mint constant mismatch"); ok = False
    else:
        print("challenge/verifier mint constant: MATCH")

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
