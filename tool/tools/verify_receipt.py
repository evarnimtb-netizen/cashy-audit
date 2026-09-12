#!/usr/bin/env python3
"""verify_receipt.py — BUYER-side independent verification of an x402 purchase.

An agent that PAYS for a report should not have to trust the seller's dashboard.
This tool lets the *buyer* independently check two things:

  1. INTEGRITY  — the bytes I received match the sha256 the seller bound in the
                  receipt, using the seller's published canonicalization.
  2. SETTLEMENT — the on-chain tx the seller pointed at actually transferred at
                  least the required USDC to the claimed recipient.

Two integrity modes (the seller documents which it used):
  * json   — report is JSON; sha256 of `json.dumps(body_without_receipt,
             sort_keys=True, separators=(',',':'), default=str)`.
             Used by GET /report.json (receipt embedded as `receipt`).
  * bytes  — sha256 of the exact received file bytes.
             Used by GET /report (receipt in the X-RECEIPT header; save it with
             --receipt-from-header).

Honesty contract (same fail-closed rule as the seller side):
  * No RPC configured  -> settlement = "unverified". NEVER claim "settled".
  * RPC error/timeout  -> "unverified".
  * Hash mismatch      -> integrity = "fail" (hard failure, exit 1).
  * Only a confirmed, correct amount/recipient/mint -> settlement = "settled".

Read-only. Stdlib only. No keys, no signing, no network unless an RPC is set.
Exit codes: 0 = integrity ok AND settlement settled; 1 = integrity fail;
2 = integrity ok but settlement unverified.

Usage:
  python3 tools/verify_receipt.py --receipt receipt.json --report report.json
  python3 tools/verify_receipt.py --json-report report.json   # embedded receipt
  python3 tools/verify_receipt.py --report report.md --receipt-from-header HDR
      HDR = base64 of the X-RECEIPT header value
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from settlement import verify_tx, USDC_MINT_SOLANA  # noqa: E402
except ModuleNotFoundError as _e:  # fail clearly, never silently mis-verify
    _where = os.path.dirname(os.path.abspath(__file__))
    sys.stderr.write(
        "verify_receipt: required module not found next to this script: "
        f"{_e.name}\n  looked in: {_where}\n"
        "  The self-contained bundle must ship settlement.py alongside this file.\n"
        "  Re-create the bundle with: bash tools/build_verify_bundle.sh\n")
    raise SystemExit(3)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_sha(obj) -> str:
    """MUST match audit_service.canonical_sha exactly."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256_bytes(blob)


def load_receipt(src: str) -> dict:
    if src == "-":
        return json.load(sys.stdin)
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


