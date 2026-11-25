#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作04｜参考文献与引用管理：正文—文献库一致性核验与重排。

用法：
  python run_cite.py --case /input/case.json --out /app/output
  python run_cite.py --manuscript paper.md --library refs.bib --out out

产物：
  manuscript_revised.*   重排编号后的稿件（numeric 样式；其余样式原样保留并说明）
  references_gbt7714.txt 按 GB/T 7714—2015 生成的文末表（按新编号排序）
  references_deduped.bib 去重后的 BibTeX（便于回填文献管理器）
  citation_map.json      旧编号 → 新编号、key → 序号、合并记录
  check.json             悬空引用、未被引用、重复 DOI、字段缺失、待补引用候选
  result.json            结构化结果
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import citekit as ck
import paperkit as pk

DOC_KEYS = ("manuscript_path", "manuscript", "doc", "document", "paper_path", "paper", "draft")
LIB_KEYS = ("library_path", "library", "bibliography", "bib", "refs", "references")


def read_docx_text(path):
    """不依赖 python-docx：直接读 word/document.xml 的段落文本。"""
    out = []
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S)
        if texts:
            out.append(pk.norm("".join(texts)))
    return "\n\n".join(out)


def load_manuscript(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return read_docx_text(path), "md", "docx"
    text = open(path, encoding="utf-8", errors="replace").read()
    out_ext = {".md": "md", ".tex": "tex", ".txt": "txt"}.get(ext, "txt")
    return text, out_ext, ext.lstrip(".")


def find_inputs(ctx):
    case = ctx.get("case") or {}
    doc = None
    for k in DOC_KEYS:
        v = case.get(k) or (case.get("input") or {}).get(k) if isinstance(case.get("input"), dict) else case.get(k)
        if isinstance(v, str) and v:
            cand = v if os.path.isabs(v) else os.path.join(ctx["base"], v)
            if os.path.exists(cand):
                doc = cand
                break
    libs = []
    for k in LIB_KEYS:
        v = case.get(k)
        if isinstance(v, str) and v:
            cand = v if os.path.isabs(v) else os.path.join(ctx["base"], v)
            if os.path.exists(cand):
                libs.append(cand)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    cand = item if os.path.isabs(item) else os.path.join(ctx["base"], item)
                    if os.path.exists(cand):
                        libs.append(cand)
    if not doc:
        cands = pk.find_files(ctx["base"], (".md", ".txt", ".tex", ".docx"))
        cands = [c for c in cands if not c.lower().endswith((".bib", ".ris"))]
        doc = cands[0] if cands else None
    if not libs:
        libs = pk.find_files(ctx["base"], (".bib", ".ris"))
        if not libs:
            libs = [p for p in pk.find_files(ctx["base"], (".txt",))
                    if re.search(r"^\s*\[?\d{1,3}[\].、]", open(p, encoding="utf-8", errors="replace").read(), re.M)][:1]
    return doc, libs


def candidate_sentences(text):
    """带数字/比较断言、却没有引用标记的句子——提示人工确认是否漏引。"""
    out = []
    for m in re.finditer(r"[^。\n]{0,160}(?:\d+(?:\.\d+)?%?|显著|提高|降低|优于|significantly|increase|decrease|outperform)[^。\n]{0,160}[。.]", text):
        s = pk.norm(m.group(0))
        if len(s) < 20 or ck.AY_CITE_RE.search(s) or ck.NUM_CITE_RE.search(s) or ck.TEX_CITE_RE.search(s):
            continue
        out.append({"offset": m.start(), "sentence": s[:220]})
        if len(out) >= 30:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--manuscript", default=None)
    ap.add_argument("--library", action="append", default=None)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--format", default="gbt7714", choices=["gbt7714", "plain"])
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    case_path = args.case if args.case and os.path.exists(args.case) else None
    _, ctx = pk.load_case(case_path) if case_path else ({}, {"case_id": "case", "contract": {}, "base": os.getcwd()})
    contract = ctx.get("contract") or {}
    case_id = ctx.get("case_id", "case")

    doc_path, lib_paths = (args.manuscript, args.library or []) if args.manuscript else find_inputs(ctx)
    if not doc_path or not os.path.exists(doc_path):
        pk.emit_result(os.path.join(args.out, "result.json"), case_id, "failed",
                       {"reason": "no_manuscript", "searched": ctx.get("base")},
                       uncertainty=[{"item": "manuscript not found", "impact": "nothing to check"}],
                       contract=contract)
        return 2

    text, out_ext, in_ext = load_manuscript(doc_path)
    entries = ck.load_library(lib_paths)
    uncertainty = []
    if not entries:
        uncertainty.append({"item": "no bibliography parsed",
                            "impact": "citation resolution impossible; numbers left untouched"})

    merged, groups = ck.dedupe(entries) if entries else ([], [])
    cits = ck.scan_citations(text)
    styles = sorted({c["kind"] for c in cits})
    style = "numeric" if "numeric" in styles else ("latex" if "latex" in styles else
                                                   ("author-year" if "author-year" in styles else "none"))

    mapping, unresolved, order = {}, [], []
    revised, map_rows = text, []
    by_old = {}
    for e in merged:
        for a in (e.get("aliases") or []):
            if a:
                by_old[a] = e
    if style == "numeric" and merged:
        revised, mapping, unresolved, order = ck.renumber(text, cits, by_old)
        for idx, new in sorted(mapping.items(), key=lambda kv: kv[1]):
            e = merged[idx - 1]
            map_rows.append({"old": e.get("old_index"), "new": new, "key": e.get("key"),
                             "title": e["fields"].get("title", "")[:90]})
    elif style == "latex" and merged:
        by_key = {e.get("key"): e for e in merged}
        for c in cits:
            for k in c.get("keys", []):
                if k not in by_key:
                    unresolved.append(k)
                elif k not in mapping:
                    mapping[k] = len(order) + 1
                    order.append(k)
    elif style == "author-year" and merged:
        for c in cits:
            surname, year = c["authors"][0].lower(), c["year"]
            hit = [e for e in merged
                   if year == str(e["fields"].get("year", ""))
                   and surname in (e["fields"].get("author", "") or "").lower()]
            if not hit:
                unresolved.append(f"{c['authors'][0]} {year}")
            elif hit[0]["index"] not in mapping.values():
                mapping[hit[0]["index"]] = len(order) + 1
                order.append(hit[0]["index"])

    # 输出稿件
    revised_path = os.path.join(args.out, f"manuscript_revised.{out_ext}")
    with open(revised_path, "w", encoding="utf-8") as f:
        f.write(revised)

    # 文末表：numeric/latex 按新编号排序，其余保持原序
    if style in ("numeric", "latex") and order:
        if style == "numeric":
            ordered = [merged[i - 1] for i in order]
        else:
            by_key = {e.get("key"): e for e in merged}
            ordered = [by_key[k] for k in order if k in by_key]
    else:
        ordered = merged
    ref_lines = []
    for i, e in enumerate(ordered, 1):
        if args.format == "gbt7714":
            ref_lines.append(f"[{i}] {ck.format_gbt7714(e)}")
        else:
            ref_lines.append(f"[{i}] {e['fields'].get('author','')}. {e['fields'].get('title','')}. "
                             f"{e['fields'].get('journal','')}, {e['fields'].get('year','')}.")
    refs_path = os.path.join(args.out, "references_gbt7714.txt" if args.format == "gbt7714" else "references.txt")
    with open(refs_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ref_lines) + "\n")

    bib_path = os.path.join(args.out, "references_deduped.bib")
    with open(bib_path, "w", encoding="utf-8") as f:
        for e in ordered:
            f.write(render_bib(e) + "\n\n")

    report = ck.check_entries(merged, cits, mapping, unresolved, groups)
    report["style"] = style
    report["input_format"] = in_ext
    report["candidates_needing_citation"] = candidate_sentences(text)
    map_path = os.path.join(args.out, "citation_map.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({"style": style, "renumbered": map_rows, "merged": groups,
                   "order": order, "unresolved": unresolved}, f, ensure_ascii=False, indent=1)

    check = {"schema": "citekit/check/v1", **report}
    check_path = os.path.join(args.out, "check.json")
    with open(check_path, "w", encoding="utf-8") as f:
        json.dump(check, f, ensure_ascii=False, indent=1)

    if style == "docx" or in_ext == "docx":
        uncertainty.append({"item": "docx input converted to Markdown, original .docx not rewritten",
                            "impact": "apply the revised text back in Word; numbering map is provided"})
    if style == "author-year":
        uncertainty.append({"item": "author-year style kept as-is",
                            "impact": "no renumbering; only resolution check performed"})
    if style == "latex":
        uncertainty.append({"item": "LaTeX \\cite keys kept; numbering left to the bibliography style",
                            "impact": "use references_deduped.bib and citation_map.json to update the .bbl"})

    status = "ok"
    if not merged:
        status = "failed"
    elif report["status"] == "fail" or unresolved:
        status = "partial"

    evidence = [{"kind": "renumber", "old": r["old"], "new": r["new"],
                 "title": r["title"]} for r in map_rows[:20]]
    evidence += [{"kind": "dedupe", "kept": g.get("kept"), "merged": g.get("merged"),
                  "basis": g.get("basis")} for g in groups[:10]]

    pk.emit_result(os.path.join(args.out, "result.json"), case_id, status,
                   {"manuscript": os.path.basename(revised_path),
                    "references": os.path.basename(refs_path),
                    "citation_style": style,
                    "entries_in": len(entries),
                    "entries_after_dedupe": len(merged),
                    "duplicates_merged": len(groups),
                    "citations": len(cits),
                    "renumbered": len(map_rows),
                    "unresolved": len(unresolved),
                    "uncited": report["uncited"]},
                   evidence=evidence,
                   uncertainty=uncertainty,
                   artifacts=[(revised_path, "manuscript", "text/markdown"),
                              (refs_path, "bibliography", "text/plain"),
                              (bib_path, "bibliography_bibtex", "text/plain"),
                              (map_path, "citation_map", "application/json"),
                              (check_path, "self_check", "application/json")],
                   contract=contract,
                   extra_top={"check_summary": {k: report[k] for k in
                                                ("status", "n_entries", "n_cited", "dangling")}})
    print(json.dumps({"status": status, "style": style, "entries": len(entries),
                      "after_dedupe": len(merged), "citations": len(cits),
                      "renumbered": len(map_rows), "issues": len(report["issues"])},
                     ensure_ascii=False))
    return 0


def render_bib(e):
    f = dict(e.get("fields") or {})
    f.pop("_text", None)
    etype = e.get("type") or "misc"
    key = e.get("key") or "ref"
    lines = [f"@{etype}{{{key},"]
    for k, v in f.items():
        if v:
            lines.append(f"  {k} = {{{v}}},")
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
