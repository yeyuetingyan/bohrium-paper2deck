#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tex_assemble —— LaTeX Skill 的第三步：硬核验 + （有引擎时）真实编译 + 导出。

用法：
    python tex_assemble.py --case /input/case.json --work /app/work [--out /app/output]
                           [--revised revised.tex] [--changes changes.jsonl]
                           [--diagnosis diagnosis.json] [--checklist checklist.json]
                           [--source-map source_map.json] [--compile] [--engine xelatex]
                           [--max-passes 4] [--timeout 180]

核验分两组：
  A. 静态（无引擎也能跑）：结构、引用/文献、数值守恒、模板必填项、改动登记、
     来源映射、编译计划完整性、诊断覆盖度；
  B. 编译（有引擎才跑）：多轮编译 + bibtex/biber，解析日志到 文件:行号 + 根因，
     核对产物（PDF/日志/页数），失败时给出分类与修法。
没有引擎时不假装成功：status 记 not_attempted 并说明原因。
"""

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import texkit as tk  # noqa: E402

VERSION = "tex_assemble/1.0"

REVISED_CANDIDATES = ("revised.tex", "main_revised.tex", "manuscript_revised.tex", "polished.tex")
CHANGES_CANDIDATES = ("changes.jsonl", "changes.json", "edits.jsonl", "diffs.jsonl")
DIAG_CANDIDATES = ("diagnosis.json", "diagnostics.json", "issues.json")
CHECKLIST_CANDIDATES = ("checklist.json", "template_checklist.json", "elements.json")
SOURCEMAP_CANDIDATES = ("source_map.json", "mapping.json", "sources.json")
PLAN_CANDIDATES = ("compile_plan.json", "build_plan.json", "plan.json")

CHANGE_KINDS = ("fix_error", "template", "structure", "math", "table", "citation", "reference",
                "encoding", "package", "format", "wording", "other")
DIAG_STATES = ("fixed", "accepted", "needs_confirm", "unfixed")

MIN_REASON_CHARS = 6
MIN_QUOTE_CHARS = 8
# 这些“引文”其实是指向交付稿内部锚点的指针（标签/公式/图表/引用号），不参与逐字核对
ANCHOR_KINDS = ("label", "anchor", "formula_ref", "figure", "table_ref", "crossref", "ref", "citation")


def pick(explicit, candidates, work):
    if explicit and os.path.exists(explicit):
        return explicit
    for c in candidates:
        p = os.path.join(work, c)
        if os.path.exists(p):
            return p
    return None


def load_any(path):
    if not path or not os.path.exists(path):
        return None
    if path.lower().endswith(".jsonl"):
        return tk.load_jsonl(path)
    if path.lower().endswith(".json"):
        d = tk.read_json(path)
        return None if "__load_error__" in d else d
    txt, _ = tk.read_text_any(path)
    return txt


def find_info(info, labels, n):
    """issue info → {file,line}（在原文里找到文本时补行号）。"""
    src = labels.get("source_text") or ""
    line = None
    if info and src:
        idx = src.find(info)
        if idx >= 0:
            line = tk.line_of_index(src, idx)[0]
    return {"evidence": info or "", "line": line, "fuzzy": info or ("#%d" % n)}


def iss(issues, level, kind, where, detail, hint=""):
    row = {"level": level, "kind": kind, "detail": detail}
    if where:
        row.update({k: v for k, v in where.items() if v not in (None, "")})
    if hint:
        row["hint"] = hint
    issues.append(row)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="LaTeX 工程核验与编译（第三步）")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--revised")
    ap.add_argument("--changes")
    ap.add_argument("--diagnosis")
    ap.add_argument("--checklist")
    ap.add_argument("--source-map")
    ap.add_argument("--plan")
    ap.add_argument("--engine", default=None)
    ap.add_argument("--max-passes", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--compile", dest="do_compile", action="store_true", default=True)
    ap.add_argument("--no-compile", dest="do_compile", action="store_false")
    args = ap.parse_args(argv)

    out = args.out
    work = args.work
    os.makedirs(out, exist_ok=True)
    issues = []
    metrics = {}

    # ---- 载入 prep 产物 ----
    prep_p = os.path.join(work, "prep.json")
    prep = tk.read_json(prep_p) if os.path.exists(prep_p) else {}
    project = tk.read_json(os.path.join(work, "project.json")) if os.path.exists(os.path.join(work, "project.json")) else {}
    labels_info = tk.read_json(os.path.join(work, "labels.json")) if os.path.exists(os.path.join(work, "labels.json")) else {}
    citations_info = tk.read_json(os.path.join(work, "citations.json")) if os.path.exists(os.path.join(work, "citations.json")) else {}
    bib_doc = tk.read_json(os.path.join(work, "bib.json")) if os.path.exists(os.path.join(work, "bib.json")) else {"entries": []}
    locked_numbers = tk.read_json(os.path.join(work, "numbers.json")) if os.path.exists(os.path.join(work, "numbers.json")) else {}
    prep_issues = tk.load_jsonl(os.path.join(work, "issues.jsonl"))
    checklist_draft = tk.read_json(os.path.join(work, "checklist_draft.json")) if os.path.exists(os.path.join(work, "checklist_draft.json")) else {}

    case, ctx = (tk.load_case(args.case) if os.path.exists(args.case) else ({}, {"case_id": "unknown"}))

    # ---- 载入 Agent 交付物 ----
    p_rev = pick(args.revised, REVISED_CANDIDATES, work)
    p_chg = pick(args.changes, CHANGES_CANDIDATES, work)
    p_diag = pick(args.diagnosis, DIAG_CANDIDATES, work)
    p_chk = pick(args.checklist, CHECKLIST_CANDIDATES, work)
    p_map = pick(args.source_map, SOURCEMAP_CANDIDATES, work)
    p_plan = pick(args.plan, PLAN_CANDIDATES, work)

    revised_text = load_any(p_rev) if p_rev else None
    changes = load_any(p_chg) if p_chg else None
    diagnosis = load_any(p_diag) if p_diag else None
    checklist = load_any(p_chk) if p_chk else None
    smap = load_any(p_map) if p_map else None
    plan = load_any(p_plan) if p_plan else None

    if not revised_text or not revised_text.strip():
        iss(issues, "high", "revised_missing", {}, "没有交付 revised.tex（或文件为空）",
            "给出改好的主文件全文，供平台直接编译。")

    # ---- A1 结构 ----
    main_src = revised_text or ""
    dc = tk.document_class(main_src)
    if not dc:
        iss(issues, "high", "no_documentclass", {}, "revised.tex 里没有 \\documentclass",
            "补上文档类声明（若原本是子文件，应交付可独立编译的主文件）。")
    pkgs = tk.packages(main_src)
    metrics["packages"] = len(pkgs)
    for b in tk.brace_balance(main_src):
        iss(issues, "high", "brace_unbalanced", {"line": b.get("line")},
            "花括号不配对（%s）" % b.get("char"), "定位该行补齐括号。")
    _envs, env_problems = tk.environments(main_src)
    for p in env_problems:
        iss(issues, "high", p["kind"], {"line": p.get("line")}, "环境 %s 未配对" % p.get("env"),
            "\\begin/\\end 必须成对。")
    n_inputs = tk.inputs(main_src)
    if n_inputs:
        iss(issues, "medium", "unresolved_input_in_deliverable", {"line": n_inputs[0]["line"]},
            "交付的 main.tex 里仍有 %d 处 \\input/\\include" % len(n_inputs),
            "若目标文件没随包交付，编译会失败；建议把内容内联成可独立编译的单文件。")
    metrics["inputs_in_deliverable"] = len(n_inputs)
    metrics["environments"] = len(_envs)

    # ---- A2 引用 / 文献 ----
    bib_entries = (bib_doc or {}).get("entries") or []
    bib_keys = {e["key"] for e in bib_entries}
    labels = tk.labels(main_src)
    refs = tk.refs(main_src)
    cites = tk.citations(main_src)
    label_keys = {l["key"] for l in labels}
    for r in refs:
        if r["key"] not in label_keys:
            iss(issues, "high", "undefined_ref", {"line": r["line"]},
                "\\%s{%s} 找不到 label" % (r["command"], r["key"]), "补 \\label 或改键名。")
    for c in cites:
        if c["key"] not in bib_keys:
            iss(issues, "high", "undefined_citation", {"line": c["line"]},
                "\\%s{%s} 不在文献库" % (c["command"], c["key"]),
                "补 bib 条目或修正键名；若是内联 thebibliography，请确认 \\bibitem 键存在。")
    used = {r["key"] for r in refs}
    for l in labels:
        if l["key"] not in used:
            iss(issues, "low", "unused_label", {"line": l["line"]}, "label %s 未被引用" % l["key"], "删除或补引用。")
    cited = {c["key"] for c in cites}
    for e in bib_entries:
        if e["key"] not in cited:
            iss(issues, "low", "uncited_bib_entry", {}, "文献 %s 未被引用" % e["key"], "引用或删除。")
    metrics.update({"labels": len(labels), "refs": len(refs), "citations": len(cites),
                    "bib_entries": len(bib_entries)})
    if not cites and not bib_entries:
        iss(issues, "medium", "no_citations", {}, "改后文件既没有引用也没有文献库",
            "学术稿件通常至少引用若干文献；确认是否漏交 references.bib。")

    # ---- A3 数值与不可变成分守恒 ----
    # 账本口径：主文件的不可变成分（改前）。子文件（\input 进来的 sections/*.tex）由 Agent 决定
    # 是内联进 revised.tex 还是照样交付，所以它们不参与"缺少"判定，只参与"新增"判定。
    if isinstance(locked_numbers, dict) and "main" in locked_numbers:
        before = locked_numbers.get("main") or {}
        scope_note = "主文件 %s" % (locked_numbers.get("main_file") or "main.tex")
    else:
        before = locked_numbers if isinstance(locked_numbers, dict) else {}
        scope_note = "全部 .tex 文件（旧版账本）"
    after = tk.protected_spans(main_src)
    metrics["protected_scope"] = scope_note
    changed, added, dropped = [], [], []
    for kind, vals in before.items():
        a = after.get(kind) or []
        for v in vals:
            if tk.flat(v) not in {tk.flat(x) for x in a}:
                (dropped if kind in ("number", "citation", "crossref", "formula") else changed).append("%s:%s" % (kind, v))
    for kind, vals in after.items():
        b = before.get(kind) or []
        for v in vals:
            if tk.flat(v) not in {tk.flat(x) for x in b}:
                added.append("%s:%s" % (kind, v))
    metrics["protected_before"] = sum(len(v) for v in before.values())
    metrics["protected_after"] = sum(len(v) for v in after.values())
    metrics["protected_dropped"] = len(dropped)
    metrics["protected_added"] = len(added)
    declared = set()
    if isinstance(changes, list):
        for ch in changes:
            for key in ("before", "after", "value", "numbers"):
                v = ch.get(key)
                if isinstance(v, str):
                    declared.add(tk.flat(v))
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            declared.add(tk.flat(x))
    declared_blob = "||".join(sorted(declared))
    for d in dropped:
        v = d.split(":", 1)[1]
        if not (tk.flat(v) and tk.flat(v) in declared_blob):
            iss(issues, "high", "protected_dropped_undeclared", {},
                "改后缺少原本存在的不可变成分：%s" % d,
                "数值/引用/公式不得悄悄消失；若确实要删，请在 changes.jsonl 里登记理由。")
    for a in added:
        v = a.split(":", 1)[1]
        if not (tk.flat(v) and tk.flat(v) in declared_blob):
            iss(issues, "medium", "protected_added_undeclared", {},
                "改后新增了材料里没有的不可变成分：%s" % a,
                "新增数值/引用必须在 changes.jsonl 里给出依据。")

    # ---- A4 模板必填项 ----
    template_items = (checklist_draft or {}).get("items") or []
    cl_items = None
    if isinstance(checklist, dict):
        cl_items = checklist.get("items") or checklist.get("requirements") or checklist.get("checklist")
    if cl_items is None and template_items:
        iss(issues, "medium", "checklist_missing", {}, "没有交付 checklist.json（模板必填项对照）",
            "逐条对照模板要求，标注 present/missing 与证据。")
    else:
        got_ids = {str(i.get("id") or i.get("requirement")) for i in (cl_items or []) if isinstance(i, dict)}
        for it in template_items:
            if it.get("present"):
                continue
            if not (got_ids & {str(it.get("id")), str(it.get("requirement"))}):
                iss(issues, "medium", "template_item_unaddressed", {},
                    "模板必填项 %s 在改后文件里仍缺失，且清单里没有说明" % it.get("requirement"),
                    "补齐该项，或在 checklist.json 里写明缺失原因与待确认。")
    metrics["template_items"] = len(template_items)
    metrics["template_missing"] = len([i for i in template_items if not i.get("present")])

    # ---- A5 改动登记 ----
    if changes is None:
        iss(issues, "high", "changes_missing", {}, "没有交付 changes.jsonl（逐处改动说明）",
            "每处改动一条：before/after/kind/reason。")
    else:
        rows = changes if isinstance(changes, list) else changes.get("changes") or []
        if not rows:
            # 交付了文件但一条改动都没有 —— 与“没交付”同样是 high：
            # 题面要求逐处修改说明，空清单等于没有说明。
            iss(issues, "high", "changes_missing", {"rows": 0},
                "changes.jsonl 里没有任何改动记录（空清单）",
                "每处改动一条：before/after/kind/reason。")
        bad_kind = 0
        short_reason = 0
        not_found = 0
        for n, ch in enumerate(rows, 1):
            if not isinstance(ch, dict):
                iss(issues, "high", "change_row_invalid", {}, "第 %d 条改动不是对象" % n, "")
                continue
            k = ch.get("kind") or ch.get("type")
            if k not in CHANGE_KINDS:
                bad_kind += 1
            rs = ch.get("reason") or ""
            if len(rs.strip()) < MIN_REASON_CHARS:
                short_reason += 1
        if bad_kind:
            iss(issues, "medium", "change_kind_unknown", {}, "%d 条改动的 kind 不在约定集合内" % bad_kind,
                "kind 取 %s。" % "/".join(CHANGE_KINDS))
        if short_reason:
            iss(issues, "low", "change_reason_too_short", {}, "%d 条改动的 reason 太短" % short_reason,
                "写清为什么改（>=%d 字符）。" % MIN_REASON_CHARS)
        metrics["changes"] = len(rows)
    metrics.setdefault("changes", 0)

    # ---- A6 来源映射 ----
    if smap is None:
        iss(issues, "medium", "source_map_missing", {}, "没有交付 source_map.json",
            "给数值/论断的来源定位，便于评审回溯。")
    else:
        rows = smap if isinstance(smap, list) else smap.get("items") or smap.get("mappings") or []
        # 材料原文集合（引文必须能在材料里逐字找到 —— “对得上/追得回”是本题的硬要求）
        mat_hard = ""
        mat_names = set()
        for f in tk._as_list(ctx.get("material_paths")):
            mat_names.add(os.path.basename(os.path.abspath(f)).lower())
            try:
                with open(os.path.abspath(f), "r", encoding="utf-8", errors="replace") as fh:
                    mat_hard += "\n" + tk.norm_hard(fh.read())
            except Exception:  # noqa: BLE001
                continue
        deliv_hard = tk.norm_hard(main_src or "")
        no_quote = 0
        fake_quote = 0
        for n, m in enumerate(rows, 1):
            if not isinstance(m, dict):
                continue
            q = m.get("quote") or m.get("evidence") or m.get("text")
            if not q or len(str(q).strip()) < MIN_QUOTE_CHARS:
                no_quote += 1
                continue
            src_name = os.path.basename(str(m.get("source") or m.get("file") or "")).lower()
            kind = str(m.get("kind") or m.get("type") or "").lower()
            qh = tk.norm_hard(str(q))
            # 指向锚点（标签/公式/图表/引用号）的映射只是“指针”，不要求逐字；
            # 其余映射（数值、论断、事实）必须能在材料或交付稿里逐字找到。
            if kind in ANCHOR_KINDS:
                continue
            if mat_hard and deliv_hard:
                if qh not in mat_hard and qh not in deliv_hard:
                    fake_quote += 1
            elif mat_hard and qh not in mat_hard:
                fake_quote += 1
        metrics["source_map_items"] = len(rows)
        if no_quote:
            iss(issues, "low", "source_map_quote_missing", {}, "%d 条映射缺少引文" % no_quote, "补逐字引文。")
        if fake_quote:
            iss(issues, "high", "source_map_quote_not_in_material", {"count": fake_quote},
                "%d 条映射的引文在材料里找不到（引文必须逐字来自材料）" % fake_quote,
                "回到材料里复制原文片段，别改写或凭记忆写。")

    # ---- A7 诊断 ----
    if diagnosis is None:
        iss(issues, "medium", "diagnosis_missing", {}, "没有交付 diagnosis.json（逐条根因与修法）",
            "把 prep 发现的问题逐条给根因、修法与状态。")
    else:
        items = diagnosis if isinstance(diagnosis, list) else diagnosis.get("items") or diagnosis.get("issues") or []
        seen = []
        for n, it in enumerate(items, 1):
            if not isinstance(it, dict):
                continue
            seen.append(str(it.get("kind") or ""))
            st = it.get("state") or it.get("status")
            if st not in DIAG_STATES:
                iss(issues, "low", "diagnosis_state_unknown", {}, "第 %d 条诊断的 state=%s 不在约定集合" % (n, st),
                    "state 取 %s。" % "/".join(DIAG_STATES))
        highs = [i for i in prep_issues if i.get("level") == "high"]
        unhandled = [i.get("kind") for i in highs if i.get("kind") not in seen]
        metrics["prep_high"] = len(highs)
        metrics["diagnosis_items"] = len(items)
        metrics["diagnosis_unhandled_high"] = len(unhandled)
        if unhandled:
            iss(issues, "high", "prep_high_unaddressed", {},
                "prep 发现的 high 问题没有出现在诊断里：%s" % "、".join(sorted(set(unhandled))[:8]),
                "每条 high 都要有处置（fixed / accepted / needs_confirm）。")

    # ---- A8 编译计划 ----
    if plan is None:
        iss(issues, "low", "compile_plan_missing", {}, "没有交付 compile_plan.json",
            "写明引擎、命令、轮次与预期产物，便于他人复现。")
    else:
        need = ("engine", "commands")
        miss = [k for k in need if not (plan.get(k) if isinstance(plan, dict) else None)]
        if miss:
            iss(issues, "medium", "compile_plan_incomplete", {}, "编译计划缺字段：%s" % "、".join(miss),
                "至少给出 engine 与 commands（含轮次）。")
        metrics["compile_plan_rounds"] = len((plan or {}).get("commands") or []) if isinstance(plan, dict) else 0

    # ---- B 编译 ----
    compile_report = {"status": "not_attempted", "reason": "compile_disabled"}
    tc = tk.detect_toolchain()
    if args.do_compile:
        if not tc.get("available"):
            compile_report = {"status": "not_attempted", "reason": "no_tex_engine",
                              "hint": "本机未安装 TeX 引擎（pdflatex/xelatex/lualatex/tectonic），"
                                      "未执行编译；在有 TeX 的环境或平台 latex-compiler 中可编译。",
                              "toolchain": {"available": False}}
            iss(issues, "low", "compile_not_attempted", {}, "本机无 TeX 引擎，未编译",
                "不伪造编译结果；交付物里的编译证据需在有引擎的环境补齐。")
        else:
            # 写一个临时工程目录
            proj = os.path.join(out, "_build")
            os.makedirs(proj, exist_ok=True)
            main_name = os.path.basename(p_rev or "main.tex")
            tk.dump_text(os.path.join(proj, main_name), main_src)
            for f in tk._as_list(ctx.get("material_paths")):
                src_p = os.path.abspath(f)
                if os.path.exists(src_p) and os.path.splitext(src_p)[1].lower() in (".bib", ".cls", ".sty", ".bst", ".png", ".jpg", ".pdf", ".eps"):
                    try:
                        with open(src_p, "rb") as fh:
                            data = fh.read()
                        with open(os.path.join(proj, os.path.basename(src_p)), "wb") as fh:
                            fh.write(data)
                    except Exception:  # noqa: BLE001
                        pass
            for extra in ("references.bib", "refs.bib"):
                wp = os.path.join(work, extra)
                if os.path.exists(wp):
                    with open(wp, "rb") as fh:
                        data = fh.read()
                    with open(os.path.join(proj, extra), "wb") as fh:
                        fh.write(data)
            compile_report = tk.compile_project(proj, main_name, engine=args.engine,
                                                max_passes=args.max_passes, timeout=args.timeout)
            tk.dump_text(os.path.join(out, "compile.log"), compile_report.get("log_text") or "")
            for e in compile_report.get("errors") or []:
                iss(issues, "high", "compile_error:%s" % e.get("category", "unknown"),
                    {"file": e.get("file"), "line": e.get("line")},
                    (e.get("hint") or e.get("message") or e.get("raw") or "")[:300],
                    e.get("fix") or "")
            w = compile_report.get("warnings") or {}
            if w.get("undefined_refs"):
                iss(issues, "high", "compile_undefined_refs", {},
                    "编译日志显示未定义引用：%s" % "、".join(w["undefined_refs"][:8]), "补 label 或多编译一轮。")
            if w.get("undefined_cites"):
                iss(issues, "high", "compile_undefined_cites", {},
                    "编译日志显示未定义引用文献：%s" % "、".join(w["undefined_cites"][:8]), "补 bib 条目。")
            if w.get("rerun"):
                iss(issues, "low", "compile_needs_rerun", {}, "日志提示 Rerun（交叉引用尚未收敛）", "再编译一轮。")
            if w.get("overfull"):
                worst = sorted(w["overfull"], key=lambda x: -x["pts"])[:3]
                iss(issues, "low", "compile_overfull", {},
                    "存在 %d 处 Overfull \\hbox（最大 %.1fpt）" % (len(w["overfull"]), worst[0]["pts"]),
                    "用列宽/换行调整，别靠缩放掩盖。")
            metrics["compile_status"] = compile_report.get("status")
            metrics["compile_pages"] = ((compile_report.get("artifacts") or {}).get("pdf_bytes") and
                                        ((compile_report.get("summary") or {}).get("pages")))
            metrics["compile_passes"] = len(compile_report.get("passes") or [])

    # ---- 状态 ----
    levels = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        levels[i["level"]] = levels.get(i["level"], 0) + 1
    metrics.update({"issues_high": levels["high"], "issues_medium": levels["medium"], "issues_low": levels["low"]})
    if not revised_text:
        status = "failed"
    elif levels["high"] == 0 and levels["medium"] == 0:
        status = "ok"
    else:
        status = "partial"

    # ---- 导出产物 ----
    art_dir = out
    if revised_text:
        tk.dump_text(os.path.join(art_dir, "revised.tex"), revised_text)
    tk.dump_json(os.path.join(art_dir, "compile.json"), {
        "status": compile_report.get("status"), "engine": compile_report.get("engine"),
        "reason": compile_report.get("reason"), "hint": compile_report.get("hint"),
        "passes": [{k: v for k, v in p.items() if k != "log_excerpt"} for p in (compile_report.get("passes") or [])],
        "artifacts": compile_report.get("artifacts") or {},
        "warnings": compile_report.get("warnings") or {},
        "toolchain": compile_report.get("toolchain") or {"available": bool(tc.get("available"))},
    })
    if isinstance(changes, list):
        tk.dump_jsonl(os.path.join(art_dir, "changes.jsonl"), changes)
    elif isinstance(changes, dict):
        tk.dump_json(os.path.join(art_dir, "changes.json"), changes)
    if isinstance(diagnosis, dict):
        tk.dump_json(os.path.join(art_dir, "diagnosis.json"), diagnosis)
    elif isinstance(diagnosis, list):
        tk.dump_json(os.path.join(art_dir, "diagnosis.json"),
                     {"schema": "tex-diagnosis/1.0", "items": diagnosis})
    if isinstance(checklist, dict):
        tk.dump_json(os.path.join(art_dir, "checklist.json"), checklist)
    if smap is not None:
        tk.dump_json(os.path.join(art_dir, "source_map.json"),
                     smap if isinstance(smap, dict) else {"schema": "tex-source-map/1.0", "items": smap})
    if isinstance(plan, dict):
        tk.dump_json(os.path.join(art_dir, "compile_plan.json"), plan)

    diff_md = ["# 改动说明\n"]
    if isinstance(changes, list) and changes:
        for n, ch in enumerate(changes, 1):
            diff_md.append("## %s %s" % (ch.get("change_id") or n, ch.get("kind") or ch.get("type") or ""))
            diff_md.append("- 文件：%s" % (ch.get("file") or "main.tex"))
            if ch.get("before"):
                diff_md.append("- 改前：`%s`" % str(ch["before"]).replace("\n", " ")[:200])
            if ch.get("after"):
                diff_md.append("- 改后：`%s`" % str(ch["after"]).replace("\n", " ")[:200])
            diff_md.append("- 理由：%s" % (ch.get("reason") or ""))
            diff_md.append("")
    else:
        diff_md.append("（没有交付 changes.jsonl，无法列出逐处改动）\n")
    tk.dump_text(os.path.join(art_dir, "diff.md"), "\n".join(diff_md))

    review = ["# 核验报告\n", "状态：**%s**（high %d / medium %d / low %d）\n" % (status, levels["high"], levels["medium"], levels["low"])]
    review.append("## 编译")
    review.append("- 状态：%s%s" % (compile_report.get("status"),
                                    ("（%s）" % compile_report.get("reason")) if compile_report.get("reason") else ""))
    review.append("- 引擎：%s" % (compile_report.get("engine") or "（未指定）"))
    art = compile_report.get("artifacts") or {}
    if art.get("pdf_bytes"):
        review.append("- 产物：PDF %d 字节，编译 %d 轮" % (art["pdf_bytes"], len(compile_report.get("passes") or [])))
    else:
        review.append("- 产物：无 PDF（未编译或编译失败）")
    review.append("\n## 问题清单")
    for i in issues:
        loc = (" %s:%s" % (i.get("file"), i.get("line"))) if i.get("line") else ""
        review.append("- [%s] %s%s：%s%s" % (i["level"], i["kind"], loc, i["detail"],
                                             (" → %s" % i["hint"]) if i.get("hint") else ""))
    review.append("\n## 核验边界")
    review.append("- 静态核验能证明引用/文献/括号/环境/数值守恒是否自洽，不能证明排版美观与期刊要求全部满足。")
    review.append("- 没有 TeX 引擎时不执行编译，也不会伪造编译成功；此项在报告里如实标注。")
    review.append("- 语义层面（论证是否合理、公式是否有物理意义）不在核验范围。")
    tk.dump_text(os.path.join(art_dir, "review.md"), "\n".join(review) + "\n")

    tk.dump_json(os.path.join(art_dir, "check.json"), {
        "status": status, "metrics": metrics, "issues": issues,
        "unresolved": [
            "编译是否通过取决于运行环境是否有 TeX 引擎；本报告如实标注 compile.status。",
            "论文用词、论证与公式语义不在自动核验范围。",
            "模板的完整合规性（页边距、字号、行距）需人工比对模板说明。",
        ]})

    artifacts = [a for a in [
        tk.file_record(os.path.join(art_dir, "revised.tex"), "final source"),
        tk.file_record(os.path.join(art_dir, "changes.jsonl"), "change log"),
        tk.file_record(os.path.join(art_dir, "diff.md"), "human readable diff"),
        tk.file_record(os.path.join(art_dir, "diagnosis.json"), "diagnosis"),
        tk.file_record(os.path.join(art_dir, "checklist.json"), "template checklist"),
        tk.file_record(os.path.join(art_dir, "source_map.json"), "source map"),
        tk.file_record(os.path.join(art_dir, "compile_plan.json"), "compile plan"),
        tk.file_record(os.path.join(art_dir, "compile.json"), "compile report"),
        tk.file_record(os.path.join(art_dir, "compile.log"), "compile log"),
        tk.file_record(os.path.join(art_dir, "check.json"), "verification"),
        tk.file_record(os.path.join(art_dir, "review.md"), "review"),
    ] if a]

    tk.emit_result(os.path.join(art_dir, "result.json"),
                   ctx.get("case_id") or prep.get("case_id") or "unknown",
                   status,
                   primary={
                       "summary": "LaTeX 工程核验完成：high %d / medium %d / low %d；编译状态 %s"
                                  % (levels["high"], levels["medium"], levels["low"], compile_report.get("status")),
                       "status_detail": "%s; compile=%s" % (status, compile_report.get("status")),
                       "compile_status": compile_report.get("status"),
                       "engine": compile_report.get("engine"),
                       "issues_high": levels["high"],
                       "change_log": "changes.jsonl",
                   },
                   evidence=[{"kind": "prep", "path": "prep.json", "counts": (prep or {}).get("counts")},
                             {"kind": "compile", "status": compile_report.get("status"),
                              "engine": compile_report.get("engine")}],
                   uncertainty=[
                       "编译结果只代表本环境；无引擎环境下不伪造编译成功。",
                       "语义正确性与期刊格式的完整合规需人工确认。",
                   ],
                   artifacts=artifacts, contract=ctx.get("contract") or {},
                   extra_top={"issues": issues})
    print(tk.pjson({"status": status, "high": levels["high"], "medium": levels["medium"],
                    "low": levels["low"], "compile": compile_report.get("status")}))
    return 0 if status in ("ok", "partial") else 2


if __name__ == "__main__":
    sys.exit(main())
