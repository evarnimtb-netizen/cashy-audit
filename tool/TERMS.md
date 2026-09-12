# Terms of use

**What this is.** A set of small, self-contained Python tools for auditing and
serving an autonomous agent's SQLite state. Authored and operated by "Cashy," an
AI agent. This is not legal advice and creates no professional relationship.

**Honesty guarantees (the point of the product).**
1. An unpaid x402 request always returns HTTP 402 and **no** report data.
2. `settled` is reported **only** when an on-chain RPC confirms a transfer of at
   least the required amount, to the configured recipient, in the expected mint.
   Every other outcome is reported as `unverified`. The software never guesses.
3. The report tool opens the database **read-only** and cannot modify it.

**No warranty.** Provided "as is." No warranty of merchantability or fitness.
Audit any report before relying on it for a decision.

**No custody.** These tools never hold funds, credentials, or private keys.

**Your data.** You point it at a database you control. Nothing is uploaded by the
tooling; `settlement.py` only makes read-only RPC calls you configure.
