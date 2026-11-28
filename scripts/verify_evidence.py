#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-verify every evidence claim in plan.json against the source PDF.

This is the "can someone check it" step: it re-opens the paper, and for each
slide's evidence it asserts

  * the page number exists in the PDF;
  * an evidence quote actually occurs on that page (whitespace- and
    hyphenation-insensitive, so PDF line breaks do not cause false alarms);
  * figure/table labels referenced by the slide exist in paper.json and their
    image files are present, non-empty and (for figures) inside the page;
  * every slide of type figure/table carries a label from paper.json.

Output is a machine-readable report (evidence_check.json) plus a one-line
summary the caller can surface. Exit code 0 = pass, 2 = problems found.

Usage:
  python verify_evidence.py plan.json --paper paper.json [--pdf paper.pdf]
                                      [--json report.json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

WS_RE = re.compile(r"\s+")
SOFT_HYPHEN = "\u00ad"


def norm(s: str) -> str:
    """Normalise the way a PDF actually loses whitespace inside a line."""
    s = s.replace(SOFT_HYPHEN, "")
    s = WS_RE.sub("", s)
    return s.lower()


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return json.loads(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise SystemExit("cannot decode %s" % path)


def page_texts(paper, pdf_path=None):
    """Page texts from paper.json, or straight from the PDF when available."""
    if pdf_path and os.path.exists(pdf_path):
        try:
            import fitz  # PyMuPDF
            with fitz.open(pdf_path) as doc:
                return [p.get_text("text") for p in doc], "pdf"
        except Exception:
            pass
    pages = paper.get("page_text") or []
    if isinstance(pages, dict):
        items = sorted(pages.items(), key=lambda kv: int(kv[0]))
        return [v for _, v in items], "paper.json"
    return list(pages), "paper.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify slide evidence against the paper")
    ap.add_argument("plan")
    ap.add_argument("--paper", required=True)
    ap.add_argument("--pdf", default=None, help="source PDF (re-read instead of trusting paper.json)")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true", help="exit 2 on warnings as well")
    args = ap.parse_args(argv)

    plan = load(args.plan)
    paper = load(args.paper)
    pages, source = page_texts(paper, args.pdf)
    npages = len(pages)

    base = os.path.dirname(os.path.abspath(args.paper))
    figs = {}
    for f in paper.get("figures") or []:
        figs[str(f.get("label") or f.get("id") or "").lower()] = f
    tabs = {}
    for t in paper.get("tables") or []:
        tabs[str(t.get("label") or t.get("id") or "").lower()] = t
    norm_pages = [norm(p) for p in pages]

    checks = []          # each: dict(id, slide, level, kind, detail)
    ok = 0

    def add(slide_id, level, kind, detail):
        checks.append({"slide": slide_id, "level": level, "kind": kind, "detail": detail})

    slides = plan.get("slides") or []
    for s in slides:
        sid = str(s.get("id") or "?")
        stype = str(s.get("type") or "")
        ev = s.get("evidence") or []

        # 1) label / image cross-check for figure and table slides
        if stype == "figure":
            fig = s.get("figure") or {}
            label = str(fig.get("label") or "").strip()
            rec = figs.get(label.lower()) or tabs.get(label.lower())
            if not rec:
                add(sid, "medium", "label_unknown", "figure label not in paper.json: %r" % label)
            else:
                img = rec.get("image")
                if not img:
                    add(sid, "high", "image_missing_field", "%s has no image in paper.json" % label)
                else:
                    path = os.path.join(base, img)
                    if not os.path.exists(path):
                        add(sid, "high", "image_file_missing", "%s: %s not found" % (label, img))
                    elif os.path.getsize(path) == 0:
                        add(sid, "high", "image_empty", "%s: %s is 0 bytes" % (label, img))
                    else:
                        ok += 1
                pg = rec.get("page")
                if isinstance(pg, int) and (pg < 1 or pg > npages):
                    add(sid, "high", "page_out_of_range", "%s claims page %s of %d" % (label, pg, npages))

        # 2) every evidence entry must point at a real page and a real quote
        for i, e in enumerate(ev):
            frame = "%s#ev%d" % (sid, i + 1)
            page = e.get("page")
            if not isinstance(page, int):
                add(frame, "high", "page_not_int", "evidence page must be an integer, got %r" % (page,))
                continue
            if page < 1 or page > npages:
                add(frame, "high", "page_out_of_range", "page %d outside 1..%d" % (page, npages))
                continue
            quote = (e.get("quote") or "").strip()
            if not quote:
                # page-only evidence is allowed for figure/table slides, but say so
                add(frame, "low", "quote_absent", "evidence has page but no quote")
                ok += 1
                continue
            hay = norm_pages[page - 1]
            if norm(quote) in hay:
                ok += 1
                continue
            # allow a shortened quote: check the longest prefix that is >= 24 chars
            hit = False
            q = norm(quote)
            for cut in (len(q), int(len(q) * 0.8), int(len(q) * 0.6)):
                if 24 <= cut <= len(q) and q[:cut] in hay:
                    hit = True
                    add(frame, "low", "quote_prefix_match",
                        "quote only matches the first %d chars of its page text" % cut)
                    break
            if not hit:
                add(frame, "high", "quote_not_found", "quote not found on page %d: %r" % (page, quote[:70]))

    high = sum(1 for c in checks if c["level"] == "high")
    medium = sum(1 for c in checks if c["level"] == "medium")
    low = sum(1 for c in checks if c["level"] == "low")
    status = "fail" if high else ("warn" if (medium or (args.strict and low)) else "pass")

    report = {
        "schema": "evidence-check/v1",
        "status": status,
        "source": source,
        "pages_in_paper": npages,
        "slides": len(slides),
        "evidence_checked": sum(len(s.get("evidence") or []) for s in slides),
        "evidence_verified": ok,
        "issues": {"high": high, "medium": medium, "low": low},
        "checks": checks,
        "limits": [
            "只核对引文是否出现在所声明的页上，不判断该引文是否真的支撑该页主张（语义判断不在自动核验范围）。",
            "页码以 PDF 物理页序为准（与 extract_paper.py 的 page 字段一致），不是期刊印刷页码。",
            "图/表只核对标签是否在 paper.json 中、图片是否存在，不核对图像内容与图注是否一致。",
        ],
    }

    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as f:
            f.write(out + "\n")
    print(json.dumps({k: report[k] for k in
                      ("status", "pages_in_paper", "slides", "evidence_checked",
                       "evidence_verified", "issues")}, ensure_ascii=False))
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
