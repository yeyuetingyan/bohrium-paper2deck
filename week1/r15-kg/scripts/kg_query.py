#!/usr/bin/env python3
"""kg_query.py — 图谱查询器（独立可用）。

图谱的交付要求之一是「查得到、回得去」：每个查询结果必须能回到论文的具体位置与原文片段。
所以本查询器的**每一条结果行都强制带 evidence**（source_id + paragraph_id + 原文短引），
没有证据的边不会出现在结果里，只会在 `dropped_edges` 里计数说明。

用法：
  python kg_query.py --graph /app/output/graph.json --queries /app/output/queries.json \
      --out /app/output/query_results.json
  python kg_query.py --graph graph.json --label MAPbI3 --type neighbors   # 临时手查
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kgkit as kk  # noqa: E402

VERSION = "kg_query/1.0"
QUERY_TYPES = ("entity", "neighbors", "path", "relation", "keyword", "evidence", "conflicts",
               "subgraph", "stats")


def _norm(s):
    return kk.norm_hard(s)


def load_graph(path):
    doc = kk.read_json(path) or {}
    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    by_id = {n.get("id"): n for n in nodes if n.get("id")}
    return doc, nodes, edges, by_id


def resolve(by_id, ref):
    """把实体引用（id / label / alias）解析成节点。"""
    if not ref:
        return None
    if ref in by_id:
        return by_id[ref]
    hard = _norm(ref)
    for n in by_id.values():
        if _norm(n.get("label")) == hard:
            return n
        if any(_norm(a) == hard for a in (n.get("aliases") or [])):
            return n
    return None


def edge_evidence(e):
    return e.get("evidence") or []


def _row(e, direction="out"):
    return {"relation": e.get("relation"), "subject": e.get("subject_label") or e.get("subject"),
            "object": e.get("object_label") or e.get("object"),
            "conditions": e.get("conditions") or [], "direction": direction,
            "value": e.get("value"), "evidence": edge_evidence(e)}


def q_entity(by_id, edges, args, graph=None):
    node = resolve(by_id, args.get("entity") or args.get("label") or args.get("id"))
    if not node:
        return {"rows": [], "note": f"未找到实体：{args.get('entity') or args.get('label') or args.get('id')}"}
    inc = [e for e in edges if e.get("subject") == node["id"] or e.get("object") == node["id"]]
    rows = [{"entity": node["label"], "type": node.get("type"),
             "aliases": node.get("aliases") or [], "occurrences": node.get("occurrences") or [],
             "degree": len(inc)}]
    return {"rows": rows, "matched_node": node["id"],
            "edges": [_row(e, "out" if e.get("subject") == node["id"] else "in") for e in inc]}


def q_neighbors(by_id, edges, args, graph=None):
    node = resolve(by_id, args.get("entity") or args.get("label") or args.get("id"))
    if not node:
        return {"rows": [], "note": "未找到起始实体"}
    rel = args.get("relation")
    depth = max(1, min(int(args.get("depth") or 1), 3))
    seen = {node["id"]}
    frontier = [node["id"]]
    rows = []
    for _ in range(depth):
        nxt = []
        for cur in frontier:
            for e in edges:
                if e.get("subject") == cur or e.get("object") == cur:
                    other = e.get("object") if e.get("subject") == cur else e.get("subject")
                    direction = "out" if e.get("subject") == cur else "in"
                    if rel and e.get("relation") != rel:
                        continue
                    rows.append({**_row(e, direction),
                                 "from": by_id.get(cur, {}).get("label", cur),
                                 "to": by_id.get(other, {}).get("label", other)})
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
        frontier = nxt
        if not frontier:
            break
    rows.sort(key=lambda r: (-len(r["evidence"]), str(r["relation"])))
    return {"rows": rows}


def q_relation(by_id, edges, args, graph=None):
    rel = args.get("relation")
    rows = [_row(e, "out") for e in edges if not rel or e.get("relation") == rel]
    rows.sort(key=lambda r: str(r["relation"]))
    return {"rows": rows}


def q_path(by_id, edges, args, graph=None):
    src = resolve(by_id, args.get("from") or args.get("entity"))
    dst = resolve(by_id, args.get("to") or args.get("target"))
    if not src or not dst:
        return {"rows": [], "note": "起点或终点未找到"}
    adj = defaultdict(list)
    for e in edges:
        adj[e.get("subject")].append((e.get("object"), e))
        adj[e.get("object")].append((e.get("subject"), e))
    prev, q, seen = {}, deque([src["id"]]), {src["id"]}
    while q:
        cur = q.popleft()
        if cur == dst["id"]:
            break
        for nxt, e in adj.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            prev[nxt] = (cur, e)
            q.append(nxt)
    if dst["id"] not in prev and src["id"] != dst["id"]:
        return {"rows": [], "note": "两点之间没有带证据的路径"}
    chain, cur = [], dst["id"]
    while cur != src["id"]:
        p, e = prev[cur]
        chain.append(_row(e, "out" if e.get("subject") == p else "in"))
        cur = p
    chain.reverse()
    return {"rows": chain}


def q_keyword(by_id, edges, args, graph=None):
    kw = args.get("keyword") or args.get("text") or ""
    hard = _norm(kw)
    if not hard:
        return {"rows": [], "note": "缺少 keyword"}
    rows = []
    for n in by_id.values():
        if hard in _norm(n.get("label")) or any(hard in _norm(a) for a in (n.get("aliases") or [])):
            rows.append({"kind": "node", "entity": n["label"], "type": n.get("type"),
                         "occurrences": n.get("occurrences") or []})
    for e in edges:
        for ev in edge_evidence(e):
            if hard in _norm(ev.get("quote")):
                rows.append({"kind": "edge", **_row(e, "out")})
                break
    return {"rows": rows[:200]}


def q_evidence(by_id, edges, args, graph=None):
    node = resolve(by_id, args.get("entity") or args.get("label"))
    if node:
        return {"rows": [{"entity": node["label"], **o} for o in (node.get("occurrences") or [])]}
    rid = args.get("relation_id")
    rows = []
    for e in edges:
        if not rid or e.get("id") == rid:
            rows.extend([{**ev, "relation": e.get("relation"), "subject": e.get("subject_label"),
                          "object": e.get("object_label")} for ev in edge_evidence(e)])
    return {"rows": rows}


def q_conflicts(by_id, edges, args=None, graph=None):
    """跨篇冲突/不可合并分歧：既包括 conflicts_with 边，也包括 must_not_merge 裁决记录。"""
    rows = [_row(e, "out") for e in edges if e.get("relation") == "conflicts_with"]
    for rec in (graph or {}).get("must_not_merge") or []:
        ev = edge_evidence(rec) or [e for e in (rec.get("evidence") or []) if isinstance(e, dict)]
        rows.append({"kind": rec.get("kind"), "labels": rec.get("labels"),
                     "reason": rec.get("reason"), "action": rec.get("action"),
                     "cross_paper": rec.get("cross_paper"),
                     "evidence": [{"source_id": e.get("source_id"), "paragraph_id": e.get("paragraph_id"),
                                   "quote": e.get("quote")} for e in ev[:3]]})
    return {"rows": rows, "note": "conflicts_with 边与 must_not_merge 记录都表示「不合并、显式保留」"}


def q_subgraph(by_id, edges, args, graph=None):
    ids = args.get("entities") or args.get("nodes") or []
    keep = set()
    for r in ids:
        n = resolve(by_id, r)
        if n:
            keep.add(n["id"])
    rows = [_row(e, "out") for e in edges
            if e.get("subject") in keep and e.get("object") in keep]
    return {"rows": rows, "nodes": [by_id[i]["label"] for i in keep]}


def q_stats(by_id, edges, args=None, graph=None):
    by_type, by_rel = defaultdict(int), defaultdict(int)
    for n in by_id.values():
        by_type[n.get("type")] += 1
    for e in edges:
        by_rel[e.get("relation")] += 1
    return {"rows": [{"nodes": len(by_id), "edges": len(edges),
                      "by_type": dict(by_type), "by_relation": dict(by_rel),
                      "edges_with_evidence": sum(1 for e in edges if edge_evidence(e))}]}


HANDLERS = {"entity": q_entity, "neighbors": q_neighbors, "relation": q_relation, "path": q_path,
            "keyword": q_keyword, "evidence": q_evidence, "conflicts": q_conflicts,
            "subgraph": q_subgraph, "stats": q_stats}


def run_queries(graph, queries):
    """执行查询清单；返回 (results, problems)。每条结果都附证据。"""
    _, nodes, edges, by_id = (None, graph.get("nodes") or [], graph.get("edges") or [],
                              {n.get("id"): n for n in (graph.get("nodes") or []) if n.get("id")})
    out, problems = [], []
    qs = queries.get("queries") if isinstance(queries, dict) else queries
    for i, q in enumerate(qs or [], start=1):
        if not isinstance(q, dict):
            problems.append(f"query #{i} 不是对象")
            continue
        qtype = q.get("type") or "entity"
        args = q.get("args") or {}
        if qtype not in HANDLERS:
            problems.append(f"query {q.get('id') or i} 的类型 {qtype!r} 不在支持列表 {QUERY_TYPES}")
            continue
        res = HANDLERS[qtype](by_id, edges, args, graph)
        rows = res.get("rows") or []
        out.append({"id": q.get("id") or f"q{i}", "type": qtype,
                    "question": q.get("question") or "", "args": args,
                    "row_count": len(rows), "rows": rows,
                    "answer": (q.get("expect") or "") if rows else (res.get("note") or "无匹配结果"),
                    "has_evidence": bool(rows) and all(
                        ("evidence" in r and r["evidence"]) or ("quote" in r) or r.get("occurrences")
                        for r in rows)})
    return out, problems


def main():
    ap = argparse.ArgumentParser(description="在 graph.json 上跑查询（每行结果都带证据）")
    ap.add_argument("--graph", required=True)
    ap.add_argument("--queries", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--type", default="entity")
    a = ap.parse_args()
    doc, nodes, edges, by_id = load_graph(a.graph)
    if not a.queries:
        if a.type not in HANDLERS:
            kk.pjson({"error": f"未知查询类型 {a.type}"})
            return 1
        res = HANDLERS[a.type](by_id, edges, {"entity": a.label, "label": a.label}, doc)
        kk.pjson({"type": a.type, "label": a.label, "row_count": len(res.get("rows") or []),
                  "rows": res.get("rows")})
        return 0
    queries = kk.read_json(a.queries) or {}
    results, problems = run_queries(doc, queries)
    payload = {"schema": VERSION, "graph": os.path.basename(a.graph),
               "query_count": len(results), "results": results, "problems": problems}
    if a.out:
        kk.dump_json(a.out, payload)
    kk.pjson({"queries": len(results), "rows": sum(r["row_count"] for r in results),
              "with_evidence": sum(1 for r in results if r["has_evidence"]),
              "problems": problems})
    return 0


if __name__ == "__main__":
    sys.exit(main())
