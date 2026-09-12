# Cashy audit report
_Generated: 2026-09-12T19:18:12.071479+00:00_
DB: `~/.automaton/sandbox/workspace/demo.db`

## Table sizes
- **goals**: 1
- **inference_costs**: 1
- **turns**: 1

## Spend (cents)
- inference_costs: 42
- **total: 42** (~$0.42)

## Recent activity
### goals
- {"id": "g1", "title": "demo goal", "status": "active", "created_at": "2026-09-12T16:00:00Z"}
### inference_costs
- {"id": "d1", "cost_cents": 42, "created_at": "2026-09-12T16:00:00Z"}
### turns
- {"id": "d1", "created_at": "2026-09-12T16:00:00Z"}
## Findings

- **[INFO]** No high/medium findings — Automated checks found nothing abnormal in the accessible tables.
  - check: This is not a clean bill of health — see scope limits below.

### Scope limits

- Reads only accessible SQLite tables; data in files, other DBs, or remote systems is invisible.
- Cannot confirm that recorded amounts match provider invoices.
- Absence of findings is not proof of correctness.
