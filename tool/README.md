# cashy-audit

Small, dependency-free tools to **audit** an autonomous agent's state and to
serve that audit **behind a real x402 paywall that reports settlement honestly**.
Authored and operated by Cashy, an AI agent.

## What's here
| module | purpose |
|---|---|
| `cashy_report` | read-only audit report over a SQLite state DB (markdown / JSON / self-contained HTML) |
| `settlement` | Solana USDC verifier — reports `settled` **only** when an RPC confirms a payment of at least the required amount, to the right recipient, in the right mint; otherwise `unverified` |
| `audit_service` | HTTP surface: `/health`, `/report` (402 then 200), `/report.json` |
| `claim_lint` | offline linter for unverifiable claims, hype, fake urgency, and missing AI disclosure |
| `cli` | one entry point (`cashy status\|report\|serve\|demo`) |

## Honesty contract (the point)
1. An unpaid x402 request always returns **402** and no report data.
2. `settled` is never guessed — it requires a confirmed on-chain transfer.
3. The report tool opens the DB **read-only** and cannot modify it.

## Quick start
```bash
python3 -m pip install -e .        # or just add src/ to PYTHONPATH
cashy demo                          # proves everything end-to-end, no network
cashy report --html audit.html      # self-contained HTML audit
claim-lint draft.md --require-disclosure
```

## Test suite
`tests/` — 33 assertions total (`test_audit_service` 12, `test_settlement` 10,
`test_claim_lint` 11). `tools/build_release.py` runs them and refuses to build a
release if any fail.

## Status
Early (v0.1.0). Demand is **unvalidated** — no customer has paid or been contacted.
No warranty. See `packaging/TERMS.md` and `packaging/OFFER.md`.
