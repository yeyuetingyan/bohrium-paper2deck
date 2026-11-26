#!/usr/bin/env python3
"""nanoassemble.py — 第三步：核验断言、绑定证据、导出可机器读取的 Nanopublication 结构。

确定性脚本，不调用模型。输入是 Agent 写出的 work/assertions.jsonl，
本脚本对每条断言做"能不能回到原文"的硬核验，然后导出：

  assertions.jsonl       校验后的断言（补 nanopub_id 与 validation 块）
  assertions.tsv         表格版，便于人工扫读与下游导入
  nanopublications.md    人读版：一条断言 = 断言 / 证据（逐字引用 + 位置）/ 来源 / 判定
  check.json             指标 + 逐条问题清单（机器可读）
  review.md              待人工确认清单（只列有问题的）
  result.json            平台契约结果（含 output_contract 全部字段）

硬核验（证据必须能在原文里逐字找到，否则不算"对得上"）：
  quote_not_found          证据片段在所指 src_id 的原文里找不到
  quote_offset_wrong       给了 char_start/char_end，但切出来不是该片段
  subject_not_in_evidence  断言主体没出现在证据片段里（主体/证据错配）
  direction_conflict       断言极性与证据里的否定线索矛盾
  relation_not_in_vocab    关系不在受控词表里
  condition_dropped        原文有条件/范围线索，断言却没写进 conditions
  overbroad                原文是"可能/提示/在部分条件下"，断言写成了无条件结论
  quote_not_minimal        证据太长（>240 字符或跨 2 句以上），不算最小充分片段
  duplicate_assertion      与另一条断言高度重合（去重规则）
  provenance_incomplete    来源元数据缺字段（论文名/作者/年份/指纹/位置）
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paperkit as pk  # noqa: E402

VERSION = "nanokit/1.0"
REQUIRED_ASSERTION = ("subject", "relation", "object", "polarity", "quantifier", "statement")
REQUIRED_EVIDENCE = ("src_id", "quote")
REQUIRED_PROVENANCE = ("paper_title", "authors", "year", "source_file", "page", "section")
MAX_QUOTE = 240
MIN_QUOTE = 12
DUP_JACCARD = 0.85

PUNCT_MAP = {ord(c): None for c in "，。；：！？、“”‘’（）《》【】—…·,.;:!?\"'()[]{}<>-–—`"}

# 线索词表：核验时**直接从证据片段本体**再扫一遍，不依赖第一步的候选标注
CUE_CONDITION = ["if", "when", "whenever", "under", "provided", "assuming", "given that", "unless",
                 "because", "since", "due to", "in the presence of", "in the absence of",
                 "at ph", "at room temperature", "after", "before", "during", "upon",
                 "in the range", "depending on", "for samples", "for cells",
                 "当", "若", "如果", "因为", "由于", "在…条件下", "取决于", "仅当", "随着"]
CUE_HEDGE = ["may", "might", "could", "possibly", "perhaps", "likely", "unlikely", "suggest",
             "suggests", "suggested", "appear", "appears", "seem", "seems", "tend", "tends",
             "typically", "generally", "usually", "often", "sometimes", "probably", "presumably",
             "approximately", "about", "roughly", "on average", "relatively", "somewhat",
             "可能", "或许", "大概", "往往", "通常", "一般", "倾向", "似乎", "大致"]
CUE_ABSOLUTE = ["prove", "proves", "proven", "demonstrate", "demonstrates", "always", "never",
                "all", "none", "every", "completely", "entirely", "definitively", "conclusively",
                "must", "certainly", "undoubtedly", "证明", "证实", "必然", "完全", "绝对",
                "总是", "从不", "唯一"]
NEG_RE = re.compile(r"(?<![\w])(not|no|never|none|neither|nor|without|cannot|can't|did not|"
                    r"does not|do not|is not|was not|were not|are not|failed to|unable|"
                    r"不|无|未|没有|并非|并非)(?![\w])", re.IGNORECASE)


def cue_scan(text):
    low = " " + (text or "").lower() + " "

    def hit(words):
        return [w for w in words
                if re.search(r"(?<![\w])" + re.escape(w.lower()) + r"(?![\w])", low)]
    return {"conditions": hit(CUE_CONDITION), "hedges": hit(CUE_HEDGE),
            "absolutes": hit(CUE_ABSOLUTE), "negation": bool(NEG_RE.search(text or ""))}



def norm_hard(s):
    """比 pk.norm 更狠的归一：去空白 + 去标点，用于"只差排版"的宽容判定。"""
    return (s or "").translate(PUNCT_MAP).replace(" ", "").replace("\t", "").lower()


def tokens(s):
    return set(re.findall(r"[A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-']*", (s or "").lower()))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_sources(work):
    with open(os.path.join(work, "sources.json"), encoding="utf-8") as f:
        doc = json.load(f)
    return doc, {s["src_id"]: s for s in doc["sources"]}


def load_assertions(path):
    if not os.path.exists(path):
        return []
    recs = []
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []
    if raw.startswith("{"):
        try:
            doc = json.loads(raw)
            if isinstance(doc, dict) and "assertions" in doc:
                return list(doc["assertions"])
        except Exception:
            pass
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            recs.append({"_parse_error": line[:120]})
            continue
        if isinstance(obj, dict):
            recs.append(obj)
    return recs


def load_vocab(work):
    rel = {}
    for cand in (os.path.join(work, "relation_vocab.json"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "references", "relation_vocab.json")):
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    doc = json.load(f)
                rel = doc.get("relations") or doc
                if isinstance(rel, dict) and rel:
                    break
            except Exception:
                rel = {}
    return rel or {}


def quote_check(rec, src):
    """返回 (issues, info)。issues 里 severity 已定。"""
    issues = []
    ev = rec.get("evidence") or {}
    quote = pk.norm(ev.get("quote") or "")
    src_text = src.get("text", "") if src else ""
    if not src:
        issues.append({"issue": "evidence_source_unknown", "severity": "high",
                       "detail": f"src_id={ev.get('src_id')!r} 不在 sources.json 里"})
        return issues, {"verified": False}
    if not quote:
        issues.append({"issue": "missing_evidence_quote", "severity": "high",
                       "detail": "evidence.quote 为空"})
        return issues, {"verified": False}
    hay_raw, needle_raw = src_text, quote
    exact = needle_raw in hay_raw
    loose = norm_hard(needle_raw) in norm_hard(hay_raw)
    if not exact and loose:
        issues.append({"issue": "quote_whitespace_variant", "severity": "low",
                       "detail": "引用与原文只差空白/标点（可接受，但建议照抄原文）"})
    elif not exact and not loose:
        issues.append({"issue": "quote_not_found", "severity": "high",
                       "detail": f"在该 src_id 原文里找不到该片段：{quote[:60]}…"})
    # 偏移量核对
    cs, ce = ev.get("char_start"), ev.get("char_end")
    off_ok = None
    if isinstance(cs, int) and isinstance(ce, int):
        sliced = src_text[max(0, cs):max(0, ce)]
        off_ok = pk.norm(sliced) == quote or norm_hard(sliced) == norm_hard(quote)
        if not off_ok:
            idx = src_text.find(quote)
            issues.append({"issue": "quote_offset_wrong", "severity": "medium",
                           "detail": f"char_start/end 切出的内容与 quote 不符；实测首次出现位置={idx}"})
    # 最小充分性
    n_sent = len([x for x in pk.sentences(quote) if x])
    if len(quote) > MAX_QUOTE or n_sent > 2:
        issues.append({"issue": "quote_not_minimal", "severity": "medium",
                       "detail": f"证据长 {len(quote)} 字符 / {n_sent} 句，超出最小充分片段"})
    elif len(quote) < MIN_QUOTE:
        issues.append({"issue": "quote_too_short", "severity": "medium",
                       "detail": f"证据仅 {len(quote)} 字符，可能不足以支撑断言"})
    # 主体必须在证据里出现
    subj = pk.norm((rec.get("assertion") or {}).get("subject") or "")
    if subj and norm_hard(subj) and norm_hard(subj) not in norm_hard(quote):
        issues.append({"issue": "subject_not_in_evidence", "severity": "medium",
                       "detail": f"主体 {subj!r} 未出现在证据片段中"})
    # 客体：允许改写，但默认要求能在证据里找到（改写请显式写 object_normalized: true）
    objv = pk.norm((rec.get("assertion") or {}).get("object") or "")
    if (objv and not (rec.get("assertion") or {}).get("object_normalized")
            and norm_hard(objv) and norm_hard(objv) not in norm_hard(quote) and len(objv) < 80):
        issues.append({"issue": "object_not_in_evidence", "severity": "low",
                       "detail": f"客体 {objv!r} 未出现在证据片段中；若确为归一化表述请加 "
                                 f"assertion.object_normalized = true"})
    # 极性与否定线索（证据本体 + 候选标注合并）
    pol = ((rec.get("assertion") or {}).get("polarity") or "").lower()
    qc = cue_scan(quote)
    neg = qc["negation"] or bool((rec.get("_cues") or {}).get("negation"))
    if pol in ("negative", "negated") and not qc["negation"]:
        issues.append({"issue": "direction_conflict", "severity": "high",
                       "detail": "断言为否定，但证据本体里没有否定线索"})
    if pol in ("positive", "affirmative") and qc["negation"]:
        issues.append({"issue": "verify_direction", "severity": "low",
                       "detail": "证据本体含否定线索，而断言写作肯定；请确认否定作用的对象是否被正确转述"})
    return issues, {"verified": exact or loose, "offset_ok": off_ok,
                    "quote_chars": len(quote), "quote_sentences": n_sent, "quote_cues": qc}


def check_record(rec, src, vocab, seen):
    issues = []
    if "_parse_error" in rec:
        return [{"issue": "invalid_json_line", "severity": "high",
                 "detail": rec["_parse_error"]}], {}
    a = rec.get("assertion") or {}
    ev = rec.get("evidence") or {}
    pv = rec.get("provenance") or {}
    for k in REQUIRED_ASSERTION:
        if not str(a.get(k) or "").strip():
            issues.append({"issue": "assertion_field_missing", "severity": "high",
                           "detail": f"assertion.{k} 缺失"})
    for k in REQUIRED_EVIDENCE:
        if not str(ev.get(k) or "").strip():
            issues.append({"issue": "evidence_field_missing", "severity": "high",
                           "detail": f"evidence.{k} 缺失"})
    for k in REQUIRED_PROVENANCE:
        v = pv.get(k)
        if v in (None, "", [], {}):
            issues.append({"issue": "provenance_incomplete", "severity": "medium",
                           "detail": f"provenance.{k} 缺失"})
    rel = str(a.get("relation") or "").strip()
    if rel and vocab and rel not in vocab:
        near = [r for r in vocab if rel.lower() in r.lower() or r.lower() in rel.lower()]
        issues.append({"issue": "relation_not_in_vocab", "severity": "high",
                       "detail": f"关系 {rel!r} 不在受控词表"
                                 + (f"；最接近的是 {near[:3]}" if near else "")})
    q_issues, q_info = quote_check(rec, src)
    issues.extend(q_issues)
    # 条件与过宽：口径取自**证据片段本体**（第一步的标注只作补充）
    quote = pk.norm(ev.get("quote") or "")
    cand_cues = (rec.get("_cand") or {}).get("cues") or {}
    conds_hit = sorted(set(cue_scan(quote)["conditions"]) | set(cand_cues.get("conditions") or []))
    hedges_hit = sorted(set(cue_scan(quote)["hedges"]) | set(cand_cues.get("hedges") or []))
    abs_hit = sorted(set(cue_scan(quote)["absolutes"]) | set(cand_cues.get("absolutes") or []))
    conds = a.get("conditions") or []
    if isinstance(conds, str):
        conds = [conds] if conds.strip() else []
    if conds_hit and not conds:
        issues.append({"issue": "condition_dropped", "severity": "medium",
                       "detail": "证据含条件/范围线索，但 assertion.conditions 为空：" +
                                 ", ".join(conds_hit[:4])})
    if hedges_hit:
        stmt = str(a.get("statement") or "")
        hedged = bool(re.search(r"(可能|或许|提示|倾向于|大致|约|may|might|could|suggest|likely|"
                                r"appear|tend|possible|approximately)", stmt, re.I))
        conf = (rec.get("confidence") or {}).get("basis") or ""
        if not hedged and not conf:
            issues.append({"issue": "overbroad", "severity": "medium",
                           "detail": "证据含模糊限定（" + ", ".join(hedges_hit[:3]) +
                                     "），断言既无限定词也没有置信依据（confidence.basis）"})
    if abs_hit and a.get("quantifier") in (None, "", "unspecified"):
        issues.append({"issue": "absolutes_without_quantifier", "severity": "low",
                       "detail": "证据含绝对化用词（" + ", ".join(abs_hit[:3]) +
                                 "），建议写明 quantifier"})
    # 近重复
    tk = tokens(str(a.get("statement") or "") + " " + str(a.get("object") or ""))
    dup_of = None
    for other_id, other_tk in seen.items():
        if jaccard(tk, other_tk) >= DUP_JACCARD:
            dup_of = other_id
            break
    if dup_of:
        issues.append({"issue": "duplicate_assertion", "severity": "medium",
                       "detail": f"与 {dup_of} 的断言高度重合（Jaccard ≥ {DUP_JACCARD}）"})
    conf = rec.get("confidence") or {}
    if not str(conf.get("basis") or "").strip():
        issues.append({"issue": "confidence_without_basis", "severity": "low",
                       "detail": "confidence.basis 为空：无法判断该断言的把握来自何处"})
    return issues, q_info


def nanopub_id(rec):
    a = rec.get("assertion") or {}
    ev = rec.get("evidence") or {}
    pv = rec.get("provenance") or {}
    key = "|".join([str(a.get("subject")), str(a.get("relation")), str(a.get("object")),
                    str(a.get("polarity")), str(ev.get("src_id")), pk.norm(ev.get("quote") or ""),
                    str(pv.get("source_sha256") or pv.get("source_file"))])
    return "np:" + pk.sha256_text(key)


def main(argv=None):
    ap = argparse.ArgumentParser(description="核验断言并导出 Nanopublication 结构")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--assertions", default=None, help="默认 <work>/assertions.jsonl")
    ap.add_argument("--out", default="/app/output")
    args = ap.parse_args(argv)

    work = args.work
    apath = args.assertions or os.path.join(work, "assertions.jsonl")
    case, ctx = pk.load_case(args.case)
    os.makedirs(args.out, exist_ok=True)

    # 上游 prep 的坏消息一路带到底
    prep = {}
    for cand in (os.path.join(work, "prep.json"),):
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    prep = json.load(f)
            except Exception:
                prep = {}

    if not os.path.exists(os.path.join(work, "sources.json")):
        result = {"status": "failed", "reason": "no_sources",
                  "detail": f"缺少 {os.path.join(work, 'sources.json')}，请先运行 nanoextract.py"}
        with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(json.dumps(result, ensure_ascii=True))
        return 2

    sdoc, by_id = load_sources(work)
    vocab = load_vocab(work)
    raw_recs = load_assertions(apath)

    cands = {}
    cpath = os.path.join(work, "candidates.jsonl")
    if os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    cands[c["cand_id"]] = c

    checked, unresolved, seen = [], [], {}
    for i, rec in enumerate(raw_recs, start=1):
        if "_parse_error" not in rec:
            cid = rec.get("cand_id") or (rec.get("evidence") or {}).get("src_id")
            rec["_cand"] = cands.get(cid) or cands.get((rec.get("evidence") or {}).get("src_id")) or {}
            ev = rec.get("evidence") or {}
            rec["_cues"] = (rec["_cand"] or {}).get("cues") or {}
        nid = nanopub_id(rec) if "_parse_error" not in rec else f"np:bad{i}"
        issues = check_record(rec, by_id.get((rec.get("evidence") or {}).get("src_id")),
                              vocab, seen)
        issues, q_info = issues if isinstance(issues, tuple) else (issues, {})
        sev = [x["severity"] for x in issues]
        status = ("ok" if not issues else
                  "failed" if "high" in sev else "partial")
        rec_out = {k: v for k, v in rec.items() if not k.startswith("_")}
        rec_out["nanopub_id"] = nid
        rec_out["validation"] = {"status": status,
                                 "issues": issues,
                                 "evidence_verified": bool(q_info.get("verified")),
                                 "quote_chars": q_info.get("quote_chars"),
                                 "quote_sentences": q_info.get("quote_sentences")}
        a = rec.get("assertion") or {}
        seen.setdefault(nid, tokens(str(a.get("statement") or "") + " " + str(a.get("object") or "")))
        if issues:
            unresolved.append({"nanopub_id": nid, "src_id": (rec.get("evidence") or {}).get("src_id"),
                               "issues": issues})
        checked.append(rec_out)

    # ---------------- 指标
    n = len(checked)
    verified = sum(1 for r in checked if r["validation"]["evidence_verified"])
    minimal = sum(1 for r in checked if not any(i["issue"] in ("quote_not_minimal", "quote_too_short")
                                                for i in r["validation"]["issues"]))
    rel_ok = sum(1 for r in checked
                 if str((r.get("assertion") or {}).get("relation") or "") in vocab) if vocab else 0
    prov_ok = sum(1 for r in checked
                  if all((r.get("provenance") or {}).get(k) not in (None, "", [], {})
                         for k in REQUIRED_PROVENANCE))
    cond_total = sum(1 for r in checked if (r.get("_cues") or (r.get("assertion") or {})) and
                     ((r.get("_cues") or {}).get("conditions")))
    cond_kept = sum(1 for r in checked
                    if not any(i["issue"] == "condition_dropped" for i in r["validation"]["issues"]))
    dup = sum(1 for r in checked
              if any(i["issue"] == "duplicate_assertion" for i in r["validation"]["issues"]))
    clauses = [len([x for x in re.split(r"[;；,，]|\band\b|\bwhile\b|\bwhereas\b",
                                        str((r.get("assertion") or {}).get("statement") or ""))
                    if x.strip()]) for r in checked]
    used_cands = {r.get("cand_id") for r in checked if r.get("cand_id")}
    metrics = {
        "assertion_count": n,
        "candidates_available": len(cands),
        "candidates_used": len([c for c in used_cands if c]),
        "candidate_coverage": round(len([c for c in used_cands if c]) / len(cands), 4) if cands else None,
        "quote_verified_rate": round(verified / n, 4) if n else None,
        "minimal_evidence_rate": round(minimal / n, 4) if n else None,
        "relation_vocab_rate": round(rel_ok / n, 4) if vocab and n else None,
        "provenance_complete_rate": round(prov_ok / n, 4) if n else None,
        "condition_kept_rate": round(cond_kept / n, 4) if n else None,
        "duplicate_rate": round(dup / n, 4) if n else None,
        "avg_statement_clauses": round(sum(clauses) / n, 2) if n else None,
        "avg_quote_chars": round(sum(r["validation"]["quote_chars"] or 0 for r in checked) / n, 1) if n else None,
        "with_issues": len(unresolved),
        "by_relation": dict(Counter(str((r.get("assertion") or {}).get("relation"))
                                    for r in checked)),
        "by_source_kind": dict(Counter(by_id.get((r.get("evidence") or {}).get("src_id"), {})
                                       .get("kind", "unknown") for r in checked)),
    }
    high = [u for u in unresolved if any(i["severity"] == "high" for i in u["issues"])]
    if n == 0:
        status = "failed"
    elif high:
        status = "partial"
    else:
        status = "ok"

    prefix = sdoc.get("source_file", "paper")
    a_path = os.path.join(args.out, "assertions.jsonl")
    with open(a_path, "w", encoding="utf-8") as f:
        for r in checked:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    t_path = os.path.join(args.out, "assertions.tsv")
    with open(t_path, "w", encoding="utf-8") as f:
        f.write("nanopub_id\tsrc_id\tpage\tsection\tsubject\trelation\tobject\tpolarity\t"
                "quantifier\tconditions\tstatement\tquote\tdirectness\tvalidation\n")
        for r in checked:
            a, ev, pv = r.get("assertion") or {}, r.get("evidence") or {}, r.get("provenance") or {}
            row = [r["nanopub_id"], ev.get("src_id", ""), pv.get("page", ""), pv.get("section", ""),
                   a.get("subject", ""), a.get("relation", ""), a.get("object", ""),
                   a.get("polarity", ""), a.get("quantifier", ""),
                   "; ".join(a.get("conditions") or []) if isinstance(a.get("conditions"), list)
                   else str(a.get("conditions") or ""),
                   str(a.get("statement", "")).replace("\t", " "),
                   str(ev.get("quote", "")).replace("\t", " "),
                   ev.get("directness", ""), r["validation"]["status"]]
            f.write("\t".join(str(x).replace("\n", " ") for x in row) + "\n")
    md_path = os.path.join(args.out, "nanopublications.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Nanopublication 导出一览（{prefix}）\n\n"
                f"断言 {n} 条；证据逐字核验通过 {verified}/{n}；关系在受控词表内 "
                f"{rel_ok}/{n}；来源元数据完整 {prov_ok}/{n}。\n\n")
        for r in checked:
            a, ev, pv = r.get("assertion") or {}, r.get("evidence") or {}, r.get("provenance") or {}
            v = r["validation"]
            f.write(f"## {r['nanopub_id']}\n\n")
            f.write(f"- **断言**：{a.get('statement','')}\n")
            f.write(f"- **结构**：`{a.get('subject','')}` —[{a.get('relation','')}]→ "
                    f"`{a.get('object','')}`　极性 {a.get('polarity','')}　量化 {a.get('quantifier','')}\n")
            if a.get("conditions"):
                f.write(f"- **条件/范围**：{'; '.join(a.get('conditions') or [])}\n")
            f.write(f"- **证据（逐字）**：> {ev.get('quote','')}\n")
            f.write(f"- **位置**：第 {pv.get('page','?')} 页 · {pv.get('section') or '—'} · "
                    f"`{ev.get('src_id','')}`"
                    + (f" · 字符 {ev.get('char_start')}–{ev.get('char_end')}"
                       if ev.get('char_start') is not None else "") + "\n")
            f.write(f"- **证据性质**：{ev.get('directness','未标注')}\n")
            f.write(f"- **来源**：{pv.get('paper_title','')}；{', '.join(pv.get('authors') or []) if isinstance(pv.get('authors'), list) else pv.get('authors','')}；"
                    f"{pv.get('year','')}；指纹 {(pv.get('source_sha256') or '')[:16]}\n")
            f.write(f"- **把握依据**：{(r.get('confidence') or {}).get('basis','—')}\n")
            f.write(f"- **核验**：{v['status']}"
                    + (f"（{'; '.join(i['issue'] for i in v['issues'])}）" if v["issues"] else "（无问题）") + "\n\n")

    rv_path = os.path.join(args.out, "review.md")
    with open(rv_path, "w", encoding="utf-8") as f:
        f.write(f"# 待人工确认清单\n\n总体状态：**{status}**　断言 {n} 条　有问题 {len(unresolved)} 条"
                f"（其中严重 {len(high)} 条）\n\n")
        if not unresolved:
            f.write("无。所有断言都通过了逐字证据核验与字段检查。\n")
        else:
            f.write("| nanopub_id | 位置 | 级别 | 问题 | 说明 |\n|-|-|-|-|-|\n")
            for u in unresolved:
                for i in u["issues"]:
                    f.write(f"| `{u['nanopub_id']}` | {u['src_id']} | {i['severity']} | "
                            f"{i['issue']} | {str(i.get('detail',''))[:120]} |\n")
            f.write("\n修复方式：改 `work/assertions.jsonl` 对应条目后重跑 `nanoassemble.py`，"
                    "核验会重新计算——第一步的切分结果不必重算。\n")

    ck_path = os.path.join(args.out, "check.json")
    with open(ck_path, "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "case_id": ctx.get("case_id"), "status": status,
                   "metrics": metrics, "unresolved": unresolved[:200],
                   "sources_summary": {"sources": len(by_id),
                                       "pages": sdoc.get("page_count"),
                                       "source_file": prefix}}, f, ensure_ascii=False, indent=1)

    uncertainty = []
    if prep.get("status") == "failed":
        uncertainty.append({"item": "材料不可读，本轮没有产出断言",
                            "reason": prep.get("reason", "unknown"),
                            "impact": prep.get("hint", "请更换可读材料后重跑")})
    if prep.get("skipped_pages"):
        uncertainty.append({"item": f"{len(prep['skipped_pages'])} 页无可抽取文字层（已跳过）",
                            "pages": [p.get("page") for p in prep["skipped_pages"]][:20],
                            "impact": "这些页面里的结论未被抽取；扫描件需先 OCR"})
    if metrics["quote_verified_rate"] is not None and metrics["quote_verified_rate"] < 1:
        uncertainty.append({"item": f"证据逐字核验通过率 {metrics['quote_verified_rate']:.1%}",
                            "impact": "未通过项见 check.json.unresolved（quote_not_found 等）"})
    if metrics["duplicate_rate"]:
        uncertainty.append({"item": f"重复断言比例 {metrics['duplicate_rate']:.1%}",
                            "impact": "同义断言未合并，可能高估覆盖度"})
    uncertainty.append({"item": "断言是否忠实于原文语义由人复核",
                        "impact": "本脚本只能核验证据可回查、方向、条件与字段完备性，不能判定领域解释是否正确"})
    uncertainty.append({"item": "证据性质（直接/间接）依据 Agent 标注",
                        "impact": "未逐条人工确认推论链"})

    paths = {"assertions.jsonl": a_path, "assertions.tsv": t_path,
             "nanopublications.md": md_path, "check.json": ck_path, "review.md": rv_path}
    artifacts = [(p, role, mtype) for p, role, mtype in (
        (a_path, "assertion-records", "application/json"),
        (t_path, "assertion-table", "text/tab-separated-values"),
        (md_path, "human-readable-nanopublications", "text/markdown"),
        (ck_path, "validation-report", "application/json"),
        (rv_path, "human-review-list", "text/markdown"))]
    primary = {
        "assertions": [{"nanopub_id": r["nanopub_id"],
                        "statement": (r.get("assertion") or {}).get("statement"),
                        "subject": (r.get("assertion") or {}).get("subject"),
                        "relation": (r.get("assertion") or {}).get("relation"),
                        "object": (r.get("assertion") or {}).get("object"),
                        "polarity": (r.get("assertion") or {}).get("polarity"),
                        "conditions": (r.get("assertion") or {}).get("conditions"),
                        "evidence": {"src_id": (r.get("evidence") or {}).get("src_id"),
                                     "quote": (r.get("evidence") or {}).get("quote"),
                                     "page": (r.get("provenance") or {}).get("page"),
                                     "section": (r.get("provenance") or {}).get("section"),
                                     "char_start": (r.get("evidence") or {}).get("char_start"),
                                     "char_end": (r.get("evidence") or {}).get("char_end")},
                        "provenance": r.get("provenance"),
                        "confidence": r.get("confidence"),
                        "validation": r["validation"]} for r in checked],
        "assertion_count": n,
        "check": metrics,
        "status_detail": status if status != "failed" else
                         f"failed: {prep.get('reason') or ('no_assertions' if n == 0 else 'unknown')}",
        "sources_index": {sid: {"page": s["page"], "section": s["section"], "kind": s["kind"],
                                "chars": s["chars"]} for sid, s in list(by_id.items())[:400]},
    }
    evidence = [{"nanopub_id": r["nanopub_id"],
                 "src_id": (r.get("evidence") or {}).get("src_id"),
                 "page": (r.get("provenance") or {}).get("page"),
                 "quote": (r.get("evidence") or {}).get("quote"),
                 "verified": r["validation"]["evidence_verified"]} for r in checked[:200]]

    contract = ctx.get("contract") if isinstance(ctx.get("contract"), dict) else {}
    if contract:
        alias = {"assertions": "assertions.jsonl", "nanopublications": "nanopublications.md",
                 "evidence": "assertions.jsonl", "check": "check.json", "review": "review.md",
                 "table": "assertions.tsv", "records": "assertions.jsonl"}
        unmapped = []
        for key in contract:
            if key in ("schema", "case_id", "status", "primary_result", "evidence",
                       "uncertainty", "artifacts", "change_log"):
                continue
            if key.lower() in alias:
                primary.setdefault(key, alias[key.lower()])
            elif key in primary:
                continue
            else:
                unmapped.append(key)
        if unmapped:
            uncertainty.append({"item": "output_contract 字段未自动映射: " + ", ".join(unmapped),
                                "impact": "已按默认字段交付，评审如需特定命名请对照 primary_result"})

    pk.emit_result(os.path.join(args.out, "result.json"), ctx.get("case_id") or "case",
                   status, primary, evidence=evidence, uncertainty=uncertainty,
                   artifacts=artifacts, contract=contract)
    summary = {"status": status, "assertions": n, "with_issues": len(unresolved),
               **{k: metrics[k] for k in ("quote_verified_rate", "minimal_evidence_rate",
                                          "relation_vocab_rate", "provenance_complete_rate",
                                          "candidate_coverage")}}
    if status == "failed":
        summary["reason"] = prep.get("reason") or ("no_assertions" if n == 0 else "unknown")
        summary["hint"] = prep.get("hint") or (
            "没有可核验的断言：确认 work/assertions.jsonl 已写入；"
            "若上游 prep.json 报 failed，请先更换可读材料。")
    print(json.dumps(summary, ensure_ascii=True))
    return 0 if status in ("ok", "partial") else 2


if __name__ == "__main__":
    sys.exit(main())
