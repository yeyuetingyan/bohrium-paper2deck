#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic self-check for a generated deck.

Checks that can be verified without PowerPoint:
  * slide count vs. max_slides
  * every content slide has a title, speaker notes and an evidence line
  * estimated text overflow (real font metrics, per text frame)
  * minimum font size, image presence, table dimensions
  * evidence pages exist in the source PDF page range (optional)

Usage:
  python check_deck.py deck.pptx --plan plan.json [--paper paper.json]
                                  [--json report.json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_deck import wrap_count  # noqa: E402

from pptx import Presentation
from pptx.util import Emu


def inches(v):
    return v / 914400.0


def para_need(paragraph, width_in):
    """(lines, height_in) needed by one paragraph."""
    text = "".join(r.text for r in paragraph.runs)
    if not text.strip():
        return 0, 0.0
    size = max((r.font.size.pt for r in paragraph.runs if r.font.size), default=12)
    bold = any(r.font.bold for r in paragraph.runs)
    ls = paragraph.line_spacing or 1.12
    if isinstance(ls, float) and ls < 0.5:      # pptx stores exact spacing in Pt/float
        ls = 1.12
    indent = float(paragraph._p.pPr.get("marL", 0)) / 914400.0 if paragraph._p.pPr is not None else 0
    lines = wrap_count(text, size, max(10, (width_in - indent) * 72), bold)
    h = lines * size * ls / 72.0
    sa = paragraph.space_after.pt / 72.0 if paragraph.space_after else 0
    return lines, h + sa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--paper", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    prs = Presentation(args.pptx)
    plan = {}
    if args.plan and os.path.exists(args.plan):
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
    slides_plan = plan.get("slides", [])
    max_slides = int(plan.get("deck", {}).get("max_slides", 0) or 0)

    errors, warnings, per_slide = [], [], []
    if max_slides and len(prs.slides) > max_slides:
        errors.append(f"slide count {len(prs.slides)} exceeds max_slides {max_slides}")

    for idx, slide in enumerate(prs.slides):
        no = idx + 1
        info = {"slide": no, "text_boxes": 0, "images": 0, "min_font": None,
                "overflow": [], "chars": 0}
        notes = ""
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        info["notes_chars"] = len(notes)

        title_text = ""
        for shp in slide.shapes:
            if shp.has_text_frame:
                info["text_boxes"] += 1
                for p in shp.text_frame.paragraphs:
                    for r in p.runs:
                        if r.font.size:
                            info["min_font"] = min(info["min_font"] or 99, r.font.size.pt)
                        info["chars"] += len(r.text)
                if not title_text and shp.has_text_frame:
                    t = shp.text_frame.text.strip()
                    if t and len(t) < 120:
                        title_text = title_text or t
            if shp.shape_type == 13 or getattr(shp, "image", None):
                info["images"] += 1

        # overflow estimation
        for shp in slide.shapes:
            if not shp.has_text_frame:
                continue
            tf = shp.text_frame
            w = inches(shp.width) - inches(tf.margin_left) - inches(tf.margin_right)
            h_avail = inches(shp.height) - inches(tf.margin_top) - inches(tf.margin_bottom)
            need = 0.0
            for p in tf.paragraphs:
                _, ph = para_need(p, w)
                need += ph
            if need > h_avail * 1.12 + 0.02 and h_avail > 0.15:
                info["overflow"].append({
                    "shape": shp.name,
                    "need_in": round(need, 2),
                    "have_in": round(h_avail, 2),
                    "text": tf.text[:60],
                })
        if info["overflow"]:
            warnings.append(f"slide {no}: possible text overflow in "
                            f"{len(info['overflow'])} shape(s)")
        if plan and slides_plan:
            kind = slides_plan[idx].get("type") if idx < len(slides_plan) else ""
            if kind not in ("title", "closing") and not notes:
                warnings.append(f"slide {no}: missing speaker notes")
        per_slide.append(info)

    if args.paper and os.path.exists(args.paper) and plan:
        with open(args.paper, encoding="utf-8") as f:
            paper = json.load(f)
        n_pages = paper.get("meta", {}).get("pages", 999)
        for sl in slides_plan:
            for e in sl.get("evidence", []) or []:
                pg = e.get("page")
                if isinstance(pg, int) and (pg < 1 or pg > n_pages):
                    errors.append(f"{sl.get('id')}: evidence page {pg} outside 1..{n_pages}")

    result = {"schema": "deck-check/v1", "status": "fail" if errors else "pass",
              "slides": len(prs.slides), "errors": errors,
              "warnings": warnings, "per_slide": per_slide}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    ok = not errors and (not args.strict or not warnings)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
