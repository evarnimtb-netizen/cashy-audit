#!/usr/bin/env python3
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import claim_lint as CL
FAILS = []
def check(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' — '+x) if x and not c else ''}")
    if not c: FAILS.append(n)

bad = """Our revolutionary tool made $50,000 in sales.
Over 500 happy customers say they love it.
100% guaranteed accurate, act now!
"""
f = CL.lint(bad, require_disclosure=True)
rules = {x["rule"] for x in f}
for r in ("hype", "revenue-claim", "customer-count", "fake-testimonial", "guarantee", "fake-urgency", "missing-ai-disclosure"):
    check(f"flags {r}", r in rules, str(sorted(rules)))
check("counts errors", CL.summarize(f)["errors"] >= 4)

good = """I am an AI agent. This report reads your database read-only.
It shows what was recorded. Payment status is 'unverified' until an RPC confirms it.
"""
g = CL.lint(good, require_disclosure=True)
check("clean honest text passes", not g, str(g))

only_disc = CL.lint("I am an AI agent.", require_disclosure=True)
check("disclosure alone satisfies requirement", not only_disc, str(only_disc))

neg = "This is not a guarantee. We made no revenue claim. There are no 500 customers."
n = CL.lint(neg)
check("negated claims are not flagged", not n, str(n))

print()
if FAILS:
    print(f"RESULT: FAIL ({len(FAILS)}) -> {FAILS}"); sys.exit(1)
print("RESULT: ALL PASS")

def test_range_ignore_and_dates():
    # a date must not be read as a money claim
    assert not L.lint_text("Built 2026-09-12 by build_site.py")["errors"], "date false positive"
    # off/on region suppresses everything between, incl. multi-line examples
    text = "safe line\n<!--claim-lint:off-->\nwe made $50,000 in sales\n100% guaranteed\n<!--claim-lint:on-->\nalso safe\n"
    r = L.lint_text(text)
    assert not r["errors"] and not r["warnings"], r
    print("  [PASS] range ignore + date false-positive guard")
