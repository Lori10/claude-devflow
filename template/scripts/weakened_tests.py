#!/usr/bin/env python3
"""Flag test changes that may weaken the suite: removed assertions or tests, added skips
or .only. Lines that reappear unchanged elsewhere in the diff (moved or split tests) are
ignored. A judgment call, so it never fails the build: exit 1 means "review these hunks".

Usage: scripts/weakened_tests.py --base <rev> [test paths...]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter

REMOVED = re.compile(
    r"^\s*(assert\b|self\.assert\w*\(|assert\w*\(|expect\(|.*\.should\b|"
    r"(async\s+)?def\s+test_\w*|(it|test|describe)\s*\()"
)
ADDED = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\(|@unittest\.skip|"
    r"\b(it|test|describe)\.(skip|todo|only)\s*\(|\bx(it|test|describe)\s*\(|\bf(it|describe)\s*\("
)


def scan(diff: str):
    removed, added, current = [], [], "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("-") and not line.startswith("---"):
            removed.append((current, line[1:]))
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((current, line[1:]))
    readded = Counter(text.strip() for _, text in added)
    findings = []
    for path, text in removed:
        key = text.strip()
        if REMOVED.match(text):
            if readded[key]:
                readded[key] -= 1  # moved, not removed
                continue
            findings.append(f"{path}: removed: {key}")
    for path, text in added:
        if ADDED.search(text):
            findings.append(f"{path}: added: {text.strip()}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("paths", nargs="*", default=["tests"])
    args = ap.parse_args()
    paths = [p for p in args.paths if os.path.exists(p)] or args.paths
    diff = subprocess.run(["git", "diff", "--no-color", "-U0", args.base, "--", *paths],
                          capture_output=True, text=True).stdout
    findings = scan(diff)
    if not findings:
        print("--> none")
        return 0
    print("\n".join(findings))
    print("--> REVIEW (read these hunks; see the verify skill's reference.md)")
    if os.environ.get("GITHUB_ACTIONS"):
        print("::warning title=Possibly weakened test::Review the test hunks listed in the check.sh log.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
