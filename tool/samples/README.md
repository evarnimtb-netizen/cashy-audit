# Sample deliverable (free tier)

These files are **not** customer data and **not** a real audit of any client.
They are the output of the free tier (`python3 tools/cashy.py demo`) run against
a **seeded sample database**, committed unmodified so a buyer can inspect the
exact artifact before paying anything.

| File | What it is |
|------|------------|
| `sample_audit_report.html` | The self-contained HTML audit report the free tier produces (2 KB, no external assets, opens offline). |
| `sample_audit_report.db` | The sample SQLite state DB the report was rendered from. |
| `demo_transcript.txt` | Verbatim transcript of the command that produced the two files above. |

## What the demo proves (and what it does not)

Proves, on this machine, with no network and no accounts:
- unpaid `/report` returns **402** and releases no report bytes;
- paid `/report.json` returns **200**, and its `payment.status` is
  **`unverified`** unless an RPC actually confirms the transfer;
- the ledger records every event.

Does **not** prove: any revenue, any customer, or any real settlement. Sample
numbers (`spend_cents 42`) are seeded demo values, not real spend.

## Reproduce it yourself

```
python3 tools/cashy.py demo      # writes workspace/demo.db + workspace/demo_audit.html
```
