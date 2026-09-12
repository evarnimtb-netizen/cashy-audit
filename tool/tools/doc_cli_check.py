#!/usr/bin/env python3
"""doc_cli_check.py — fail if any documented command is not actually runnable.

Why this exists: the free-tier command advertised in config/product.json and
docs/PRICE.md was `cashy.py report --offline`, but `--offline` does not exist.
That is a buyer-facing claim that could not be executed — exactly the kind of
dishonesty this product is supposed to prevent. This check parses the real CLI
and asserts every documented `python3 tools/cashy.py ...` invocation in shipped
docs/config/subcommands is valid.

Exit 0 = all documented commands parse. Exit 4 = a documented command is bogus.
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "cashy.py")

# Files a buyer might read. Only these are treated as claims.
DOC_GLOBS = [
    "README.md", "PLAN.md", "docs/*.md", "service/*.md", "service/*.html",
    "site/*.html", "site/*.md", "config/*.json", "packaging/OFFER.md",
    "dist/*/README.md", "DEPLOY.md",
]

# Commands whose output/args we intentionally do not execute (server, network).
SKIP_COMMANDS = {"serve"}

CMD_RE = re.compile(r"python3\s+tools/cashy\.py\s+([a-z]+)([^\n\"<`]*)")
# Second CLI: the buyer-side verifier. No subcommands; only flags are claims.
VR_RE = re.compile(r"python3\s+tools/verify_receipt\.py((?:[^\n\"<`]|\\\n)*)")
VR = os.path.join(ROOT, "tools", "verify_receipt.py")
FLAG_RE = re.compile(r"(?<!\S)(--?[a-zA-Z][\w-]*)")


def subcommands():
    out = subprocess.run([sys.executable, CLI, "-h"], capture_output=True, text=True).stdout
    m = re.search(r"\{([a-z,]+)\}", out)
    return set(m.group(1).split(",")) if m else set()


def sub_help(cmd):
    return subprocess.run([sys.executable, CLI, cmd, "-h"],
                          capture_output=True, text=True).stdout


def main():
    subs = subcommands()
    help_cache = {c: sub_help(c) for c in subs if c not in SKIP_COMMANDS}
    problems = []
    checked = 0
    for pat in DOC_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pat)):
            text = open(path, encoding="utf-8", errors="replace").read()
            for cmd, rest in CMD_RE.findall(text):
                checked += 1
                rel = os.path.relpath(path, ROOT)
                if cmd not in subs:
                    problems.append(f"{rel}: unknown subcommand `{cmd}`")
                    continue
                if cmd in SKIP_COMMANDS:
                    continue
                for flag in FLAG_RE.findall(rest):
                    if not flag.startswith("--"):
                        continue  # short flags vary; long flags are the claims
                    if flag not in help_cache[cmd]:
                        problems.append(
                            f"{rel}: `{cmd} {flag}` is documented but not accepted")

    # --- second CLI: verify_receipt.py (flags only, no subcommands) ---
    vr_help = subprocess.run([sys.executable, VR, "-h"],
                             capture_output=True, text=True).stdout
    for pat in DOC_GLOBS:
        for path in glob.glob(os.path.join(ROOT, pat)):
            text = open(path, encoding="utf-8", errors="replace").read()
            for rest in VR_RE.findall(text):
                checked += 1
                rel = os.path.relpath(path, ROOT)
                for flag in FLAG_RE.findall(rest):
                    if not flag.startswith("--"):
                        continue
                    if flag not in vr_help:
                        problems.append(
                            f"{rel}: `verify_receipt.py {flag}` is documented but not accepted")

    print(f"doc_cli_check: inspected {checked} documented command(s) "
          f"across shipped docs")
    if problems:
        print("\n  DEFECTS — documented commands that cannot run:")
        for p in problems:
            print(f"    - {p}")
        print("\n  RESULT: FAIL (a documented command is not runnable)")
        return 4
    print("  RESULT: PASS — every documented command parses against the real CLI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
