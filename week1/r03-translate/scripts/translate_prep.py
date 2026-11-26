#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translate_prep.py — 把科研材料切成"可对齐、可回查"的翻译段，并抽取候选术语表。

设计目标（对应题面四个考察点）：
  段落全：段号 seg_id 与原文一一对应，跨页/跨栏/跨章节不漏不重；
  术语稳：先建术语表草稿，把"译名锁定"变成流程里的一步，而不是提示里的一句话；
  关系准：每段预先抽出不变量（数字单位、引用标记、图表公式编号、否定与限定词）；
  可核验：每段带 page + quote 锚点，装配阶段据此逐段回查。

输出（默认落到 --out 目录）：
    segments.json        段级结构：seg_id / page / kind / section / text / 不变量 / 锚点
    segments.md          给人（和 Agent）读的编号原文，供逐段翻译
    glossary_draft.tsv   候选术语表草稿：term / freq / pages / sections / zh(空) / status
    prep.json            统计与告警：页数、段数、已含中文段、无可抽取文字层等
    prep_check.json      分段自检：空段、重复段、跨页接续、疑似漏段

用法：
    python scripts/translate_prep.py --case /input/case.json --out /app/work
    python scripts/translate_prep.py --pdf paper.pdf --out work --tgt-lang zh --max-pages 40
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paperkit as pk  # noqa: E402

VERSION = "translatekit/1.0"

# ------------------------------------------------------------------ 不变量抽取

# 数字（含小数、千分位、科学计数、范围），保留单位后缀
NUM_RE = re.compile(
    r"(?<![\w.])(?P<num>\d+(?:[.,]\d+)*(?:\s*[×x]\s*10\s*\^?-?\d+)?)"
    r"(?P<unit>\s*(?:%|‰|°C|°|K|nm|µm|um|mm|cm|m|km|mL|L|µL|uL|nL|mg|µg|ug|ng|g|kg|"
    r"mol|mmol|µmol|umol|nmol|M|mM|µM|uM|nM|pM|s|ms|µs|us|ns|min|h|Hz|kHz|MHz|GHz|"
    r"eV|keV|MeV|mV|V|kV|mA|A|mW|W|kW|kW·h|J|kJ|Pa|kPa|MPa|GPa|bar|atm|Torr|"
    r"rpm|Da|kDa|bp|kb|Mb|GB|MB|KB|bit|byte|wt%|vol%|at%|ppm|ppb|"
    r"authors?|pages?|samples?|cells?|patients?|epochs?|steps?|layers?|params?))?",
    re.IGNORECASE)

# 引用标记：[12] [12,13] [12-15] (Smith et al., 2020) (Smith 2020) \cite{key}
CITE_BRACKET_RE = re.compile(r"\[\s*\d{1,3}\s*(?:[-,–]\s*\d{1,3}\s*)*\]")
CITE_AUTHOR_RE = re.compile(
    r"\((?:[A-Z][\w'’\-]+(?:\s+(?:and|&)\s+[A-Z][\w'’\-]+)?(?:\s+et\s+al\.?)?)"
    r"\s*,?\s*(?:19|20)\d{2}[a-z]?(?:\s*;\s*[^)]{0,80})?\)")
CITE_TEX_RE = re.compile(r"\\cite[a-z]*\{[^}]{1,200}\}")

# 图表公式编号引用：Fig. 2 / Figure 2 / Table 3 / Eq. (4) / Section 2.1 / Supplementary Fig. S1
REF_RE = re.compile(
    r"\b(?P<label>Fig(?:ure)?s?\.?|Tables?|Eqs?\.?|Equations?|Sections?|Sec\.?|"
    r"Algorithms?|Schemes?|Chart|Appendix|Supplementary\s+(?:Fig(?:ure)?s?|Tables?))"
    r"\s*(?P<num>[0-9]{1,3}(?:\.[0-9]{1,2})*|[IVX]{1,6}|S[0-9]{1,2})\b",
    re.IGNORECASE)

