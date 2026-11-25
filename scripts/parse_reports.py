#!/usr/bin/env python3
"""Parse Maven Surefire XML reports of ONE test-suite run into CSV rows.

One row per test case: project, cpus, order, run, seed, class, test, status.
status is one of: pass, fail, error, skip.
Prints the number of test cases found (0 means the run produced no reports).
"""
import argparse
import csv
import os
import sys
import xml.etree.ElementTree as ET

FIELDS = ["project", "cpus", "order", "run", "seed", "class", "test", "status"]


def status_of(case):
    if case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "fail"
    if case.find("skipped") is not None:
        return "skip"
    return "pass"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--cpus", required=True)
    ap.add_argument("--order", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows = []
    for dirpath, _dirs, files in os.walk(a.src):
        if os.path.basename(dirpath) != "surefire-reports":
            continue
        for fn in files:
            if not (fn.startswith("TEST-") and fn.endswith(".xml")):
                continue
            try:
                root = ET.parse(os.path.join(dirpath, fn)).getroot()
            except ET.ParseError:
                continue
            for case in root.iter("testcase"):
                rows.append([
                    a.project, a.cpus, a.order, a.run, a.seed,
                    case.get("classname", ""), case.get("name", ""),
                    status_of(case),
                ])

    new_file = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(FIELDS)
        w.writerows(rows)
    print(len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
