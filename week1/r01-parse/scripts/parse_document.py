#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读01｜文献文档解析：PDF → 带页码锚点的 Markdown + 块级锚点表。

用法：
  python parse_document.py --case /input/case.json --out /app/output
  python parse_document.py --pdf paper.pdf --out out [--max-pages 60]

产物：
  document.md     结构化 Markdown（标题层级、段落、GFM 表格、图片引用、<!-- page N --> 锚点）
  blocks.json     块级锚点表（id/page/kind/hash/quote），供逐块回溯
  figures/        图与不可靠表格的页面渲染图
  result.json     结构化结果（status / 证据 / 不确定项 / 产物哈希）
  check.json      自检结果
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paperkit as pk


def build(case_path, pdf, out_dir, max_pages):
    os.makedirs(out_dir, exist_ok=True)
    _, ctx = pk.load_case(case_path) if case_path else ({}, {"case_id": "case", "contract": {}})
    pdf = pdf or ctx.get("paper")
    case_id = ctx.get("case_id", "case")
    contract = ctx.get("contract") or {}
    uncertainty = []

    if not pdf or not os.path.exists(pdf):
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, "failed",
                       {"reason": "no_pdf", "expected": "/input/*.pdf"},
                       uncertainty=[{"item": "input pdf not found",
                                     "impact": "nothing can be parsed"}],
                       contract=contract)
        return 2

    try:
        doc = pk.PDFDoc(pdf, max_pages=max_pages)
    except RuntimeError as e:
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, "failed",
                       {"reason": str(e), "source": os.path.basename(pdf)},
                       uncertainty=[{"item": f"pdf unreadable: {e}",
                                     "impact": "no content extracted"}],
                       contract=contract)
        return 2

    figdir = os.path.join(out_dir, "figures")
    md, blocks, figs, tabs = pk.to_markdown(doc, figdir_rel="figures")

    # 扫描页：文字层缺失
    scanned = []
    for p in doc.pages:
        t = p.get_text().strip()
        if len(t) < 40:
            scanned.append(p.number + 1)
    if scanned:
        uncertainty.append({
            "item": f"pages with little/no text layer: {scanned}",
            "impact": "those pages need OCR; content is not invented here"})

    md_path = os.path.join(out_dir, "document.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    blocks_path = os.path.join(out_dir, "blocks.json")
    with open(blocks_path, "w", encoding="utf-8") as f:
        json.dump({"schema": "paperkit/blocks/v1", "source": os.path.basename(pdf),
                   "pages": doc.page_count, "blocks": blocks}, f,
                  ensure_ascii=False, indent=1)

    # 逐页覆盖与锚点自检
    per_page = Counter(b["page"] for b in blocks)
    empty_pages = [p for p in range(1, doc.page_count + 1) if per_page.get(p, 0) == 0]
    dropped = sum(1 for ln in doc.lines if doc.is_running(ln))

    tables_ok = [t for t in tabs if t["reliable"]]
    tables_img = [t for t in tabs if not t["reliable"]]
    check = {
        "schema": "paperkit/check/v1",
        "pages": doc.page_count,
        "blocks": len(blocks),
        "blocks_per_page": {str(k): v for k, v in sorted(per_page.items())},
        "empty_pages": empty_pages,
        "headings": sum(1 for b in blocks if b["kind"] == "heading"),
        "paragraphs": sum(1 for b in blocks if b["kind"] == "paragraph"),
        "tables_markdown": len(tables_ok),
        "tables_as_image": len(tables_img),
        "figures": len(figs),
        "running_head_lines_dropped": dropped,
        "scanned_pages": scanned,
        "title": doc.detect_title(),
        "authors": doc.detect_authors(),
        "body_pt": doc.body_pt,
        "warnings": list(doc.warnings),
        "status": "pass" if not empty_pages and doc.page_count else "warn",
    }
    check_path = os.path.join(out_dir, "check.json")
    with open(check_path, "w", encoding="utf-8") as f:
        json.dump(check, f, ensure_ascii=False, indent=1)

    status = "ok" if not scanned and not empty_pages else "partial"
    primary = {
        "markdown": "document.md",
        "blocks": len(blocks),
        "pages": doc.page_count,
        "sections": check["headings"],
        "tables": len(tabs),
        "figures": len(figs),
        "title": check["title"],
        "authors": check["authors"],
        "language": "zh" if pk.cjk_ratio(md[:4000]) > 0.15 else "en",
    }
    evidence = [{"page": b["page"], "kind": b["kind"], "block": b["id"],
                 "quote": b["quote"]} for b in blocks if b["kind"] in
                ("figure", "table", "table-image", "heading")][:40]
    pk.emit_result(os.path.join(out_dir, "result.json"), case_id, status, primary,
                   evidence=evidence, uncertainty=uncertainty,
                   artifacts=[(md_path, "markdown", "text/markdown"),
                              (blocks_path, "block_anchors", "application/json"),
                              (check_path, "self_check", "application/json")],
                   contract=contract)
    print(json.dumps({"status": status, "pages": doc.page_count,
                      "blocks": len(blocks), "tables": len(tabs),
                      "figures": len(figs), "out": out_dir}, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--max-pages", type=int, default=60)
    args = ap.parse_args()
    case = args.case if args.case and os.path.exists(args.case) else None
    return build(case, args.pdf, args.out, args.max_pages)


if __name__ == "__main__":
    sys.exit(main())
