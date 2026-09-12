#!/usr/bin/env python3
"""settlement.py — verify an x402/Solana USDC payment proof against a real RPC.

Turns a provisional `settled:false` into a truthful `settled:true` only when an
on-chain transaction actually confirms a USDC transfer of at least the required
amount to the expected recipient.

Honesty rules:
  * No RPC configured   -> "unverified". Never claim settled.
  * RPC error/timeout   -> "unverified". Never claim settled.
  * Confirmed + correct recipient + amount >= price + correct mint -> "settled".

Read-only. Stdlib only (urllib).

Correctness note (fixed): the recipient is credited if their wallet owner address
appears in meta.pre/postTokenBalances for the right mint. We must NOT require the
wallet to also appear in transaction.message.accountKeys — many legitimate SPL
transfers only expose the wallet as the *owner* of a token account in metadata, so
key-index matching produced false negatives. We now iterate the balance entries
directly, matching on owner+mint, and count each balance entry once.
"""
from __future__ import annotations
import json, os, urllib.request, urllib.error

USDC_MINT_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

def _rpc(url, method, params, timeout=8):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _token_delta(tx, mint, owner):
    """Net atomic increase in `mint` for wallet `owner` across the tx's token
    balances. Matches by owner+mint in metadata; no dependence on accountKeys."""
    total = 0
    meta = (tx.get("meta") or {})
    pre_by_index = {}
    for pb in (meta.get("preTokenBalances") or []):
        pre_by_index[pb.get("accountIndex")] = int((pb.get("uiTokenAmount") or {}).get("amount") or 0)
    for bal in (meta.get("postTokenBalances") or []):
        if bal.get("owner") != owner or bal.get("mint") != mint:
            continue
        pre = pre_by_index.get(bal.get("accountIndex"), 0)
        post = int((bal.get("uiTokenAmount") or {}).get("amount") or 0)
        total += max(0, post - pre)
    return total

def verify_tx(signature, *, pay_to, mint=USDC_MINT_SOLANA, min_amount,
              rpc_url=None, commitment="confirmed"):
    """Return (status, detail) with status in {"settled","unverified"}."""
    rpc_url = rpc_url or os.environ.get("SOLANA_RPC_URL")
    if not rpc_url:
        return "unverified", "no SOLANA_RPC_URL configured; cannot confirm on-chain"
    if not signature:
        return "unverified", "empty signature"
    try:
        resp = _rpc(rpc_url, "getTransaction", [
            signature,
            {"encoding": "jsonParsed", "commitment": commitment,
             "maxSupportedTransactionVersion": 0},
        ])
    except urllib.error.URLError as e:
        return "unverified", f"rpc unreachable: {e}"
    except Exception as e:
        return "unverified", f"rpc error: {e}"
    if resp.get("error"):
        return "unverified", f"rpc returned error: {resp['error']}"
    tx = resp.get("result")
    if not tx:
        return "unverified", "transaction not found at commitment level"
    if (tx.get("meta") or {}).get("err") is not None:
        return "unverified", "transaction failed on-chain"
    delta = _token_delta(tx, mint, pay_to)
    if delta < int(min_amount):
        return "unverified", f"recipient received {delta} < required {min_amount}"
    return "settled", {"signature": signature, "amount_atomic": delta, "mint": mint,
                       "pay_to": pay_to, "slot": tx.get("slot"), "commitment": commitment}

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("usage: settlement.py <signature> <min_amount_atomic>"); raise SystemExit(2)
    print(json.dumps(verify_tx(sys.argv[1], pay_to=os.environ.get(
        "AUDIT_PAY_TO", "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats"),
        min_amount=int(sys.argv[2])), indent=2, default=str))
