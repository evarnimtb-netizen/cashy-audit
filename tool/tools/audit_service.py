#!/usr/bin/env python3
"""audit_service — HTTP surface over cashy_report with a real x402 payment handshake.

  GET /health        -> 200 free
  GET /report        -> 402 + payment requirements, then 200 markdown on paid proof
  GET /report.json   -> same, JSON body

Honesty contract (FAIL-CLOSED):
  * Unpaid / malformed / underpaid / forged requests ALWAYS get 402 and no report.
  * The report is served ONLY when settlement is CONFIRMED on-chain via
    settlement.py (requires SOLANA_RPC_URL). If it cannot be confirmed, the
    default is 402 — never a silent 200.
  * The single exception is an explicit AUDIT_ALLOW_UNVERIFIED=1 demo opt-in,
    used only by the offline `cashy demo`. Even then the response is truthfully
    labelled payment.status == "unverified" — never "settled".
  * Every payment event is appended to workspace/payments.log for creator audit.

BUYER-VERIFIABLE RECEIPT (new):
  A paying buyer must be able to independently confirm what they paid for. Every
  200 response now carries a receipt bound to the report bytes:
    * /report.json  -> body has a top-level "receipt" field whose
                       receipt.report.sha256 is the SHA-256 of the canonical JSON
                       of that body with the "receipt" field removed.
                       Canonical = json.dumps(obj, sort_keys=True,
                       separators=(",",":"), default=str).
    * /report       -> an "X-RECEIPT" header (base64 JSON) whose
                       receipt.report.sha256 is the SHA-256 of the EXACT response
                       body bytes.
  Tools that generate the receipt and the buyer-side checker must agree on this.
  Read-only w.r.t. the state DB. Stdlib only.
"""
from __future__ import annotations
import base64, hashlib, json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cashy_report as cr
try:
    from settlement import verify_tx, USDC_MINT_SOLANA
except Exception:
    verify_tx = None; USDC_MINT_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _load_price():
    """Authoritative price: env override, then config/product.json, then default."""
    env = os.environ.get("AUDIT_PRICE_ATOMIC")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "product.json")
    try:
        with open(cfg) as f:
            return int(json.load(f)["price_atomic"])
    except Exception:
        return 100000  # $0.10 at 6 decimals


HOST = os.environ.get("AUDIT_HOST", "127.0.0.1")
PORT = int(os.environ.get("AUDIT_PORT", "8787"))
DB = os.environ.get("AUDIT_DB", os.path.expanduser("~/.automaton/state.db"))
PAY_TO = os.environ.get("AUDIT_PAY_TO", "7D6KigtqqpiGqn86YFR2qvNFRdDU9aDGiaCnSfLuwats")
PRICE = _load_price()
ALLOW_UNVERIFIED = os.environ.get("AUDIT_ALLOW_UNVERIFIED", "0") == "1"
LEDGER = os.environ.get("AUDIT_LEDGER", os.path.expanduser("~/.automaton/workspace/payments.log"))
RECEIPT_VERSION = 1


def requirements():
    return {"x402Version": 1, "scheme": "exact", "network": "solana",
            "maxAmountRequired": str(PRICE), "resource": "/report",
            "description": "Cashy agent audit report (read-only state summary)",
            "mimeType": "application/json", "payTo": PAY_TO, "assetMint": USDC_MINT_SOLANA,
            "maxTimeoutSeconds": 60}


