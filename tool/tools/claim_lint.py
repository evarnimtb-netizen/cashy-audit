#!/usr/bin/env python3
"""claim_lint — catch unverifiable claims and missing AI disclosure before publishing.

Motivation (Constitution Law III / Genesis PROHIBITED CONDUCT): don't fabricate
testimonials, reviews, demand, revenue, credentials, or results; don't deceive
about being an AI. This is a deterministic, offline linter that scans text you
are about to publish and flags risky patterns. It is *advisory*: it points at
lines, it does not censor.

Rules are conservative and explainable. Exit code 1 if any ERROR-level finding,
so it can gate a publish step in CI.

Usage:
    python3 tools/claim_lint.py FILE [FILE...]
    python3 tools/claim_lint.py --json FILE
    cat draft.md | python3 tools/claim_lint.py -
"""
from __future__ import annotations
import argparse, json, re, sys

# (id, severity, regex, message)  severity: error | warn
RULES = [
    ("fake-testimonial", "error",
     r"\b(customers?|clients?|users?)\s+(say|said|love|rave|agree)\b|\btestimonial\b|\b\d+[- ]star review\b",
     "Unverifiable testimonial/review language. Do not claim what you cannot cite."),
    ("fabricated-metric", "error",
     r"\b\d{1,3}(\.\d+)?\s?%\s+(faster|better|more|increase|improvement|accuracy)\b|\b\d+x\s+(faster|better|growth|roi)\b",
     "Bare performance multiple/percentage with no cited source. Cite or drop."),
    ("revenue-claim", "error",
     r"\b(earned|made|generated|revenue of|profit of)\s+\$\d[\d,\.]*\b|\b\$[\d,\.]+\s+(in\s+)?(revenue|sales|profit|mrr|arr)\b",
     "Revenue/earnings claim. Only assert cleared, received money — and label it."),
    ("customer-count", "error",
     r"\b(over|more than)?\s?\d[\d,\.]*\+?\s+(happy\s+)?(customers|clients|users|subscribers)\b",
     "Customer/user count claim. Must be verifiable and non-misleading."),
    ("guarantee", "warn",
     r"\b(guarantee|guaranteed|100%\s+(safe|secure|accurate|guaranteed)|risk[- ]?free)\b",
     "Absolute guarantee. Almost never truthful; qualify or remove."),
    ("credential", "warn",
     r"\b(certified|licensed|accredited|audited by|ISO\s?\d{4,5})\b",
     "Credential/audit claim. Only if a real, citable credential exists."),
    ("fake-urgency", "warn",
     r"\b(act now|only \d+ (left|spots)|limited time|expires (today|tonight)|last chance)\b",
     "Manufactured urgency — prohibited by the mission. Remove."),
    ("hype", "warn",
     r"\b(revolutionary|world[- ]?class|cutting[- ]?edge|game[- ]?chang\w+|effortless|magic(al)?|10x your)\b",
     "Hype language; keeps the offer honest by removing it."),
]
AI_DISCLOSURE = re.compile(r"\b(i am an ai|i'm an ai|\bai agent\b|operated by (an )?ai|autonomous agent|ai-operated)\b", re.I)

# A negation may be followed by a couple of small words ("not a", "no such",
# "there are no", "is not our") before the claim. Allow a short window.
NEGATION = re.compile(
    r"(\bnot\b|\bno\b|\bnever\b|\bwon't\b|\bcannot\b|\bcan't\b|\bdoesn't\b|\bdon't\b|\bdoes not\b|\bisn't\b|\bwithout\b|\bnon-|\bnor\b)"
    r"(\s+\w+){0,2}\s*$", re.I)

def _is_negated(line: str, start: int) -> bool:
    """True if the match at `start` is preceded by a negation/disclaimer word,
    so 'not a guarantee' or 'no revenue claim' is not treated as a claim."""
    return bool(NEGATION.search(line[:start]))

def lint(text: str, require_disclosure: bool = False):
    findings = []
    lines = text.splitlines()
    # Ignore fenced example blocks and lines marked with the ignore sentinel so a page
    # may *show* bad copy (e.g. a linter demo) without being flagged as making it.
    in_fence = False
    lint_off = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "claim-lint:off" in line:
            lint_off = True; continue
        if "claim-lint:on" in line:
            lint_off = False; continue
        if stripped.startswith("```"):
            in_fence = not in_fence; continue
        if in_fence or lint_off or "claim-lint:ignore" in line:
            continue
        low = line.lower()
        for rid, sev, pat, msg in RULES:
            m = re.search(pat, low, re.I)
            if m and not _is_negated(low, m.start()):
                findings.append({"line": i, "rule": rid, "severity": sev,
                                 "match": m.group(0), "message": msg,
                                 "text": line.strip()[:160]})
    if require_disclosure and text.strip() and not AI_DISCLOSURE.search(text):
        findings.append({"line": 0, "rule": "missing-ai-disclosure", "severity": "error",
                         "match": "", "message": "No AI-disclosure sentence found; required for public/customer-facing text.",
                         "text": ""})
    return findings

def summarize(findings):
    errs = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    return {"errors": errs, "warnings": warns, "total": len(findings)}

def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()

def main(argv=None):
    ap = argparse.ArgumentParser(prog="claim_lint", description="Flag unverifiable claims in text you are about to publish.")
    ap.add_argument("files", nargs="+", help="files, or - for stdin")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-disclosure", action="store_true",
                    help="require an AI-disclosure sentence (public/customer-facing text)")
    a = ap.parse_args(argv)
    results = {}
    for path in a.files:
        try:
            results[path] = lint(_read(path), a.require_disclosure)
        except OSError as e:
            results[path] = [{"line": 0, "rule": "read-error", "severity": "error",
                              "match": "", "message": str(e), "text": ""}]
    if a.json:
        print(json.dumps({"results": results, "summary": summarize([f for r in results.values() for f in r])}, indent=2))
    else:
        total = []
        for path, fs in results.items():
            if not fs:
                print(f"{path}: clean"); continue
            print(f"{path}:")
            for f in fs:
                loc = f"line {f['line']}" if f["line"] else "file"
                print(f"  [{f['severity'].upper():5}] {loc}: {f['rule']} — {f['message']}")
                if f["text"]: print(f"          > {f['text']}")
            total += fs
        s = summarize(total)
        print(f"\nsummary: {s['errors']} error(s), {s['warnings']} warning(s)")
    return 1 if any(f["severity"] == "error" for fs in results.values() for f in fs) else 0

if __name__ == "__main__":
    raise SystemExit(main())
