#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tex_prep —— LaTeX 工程的第一步：确定性解析 + 问题清单（不调用任何模型）。

用法：
    python tex_prep.py --case /input/case.json --out /app/work

产出（全部写进 --out 目录）：
    files.json        工程文件清单（角色、大小、行数、编码）
    project.json      工程结构：documentclass、宏包与顺序、\\input 树、环境、表格、数学区域
    labels.json       标签与引用对账
    citations.json    引用与文献库对账
    bib.json          文献库条目
    numbers.json      不可变成分（数值/引用/标签/公式/URL/DOI）
    issues.jsonl      确定性发现的问题（带文件、行号、证据、建议）
    checklist_draft.json  模板必填项候选
    toolchain.json    TeX 工具链探测结果
    structure.md      人/Agent 读的工程概览（含必须保留的成分与问题清单）
    prep.json         {status, reason?, hint?, counts, next_step}
    prep_check.json   抽取自检

退出码：0 正常；2 材料不可用（reason 写在 prep.json）。
"""

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import texkit as tk  # noqa: E402

VERSION = "tex_prep/1.0"

ENV_ISSUE_LEVEL = {"unclosed_env": "high", "end_without_begin": "high"}

TEMPLATE_FIELDS = {
    "title": r"\\title\s*\{",
    "author": r"\\author\s*\{",
    "abstract": r"\\begin\s*\{abstract\}",
    "keywords": r"\\(keywords|begin\s*\{keywords\})",
    "maketitle": r"\\maketitle",
    "section": r"\\section\s*[\*{]?",
    "bibliography": r"\\(bibliography|addbibresource|begin\s*\{thebibliography\})",
}

PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|XXX|TBD|待补|待定|占位)\b", re.I)
HYPERREF_ORDER_NOTE = (
    "hyperref 通常应最后加载；cleveref 应在 hyperref 之后加载，否则交叉引用格式会失效。",
)


def read_project(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for n in sorted(names):
                    files.append(os.path.join(root, n))
        elif os.path.exists(p):
            files.append(p)
    seen = set()
    out = []
    for f in files:
        ap = os.path.abspath(f)
        if ap in seen:
            continue
        seen.add(ap)
        ext = os.path.splitext(f)[1].lower()
        text, note = ("", "")
        if ext in tk.TEXT_EXTS:
            text, note = tk.read_text_any(f)
        elif ext not in (".tex", ".bib", ".cls", ".sty", ".bst", ".png", ".jpg", ".jpeg",
                         ".pdf", ".eps", ".svg", ".log", ".aux", ".blg", ".bbl", ".gz", ".zip"):
            # 其它扩展名（.docx/.doc/.odt…）走通用读取，失败时给出 unreadable 说明，
            # 否则这类文件会被当成“无 note 的空文件”，把 unreadable 误判成 empty。
            text, note = tk.read_text_any(f)
        if not text and not note and os.path.getsize(ap) > 0:
            note = "unreadable:no_extractor"
        out.append({
            "path": ap,
            "rel": os.path.relpath(ap, os.path.dirname(paths[0]) if paths else ap),
            "ext": ext,
            "kind": ("tex" if ext == ".tex" else "bib" if ext == ".bib" else
                     "cls" if ext == ".cls" else "sty" if ext == ".sty" else
                     "log" if ext == ".log" else "other"),
            "text": text,
            "note": note,
            "lines": (text.count("\n") + 1) if text else 0,
        })
    return out


def pick_main(files, ctx):
    tex = [f for f in files if f["kind"] == "tex"]
    if not tex:
        return None
    # 1) magic root 2) 含 \documentclass 3) 名字像 main 4) 最长
    for f in tex:
        if tk.magic_root(f["text"]):
            root = tk.magic_root(f["text"])
            for g in tex:
                if os.path.basename(g["path"]) == os.path.basename(root):
                    return g
    with_dc = [f for f in tex if "\\documentclass" in f["text"]]
    if with_dc:
        with_dc.sort(key=lambda f: (-len(f["text"])))
        return with_dc[0]
    named = [f for f in tex if os.path.basename(f["path"]).lower() in
             ("main.tex", "paper.tex", "manuscript.tex", "article.tex", "document.tex", "ms.tex")]
    if named:
        return named[0]
    tex.sort(key=lambda f: -len(f["text"]))
    return tex[0]


def walk_inputs(main, files):
    """按 \\input/\\include 展开包含树，返回 (tree, missing)。"""
    by_name = {}
    for f in files:
        by_name[os.path.basename(f["path"])] = f
        by_name[os.path.splitext(os.path.basename(f["path"]))[0]] = f
    tree = []
    missing = []
    seen = set()

    def rec(node, depth):
        if depth > 8 or node["path"] in seen:
            return
        seen.add(node["path"])
        tree.append({"path": node["rel"], "depth": depth})
        for inc in tk.inputs(node["text"]):
            t = inc["target"]
            cand = by_name.get(os.path.basename(t)) or by_name.get(os.path.splitext(os.path.basename(t))[0])
            if not cand:
                missing.append({"target": t, "from": node["rel"], "line": inc["line"]})
                continue
            rec(cand, depth + 1)

    rec(main, 0)
    return tree, missing


def check_package_order(pkgs):
    names = [p["name"] for p in pkgs]
    issues = []
    if "hyperref" in names:
        idx = names.index("hyperref")
        after = [n for n in names[idx + 1:] if n in ("cleveref", "nameref")]
        if after:
            issues.append({"kind": "package_order", "level": "medium",
                           "detail": "%s 在 hyperref 之后加载" % "、".join(after),
                           "hint": HYPERREF_ORDER_NOTE[0]})
        later = [n for n in names[idx + 1:] if n in ("geometry", "babel", "polyglossia", "fontenc")]
        if later:
            issues.append({"kind": "package_order", "level": "low",
                           "detail": "%s 加载在 hyperref 之后" % "、".join(later),
                           "hint": "这些宏包建议放在 hyperref 之前，避免选项被覆盖。"})
    if "graphicx" not in names and "\\includegraphics" in "":
        pass
    return issues


def check_tables(files):
    issues = []
    for f in files:
        if f["kind"] != "tex" or not f["text"]:
            continue
        src = tk.strip_comments(f["text"])
        for t in tk.tables(f["text"]):
            if t["ncols"] and t["rows"]:
                # 逐行数 & 数
                body = None
                m = re.search(r"\\begin\s*\{%s\}(.*?)\\end\s*\{%s\}" % (re.escape(t["env"]), re.escape(t["env"])),
                              src, re.S)
                if m:
                    body = m.group(1)
                if body:
                    bad = []
                    for i, row in enumerate(re.split(r"\\\\", body), 1):
                        row = row.strip()
                        if not row or row.startswith("\\hline") or row.startswith("\\toprule") or "&" not in row:
                            continue
                        n = len([c for c in row.split("&")])
                        if n != t["ncols"]:
                            bad.append({"row": i, "cells": n})
                    if bad:
                        issues.append({"kind": "table_column_mismatch", "level": "high",
                                       "file": f["rel"], "line": t["line"],
                                       "detail": "%s 声明 %d 列，但有行给出别的列数：%s" %
                                                 (t["env"], t["ncols"], bad[:5]),
                                       "hint": "表列数不一致会让 LaTeX 报 'Extra alignment tab'；补齐或合并多余 &。"})
            if not t["has_hlines"]:
                issues.append({"kind": "table_no_rules", "level": "low", "file": f["rel"], "line": t["line"],
                               "detail": "%s 没有 \\hline/\\toprule 等横线" % t["env"],
                               "hint": "学术表格一般用三线表（booktabs 的 \\toprule/\\midrule/\\bottomrule）。"})
    return issues


def check_math(files):
    issues = []
    for f in files:
        if f["kind"] != "tex" or not f["text"]:
            continue
        src = tk.strip_comments(f["text"])
        dollars = len(re.findall(r"(?<!\\)\$", src))
        if dollars % 2:
            issues.append({"kind": "unbalanced_math", "level": "high", "file": f["rel"],
                           "detail": "$ 数量为奇数（%d），数学模式可能未闭合" % dollars,
                           "hint": "检查缺失的 $，或用 \\[ \\] / equation 环境替代。"})
        for m in tk.math_regions(f["text"]):
            if m["kind"] == "environment" and m["numbered"]:
                seg = src[m["line"]: m["line"] + 400] if m["line"] else ""
                head = src.split("\n")[max(0, (m["line"] or 1) - 1): (m["line"] or 1) + 30]
                if "\\label" not in "\n".join(head):
                    issues.append({"kind": "numbered_equation_without_label", "level": "medium",
                                   "file": f["rel"], "line": m["line"],
                                   "detail": "带编号的 %s 环境没有 \\label，正文无法引用" % m["env"],
                                   "hint": "给公式加 \\label{eq:...} 并在正文用 \\eqref 引用。"})
    return issues


def check_tex_files(files):
    issues = []
    for f in files:
        if f["kind"] != "tex" or not f["text"]:
            continue
        for b in tk.brace_balance(f["text"]):
            issues.append({"kind": "brace_unbalanced", "level": "high", "file": f["rel"],
                           "line": b.get("line"), "col": b.get("col"), "char": b.get("char"),
                           "detail": "花括号不配对（%s，depth=%s）" % (b.get("char"), b.get("depth")),
                           "hint": "按行号定位，补齐或删除多余的 { }。"})
        _envs, problems = tk.environments(f["text"])
        for p in problems:
            issues.append({"kind": p["kind"], "level": ENV_ISSUE_LEVEL.get(p["kind"], "high"),
                           "file": f["rel"], "line": p.get("line"), "env": p.get("env"),
                           "detail": "环境 %s 未正确配对" % p.get("env"),
                           "hint": "每个 \\begin{env} 必须有对应的 \\end{env}。"})
        for ph in PLACEHOLDER_RE.finditer(tk.strip_comments(f["text"])):
            ln, _ = tk.line_of_index(f["text"], ph.start())
            issues.append({"kind": "placeholder_left", "level": "medium", "file": f["rel"], "line": ln,
                           "detail": "残留占位标记 %s" % ph.group(1), "hint": "交付前清掉占位或改成正式内容。"})
    return issues


def check_refs_cites(files, bib_entries):
    labels, refs, cites = [], [], []
    for f in files:
        if f["kind"] != "tex" or not f["text"]:
            continue
        for l in tk.labels(f["text"]):
            l["file"] = f["rel"]
            labels.append(l)
        for r in tk.refs(f["text"]):
            r["file"] = f["rel"]
            refs.append(r)
        for c in tk.citations(f["text"]):
            c["file"] = f["rel"]
            cites.append(c)
    label_keys = {l["key"] for l in labels}
    bib_keys = {e["key"] for e in bib_entries}
    cited = {c["key"] for c in cites}
    used = {r["key"] for r in refs}
    issues = []
    for r in refs:
        if r["key"] not in label_keys:
            issues.append({"kind": "undefined_ref", "level": "high", "file": r["file"], "line": r["line"],
                           "detail": "\\%s{%s} 引用了不存在的 label" % (r["command"], r["key"]),
                           "hint": "补 \\label{%s} 或修正键名。" % r["key"]})
    for c in cites:
        if c["key"] not in bib_keys:
            issues.append({"kind": "undefined_citation", "level": "high", "file": c["file"], "line": c["line"],
                           "detail": "\\%s{%s} 在文献库里找不到" % (c["command"], c["key"]),
                           "hint": "补 bib 条目或修正键名。"})
    for l in labels:
        if l["key"] not in used:
            issues.append({"kind": "unused_label", "level": "low", "file": l["file"], "line": l["line"],
                           "detail": "label %s 没有被任何地方引用" % l["key"], "hint": "删除或补引用。"})
    for e in bib_entries:
        if e["key"] not in cited:
            issues.append({"kind": "uncited_bib_entry", "level": "low", "file": "references.bib",
                           "line": e.get("line"),
                           "detail": "文献 %s 未被正文引用" % e["key"], "hint": "引用它，或从库里删除。"})
    return {"labels": labels, "refs": refs, "citations": cites,
            "issues": issues,
            "summary": {"labels": len(labels), "refs": len(refs), "citations": len(cites),
                        "bib_entries": len(bib_entries),
                        "undefined_refs": len([i for i in issues if i["kind"] == "undefined_ref"]),
                        "undefined_citations": len([i for i in issues if i["kind"] == "undefined_citation"])}}


def check_template(files, main):
    src = main["text"] if main else ""
    items = []
    for name, pat in TEMPLATE_FIELDS.items():
        found = bool(re.search(pat, tk.strip_comments(src)))
        items.append({"id": name, "requirement": name, "present": found,
                      "evidence": "" if not found else "matched: %s" % pat})
    cls = tk.document_class(src) if main else None
    engine = tk.magic_engine(src) if main else None
    return {"documentclass": cls, "magic_engine": engine, "items": items,
            "missing": [i["requirement"] for i in items if not i["present"]]}


def check_encoding(files, main, engine):
    """只报真正会编译失败的情形：CJK 字符却没有 ctex/xeCJK/fontspec，或明确声明了不支持该字符的引擎。

    现代 pdfLaTeX（TeX Live 2018+ / MiKTeX 同代）默认 UTF-8 输入，`°C`、`±`、`ε`（数学模式或文本）
    这类 Latin-1/希腊字母不会再报错，因此**不**把它们当问题——避免把好稿子判错。
    """
    suspects = []
    for f in files:
        if f["kind"] != "tex" or not f["text"]:
            continue
        src = tk.strip_comments(f["text"])
        cjk = re.findall(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]", src)
        if not cjk:
            continue
        pkgs = {p["name"] for p in tk.packages(f["text"])}
        if pkgs & {"ctex", "xeCJK", "fontspec", "CJK", "ctexart"}:
            continue
        suspects.append({"file": f["rel"], "sample": "".join(sorted(set(cjk))[:8])})
    if not suspects:
        return []
    eng = (engine or "").lower()
    hint = ("检测到中文字符但未加载中文支持：改用 XeLaTeX/LuaLaTeX + xeCJK/fontspec，"
            "或加载 ctex 宏包（当前推荐引擎 %s）。" % (eng or "未声明"))
    return [{"kind": "cjk_without_support", "level": "high", "file": s["file"],
             "detail": "出现中文字符（%s）但未加载 ctex/xeCJK/fontspec" % s["sample"], "hint": hint}
            for s in suspects]


def recommend_engine(main, files, ctx):
    magic = tk.magic_engine(main["text"]) if main else None
    if magic:
        return {"engine": magic, "reason": "源码里的 %!TEX program 指定", "source": "magic"}
    if ctx.get("engine"):
        return {"engine": ctx["engine"], "reason": "case.json 指定", "source": "case"}
    joined = "\n".join(f["text"] for f in files if f["kind"] == "tex" and f["text"])
    pkgs = {p["name"] for p in tk.packages(joined)}
    if pkgs & {"fontspec", "xeCJK"} or re.search(r"[\u4e00-\u9fff]", joined):
        return {"engine": "xelatex", "reason": "用了 fontspec/xeCJK 或含中文", "source": "heuristic"}
    return {"engine": "pdflatex", "reason": "纯 ASCII 常规稿件", "source": "heuristic"}


def build_structure_md(main, files, project, refs_info, template, toolchain, issues, engine):
    out = []
    out.append("# LaTeX 工程概览\n")
    out.append("主文件：`%s`（%d 行）" % (main["rel"] if main else "(未找到)", main["lines"] if main else 0))
    out.append("工程文件：")
    for f in files:
        out.append("- `%s`  %s  %d B  %d 行%s" % (f["rel"], f["kind"], os.path.getsize(f["path"]),
                                                  f["lines"], ("  [%s]" % f["note"]) if f["note"] else ""))
    dc = project.get("documentclass")
    out.append("\n## 导言区")
    out.append("- documentclass：%s%s" % ((dc or {}).get("name", "（无）"),
                                          (" [%s]" % dc.get("options")) if dc and dc.get("options") else ""))
    names = [p["name"] for p in project.get("packages") or []]
    out.append("- 宏包（按加载顺序）：%s" % ("、".join(names) if names else "（无）"))
    out.append("- 推荐引擎：**%s**（%s）" % (engine.get("engine"), engine.get("reason")))
    out.append("\n## 结构")
    out.append("- 包含树：%s" % (project.get("include_tree") or "（无 \\input）"))
    out.append("- 环境 %d 个，表格 %d 个，数学区域 %d 处，标签 %d，引用 %d，文献条目 %d"
               % (len(project.get("environments") or []), len(project.get("tables") or []),
                  len(project.get("math_regions") or []), refs_info["summary"]["labels"],
                  refs_info["summary"]["citations"], refs_info["summary"]["bib_entries"]))
    out.append("\n## 工具链")
    out.append("- 可用引擎：%s" % (", ".join(toolchain.get("engines", {}).keys()) or "（本机无 TeX 引擎）"))
    out.append("- 文献工具：%s" % (", ".join(toolchain.get("bib_tools", {}).keys()) or "（无）"))
    out.append("\n## 模板必填项")
    for it in template["items"]:
        out.append("- [%s] %s" % ("x" if it["present"] else " ", it["requirement"]))
    out.append("\n## 必须原样保留的成分（改写时不得动）")
    out.append("- 数值与单位、`\\cite{...}`、`\\ref{...}`/`\\eqref{...}`、`\\label{...}`、公式、URL/DOI")
    out.append("\n## 确定性发现的问题（%d 条）" % len(issues))
    for i in issues[:80]:
        out.append("- [%s] %s%s %s：%s" % (i.get("level"), i.get("kind"),
                                           (" %s:%s" % (i.get("file"), i.get("line"))) if i.get("line") else "",
                                           "", i.get("detail")))
    out.append("\n## 下一步（Agent 要产出的六件交付物）")
    out.append("1. `revised.tex`：改好的主文件全文（可直接编译）")
    out.append("2. `changes.jsonl`：每处改动 {change_id, file, kind, before, after, reason, source}")
    out.append("3. `diagnosis.json`：每个问题的根因、修法与状态（fixed/accepted/needs_confirm）")
    out.append("4. `checklist.json`：模板必填项逐条对照")
    out.append("5. `source_map.json`：数值/引用/论断的来源定位")
    out.append("6. `compile_plan.json`：引擎、命令、轮次与预期产物")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="LaTeX 工程确定性解析（第一步）")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--material", action="append", default=None)
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--max-files", type=int, default=300)
    args = ap.parse_args(argv)

    out = args.out
    os.makedirs(out, exist_ok=True)
    prep = {"version": VERSION, "status": "ok", "reason": None, "hint": None, "counts": {},
            "next_step": []}
    if not os.path.exists(args.case):
        prep.update({"status": "failed", "reason": "no_case",
                     "hint": "找不到 case 文件：%s" % args.case})
        tk.dump_json(os.path.join(out, "prep.json"), prep)
        print(tk.pjson(prep))
        return 2

    case, ctx = tk.load_case(args.case)
    paths = list(args.material or []) or list(ctx.get("material_paths") or [])
    if not paths:
        prep.update({"status": "failed", "reason": "no_material",
                     "hint": "case.json 里没有材料文件，且目录下也没有 main.tex。"})
        tk.dump_json(os.path.join(out, "prep.json"), prep)
        print(tk.pjson(prep))
        return 2

    files = read_project(paths[: args.max_files])
    readable = [f for f in files if f["text"]]
    if not files:
        prep.update({"status": "failed", "reason": "no_material", "hint": "材料路径都读不到文件。"})
        tk.dump_json(os.path.join(out, "prep.json"), prep)
        print(tk.pjson(prep))
        return 2
    if not readable:
        # 语义分工：**空 = 文件里没有内容；unreadable = 有字节但抽不出文字层**。
        # read_project 给的 note 才是判据（'empty' / 'unreadable:...'），别用 text 是否为空反推。
        notes = [f.get("note") or "" for f in files]
        blanks = [f for f in files if (f.get("note") or "") == "empty"]
        if blanks and not any(n.startswith(("unreadable", "failed", "error")) for n in notes):
            names = "、".join(os.path.basename(f["path"]) for f in blanks[:3])
            prep.update({"status": "failed", "reason": "empty_material",
                         "hint": "材料文件是空的（%s）；补上正文内容再跑。" % names})
        else:
            shown = sorted({n for n in notes if n})
            prep.update({"status": "failed", "reason": "unreadable_material",
                         "hint": "材料存在但都没读出文字层：%s" % "；".join(shown[:3])})
        tk.dump_json(os.path.join(out, "prep.json"), prep)
        print(tk.pjson(prep))
        return 2
    if not [f for f in readable if f["kind"] == "tex"]:
        prep.update({"status": "failed", "reason": "no_tex",
                     "hint": "材料里没有 .tex 源码，无法进行 LaTeX 写作与编译。"})
        tk.dump_json(os.path.join(out, "prep.json"), prep)
        print(tk.pjson(prep))
        return 2

    main_stage = {}
    main_file = pick_main(readable, ctx)
    if main_file is None or "\\documentclass" not in main_file["text"]:
        # 仍继续，但记 high 问题
        main_stage["no_documentclass"] = True

    bib_files = [f for f in readable if f["kind"] == "bib"]
    bib_entries = []
    for bf in bib_files:
        for e in tk.bib_entries(bf["text"]):
            e["source_file"] = bf["rel"]
            bib_entries.append(e)
    # 也接受 case 内联 bib
    inline_bib = tk._first(case, ("bib", "bibtex", "bibliography")) if isinstance(case, dict) else None
    if isinstance(inline_bib, str) and "@" in inline_bib:
        for e in tk.bib_entries(inline_bib):
            e["source_file"] = "case.json:inline"
            bib_entries.append(e)

    include_tree, missing_inputs = walk_inputs(main_file, readable) if main_file else ([], [])
    project = {
        "main": main_file["rel"] if main_file else None,
        "documentclass": tk.document_class(main_file["text"]) if main_file else None,
        "packages": tk.packages(main_file["text"]) if main_file else [],
        "include_tree": include_tree,
        "missing_inputs": missing_inputs,
        "environments": tk.environments(main_file["text"])[0] if main_file else [],
        "tables": tk.tables(main_file["text"]) if main_file else [],
        "math_regions": tk.math_regions(main_file["text"]) if main_file else [],
        "bibliography_directives": tk.bibliography_directives(main_file["text"]) if main_file else {},
    }

    issues = []
    issues += check_tex_files(readable)
    issues += check_package_order(project["packages"])
    issues += check_tables(readable)
    issues += check_math(readable)
    for mi in missing_inputs:
        issues.append({"kind": "missing_input", "level": "high", "file": mi["from"], "line": mi["line"],
                       "detail": "\\input{%s} 对应的文件不在工程里" % mi["target"],
                       "hint": "补上被包含的文件，或把内容合并进主文件。"})
    if main_stage.get("no_documentclass"):
        issues.append({"kind": "no_documentclass", "level": "high",
                       "file": main_file["rel"] if main_file else "",
                       "detail": "找不到带 \\documentclass 的主文件", "hint": "确认主文件与 magic root 设置。"})
    refs_info = check_refs_cites(readable, bib_entries)
    issues += refs_info["issues"]
    template = check_template(readable, main_file)
    engine = recommend_engine(main_file, readable, ctx)
    issues += check_encoding(readable, main_file, engine.get("engine"))
    toolchain = tk.detect_toolchain()
    if not toolchain.get("available"):
        issues.append({"kind": "no_tex_engine", "level": "low", "file": "",
                       "detail": "本机未找到 TeX 引擎，无法在此环境编译",
                       "hint": "在有 TeX 的环境（或平台沙箱的 latex-compiler）里编译；本 Skill 会如实标注未编译。"})

    numbers = tk.protected_spans("".join(f["text"] for f in readable if f["kind"] == "tex"))
    by_file = {}
    for f in readable:
        if f["kind"] == "tex":
            by_file[f["rel"]] = tk.protected_spans(f["text"])
    numbers_doc = {
        "schema": "tex-numbers/1.0",
        "main_file": main_file["rel"] if main_file else None,
        "main": by_file.get(main_file["rel"], {}) if main_file else {},
        "by_file": by_file,
        "all": numbers,
    }

    tk.dump_json(os.path.join(out, "files.json"), [
        {k: v for k, v in f.items() if k != "text"} for f in files])
    tk.dump_json(os.path.join(out, "project.json"), project)
    tk.dump_json(os.path.join(out, "labels.json"), {"labels": refs_info["labels"], "refs": refs_info["refs"],
                                                    "summary": refs_info["summary"]})
    tk.dump_json(os.path.join(out, "citations.json"), {
        "citations": refs_info["citations"],
        "bib_keys": sorted({e["key"] for e in bib_entries}),
        "cited_keys": sorted({c["key"] for c in refs_info["citations"]}),
        "summary": refs_info["summary"]})
    tk.dump_json(os.path.join(out, "bib.json"), {"entries": bib_entries})
    tk.dump_json(os.path.join(out, "numbers.json"), numbers_doc)
    tk.dump_jsonl(os.path.join(out, "issues.jsonl"), issues)
    tk.dump_json(os.path.join(out, "checklist_draft.json"), template)
    tk.dump_json(os.path.join(out, "toolchain.json"), toolchain)

    levels = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        levels[i.get("level", "low")] = levels.get(i.get("level", "low"), 0) + 1
    prep["counts"] = {
        "files": len(files), "tex_files": len([f for f in files if f["kind"] == "tex"]),
        "bib_entries": len(bib_entries), "labels": refs_info["summary"]["labels"],
        "refs": refs_info["summary"]["refs"], "citations": refs_info["summary"]["citations"],
        "environments": len(project["environments"]), "tables": len(project["tables"]),
        "math_regions": len(project["math_regions"]), "issues": len(issues), "issues_by_level": levels,
        "engine": engine.get("engine"), "engine_source": engine.get("source"),
        "toolchain_available": bool(toolchain.get("available")),
    }
    prep["next_step"] = [
        "读 structure.md 与 issues.jsonl，理解工程结构与全部问题",
        "产出 revised.tex：修好可确定性修复的问题，保留其余问题并说明",
        "产出 changes.jsonl：每处改动一条，含 before/after/reason，protect 成分不许改",
        "产出 diagnosis.json：逐条列根因与修法，状态 fixed/accepted/needs_confirm",
        "产出 checklist.json：模板必填项逐条对照",
        "产出 source_map.json：数值/引用/论断的来源定位",
        "产出 compile_plan.json：引擎、命令、轮次、预期产物",
        "运行 tex_assemble.py 做核验与（若有引擎）真实编译",
    ]
    tk.dump_json(os.path.join(out, "prep.json"), prep)
    tk.dump_text(os.path.join(out, "structure.md"),
                 build_structure_md(main_file, files, project, refs_info, template, toolchain, issues, engine))
    tk.dump_json(os.path.join(out, "prep_check.json"), {
        "main_found": bool(main_file and "\\documentclass" in main_file["text"]),
        "bib_found": bool(bib_entries),
        "include_missing": len(missing_inputs),
        "issues_high": levels.get("high", 0),
        "engine_recommended": engine.get("engine"),
        "notes": ctx.get("notes") or [],
    })
    print(tk.pjson(prep["counts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