# 数学/公式片段：上下标变量、关系式、LaTeX 命令、希腊字母变量。
# 收紧口径：不带上下标、又没有关系运算符的 "x-y" 一律不算公式，避免把普通连字词误判成不变量。
FORMULA_RE = re.compile(
    r"(?:\b[A-Za-z]\s*[_^]\s*\{?[\w{}]{1,12}\}?)|"
    r"(?:[A-Za-z0-9)\]]\s*(?:=|≈|≤|≥|∝)\s*[A-Za-z0-9(\[])|"
    r"(?:\\[a-zA-Z]{2,12}\b)|"
    r"(?:[αβγδεζηθικλμνξπρστυφχψω]\s*[_^]?\s*[0-9]?)")

# 否定与限定线索（英→中方向；同时用于中文侧计数）
NEG_CUES_EN = {
    "not", "no", "never", "none", "neither", "nor", "without", "cannot", "can't",
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
    "unable", "fail", "fails", "failed", "failure", "except", "excluding",
    "absent", "lack", "lacks", "lacking", "unclear", "unknown", "only", "merely",
    "solely", "at most", "no more than", "under", "below", "rarely", "seldom",
    "suggest", "may", "might", "could", "likely", "unlikely", "assume", "assumed",
}
NEG_CUES_ZH = ("不", "未", "无", "非", "没", "别", "无法", "不能", "不含", "未经",
               "仅", "只", "至多", "不足", "低于", "尚未", "除外", "缺少", "可能", "假设")

# ------------------------------------------------------------- 术语候选抽取

STOP = set("""
the of and for with from that this these those are was were is be been being by in on at as
to into over under between among within without using used use uses we our their its it he she they
can may might must should could would will shall not no than then there here which who whom whose
however therefore moreover furthermore thus also both each other another such same different
a an or if when while where what how why all any more most less least very much many few some
study paper results result method methods figure table eq equation section data we show shows
""".split())

WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-'’]{1,30}")
TERM_SUFFIX = re.compile(
    r"(tion|sion|ance|ence|ity|ness|ment|ology|ometry|ography|esis|ysis|itis|emia|"
    r"ase|ome|omics|genic|pathy|plasty|scopy|gram|graph|meter|metry|philic|phobic|"
    r"genic|lytic|trophic|plastic|tropic|blast|cyte|phage|zyme)$", re.IGNORECASE)
GREEK = ("alpha", "beta", "gamma", "delta", "epsilon", "kappa", "lambda", "sigma",
         "theta", "omega", "mu", "tau", "rho", "phi", "psi", "chi", "eta", "zeta")


HEADING_STOP = {"introduction", "conclusion", "conclusions", "abstract", "background",
                "method", "methods", "methodology", "results", "discussion",
                "references", "acknowledgments", "acknowledgements", "appendix",
                "experiments", "related", "work", "figure", "figures", "table", "tables"}


def _is_termish(tok: str, freq: int, mid_cap: int) -> bool:
    low = tok.lower()
    if len(tok) < 5 or low in STOP or low in HEADING_STOP:
        return False
    if TERM_SUFFIX.search(low):
        return True
    if "-" in tok:                       # 连字复合词：long-document、sparse-routing
        return True
    if mid_cap >= 2:                     # 句首大写不算专有名词，句中重复大写才算
        return True
    return freq >= 4 and len(tok) >= 7   # 高频长词也值得锁定


