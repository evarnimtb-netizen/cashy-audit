#!/usr/bin/env python3
"""rpc_check — approved read-only Solana RPC liveness probe.

Read-only JSON-RPC only (getHealth/getVersion). NEVER signs and NEVER submits a
transaction. Used to confirm settlement verification has a live endpoint.
"""
from __future__ import annotations
import json, os, sys, urllib.request

DEFAULT = "https://api.mainnet-beta.solana.com"
def rpc_url(): return os.environ.get("SOLANA_RPC_URL", DEFAULT)

def _call(method, timeout=8):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}).encode()
    req = urllib.request.Request(rpc_url(), data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def main(argv=None):
    print("rpc_url:", rpc_url())
    print("mode: READ-ONLY (no signing, no transactions)")
    ok = True
    for m in ("getHealth", "getVersion"):
        try:
            d = _call(m)
            print(f"  {m}: {json.dumps(d.get('result', d))[:100]}")
        except Exception as e:
            ok = False
            print(f"  {m}: ERROR {type(e).__name__}: {e}"[:140])
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
