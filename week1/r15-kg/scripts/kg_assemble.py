#!/usr/bin/env python3
"""kg_assemble.py — 文献知识图谱第三步（确定性核验 + 导出 + 执行查询）。

输入（Agent 写的三份 + 第一步的工作副本）：
  work/passages.json         第一步产出：段落与位置口径
  work/merge_candidates.jsonl / must_not_merge.jsonl  第一步产出：待裁决的别名与冲突
  relations.jsonl            必填：断言-证据-位置三者齐备的关系边
  entities.jsonl             可选：显式声明要进图的实体（缺失时自动收录被关系引用的候选）
  merges.jsonl               可选（但候选存在时不写会记 medium）：合并/不合并的逐条裁决
  queries.json               必填：≥3 个真实查询

核验口径只有一条总原则：**能机械证伪的一律硬校验，不能机械判定的绝不假装通过**——
语义是否"译对/抽对"不在这里下结论，而是写进 check.json 的 unresolved 与 review.md。
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kgkit as kk  # noqa: E402
import kg_query as kq  # noqa: E402

VERSION = "kg_assemble/1.0"
HIGH, MED, LOW = "high", "medium", "low"


def iss(store, level, kind, where, detail):
    store.append({"level": level, "kind": kind, "where": where, "detail": detail})


def hard(s):
    return kk.norm_hard(s)


# --------------------------------------------------------------------------- 载入

def load_context(work, out):
    passages_doc = kk.read_json(os.path.join(work, "passages.json")) or {}
    papers = passages_doc.get("papers") or []
    idx, cues_idx = {}, {}
    for p in papers:
        for q in p.get("paragraphs") or []:
            idx[(p.get("source_id"), q.get("paragraph_id"))] = q
            cues_idx[(p.get("source_id"), q.get("paragraph_id"))] = q.get("cues") or {}
    vocab = kk.read_json(os.path.join(work, "relation_vocab.json")) or {}
    etypes = kk.read_json(os.path.join(work, "entity_types.json")) or {}
    return {"papers": papers, "idx": idx, "cues": cues_idx, "vocab": vocab, "etypes": etypes,
            "prep": kk.read_json(os.path.join(work, "prep.json")) or {}}


def quote_ok(quote, text):
    """返回 (ok, level)：严格逐字 > 仅空白/连字符差异 > 找不到。"""
    if not quote:
        return False, "missing"
    if quote in text:
        return True, "verbatim"
    if kk.norm(quote) and kk.norm(quote) in kk.norm(text):
        return True, "whitespace_variant"
    return False, "not_found"


# --------------------------------------------------------------------------- 实体

def build_entities(ctx, ents_rows, rels, issues, work):
    types = set((ctx["etypes"].get("types") or {}).keys()) or {
        "researcher", "material", "method", "task", "metric", "condition", "dataset", "conclusion"}
    draft = kk.load_jsonl(os.path.join(work, "entities_draft.jsonl"))
    draft_by_label = {hard(d.get("label")): d for d in draft if isinstance(d, dict)}

    entities, notes = [], []
    if ents_rows:
        for i, r in enumerate(ents_rows, start=1):
            if not isinstance(r, dict):
                iss(issues, HIGH, "entity_row_invalid", f"entities#{i}", "不是对象")
                continue
            label, etype = kk.norm(r.get("label")), (r.get("type") or "").strip()
            where = f"entity {label or i}"
            if not label:
                iss(issues, HIGH, "entity_field_missing", where, "缺少 label")
                continue
            if etype not in types:
                iss(issues, HIGH, "entity_type_not_in_vocab", where,
                    f"type={etype!r} 不在受控类型表 {sorted(types)}")
            occ = [o for o in kk.as_list(r.get("occurrences")) if isinstance(o, dict)]
            if not occ and r.get("source_id") and r.get("paragraph_id"):
                occ = [{"source_id": r.get("source_id"), "paragraph_id": r.get("paragraph_id"),
                        "quote": r.get("quote")}]
            if not occ:
                iss(issues, HIGH, "entity_no_occurrence", where, "没有任何 occurrence，节点无法回查")
            bad = 0
            for o in occ:
                key = (o.get("source_id"), o.get("paragraph_id"))
                para = ctx["idx"].get(key)
                if not para:
                    iss(issues, HIGH, "occurrence_location_unknown", where,
                        f"段落 {key[0]}::{key[1]} 不在材料里")
                    bad += 1
                    continue
                ok, lv = quote_ok(o.get("quote"), para["text"])
                if not ok:
                    iss(issues, HIGH, "occurrence_quote_not_found", where,
                        f"{key[1]} 里找不到引文：{(o.get('quote') or '')[:60]!r}")
                    bad += 1
                elif lv == "whitespace_variant":
                    iss(issues, LOW, "occurrence_quote_whitespace_variant", where, f"{key[1]}")
                elif hard(o.get("quote")) and hard(label) not in hard(o["quote"]) and \
                        not any(hard(a) in hard(o["quote"]) for a in kk.as_list(r.get("aliases"))):
                    iss(issues, MED, "label_not_in_occurrence", where,
                        f"{key[1]} 的引文里没有出现该 label 或别名（可能是归一化表述，请核对）")
            entities.append({
                "id": r.get("entity_id") or r.get("id") or f"e{i:03d}",
                "label": label, "type": etype or "unknown",
                "aliases": [kk.norm(a) for a in kk.as_list(r.get("aliases")) if kk.norm(a)],
                "source_ids": sorted({o.get("source_id") for o in occ if o.get("source_id")}),
                "occurrences": occ, "occurrence_verified": len(occ) - bad,
                "cross_paper": len({o.get("source_id") for o in occ}) > 1,
                "note": kk.norm(r.get("note") or "")})
    # 没有被 entities.jsonl 声明、但被关系引用的候选 → 自动收录（并记一条 note）
    declared = {hard(e["label"]) for e in entities}
    used = set()
    for r in rels:
        for side in ("subject", "object"):
            v = r.get(side)
            if isinstance(v, dict):
                v = v.get("label") or v.get("id")
            if v:
                used.add(hard(v))
    for lbl in sorted(used - declared):
        d = draft_by_label.get(lbl)
        if not d:
            continue
        entities.append({
            "id": f"auto-{len(entities) + 1:03d}", "label": d.get("label"), "type": d.get("type"),
            "aliases": [], "source_ids": d.get("source_ids") or [],
            "occurrences": d.get("occurrences") or [],
            "occurrence_verified": len(d.get("occurrences") or []),
            "cross_paper": bool(d.get("cross_paper")), "note": "自动收录（被关系引用但未在 entities.jsonl 声明）"})
        notes.append(f"自动收录实体 {d.get('label')}（被关系引用）")
    seen = {}
    for e in entities:
        if hard(e["label"]) in seen:
            iss(issues, HIGH, "duplicate_entity_label", f"entity {e['label']}",
                f"与 {seen[hard(e['label'])]} 重复；同一对象请用 aliases 合并")
        else:
            seen[hard(e["label"])] = e["id"]
    return entities, notes


# --------------------------------------------------------------------------- 关系

def resolve_entity(entities, ref):
    if not ref:
        return None
    if isinstance(ref, dict):
        ref = ref.get("entity_id") or ref.get("id") or ref.get("label")
    h = hard(ref)
    for e in entities:
        if e["id"] == ref or hard(e["label"]) == h or any(hard(a) == h for a in e["aliases"]):
            return e
    return None


def build_relations(ctx, entities, rels, issues):
    vocab = (ctx["vocab"].get("relations") or {})
    out = []
    for i, r in enumerate(rels, start=1):
        if not isinstance(r, dict):
            iss(issues, HIGH, "relation_row_invalid", f"relations#{i}", "不是对象")
            continue
        rel = (r.get("relation") or r.get("type") or "").strip()
        sub_ref, obj_ref = r.get("subject"), r.get("object")
        sid = r.get("source_id") or (r.get("evidence") or {}).get("source_id")
        pid = r.get("paragraph_id") or (r.get("evidence") or {}).get("paragraph_id")
        quote = r.get("quote") or (r.get("evidence") or {}).get("quote") or ""
        where = f"relation#{i} {sub_ref} -{rel}-> {obj_ref}"
        if not rel or not sub_ref or not obj_ref:
            iss(issues, HIGH, "relation_field_missing", where, "缺少 relation/subject/object 之一")
            continue
        if vocab and rel not in vocab:
            iss(issues, HIGH, "relation_not_in_vocab", where,
                f"{rel!r} 不在受控关系表 {sorted(vocab)}；请改用表内关系或并入最近的语义")
        sub, obj = resolve_entity(entities, sub_ref), resolve_entity(entities, obj_ref)
        if not sub:
            iss(issues, HIGH, "subject_not_found", where, f"主语 {sub_ref!r} 不在实体表里")
        if not obj:
            iss(issues, HIGH, "object_not_found", where, f"宾语 {obj_ref!r} 不在实体表里")
        para = ctx["idx"].get((sid, pid))
        if not para:
            iss(issues, HIGH, "relation_location_unknown", where, f"段落 {sid}::{pid} 不在材料里")
        else:
            ok, lv = quote_ok(quote, para["text"])
            if not ok:
                iss(issues, HIGH, "relation_quote_not_found", where,
                    f"{pid} 里找不到引文：{quote[:60]!r}")
            elif lv == "whitespace_variant":
                iss(issues, LOW, "relation_quote_whitespace_variant", where, pid)
            elif len(kk.norm(quote)) < 12:
                iss(issues, LOW, "relation_quote_too_short", where, f"{len(kk.norm(quote))} 字符")
            elif len(kk.norm(quote)) > 400 or len(kk.sentences(quote)) > 3:
                iss(issues, MED, "relation_quote_not_minimal", where,
                    f"{len(kk.norm(quote))} 字符 / {len(kk.sentences(quote))} 句，请缩到最短支撑片段")
            conds = [kk.norm(c) for c in kk.as_list(r.get("conditions")) if kk.norm(c)]
            src_conds = (ctx["cues"].get((sid, pid)) or {}).get("conditions") or []
            if src_conds:
                in_quote = [c for c in src_conds if kk.norm(c) and kk.norm(c) in kk.norm(quote)]
                missing = [c for c in in_quote if not any(kk.norm(c) == kk.norm(x) for x in conds)]
                missing = [c for c in in_quote if not any(kk.norm(c) == kk.norm(x) for x in conds)]
                if missing and not conds:
                    iss(issues, MED, "condition_dropped", where,
                        f"引文里出现条件值 {missing}，但 conditions 是空的：条件不得整批丢掉，"
                        "要么补齐，要么把引文缩到不含条件的片段")
                elif missing:
                    iss(issues, LOW, "condition_subset_incomplete", where,
                        f"引文里还有条件值 {missing} 未列入 conditions：若它约束本条关系请补上")
                elif not in_quote and conds:
                    iss(issues, LOW, "conditions_from_paragraph", where,
                        f"conditions {conds} 不在引文里，只在本段别处出现：请确认口径一致")
            for c in conds:
                if kk.norm(c) not in kk.norm(para["text"]):
                    other = [k for k in ctx["idx"]
                             if k[0] != sid and kk.norm(c) in kk.norm(ctx["idx"][k]["text"])]
                    if other:
                        iss(issues, HIGH, "condition_from_other_source", where,
                            f"条件 {c!r} 不出现在 {pid}，却出现在 {other[0][0]}::{other[0][1]}："
                            "两篇的条件不得混用")
                    else:
                        iss(issues, HIGH, "condition_not_in_source", where,
                            f"条件 {c!r} 在 {pid} 原文里找不到")
            if sub and obj and para:
                hs, ho = hard(quote), None
                ps, po = hs.find(hard(sub["label"])), hs.find(hard(obj["label"]))
                if ps >= 0 and po >= 0 and po < ps:
                    iss(issues, LOW, "direction_suspect", where,
                        "引文里宾语出现在主语之前，请确认方向没反")
            if (ctx["cues"].get((sid, pid)) or {}).get("attribution") and not r.get("evidence_kind"):
                iss(issues, MED, "attribution_unmarked", where,
                    "该段含转述线索（reported/according to/et al.），请用 evidence_kind 标明"
                    "direct（本文直接实验）还是 reported（转述他人）")
            if sub and obj and quote:
                hq = hard(quote)
                forms = lambda e: [e["label"]] + list(e["aliases"])
                if not any(hard(f) in hq for f in forms(sub)):
                    iss(issues, MED, "quote_lacks_subject", where,
                        f"引文里没有出现主语 {sub['label']!r} 或其别名")
                if not any(hard(f) in hq for f in forms(obj)):
                    iss(issues, MED, "quote_lacks_object", where,
                        f"引文里没有出现宾语 {obj['label']!r} 或其别名")
        out.append({
            "id": r.get("relation_id") or r.get("id") or f"r{i:03d}",
            "relation": rel, "subject": (sub or {}).get("id") or str(sub_ref),
            "object": (obj or {}).get("id") or str(obj_ref),
            "subject_label": (sub or {}).get("label") or str(sub_ref),
            "object_label": (obj or {}).get("label") or str(obj_ref),
            "conditions": [kk.norm(c) for c in kk.as_list(r.get("conditions")) if kk.norm(c)],
            "value": r.get("value"), "evidence_kind": r.get("evidence_kind") or "direct",
            "confidence": r.get("confidence"),
            "evidence": [{"source_id": sid, "paragraph_id": pid, "quote": kk.norm(quote)}],
            "note": kk.norm(r.get("note") or "")})
    pairs = defaultdict(int)
    for e in out:
        pairs[(e["subject"], e["relation"], e["object"],
               (e["evidence"][0]["source_id"], e["evidence"][0]["paragraph_id"]))] += 1
    for k, n in pairs.items():
        if n > 1:
            iss(issues, MED, "relation_duplicate", f"{k[0]} -{k[1]}-> {k[2]}",
                f"同一段落里重复 {n} 次，请合并")
    return out


# --------------------------------------------------------------------------- 合并裁决

def check_merges(ctx, entities, merges, issues, work):
    cands = kk.load_jsonl(os.path.join(work, "merge_candidates.jsonl"))
    must_not = kk.load_jsonl(os.path.join(work, "must_not_merge.jsonl"))
    covered, stats = set(), {"merge": 0, "keep_separate": 0, "unaddressed": 0}
    for i, m in enumerate(merges, start=1):
        if not isinstance(m, dict):
            iss(issues, HIGH, "merge_row_invalid", f"merges#{i}", "不是对象")
            continue
        decision = (m.get("decision") or "").strip()
        members = [kk.norm(x) for x in kk.as_list(m.get("members")) if kk.norm(x)]
        where = f"merge#{i} {members}"
        if decision not in ("merge", "keep_separate"):
            iss(issues, HIGH, "merge_decision_invalid", where,
                f"decision={decision!r} 必须是 merge / keep_separate")
            continue
        cids = [kk.norm(x) for x in kk.as_list(m.get("candidate_ids")) if kk.norm(x)]
        if decision == "merge" and len(members) < 2:
            iss(issues, HIGH, "merge_members_too_few", where, "merge 至少要有两个 members")
        if not members and not cids:
            iss(issues, HIGH, "merge_members_missing", where,
                "keep_separate 也要给 members，或给 candidate_ids 指回 prep 生成的候选")
        stats[decision] = stats.get(decision, 0) + 1
        known = {hard(e["label"]) for e in entities} | {hard(a) for e in entities for a in e["aliases"]}
        for mem in members:
            if hard(mem) not in known:
                iss(issues, MED, "merge_member_not_in_graph", where, f"{mem!r} 不在实体表里")
        for cid in cids:
            hit = [c for c in cands + must_not if c.get("candidate_id") == cid]
            if not hit:
                iss(issues, MED, "merge_candidate_id_unknown", where, f"candidate_ids 里的 {cid!r} 不存在")
            for c in hit:
                covered.add(id(c))
        ev = [e for e in kk.as_list(m.get("evidence")) if isinstance(e, dict)]
        if not ev:
            iss(issues, HIGH, "merge_without_evidence", where,
                "合并/不合并都必须给出原文证据（source_id + paragraph_id + quote）")
        for e in ev:
            para = ctx["idx"].get((e.get("source_id"), e.get("paragraph_id")))
            if not para:
                iss(issues, HIGH, "merge_evidence_location_unknown", where,
                    f"段落 {e.get('source_id')}::{e.get('paragraph_id')} 不在材料里")
                continue
            ok, _ = quote_ok(e.get("quote"), para["text"])
            if not ok:
                iss(issues, HIGH, "merge_evidence_quote_not_found", where,
                    f"{e.get('paragraph_id')} 里找不到引文 {(e.get('quote') or '')[:60]!r}")
        if decision == "merge" and not kk.norm(m.get("reason") or ""):
            iss(issues, MED, "merge_without_reason", where, "合并必须写明依据（缩写定义/同物异写/…）")
        if decision == "keep_separate" and not kk.norm(m.get("reason") or ""):
            iss(issues, MED, "keep_separate_without_reason", where,
                "不合并也要写明理由（条件不同/同名不同物/证据不足）")
        srcs = {e.get("source_id") for e in ev}
        if decision == "merge" and len(srcs) > 1 and m.get("cross_paper") is not True:
            iss(issues, MED, "cross_paper_merge_unflagged", where,
                "跨篇合并必须显式写 cross_paper: true 并给出两篇各自的证据")
        # 同名指标在不同条件下不得合并
        if decision == "merge":
            ms = [e for e in entities if hard(e["label"]) in {hard(x) for x in members}
                  and e["type"] == "metric"]
            per_source = {}
            for e in ms:
                for o in e["occurrences"]:
                    cs = set((ctx["cues"].get((o.get("source_id"), o.get("paragraph_id"))) or {}) \
                        .get("conditions") or [])
                    per_source.setdefault(o.get("source_id"), set()).update(cs)
            groups = [sorted(v) for v in per_source.values() if v]
            cand_hit = [c for c in cands + must_not
                        if c.get("kind") == "same_metric_different_conditions"
                        and set(kk.norm_hard(x) for x in (c.get("labels") or []))
                        & {hard(x) for x in members}]
            if cand_hit or (len(groups) > 1 and any(g != groups[0] for g in groups[1:])):
                iss(issues, HIGH, "merge_across_conditions", where,
                    f"指标同名但报告条件不同（{groups or [cand_hit[0].get('candidate_id')]}）："
                    "条件不同的数值/结论不得合并")
        for c in cands + must_not:
            if set(kk.norm_hard(x) for x in (c.get("labels") or [])) & {hard(x) for x in members}:
                covered.add(id(c))
    total = len(cands) + len(must_not)
    unaddressed = [c for c in cands + must_not if id(c) not in covered]
    stats["unaddressed"] = len(unaddressed)
    for c in unaddressed[:20]:
        iss(issues, MED, "merge_candidate_unaddressed", "merges",
            f"待裁决候选未处理：{c.get('kind')} {c.get('labels')} —— 请在 merges.jsonl 里明确"
            "merge 或 keep_separate")
    conflict_records = []
    for c in must_not:
        ev = [e for e in (c.get("evidence") or []) if isinstance(e, dict) and e.get("paragraph_id")]
        for side in ("a", "b"):
            if isinstance(c.get(side), dict) and c[side].get("paragraph_id"):
                ev.append({"source_id": c[side].get("source_id"),
                           "paragraph_id": c[side].get("paragraph_id"),
                           "quote": kk.norm(c[side].get("quote") or "")})
        conflict_records.append({"labels": c.get("labels"), "kind": c.get("kind"),
                                 "reason": c.get("reason"), "action": "keep_separate",
                                 "origin": "prep_candidate", "candidate_id": c.get("candidate_id"),
                                 "evidence": [{"source_id": e.get("source_id"),
                                               "paragraph_id": e.get("paragraph_id"),
                                               "quote": e.get("quote")} for e in ev[:3]]})
    for m in merges:
        if isinstance(m, dict) and m.get("decision") == "keep_separate":
            mev = [e for e in (m.get("evidence") or [])
                   if isinstance(e, dict) and e.get("paragraph_id")][:3]
            conflict_records.append({"labels": [kk.norm(x) for x in kk.as_list(m.get("members"))],
                                     "kind": "agent_declared", "reason": kk.norm(m.get("reason") or ""),
                                     "action": "keep_separate", "origin": "merges.jsonl",
                                     "candidate_ids": kk.as_list(m.get("candidate_ids")),
                                     "cross_paper": bool(m.get("cross_paper")),
                                     "evidence": [{"source_id": e.get("source_id"),
                                                   "paragraph_id": e.get("paragraph_id"),
                                                   "quote": e.get("quote")} for e in mev]})
    return {"candidates": total, "addressed": total - len(unaddressed),
            "unaddressed": len(unaddressed), "stats": stats,
            "conflicts_preserved": conflict_records}


# --------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="r15 图谱核验与导出")
    ap.add_argument("--case", default=None)
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--entities", default=None)
    ap.add_argument("--relations", default=None)
    ap.add_argument("--merges", default=None)
    ap.add_argument("--queries", default=None)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--min-queries", type=int, default=3)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    issues, uncertainty = [], []
    ctx = load_context(a.work, a.out)
    if not ctx["idx"]:
        kk.dump_json(os.path.join(a.out, "check.json"), {
            "schema": VERSION, "status": "failed", "reason": "no_passages",
            "hint": f"{a.work}/passages.json 不存在或没有段落：请先跑 kg_prep.py"})
        kk.pjson({"status": "failed", "reason": "no_passages"})
        return 2

    rel_path = a.relations or os.path.join(a.work, "relations.jsonl")
    ent_path = a.entities or os.path.join(a.work, "entities.jsonl")
    mrg_path = a.merges or os.path.join(a.work, "merges.jsonl")
    qry_path = a.queries or os.path.join(a.work, "queries.json")
    rels_raw = kk.load_jsonl(rel_path)
    ents_raw = kk.load_jsonl(ent_path)
    merges_raw = kk.load_jsonl(mrg_path)
    queries = kk.read_json(qry_path) or {}
    if not rels_raw:
        kk.dump_json(os.path.join(a.out, "check.json"), {
            "schema": VERSION, "status": "failed", "reason": "no_relations",
            "hint": f"没读到关系边（{rel_path}）：图谱至少要有一批带证据的关系"})
        kk.pjson({"status": "failed", "reason": "no_relations"})
        return 2

    entities, auto_notes = build_entities(ctx, ents_raw, rels_raw, issues, a.work)
    relations = build_relations(ctx, entities, rels_raw, issues)
    merge_info = check_merges(ctx, entities, merges_raw, issues, a.work)

    qlist = queries.get("queries") if isinstance(queries, dict) else queries
    if len(qlist or []) < a.min_queries:
        iss(issues, HIGH, "query_count_below_min", "queries",
            f"只有 {len(qlist or [])} 个查询，题面要求至少 {a.min_queries} 个真实查询")

    # 图谱
    deg = defaultdict(int)
    for e in relations:
        deg[e["subject"]] += 1
        deg[e["object"]] += 1
    nodes = [{"id": e["id"], "label": e["label"], "type": e["type"], "aliases": e["aliases"],
              "source_ids": e["source_ids"], "occurrences": e["occurrences"],
              "degree": deg.get(e["id"], 0), "note": e["note"]} for e in entities]
    graph = {"schema": "kgkit-graph/1.0", "corpus": [p.get("source_id") for p in ctx["papers"]],
             "nodes": nodes, "edges": relations,
             "must_not_merge": merge_info["conflicts_preserved"],
             "caveats": ["位置口径为组织方段落 ID，不含 PDF 页码",
                         "conditions 不参与合并：条件不同的数值与结论各自保留",
                         "evidence_kind=reported 的边只表示原文转述，不代表本文实验结论"]}

    qresults, qproblems = kq.run_queries(graph, queries)
    for p in qproblems:
        iss(issues, MED, "query_problem", "queries", p)
    # stats 类查询是对图谱本身的计数，不携带证据片段，属正常
    no_evidence_needed = ("stats",)
    for r in qresults:
        if r["row_count"] == 0:
            iss(issues, MED, "query_no_result", f"query {r['id']}", f"{r['question']} → 无结果")
        elif not r["has_evidence"] and r["type"] not in no_evidence_needed:
            iss(issues, HIGH, "query_result_without_evidence", f"query {r['id']}",
                "结果行必须带回证据（位置 + 引文）")

    # 指标
    n_rel = len(relations) or 1
    rel_vocab = ctx["vocab"].get("relations") or {}
    by_type, by_rel = defaultdict(int), defaultdict(int)
    for e in entities:
        by_type[e["type"]] += 1
    for e in relations:
        by_rel[e["relation"]] += 1
    metrics = {
        "entity_count": len(entities), "relation_count": len(relations),
        "entity_by_type": dict(sorted(by_type.items())),
        "relation_by_type": dict(sorted(by_rel.items())),
        "relation_vocab_rate": round(sum(1 for e in relations
                                         if not rel_vocab or e["relation"] in rel_vocab) / n_rel, 4),
        "evidence_verified_rate": round(sum(1 for e in relations if e["evidence"][0]["quote"]) / n_rel, 4),
        "cross_paper_edges": sum(1 for e in relations if e["subject"] in
                                 {n["id"] for n in nodes if len(n["source_ids"]) > 1}),
        "nodes_cross_paper": sum(1 for n in nodes if len(n["source_ids"]) > 1),
        "conditions_kept_rate": round(sum(1 for e in relations if e["conditions"]) / n_rel, 4),
        "merge_candidates": merge_info["candidates"], "merge_addressed": merge_info["addressed"],
        "conflicts_preserved": len(merge_info["conflicts_preserved"]),
        "query_count": len(qresults), "queries_with_results": sum(1 for r in qresults if r["row_count"]),
        "queries_with_evidence": sum(1 for r in qresults if r["has_evidence"]),
        "issues_high": sum(1 for i in issues if i["level"] == HIGH),
        "issues_medium": sum(1 for i in issues if i["level"] == MED),
        "issues_low": sum(1 for i in issues if i["level"] == LOW),
    }
    status = "failed" if (not entities or not relations) else (
        "partial" if metrics["issues_high"] else "ok")
    unresolved = [
        "语义级判断不在自动核验范围内：断言是否真的被原文支持、方法是否被正确归类，需要人工复核。",
        "同名不同物（例如两篇都用 MA 但指代不同）只能靠 evidence 与 conditions 暴露，不能由脚本断言。",
        "图谱只覆盖输入材料中出现的对象；未出现的对象不应被补全，也不在本次结果里。",
    ]
    if metrics["issues_high"]:
        unresolved.append(f"有 {metrics['issues_high']} 条 high 级问题未解决，结果状态降为 partial，"
                          "详见 check.json 的 issues 与 review.md。")
    uncertainty.extend(auto_notes)

    kk.dump_json(os.path.join(a.out, "graph.json"), graph)
    kk.dump_json(os.path.join(a.out, "entities.json"),
                 {"schema": "kgkit-entities/1.0", "count": len(nodes), "nodes": nodes})
    kk.dump_json(os.path.join(a.out, "relations.json"),
                 {"schema": "kgkit-relations/1.0", "count": len(relations),
                  "vocab": sorted(rel_vocab), "edges": relations})
    kk.dump_json(os.path.join(a.out, "query_results.json"),
                 {"schema": kq.VERSION, "query_count": len(qresults), "results": qresults,
                  "problems": qproblems})
    check = {"schema": VERSION, "status": status, "metrics": metrics, "issues": issues,
             "merge_decisions": merge_info, "unresolved": unresolved,
             "vocab_version": ctx["vocab"].get("schema"), "source_papers": [p.get("source_id") for p in ctx["papers"]]}
    kk.dump_json(os.path.join(a.out, "check.json"), check)

    md = ["# 文献知识图谱（两篇材料）", "",
          f"- 语料：{', '.join(p.get('source_id') or '' for p in ctx['papers'])}",
          f"- 节点 {len(nodes)} / 边 {len(relations)} / 查询 {len(qresults)}",
          f"- 位置口径：**组织方段落 ID**（无 PDF 页码）", ""]
    md.append("## 节点")
    for t in sorted({n["type"] for n in nodes}):
        md.append(f"### {t}")
        for n in sorted([x for x in nodes if x["type"] == t], key=lambda x: -x["degree"]):
            al = f"（别名：{', '.join(n['aliases'])}）" if n["aliases"] else ""
            md.append(f"- **{n['label']}**{al} — 度 {n['degree']} — 来源 {', '.join(n['source_ids'])}")
            if n["occurrences"]:
                o = n["occurrences"][0]
                md.append(f"  - 位置 {o.get('source_id')} / {o.get('paragraph_id')}："
                          f">{(o.get('quote') or '')[:120]}")
        md.append("")
    md.append("## 关系（含证据）")
    for e in relations:
        ev = e["evidence"][0]
        cond = f" [条件：{'; '.join(e['conditions'])}]" if e["conditions"] else ""
        val = f" = {e['value']}" if e.get("value") is not None else ""
        md.append(f"- {e['subject_label']} —{e['relation']}→ {e['object_label']}{val}{cond}")
        md.append(f"  - {ev['source_id']} / {ev['paragraph_id']}：>{ev['quote'][:160]}")
        if e.get("evidence_kind") == "reported":
            md.append("  - ⚠ evidence_kind=reported：这是转述他人结果，不是本文结论")
    md.append("")
    md.append("## 显式不合并 / 冲突（保留下来的分歧）")
    for c in merge_info["conflicts_preserved"]:
        md.append(f"- {c.get('labels')} — {c.get('kind')}：{c.get('reason')}")
    md.append("")
    md.append("## 查询结果")
    for r in qresults:
        md.append(f"### {r['id']}（{r['type']}）{r['question']}")
        md.append(f"- 命中 {r['row_count']} 行")
        for row in r["rows"][:6]:
            ev = (row.get("evidence") or [{}])[0]
            md.append(f"  - {row.get('subject') or row.get('entity')} "
                      f"{('—' + str(row.get('relation')) + '→') if row.get('relation') else ''} "
                      f"{row.get('object') or ''} "
                      f"[{ev.get('paragraph_id') or ''}] >{(ev.get('quote') or '')[:100]}")
    md.append("")
    md.append("## 未解决 / 边界")
    for u in unresolved:
        md.append(f"- {u}")
    with open(os.path.join(a.out, "graph.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")

    rev = ["# 复核清单（人读）", ""]
    for level in (HIGH, MED, LOW):
        grp = [i for i in issues if i["level"] == level]
        if not grp:
            continue
        rev.append(f"## {level}（{len(grp)}）")
        for i in grp:
            rev.append(f"- [{i['kind']}] {i['where']}：{i['detail']}")
        rev.append("")
    if not issues:
        rev.append("无问题：所有边都带可逐字核验的引文与位置。")
    with open(os.path.join(a.out, "review.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rev) + "\n")

    arts = ["graph.json", "graph.md", "entities.json", "relations.json", "query_results.json",
            "check.json", "review.md"]
    contract = {"graph": {"default": None}, "entities": {"default": None},
                "relations": {"default": None}, "queries": {"default": None},
                "check": {"default": None}}
    case_id = (kk.load_case(a.case)[1].get("case_id") if a.case else None) or "case"
    primary = {"status": status, "status_detail": f"{status}: {len(nodes)} nodes / "
                                                   f"{len(relations)} edges / "
                                                   f"{len(qresults)} queries",
               "node_count": len(nodes), "edge_count": len(relations),
               "query_count": len(qresults), "metrics": metrics,
               "graph": "graph.json", "entities": "entities.json", "relations": "relations.json",
               "queries": "query_results.json", "check": "check.json"}
    top_evidence = [{"source_id": e["evidence"][0]["source_id"],
                     "paragraph_id": e["evidence"][0]["paragraph_id"],
                     "quote": e["evidence"][0]["quote"],
                     "relation": e["relation"],
                     "subject": e["subject_label"], "object": e["object_label"]}
                    for e in relations[:20]]
    doc = kk.emit_result(os.path.join(a.out, "result.json"), case_id, status, primary,
                         evidence=top_evidence,
                         uncertainty=uncertainty + [u for u in unresolved],
                         artifacts=arts, contract=contract)
    kk.pjson({"status": status, "nodes": len(nodes), "edges": len(relations),
              "queries": len(qresults), "issues": {HIGH: metrics["issues_high"],
                                                   MED: metrics["issues_medium"],
                                                   LOW: metrics["issues_low"]},
              "result": os.path.basename(os.path.join(a.out, "result.json"))})
    return 0 if status in ("ok", "partial") else 2


if __name__ == "__main__":
    sys.exit(main())
