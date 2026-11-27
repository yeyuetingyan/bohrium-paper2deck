#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intro_prep —— 引言与相关工作写作 Skill 的第一步（确定性）。

把「事实底稿 + 文献材料」整理成 Agent 可以直接使用的候选池：
  * 可引材料句（facts）——带段号、逐字原文、可回溯位置
  * 文献记录（references）——每条的 key / 作者 / 年份 / 来源
  * 分组线索（ref_groups）——按共享术语/venue/年份给出的确定性聚类候选
  * 空白候选（gap_candidates）——从材料里带「局限/未解决」线索的句子里抽
  * 贡献候选（contribution_candidates）——从「we propose / 本文」类句子里抽
  * 既有初稿的引用覆盖与结构体检（如 case 提供 draft）

不调用任何模型；不做判断性结论；读不到的东西一律进 warnings。
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import introkit as ik  # noqa: E402

STOP = set("""a an the of and or for with without using used use to in on at by from as is are was were be been
being this that these those it its their our we us they them he she his her not no nor but however also such
can could may might will would should must do does did done has have had than then there here which who whom
whose what when where why how all any both each few more most other some such only own same so too very
study studies paper papers work works result results show shows shown reported report propose proposes
proposed present presents presented method methods approach approaches based new novel first second
of the and we our this that their they these those it is are was were be been being not no but also such
zhong guo ke xue yuan""".split())

METHOD_WORDS = re.compile(
    r"\b(method|methods|approach|model|models|framework|pipeline|algorithm|network|networks|simulation|"
    r"simulations|experiment|experiments|synthesis|characterization|measurement|measurements|analysis|"
    r"dft|density\s+functional|machine\s+learning|neural|regression|classification|optimization|"
    r"spectroscopy|xrd|xps|sem|tem|afm|nmr|ftir|uv-vis|pl|bet|electrochemical|"
    r"方法|模型|框架|算法|网络|模拟|实验|合成|表征|测量|分析|机器学习|神经网络|优化|光谱)\b", re.I)
METRIC_WORDS = re.compile(
    r"\b(efficiency|performance|accuracy|precision|recall|f1|rmse|mae|r2|error|errors|yield|selectivity|"
    r"stability|conductivity|capacity|sensitivity|resolution|throughput|latency|cost|"
    r"效率|性能|精度|准确率|误差|产率|选择性|稳定性|导电性|容量|灵敏度|分辨率|吞吐|延迟|成本)\b", re.I)
MATERIAL_WORDS = re.compile(
    r"\b(perovskite|mapbi3|cspbbr3|sio2|tio2|zno|graphene|cnt|carbon|polymer|hydrogel|nanoparticle|"
    r"nanoparticles|nanowire|catalyst|electrolyte|membrane|alloy|oxide|hydroxide|mof|zeolite|"
    r"钙钛矿|石墨烯|纳米|聚合物|催化剂|电解质|膜|合金|氧化物)\b", re.I)


def split_material(text: str, max_paragraphs=400):
    """把材料切成段落，给每段稳定 id；再切句。返回 (paragraphs, sentences)。"""
    paras = []
    blocks = re.split(r"\n\s*\n", text or "")
    idx = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        # 短行且像标题 -> 独立成段并标记 heading
        if len(lines) == 1 and len(lines[0]) <= 80 and not re.search(r"[.。;；]$", lines[0]) \
                and not re.match(r"^(fig|table|eq)\b", lines[0], re.I):
            kind = "heading"
            body = lines[0]
        else:
            kind = "body"
            body = " ".join(lines)
        idx += 1
        if idx > max_paragraphs:
            break
        pid = "m-p%03d" % idx
        paras.append({"para_id": pid, "index": idx, "kind": kind, "text": body,
                      "chars": len(body), "sha256_16": ik.sha256_16(body)})
    sents = []
    for p in paras:
        if p["kind"] == "heading":
            sents.append({"sent_id": p["para_id"] + "s1", "para_id": p["para_id"], "index": 1,
                          "text": p["text"], "kind": "heading", "offset": 0})
            continue
        for i, (s, off) in enumerate(ik.sentences(p["text"]), 1):
            sents.append({"sent_id": "%ss%d" % (p["para_id"], i), "para_id": p["para_id"],
                          "index": i, "text": s, "kind": "body", "offset": off})
    return paras, sents


