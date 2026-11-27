#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""method_assemble —— 方法与实验章节的硬核验与交付物封装（第三步）。

它不写一个字的方法段落；它只做三件事：
  1. 把 Agent 写出的稿子与材料/参数候选逐条对账（数值、单位、划分、对照、限制、复现清单）；
  2. 把无法核验的地方全部挑出来，分成 high/medium/low 三级；
  3. 产出一套下游可直接解析的交付物（methods.md + 五份结构化文件 + review.md + result.json）。

退出码：0 = ok/partial（有产物可交）；2 = failed（稿子缺失或不可解析，没得交）。
"""
import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import methodkit as mk  # noqa: E402

VERSION = "method_assemble/1.0"

METHODS_CANDIDATES = ("methods.md", "method.md", "methods.txt", "methods_section.md",
                      "experimental.md", "method_section.md")
PARAMS_CANDIDATES = ("params.tsv", "parameters.tsv", "params.csv", "parameters.csv")
ELEMENTS_CANDIDATES = ("elements.json", "element_coverage.json", "coverage.json")
GAPS_CANDIDATES = ("gaps.json", "gaps.jsonl", "open_questions.json", "gaps_open.json")
REPRO_CANDIDATES = ("repro.json", "reproducibility.json", "repro_checklist.json")
SOURCEMAP_CANDIDATES = ("source_map.json", "sources_map.json", "evidence_map.json", "source_map.jsonl")

SECTION_KEYS = ("steps", "settings", "params", "datasets", "baselines", "repro_limits")

SECTION_PATTERNS = {
    "steps": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:method(?:s)?|approach(?:es)?|"
                        r"experimental\s+(?:setup|procedure|section)|procedure|pipeline|"
                        r"方法|实验方法|方法步骤|实现细节|技术路线)\b"),
    "settings": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:experimental\s+settings?|"
                           r"implementation\s+details?|training\s+(?:setup|details|settings?)|"
                           r"hyper-?parameters?|实验设置|训练设置|实现细节|超参数)\b"),
    "params": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:parameters?|parameter\s+settings?|"
                         r"configurations?|参数|参数设置|配置)\b"),
    "datasets": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:datasets?|data\s+(?:sets?|splits?|preparation)|"
                           r"corpora|数据集|数据划分|数据预处理)\b"),
    "baselines": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:baselines?|baselines?\s+and\s+metrics?|"
                            r"comparison\s+(?:methods?|baselines?)|对照|基线|对照实验|对比方法)\b"),
    "repro_limits": re.compile(r"(?im)^#{1,4}\s*(?:\d+[.、)]\s*)?(?:reproducibility|limitations?|"
                               r"threats\s+to\s+validity|reproducibility\s+and\s+limitations?|"
                               r"可复现性|复现|限制|局限性|局限与不足)\b"),
}

HEADING_RE = re.compile(r"(?m)^\s*#{1,4}\s*\S.*$|^\s*(?:\d+[.、)]\s*)+\S.{0,60}$")

BOILERPLATE = re.compile(
    r"(?:取得了?显著(?:的)?(?:效果|提升|成果)|性能优越|效果良好|具有重要意义|"
    r"开辟了新的(?:方向|道路)|achieved\s+significant\s+(?:results?|improvements?)|"
    r"shows?\s+promising\s+results?|opens?\s+new\s+avenues?)", re.I)

MIN_SECTION_CHARS = 60
# 参数表里的数值型取值（含科学计数法与百分号）：这类取值必须与材料数值集合精确比对
NUMERIC_VALUE_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d{1,3}|%)?")
MIN_SOURCE_QUOTE = 12


def iss(issues, level, kind, where, detail, hint=None):
    item = {"level": level, "kind": kind, "where": where, "detail": detail}
    if hint:
        item["hint"] = hint
    issues.append(item)


def hard(x):
    """宽容比对用的归一：去标点空白并小写。

    比对的双方必须走同一套归一，否则「0.001」「data/x.jsonl」「2.1.0+cu118」
    这类带标点的串会在材料里永远找不到，把好稿子判成错稿子。
    """
    return mk.norm_hard(x)


def pick(explicit, candidates, work, jsonl=False):
    """在 work 目录里找交付物：显式路径优先，其次候选文件名。"""
    tried = []
    if explicit:
        p = explicit if os.path.isabs(explicit) else os.path.join(work, explicit)
        tried.append(p)
        if os.path.isfile(p):
            return p, None
        return None, {"kind": "provided_file_missing", "path": explicit}
    for name in candidates:
        p = os.path.join(work, name)
        tried.append(p)
        if os.path.isfile(p):
            return p, None
    return None, {"kind": "not_found", "tried": tried}


def read_rows(path):
    """tsv/csv/jsonl/json 都能读成 list[dict]。"""
    if path is None:
        return [], None
    if path.lower().endswith(".json"):
        doc = mk.read_json(path)
        if isinstance(doc, dict):
            for key in ("rows", "items", "params", "parameters", "entries", "data"):
                if isinstance(doc.get(key), list):
                    return [r for r in doc[key] if isinstance(r, dict)], None
            return [], "no_rows"
        if isinstance(doc, list):
            return [r for r in doc if isinstance(r, dict)], None
        return [], "unreadable"
    if path.lower().endswith(".jsonl"):
        return mk.load_jsonl(path), None
    txt = ""
    try:
        txt = io.open(path, encoding="utf-8-sig").read()
    except Exception as exc:  # noqa: BLE001
        return [], "unreadable: %s" % exc
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return [], "empty"
    sep = "\t" if "\t" in lines[0] else ","
    header = [h.strip().lower() for h in lines[0].split(sep)]
    rows = []
    for ln in lines[1:]:
        cells = [c.strip().strip('"') for c in ln.split(sep)]
        if len(cells) < 2:
            continue
        row = {}
        for i, h in enumerate(header):
            row[h] = cells[i] if i < len(cells) else ""
        row["_cells"] = cells
        rows.append(row)
    return rows, None


def split_paragraphs(text):
    out = []
    for i, block in enumerate(re.split(r"\n\s*\n", text or ""), 1):
        b = block.strip()
        if not b:
            continue
        kind = "heading" if HEADING_RE.match(b) else "body"
        out.append({"para_id": "m-p%03d" % i, "kind": kind, "text": b})
    return out


def section_spans(text):
    """按标题行把小节边界找出来：{key: (start, end)}。

    同一个 key 可能被多个标题命中（例如文档大标题 `# Methods and Experimental
    Section` 也含 Methods，而真正的要素小节是 `## 1. Methods`）。这时**取跨度最大
    的那个**——大标题到下一标题往往只剩几十个字符，取它会凭空判出「小节过短」。
    """
    lines = (text or "").splitlines(keepends=True)
    heads = []
    pos = 0
    first_head = None
    for ln in lines:
        if HEADING_RE.match(ln.strip()):
            if first_head is None:
                first_head = pos
            heads.append((pos, ln.strip()))
        pos += len(ln)
    best = {}
    for i, (off, htxt) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(text or "")
        for key, pat in SECTION_PATTERNS.items():
            if not pat.match(htxt):
                continue
            if off == first_head and len(heads) > 1:
                # 文档大标题不当要素小节用（H1 常把全名写全，容易误命中）
                continue
            cur = best.get(key)
            if cur is None or (nxt - off) > (cur[1] - cur[0]):
                best[key] = (off, nxt)
    return best


def collect_number_index(facts, params, material):
    """材料侧数值索引：{flat_value: [来源...]}，按「数值本身」比对（单位另行比对）。"""
    idx = {}
    for src, tag in ((material, "material"),):
        for m in mk.NUM_RE.finditer(src or ""):
            v = m.group("val")
            idx.setdefault(v, []).append(tag)
    for f in facts:
        for m in mk.NUM_RE.finditer(f.get("text", "") or ""):
            idx.setdefault(m.group("val"), []).append("fact:%s" % f.get("fact_id"))
    for p in params:
        v = mk.clean_value(str(p.get("value", "")))
        for m in mk.NUM_RE.finditer(v):
            idx.setdefault(m.group("val"), []).append("param:%s" % p.get("key"))
        if re.match(r"^[-+]?\d+(?:\.\d+)?$", v):
            idx.setdefault(v, []).append("param:%s" % p.get("key"))
    return idx


def main():
    ap = argparse.ArgumentParser(description="方法与实验章节写作：硬核验与交付物封装")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--methods")
    ap.add_argument("--params")
    ap.add_argument("--elements")
    ap.add_argument("--gaps")
    ap.add_argument("--repro")
    ap.add_argument("--source-map", dest="source_map")
    ap.add_argument("--out", default="/app/output")
    args = ap.parse_args()

    case, ctx = mk.load_case(args.case)
    case_id = ctx.get("case_id") or case.get("case_id") or "unknown"
    contract = ctx.get("contract") or {}
    work = args.work
    os.makedirs(args.out, exist_ok=True)

    issues = []
    notes = []

    # ---------- 载入前置产物 ----------
    facts = mk.load_jsonl(os.path.join(work, "facts.jsonl"))
    # 材料正文：sources.json 出于体积考虑**不含正文**，正文一律回 case 目录现取
    src_doc = mk.read_json(os.path.join(work, "sources.json"))
    if isinstance(src_doc, list):
        sources = src_doc
    elif isinstance(src_doc, dict):
        sources = src_doc.get("materials") or src_doc.get("sources") or []
    else:
        sources = []
    _texts = [(m.get("text") or "") for m in (ctx.get("materials") or [])]
    material = "\n\n".join(t for t in _texts if t.strip())
    if not material.strip():
        # sources.json 通常不含正文（体积考虑），仅作最后兜底
        material = "\n\n".join(t for t in
                              ((s.get("text") or "") for s in sources if isinstance(s, dict))
                              if t.strip())
    if not material.strip():
        iss(issues, "high", "material_missing", "case.json",
            "没有取到任何材料正文，所有「是否在材料里」的核验都不可信",
            "确认 case.json 的 materials 路径或 materials/ 目录存在且可读")
    pdoc = mk.read_json(os.path.join(work, "params_candidates.tsv"))  # 占位，真实解析在下面
    prep_params, perr = read_rows(os.path.join(work, "params_candidates.tsv"))
    if perr and perr not in ("not_found",):
        notes.append("params_candidates.tsv: %s" % perr)
    conflicts_doc = mk.read_json(os.path.join(work, "conflicts.json"))
    conflicts = (conflicts_doc or {}).get("conflicts") or []
    checklist_doc = mk.read_json(os.path.join(work, "elements_checklist.json"))
    checklist = (checklist_doc or {}).get("elements") or {}
    split_doc = mk.read_json(os.path.join(work, "splits_candidates.json"))
    splits = (split_doc or {}).get("splits") or []
    base_rows = mk.load_jsonl(os.path.join(work, "baselines_candidates.jsonl"))
    limit_rows = mk.load_jsonl(os.path.join(work, "limits_candidates.jsonl"))
    step_rows = mk.load_jsonl(os.path.join(work, "steps_candidates.jsonl"))
    del pdoc

    # ---------- 主体稿 ----------
    mpath, miss = pick(args.methods, METHODS_CANDIDATES, work)
    if mpath is None:
        iss(issues, "high", "methods_missing", "work", "找不到方法与实验章节稿（%s）" % (miss or {}).get("kind"),
            "把写好的稿子放到 work 目录，文件名用 methods.md")
        status = "failed"
        primary = {"summary": "缺少方法与实验章节稿，无法核验", "status_detail": "failed: methods_missing"}
        mk.emit_result(os.path.join(args.out, "result.json"), case_id, status, primary,
                       uncertainty=["稿子缺失，未产生任何核验结论。"],
                       contract=contract, extra_top={"issues": issues})
        print(mk.pjson({"status": status, "issues": {"high": len(issues)}}))
        return 2
    methods = io.open(mpath, encoding="utf-8-sig").read()
    if not methods.strip():
        iss(issues, "high", "methods_empty", "work", "稿子为空文件", "写入正文后再跑")
        status = "failed"
        primary = {"summary": "方法与实验章节稿为空", "status_detail": "failed: methods_empty"}
        mk.emit_result(os.path.join(args.out, "result.json"), case_id, status, primary,
                       uncertainty=["稿子为空，未产生任何核验结论。"],
                       contract=contract, extra_top={"issues": issues})
        print(mk.pjson({"status": status, "issues": {"high": len(issues)}}))
        return 2

    paras = split_paragraphs(methods)
    body_paras = [p for p in paras if p["kind"] == "body"]
    spans = section_spans(methods)

    # ---------- 1. 六节结构 ----------
    for key in SECTION_KEYS:
        if key not in spans:
            iss(issues, "high", "section_missing", "methods.md", "缺少要素小节：%s" % key,
                "按 ELEMENTS 六要素各写一节，标题写明该要素")
            continue
        a, b = spans[key]
        seg = methods[a:b]
        if len(mk.norm(seg)) < MIN_SECTION_CHARS:
            iss(issues, "medium", "section_too_short", "methods.md", "小节 %s 内容过短（%d 字符）"
                % (key, len(mk.norm(seg))), "补到能独立读懂的程度")
    order = [k for k in SECTION_KEYS if k in spans]
    if order != sorted(order, key=lambda k: spans[k][0]):
        iss(issues, "medium", "section_order", "methods.md", "小节出现顺序与方法步骤→设置→参数→数据集→对照→复现限制的常见顺序不同",
            "顺序本身不是硬错误，确认读者能顺着读下去")
    if not (methods.startswith("#") or HEADING_RE.search(methods)):
        iss(issues, "low", "no_headings", "methods.md", "稿子没有任何小节标题", "加标题便于审稿人定位")

    # ---------- 2. 正文数值与不可变成分 ----------
    num_idx = collect_number_index(facts, prep_params, material)
    number_pool = set(num_idx.keys())
    seen_nums = {}
    for m in mk.NUM_RE.finditer(methods):
        seen_nums.setdefault(m.group("val"), []).append(m.group(0))
    unverified = []
    for val, samples in seen_nums.items():
        if val not in num_idx:
            unverified.append((val, samples[0]))
    if unverified:
        for val, sample in unverified[:12]:
            iss(issues, "high", "number_not_in_material", "methods.md",
                "正文数值 %s 在材料、日志、配置与参数候选里都找不到来源" % sample,
                "要么给出处的文件与行，要么删掉这个数值")
        if len(unverified) > 12:
            iss(issues, "high", "number_not_in_material_more", "methods.md",
                "另有 %d 个数值同样查不到来源" % (len(unverified) - 12), "同上")
    unit_mismatch = []
    for val, samples in seen_nums.items():
        srcs = num_idx.get(val)
        if not srcs:
            continue
        src_units = set()
        for f in facts:
            for m in mk.NUM_RE.finditer(f.get("text", "") or ""):
                if m.group("val") == val and m.group("unit"):
                    src_units.add(m.group("unit").lower())
        for s in samples:
            for m in mk.NUM_RE.finditer(s):
                u = (m.group("unit") or "").lower()
                if u and src_units and u not in src_units:
                    unit_mismatch.append((s, sorted(src_units)))
    for s, src_units in unit_mismatch[:6]:
        iss(issues, "medium", "number_unit_mismatch", "methods.md",
            "数值 %s 的单位与材料里的写法不一致（材料：%s）" % (s, ", ".join(src_units)),
            "单位以材料/配置为准，不要换算后再写成另一个量纲")

    protected = {"citation": 0, "crossref": 0, "url": 0, "doi": 0, "formula": 0}
    mat_hard = hard(material)
    for kind in protected:
        got = mk.protected_spans(methods).get(kind) or []
        in_mat = {hard(x) for x in (mk.protected_spans(material).get(kind) or [])}
        for g in got:
            if hard(g) not in in_mat:
                protected[kind] += 1
                iss(issues, "high", "protected_token_not_in_material", "methods.md",
                    "%s 标记 %s 不在材料里" % (kind, g), "引用/图表指向必须与材料一致，不得杜撰")

    seeds_in_material = sorted(set(mk.SEED_RE.findall(material or "")))
    seeds_in_text = sorted(set(mk.SEED_RE.findall(methods)))
    if seeds_in_material and not seeds_in_text:
        iss(issues, "high", "seed_missing", "methods.md",
            "材料里给了随机种子（%s），稿子里一个都没写" % ", ".join(seeds_in_material),
            "随机种子属于「做得着」的硬信息，必须写进实验设置")
    def _ver_of(m):
        """只取版本号本身：VERSION_RE 的第一个分组是软件名（driver/cuda/torch…）。"""
        if isinstance(m, tuple):
            return m[-1] or ""
        return m or ""
    versions_in_material = sorted({_ver_of(m) for m in mk.VERSION_RE.findall(material or "")})
    versions_in_text = hard(methods)
    missing_versions = [v for v in versions_in_material if v and hard(v) not in versions_in_text]
    if missing_versions:
        iss(issues, "medium", "version_missing", "methods.md",
            "材料里的版本号 %s 未出现在稿子里" % ", ".join(missing_versions[:6]),
            "版本号决定能否复现，漏了就补上")

    # ---------- 3. 参数表 ----------
    ppath, pmiss = pick(args.params, PARAMS_CANDIDATES, work)
    params_rows, prouble = ([], None) if ppath is None else read_rows(ppath)
    if ppath is None:
        iss(issues, "high", "params_missing", "work", "缺少参数表 params.tsv", "把每个参数写成一行：name/value/unit/source")
    else:
        if prouble:
            iss(issues, "high", "params_unreadable", "params.tsv", "参数表读不出来：%s" % prouble, "按 tsv 表头写")
        cand_values = {}
        for p in prep_params:
            cand_values.setdefault(hard(str(p.get("value", ""))), []).append(p)
        for i, row in enumerate(params_rows, 1):
            cells = row.get("_cells") or []
            if len(cells) < 2:
                iss(issues, "high", "param_row_invalid", "params.tsv#%d" % i, "行里字段少于 2 个", "name 与 value 必填")
                continue
            val = mk.clean_value(cells[1])
            src = row.get("source") or (cells[3] if len(cells) > 3 else "")
            if not val:
                iss(issues, "high", "param_value_empty", "params.tsv#%d" % i, "参数 %s 没有取值" % cells[0], "补上取值或移出表")
                continue
            in_cand = hard(val) in cand_values
            # 数值型取值只按「材料里出现过的数值集合」比对：去标点后的子串匹配会让 48 混进
            # 0.4812 / 8,400 这类长数字里，把改过的参数值误判成"材料里有"。
            if NUMERIC_VALUE_RE.fullmatch(val):
                in_mat = val in number_pool
            else:
                in_mat = bool(hard(val)) and hard(val) in mat_hard
            if not in_cand and not in_mat:
                iss(issues, "high", "param_value_not_in_material", "params.tsv#%d" % i,
                    "参数 %s=%s 与材料、配置、日志都对不上" % (cells[0], val),
                    "取值必须来自材料；来源写清是哪个文件哪一行")
            if not src.strip():
                iss(issues, "low", "param_source_missing", "params.tsv#%d" % i,
                    "参数 %s 没写来源" % cells[0], "来源列是「写得准」的证据，补上")
        headline = {mk.flat(str(p.get("key", "")).lower()) for p in prep_params
                    if p.get("material_kind") == "config" and str(p.get("key", "")).lower() not in mk.SERIES_KEYS}
        # 参数名允许分层写法：配置里是 dropout，表里写 model.dropout 也算覆盖到
        covered_full = set()
        covered_tail = set()
        for r in params_rows:
            nm = mk.flat(str((r.get("_cells") or [""])[0]).lower())
            if not nm:
                continue
            covered_full.add(nm)
            covered_tail.add(nm.split(".")[-1])
        untouched = sorted(k for k in headline
                           if k not in covered_full and k.split(".")[-1] not in covered_tail)
        if untouched:
            iss(issues, "medium", "param_candidates_uncovered", "params.tsv",
                "配置文件里有 %d 个参数候选未进表（如 %s）" % (len(untouched), ", ".join(untouched[:8])),
                "要么补进表，要么在 gaps.json 里说明为什么不写")
    for cf in conflicts:
        txt = hard(methods)
        if hard(str(cf.get("key", ""))) not in txt:
            iss(issues, "medium", "conflict_unreported", "methods.md",
                "同名不同值的参数 %s 在稿子里没有交代" % cf.get("key"), "在复现限制一节写清取哪个值、依据是什么")
        else:
            vals = [v.get("value") for v in cf.get("values", [])]
            if not any(hard(str(v)) and hard(str(v)) in txt for v in vals):
                iss(issues, "medium", "conflict_value_unwritten", "methods.md",
                    "参数 %s 的取值一个都没写进正文" % cf.get("key"), "写明实际使用的取值")

    # ---------- 4. 划分一致性 ----------
    for sp in splits:
        name = str(sp.get("name") or sp.get("split") or "")
        num = str(sp.get("value") or sp.get("count") or sp.get("size") or "")
        if num and num not in methods:
            iss(issues, "high", "split_mismatch", "methods.md",
                "材料里划分 %s 的规模是 %s，稿子里没写或写成了别的数" % (name, num),
                "数据集划分是与运行记录对齐的硬信息")
    train_terms = len(re.findall(r"(?i)\btrain(?:ing)?\b|训练", methods))
    val_terms = len(re.findall(r"(?i)\b(?:val|valid|validation)\b|验证集", methods))
    test_terms = len(re.findall(r"(?i)\btest(?:ing)?\b|测试集", methods))
    if not (train_terms and val_terms and test_terms):
        iss(issues, "medium", "split_terms_incomplete", "methods.md",
            "训练/验证/测试三者的写法不全（train=%d val=%d test=%d）" % (train_terms, val_terms, test_terms),
            "划分口径要写全，否则无法照做")

    # ---------- 5. 六要素清单 ----------
    epath, emiss = pick(args.elements, ELEMENTS_CANDIDATES, work)
    elements = {}
    if epath is None:
        iss(issues, "high", "elements_missing", "work", "缺少要素清单 elements.json", "逐要素写 found/count/evidence")
    else:
        doc = mk.read_json(epath)
        elements = (doc or {}).get("elements") if isinstance(doc, dict) and "elements" in (doc or {}) else doc
        if not isinstance(elements, dict):
            iss(issues, "high", "elements_unreadable", "elements.json", "要素清单结构不对", "用 {\"elements\": {...}} 或直接给六键")
            elements = {}
    gpath, gmiss = pick(args.gaps, GAPS_CANDIDATES, work)
    gaps = []
    if gpath is not None:
        gdoc = mk.read_json(gpath)
        if gpath.lower().endswith(".jsonl"):
            gaps = mk.load_jsonl(gpath)
        elif isinstance(gdoc, dict):
            gaps = gdoc.get("gaps") or gdoc.get("items") or []
        elif isinstance(gdoc, list):
            gaps = gdoc
    gaps_text = mk.norm_hard(json.dumps(gaps, ensure_ascii=False))
    for key in SECTION_KEYS:
        cell = checklist.get(key) or {}
        found_in_material = bool(cell.get("found"))
        in_doc = bool(elements.get(key))
        in_text = key in spans
        if not found_in_material and not in_doc:
            iss(issues, "medium", "element_absent_silent", "elements.json",
                "材料里没有 %s 要素，稿子与要素清单都没交代" % key, "写进 gaps.json 交作者确认")
        if not in_doc and found_in_material:
            iss(issues, "medium", "element_not_declared", "elements.json",
                "材料里有 %s 要素，要素清单里没声明" % key, "六要素要逐一交代覆盖情况")
        if in_doc and not in_text and found_in_material:
            iss(issues, "medium", "element_not_written", "methods.md",
                "要素清单声明 %s 已覆盖，正文却没有对应小节" % key, "正文与清单必须对得上")

    # ---------- 6. 对照 ----------
    bnames = {hard(str(b.get("name", ""))) for b in base_rows}
    btext = hard(methods)
    for b in base_rows:
        nm = str(b.get("name", ""))
        if hard(nm) not in btext:
            iss(issues, "medium", "baseline_not_in_text", "methods.md",
                "材料里的对照 %s 没进正文" % nm, "对照实验要写全，否则增益无从判断")
    GENERIC_BASELINE = {"baseline", "baselines", "control", "controls", "compare", "comparison",
                        "vs", "versus", "section", "table", "figure", "method", "methods",
                        "model", "models", "our", "the", "this", "study", "approach"}
    for m in re.finditer(r"(?i)(?P<n>[A-Za-z][\w\-]{2,30})\s*(?:as\s+)?(?:baseline|基线|对照)", methods):
        nm = m.group("n")
        if nm.lower() in GENERIC_BASELINE:
            continue
        if hard(nm) not in bnames and hard(nm) not in mat_hard:
            iss(issues, "medium", "baseline_not_in_material", "methods.md",
                "正文把 %s 称作对照，但材料里没有这个对照" % nm, "对照必须真实存在，不得临时编一个")
    if not base_rows and "baseline" not in btext and "基线" not in methods:
        iss(issues, "medium", "baseline_missing", "methods.md", "全篇没有对照实验的交代", "补对照与同预算说明")

    # ---------- 7. 限制 ----------
    lim_span = spans.get("repro_limits")
    lim_seg = methods[lim_span[0]:lim_span[1]] if lim_span else methods
    lim_hard = hard(lim_seg)
    for l in limit_rows:
        quote = str(l.get("quote", ""))
        nums = [m.group("val") for m in mk.NUM_RE.finditer(quote)]
        if nums:
            # 有具体数值的限制：数值必须落到「复现限制」一节里（改写不算漏）
            missing_nums = [n for n in nums if hard(n) not in lim_hard]
            if missing_nums:
                iss(issues, "medium", "limit_not_written", "methods.md",
                    "限制里的数值 %s 没写进复现限制一节：%s…" % (", ".join(missing_nums), quote[:40]),
                    "限制要逐条落实；数值是判断失效场景的关键")
            continue
        # 没有数值的限制：按关键内容词覆盖度判定，避免要求逐字照抄
        toks = [t for t in mk.tokens(quote) if len(t) >= 3 and not t.isdigit()]
        hit = sum(1 for t in toks if hard(t) and hard(t) in lim_hard)
        if toks and hit / float(len(toks)) < 0.5:
            iss(issues, "medium", "limit_not_written", "methods.md",
                "材料里的限制条目未写进复现限制一节：%s…" % quote[:40], "限制要逐条落实")
    for m in re.finditer(r"(?:有待|尚需|有待于|还需)(?:进一步)?(?:研究|验证|探索)|"
                         r"(?:future\s+work|remains?\s+(?:unclear|unknown|open))", methods, re.I):
        seg = methods[max(0, m.start() - 80):m.end() + 60]
        # 作者把它当作「需要补条件」的待确认项写出来，就不是把套话当结论——不报。
        if re.search(r"需(?:要)?(?:作者)?确认|待确认|追问|列入|材料未(?:给出|说明)|不足以判定|不可用", seg):
            continue
        iss(issues, "medium", "limit_too_vague", "methods.md",
            "限制写得笼统：%s" % mk.norm(seg)[:80], "指向具体失效场景（什么条件下会失效、哪种数据下不成立）")
    for m in BOILERPLATE.finditer(methods):
        iss(issues, "low", "boilerplate_phrase", "methods.md",
            "出现评价性套话：%s" % m.group(0), "换成可核对的描述")

    # ---------- 8. 复现清单 ----------
    rpath, rmiss = pick(args.repro, REPRO_CANDIDATES, work)
    repro = {}
    if rpath is None:
        iss(issues, "high", "repro_missing", "work", "缺少复现清单 repro.json", "版本/环境/种子/命令四项都要有")
    else:
        repro = mk.read_json(rpath) or {}
        if not isinstance(repro, dict):
            iss(issues, "high", "repro_unreadable", "repro.json", "结构不是对象", "改成对象")
            repro = {}
        fields = {
            "versions": r"(?i)version|版本",
            "environment": r"(?i)env|环境|依赖|requirements|docker|conda",
            "seeds": r"(?i)seed|种子",
            # 命令字段要认真正的可执行入口：只写 python 版本号（python 3.10.13）不算命令
            "commands": (r"(?i)(python|py)\s+[-\w./\\]+\.py|"
                         r"\b(?:bash|sh|zsh|sbatch|qsub|make|docker\s+run)\b|"
                         r"[\w./\\-]+\.(?:sh|ipynb|cmd|ps1)\b|"
                         r"\b(?:command|命令|cmd)\b\s*[:：]"),
        }
        flat_repro = mk.norm_hard(json.dumps(repro, ensure_ascii=False))
        for key, pat in fields.items():
            if key not in repro or not repro.get(key):
                if not re.search(pat, flat_repro):
                    iss(issues, "high", "repro_incomplete", "repro.json",
                        "复现清单缺少 %s" % key, "四项缺一不可：版本、环境、种子、命令")
        for m in mk.NUM_RE.finditer(json.dumps(repro, ensure_ascii=False)):
            if m.group("val") not in num_idx:
                iss(issues, "high", "repro_number_not_in_material", "repro.json",
                    "复现清单里的数值 %s 在材料里查不到" % m.group(0), "复现清单不许出现材料外数值")
                break
        for m in mk.CMD_RE.finditer(json.dumps(repro, ensure_ascii=False)):
            cmd = m.group("cmd")
            if hard(cmd) not in mat_hard:
                # 命令允许只给脚本名（完整命令行常被排版拆开）
                script = re.search(r"([\w\-]+\.(?:py|sh|ipynb|R|m))", cmd)
                if not (script and hard(script.group(1)) in mat_hard):
                    iss(issues, "medium", "repro_command_not_in_material", "repro.json",
                        "命令 %s 在材料里找不到" % cmd[:60], "命令要能在材料/脚本里对上")

    # ---------- 9. 来源映射 ----------
    spath, smiss = pick(args.source_map, SOURCEMAP_CANDIDATES, work)
    fact_ids = {f.get("fact_id") for f in facts}
    fact_text = {f.get("fact_id"): f.get("text", "") for f in facts}
    mapped_ids = set()
    mapped_paras = set()
    if spath is None:
        iss(issues, "high", "source_map_missing", "work", "缺少事实与来源映射 source_map.json",
            "逐段写出用了哪些 fact_id 与原文片段")
    else:
        sm = mk.read_json(spath)
        rows = sm if isinstance(sm, list) else ((sm or {}).get("items") or (sm or {}).get("sources") or [])
        if not rows and isinstance(sm, dict):
            rows = [{"para_id": k, "v": v} for k, v in sm.items() if isinstance(v, (dict, list))]
        for i, r in enumerate(rows if isinstance(rows, list) else [], 1):
            pid = r.get("para_id") or r.get("paragraph") or r.get("id") or r.get("seg_id")
            if pid:
                mapped_paras.add(pid)
            quotes = []
            ids = []
            for key in ("fact_ids", "facts", "source_ids", "sources", "evidence"):
                v = r.get(key)
                if isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            ids.append(x)
                        elif isinstance(x, dict):
                            if x.get("fact_id"):
                                ids.append(x["fact_id"])
                            if x.get("quote"):
                                quotes.append(x["quote"])
                elif isinstance(v, str) and v.startswith("f-"):
                    ids.append(v)
            if r.get("quote"):
                quotes.append(r["quote"])
            if r.get("fact_id"):
                ids.append(r["fact_id"])
            for fid in ids:
                mapped_ids.add(fid)
                if fid not in fact_ids:
                    iss(issues, "high", "source_fact_unknown", "source_map.json",
                        "引用了不存在的事实编号 %s" % fid, "只能用 facts.jsonl 里给出的 fact_id")
            for q in quotes:
                qq = hard(q)
                if len(qq) < MIN_SOURCE_QUOTE:
                    iss(issues, "low", "source_quote_too_short", "source_map.json",
                        "引用片段过短：%s" % q, "至少给一个能定位的短语")
                    continue
                if qq not in mat_hard:
                    iss(issues, "high", "source_quote_not_found", "source_map.json",
                        "引用片段在材料里找不到：%s" % mk.norm(q)[:60], "必须逐字来自材料")
                if len(qq) > 240:
                    iss(issues, "medium", "source_quote_not_minimal", "source_map.json",
                        "引用片段过长（%d 字符）" % len(qq), "裁到支撑该句所需的最小范围")
            if pid and quotes:
                # 改写是常态，所以这里按「关键内容词是否覆盖」判断，
                # 不要求引用原句逐字出现在稿子里。
                ptext = ""
                for p in body_paras:
                    if p["para_id"] == pid:
                        ptext = hard(p["text"])
                        break
                if not ptext:
                    ptext = hard(methods)
                toks = [t for t in mk.tokens(quotes[0]) if len(t) >= 3 and not t.isdigit()]
                hit = sum(1 for t in toks if hard(t) in ptext)
                if toks and hit == 0:
                    iss(issues, "low", "source_quote_not_in_methods", "source_map.json",
                        "映射到 %s 的引用片段与正文该段几乎没有共同内容词" % pid,
                        "确认这条映射确实支撑该段；若正文已改写，保留原句作依据也说明清楚")
        if not rows:
            iss(issues, "high", "source_map_empty", "source_map.json", "映射文件是空的", "逐段写清来源")

    # ---------- 10. 未映射段落 ----------
    if body_paras:
        fact_quotes = [hard(t)[:20] for t in fact_text.values() if len(hard(t)) >= MIN_SOURCE_QUOTE]
        for p in body_paras:
            ptxt = mk.norm_hard(p["text"])
            hit = any(fq and fq in ptxt for fq in fact_quotes)
            if hit or p["para_id"] in mapped_paras:
                continue
            if len(mk.norm(p["text"])) < 40:
                continue
            iss(issues, "medium", "paragraph_unmapped", "methods.md",
                "段落 %s 找不到材料出处，也没有在 source_map 里登记" % p["para_id"],
                "补上来源或标记为作者判断")

    # ---------- 11. 步骤完整性 ----------
    steps_span = spans.get("steps")
    if steps_span:
        seg = methods[steps_span[0]:steps_span[1]]
        n_items = len(re.findall(r"(?m)^\s*(?:\d+[.、)]|[-*•])\s+\S", seg)) or len(re.split(r"\n\s*\n", seg.strip()))
        if n_items < 2:
            iss(issues, "medium", "steps_too_few", "methods.md", "方法步骤一节条目过少（%d 条）" % n_items,
                "按可执行顺序列出步骤")
        if not mk.CMD_RE.search(seg) and not re.search(r"`[^`]{3,}`", seg):
            iss(issues, "medium", "step_no_command", "methods.md",
                "方法步骤一节里没有任何命令或脚本名", "「做得着」要求给出可执行入口")
        io_hits = len(re.findall(r"(?i)\b(?:input|output|输入|输出)\b", seg))
        if io_hits == 0:
            iss(issues, "medium", "step_no_io", "methods.md",
                "方法步骤一节没有交代输入与输出", "每步写清输入、动作、输出")

    # ---------- 状态与产物 ----------
    highs = [i for i in issues if i["level"] == "high"]
    meds = [i for i in issues if i["level"] == "medium"]
    lows = [i for i in issues if i["level"] == "low"]
    status = "partial" if highs else "ok"

    metrics = {
        "sections_found": len(spans),
        "sections_expected": len(SECTION_KEYS),
        "paragraphs": len(paras),
        "body_paragraphs": len(body_paras),
        "numbers_in_text": len(seen_nums),
        "numbers_unverified": len(unverified),
        "numbers_verified_rate": round(1.0 - (len(unverified) / len(seen_nums)), 4) if seen_nums else 1.0,
        "params_rows": len(params_rows),
        "param_candidates": len(prep_params),
        "steps_candidates": len(step_rows),
        "baselines": len(base_rows),
        "limits": len(limit_rows),
        "limits_concrete": sum(1 for l in limit_rows if l.get("concrete")),
        "splits": len(splits),
        "conflicts": len(conflicts),
        "facts": len(facts),
        "mapped_facts": len(mapped_ids),
        "protect_mismatch": sum(protected.values()),
        "issues_high": len(highs),
        "issues_medium": len(meds),
        "issues_low": len(lows),
        "version": VERSION,
    }

    out_methods = os.path.join(args.out, "methods.md")
    mk.dump_text(out_methods, methods if methods.endswith("\n") else methods + "\n")
    if ppath:
        mk.dump_text(os.path.join(args.out, "params.tsv"),
                     io.open(ppath, encoding="utf-8-sig").read())
    for name, path, doc in (("elements.json", epath, elements), ("gaps.json", gpath, gaps),
                            ("repro.json", rpath, repro)):
        if path:
            try:
                mk.dump_json(os.path.join(args.out, name), mk.read_json(path) if path.lower().endswith(".json") else doc)
            except Exception:  # noqa: BLE001
                mk.dump_json(os.path.join(args.out, name), doc)
        else:
            mk.dump_json(os.path.join(args.out, name), doc if doc else {})
    if spath:
        try:
            mk.dump_json(os.path.join(args.out, "source_map.json"),
                         mk.read_json(spath) if spath.lower().endswith(".json") else mk.load_jsonl(spath))
        except Exception:  # noqa: BLE001
            mk.dump_json(os.path.join(args.out, "source_map.json"), {})

    mk.dump_json(os.path.join(args.out, "consistency.json"), {
        "version": VERSION,
        "metrics": metrics,
        "sections": {k: {"chars": len(mk.norm(methods[v[0]:v[1]]))} for k, v in spans.items()},
        "numbers": {"verified": sorted(v for v in seen_nums if v in num_idx),
                    "unverified": sorted(v for v, _ in unverified)},
        "protected_mismatch": protected,
        "params_checked": len(params_rows),
        "conflicts": conflicts,
    })

    check = {
        "status": status,
        "metrics": metrics,
        "checks": {
            "sections": {"expected": list(SECTION_KEYS), "found": sorted(spans)},
            "numbers": {"unverified": [s for _, s in unverified]},
            "seeds": {"in_material": seeds_in_material, "in_text": seeds_in_text},
            "versions_missing": missing_versions[:6],
            "conflicts": [c.get("key") for c in conflicts],
            "element_absent": [k for k in SECTION_KEYS if not (checklist.get(k) or {}).get("found")],
        },
        "issues": issues,
        "unresolved": [
            "本核验只覆盖可机械比对的部分：数值/单位/划分/版本/种子/引用标记/命令是否与材料对得上。",
            "步骤写得是否真能让别人照做、对照是否公平、限制是否切中要害，需要作者与审稿人判断。",
            "材料本身未记录的实验细节无法凭空核验，只能以 gaps.json 的形式交作者确认。",
        ],
    }
    mk.dump_json(os.path.join(args.out, "check.json"), check)

    diff_lines = ["# 稿子与材料的对账（自动生成）", ""]
    diff_lines.append("| 项 | 数量 | 说明 |")
    diff_lines.append("| --- | --- | --- |")
    diff_lines.append("| 小节 | %d/%d | %s |" % (len(spans), len(SECTION_KEYS), ", ".join(sorted(spans))))
    diff_lines.append("| 正文数值 | %d | 未验证 %d |" % (len(seen_nums), len(unverified)))
    diff_lines.append("| 参数表 | %d 行 | 候选 %d 个 |" % (len(params_rows), len(prep_params)))
    diff_lines.append("| 对照 | %d | 限制 %d 条（具体 %d） |" % (len(base_rows), len(limit_rows),
                                                       metrics["limits_concrete"]))
    diff_lines.append("| 来源映射 | %d 条事实 | 引用片段逐字命中材料 |" % len(mapped_ids))
    diff_lines.append("")
    if unverified:
        diff_lines.append("## 查不到来源的数值")
        for _, s in unverified:
            diff_lines.append("- `%s`" % s)
        diff_lines.append("")
    mk.dump_text(os.path.join(args.out, "diff.md"), "\n".join(diff_lines) + "\n")

    review = ["# 核验报告（自动生成）", "",
              "状态：**%s**（high %d / medium %d / low %d）" % (status, len(highs), len(meds), len(lows)), ""]
    for title, group in (("必须修（high）", highs), ("建议修（medium）", meds), ("提示（low）", lows)):
        review.append("## %s" % title)
        if not group:
            review.append("（无）")
        for i in group[:40]:
            line = "- `%s` @ %s：%s" % (i["kind"], i["where"], i["detail"])
            if i.get("hint"):
                line += " —— %s" % i["hint"]
            review.append(line)
        review.append("")
    review.append("## 核验边界")
    for u in check["unresolved"]:
        review.append("- %s" % u)
    mk.dump_text(os.path.join(args.out, "review.md"), "\n".join(review) + "\n")

    evidence = []
    for f in facts[:8]:
        evidence.append({"fact_id": f.get("fact_id"), "source": f.get("src_id"),
                         "quote": (f.get("text") or "")[:120]})
    artifacts = []
    for name in sorted(os.listdir(args.out)):
        p = os.path.join(args.out, name)
        if os.path.isfile(p) and name != "result.json":
            artifacts.append({"path": name, "role": "deliverable",
                              "bytes": os.path.getsize(p), "sha256": mk.sha256_file(p)})

    primary = {
        "summary": "方法与实验章节核验完成：六节 %d/%d，数值未验证 %d 个，high %d 条"
                   % (len(spans), len(SECTION_KEYS), len(unverified), len(highs)),
        "status_detail": status if status == "ok" else "partial: %d high" % len(highs),
        "sections_found": sorted(spans),
        "issues_high": len(highs),
    }
    uncertainty = []
    if unverified:
        uncertainty.append("有 %d 个正文数值在材料里查不到来源，可能是材料缺口，也可能需要补出处。" % len(unverified))
    if conflicts:
        uncertainty.append("材料里存在同名不同值的参数（%s），稿子里的取值需要作者确认。"
                           % ", ".join(str(c.get("key")) for c in conflicts))
    uncertainty.append("本核验不判断实验设计是否合理、对照是否公平，这些需要作者与审稿人判断。")

    mk.emit_result(os.path.join(args.out, "result.json"), case_id, status, primary,
                   evidence=evidence, uncertainty=uncertainty, artifacts=artifacts,
                   contract=contract, extra_top={"issues": issues})
    print(mk.pjson({"status": status, "sections": len(spans), "numbers": len(seen_nums),
                    "unverified": len(unverified), "params": len(params_rows),
                    "high": len(highs), "medium": len(meds), "low": len(lows)}))
    return 0 if status in ("ok", "partial") else 2


if __name__ == "__main__":
    sys.exit(main())
