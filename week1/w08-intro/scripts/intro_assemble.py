#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intro_assemble —— 引言与相关工作写作 Skill 的第三步（硬核验 + 导出）。

读取（默认在 --work 目录里）：
  introduction.md            Agent 写的正文（四节齐全）
  claims.jsonl               逐条论断：text / citations[] / source{para_id,quote} / kind
  contributions.jsonl        贡献条目：text / anchor(section|figure|table|result) / evidence
  groups.jsonl               相关工作分组：dimension / members[](引用 key) / compare_on / summary
  citation_map.json          引用 key -> {authors, year, venue, doi, title}
  gaps.jsonl（可选）          空白推导：statement / from_refs[] / how_filled
  glossary/terms.jsonl（可选）术语一致性

核验后导出到 --out：
  introduction.md  citation_map.json  claims.jsonl  contributions.jsonl  groups.jsonl
  gaps.jsonl  check.json  review.md  diff.md  result.json
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import introkit as ik  # noqa: E402

VERSION = "intro_assemble/1.0"
INTRO_CANDIDATES = ("introduction.md", "intro.md", "introduction.txt", "related_work.md", "manuscript.md")
CLAIM_CANDIDATES = ("claims.jsonl", "claims.json", "claim_map.jsonl", "facts.jsonl")
CONTRIB_CANDIDATES = ("contributions.jsonl", "contributions.json", "contribution.jsonl")
GROUP_CANDIDATES = ("groups.jsonl", "groups.json", "grouping.jsonl")
CITEMAP_CANDIDATES = ("citation_map.json", "citations.json", "references_map.json", "citation-map.json")
GAP_CANDIDATES = ("gaps.jsonl", "gaps.json", "gap.jsonl")
TERM_CANDIDATES = ("terms.jsonl", "glossary.jsonl", "terms.json")
SECTIONS = ("background", "related_work", "gap", "contributions")
SECTION_ZH = {"background": "研究背景", "related_work": "相关工作", "gap": "研究空白", "contributions": "贡献"}
AUTHOR_JUDGMENT = {"author_judgment", "judgment", "opinion", "author_view", "interpretation", "作者判断", "本文判断"}
CONTRIBUTION_KINDS = {"contribution", "contributions", "contribution_statement", "novelty", "本文贡献", "贡献"}
OWN_RESULT_KINDS = {"own_result", "our_result", "result", "results", "own_work", "experimental_result",
                    "measurement", "本文结果", "实验结果", "结果"}
GAP_KINDS = {"gap", "research_gap", "knowledge_gap", "研究空白", "空白"}
UNCERTAIN_KINDS = AUTHOR_JUDGMENT | {"uncertain", "needs_confirmation", "to_verify", "unclear", "待确认"}
CONTRIB_ANCHOR_KINDS = {"section", "figure", "fig", "table", "tab", "result", "equation", "eq", "appendix", "supplementary", "正文", "图表", "结果"}
# 扁平写法（`result_anchor: "Table 1"`）→ 锚点类型
CONTRIB_FLAT_KIND = {"result_anchor": "result", "figure": "figure", "table": "table",
                     "equation": "equation", "result": "result", "section": "section"}


def load_first(work, names, want_jsonl=True, key=None):
    for n in names:
        p = os.path.join(work, n)
        if not os.path.exists(p):
            continue
        if n.endswith(".jsonl"):
            rows = ik.read_jsonl(p)
            return rows, p
        data = ik.read_json(p, default={})
        if isinstance(data, list):
            return data, p
        for k in (key or "items", "entries", "claims", "contributions", "groups", "gaps", "records", "terms"):
            if isinstance(data, dict) and isinstance(data.get(k), list):
                return data[k], p
        if isinstance(data, dict):
            return data, p
    return None, None


def find_sections(text):
    """返回 {section: (start, end, heading_text)}"""
    hits = []
    for name, rx in getattr(ik, "SECTION_PATTERNS", ()):
        m = rx.search(text or "")
        if m:
            hits.append((m.start(), name, m.group(0).strip()))
    hits.sort()
    out = {}
    for i, (start, name, head) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out[name] = (start, end, head)
    return out, hits


def sentence_index(text):
    idx = {}
    for s, off in ik.sentences(text or ""):
        idx[ik.norm_hard(s)] = (s, off)
    return idx