def build_facts(sents, refs):
    """可引材料句：带引用线索/数字/结论性谓词，且不是纯标题。"""
    facts = []
    for s in sents:
        t = s["text"]
        if len(t) < 30:
            continue
        c = ik.cues(t)
        score = 0.0
        reasons = []
        if c["citations"]:
            score += 0.4
            reasons.append("has_citation")
        if c["numbers"]:
            score += 0.2
            reasons.append("has_number")
        if c["attribution"]:
            score += 0.3
            reasons.append("has_attribution")
        if c["limitation"]:
            score += 0.3
            reasons.append("has_limitation")
        if c["gap_cue"]:
            score += 0.4
            reasons.append("has_gap_cue")
        if c["contrib_cue"]:
            score += 0.4
            reasons.append("has_contrib_cue")
        if c["support"] or c["conflict"]:
            score += 0.2
            reasons.append("has_relation_cue")
        if METHOD_WORDS.search(t) or METRIC_WORDS.search(t) or MATERIAL_WORDS.search(t):
            score += 0.2
            reasons.append("has_domain_term")
        if not reasons:
            continue
        facts.append({
            "fact_id": "f" + s["sent_id"],
            "sent_id": s["sent_id"],
            "para_id": s["para_id"],
            "text": t,
            "anchor_text": t,
            "score": round(min(1.0, score), 2),
            "reasons": reasons,
            "cues": {k: c[k] for k in ("attribution", "limitation", "gap_cue", "contrib_cue",
                                       "support", "conflict", "hedge", "quantifier")},
            "protected": ik.protected_spans(t),
        })
    facts.sort(key=lambda x: (-x["score"], x["sent_id"]))
    return facts


def build_number_citations(paras):
    """给每个「数值 + 紧随的引用标记」建一条可绑定关系（确定性的，不含判断）。"""
    out = []
    for p in paras:
        text = p["text"]
        nums = list(ik.NUM_RE.finditer(text))
        for nm in nums:
            tail = text[nm.end():nm.end() + 40]
            cites = ik.parse_citations(tail)
            for c in cites:
                off = nm.end() + (c["spans"][0][0] if c.get("spans") else 0)
                if off - nm.end() > 12:
                    continue
                out.append({
                    "number": nm.group(0).strip(),
                    "para_id": p["para_id"],
                    "offset": nm.start(),
                    "citation": c["raw"],
                    "citation_keys": [ik.citation_key_of(c["kind"], k) for k in c.get("keys") or []],
                    "span": text[max(0, nm.start() - 60): min(len(text), nm.end() + 60)],
                    "note": "材料里的数字与紧随引用：正文使用该数字时必须保留同样写法并绑定同一引用。",
                })
    return out


def _content_terms(text):
    out = set()
    for tok in ik.tokens(text or ""):
        low = tok.lower()
        if low in STOP or len(low) < 4:
            continue
        out.add(low)
    return out


