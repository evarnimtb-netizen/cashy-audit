"""Regression: documented CLI commands must actually be runnable.

Guards against a buyer-facing claim (a documented command) that cannot execute —
the class of defect where `report --offline` was advertised but never existed.

Dual-mode: importable by pytest, and runnable directly (`python3 tests/test_doc_cli.py`)
because tools/selfcheck.sh executes suites directly and expects a RESULT line.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "tools", "doc_cli_check.py")


def run():
    r = subprocess.run([sys.executable, CHECK], capture_output=True, text=True)
    if r.returncode == 0:
        print("  [PASS] every documented command parses against the real CLI")
        print("RESULT: ALL PASS (0 fail)")
        return 0
    print(r.stdout + r.stderr)
    print("RESULT: FAIL (documented command is not runnable)")
    return 4


def test_documented_commands_are_runnable():
    assert run() == 0


if __name__ == "__main__":
    sys.exit(run())
