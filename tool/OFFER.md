# Cashy Agent-State Audit — offer (draft, honesty-first)

**The problem.** Operators of autonomous agents often cannot answer, quickly and
readably: what did it spend, what did it do, did that "payment" actually settle?

**The deliverable.** A read-only audit report over an agent's `state.db`
(markdown, JSON, or a single self-contained HTML file), plus — if you run the
service — a paid endpoint that serves the same report behind a real x402
handshake that reports settlement truthfully.

**What you get, concretely.**
- `cashy status` — one-screen summary.
- `cashy report --html out.html` — a self-contained HTML audit, no dependencies.
- `audit_service.py` — `/health`, `/report` (402 then 200), `/report.json`.
- A 22-assertion test suite proving the honesty contract.

**Price.** Not set. Demand is **unvalidated** — no customer has paid or been
contacted. I will not quote a price or claim customers until that is real.

**What this is not.** Not a security audit, not financial advice, not a guarantee
that any given payment settled. No hype, no fake testimonials, no urgency.
