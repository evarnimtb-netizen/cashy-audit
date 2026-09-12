#!/usr/bin/env python3
"""set_public_url.py — update the ONE public address used by the site.

Usage: python3 tools/set_public_url.py https://mysite.example
Validates the URL, writes config/public_url.json, rebuilds the site.
Refuses anything that is not a plain public http(s) origin.
"""
import json, os, re, subprocess, sys, datetime

CFG = "config/public_url.json"

def main(argv):
    if len(argv) != 2:
        print("usage: set_public_url.py <https://origin>", file=sys.stderr); return 2
    url = argv[1].strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d+)?", url):
        print(f"refusing: {url!r} is not a plain public http(s) origin", file=sys.stderr); return 2
    cfg = json.load(open(CFG))
    cfg["public_base_url"] = url
    cfg["status"] = "live"
    cfg["updated_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    json.dump(cfg, open(CFG, "w"), indent=2)
    open(CFG, "a").write("\n")
    print(f"public_base_url = {url}")
    # rebuild site so no page carries a stale/absent address
    r = subprocess.run([sys.executable, "tools/build_site.py", "--out", "site"], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode

if __name__ == "__main__":
    sys.exit(main(sys.argv))
