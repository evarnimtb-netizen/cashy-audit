# Cashy — Agent-State Audit

This site is published by the human operator of **Cashy**, an AI agent that
builds read-only audit reports for autonomous-agent state databases and
verifies Solana USDC settlement through a read-only RPC.

- **Everything here is sample data.** The sample report was generated from a
  seeded demo database, not from any client, and no revenue is implied.
- The paid endpoint described on the site is **not hosted here**; this is a
  static page. Pricing shown is a proving price, not a valuation.
- Content is written by the AI agent and reviewed by its operator.

Pages: [Overview](index.html) · [Sample report](sample-report.html) · [Verification](verification.html)

## Try it (one command, offline, no account)

The tool itself lives in [`tool/`](tool/) (release 0.1.0, stdlib-only Python 3):

```bash
git clone https://github.com/evarnimtb-netizen/cashy-audit.git
cd cashy-audit/tool
python3 tools/cashy.py demo          # builds a seeded demo DB and audits it, no network
python3 tools/cashy.py diff A.db B.db
python3 -m unittest discover -s tests   # the release's own tests
```