def extract_terms(segments, top_n: int = 120):
    """从段落里抽候选术语：多词短语优先，再补高频/后缀特征的单术语。"""
    term_occ = OrderedDict()     # term -> {"count","pages":[],"sections":[],"phrase":True/False}
    mid_cap = Counter()          # 句中大写出现次数（句首大写不算）

    def bump(term, page, section, phrase=False):
        key = term.strip()
        if not key or len(key) < 3:
            return
        rec = term_occ.setdefault(key, {"count": 0, "pages": [], "sections": [],
                                        "phrase": phrase})
        rec["count"] += 1
        if page not in rec["pages"]:
            rec["pages"].append(page)
        if section and section not in rec["sections"]:
            rec["sections"].append(section)

    for seg in segments:
        text = seg["text"]
        page, section = seg["page"], seg.get("section") or ""
        # 多词短语：连续 2~4 个实词、无标点中断
        for m in re.finditer(r"\b([A-Za-z][\w\-']*(?:\s+[A-Za-z][\w\-']*){1,3})\b", text):
            words = m.group(1).split()
            if any(w.lower() in STOP for w in words):
                continue
            if not any(w[0].isupper() or TERM_SUFFIX.search(w) or "-" in w for w in words):
                continue
            if len(" ".join(words)) < 8:
                continue
            bump(" ".join(words), page, section, phrase=True)
        # 单术语
        for m in WORD_RE.finditer(text):
            w = m.group(0)
            bump(w, page, section)
            if w[:1].isupper():
                before = text[:m.start()].rstrip()
                if before and not before.endswith((".", "!", "?", "。", "！", "？", ":", "：", ";")):
                    mid_cap[w.lower()] += 1
        # 希腊字母变量
        for g in GREEK:
            if re.search(r"\b" + g + r"\b", text, re.IGNORECASE):
                bump(g, page, section)

    freq = Counter()
    for seg in segments:
        for w in WORD_RE.findall(seg["text"]):
            freq[w.lower()] += 1

    rows = []
    for term, rec in term_occ.items():
        if rec["phrase"]:
            if rec["count"] < 2 and len(term.split()) < 3:
                continue
        else:
            if not _is_termish(term, freq.get(term.lower(), rec["count"]),
                               mid_cap.get(term.lower(), 0)):
                continue
        rows.append({
            "term": term,
            "freq": rec["count"],
            "pages": rec["pages"][:8],
            "sections": rec["sections"][:5],
            "phrase": rec["phrase"],
        })
    rows.sort(key=lambda r: (-r["freq"], -len(r["term"]), r["term"].lower()))
    return rows[:top_n]


# ------------------------------------------------------------------ 不变量

