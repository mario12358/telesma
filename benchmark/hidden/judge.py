#!/usr/bin/env python3
"""Benchmark judge: runs the hidden tests against a project and prints the result as JSON.

    python3 benchmark/hidden/judge.py <project directory> A|B

Stage B = stage A tests (regression, minus the ones the change requests deliberately change) + stage B tests.
Result: {"stage", "total", "passed", "failed": [names], "groups": {class: [ok, total]}}.
"""
import collections
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Collector(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.results = {}

    def startTest(self, test):
        super().startTest(test)
        self.results[test.id()] = "ok"

    def addFailure(self, test, err):
        self.results[test.id()] = "fail"

    def addError(self, test, err):
        self.results[test.id()] = "fail"

    def addSkip(self, test, reason):
        self.results[test.id()] = "skip"


def evaluate(project, stage):
    os.environ["BENCH_PROJECT"] = str(Path(project).resolve())
    os.environ["BENCH_STAGE"] = stage
    sys.path.insert(0, str(HERE))
    for m in ("base", "test_stage_a", "test_stage_b"):
        sys.modules.pop(m, None)
    modules = ["test_stage_a"] + (["test_stage_b"] if stage == "B" else [])
    col = Collector()
    unittest.defaultTestLoader.loadTestsFromNames(modules).run(col)
    counted = {k: v for k, v in col.results.items() if v != "skip"}
    groups = collections.defaultdict(lambda: [0, 0])
    for name, r in counted.items():
        g = ".".join(name.split(".")[:2])
        groups[g][1] += 1
        groups[g][0] += r == "ok"
    return dict(stage=stage, total=len(counted), passed=sum(r == "ok" for r in counted.values()),
                failed=sorted(n for n, r in counted.items() if r != "ok"), groups=dict(groups))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("A", "B"):
        sys.exit(__doc__)
    print(json.dumps(evaluate(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
