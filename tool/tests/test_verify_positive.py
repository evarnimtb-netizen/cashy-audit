#!/usr/bin/env python3
"""Positive-path verification of solana_verify.verify_signature.

The existing suite proves the NEGATIVE direction well (forged/failed/absent
transactions must NOT be reported as settled). This adds the POSITIVE direction,
which is what actually keeps the product honest: `settled` must be returned
ONLY when a confirmed, error-free transaction really moved >= min_atomic of the
mint to the payee — and must be exactly the boundary, not a guess.

Runs fully offline: the only network call (`_call` -> JSON-RPC) is replaced with
injected fixtures. No network, no keys, no signing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import solana_verify as sv  # noqa: E402

PAYEE = "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats"
MINT = sv.USDC_MINT


def _tx(delta, err=None, owner=PAYEE, mint=MINT, confirmed=True):
    """Build a getTransaction-shaped response moving `delta` atomic to owner."""
    pre = [{"accountIndex": 0, "mint": mint, "owner": owner,
            "uiTokenAmount": {"amount": str(max(0, -delta))}}]
    post = [{"accountIndex": 0, "mint": mint, "owner": owner,
             "uiTokenAmount": {"amount": str(max(0, delta))}}]
    meta = {"err": err, "preTokenBalances": pre, "postTokenBalances": post}
    if not confirmed:
        return {"result": None}
    return {"result": {"meta": meta}}


def _with_rpc(monkeypatch_result):
    """Patch _call to return a fixed payload; return a restore callable."""
    original = sv._call
    sv._call = lambda method, params, timeout=12: monkeypatch_result
    return lambda: setattr(sv, "_call", original)


FAILS = []


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} {detail}")
    else:
        print(f"  [PASS] {name}")


def main():
    # 1. exactly at the threshold -> settled (boundary must be inclusive)
    r = _with_rpc(_tx(100_000))
    try:
        st, d = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("exact-amount settles", st == "settled", f"got {st}: {d}")

    # 2. one atomic unit short -> unverified (off-by-one guard)
    r = _with_rpc(_tx(99_999))
    try:
        st, d = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("one-short is unverified", st == "unverified", f"got {st}")

    # 3. overpayment settles
    r = _with_rpc(_tx(500_000))
    try:
        st, _ = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("overpayment settles", st == "settled")

    # 4. confirmed-but-failed tx must NOT settle even with a large delta
    r = _with_rpc(_tx(500_000, err={"InstructionError": [0, "Custom"]}))
    try:
        st, _ = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("failed tx never settles", st == "unverified")

    # 5. right mint, WRONG payee -> unverified (no unrelated credit)
    r = _with_rpc(_tx(500_000, owner="SOMEONE_ELSE"))
    try:
        st, _ = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("wrong payee unverified", st == "unverified")

    # 6. wrong mint (not USDC) -> unverified
    r = _with_rpc(_tx(500_000, mint="So11111111111111111111111111111111111111112"))
    try:
        st, _ = sv.verify_signature("sig", PAYEE, 100_000, mint=MINT)
    finally:
        r()
    check("wrong mint unverified", st == "unverified")

    # 7. unknown/unconfirmed signature -> unverified, never settled
    r = _with_rpc({"result": None})
    try:
        st, _ = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        r()
    check("unknown sig unverified", st == "unverified")

    # 8. RPC failure -> unverified (fail-closed), never an exception
    def boom(method, params, timeout=12):
        raise TimeoutError("no network")
    original = sv._call
    sv._call = boom
    try:
        st, d = sv.verify_signature("sig", PAYEE, 100_000)
    finally:
        sv._call = original
    check("rpc failure fails closed", st == "unverified", f"got {st}: {d}")

    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)} positive-path defect(s))")
        return 4
    print("RESULT: ALL PASS (0 fail) — settled only on a confirmed, matching, sufficient transfer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