def build_groups(refs, hints=None):
    """确定性分组候选：按共享内容词 + venue 做连通分量。"""
    hints = hints or {}
    terms = {}
    for r in refs:
        blob = " ".join([r.get("title") or "", r.get("venue") or "", r.get("authors") or ""])
        terms[r["key"]] = _content_terms(blob)
    venue_key = {}
    for r in refs:
        v = (r.get("venue") or "").strip().lower()
        if v:
            venue_key.setdefault(v, []).append(r["key"])
    # 并查集
    parent = {r["key"]: r["key"] for r in refs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys = [r["key"] for r in refs]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared = terms[a] & terms[b]
            if len(shared) >= 3:
                union(a, b)
    for group in venue_key.values():
        for b in group[1:]:
            union(group[0], b)
    comp = {}
    for k in keys:
        comp.setdefault(find(k), []).append(k)
    groups = []
    ref_by_key = {r["key"]: r for r in refs}
    for i, (root, members) in enumerate(sorted(comp.items(), key=lambda kv: -len(kv[1])), 1):
        shared = None
        for m in members:
            shared = terms[m] if shared is None else (shared & terms[m])
        groups.append({
            "group_id": "g%02d" % i,
            "members": members,
            "size": len(members),
            "shared_terms": sorted(shared or [])[:12],
            "years": sorted({(ref_by_key[m].get("year") or "") for m in members if ref_by_key[m].get("year")}),
            "venues": sorted({(ref_by_key[m].get("venue") or "") for m in members if ref_by_key[m].get("venue")}),
            "note": "自动分组候选（按共享内容词/venue 连通）。分组维度与比较结论必须由 Agent 依据原文判断后写入 groups.jsonl。",
        })
    hint_map = {}
    for key, val in (hints or {}).items():
        hint_map[str(key)] = val
    return groups, hint_map


def build_gap_candidates(facts):
    out = []
    for f in facts:
        c = f["cues"]
        if c["gap_cue"] or c["limitation"] >= 1:
            kind = "explicit_gap" if c["gap_cue"] else "limitation"
            out.append({
                "candidate_id": "gap-" + f["sent_id"],
                "kind": kind,
                "text": f["text"],
                "para_id": f["para_id"],
                "gap_cue": c["gap_cue"],
                "limitation_hits": c["limitation"],
                "note": "空白候选：必须在正文里由已引文献的缺口推出，并写清本文工作如何填补。",
            })
    return out


def build_contribution_candidates(facts):
    out = []
    for f in facts:
        if f["cues"]["contrib_cue"]:
            out.append({
                "candidate_id": "contrib-" + f["sent_id"],
                "text": f["text"],
                "para_id": f["para_id"],
                "cues": f["cues"]["contrib_cue"],
                "note": "贡献候选：每条贡献都要能在正文/图表/结果里找到对应证据，不夸大适用范围。",
            })
    return out


def build_terms(paras, refs):
    counts = {}
    for p in paras:
        for m in METHOD_WORDS.finditer(p["text"]):
            key = m.group(0).lower()
            counts.setdefault(("method", key), 0)
            counts[("method", key)] += 1
        for m in METRIC_WORDS.finditer(p["text"]):
            key = m.group(0).lower()
            counts.setdefault(("metric", key), 0)
            counts[("metric", key)] += 1
        for m in MATERIAL_WORDS.finditer(p["text"]):
            key = m.group(0).lower()
            counts.setdefault(("material", key), 0)
            counts[("material", key)] += 1
    # 缩写：全称 (缩写)
    acronyms = {}
    for p in paras:
        for m in re.finditer(r"([A-Za-z][A-Za-z\-\s]{2,60}?)\s*\(([A-Z][A-Z0-9]{1,6})\)", p["text"]):
            full = re.sub(r"\s+", " ", m.group(1)).strip()
            full = re.sub(r"^(?:the|a|an|of|and|with|by|using|we|our)\s+", "", full, flags=re.I)
            words = [w for w in full.split() if w.lower() not in STOP]
            if not (1 <= len(words) <= 5):
                continue
            acronyms.setdefault(m.group(2), {"acronym": m.group(2), "full": " ".join(words), "para_ids": []})
            acronyms[m.group(2)]["para_ids"].append(p["para_id"])
    out = []
    for (kind, key), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        out.append({"kind": kind, "term": key, "freq": n,
                    "preferred": key, "locked": False,
                    "note": "术语一致：首次出现给全称，全篇用同一形态。"})
    for ac in acronyms.values():
        out.append({"kind": "acronym", "term": ac["acronym"], "full": ac["full"],
                    "freq": len(ac["para_ids"]), "para_ids": ac["para_ids"],
                    "preferred": ac["acronym"], "locked": False,
                    "note": "缩写首次使用前必须先给全称。"})
    ref_terms = {}
    for r in refs:
        for t in _content_terms((r.get("title") or "") + " " + (r.get("venue") or "")):
            ref_terms.setdefault(t, []).append(r["key"])
    return out, ref_terms


def census_references(paras, facts, refs):
    """材料里出现的引用标记 / DOI 与文献表的对账。

    文献表若本身带编号（num），直接用；若只有 BibTeX key（无编号），则按**出现顺序**
    提供一个位置映射，并在返回里标明 `numbering_basis="positional"`——
    这是可复核的假设，必须由 Agent 在正文与 citation_map 中保持一致。
    """
    all_cites = []
    dois = []
    for p in paras:
        for c in ik.parse_citations(p["text"]):
            c = dict(c)
            c["para_id"] = p["para_id"]
            all_cites.append(c)
        for m in ik.DOI_RE.finditer(p["text"]):
            dois.append({"doi": m.group(0), "para_id": p["para_id"]})
    by_key = {}
    explicit_num = any(r.get("num") is not None for r in refs)
    positional = {}
    for i, r in enumerate(refs, 1):
        k = (r.get("key") or "").lower()
        by_key[k] = r
        # citation_key_of() 对非编号引用会加 "k:" 前缀，这里必须同样登记，
        # 否则作者-年份引用（`Peters et al. (2018)`）会被全判成"未解析"。
        by_key.setdefault("k:" + k, r)
        # 姓在前/名在前的排版都可能只派生出"名"（如 akbik）。把候选姓也登记为别名，
        # 免得正文写 `Akbik et al. (2018)`、文献表派生出 `akbik2018` 却对不上。
        for alias in (ik.ref_key_from_raw(r.get("raw") or ""), ik._first_author_surname(r.get("raw") or "").lower()):
            if alias:
                by_key.setdefault(alias, r)
                by_key.setdefault("k:" + alias, r)
        ay = r.get("authors") or ""
        if ay:
            sur = ik._first_author_surname(ay).lower()
            if sur:
                sur = re.sub(r"[^a-z0-9]", "", sur)
                by_key.setdefault(sur, r)
                by_key.setdefault("k:" + sur, r)
        num = r.get("num")
        if num is not None:
            by_key["n:" + str(num).lower()] = r
        if not explicit_num:
            positional["n:" + str(i)] = r.get("key")
            by_key.setdefault("n:" + str(i), r)
    unresolved = []
    for c in all_cites:
        for k in c.get("keys") or []:
            ck = ik.citation_key_of(c.get("kind"), k)
            if ck not in by_key:
                unresolved.append({"citation": c.get("raw"), "key": ck, "para_id": c.get("para_id"),
                                   "kind": c.get("kind")})
    return {
        "citations_in_material": len(all_cites),
        "citations_used_keys": sorted({ik.citation_key_of(c.get("kind"), k)
                                       for c in all_cites for k in (c.get("keys") or [])}),
        "unresolved_in_material": unresolved,
        "numbering_basis": "explicit" if explicit_num else "positional",
        "positional_number_map": positional,
        "dois_in_material": dois,
        "dois_in_bibliography": [r.get("doi") for r in refs if r.get("doi")],
        "bib_keys": sorted(k for k in by_key.keys()),
    }


def draft_audit(ctx, refs):
    """若 case 提供既有初稿，做结构与引用覆盖体检。"""
    draft = None
    for key in ("draft", "draft_text", "introduction", "intro", "existing_intro", "current_intro"):
        v = ctx.get("_case_raw", {}).get(key) if isinstance(ctx.get("_case_raw"), dict) else None
        if isinstance(v, str) and v.strip():
            draft = ik.norm(v)
            break
    if draft is None:
        return None
    sections = detect_sections(draft)
    cites = ik.parse_citations(draft)
    cited_keys = set()
    for c in cites:
        for k in c.get("keys") or []:
            cited_keys.add(ik.citation_key_of(c.get("kind"), k))
    bib_keys = set()
    for r in refs:
        bib_keys.add((r.get("key") or "").lower())
        if r.get("num") is not None:
            bib_keys.add("n:" + str(r["num"]).lower())
    return {
        "sections": sections,
        "citation_count": len(cites),
        "cited_keys": sorted(cited_keys),
        "unresolved_citations": sorted(k for k in cited_keys if k not in bib_keys),
        "uncited_references": sorted(k for k in bib_keys if k not in cited_keys and not k.startswith("auto:")),
        "numbers": len(ik.NUM_RE.findall(draft)),
        "boilerplate": [m.group(0) for m in ik.BOILERPLATE.finditer(draft)],
    }


SECTION_PATTERNS = [
    ("background", re.compile(r"(^|\n)\s*(?:#{1,6}\s*)?(?:1[\.\s]*)?(?:introduction|background|research background|motivation|引言|研究背景|背景)\b", re.I)),
    ("related_work", re.compile(r"(^|\n)\s*(?:#{1,6}\s*)?(?:2[\.\s]*)?(?:related\s+works?|literature\s+review|prior\s+work|相关工作|文献综述)\b", re.I)),
    ("gap", re.compile(r"(^|\n)\s*(?:#{1,6}\s*)?(?:3[\.\s]*)?(?:research\s+gap|gap|knowledge\s+gap|open\s+questions?|研究空白|空白|未解决的问题)\b", re.I)),
    ("contributions", re.compile(r"(^|\n)\s*(?:#{1,6}\s*)?(?:4[\.\s]*)?(?:contributions?|our\s+contributions?|main\s+contributions?|贡献|本文贡献)\b", re.I)),
]


def detect_sections(text):
    """返回 {section: {found, start, heading}}"""
    out = {}
    for name, rx in SECTION_PATTERNS:
        m = rx.search(text or "")
        out[name] = {"found": bool(m), "start": m.start() if m else None,
                     "heading": (m.group(0).strip() if m else None)}
    return out


def main():
    ap = argparse.ArgumentParser(description="引言与相关工作写作 —— 确定性第一步")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--material", default=None, help="材料文本路径（默认从 case 推断）")
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--max-paragraphs", type=int, default=400)
    args = ap.parse_args()

    warnings = []
    if not os.path.exists(args.case):
        msg = {"status": "failed", "reason": "no_case", "case": args.case,
               "hint": "缺少 case.json；请确认平台把输入挂到 /input/case.json。"}
        os.makedirs(args.out, exist_ok=True)
        ik.dump_json(os.path.join(args.out, "prep.json"), msg)
        ik.pjson(msg)
        return 2

    case, ctx = ik.load_case(args.case)
    ctx["_case_raw"] = case
    warnings.extend(ctx.get("warnings") or [])

    if args.material:
        txt, err = ik._read_any_text(args.material)
        if txt is None:
            ctx["material_text"] = ""
            ctx["material_source"] = "unreadable"
            warnings.append("指定材料读取失败: %s" % err)
        else:
            ctx["material_text"] = ik.norm(txt)
            ctx["material_path"] = os.path.abspath(args.material)
            ctx["material_source"] = "file:" + os.path.splitext(args.material)[1].lstrip(".").lower()

    src = ctx.get("material_source") or "missing"
    if src == "missing":
        msg = {"status": "failed", "reason": "no_material",
               "hint": "没找到科研材料。请把材料文本放进 case 的 material/material_text，或与 case 同目录放 material.md。",
               "case_id": ctx.get("case_id"), "warnings": warnings}
        os.makedirs(args.out, exist_ok=True)
        ik.dump_json(os.path.join(args.out, "prep.json"), msg)
        ik.pjson(msg)
        return 2
    if src in ("unreadable",) or src.startswith("unreadable:") or (not ctx.get("material_text")):
        if src == "case_inline":
            reason = "empty_material"
        elif src == "unreadable" or src.startswith("unreadable:"):
            reason = "unreadable_material"
        elif src.endswith(":empty"):
            reason = "empty_material"
        else:
            reason = "unreadable_material"
        msg = {"status": "failed", "reason": reason,
               "hint": "材料文件存在但读不出文本（可能不是文本层 PDF / 编码异常 / 内容为空）。"
                       "%s" % ("原文：%s" % src if src else ""),
               "material_source": src, "case_id": ctx.get("case_id"), "warnings": warnings}
        os.makedirs(args.out, exist_ok=True)
        ik.dump_json(os.path.join(args.out, "prep.json"), msg)
        ik.pjson(msg)
        return 2

    material = ctx["material_text"]
    paras, sents = split_material(material, max_paragraphs=args.max_paragraphs)
    if not [p for p in paras if p.get("kind") == "body"]:
        msg = {"status": "failed", "reason": "no_paragraphs",
               "hint": "材料里没有正文段落（只有标题或空行）。",
               "material_source": src, "case_id": ctx.get("case_id"), "warnings": warnings}
        os.makedirs(args.out, exist_ok=True)
        ik.dump_json(os.path.join(args.out, "prep.json"), msg)
        ik.pjson(msg)
        return 2

    refs, bib_warn = ik.load_bibliography(*ctx.get("bib_docs") or [])
    warnings.extend(bib_warn)
    facts = build_facts(sents, refs)
    num_cites = build_number_citations(paras)
    groups, _hints = build_groups(refs)
    gaps = build_gap_candidates(facts)
    contribs = build_contribution_candidates(facts)
    terms, ref_terms = build_terms(paras, refs)
    ref_census = census_references(paras, facts, refs)
    draft = draft_audit(ctx, refs)

    os.makedirs(args.out, exist_ok=True)
    ik.dump_jsonl(os.path.join(args.out, "facts.jsonl"), facts)
    ik.dump_jsonl(os.path.join(args.out, "number_citations.jsonl"), num_cites)
    ik.dump_json(os.path.join(args.out, "references.json"),
                 {"count": len(refs), "records": refs, "census": ref_census})
    ik.dump_jsonl(os.path.join(args.out, "ref_groups.jsonl"), groups)
    ik.dump_jsonl(os.path.join(args.out, "gap_candidates.jsonl"), gaps)
    ik.dump_jsonl(os.path.join(args.out, "contribution_candidates.jsonl"), contribs)
    ik.dump_jsonl(os.path.join(args.out, "terms.jsonl"), terms)
    ik.dump_json(os.path.join(args.out, "context.json"), {
        "version": ik.VERSION,
        "case_id": ctx.get("case_id"),
        "audience": ctx.get("audience"),
        "genre": ctx.get("genre"),
        "language": ctx.get("lang"),
        "format_constraints": ctx.get("format_constraints"),
        "contract": ctx.get("contract"),
        "task_excerpt": (ctx.get("task") or "")[:1200],
        "material_source": src,
        "material_path": ctx.get("material_path"),
        "material_chars": len(material),
        "bibliography_source": ctx.get("bibliography_source"),
        "bibliography_path": ctx.get("bibliography_path"),
        "section_patterns": [{"name": n, "regex": rx.pattern} for n, rx in SECTION_PATTERNS],
    })
    if draft:
        ik.dump_json(os.path.join(args.out, "draft_audit.json"), draft)

    # 人/Agent 读的清单
    lines = ["# 事实底稿（可引材料句）", "",
             "> 每条都带段号与逐字原文，引用时必须能回到这里。", ""]
    for f in facts[:120]:
        lines.append("## %s  (score %s, %s)" % (f["fact_id"], f["score"], ",".join(f["reasons"])))
        lines.append("")
        lines.append(f["text"])
        lines.append("")
        prot = f["protected"]
        prot_txt = "; ".join("%s: %s" % (k, ", ".join(v)) for k, v in prot.items() if v)
        if prot_txt:
            lines.append("- 必须原样保留：%s" % prot_txt)
            lines.append("")
    lines.append("# 文献记录（%d 条）" % len(refs))
    lines.append("")
    for r in refs[:200]:
        lines.append("- `%s` | %s | %s | %s | doi=%s" % (
            r.get("key"), r.get("authors") or "?", r.get("year") or "?", (r.get("title") or r.get("venue") or "")[:80], r.get("doi") or "-"))
    if num_cites:
        lines.append("")
        lines.append("# 数字与紧随引用（正文用到这些数字时必须同样写法、同一引用）")
        lines.append("")
        for nc in num_cites[:80]:
            lines.append("- `%s` + `%s` @%s … %s" % (nc["number"], nc["citation"], nc["para_id"], nc["span"][:90]))
    if ref_census.get("positional_number_map"):
        lines.append("")
        lines.append("# 编号映射（文献表没有自带编号 → 按条目出现顺序给出的位置映射，可复核）")
        lines.append("")
        for num, key in sorted(ref_census["positional_number_map"].items(), key=lambda kv: int(kv[0][2:])):
            rec = next((r for r in refs if (r.get("key") or "") == key), {})
            lines.append("- `%s` -> `%s` (%s, %s)" % (num, key, rec.get("authors") or "?", rec.get("year") or "?"))
    if draft:
        lines.append("")
        lines.append("# 既有初稿体检")
        lines.append("")
        lines.append("- 结构命中：%s" % ", ".join("%s=%s" % (k, v["found"]) for k, v in draft["sections"].items()))
        lines.append("- 引用 %d 处；未在文献表中找到的引用：%s" % (draft["citation_count"], draft["unresolved_citations"] or "无"))
        lines.append("- 文献表里未被引用的：%s" % (draft["uncited_references"] or "无"))
    ik.dump_text(os.path.join(args.out, "facts.md"), "\n".join(lines))

    next_step = [
        "1. 读 facts.md / facts.jsonl：挑出真正能支撑论断的材料句，记下 fact_id 与段号。",
        "2. 读 references.json：确认每条文献的 key / 作者 / 年份 / 来源；不得使用表外文献。",
        "3. 读 ref_groups.jsonl：这只是聚类候选，必须自己判断分组维度（问题/方法/路线），并写 groups.jsonl。",
        "4. 写 introduction.md：四节齐全（研究背景 / 相关工作 / 研究空白 / 贡献），彼此承接。",
        "5. 写 claims.jsonl：每条论断一条记录，绑定引用 key 与来源（引文逐字 + 段号），空白句必须带引用。",
        "6. 写 contributions.jsonl：每条贡献给出正文/图表/结果锚点。",
        "7. 写 citation_map.json：引用 key -> 文献元数据（作者/年份/来源），与参考文献表一一对应。",
        "8. 最后跑 intro_assemble.py 做硬核验并生成 result.json。",
    ]
    prep = {
        "status": "ok",
        "version": ik.VERSION,
        "case_id": ctx.get("case_id"),
        "material_source": src,
        "paragraphs": len(paras),
        "sentences": len(sents),
        "facts": len(facts),
        "number_citations": len(num_cites),
        "references": len(refs),
        "ref_groups": len(groups),
        "gap_candidates": len(gaps),
        "contribution_candidates": len(contribs),
        "terms": len(terms),
        "citations_in_material": ref_census["citations_in_material"],
        "unresolved_citations_in_material": len(ref_census["unresolved_in_material"]),
        "numbering_basis": ref_census.get("numbering_basis"),
        "audience": ctx.get("audience"),
        "genre": ctx.get("genre"),
        "warnings": warnings,
        "next_step": next_step,
    }
    ik.dump_json(os.path.join(args.out, "prep.json"), prep)

    check = {
        "paragraphs": len(paras),
        "empty_paragraphs": 0,
        "duplicate_para_ids": [],
        "sentences": len(sents),
        "very_long_sentences": [s["sent_id"] for s in sents if len(s["text"]) > 400][:20],
        "facts_without_number_or_citation": [f["fact_id"] for f in facts
                                             if not f["protected"]["number"] and not f["protected"]["citation"]][:20],
        "facts_without_anchor_text": [f["fact_id"] for f in facts if not f.get("anchor_text")][:20],
        "references_without_year": [r["key"] for r in refs if not r.get("year")][:20],
        "references_without_authors": [r["key"] for r in refs if not r.get("authors")][:20],
        "references_without_doi": [r["key"] for r in refs if not r.get("doi")][:20],
        "bibliography_empty": len(refs) == 0,
        "numbering_basis": ref_census.get("numbering_basis"),
        "unresolved_citations_in_material": len(ref_census["unresolved_in_material"]),
    }
    ik.dump_json(os.path.join(args.out, "prep_check.json"), check)
    ik.pjson(prep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
