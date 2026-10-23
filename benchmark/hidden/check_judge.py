#!/usr/bin/env python3
"""Can the judge be trusted? Two conditions, both checked on the reference implementation:

  1. a correct implementation passes EVERYTHING (stage A and B) — the judge requires nothing
     that is not in the specification and the change requests;
  2. every deliberate fault (`REFERENCE_FAULT`) is CAUGHT — the judge really catches the defect
     classes the benchmark was built for (a mechanism not wired in, a rule in 1 place out of N).

Run it after every change in `hidden/`. A benchmark whose judge does not pass this measures
its own bugs, not Telesma.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAULTS = ("reminders_not_wired", "expiry_not_wired", "audiobook_missing_from_filter",
          "audiobook_missing_from_report", "limit_without_audiobook")


def judge(stage, fault=""):
    env = dict(os.environ, REFERENCE_STAGE=stage, REFERENCE_FAULT=fault)
    r = subprocess.run([sys.executable, str(HERE / "judge.py"), str(HERE / "reference"), stage],
                       capture_output=True, text=True, env=env)
    return json.loads(r.stdout)


errors = 0
for stage in ("A", "B"):
    r = judge(stage)
    good = r["passed"] == r["total"] and r["total"] > 0
    print(f"{'✓' if good else '✗'} reference, stage {stage}: {r['passed']}/{r['total']}")
    for n in r["failed"]:
        print("    ", n)
    errors += not good
for f in FAULTS:
    r = judge("B", f)
    print(f"{'✓' if r['failed'] else '✗'} fault {f}: caught by {len(r['failed'])} "
          f"test(s)" + ("" if r["failed"] else " — THE JUDGE DOES NOT SEE IT"))
    errors += not r["failed"]
print("OK" if not errors else f"ERRORS: {errors}")
sys.exit(1 if errors else 0)
