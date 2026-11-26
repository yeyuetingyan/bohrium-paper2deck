#!/usr/bin/env python3
"""kg_prep.py — 文献知识图谱第一步（确定性）：切段落、抽实体候选、别名候选、关系候选。

它只做机器能确证的事：把原文切成带 source_id + paragraph_id 的段落单元，按受控类型表
标出**原文里真实出现过的**实体候选（带字符偏移，便于逐字核验），给出跨篇别名/冲突候选，
以及同一段内带线索词的关系候选。

不确定的一律放进候选而不是结论：最终关系、合并与查询由 Agent 写 relations.jsonl /
merges.jsonl / queries.json，再由 kg_assemble.py 硬核验。

用法：
  python kg_prep.py --case /input/case.json --out /app/work
  python kg_prep.py --material m.json --primary p.json --secondary s.json --manifest c.json --out work
退出码：0 正常（含部分警告）/ 2 材料不可用（reason 写进 prep.json）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kgkit as kk  # noqa: E402

VERSION = "kg_prep/1.0"

# --------------------------------------------------------------------------- 受控词表（与 references/ 同步）

MATERIAL_KEYWORDS = [
    "perovskite", "methylammonium", "formamidinium", "cesium", "absorber", "halide",
    "epoxy seal", "desiccant", "mesoporous TiO2", "spiro-OMeTAD", "precursor solution",
]
METHOD_KEYWORDS = [
    "spin-coating", "two-step spin-coating", "annealing", "encapsulation", "vapor treatment",
    "MA vapor treatment", "deposition", "damp-heat testing", "stability test", "climate chamber",
    "glovebox", "characterization", "recrystallize",
]
CONDITION_KEYWORDS = [
    "relative humidity", "humidity", "humid air", "damp heat", "damp-heat", "temperature",
    "1 sun illumination", "nitrogen glovebox",
]
METHOD_ACRONYMS = ["SEM", "XRD", "AFM", "TEM", "PL", "XPS", "UV-vis", "NMR", "DFT", "MA vapor"]
METRIC_KEYWORDS = [
    "power conversion efficiency", "efficiency", "open-circuit voltage", "short-circuit current density",
    "grain size", "stability", "lifetime", "degradation",
]
METRIC_ACRONYMS = ["PCE", "T80", "Voc", "Jsc", "FF", "RH", "EQE"]
TASK_KEYWORDS = [
    "stability", "degradation", "commercialization", "damp heat", "damp-heat", "recrystallization",
    "water ingress", "decomposition", "reporting standard",
]
CONDITION_CONTEXT = ("at", "under", "for", "within", "after", "in", "holding", "条件下", "在")

FORMULA_RE = re.compile(r"\b(?:[A-Z][a-z]?[0-9]*(?:\.[0-9]+)?){2,}\b")
BRACKET_FORMULA_RE = re.compile(r"\b[A-Z][a-z]?[0-9.]*\([^()]{1,60}\)[0-9.]*[A-Za-z0-9]*")
VALUE_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:%|C\b|h\b|min\b|s\b|nm\b|mA cm-2|mA/cm2|V\b|degrees\b|RH\b)")
ACRONYM_DEF_RE = re.compile(r"\b([A-Z][A-Za-z0-9\- ]{3,60}?)\s*\(([A-Z][A-Za-z0-9]{1,9})\)")
# 全称裁剪用：这些词出现说明正则把句子里的动词/功能词也吞进来了
PHRASE_STOP = {"we", "our", "this", "the", "a", "an", "of", "and", "or", "with", "for", "in",
               "on", "at", "to", "by", "as", "that", "which", "is", "are", "was", "were", "be",
               "note", "notes", "noted", "reported", "reports", "reached", "reach", "showed",
               "shows", "found", "finds", "observed", "observes", "using", "used", "uses",
               "achieved", "achieves", "measured", "measures", "here", "we", "they", "it"}


def trim_full_form(phrase):
    """把「全称 (缩写)」里的全称裁成真正的术语：去掉句首动词与功能词。"""
    words = [w for w in kk.norm(phrase).split(" ") if w]
    while words:
        if words[0].lower().strip("-") in PHRASE_STOP:
            words.pop(0)
            continue
        stop_at = None
        for i, w in enumerate(words):
            if w.lower().strip("-") in PHRASE_STOP:
                stop_at = i
        if stop_at is not None:
            words = words[stop_at + 1:]
            continue
        break
    if not words or len(words) > 4:
        return ""
    return " ".join(words)
NAME_RE = re.compile(r"\b([A-Z][a-z]{2,15})\s+et al\.")

CUE_TO_RELATION = [
    (("compared with", "versus", "vs.", "higher than", "lower than", "对照", "相比"), "compares_with"),
    (("outperform", "superior to", "优于"), "outperforms"),
    (("degrad", "decrease", "reduce", "loss", "decline", "降低", "衰减", "下降"), "degrades"),
    (("improve", "enhance", "increase", "boost", "better", "提高", "提升", "增强"), "improves"),
    (("cause", "due to", "because", "result in", "导致", "因为"), "causes"),
    (("require", "necessitat", "depend on", "only if", "需要", "依赖"), "requires"),
    (("applied to", "deposited on", "coated onto", "fabricated on", "沉积于"), "applied_to"),
    (("measured", "characterized", "evaluated", "assessed", "测定", "表征", "评价"), "measures"),
    (("using", "used", "adopt", "employ", "via", "by means of", "采用", "使用"), "uses"),
    (("part of", "consist of", "composed of", "属于", "包含"), "part_of"),
    (("support", "consistent with", "confirm", "支持", "印证"), "supports"),
    (("in contrast", "contradict", "disagree", "conflict", "相反", "矛盾"), "conflicts_with"),
    (("extend", "build on", "based on", "follow-up", "扩展", "沿用", "基于"), "extends"),
]
# 提示：cue 只是候选提示，最终关系由 Agent 结合句子判断，绝不允许"共现即关系"。


# --------------------------------------------------------------------------- 段落与线索

def cues(text):
    low = " " + kk.norm(text).lower() + " "
    out = {"conditions": [], "values": [], "negation": bool(re.search(r"\b(?:not|no|never|cannot|without)\b", low)),
           "hedges": bool(re.search(r"\b(?:may|might|could|suggest|indicate|appear)\b", low)),
           "absolutes": bool(re.search(r"\b(?:always|never|all|every|must)\b", low)),
           "attribution": bool(re.search(r"\b(?:reported|according to|previous work|et al\.)\b", low)),
           "contrast": bool(re.search(r"\b(?:however|but|although|whereas|in contrast)\b", low))}
    for m in VALUE_UNIT_RE.finditer(text):
        val = kk.norm(m.group(0))
        pre = text[max(0, m.start() - 30):m.start()].lower()
        out["values"].append({"value": val, "offset": m.start()})
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", pre) for w in CONDITION_CONTEXT):
            out["conditions"].append(val)
    return out


def build_papers(ctx, warnings):
    material = kk.read_json(ctx.get("material"))
    primary = kk.read_json(ctx.get("primary"))
    secondary = kk.read_json(ctx.get("secondary"))
    manifest_doc = kk.read_json(ctx.get("manifest"))
    for doc, nm in ((material, "material"), (primary, "primary"), (secondary, "secondary"),
                    (manifest_doc, "manifest")):
        if isinstance(doc, dict) and doc.get("__load_error__"):
            warnings.append(f"{nm}.json 读取失败：{doc['__load_error__']}")
    manifest = kk.load_manifest(manifest_doc, warnings) if manifest_doc else {}

    docs = []
    if isinstance(material, dict) and not material.get("__load_error__"):
        docs.append(material)
    if not docs and isinstance(primary, dict) and not primary.get("__load_error__"):
        docs.append(primary)
        if isinstance(secondary, dict) and not secondary.get("__load_error__"):
            docs.append(secondary)
    papers, w = kk.load_papers(*docs)
    warnings.extend(w)
    if not papers:
        return [], warnings, manifest, bool(docs)

    # manifest 交叉核对：只按 source_id 对齐，**绝不把一篇的 DOI/作者套到另一篇**
    for p in papers:
        m = manifest.get(p["source_id"])
        if not m:
            if manifest:
                warnings.append(f"{p['source_id']} 不在 corpus-manifest 里：DOI/许可证无法交叉核对")
            continue
        p["manifest"] = m
        for key, label in (("doi", "DOI"), ("title", "标题"), ("license", "许可证")):
            mv, pv = m.get(key) or "", p.get(key) or ""
            if mv and not pv:
                p[key] = mv
                warnings.append(f"{p['source_id']} 的 {label} 取自 corpus-manifest（材料本体没写）")
            elif mv and pv and kk.norm_hard(mv) != kk.norm_hard(pv):
                warnings.append(f"{p['source_id']} 的 {label} 在材料与 manifest 里不一致："
                                f"材料={pv!r} manifest={mv!r}")
        if m.get("authors") and p.get("authors"):
            if kk.norm_hard(" ".join(m["authors"])) != kk.norm_hard(" ".join(p["authors"])):
                warnings.append(f"{p['source_id']} 的作者在材料与 manifest 里不一致：以材料的署名为准")
    # 根级字段串号风险提示
    if len(papers) >= 2 and papers[0].get("title") and papers[0]["title"] == papers[1].get("title"):
        warnings.append("两篇材料的标题相同：可能根级 title 被误当成第二篇的标题，请核对")
    return papers, warnings, manifest, True


def build_passages(papers, max_paragraphs):
    passages, n = [], 0
    for p in papers:
        plist = []
        for para in p["paragraphs"]:
            if n >= max_paragraphs:
                break
            text = para["text"]
            sents = kk.sentences(text)
            plist.append({
                "source_id": p["source_id"], "paragraph_id": para["paragraph_id"],
                "section": para.get("section") or "", "chars": len(text), "text": text,
                "sentences": sents, "cues": cues(text),
            })
            n += 1
        passages.append({"source_id": p["source_id"], "title": p.get("title") or "",
                         "doi": p.get("doi") or "", "authors": p.get("authors") or [],
                         "license": p.get("license") or "", "paragraphs": plist})
    return passages


# --------------------------------------------------------------------------- 实体候选

def add_occ(store, key, etype, surface, pid, text, start, end, why):
    ent = store.setdefault(key, {"key": key, "type": etype, "label": surface, "occurrences": [],
                                 "why": []})
    quote = text[start:end]
    if not any(o["paragraph_id"] == pid and o["char_start"] == start for o in ent["occurrences"]):
        ent["occurrences"].append({"source_id": pid.split("::")[0], "paragraph_id": pid.split("::")[1],
                                   "char_start": start, "char_end": end, "quote": quote})
    if why not in ent["why"]:
        ent["why"].append(why)


def find_all(text, pattern, flags=0):
    for m in re.finditer(pattern, text, flags):
        yield m.start(), m.end(), m.group(0)


def extract_entities(passages, warnings):
    store = {}
    for p in passages:
        sid = p["source_id"]
        for author in p.get("authors") or []:
            add_occ(store, f"researcher::{kk.norm_hard(author)}", "researcher", author,
                    f"{sid}::authors", author, 0, len(author), "manifest_authors")
        for para in p["paragraphs"]:
            text, pid = para["text"], f"{sid}::{para['paragraph_id']}"
            # 材料：化学式 / 括号式 / 关键词
            for start, end, s in list(find_all(text, BRACKET_FORMULA_RE)) + list(find_all(text, FORMULA_RE)):
                if len(s) < 4 or not re.search(r"\d", s):
                    continue
                if s.lower() in ("situ", "exvivo"):
                    continue
                add_occ(store, f"material::{kk.norm_hard(s)}", "material", s, pid, text, start, end,
                        "chemical_formula")
            low = text.lower()
            for kw in MATERIAL_KEYWORDS:
                for start, end, s in find_all(text, re.escape(kw), re.IGNORECASE):
                    add_occ(store, f"material::{kk.norm_hard(s)}", "material", s, pid, text, start, end,
                            "material_keyword")
            for kw in METHOD_KEYWORDS:
                for start, end, s in find_all(text, re.escape(kw), re.IGNORECASE):
                    add_occ(store, f"method::{kk.norm_hard(s)}", "method", s, pid, text, start, end,
                            "method_keyword")
            for kw in METHOD_ACRONYMS:
                for start, end, s in find_all(text, r"\b" + re.escape(kw) + r"\b"):
                    add_occ(store, f"method::{kk.norm_hard(s)}", "method", s, pid, text, start, end,
                            "method_acronym")
            for kw in METRIC_KEYWORDS:
                for start, end, s in find_all(text, re.escape(kw), re.IGNORECASE):
                    add_occ(store, f"metric::{kk.norm_hard(s)}", "metric", s, pid, text, start, end,
                            "metric_keyword")
            for kw in METRIC_ACRONYMS:
                for start, end, s in find_all(text, r"\b" + re.escape(kw) + r"\b"):
                    add_occ(store, f"metric::{kk.norm_hard(s)}", "metric", s, pid, text, start, end,
                            "metric_acronym")
            for kw in TASK_KEYWORDS:
                for start, end, s in find_all(text, re.escape(kw), re.IGNORECASE):
                    add_occ(store, f"task::{kk.norm_hard(s)}", "task", s, pid, text, start, end,
                            "task_keyword")
            for kw in CONDITION_KEYWORDS:
                for start, end, s in find_all(text, re.escape(kw), re.IGNORECASE):
                    add_occ(store, f"condition::{kk.norm_hard(s)}", "condition", s, pid, text, start, end,
                            "condition_keyword")
            # 条件：带单位的数值 + 上下文词
            for v in para["cues"]["values"]:
                if v["value"] in para["cues"]["conditions"]:
                    st = v["offset"]
                    add_occ(store, f"condition::{kk.norm_hard(v['value'])}", "condition", v["value"],
                            pid, text, st, st + len(v["value"]), "value_with_unit")
            # 缩写定义（用于别名候选）
            for m in ACRONYM_DEF_RE.finditer(text):
                full, ac = kk.norm(m.group(1)), m.group(2)
                if len(full.split()) < 2:
                    continue
                add_occ(store, f"material::{kk.norm_hard(full)}", "material", full, pid, text,
                        m.start(1), m.end(1), "acronym_definition:full")
                add_occ(store, f"acronym::{ac}", "acronym", ac, pid, text, m.start(2), m.end(2),
                        "acronym_definition:short")
            for m in NAME_RE.finditer(text):
                add_occ(store, f"researcher::{kk.norm_hard(m.group(1))}", "researcher", m.group(1),
                        pid, text, m.start(1), m.end(1), "named_in_text")
    ents = list(store.values())
    for e in ents:
        e["source_ids"] = sorted({o["source_id"] for o in e["occurrences"]})
        e["occurrence_count"] = len(e["occurrences"])
        e["cross_paper"] = len(e["source_ids"]) > 1
    ents.sort(key=lambda e: (-e["occurrence_count"], e["type"], e["key"]))
    return ents


# --------------------------------------------------------------------------- 别名 / 冲突候选

def merge_candidates(ents, passages):
    cands, conflicts = [], []
    by_hard = {}
    for e in ents:
        if e["type"] == "acronym":
            continue
        by_hard.setdefault(kk.norm_hard(e["label"]), []).append(e)
    for hard, group in by_hard.items():
        if len(group) > 1:
            labels = sorted({g["label"] for g in group})
            if len(labels) > 1:
                cands.append({
                    "kind": "surface_variant", "reason": "归一化后同一字符串（大小写/连字符/空格差异）",
                    "labels": labels, "keys": [g["key"] for g in group],
                    "source_ids": sorted({s for g in group for s in g["source_ids"]}),
                    "suggested_canonical": group[0]["label"], "decision": "suggested",
                    "evidence": [o for g in group for o in g["occurrences"][:1]][:3]})
    # 缩写：只给"全称 + 缩写"对，是否合并由 Agent 定
    for e in ents:
        if e["type"] != "acronym":
            continue
        for para in [q for p in passages for q in p["paragraphs"]]:
            m = ACRONYM_DEF_RE.search(para["text"])
            if m and m.group(2) == e["label"]:
                full = trim_full_form(m.group(1))
                if not full or kk.norm_hard(full) == kk.norm_hard(e["label"]):
                    continue
                # 裁出来的全称若以某个既有实体标签结尾（"average power conversion efficiency"
                # → "power conversion efficiency"），就归到那个标签，避免造出第三份写法
                hf = kk.norm_hard(full)
                for other in sorted(ents, key=lambda x: -len(x["label"])):
                    if other["type"] == "acronym" or other["key"] == e["key"]:
                        continue
                    ho = kk.norm_hard(other["label"])
                    if len(ho) >= 6 and hf.endswith(ho):
                        full = other["label"]
                        break
                if kk.norm_hard(full) == kk.norm_hard(e["label"]):
                    continue
                cands.append({
                    "kind": "acronym_in_text", "reason": "原文以「全称 (缩写)」形态定义",
                    "labels": [full, e["label"]], "source_ids": [para["source_id"]],
                    "suggested_canonical": full, "decision": "suggested",
                    "evidence": [{"source_id": para["source_id"],
                                  "paragraph_id": para["paragraph_id"],
                                  "quote": para["text"][m.start(1):m.end(2)]}]})
    # 指标同名 + 条件不同 → 不可合并
    for hard, group in by_hard.items():
        if len(group) != 1 or group[0]["type"] != "metric":
            continue
        e = group[0]
        if not e["cross_paper"]:
            continue
        cond_by_src = {}
        for p in passages:
            for para in p["paragraphs"]:
                if any(o["paragraph_id"] == para["paragraph_id"] and o["source_id"] == para["source_id"]
                       for o in e["occurrences"]):
                    if para["cues"]["conditions"]:
                        cond_by_src.setdefault(para["source_id"], set()).update(para["cues"]["conditions"])
        if len(cond_by_src) > 1:
            sets = {k: sorted(v) for k, v in cond_by_src.items()}
            first = next(iter(sets.values()))
            if any(set(v) != set(first) for v in sets.values()):
                conflicts.append({
                    "kind": "same_metric_different_conditions",
                    "labels": [e["label"]],
                    "reason": "两篇出现同名指标，但报告条件不同：数值与结论不得合并",
                    "conditions_by_source": sets,
                    "evidence": e["occurrences"][:3]})
    return cands, conflicts


def conflict_candidates(passages, ents):
    """跨篇显式冲突候选：一方说 degrades/accelerates，另一方说 retain/improved。

    只在两段**共享至少一个实体**时配对，否则跨篇"冲突"多半是各说各话。
    """
    neg = re.compile(r"(degrad|decompos|loss|reduce|decline|accelerat|衰减|降低)", re.I)
    pos = re.compile(r"(retain|improve|stable|stabiliz|increase|提升|保持)", re.I)
    keys_of = {}
    for e in ents:
        if e["type"] == "acronym":
            continue
        for o in e["occurrences"]:
            keys_of.setdefault((o["source_id"], o["paragraph_id"]), set()).add(e["key"])
    hits = {}
    for p in passages:
        for para in p["paragraphs"]:
            if neg.search(para["text"]):
                hits.setdefault("negative", []).append(para)
            if pos.search(para["text"]):
                hits.setdefault("positive", []).append(para)
    out = []
    for a in hits.get("negative", []):
        for b in hits.get("positive", []):
            if a["source_id"] == b["source_id"]:
                continue
            ka = keys_of.get((a["source_id"], a["paragraph_id"]), set())
            kb = keys_of.get((b["source_id"], b["paragraph_id"]), set())
            if not (ka & kb):
                continue
            out.append({
                "kind": "cross_paper_tension",
                "reason": "一篇描述性能下降，另一篇描述性能保持/提升：可能是真冲突，也可能条件不同，需人工判定",
                "shared_keys": sorted(ka & kb),
                "a": {"source_id": a["source_id"], "paragraph_id": a["paragraph_id"],
                      "quote": a["text"][:160]},
                "b": {"source_id": b["source_id"], "paragraph_id": b["paragraph_id"],
                      "quote": b["text"][:160]},
                "decision": "needs_review"})
    return out[:12]


# --------------------------------------------------------------------------- 关系候选

def relation_candidates(ents, passages):
    out = []
    for p in passages:
        for para in p["paragraphs"]:
            here = []
            for e in ents:
                if e["type"] == "acronym":
                    continue
                for o in e["occurrences"]:
                    if o["source_id"] == p["source_id"] and o["paragraph_id"] == para["paragraph_id"]:
                        here.append((o["char_start"], o["char_end"], e))
                        break
            here.sort(key=lambda x: (x[0], x[1], x[2]["key"]))
            if len(here) < 2:
                continue
            for para_sent in kk.sentences(para["text"]):
                low = para_sent.lower()
                for i, (s1, e1, ent1) in enumerate(here):
                    for s2, e2, ent2 in here[i + 1:]:
                        if ent1["key"] == ent2["key"]:
                            continue
                        for cues_, rel in CUE_TO_RELATION:
                            hit = next((c for c in cues_ if c in low), None)
                            if not hit:
                                continue
                            if kk.norm_hard(ent1["label"]) not in kk.norm_hard(para_sent) or \
                               kk.norm_hard(ent2["label"]) not in kk.norm_hard(para_sent):
                                continue
                            out.append({
                                "source_id": p["source_id"], "paragraph_id": para["paragraph_id"],
                                "sentence": para_sent, "cue": hit, "suggested_relation": rel,
                                "subject": {"key": ent1["key"], "label": ent1["label"], "type": ent1["type"]},
                                "object": {"key": ent2["key"], "label": ent2["label"], "type": ent2["type"]},
                                "conditions": para["cues"]["conditions"],
                                "note": "线索词命中只代表候选；请结合句子确认方向、条件与类型，"
                                        "共现本身不是证据"})
                            break
    dedup, seen = [], set()
    for c in out:
        k = (c["paragraph_id"], c["subject"]["key"], c["object"]["key"], c["suggested_relation"])
        if k in seen:
            continue
        seen.add(k)
        dedup.append(c)
    return dedup


# --------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="r15 文献知识图谱第一步：段落/实体/别名/关系候选")
    ap.add_argument("--case", default=None)
    ap.add_argument("--material", default=None)
    ap.add_argument("--primary", default=None)
    ap.add_argument("--secondary", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--max-paragraphs", type=int, default=400)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    warnings = []
    case, ctx = kk.load_case(a.case) if a.case else ({}, {"case_id": "case", "base": os.getcwd(),
                                                          "contract": {}, "notes": []})
    for key, val in (("material", a.material), ("primary", a.primary),
                     ("secondary", a.secondary), ("manifest", a.manifest)):
        if val:
            ctx[key] = os.path.abspath(val)
    warnings.extend(ctx.get("notes") or [])

    if not any(ctx.get(k) for k in ("material", "primary", "secondary")):
        kk.dump_json(os.path.join(a.out, "prep.json"), {
            "schema": VERSION, "status": "failed", "reason": "no_material",
            "hint": "输入里没找到 material.json / primary-material.json / secondary-material.json；"
                    "请用 --material/--primary/--secondary 显式指定，或把语料放在 case.json 同目录",
            "resolved": {k: ctx.get(k) for k in ("material", "primary", "secondary", "manifest")}})
        kk.pjson({"status": "failed", "reason": "no_material"})
        return 2

    papers, warnings, manifest, readable = build_papers(ctx, warnings)
    if not papers:
        # 文件能解析、只是没有任何可用段落 → no_paragraphs；连结构都读不出来 → unreadable_material
        reason = "no_paragraphs" if readable else "unreadable_material"
        kk.dump_json(os.path.join(a.out, "prep.json"), {
            "schema": VERSION, "status": "failed", "reason": reason,
            "hint": "材料文件能解析，但里面没有任何 ≥20 字符的正文段落（段落键支持 "
                    "paragraphs/passages/elements/blocks 等）" if readable else
                    "材料文件存在但没能解析出结构（schema 不在候选键覆盖范围内）",
            "warnings": warnings})
        kk.pjson({"status": "failed", "reason": reason})
        return 2

    passages = build_passages(papers, a.max_paragraphs)
    total_paras = sum(len(p["paragraphs"]) for p in passages)
    if total_paras == 0:
        kk.dump_json(os.path.join(a.out, "prep.json"), {
            "schema": VERSION, "status": "failed", "reason": "no_paragraphs", "warnings": warnings})
        kk.pjson({"status": "failed", "reason": "no_paragraphs"})
        return 2

    ents = extract_entities(passages, warnings)
    mc, must_not = merge_candidates(ents, passages)
    must_not.extend(conflict_candidates(passages, ents))
    for i, c in enumerate(mc, 1):
        c["candidate_id"] = f"mc-{i:03d}"
    for i, c in enumerate(must_not, 1):
        c["candidate_id"] = f"mn-{i:03d}"
    rels = relation_candidates(ents, passages)

    kk.dump_json(os.path.join(a.out, "passages.json"), {"schema": VERSION, "papers": passages})
    kk.dump_jsonl(os.path.join(a.out, "entities_draft.jsonl"), ents)
    kk.dump_jsonl(os.path.join(a.out, "merge_candidates.jsonl"), mc)
    kk.dump_jsonl(os.path.join(a.out, "must_not_merge.jsonl"), must_not)
    kk.dump_jsonl(os.path.join(a.out, "relations_candidates.jsonl"), rels)
    for name in ("relation_vocab.json", "entity_types.json"):
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", name)
        doc = kk.read_json(src)
        if doc:
            kk.dump_json(os.path.join(a.out, name), doc)

    counts = {}
    for e in ents:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    checks = {
        "papers": len(passages),
        "paragraphs": total_paras,
        "paragraphs_without_id": sum(1 for p in passages for q in p["paragraphs"]
                                     if not str(q["paragraph_id"]).strip()),
        "empty_sections": sum(1 for p in passages for q in p["paragraphs"] if not q["section"]),
        "entity_candidates": len(ents),
        "entity_by_type": counts,
        "cross_paper_entities": sum(1 for e in ents if e["cross_paper"]),
        "merge_candidates": len(mc),
        "must_not_merge": len(must_not),
        "relation_candidates": len(rels),
        "manifest_cross_checked": len(manifest),
    }
    kk.dump_json(os.path.join(a.out, "prep_check.json"), checks)
    prep = {
        "schema": VERSION, "status": "ok" if not must_not else "ok_with_conflicts",
        "case_id": ctx.get("case_id"), "counts": checks,
        "next_step": [
            "1) 打开 passages.md 逐段核对原文；2) 从 entities_draft.jsonl 里挑真实科研对象，"
            "必要时补 entities.jsonl；3) 写 relations.jsonl（每条带 source_id + paragraph_id + "
            "逐字 quote + conditions + direction）；4) 对 merge_candidates.jsonl 逐条决定合并或"
            "不合并，写 merges.jsonl（不合并的也要写明理由）；5) 写 queries.json（≥3 个真实查询，"
            "带期望能回答什么）；6) 跑 kg_assemble.py。",
        ],
        "warnings": warnings,
    }
    kk.dump_json(os.path.join(a.out, "prep.json"), prep)

    # 人读版
    lines = ["# 段落清单（证据位置口径：source_id + paragraph_id，非 PDF 页码）", ""]
    for p in passages:
        lines.append(f"## {p['source_id']} — {p['title']}")
        lines.append(f"- DOI: {p['doi'] or '未提供'} | 作者: {', '.join(p['authors']) or '未提供'}"
                     f" | 许可证: {p['license'] or '未提供'}")
        for q in p["paragraphs"]:
            marks = ", ".join(sorted({e["label"] for e in ents
                                      if any(o["paragraph_id"] == q["paragraph_id"]
                                             and o["source_id"] == q["source_id"]
                                             for o in e["occurrences"])}))
            lines.append("")
            lines.append(f"### {q['paragraph_id']}  [{q['section'] or '无章节'}]")
            lines.append(f">{q['text']}")
            if q["cues"]["conditions"]:
                lines.append(f"- 条件线索：{', '.join(q['cues']['conditions'])}")
            if marks:
                lines.append(f"- 候选实体：{marks}")
            lines.append("- 引用要求：直接引用本段原文作为证据，位置写 "
                         f"`{p['source_id']}` + `{q['paragraph_id']}`")
    with open(os.path.join(a.out, "passages.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    kk.pjson({"status": prep["status"], "papers": len(passages), "paragraphs": total_paras,
              "entities": len(ents), "entity_by_type": counts, "merge_candidates": len(mc),
              "must_not_merge": len(must_not), "relation_candidates": len(rels),
              "warnings": len(warnings)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
