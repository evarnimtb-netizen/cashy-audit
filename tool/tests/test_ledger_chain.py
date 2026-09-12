#!/usr/bin/env python3
"""Tests for tools/ledger_chain.py — every tamper case must be caught.

Covers: clean chain verifies; field edit caught; mid-record deletion caught;
reordering caught; truncation caught only via a published seal; malformed line
caught; append refuses to extend a broken chain; empty file verifies as GENESIS.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ledger_chain as L  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def build(path, n=4):
    for i in range(n):
        L.append(path, f"event{i}", {"i": i}, ts=f"2026-01-01T00:00:0{i}+00:00")


def main():
    tmp = tempfile.mkdtemp(prefix="ledgerchain_")
    log = os.path.join(tmp, "log.jsonl")

    print("empty log")
    check("empty verifies as GENESIS", L.verify(log) == (True, [], L.GENESIS, 0))

    print("clean chain")
    build(log)
    ok, problems, head, count = L.verify(log)
    check("clean chain verifies", ok and count == 4 and not problems)
    check("head is 64 hex chars", len(head) == 64 and all(c in "0123456789abcdef" for c in head))

    print("determinism")
    log2 = os.path.join(tmp, "log2.jsonl")
    for i in range(4):
        L.append(log2, f"event{i}", {"i": i}, ts=f"2026-01-01T00:00:0{i}+00:00")
    check("same inputs -> same head", L.verify(log2)[2] == head)

    print("field edit")
    tampered = os.path.join(tmp, "edit.jsonl")
    lines = open(log).read().splitlines()
    rec = json.loads(lines[1]); rec["data"]["i"] = 999
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    open(tampered, "w").write("\n".join(lines) + "\n")
    ok, problems, _, _ = L.verify(tampered)
    check("edited field detected", (not ok) and any("edited" in p or "mismatch" in p for p in problems))
    check("no head returned when tampered", L.verify(tampered)[2] is None)

    print("deletion")
    dele = os.path.join(tmp, "del.jsonl")
    open(dele, "w").write("\n".join(lines[:1] + lines[2:]) + "\n")
    ok, problems, _, _ = L.verify(dele)
    check("deleted record detected", not ok)

    print("reorder")
    swp = os.path.join(tmp, "swap.jsonl")
    open(swp, "w").write("\n".join([lines[0], lines[2], lines[1], lines[3]]) + "\n")
    ok, problems, _, _ = L.verify(swp)
    check("reordered records detected", not ok)

    print("malformed line")
    mal = os.path.join(tmp, "mal.jsonl")
    open(mal, "w").write(lines[0] + "\n{not json\n")
    ok, problems, _, _ = L.verify(mal)
    check("malformed JSON detected", (not ok) and any("unparsable" in p for p in problems))

    print("append is safe")
    try:
        L.append(tampered, "should-fail")
        check("append refuses tampered chain", False)
    except ValueError:
        check("append refuses tampered chain", True)
    before = len(open(log).read().splitlines())
    L.append(log, "extra", {"x": 1}, ts="2026-01-01T01:00:00+00:00")
    check("append extends clean chain", L.verify(log)[0] and len(open(log).read().splitlines()) == before + 1)

    print("truncation vs published seal")
    seal_path = os.path.join(tmp, "seal.json")
    L.seal(log, seal_path)
    check("seal matches live log", L.verify_seal(log, seal_path)[0])
    trunc = os.path.join(tmp, "trunc.jsonl")
    open(trunc, "w").write("\n".join(open(log).read().splitlines()[:2]) + "\n")
    ok, problems = L.verify_seal(trunc, seal_path)
    check("truncated log detected via seal", (not ok) and any("truncated" in p for p in problems))
    ok, _ = L.verify_seal(log, seal_path)
    check("intact log still passes seal", ok)
    rew = os.path.join(tmp, "rewrite.jsonl")
    rl = open(log).read().splitlines(); rl[4] = rl[4].replace('"extra"', '"rewritten"')  # last record IS the sealed head
    open(rew, "w").write("\n".join(rl) + "\n")
    check("rewrite at sealed length detected", not L.verify_seal(rew, seal_path)[0])

    print(f"\nRESULT: {'ALL PASS' if FAIL == 0 else 'FAILURES'} ({FAIL} fail) — "
          f"{PASS}/{PASS+FAIL} checks")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
