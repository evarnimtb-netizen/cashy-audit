#!/usr/bin/env python3
"""ledger_chain.py — append-only, tamper-evident event log.

Why this exists: the product's honesty claim is "every material action is
recorded". A plain append-only file does not back that claim — events can be
edited or deleted in the middle and the file still looks fine. This module
makes retroactive edits detectable by anyone, offline, without trusting the
server that wrote the log.

Design (deliberately boring, so it can be verified by hand):
  - The log is a JSONL file. Each line is one record.
  - record_hash = sha256(canonical_json({seq, ts, event, data, prev_hash}))
  - canonical_json = json.dumps(..., sort_keys=True, separators=(",", ":"))
  - The first record's prev_hash is GENESIS = "0" * 64.
  - Each record stores prev_hash and record_hash.

Properties:
  - Editing any field of any record breaks that record's hash.
  - Deleting a record breaks the seq/prev_hash link of the next record.
  - Reordering breaks the links.
  - Truncating the tail is NOT detectable from the file alone (nothing can be);
    use `seal`/`verify_seal` with an externally published head hash to detect it.

CLI:
  python3 tools/ledger_chain.py append  LOG --event E [--data JSON]
  python3 tools/ledger_chain.py verify  LOG           # exit 0 ok / 5 tampered
  python3 tools/ledger_chain.py head    LOG           # print head hash + count
  python3 tools/ledger_chain.py seal    LOG OUT.json  # publishable checkpoint
  python3 tools/ledger_chain.py verify_seal LOG SEAL  # exit 5 on divergence
"""
import argparse
import hashlib
import json
import os
import sys

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def record_hash(seq: int, ts: str, event: str, data, prev_hash: str) -> str:
    payload = {"seq": seq, "ts": ts, "event": event, "data": data,
               "prev_hash": prev_hash}
    return hashlib.sha256(canonical(payload)).hexdigest()


def read_records(path: str):
    """Return (records, errors). Blank lines are ignored, not silently lost."""
    if not os.path.exists(path):
        return [], []
    records, errors = [], []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                errors.append(f"line {i}: blank line (not permitted)")
                continue
            try:
                records.append(json.loads(line))
            except Exception as exc:  # malformed JSON breaks the chain
                errors.append(f"line {i}: unparsable JSON: {exc}")
    return records, errors


def verify(path: str):
    """Return (ok, problems, head_hash, count)."""
    records, problems = read_records(path)
    prev = GENESIS
    for idx, rec in enumerate(records):
        where = f"record {idx + 1} (seq={rec.get('seq')!r})"
        for field in ("seq", "ts", "event", "data", "prev_hash", "record_hash"):
            if field not in rec:
                problems.append(f"{where}: missing field '{field}'")
        if problems and problems[-1].startswith(where):
            return False, problems, None, idx
        if rec.get("seq") != idx:
            problems.append(f"{where}: seq mismatch (expected {idx})")
        if rec.get("prev_hash") != prev:
            problems.append(f"{where}: prev_hash does not link to prior record")
        expect = record_hash(rec["seq"], rec["ts"], rec["event"], rec["data"],
                             rec["prev_hash"])
        if rec.get("record_hash") != expect:
            problems.append(f"{where}: record_hash mismatch — record was edited")
        prev = rec.get("record_hash")
    if problems:
        return False, problems, None, len(records)
    return True, [], (prev if records else GENESIS), len(records)


def append(path: str, event: str, data=None, ts=None) -> dict:
    """Append one record. Refuses to append to an already-broken chain."""
    ok, problems, head, count = verify(path)
    if not ok:
        raise ValueError("refusing to append: existing log is tampered: "
                         + "; ".join(problems[:3]))
    seq = count
    prev = head if count else GENESIS
    ts = ts or __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat()
    rec = {"seq": seq, "ts": ts, "event": event, "data": data,
           "prev_hash": prev}
    rec["record_hash"] = record_hash(seq, ts, event, data, prev)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
    return rec


def seal(path: str, out_path: str) -> dict:
    ok, problems, head, count = verify(path)
    if not ok:
        raise ValueError("cannot seal a tampered log: " + "; ".join(problems[:3]))
    seal_obj = {"file": os.path.basename(path), "count": count, "head": head}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(seal_obj, fh, indent=2, sort_keys=True)
    return seal_obj


def verify_seal(path: str, seal_path: str):
    """Detect truncation/replacement by comparing against a published seal."""
    with open(seal_path, encoding="utf-8") as fh:
        seal_obj = json.load(fh)
    ok, problems, head, count = verify(path)
    if not ok:
        return False, problems
    if count < seal_obj["count"]:
        return False, [f"truncated: {count} records < sealed {seal_obj['count']}"]
    records, _ = read_records(path)
    if records and records[seal_obj["count"] - 1]["record_hash"] != seal_obj["head"]:
        return False, ["head at sealed length differs — history was rewritten"]
    return True, []


def main(argv=None):
    ap = argparse.ArgumentParser(description="tamper-evident event log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append"); a.add_argument("log"); a.add_argument("--event", required=True)
    a.add_argument("--data"); a.add_argument("--ts")
    for name in ("verify", "head"):
        p = sub.add_parser(name); p.add_argument("log")
    s = sub.add_parser("seal"); s.add_argument("log"); s.add_argument("out")
    v = sub.add_parser("verify_seal"); v.add_argument("log"); v.add_argument("seal")
    args = ap.parse_args(argv)

    if args.cmd == "append":
        data = json.loads(args.data) if args.data else None
        rec = append(args.log, args.event, data, args.ts)
        print(json.dumps(rec, sort_keys=True, separators=(",", ":")))
        return 0
    if args.cmd == "verify":
        ok, problems, head, count = verify(args.log)
        if ok:
            print(f"OK — {count} records, chain intact, head {head[:16]}…")
            return 0
        print(f"TAMPERED — {len(problems)} problem(s):")
        for p in problems[:20]:
            print("  " + p)
        return 5
    if args.cmd == "head":
        ok, problems, head, count = verify(args.log)
        print(json.dumps({"ok": ok, "count": count, "head": head}))
        return 0 if ok else 5
    if args.cmd == "seal":
        print(json.dumps(seal(args.log, args.out), indent=2, sort_keys=True))
        return 0
    if args.cmd == "verify_seal":
        ok, problems = verify_seal(args.log, args.seal)
        if ok:
            print("SEAL OK — log is consistent with the published checkpoint")
            return 0
        print("SEAL MISMATCH:")
        for p in problems:
            print("  " + p)
        return 5
    return 2


if __name__ == "__main__":
    sys.exit(main())