def main():
    ap = argparse.ArgumentParser(description="引言与相关工作写作 —— 硬核验与导出")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--introduction", default=None)
    ap.add_argument("--claims", default=None)
    ap.add_argument("--contributions", default=None)
    ap.add_argument("--groups", default=None)
    ap.add_argument("--citation-map", dest="citation_map", default=None)
    ap.add_argument("--gaps", default=None)
    ap.add_argument("--terms", default=None)
    args = ap.parse_args()

    issues = []

    def iss(level, kind, where, detail):
        issues.append({"level": level, "kind": kind, "where": where, "detail": detail})

    work = args.work
    out = args.out
    os.makedirs(out, exist_ok=True)

    case, ctx = ik.load_case(args.case)
    ctx["_case_raw"] = case
    material = ctx.get("material_text") or ""
    refs, _w = ik.load_bibliography(*ctx.get("bib_docs") or [])
    material_hard = ik.norm_hard(material)
    material_flat = ik.flat(material)

    ref_by_key = {}
    key_to_num = {}
    positional = {}
    explicit_num = any(r.get("num") is not None for r in refs)
    for i, r in enumerate(refs, 1):
        rk = (r.get("key") or "").lower()
        ref_by_key[rk] = r
        # citation_key_of() 给非编号引用加 "k:" 前缀，这里必须同样登记，
        # 否则作者-年份引用（`Peters et al. (2018)`）会被判成"引用了表外条目"。
        ref_by_key.setdefault("k:" + rk, r)
        # 文献表派生的别名（首作者姓+年、纯姓）也登记，两种排版都能对上
        for alias in (ik.ref_key_from_raw(r.get("raw") or ""),
                      re.sub(r"[^a-z0-9]", "", ik._first_author_surname(r.get("authors") or "").lower())):
            if alias:
                ref_by_key.setdefault(alias, r)
                ref_by_key.setdefault("k:" + alias, r)
        num = r.get("num")
        if num is not None:
            ref_by_key["n:" + str(num).lower()] = r
            key_to_num[rk] = str(num)
            key_to_num["n:" + str(num).lower()] = str(num)
        if not explicit_num:
            positional["n:" + str(i)] = r.get("key")
            ref_by_key.setdefault("n:" + str(i), r)
            key_to_num.setdefault(rk, str(i))
            key_to_num.setdefault("n:" + str(i), str(i))

    def canon(k):
        """把任意引用写法（BibTeX key / 编号 n:3 / 原始标记）归一到同一个规范 key。

        这样正文里写编号、分组里写 BibTeX key 也能对上——两侧都能被解析到同一条文献。
        """
        k = str(k).strip().lower()
        rec = ref_by_key.get(k)
        if rec is not None:
            return (rec.get("key") or k).lower()
        return k

    bib_keys = set(ref_by_key.keys())
    bib_canon = {canon(k) for k in bib_keys}

    def key_known(k):
        """判断一个引用写法是否落在文献表里。

        代理产物可能写 BibTeX key、`n:3`、也可能是**裸编号 3**（真实 Agent 最常见的写法），
        三种都要认，否则会把"正文写 [3]、claims 里也写 3"这种完全正确的交付判成编造引用。
        """
        k = str(k).strip().lower()
        if not k:
            return True
        cands = [k, canon(k)]
        if re.match(r"^\d+$", k):
            cands += ["n:" + k]
        elif k.startswith("n:") and k[2:].isdigit():
            cands += [k[2:]]
        if not k.startswith("k:"):
            cands += ["k:" + k]
        for c in cands:
            if c in bib_keys or canon(c) in bib_canon:
                return True
        return False

    canon_record = {}
    for k, rec in ref_by_key.items():
        canon_record.setdefault(canon(k), rec)

    # ---------------------------------------------------------- 读代理产物
    def pick(explicit, candidates, jsonl=True, key=None):
        if explicit:
            p = explicit if os.path.isabs(explicit) else os.path.join(work, explicit)
            if os.path.exists(p):
                if p.endswith(".jsonl"):
                    return ik.read_jsonl(p), p
                d = ik.read_json(p, default={})
                if isinstance(d, list):
                    return d, p
                for k in (key or "items", "entries", "claims", "contributions", "groups", "records"):
                    if isinstance(d, dict) and isinstance(d.get(k), list):
                        return d[k], p
                return d, p
            iss("high", "provided_file_missing", explicit, "命令里指定了该文件但不存在")
        return load_first(work, candidates, jsonl, key)

    intro_path = None
    for n in ([args.introduction] if args.introduction else []) + list(INTRO_CANDIDATES):
        if not n:
            continue
        p = n if os.path.isabs(n) else os.path.join(work, n)
        if os.path.exists(p):
            intro_path = p
            break
    if not intro_path:
        ik.dump_json(os.path.join(out, "check.json"), {
            "status": "failed", "issues": [{"level": "high", "kind": "introduction_missing",
                                            "where": work, "detail": "没有找到 introduction.md"}],
            "metrics": {}, "unresolved": ["缺少正文，无法核验。"]})
        ik.emit_result(os.path.join(out, "result.json"), ctx.get("case_id"), "failed",
                       {"reason": "introduction_missing"}, contract=ctx.get("contract"))
        ik.pjson({"status": "failed", "reason": "introduction_missing", "hint": "把正文写到 /app/work/introduction.md 后重跑。"})
        return 2
    with open(intro_path, "r", encoding="utf-8-sig") as fh:
        intro = ik.norm(fh.read())
    if not intro.strip():
        iss("high", "introduction_empty", intro_path, "正文文件为空")

    claims, claims_path = pick(args.claims, CLAIM_CANDIDATES, key="claims")
    contribs, contrib_path = pick(args.contributions, CONTRIB_CANDIDATES, key="contributions")
    groups, groups_path = pick(args.groups, GROUP_CANDIDATES, key="groups")
    cmap, cmap_path = pick(args.citation_map, CITEMAP_CANDIDATES, key="citation_map")
    gaps, gaps_path = pick(args.gaps, GAP_CANDIDATES, key="gaps")
    terms, terms_path = pick(args.terms, TERM_CANDIDATES, key="terms")

    # ---------------------------------------------------------- 1. 结构
    sec, hits = find_sections(intro)
    for name in SECTIONS:
        if name not in sec:
            iss("high", "section_missing", name, "缺少「%s」小节" % SECTION_ZH[name])
    order = [h[1] for h in hits]
    if order and order != sorted(order, key=lambda n: SECTIONS.index(n) if n in SECTIONS else 99):
        iss("medium", "section_order", ",".join(order), "四节顺序应为 研究背景 → 相关工作 → 研究空白 → 贡献")
    sec_chars = {n: (sec[n][1] - sec[n][0]) for n in sec}
    for n, c in sec_chars.items():
        if c < 80:
            iss("medium", "section_too_short", n, "「%s」只有 %d 字符" % (SECTION_ZH[n], c))

    # ---------------------------------------------------------- 2. 引用完整性
    cites = ik.parse_citations(intro)
    used_keys = []
    for c in cites:
        for k in c.get("keys") or []:
            used_keys.append(ik.citation_key_of(c["kind"], k))
    used_set = sorted(set(used_keys))
    used_canon = {canon(k) for k in used_set}
    unresolved = [k for k in used_set if k not in bib_keys and canon(k) not in bib_canon]
    for k in unresolved:
        iss("high", "citation_unresolved", k, "正文引用了文献表里没有的条目")
    uncited = sorted(k for k in bib_keys if canon(k) not in used_canon and not k.startswith("auto:"))
    if uncited:
        iss("medium" if len(uncited) > 1 else "low", "reference_uncited", ",".join(uncited[:8]),
            "文献表里有 %d 条未被正文引用（不代表必须引用，但需说明取舍）" % len(uncited))

    # citation_map 与文献表比对
    cmap_rows = []
    if isinstance(cmap, dict) and cmap and not cmap.get("__load_error__"):
        for k, v in cmap.items():
            if isinstance(v, dict):
                cmap_rows.append({"key": k, **v})
            else:
                cmap_rows.append({"key": k, "value": v})
    elif isinstance(cmap, list):
        cmap_rows = [x for x in cmap if isinstance(x, dict)]
    else:
        iss("high", "citation_map_missing", work, "缺少 citation_map.json（引用 key → 元数据）")
    cmap_by_key = {}
    cmap_aliases = {}
    for row in cmap_rows:
        k = (row.get("key") or row.get("citation") or row.get("id") or "").strip()
        if not k:
            continue
        cmap_by_key[k.lower()] = row
        # 编号与 BibTeX key 是同一份对照的两种写法，互为别名
        for a in (row.get("bibtex_key"), row.get("ref_key"), row.get("citekey"), row.get("ref")):
            if isinstance(a, str) and a.strip():
                cmap_aliases.setdefault(a.strip().lower(), k.lower())
        if k.lower().startswith("n:") or k.isdigit():
            num = key_to_num.get(k.lower()) or (k[2:] if k.lower().startswith("n:") else k)
            cmap_aliases.setdefault("n:" + str(num), k.lower())
            cmap_aliases.setdefault(str(num), k.lower())

    def cmap_lookup(k):
        kk = str(k).strip().lower()
        for cand in (kk, canon(kk), cmap_aliases.get(kk) or "", ("n:" + key_to_num.get(kk, "")) if key_to_num.get(kk) else ""):
            if cand and cand in cmap_by_key:
                return cmap_by_key[cand]
        num = key_to_num.get(kk)
        if num and ("n:" + num) in cmap_by_key:
            return cmap_by_key["n:" + num]
        return None

    for k in used_set:
        row = cmap_lookup(k)
        if row is None:
            iss("medium", "citation_map_entry_missing", k, "正文用到但 citation_map 里没有这一条")
            continue
        ref = ref_by_key.get(k.lower()) or canon_record.get(canon(k))
        if not ref:
            continue
        for fld, aliases in (("year", ("year",)), ("authors", ("authors", "author")), ("doi", ("doi", "DOI")),
                             ("venue", ("venue", "journal", "source", "container-title"))):
            got = None
            for a in aliases:
                if row.get(a) not in (None, ""):
                    got = str(row.get(a))
                    break
            want = str(ref.get(fld) or "")
            if not want or not got:
                continue
            if fld == "authors":
                ok = ik.norm_hard(want).startswith(ik.norm_hard(got)[:8]) or ik.norm_hard(got).startswith(ik.norm_hard(want)[:8])
            elif fld == "year":
                ok = str(got).strip()[:4] == want.strip()[:4]
            elif fld == "doi":
                ok = ik.norm_hard(got) == ik.norm_hard(want)
            else:
                ok = ik.norm_hard(got)[:15] == ik.norm_hard(want)[:15]
            if not ok:
                iss("medium", "citation_metadata_mismatch", "%s.%s" % (k, fld),
                    "citation_map 写的是 %r，文献表是 %r" % (got[:60], want[:60]))
    for k in cmap_by_key:
        if k in bib_keys or canon(k) in bib_canon:
            continue
        # 主键写成编号、BibTeX key 放在 bibtex_key 字段里也算合格
        alias = cmap_aliases.get(k)
        if alias and (alias in bib_keys or canon(alias) in bib_canon):
            continue
        row = cmap_by_key[k]
        bk = str(row.get("bibtex_key") or "").strip().lower()
        if bk and (bk in bib_keys or canon(bk) in bib_canon):
            continue
        iss("high", "citation_map_unknown_key", k, "citation_map 里的 key 不在文献表中（疑似编造）")

    # ---------------------------------------------------------- 3. 论断绑定
    intro_hard = ik.norm_hard(intro)
    sent_idx = sentence_index(intro)
    claim_count = 0
    claims_with_citation = 0
    claims_with_source = 0
    claims_verified_quote = 0
    claims_number_bound = 0
    if not claims or (isinstance(claims, dict) and claims.get("__load_error__")):
        iss("high", "claims_missing", work, "缺少 claims.jsonl（逐条论断的引用与来源绑定）")
        claims = []
    else:
        claim_count = len(claims)
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                iss("high", "claim_row_invalid", "claims#%d" % i, "记录不是对象")
                continue
            where = c.get("claim_id") or c.get("id") or "claims#%d" % i
            text = ik.norm(c.get("text") or c.get("claim") or c.get("sentence") or "")
            if not text:
                iss("high", "claim_text_missing", where, "缺 text")
                continue
            if ik.norm_hard(text) not in intro_hard:
                loose = max((difflib.SequenceMatcher(None, ik.norm_hard(text), k).ratio() for k in sent_idx),
                            default=0.0) if sent_idx else 0.0
                if loose >= 0.92:
                    iss("low", "claim_text_whitespace_variant", where, "论断句与正文只是空白/标点差异")
                else:
                    iss("high", "claim_text_not_in_introduction", where,
                        "论断句在正文里找不到逐字对应：%s" % text[:70])
            kind = str(c.get("claim_kind") or c.get("kind") or c.get("type") or "").strip().lower()
            cits = c.get("citations") or c.get("citation_keys") or c.get("refs") or []
            if isinstance(cits, str):
                cits = [cits]
            cits = [str(x) for x in cits if str(x).strip()]
            if cits:
                claims_with_citation += 1
            else:
                pos = intro_hard.find(ik.norm_hard(text))
                in_gap = ("gap" in sec) and sec["gap"][0] <= pos < sec["gap"][1] and pos >= 0
                in_contrib = ("contributions" in sec) and sec["contributions"][0] <= pos and pos >= 0
                if kind in UNCERTAIN_KINDS:
                    iss("low", "claim_marked_uncertain", where, "无引用的论断已显式标注为作者判断/待确认（可接受）")
                elif kind in CONTRIBUTION_KINDS or in_contrib:
                    if c.get("result_anchor") or c.get("anchors"):
                        iss("low", "contribution_claim_without_citation", where,
                            "贡献陈述没有引用（可接受），已给出结果锚点")
                    else:
                        iss("medium", "contribution_claim_without_citation", where,
                            "贡献陈述没有引用（允许，但必须能在正文/图表/结果里找到对应锚点，并在 contributions.jsonl 里给出）")
                elif kind in OWN_RESULT_KINDS:
                    if c.get("result_anchor") or c.get("anchors"):
                        iss("low", "own_result_without_citation", where,
                            "本文结果句没有引用（正常），已给出结果锚点")
                    else:
                        iss("medium", "own_result_without_citation", where,
                            "本文结果句没有引用（正常，但必须能回溯到事实底稿里的同一数字/表述）")
                elif kind in GAP_KINDS or in_gap:
                    iss("high", "gap_claim_without_citation", where, "研究空白句必须由已引文献的缺口推出，却没有任何引用")
                else:
                    iss("high", "claim_without_citation", where, "论断既没有引用，也没有标注为作者判断")
            for k in cits:
                if not key_known(k):
                    iss("high", "claim_citation_unknown", where, "引用了文献表外的 key：%s" % k)
            src = c.get("source") or c.get("evidence") or {}
            if isinstance(src, str):
                src = {"quote": src}
            quote = ik.norm(src.get("quote") or src.get("span") or src.get("text") or "")
            para = src.get("para_id") or src.get("source_id") or src.get("paragraph_id") or ""
            if quote:
                claims_with_source += 1
                if ik.norm_hard(quote) in material_hard:
                    claims_verified_quote += 1
                elif ik.norm_hard(quote) in intro_hard:
                    iss("high", "claim_source_from_draft", where, "来源引文来自正文而不是科研材料")
                else:
                    iss("high", "claim_source_not_in_material", where,
                        "来源引文在材料里找不到逐字对应：%s" % quote[:70])
            else:
                iss("medium", "claim_source_quote_missing", where, "没有给出逐字来源引文")
            # 数字绑定：论断里的数字必须能在来源引文/材料里找到
            nums = [m.group(0).strip() for m in ik.NUM_RE.finditer(text)]
            for n in nums:
                near = quote or ""
                if ik.flat(n) in ik.flat(near) or ik.flat(n) in material_flat:
                    continue
                iss("high", "claim_number_not_in_material", where, "数字 %s 在材料里找不到" % n)
            if nums and cits and quote:
                claims_number_bound += 1

    # ---------------------------------------------------------- 4. 贡献与锚点
    contrib_count = 0
    contrib_with_anchor = 0
    if not contribs or (isinstance(contribs, dict) and contribs.get("__load_error__")):
        iss("high", "contributions_missing", work, "缺少 contributions.jsonl（贡献与其正文/图表/结果锚点）")
        contribs = []
    else:
        contrib_count = len(contribs)
        for i, c in enumerate(contribs):
            if not isinstance(c, dict):
                iss("high", "contribution_row_invalid", "contributions#%d" % i, "记录不是对象")
                continue
            where = c.get("contrib_id") or c.get("id") or "contributions#%d" % i
            text = ik.norm(c.get("text") or c.get("contribution") or c.get("statement") or "")
            if not text:
                iss("high", "contribution_text_missing", where, "缺 text")
                continue
            anchors = c.get("anchors") or c.get("anchor") or c.get("evidence") or []
            if isinstance(anchors, (str, dict)):
                anchors = [anchors]
            # 也认扁平的 `section` / `result_anchor` / `figure` 写法（真实 Agent 常这么写）
            if not anchors:
                flat_ref = (c.get("result_anchor") or c.get("figure") or c.get("table")
                            or c.get("equation") or c.get("result") or c.get("section") or "")
                if ik.norm(str(flat_ref)):
                    anchors = [{"kind": CONTRIB_FLAT_KIND.get(
                        next((k for k in ("result_anchor", "figure", "table", "equation", "result", "section")
                              if c.get(k)), "section"), "section"),
                        "ref": str(flat_ref)}]
            if anchors:
                contrib_with_anchor += 1
            else:
                iss("high", "contribution_anchor_missing", where, "贡献没有给出正文/图表/结果锚点")
            for a in anchors:
                if isinstance(a, str):
                    a = {"kind": "section", "ref": a}
                kind = str(a.get("kind") or a.get("type") or "").strip().lower()
                ref = ik.norm(str(a.get("ref") or a.get("locator") or a.get("target") or ""))
                quote = ik.norm(a.get("quote") or a.get("text") or "")
                if kind and kind not in CONTRIB_ANCHOR_KINDS:
                    iss("low", "contribution_anchor_kind_unknown", where, "锚点类型 %r 未在已知集合里" % kind)
                if quote and ik.norm_hard(quote) not in material_hard and ik.norm_hard(quote) not in intro_hard:
                    iss("high", "contribution_anchor_quote_not_found", where, "锚点引文在材料与正文里都找不到")
                if not quote and not ref:
                    iss("medium", "contribution_anchor_empty", where, "锚点既没有位置也没有引文")
            for oc in ik.OVERCLAIM.findall(text):
                iss("medium", "contribution_overclaim", where, "出现易夸大的表述 %r —— 必须能在结果里对应，或改为作者判断" % oc)

    # ---------------------------------------------------------- 5. 相关工作分组
    group_count = 0
    grouped_keys = set()
    if not groups or (isinstance(groups, dict) and groups.get("__load_error__")):
        iss("high", "groups_missing", work, "缺少 groups.jsonl（分组与比较维度）")
        groups = []
    else:
        group_count = len(groups)
        for i, g in enumerate(groups):
            if not isinstance(g, dict):
                iss("high", "group_row_invalid", "groups#%d" % i, "记录不是对象")
                continue
            where = g.get("group_id") or g.get("id") or "groups#%d" % i
            members = g.get("members") or g.get("refs") or g.get("keys") or []
            if isinstance(members, str):
                members = [members]
            members = [str(m).strip() for m in members if str(m).strip()]
            if len(members) < 1:
                iss("high", "group_members_missing", where, "分组没有成员")
            for m in members:
                if m.lower() not in bib_keys and canon(m) not in bib_canon:
                    iss("high", "group_member_unknown", where, "分组成员 %s 不在文献表里" % m)
                grouped_keys.add(canon(m))
            if not ik.norm(g.get("dimension") or g.get("basis") or g.get("by") or ""):
                iss("medium", "group_dimension_missing", where, "分组没写比较维度（问题/方法/路线）")
            if not ik.norm(g.get("compare_on") or g.get("comparison") or g.get("criteria") or ""):
                iss("medium", "group_comparison_missing", where, "分组没写比较依据（同一维度上比较取舍）")
            summ = ik.norm(g.get("summary") or g.get("conclusion") or "")
            if len(summ) < 20:
                iss("low", "group_summary_short", where, "分组结论过短或缺失")
            for oc in ik.OVERCLAIM.findall(summ):
                iss("low", "group_summary_overclaim", where, "分组结论里出现易夸大的表述 %r" % oc)
        cited = set(canon(k) for k in used_set)
        missing = sorted(cited - grouped_keys)
        if missing:
            iss("medium", "cited_work_not_grouped", ",".join(missing[:8]),
                "有 %d 条被引文献没有进入任何分组（相关工作漏项）" % len(missing))

    # ---------------------------------------------------------- 6. 空白推导
    gap_ok = 0
    if gaps and not (isinstance(gaps, dict) and gaps.get("__load_error__")):
        for i, g in enumerate(gaps if isinstance(gaps, list) else []):
            if not isinstance(g, dict):
                continue
            where = g.get("gap_id") or g.get("id") or "gaps#%d" % i
            st = ik.norm(g.get("statement") or g.get("text") or "")
            from_refs = g.get("from_refs") or g.get("refs") or g.get("citations") or []
            if isinstance(from_refs, str):
                from_refs = [from_refs]
            if not st:
                iss("high", "gap_statement_missing", where, "空白条目没有陈述")
            if not from_refs:
                iss("high", "gap_without_refs", where, "空白没有由已引文献的缺口推出")
            for k in from_refs:
                if not key_known(k):
                    iss("high", "gap_ref_unknown", where, "空白引用了表外 key：%s" % k)
            if not ik.norm(g.get("how_filled") or g.get("filled_by") or g.get("correspondence") or ""):
                iss("medium", "gap_filling_missing", where, "没说明本文工作如何填补该空白")
            gap_ok += 1
    else:
        iss("medium", "gaps_file_missing", work, "没有 gaps.jsonl（建议显式记录空白推导过程）")

    # ---------------------------------------------------------- 7. 措辞与不变量
    boiler = [m.group(0) for m in ik.BOILERPLATE.finditer(intro)]
    if boiler:
        iss("medium", "boilerplate_background", ",".join(sorted(set(boiler))[:4]),
            "背景出现空转铺垫表述，应改成具体的未解决问题")
    numbers_in_intro = [m.group(0).strip() for m in ik.NUM_RE.finditer(intro)]
    new_numbers = []
    for n in numbers_in_intro:
        if ik.flat(n) in material_flat:
            continue
        # 允许把"编号"当引用编号
        if re.fullmatch(r"\d+", n):
            continue
        new_numbers.append(n)
    if new_numbers:
        iss("high", "number_not_in_material", ",".join(sorted(set(new_numbers))[:8]),
            "正文出现了材料里没有的数字/单位（禁止新增材料外事实）")
    crossrefs = [m.group(0).strip() for m in ik.CROSSREF_RE.finditer(intro)]
    crossrefs_bad = [c for c in crossrefs if ik.flat(c) not in material_flat]
    if crossrefs_bad:
        iss("medium", "crossref_not_in_material", ",".join(sorted(set(crossrefs_bad))[:6]),
            "正文指向的图表/公式编号在材料里找不到")

    # 术语一致性
    term_rows = terms if isinstance(terms, list) else []
    if term_rows:
        for t in term_rows:
            if not isinstance(t, dict):
                continue
            pref = ik.norm(t.get("preferred") or t.get("term") or "")
            variants = t.get("variants") or []
            if isinstance(variants, str):
                variants = [variants]
            for v in variants:
                v = ik.norm(str(v))
                if not v or v.lower() == pref.lower():
                    continue
                if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(v), intro) and \
                        not re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(pref), intro):
                    iss("medium", "term_not_unified", pref, "正文用了非首选写法 %r，而未用 %r" % (v, pref))

    # ---------------------------------------------------------- 8. 导出
    ik.dump_text(os.path.join(out, "introduction.md"), intro)
    if cmap_rows:
        ik.dump_json(os.path.join(out, "citation_map.json"), cmap_rows)
    else:
        ik.dump_json(os.path.join(out, "citation_map.json"), {})
    ik.dump_jsonl(os.path.join(out, "claims.jsonl"), claims if isinstance(claims, list) else [])
    ik.dump_jsonl(os.path.join(out, "contributions.jsonl"), contribs if isinstance(contribs, list) else [])
    ik.dump_jsonl(os.path.join(out, "groups.jsonl"), groups if isinstance(groups, list) else [])
    ik.dump_jsonl(os.path.join(out, "gaps.jsonl"), gaps if isinstance(gaps, list) else [])

    # diff.md：正文 vs 材料（仅统计，不重写）
    diff_lines = ["# 正文与事实底稿的对照（自动生成，供人工复核）", "",
                  "- 正文段落数：%d；材料段落数：%d" % (len([x for x in intro.split("\n\n") if x.strip()]),
                                                   len([x for x in material.split("\n\n") if x.strip()])),
                  "- 正文引用数：%d（去重 %d）；文献表条目：%d" % (len(cites), len(used_set), len(refs)),
                  "- 正文数字：%d 个，其中材料里找不到的：%s" % (len(numbers_in_intro), sorted(set(new_numbers)) or "无"),
                  ""]
    for name in SECTIONS:
        if name in sec:
            s, e, head = sec[name]
            diff_lines.append("## %s（%d 字符）" % (SECTION_ZH[name], e - s))
            diff_lines.append("")
            diff_lines.append("> 起始锚点：`%s`" % head[:60])
            diff_lines.append("")
    ik.dump_text(os.path.join(out, "diff.md"), "\n".join(diff_lines))

    metrics = {
        "chars_introduction": len(intro),
        "sections_found": sorted(sec.keys()),
        "sections_missing": [s for s in SECTIONS if s not in sec],
        "citations_in_introduction": len(cites),
        "citation_keys_used": len(used_set),
        "citations_unresolved": len(unresolved),
        "references_total": len(refs),
        "references_uncited": len(uncited),
        "citation_map_entries": len(cmap_rows),
        "claims": claim_count,
        "claims_with_citation": claims_with_citation,
        "claims_with_source": claims_with_source,
        "claims_source_verified_rate": round(claims_verified_quote / claim_count, 3) if claim_count else 0.0,
        "contributions": contrib_count,
        "contributions_with_anchor": contrib_with_anchor,
        "groups": group_count,
        "grouped_keys": len(grouped_keys),
        "cited_grouped_rate": round(len(grouped_keys & used_canon) / max(1, len(used_canon)), 3),
        "gaps": gap_ok,
        "numbers_in_introduction": len(numbers_in_intro),
        "numbers_not_in_material": len(set(new_numbers)),
        "boilerplate_hits": len(boiler),
        "issues_high": sum(1 for i in issues if i["level"] == "high"),
        "issues_medium": sum(1 for i in issues if i["level"] == "medium"),
        "issues_low": sum(1 for i in issues if i["level"] == "low"),
    }
    if metrics["chars_introduction"] == 0:
        status = "failed"
    elif metrics["issues_high"]:
        status = "partial"
    else:
        status = "ok"

    unresolved_notes = [
        "自动核验只覆盖可机械比对的部分：引用能否解析、引文是否逐字、数字是否在材料里、"
        "分组与贡献是否给出维度与锚点；**论断是否真的被引文支持、分组是否合理、空白是否成立** 仍需人工判断。",
        "文献表若不带编号，编号映射按条目出现顺序给出（numbering_basis），这是可复核的假设，不是原文事实。",
        "转述与原文的一致性只检查了逐字引文，语义级的一致性不在自动范围内。",
    ]
    if unresolved:
        unresolved_notes.append("以下引用无法解析到文献表，必须补齐或删除：" + ", ".join(unresolved[:12]))
    ik.dump_json(os.path.join(out, "check.json"),
                 {"status": status, "metrics": metrics, "issues": issues, "unresolved": unresolved_notes})

    lines = ["# 引言与相关工作 —— 自动核验报告", "",
             "**状态**：`%s`（high %d / medium %d / low %d）" % (status, metrics["issues_high"],
                                                              metrics["issues_medium"], metrics["issues_low"]), "",
             "## 主要指标", ""]
    for k, v in metrics.items():
        lines.append("- `%s`: %s" % (k, v))
    lines += ["", "## 待处理问题", ""]
    if not issues:
        lines.append("无。")
    for lv in ("high", "medium", "low"):
        sub = [i for i in issues if i["level"] == lv]
        if not sub:
            continue
        lines.append("### %s（%d）" % (lv, len(sub)))
        lines.append("")
        for i in sub:
            lines.append("- `%s` @ %s —— %s" % (i["kind"], i["where"], i["detail"]))
        lines.append("")
    lines += ["## 核验边界", ""]
    for n in unresolved_notes:
        lines.append("- %s" % n)
    ik.dump_text(os.path.join(out, "review.md"), "\n".join(lines))

    primary = {"status_detail": status,
               "introduction": "introduction.md",
               "sections": sorted(sec.keys()),
               "citation_keys_used": used_set,
               "uncited_references": uncited}
    evidence = [{"kind": "citation_census", "citations": len(cites), "unresolved": unresolved},
                {"kind": "claim_binding", "claims": claim_count,
                 "source_verified_rate": metrics["claims_source_verified_rate"]},
                {"kind": "grouping", "groups": group_count, "cited_grouped_rate": metrics["cited_grouped_rate"]}]
    artifacts = []
    for name in sorted(os.listdir(out)):
        p = os.path.join(out, name)
        if not os.path.isfile(p) or name == "result.json":
            continue
        artifacts.append({"path": name, "role": "output", "bytes": os.path.getsize(p),
                          "sha256": ik.sha256_file(p)})
    ik.emit_result(os.path.join(out, "result.json"), ctx.get("case_id"), status, primary,
                   evidence=evidence, uncertainty=unresolved_notes, artifacts=artifacts,
                   contract=ctx.get("contract"))
    ik.pjson({"status": status, "high": metrics["issues_high"], "medium": metrics["issues_medium"],
              "low": metrics["issues_low"], "claims": claim_count, "groups": group_count,
              "citations": len(cites), "unresolved_citations": len(unresolved)})
    return 0 if status in ("ok", "partial") else 2


if __name__ == "__main__":
    sys.exit(main())
