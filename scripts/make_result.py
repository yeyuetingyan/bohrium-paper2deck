#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble result.json for one case.

Keeps every field the runtime contract asks for: case id, status, primary
result, page-level evidence, artifacts with hashes, uncertainty and a change
log. Missing pieces are reported as "missing", never invented.

Usage:
  python make_result.py --case-id CASE --deck out/deck.pptx --plan plan.json
        [--evidence evidence.json] [--check check.json] [--render render.json]
        [--pdf deck.pdf] [--status ok|partial|failed] [--out out/result.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--check", default=None)
    ap.add_argument("--render", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--status", default="ok", choices=["ok", "partial", "failed"])
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default="result.json")
    args = ap.parse_args()

    plan = load(args.plan) or {}
    evidence = load(args.evidence) or {}
    check = load(args.check) or {}
    render = load(args.render) or {}

    slides = plan.get("slides", [])
    artifacts = []

    def add(path, role, media_type):
        if path and os.path.exists(path):
            artifacts.append({"path": os.path.relpath(path, os.path.dirname(os.path.abspath(args.out))),
                              "role": role, "media_type": media_type,
                              "bytes": os.path.getsize(path), "sha256": sha256(path)})
        else:
            artifacts.append({"path": path, "role": role, "media_type": media_type,
                              "status": "missing"})

    add(args.deck, "editable_presentation", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    add(args.pdf, "rendered_pdf", "application/pdf")
    for png in (render.get("previews") or []):
        add(os.path.join(render.get("out", ""), png), "rendered_preview", "image/png")
    add(args.evidence, "page_level_evidence_map", "application/json")

    # claims table: one row per content slide
    claims = []
    for i, sl in enumerate(slides):
        ev = sl.get("evidence") or []
        claims.append({
            "slide": i + 1,
            "slide_id": sl.get("id"),
            "claim": sl.get("claim") or sl.get("title", ""),
            "evidence": [{"page": e.get("page"), "kind": e.get("kind"),
                          "label": e.get("label"), "quote": e.get("quote")}
                         for e in ev],
            "has_notes": bool(sl.get("notes")),
        })

    uncertainty = []
    for sl in slides:
        for e in sl.get("evidence") or []:
            if not e.get("page"):
                uncertainty.append({"slide": sl.get("id"),
                                    "item": "evidence without page anchor",
                                    "impact": "reviewer must locate the source manually"})
    for w in (check.get("warnings") or []):
        uncertainty.append({"item": w, "impact": "layout review recommended"})
    if render.get("status") == "no_renderer":
        uncertainty.append({"item": "pdf preview not produced",
                            "reason": render.get("reason"),
                            "impact": "rendering must be verified in the target Office version"})
    if args.note:
        uncertainty.append({"item": "operator note", "reason": args.note})

    summary = {
        "case_id": args.case_id,
        "status": args.status,
        "slides": len(slides),
        "figures_used": sum(1 for s in slides if (s.get("figure") or {}).get("path")),
        "tables_used": sum(1 for s in slides if s.get("table")),
        "slides_with_evidence": sum(1 for s in slides if s.get("evidence")),
        "slides_with_notes": sum(1 for s in slides if s.get("notes")),
        "check_status": check.get("status"),
        "render_status": render.get("status"),
    }

    result = {
        "schema": "paper2deck/result/v1",
        "case_id": args.case_id,
        "status": args.status,
        "primary_result": {
            "deck": os.path.relpath(args.deck, os.path.dirname(os.path.abspath(args.out))),
            "pdf": (os.path.relpath(args.pdf, os.path.dirname(os.path.abspath(args.out)))
                    if args.pdf and os.path.exists(args.pdf) else None),
            "previews": render.get("previews") or [],
            "slide_count": len(slides),
            "editable": True,
        },
        "summary": summary,
        "claims": claims,
        "evidence_map": evidence.get("slides", {}),
        "artifacts": artifacts,
        "uncertainty": uncertainty,
        "change_log": [{"time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "action": "assembled result.json from plan, deck, check and render outputs"}],
        "skill": {"name": "paper2deck", "version": "0.1.0"},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "ok", "out": args.out, "slides": len(slides),
                      "artifacts": len(artifacts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
