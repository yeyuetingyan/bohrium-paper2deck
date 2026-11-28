#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command self-test of the whole Paper2Deck pipeline (offline).

Runs, against the bundled example plan/paper and a temp directory:

  1. validate_plan.py   — plan constraints
  2. build_deck.py      — PPTX generation
  3. check_deck.py      — overflow / notes / evidence-line self-check
  4. verify_evidence.py — re-verify each evidence quote against the paper

Nothing is downloaded and no real paper is needed, so a reviewer can confirm
the skill works on their own machine with one command:

  python scripts/selftest.py            # writes into a temp dir, cleans up
  python scripts/selftest.py --keep     # keep the temp dir and print its path
  python scripts/selftest.py --json out.json

Exit code 0 = every stage passed, 2 = at least one stage failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def run(stage, args, tmp):
    cmd = [sys.executable] + args
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          errors="replace", env=env, cwd=tmp)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    first = out.splitlines()[-1] if out else ""
    passed = proc.returncode == 0
    # validate/check/verify report their verdict in the JSON line, not only the exit code
    verdict = ""
    try:
        tail = first[first.find("{"):]
        verdict = str(json.loads(tail).get("status", ""))
    except Exception:
        pass
    if verdict and verdict not in ("pass", "ok", "warn"):
        passed = False
    return {
        "stage": stage,
        "returncode": proc.returncode,
        "verdict": verdict,
        "passed": passed,
        "stdout_tail": first[:400],
        "stderr_tail": err[-400:] if err else "",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="offline self-test of the paper2deck pipeline")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--keep", action="store_true", help="keep the temp working dir")
    args = ap.parse_args(argv)

    plan = os.path.join(SKILL, "examples", "example_plan.json")
    paper = os.path.join(SKILL, "examples", "example_paper.json")
    for p in (plan, paper):
        if not os.path.exists(p):
            print(json.dumps({"status": "fail", "reason": "missing example file: %s" % p},
                             ensure_ascii=False))
            return 2

    tmp = tempfile.mkdtemp(prefix="paper2deck-selftest-")
    deck = os.path.join(tmp, "deck.pptx")
    stages = []
    try:
        stages.append(run("validate_plan", [
            os.path.join(HERE, "validate_plan.py"), plan, "--paper", paper], tmp))
        if stages[-1]["passed"]:
            stages.append(run("build_deck", [
                os.path.join(HERE, "build_deck.py"), plan, "--out", deck,
                "--evidence", os.path.join(tmp, "evidence.json")], tmp))
        if stages[-1]["passed"]:
            stages.append(run("check_deck", [
                os.path.join(HERE, "check_deck.py"), deck, "--plan", plan,
                "--paper", paper, "--json", os.path.join(tmp, "check.json")], tmp))
        if stages[-1]["passed"]:
            stages.append(run("verify_evidence", [
                os.path.join(HERE, "verify_evidence.py"), plan, "--paper", paper,
                "--json", os.path.join(tmp, "evidence_check.json")], tmp))
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    failed = [s for s in stages if not s["passed"]]
    report = {
        "schema": "paper2deck-selftest/v1",
        "status": "pass" if stages and not failed else "fail",
        "stages": [{"stage": s["stage"], "passed": s["passed"],
                    "verdict": s["verdict"], "returncode": s["returncode"]} for s in stages],
        "tmp_dir": tmp if args.keep else None,
        "detail": failed,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"],
                      "stages": report["stages"],
                      "failed": [s["stage"] for s in failed]}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