def invariants(text: str):
    nums = [m.group(0).strip() for m in NUM_RE.finditer(text) if re.search(r"\d", m.group(0))]
    cites = ([m.group(0) for m in CITE_BRACKET_RE.finditer(text)] +
             [m.group(0) for m in CITE_AUTHOR_RE.finditer(text)] +
             [m.group(0) for m in CITE_TEX_RE.finditer(text)])
    refs = [f"{m.group('label')} {m.group('num')}" for m in REF_RE.finditer(text)]
    forms = [m.group(0).strip() for m in FORMULA_RE.finditer(text)]
    low = " " + text.lower() + " "
    neg = sorted({c for c in NEG_CUES_EN
                  if re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", low)})
    return {
        "numbers": _dedupe(nums),
        "citations": _dedupe(cites),
        "refs": _dedupe(refs),
        "formulas": _dedupe(forms)[:20],
        "negation_en": neg,
    }


def _dedupe(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


# ------------------------------------------------------------------ 分段

KIND_BY_HEADING = {"abstract": "abstract", "摘要": "abstract",
                   "references": "reference", "参考文献": "reference",
                   "acknowledgments": "acknowledgment", "acknowledgements": "acknowledgment",
                   "致谢": "acknowledgment", "appendix": "appendix", "附录": "appendix"}


def _kind_of(seg, in_refs: bool) -> str:
    t = seg["text"].strip()
    if seg.get("is_title"):
        return "title"
    if seg.get("is_authors"):
        return "authors"
    if seg.get("is_caption"):
        return seg.get("caption_kind") or "caption"
    if seg.get("is_table"):
        return "table"
    if in_refs:
        return "reference"
    if seg.get("heading"):
        head = re.sub(r"^\d+(\.\d+)*\.?\s*", "", t).strip().lower()
        return KIND_BY_HEADING.get(head, "heading")
    return "body"


def merge_continuations(segments):
    """把被版面折行切碎的同一段接回去（影响"段落全"）：同页、都是正文/摘要、
    前段不以句末标点收尾、后段以小写字母或数字开头 → 合并为一段。

    合并后段号沿用前段的 seg_id，被并入的段号记入 merged_from，便于回查。
    """
    out = []
    for seg in segments:
        if out:
            prev = out[-1]
            same_flow = (prev["kind"] == seg["kind"] and prev["kind"] in
                         ("body", "abstract", "reference", "caption", "figure"))
            adj = (seg["page"] == prev["page"] and seg["index_on_page"] == prev["index_on_page"] + 1)
            open_prev = not prev["text"].rstrip().endswith(
                (".", "。", "!", "?", "！", "？", ")", "）", "]", "】", ":", "：", ";", "；"))
            starts_low = bool(seg["text"][:1]) and (seg["text"][:1].islower()
                                                    or seg["text"][:1].isdigit())
            if same_flow and adj and open_prev and starts_low and not seg.get("heading"):
                prev["text"] = (prev["text"] + " " + seg["text"]).strip()
                prev.setdefault("merged_from", []).append(seg["seg_id"])
                prev["chars"] = len(prev["text"])
                prev["cjk_ratio"] = round(pk.cjk_ratio(prev["text"]), 3)
                prev["invariants"] = invariants(prev["text"])
                prev["anchor"] = pk.anchor(prev["page"], prev["text"], kind="text",
                                           block=prev["seg_id"])
                continue
        out.append(seg)
    return out


def build_segments(pdf_path: str, max_pages: int = 60):
    warnings, skipped = [], []
    doc = pk.PDFDoc(pdf_path, max_pages=max_pages)
    warnings.extend(doc.warnings)
    title = doc.detect_title()
    authors = doc.detect_authors()
    caps = doc.captions()
    cap_texts = {pk.norm(c["text"]) for c in caps}

    # 先取表格，把表格区域从正文里挖掉，避免同一批单元格被正文和表格各译一遍（重复翻译）
    try:
        all_tables = doc.tables(out_dir=None)
    except Exception as exc:                      # pragma: no cover
        all_tables = []
        warnings.append(f"table extraction failed ({exc})")
    boxes_by_page = {}
    for tab in all_tables:
        bb = tab.get("bbox")
        if bb and len(bb) == 4:
            boxes_by_page.setdefault(tab["page"], []).append(tuple(bb))

    segments = []
    section = ""
    in_refs = False
    for pno in range(1, doc.page_count + 1):
        paras = doc.paragraphs(pno, skip_boxes=boxes_by_page.get(pno))
        if not paras:
            skipped.append({"page": pno, "reason": "no_text_layer"})
            warnings.append(f"page {pno}: no extractable text (scanned?)")
            continue
        idx = 0
        for p in paras:
            text = p["text"].strip()
            if not text:
                continue
            idx += 1
            is_title = bool(title) and pk.norm(text) == pk.norm(title) and pno == 1
            is_authors = bool(authors) and pk.norm(text) == pk.norm(authors)
            is_cap = bool(text) and pk.caption_like(text)
            cap_kind = ""
            if is_cap:
                m = pk.CAP_RE.match(text)
                head = (m.group("label") or "").split()[0].rstrip(".").lower() if m else ""
                cap_kind = "table" if head.startswith(("table", "表")) else "figure"
            if p.get("heading"):
                head = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text).strip().lower()
                section = text
                if head in ("references", "参考文献"):
                    in_refs = True
                elif head not in ("appendix", "附录"):
                    in_refs = False
            seg = {
                "seg_id": f"p{pno}b{idx}",
                "page": pno,
                "index_on_page": idx,
                "kind": "",
                "section": section,
                "text": text,
                "heading": bool(p.get("heading")),
                "level": int(p.get("level") or 0),
                "bold": bool(p.get("bold")),
                "is_title": is_title,
                "is_authors": is_authors,
                "is_caption": is_cap,
                "caption_kind": cap_kind,
                "anchor": pk.anchor(pno, text, kind="text", block=f"p{pno}b{idx}"),
            }
            seg["kind"] = _kind_of(seg, in_refs)
            # 题注若被段落合并吞掉，仍按题注类型标注
            if not is_cap and pk.norm(text) in cap_texts:
                seg["kind"] = "caption"
            seg["cjk_ratio"] = round(pk.cjk_ratio(text), 3)
            seg["chars"] = len(text)
            seg["invariants"] = invariants(text)
            segments.append(seg)

        # 表格：按单元格文本作为独立段（表头/表体），避免表内文字漏译
        for ti, tab in enumerate(t for t in all_tables if t.get("page") == pno):
            rows = tab.get("rows") or []
            for ri, row in enumerate(rows):
                cells = [pk.norm(c) for c in row if pk.norm(c)]
                if not cells:
                    continue
                idx += 1
                text = " | ".join(cells)
                seg = {
                    "seg_id": f"p{pno}t{ti + 1}r{ri + 1}",
                    "page": pno,
                    "index_on_page": idx,
                    "kind": "table_row",
                    "section": section,
                    "text": text,
                    "heading": False, "level": 0, "bold": False,
                    "is_title": False, "is_authors": False,
                    "is_caption": False, "caption_kind": "",
                    "table_label": tab.get("label") or f"Table {ti + 1}",
                    "row_index": ri,
                    "anchor": pk.anchor(pno, text, kind="table", block=f"p{pno}t{ti + 1}r{ri + 1}"),
                }
                seg["cjk_ratio"] = round(pk.cjk_ratio(text), 3)
                seg["chars"] = len(text)
                seg["invariants"] = invariants(text)
                segments.append(seg)

    body = [s for s in segments if s["kind"] != "table_row"]
    tables = [s for s in segments if s["kind"] == "table_row"]
    segments = merge_continuations(body) + tables
    segments.sort(key=lambda s: (s["page"], s["index_on_page"]))
    return doc, segments, {"title": title, "authors": authors,
                           "page_count": doc.page_count,
                           "skipped_pages": skipped, "warnings": warnings}


# ------------------------------------------------------------------ 输出

def write_segments_md(segments, path, tgt_lang="zh"):
    lines = ["# 待翻译分段表（原文）", "",
             f"目标语言：{tgt_lang}　段数：{len(segments)}　"
             "段号格式：正文 `p<页>b<块>`、表格行 `p<页>t<表>r<行>`", "",
             "> 逐段翻译时，请严格保留段号与顺序；`kind` 为 `table_row` 的段按 `|` 切分单元格逐格翻译。",
             ""]
    cur_page, cur_section = None, None
    for seg in segments:
        if seg["page"] != cur_page:
            cur_page = seg["page"]
            lines += ["", f"## —— 第 {cur_page} 页 ——", ""]
        if seg.get("section") and seg["section"] != cur_section:
            cur_section = seg["section"]
            lines += [f"*（当前章节：{cur_section}）*", ""]
        tag = seg["kind"]
        lines.append(f"### [{seg['seg_id']}] kind={tag} page={seg['page']}")
        lines.append(seg["text"])
        inv = seg["invariants"]
        bits = []
        if inv["numbers"]:
            bits.append("数字单位: " + ", ".join(inv["numbers"][:12]))
        if inv["citations"]:
            bits.append("引用: " + ", ".join(inv["citations"][:8]))
        if inv["refs"]:
            bits.append("图表公式引用: " + ", ".join(inv["refs"][:8]))
        if inv["formulas"]:
            bits.append("公式片段: " + ", ".join(inv["formulas"][:8]))
        if bits:
            lines.append("")
            lines.append("> 必须原样保留 —— " + "；".join(bits))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_glossary_draft(terms, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("# term\tzh\tfreq\tpages\tsections\tstatus\tnote\n")
        f.write("# 由 translate_prep.py 生成的候选术语表草稿。\n")
        f.write("# 请先补齐 zh 列（锁定译名），再开始逐段翻译；翻译阶段不得改 zh。\n")
        for r in terms:
            pages = ",".join(str(p) for p in r["pages"])
            secs = " / ".join(s.replace("\t", " ")[:28] for s in r["sections"])
            status = "needs_review" if r["freq"] < 2 else "suggested"
            f.write(f"{r['term']}\t\t{r['freq']}\t{pages}\t{secs}\t{status}\t\n")


def segment_selfcheck(segments):
    issues = []
    ids = [s["seg_id"] for s in segments]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    if dup:
        issues.append({"item": "duplicate_seg_id", "seg_ids": dup[:10]})
    empty = [s["seg_id"] for s in segments if len(s["text"].strip()) < 2]
    if empty:
        issues.append({"item": "empty_segment", "seg_ids": empty[:10]})
    tiny = [s["seg_id"] for s in segments if s["kind"] == "body" and s["chars"] < 40]
    if tiny:
        issues.append({"item": "short_body_segment_maybe_broken",
                       "seg_ids": tiny[:10], "impact": "可能是版面折行被误切，翻译时需与相邻段对照"})
    pages = sorted({s["page"] for s in segments})
    if pages and pages != list(range(min(pages), max(pages) + 1)):
        issues.append({"item": "page_gap", "pages_present": pages[:20]})
    # 跨页接续：上一页末段以未结束标点收尾
    for a, b in zip(segments, segments[1:]):
        if b["page"] == a["page"] + 1 and a["kind"] == "body" and b["kind"] == "body":
            if not a["text"].rstrip().endswith((".", "。", "!", "?", "！", "？", ")", "）")):
                issues.append({"item": "cross_page_continuation",
                               "from": a["seg_id"], "to": b["seg_id"],
                               "impact": "该段跨页延续，翻译需携带上一段上下文，避免断句错误"})
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="切分科研材料为可对齐翻译段 + 抽取候选术语")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--pdf", default=None, help="直接指定材料（PDF/TXT/MD），覆盖 case 解析")
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--tgt-lang", default=None, help="目标语言，默认取 case.target_language 或 zh")
    ap.add_argument("--src-lang", default=None)
    ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--top-terms", type=int, default=120)
    ap.add_argument("--glossary", default=None, help="已有术语表（term<TAB>zh），用于合并锁定")
    args = ap.parse_args(argv)

    case, ctx = pk.load_case(args.case)
    src = args.pdf or ctx.get("paper")
    tgt = args.tgt_lang or ctx.get("language") or "zh"
    os.makedirs(args.out, exist_ok=True)

    if not src or not os.path.exists(src):
        result = {"status": "failed", "reason": "no_material",
                  "detail": f"case={args.case} paper={src}"}
        with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(json.dumps(result, ensure_ascii=True))
        return 2

    ext = os.path.splitext(src)[1].lower()
    try:
        if ext == ".pdf":
            doc, segments, meta = build_segments(src, max_pages=args.max_pages)
        else:
            text = open(src, encoding="utf-8", errors="replace").read()
            blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
            segments, meta = [], {"title": "", "authors": "", "page_count": 1,
                                  "skipped_pages": [], "warnings": []}
            for i, b in enumerate(blocks, start=1):
                head = b.splitlines()[0].strip()
                is_head = head.startswith("#") or (len(head) < 80 and head.endswith(":"))
                segments.append({
                    "seg_id": f"p1b{i}", "page": 1, "index_on_page": i,
                    "kind": "heading" if is_head else "body", "section": "",
                    "text": re.sub(r"^#+\s*", "", b),
                    "heading": is_head, "level": 1 if is_head else 0, "bold": False,
                    "is_title": i == 1, "is_authors": False, "is_caption": False,
                    "caption_kind": "", "cjk_ratio": round(pk.cjk_ratio(b), 3),
                    "chars": len(b), "invariants": invariants(b),
                    "anchor": pk.anchor(1, b, kind="text", block=f"p1b{i}")})
    except Exception as exc:  # 加密/损坏/无法解析：给出结构化失败，不留裸 traceback
        name = type(exc).__name__
        msg = str(exc)
        if "encrypted" in msg.lower():
            reason, hint = "encrypted_pdf", "PDF 已加密：请提供密码或解密后的副本，本 Skill 不尝试破解。"
        elif "damaged" in msg.lower() or "cannot open" in msg.lower():
            reason, hint = "damaged_pdf", "文件损坏或不是有效 PDF：请确认上游导出完整。"
        elif ext != ".pdf":
            reason, hint = "unreadable_material", "文本文件无法按 UTF-8 读取：请确认编码。"
        else:
            reason, hint = "parse_failed", "版面解析失败：可改用文本版副本重试。"
        result = {"schema": VERSION, "status": "failed", "reason": reason,
                  "detail": f"{name}: {msg}", "source": os.path.basename(src),
                  "source_ext": ext, "segment_count": 0, "page_count": 0,
                  "skipped_pages": [], "warnings": [f"{reason}: {msg}"],
                  "hint": hint, "target_language": tgt,
                  "outputs": {}, "self_check": [],
                  "next_step": "材料不可读，无法翻译；把 reason/hint 写入 result.json 的 uncertainty 后结束"}
        with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(json.dumps({"status": "failed", "reason": reason, "detail": msg},
                         ensure_ascii=True))
        return 2

    already = [s["seg_id"] for s in segments if s["cjk_ratio"] >= 0.5]
    for s in segments:
        s["skip_translate"] = s["seg_id"] in set(already)

    terms = extract_terms(segments, top_n=args.top_terms)
    locked = {}
    if args.glossary and os.path.exists(args.glossary):
        for line in open(args.glossary, encoding="utf-8"):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                locked[parts[0].strip()] = parts[1].strip()

    seg_path = os.path.join(args.out, "segments.json")
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "source": os.path.basename(src),
                   "source_path": src, "target_language": tgt,
                   "segment_count": len(segments), "segments": segments},
                  f, ensure_ascii=False, indent=1)
    write_segments_md(segments, os.path.join(args.out, "segments.md"), tgt)
    gl_path = os.path.join(args.out, "glossary_draft.tsv")
    write_glossary_draft(terms, gl_path)
    if locked:
        with open(os.path.join(args.out, "glossary_locked.tsv"), "w", encoding="utf-8") as f:
            f.write("# term\tzh\tfreq\tpages\tsections\tstatus\tnote\n")
            for k, v in sorted(locked.items()):
                f.write(f"{k}\t{v}\t\t\t\tlocked\tfrom --glossary\n")

    issues = segment_selfcheck(segments)
    stats = {
        "schema": VERSION,
        "status": "ok" if segments else "failed",
        "source": os.path.basename(src),
        "source_ext": ext,
        "page_count": meta["page_count"],
        "segment_count": len(segments),
        "by_kind": dict(Counter(s["kind"] for s in segments)),
        "chars_total": sum(s["chars"] for s in segments),
        "already_target_language_segments": already,
        "candidate_terms": len(terms),
        "locked_terms": len(locked),
        "skipped_pages": meta["skipped_pages"],
        "warnings": meta["warnings"][:20],
        "title": meta["title"],
        "authors": meta["authors"],
        "target_language": tgt,
        "outputs": {
            "segments_json": os.path.basename(seg_path),
            "segments_md": "segments.md",
            "glossary_draft_tsv": os.path.basename(gl_path),
        },
        "self_check": issues,
        "next_step": ("逐段翻译 segments.md 中每个 seg_id，写入 translations.json；"
                      "同时补齐 glossary_draft.tsv 的 zh 列，再运行 translate_assemble.py"),
    }
    with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "prep_check.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "case_id": ctx.get("case_id"),
                   "checks": issues}, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: stats[k] for k in
                      ("status", "page_count", "segment_count", "by_kind",
                       "candidate_terms", "locked_terms", "already_target_language_segments")},
                     ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
