#!/usr/bin/env python3
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from solana_verify import owner_mint_delta, verify_signature, _fixture, USDC_MINT
fails = []
def check(n, c):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}")
    if not c: fails.append(n)
check("delta", owner_mint_delta(_fixture(2_500_000), "PAYEE", USDC_MINT) == 2_500_000)
check("owner filter", owner_mint_delta(_fixture(1), "X", USDC_MINT) == 0)
print(f"\n{'FAIL' if fails else 'RESULT: ALL PASS'} ({len(fails)} fail)")
sys.exit(1 if fails else 0)
