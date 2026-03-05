#!/usr/bin/env python3
"""scripts/task3.py – example Task 3 script (Python)."""

import argparse
import datetime

parser = argparse.ArgumentParser()
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args()

now = datetime.datetime.now(datetime.timezone.utc).isoformat()
print(f"[task3] Python task running at {now}")
if args.verbose:
    print("[task3] Verbose mode enabled.")
