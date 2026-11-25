#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate plan.json before building, so errors surface early.

Checks page-level claim discipline, bullet density, evidence anchors, notes
quality (notes must add information, not repeat the slide), and file paths.

Usage:
  python validate_plan.py plan.json [--paper paper.json] [--json report.json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

TYPES = {"title", "section", "bullets", "figure", "table", "comparison", "closing"}
KINDS = {"figure", "table", "section", "text", "equation"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--paper", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    base = os.path.dirname(os.path.abspath(args.plan))
    deck = plan.get("deck", {})
    slides = plan.get("slides", [])
    errors, warnings = [], []

    if not slides:
        errors.append("plan has no slides")
    max_slides = int(deck.get("max_slides", 0) or 0)
    if max_slides and len(slides) > max_slides:
        errors.append(f"{len(slides)} slides exceed max_slides={max_slides}")

    pages = None
    if args.paper and os.path.exists(args.paper):
        with open(args.paper, encoding="utf-8") as f:
            pages = json.load(f).get("meta", {}).get("pages")

    seen_ids = set()
    for i, sl in enumerate(slides):
        tag = sl.get("id") or f"#{i+1}"
        if tag in seen_ids:
            errors.append(f"{tag}: duplicate slide id")
        seen_ids.add(tag)
        kind = sl.get("type", "")
        if kind not in TYPES:
            errors.append(f"{tag}: unknown type '{kind}'")
        title = (sl.get("title") or "").strip()
        if not title:
            errors.append(f"{tag}: empty title")
        elif len(title) > 58:
            warnings.append(f"{tag}: title {len(title)} chars, may wrap")
        if kind not in ("title", "closing", "section"):
            if not (sl.get("claim") or "").strip():
                errors.append(f"{tag}: content slide without claim")
            ev = sl.get("evidence") or []
            if not ev:
                errors.append(f"{tag}: no evidence anchor")
            for e in ev:
                if e.get("kind") not in KINDS:
                    warnings.append(f"{tag}: evidence kind '{e.get('kind')}' unusual")
                if not isinstance(e.get("page"), int):
                    errors.append(f"{tag}: evidence without integer page")
                elif pages and not (1 <= e["page"] <= pages):
                    errors.append(f"{tag}: evidence page {e['page']} outside 1..{pages}")
        notes = (sl.get("notes") or "").strip()
        if kind not in ("title", "closing") and not notes:
            errors.append(f"{tag}: missing speaker notes")
        if notes and title and notes == title:
            warnings.append(f"{tag}: notes duplicate the title")
        bullets = sl.get("bullets") or []
        if len(bullets) > 5:
            warnings.append(f"{tag}: {len(bullets)} bullets, >5 hurts readability")
        for b in bullets:
            t = (b.get("text") or "").strip()
            if len(t) > 72:
                warnings.append(f"{tag}: bullet of {len(t)} chars may wrap twice")
            if int(b.get("level", 0)) > 1:
                warnings.append(f"{tag}: bullet level {b.get('level')} too deep")
        for key in ("figure", "table"):
            obj = sl.get(key)
            if isinstance(obj, dict) and obj.get("path"):
                p = obj["path"] if os.path.isabs(obj["path"]) else os.path.join(base, obj["path"])
                if not os.path.exists(p):
                    errors.append(f"{tag}: {key} file not found: {obj['path']}")
        if kind == "figure" and not (sl.get("figure") or {}).get("path"):
            errors.append(f"{tag}: figure slide without figure path")
        if kind == "table" and not (sl.get("table") or {}):
            errors.append(f"{tag}: table slide without table")
        if kind == "comparison" and len(sl.get("columns") or []) < 2:
            warnings.append(f"{tag}: comparison with fewer than 2 columns")

    result = {"schema": "plan-check/v1", "status": "fail" if errors else "pass",
              "slides": len(slides), "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return 0 if (not errors and (not args.strict or not warnings)) else 1


if __name__ == "__main__":
    sys.exit(main())