def canonical_sha(obj) -> str:
    """SHA-256 of the canonical JSON encoding. The ONE definition both sides use."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def parse_proof(header):
    if not header: return None, "missing X-PAYMENT header"
    try: proof = json.loads(base64.b64decode(header).decode())
    except Exception as e: return None, f"malformed payment header: {e}"
    sig = str(proof.get("signature", "")).strip()
    if not sig: return None, "payment proof has no signature"
    try:
        if int(proof.get("amount") or proof.get("maxAmountRequired") or 0) < PRICE:
            return None, "payment amount below required price"
    except Exception: return None, "payment amount missing or non-numeric"
    return proof, None


def settle(proof):
    """-> (status, detail). status in {'settled','unverified'}."""
    if verify_tx is None:
        return "unverified", "settlement module unavailable"
    return verify_tx(proof["signature"], pay_to=PAY_TO, min_amount=PRICE)


def make_receipt(sig, report_sha256):
    return {
        "version": RECEIPT_VERSION,
        "scheme": "exact",
        "network": "solana",
        "report": {"sha256": report_sha256},
        "payment": {
            "signature": sig,
            "pay_to": PAY_TO,
            "amount_atomic": PRICE,
            "mint": USDC_MINT_SOLANA,
        },
    }


def log(kind, detail):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, "detail": detail}, default=str) + "\n")
    except Exception: pass


class H(BaseHTTPRequestHandler):
    server_version = "cashy-audit/1.3"
    def _send(self, code, obj, ctype="application/json", extra=None):
        body = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, default=str)
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def _challenge(self, detail):
        return self._send(402, {"error": "payment required", "detail": detail, "accepts": [requirements()]},
                          extra={"X-PAYMENT-REQUIRED": base64.b64encode(json.dumps(requirements()).encode()).decode()})
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health":
            return self._send(200, {"ok": True, "service": "cashy-audit", "ts": time.time(),
                                    "db_present": os.path.exists(DB),
                                    "price_atomic": PRICE,
                                    "settlement": "enabled" if os.environ.get("SOLANA_RPC_URL") else "unverified",
                                    "serves_unverified": ALLOW_UNVERIFIED,
                                    "receipt_version": RECEIPT_VERSION})
        if p == "/receipt-schema":
            return self._send(200, {"version": RECEIPT_VERSION,
                                    "canonicalization": "json.dumps(obj, sort_keys=True, separators=(',',':'), default=str)",
                                    "json_mode": "sha256 over body minus 'receipt' field",
                                    "markdown_mode": "sha256 over exact body bytes; receipt in X-RECEIPT header",
                                    "buyer_tool": "tools/verify_receipt.py"})
        if p in ("/report", "/report.json"):
            proof, err = parse_proof(self.headers.get("X-PAYMENT"))
            if err:
                log("402", {"path": p, "reason": err})
                return self._challenge(err)
            status, detail = settle(proof)
            log("paid", {"path": p, "status": status, "detail": detail})
            if status != "settled" and not ALLOW_UNVERIFIED:
                # Honesty contract: no confirmed settlement -> no report, ever.
                return self._challenge(detail)
            if not os.path.exists(DB): return self._send(500, {"error": "state db not found", "db": DB})
            rep = cr.collect(DB)
            rep["payment"] = {"status": status, "detail": detail}
            rc = make_receipt(proof["signature"], "")
            if p == "/report.json":
                # Hash the body WITHOUT the receipt, then attach the receipt.
                rc["report"]["sha256"] = canonical_sha(rep)
                rep["receipt"] = rc
                return self._send(200, rep)
            # Markdown: hash the exact bytes, put receipt in a header.
            body = cr.to_markdown(rep).encode()
            rc["report"]["sha256"] = hashlib.sha256(body).hexdigest()
            hdr = base64.b64encode(json.dumps(rc, sort_keys=True).encode()).decode()
            return self._send(200, body, ctype="text/markdown; charset=utf-8",
                              extra={"X-RECEIPT": hdr, "X-RECEIPT-VERSION": str(RECEIPT_VERSION)})
        return self._send(404, {"error": "not found",
                                "paths": ["/health", "/report", "/report.json", "/receipt-schema"]})
    def log_message(self, *a): pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"cashy-audit listening on http://{HOST}:{PORT}  price={PRICE}  pay_to={PAY_TO}")
    srv.serve_forever()
