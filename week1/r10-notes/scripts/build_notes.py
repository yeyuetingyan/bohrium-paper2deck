#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读10｜文献总结与结构化笔记：论文 → 与原文结构对齐、可回查的笔记。

用法：
  python build_notes.py --case /input/case.json --out /app/output
  python build_notes.py --pdf paper.pdf --out out [--max-pages 80]

产物：
  notes.md        人读版笔记（论文卡片 / 结构 / 章节笔记 / 关键发现 / 条件 / 局限 / 术语）
  notes.json      机器可读笔记（同内容）
  anchors.json    全部笔记 → 原文锚点（page / block / quote / hash）
  concepts.json   术语与缩写表（含首次出现位置）
  index.json      倒排索引（词 → 块），供后续检索
  check.json      自检：锚点命中率、字段覆盖、结构识别、扫描页
  result.json     结构化结果（status / evidence / uncertainty / artifacts）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paperkit as pk
import noteskit as nk


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return path


def build(case_path, pdf, out_dir, max_pages):
    os.makedirs(out_dir, exist_ok=True)
    _, ctx = pk.load_case(case_path) if case_path else ({}, {"case_id": "case", "contract": {}, "base": os.getcwd()})
    contract = ctx.get("contract") or {}
    case_id = ctx.get("case_id", "case")
    pdf = pdf or ctx.get("paper")

    if not pdf or not os.path.exists(pdf):
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, "failed",
                       {"reason": "no_pdf", "expected": "/input/*.pdf"},
                       uncertainty=[{"item": "input pdf not found",
                                     "impact": "no notes can be produced"}],
                       contract=contract)
        print(json.dumps({"status": "failed", "reason": "no_pdf", "out": out_dir},
                         ensure_ascii=False))
        return 2

    try:
        doc = pk.PDFDoc(pdf, max_pages=max_pages)
    except RuntimeError as e:
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, "failed",
                       {"reason": str(e), "source": os.path.basename(pdf)},
                       uncertainty=[{"item": f"pdf unreadable: {e}",
                                     "impact": "no notes can be produced"}],
                       contract=contract)
        print(json.dumps({"status": "failed", "reason": str(e), "out": out_dir},
                         ensure_ascii=False))
        return 2

    blocks, tabs, figs = nk.build_blocks(doc)
    chars = sum(len(b["text"]) for b in blocks)
    scanned = [p.number + 1 for p in doc.pages if len(p.get_text().strip()) < 40]

    uncertainty = []
    if chars < 250:
        write_json(os.path.join(out_dir, "notes.json"),
                   {"case_id": case_id, "status": "failed", "reason": "no_text_layer"})
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, "failed",
                       {"reason": "no_text_layer", "chars": chars, "scanned_pages": scanned},
                       uncertainty=[{"item": "pdf has no usable text layer",
                                     "impact": "notes require OCR first; nothing is invented"}],
                       contract=contract)
        print(json.dumps({"status": "failed", "reason": "no_text_layer", "chars": chars,
                          "scanned_pages": scanned, "out": out_dir}, ensure_ascii=False))
        return 2

    pre_title = doc.detect_title() or nk.fallback_title(doc)
    nk.clean_headings(blocks, pre_title)
    m = nk.meta(blocks, doc)
    sections = nk.sectionize(blocks)
    notes = nk.collect(blocks, sections, m["title"])
    conc = nk.concepts(blocks)
    by_id = {b["id"]: b for b in blocks}

    checked, valid, bad = nk.anchor_check(
        {"sections": [r for rows in notes["sections"].values() for r in rows],
         **{k: notes[k] for k in ("research_question", "data", "conditions", "findings", "limitations")}},
        by_id)

    field_cov = {
        "structure": len(sections) >= 3,
        "research_question": bool(notes["research_question"]),
        "data": bool(notes["data"]),
        "conditions": bool(notes["conditions"]),
        "findings": bool(notes["findings"]),
        "limitations": bool(notes["limitations"]),
        "concepts": bool(conc),
    }
    captions = [{"label": t.get("label", ""), "caption": t.get("caption", ""),
                 "page": t.get("page"), "kind": "table"} for t in tabs]
    captions += [{"label": f.get("label", ""), "caption": f.get("caption", ""),
                  "page": f.get("page"), "kind": "figure"} for f in figs]

    check = {
        "schema": "noteskit/check/v1",
        "pages": doc.page_count,
        "blocks": len(blocks),
        "chars": chars,
        "sections": len(sections),
        "section_titles": [s["title"] for s in sections],
        "headings_from_paper": sum(1 for b in blocks if b["heading"]),
        "note_counts": {k: len(v) for k, v in notes.items() if isinstance(v, list)},
        "anchor_checked": checked,
        "anchor_valid": valid,
        "anchor_invalid_examples": bad,
        "field_coverage": field_cov,
        "tables": len(tabs),
        "figures": len(figs),
        "scanned_pages": scanned,
        "title": m["title"], "authors": m["authors"],
        "warnings": list(doc.warnings),
    }

    if scanned:
        uncertainty.append({"item": f"pages without text layer: {scanned}",
                            "impact": "those pages contribute no notes; OCR required"})
    if len(sections) < 3:
        uncertainty.append({"item": "few or no section headings detected",
                            "impact": "notes follow the detected blocks, not a paper outline"})
    for k, ok in field_cov.items():
        if not ok:
            uncertainty.append({"item": f"field not found: {k}",
                                "impact": "the paper may not report it, or it is phrased unusually; "
                                          "reviewer should check the corresponding section"})
    if checked and valid < checked:
        uncertainty.append({"item": f"{checked - valid} anchors did not match their block verbatim",
                            "impact": "those notes must be checked by hand; see check.json"})

    md = nk.render_md(m, sections, notes, conc, check, by_id)
    md_path = os.path.join(out_dir, "notes.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    notes_obj = {"schema": "noteskit/notes/v1", "case_id": case_id, "paper": m,
                 "sections": [{"id": s["id"], "title": s["title"], "level": s["level"],
                               "page": s["page"], "blocks": s["blocks"],
                               "notes": notes["sections"].get(s["id"], [])} for s in sections],
                 "fields": {k: notes[k] for k in ("research_question", "data", "conditions",
                                                  "findings", "limitations")},
                 "captions": captions}
    notes_path = write_json(os.path.join(out_dir, "notes.json"), notes_obj)
    conc_path = write_json(os.path.join(out_dir, "concepts.json"),
                           {"schema": "noteskit/concepts/v1", "count": len(conc), "items": conc})
    anchors = [dict(n["anchor"], section=s["id"], kind="section_note")
               for s in sections for n in notes["sections"].get(s["id"], [])]
    for k in ("research_question", "data", "conditions", "findings", "limitations"):
        anchors += [dict(n["anchor"], field=k, kind="field") for n in notes[k]]
    anchors_path = write_json(os.path.join(out_dir, "anchors.json"),
                              {"schema": "noteskit/anchors/v1", "count": len(anchors),
                               "items": anchors})
    index_path = write_json(os.path.join(out_dir, "index.json"),
                            {"schema": "noteskit/index/v1", "blocks": len(blocks),
                             "tokens": nk.build_index(blocks)})
    check_path = write_json(os.path.join(out_dir, "check.json"), check)

    covered = sum(1 for s in sections if notes["sections"].get(s["id"]))
    hit_rate = (valid / checked) if checked else 0.0
    status = "ok" if (hit_rate >= 0.995 and len(sections) >= 3 and
                      int(field_cov["findings"]) + int(field_cov["data"]) >= 1) else "partial"
    primary = {
        "notes": "notes.md",
        "notes_json": "notes.json",
        "anchors": "anchors.json",
        "concepts": "concepts.json",
        "paper": m,
        "sections": len(sections),
        "sections_with_notes": covered,
        "notes_total": sum(len(v) for v in notes["sections"].values()),
        "findings": len(notes["findings"]),
        "concepts": len(conc),
        "anchor_hit_rate": round(hit_rate, 4),
        "fields_found": [k for k, v in field_cov.items() if v],
    }
    evidence = [{"page": n["anchor"]["page"], "kind": k, "block": n["anchor"]["block"],
                 "quote": n["anchor"]["quote"]}
                for k in ("research_question", "findings", "conditions", "limitations")
                for n in notes[k]][:40]

    pk.emit_result(os.path.join(out_dir, "result.json"), case_id, status, primary,
                   evidence=evidence, uncertainty=uncertainty,
                   artifacts=[(md_path, "notes_markdown", "text/markdown"),
                              (notes_path, "notes_json", "application/json"),
                              (conc_path, "concepts", "application/json"),
                              (anchors_path, "anchors", "application/json"),
                              (index_path, "search_index", "application/json"),
                              (check_path, "self_check", "application/json")],
                   contract=contract)
    print(json.dumps({"status": status, "sections": len(sections), "notes": primary["notes_total"],
                      "findings": primary["findings"], "concepts": len(conc),
                      "anchor_hit_rate": primary["anchor_hit_rate"], "out": out_dir},
                     ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--max-pages", type=int, default=80)
    args = ap.parse_args()
    case = args.case if args.case and os.path.exists(args.case) else None
    return build(case, args.pdf, args.out, args.max_pages)


if __name__ == "__main__":
    sys.exit(main())