def receipt_from_json_report(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        body = json.load(f)
    rc = body.get("receipt")
    if not isinstance(rc, dict):
        raise SystemExit("error: report JSON has no embedded 'receipt' object")
    return rc


def compute_integrity(receipt: dict, report_path: str) -> tuple[str, str]:
    """-> (status, reason) where status in {'ok','fail'}."""
    claimed = (receipt.get("report") or {}).get("sha256") or receipt.get("sha256")
    if not claimed:
        return "fail", "receipt does not contain a claimed sha256 for the report"
    mode = (receipt.get("report") or {}).get("mode")
    if mode is None:
        # Infer: if the file parses as JSON containing 'receipt', it's json mode.
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                body = json.load(f)
            mode = "json" if isinstance(body, dict) and "receipt" in body else "bytes"
        except Exception:
            mode = "bytes"

    with open(report_path, "rb") as f:
        raw = f.read()

    if mode == "json":
        try:
            body = json.loads(raw.decode())
        except Exception as e:
            return "fail", f"declared json mode but body is not JSON: {e}"
        body.pop("receipt", None)
        actual = canonical_sha(body)
        label = "canonical-JSON body minus receipt"
    else:
        actual = sha256_bytes(raw)
        label = "exact body bytes"

    if actual == str(claimed).lower():
        return "ok", f"report sha256 matches receipt ({actual[:12]}…, {label})"
    return "fail", f"report sha256 MISMATCH ({label}): received {actual[:12]}… != claimed {str(claimed)[:12]}…"


def verify(receipt: dict, report_path: str, rpc_url: str | None = None) -> dict:
    """Return a truthful verdict dict. Never claims more than was proven."""
    out = {"integrity": "unknown", "settlement": "unverified", "reasons": [], "ok": False}

    status, reason = compute_integrity(receipt, report_path)
    out["integrity"] = status
    out["reasons"].append(reason)

    pay = receipt.get("payment") or {}
    sig = pay.get("signature") or receipt.get("signature")
    pay_to = pay.get("pay_to") or receipt.get("pay_to") or receipt.get("payTo")
    min_amount = pay.get("amount_atomic") or receipt.get("amount_atomic") or receipt.get("maxAmountRequired")
    mint = pay.get("mint") or USDC_MINT_SOLANA

    if not sig or not pay_to or min_amount is None:
        out["reasons"].append("receipt missing payment signature/pay_to/amount; cannot confirm")
    else:
        st, detail = verify_tx(sig, pay_to=pay_to, mint=mint, min_amount=int(min_amount), rpc_url=rpc_url)
        out["settlement"] = st
        if st == "settled":
            out["reasons"].append(f"on-chain USDC transfer confirmed: {detail}")
        else:
            out["reasons"].append(f"settlement not confirmed: {detail}")

    out["ok"] = (out["integrity"] == "ok" and out["settlement"] == "settled")
    return out


def human(verdict: dict) -> str:
    lines = ["─" * 56, " x402 buyer-side receipt verification", "─" * 56]
    lines.append(f" integrity  : {verdict['integrity'].upper()}")
    lines.append(f" settlement : {verdict['settlement'].upper()}")
    for r in verdict["reasons"]:
        lines.append(f"   • {r}")
    if verdict["ok"]:
        lines.append(" VERDICT: VERIFIED — bytes match and payment confirmed on-chain.")
    elif verdict["integrity"] == "fail":
        lines.append(" VERDICT: FAILED — do not trust these report bytes.")
    else:
        lines.append(" VERDICT: UNVERIFIED — integrity ok, but the payment could NOT be")
        lines.append("          independently confirmed (no RPC / not found). Treat as unpaid.")
    lines.append("─" * 56)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", help="receipt JSON path, or - for stdin")
    ap.add_argument("--json-report", help="a /report.json body with embedded 'receipt'")
    ap.add_argument("--receipt-from-header", help="base64 X-RECEIPT header value (markdown mode)")
    ap.add_argument("--report", help="the report file you received")
    ap.add_argument("--rpc-url", default=None, help="read-only Solana RPC (else env SOLANA_RPC_URL)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    a = ap.parse_args(argv)

    if a.json_report:
        receipt = receipt_from_json_report(a.json_report)
        report = a.json_report
    elif a.receipt_from_header:
        try:
            receipt = json.loads(base64.b64decode(a.receipt_from_header).decode())
        except Exception as e:
            print(f"error: bad X-RECEIPT header: {e}", file=sys.stderr)
            return 1
        if not a.report:
            print("error: --report is required with --receipt-from-header", file=sys.stderr)
            return 1
        receipt.setdefault("report", {})["mode"] = "bytes"
        report = a.report
    elif a.receipt and a.report:
        receipt, report = load_receipt(a.receipt), a.report
    else:
        print("error: provide (--receipt and --report), or --json-report, "
              "or (--report and --receipt-from-header)", file=sys.stderr)
        return 1

    v = verify(receipt, report, rpc_url=a.rpc_url or os.environ.get("SOLANA_RPC_URL"))
    print(json.dumps(v, indent=2) if a.json else human(v))
    if v["integrity"] == "fail":
        return 1
    return 0 if v["settlement"] == "settled" else 2


if __name__ == "__main__":
    raise SystemExit(main())
