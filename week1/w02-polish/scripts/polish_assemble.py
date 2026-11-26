#!/usr/bin/env python3
"""w02 学术语言润色 — 第三步：硬核验 + 导出交付物（确定性，不调用模型）。

职责：
  把 Agent 写出的「润色全文 + 逐句修改清单」与第一步清点出来的不可变成分逐条对账，
  只输出能被机械验证的指标与问题；语义层面的判断如实写进 review 与 result 的边界说明。

用法：
  python polish_assemble.py --case /input/case.json --work /app/work \
      [--revised /app/work/revised.md] [--edits /app/work/edits.jsonl] \
      [--glossary /app/work/glossary.tsv] --out /app/output

退出码：0 = ok/partial（已交付）；2 = failed（没有可交付的成品）
"""

import argparse
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import polishkit as pk  # noqa: E402

VERSION = "polish_assemble/1.0"
LEVELS = ("high", "medium", "low")
EDIT_TYPE_SET = set(pk.EDIT_TYPES)
# 改这些类型时允许动限定强度，但必须在 reason 里说明
STRENGTH_TYPES = {"hedging", "register", "clarity", "word-choice"}
REVISED_CANDIDATES = ("revised.md", "revised.txt", "manuscript_revised.md",
                      "polished.md", "polished.txt")
EDITS_CANDIDATES = ("edits.jsonl", "edits.json", "diff.jsonl", "changes.jsonl")
GLOSSARY_CANDIDATES = ("glossary.tsv", "terms.tsv", "glossary.json")


# ------------------------------------------------------------------ utilities

def find_file(base: str, candidates) -> str:
    for name in candidates:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return ""


def norm_ws(s: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", (s or "").replace("\r\n", "\n")).strip()


def flat(s: str) -> str:
    """lowercase + 去空白，用于数值/单位这类"间距不该影响判定"的比对。"""
    return re.sub(r"\s+", "", (s or "").lower())


def section_paragraphs(text: str) -> list:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n"))]
    return [b for b in blocks if b]


def group_segments(segments: list) -> list:
    """句子级 segments -> 段落级 [{para_id, kind, section, text, seg_ids}]（保持原顺序）。"""
    out, index = [], {}
    for s in segments:
        pid = s.get("para_id") or s.get("seg_id", "")[:5]
        if pid not in index:
            index[pid] = {"para_id": pid, "kind": s.get("kind", "body"),
                          "section": s.get("section", ""), "texts": [], "seg_ids": []}
            out.append(index[pid])
        index[pid]["texts"].append(s.get("text", ""))
        index[pid]["seg_ids"].append(s.get("seg_id", ""))
    for p in out:
        p["text"] = " ".join(t for t in p["texts"] if t)
        p.pop("texts", None)
    return out


def load_edits(path: str) -> tuple:
    rows, problems = [], []
    if not path:
        return rows, ["edits file not found"]
    if path.endswith(".json"):
        data = pk.read_json(path)
        if isinstance(data, dict):
            data = data.get("edits") or data.get("changes") or data.get("rows") or []
        rows = data if isinstance(data, list) else []
    else:
        rows = pk.read_jsonl(path)
    clean = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            problems.append(f"edit row {i} is not an object")
            continue
        clean.append(r)
    return clean, problems


def load_locked_glossary(path: str) -> list:
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    if path.endswith(".json"):
        data = pk.read_json(path)
        rows = data if isinstance(data, list) else (data.get("terms") or data.get("glossary") or [])
        return [r for r in rows if isinstance(r, dict)]
    with open(path, encoding="utf-8-sig") as fh:
        lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    if not lines:
        return rows
    header = lines[0].split("\t")
    for ln in lines[1:]:
        cells = ln.split("\t")
        row = {header[i]: (cells[i] if i < len(cells) else "") for i in range(len(header))}
        rows.append(row)
    return rows


def variants_of(row: dict) -> list:
    raw = row.get("variants") or ""
    if isinstance(raw, list):
        return [v for v in raw if v]
    return [v for v in re.split(r"[|,;]", str(raw)) if v.strip()]


def count_forms(text: str, forms) -> int:
    low = (text or "").lower()
    n = 0
    for f in forms:
        f = f.strip().lower()
        if not f:
            continue
        n += len(re.findall(rf"(?<![A-Za-z0-9]){re.escape(f)}(?![A-Za-z0-9])", low))
    return n


# -------------------------------------------------------------------- checks

def iss(issues: list, level: str, kind: str, where: str, detail: str, span: str = "") -> None:
    issues.append({"level": level, "kind": kind, "where": where,
                   "detail": detail, "span": (span or "")[:200]})


def protected_multiset(text: str) -> dict:
    spans = pk.protected_spans(text or "")
    out = {}
    for kind in pk.PROTECTED_KINDS:
        items = spans.get(kind) or []
        out[kind] = [flat(str(x)) for x in items if str(x).strip()]
    return out


def diff_multiset(a: list, b: list) -> tuple:
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    missing = list((ca - cb).elements())
    extra = list((cb - ca).elements())
    return missing, extra


def check_protected(src: str, rev: str, where: str, issues: list, protected_edits: list) -> dict:
    a, b = protected_multiset(src), protected_multiset(rev)
    stat = {"where": where, "by_kind": {}}
    for kind in pk.PROTECTED_KINDS:
        miss, extra = diff_multiset(a[kind], b[kind])
        stat["by_kind"][kind] = {"source": len(a[kind]), "revised": len(b[kind]),
                                 "missing": miss, "extra": extra}
        if miss:
            iss(issues, "high", "protected_token_changed", where,
                f"{kind} 成分在润色后丢失或改变：{', '.join(miss[:6])}", ", ".join(miss[:6]))
        if extra:
            iss(issues, "high", "number_invented" if kind == "number" else "protected_token_added",
                where, f"{kind} 出现原文没有的成分：{', '.join(extra[:6])}", ", ".join(extra[:6]))
    return stat


UNIVERSAL_QUANT = {"all", "every", "always", "none", "never", "any", "each", "no",
                   "所有", "全部", "总是", "从不", "任何", "每个", "均", "皆"}
REASON_MIN_CHARS = 6


def _stem(tok) -> str:
    """兼容旧调用：取主词干。"""
    return sorted(_stems(tok))[0]


def _stems(tok) -> set:
    """把 show/shows/showed/showing、indicate/indicates 等同一词形归成一个键集合，
    避免语法修正被误判成强度改动。"""
    t = str(tok).lower().strip()
    out = {t}
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            out.add(t[: -len(suf)] + rep)
    out |= {x + "e" for x in list(out)}
    out |= {x[:-1] for x in list(out) if x.endswith("e") and len(x) > 3}
    return out


def check_strength(src: str, rev: str, where: str, issues: list, fragments: list) -> dict:
    """fragments = 该段落里被声明为"动过限定强度"的修改片段（STRENGTH_TYPES 的 before）。"""
    bs, br = pk.hedge_balance(src), pk.hedge_balance(rev)
    cs, cr = pk.cues(src), pk.cues(rev)

    def declared(cues_gone) -> bool:
        if not cues_gone:
            return True
        return all(any(str(c).lower() in f.lower() for f in fragments) for c in cues_gone)

    rec = {"where": where, "source": bs, "revised": br, "declared_fragments": fragments}
    for key in ("negation", "conditional"):
        if br.get(key, 0) < bs.get(key, 0):
            iss(issues, "high", f"{key}_lost", where,
                f"{key} 线索从 {bs.get(key, 0)} 降到 {br.get(key, 0)}：改变了主张的适用条件")
    # 线索词是否真的消失：单词语按词干比对改后全文，多词短语按去标点子串比对，
    # 这样 "results shows -> show"、"results indicates -> indicate" 这类语法修正不会被误判成强度改动。
    rev_stems = set()
    for t in pk.tokens(rev):
        rev_stems |= _stems(t)
    rev_hard = pk.norm_hard(rev)

    def _gone(cue) -> bool:
        c = str(cue).strip()
        if not c:
            return False
        if " " in c:
            return pk.norm_hard(c) not in rev_hard
        return not (_stems(c) & rev_stems)

    hedge_gone = [h for h in cs.get("hedges", []) if _gone(h)]
    boost_gone = [b for b in cs.get("boosts", []) if _gone(b)]
    quant_gone = [q for q in cs.get("quantifiers", []) if q in UNIVERSAL_QUANT and _gone(q)]
    rec["hedges_removed"] = hedge_gone
    rec["boosts_removed"] = boost_gone
    rec["universals_removed"] = quant_gone
    if hedge_gone:
        ok = declared(hedge_gone)
        iss(issues, "low" if ok else "high", "hedging_strengthened", where,
            f"限定词被去掉：{', '.join(hedge_gone)}"
            + ("（已在修改说明中声明）" if ok else "（未声明：结论被加强了）"))
    if boost_gone:
        ok = declared(boost_gone)
        if not ok:
            iss(issues, "medium", "hedging_softened_undeclared", where,
                f"绝对化表述被削弱：{', '.join(boost_gone)}，但没有对应的修改说明")
    qr_uni = [q for q in cr.get("quantifiers", []) if q in UNIVERSAL_QUANT]
    qs_uni = [q for q in cs.get("quantifiers", []) if q in UNIVERSAL_QUANT]
    if len(qr_uni) > len(qs_uni):
        iss(issues, "high", "quantifier_strengthened", where,
            f"全称量词被加上：{', '.join(qr_uni)}（结论范围被放大）")
    elif quant_gone:
        ok = declared(quant_gone)
        iss(issues, "low" if ok else "medium", "universal_quantifier_removed", where,
            f"全称量词被去掉：{', '.join(quant_gone)}"
            + ("（已在修改说明中声明）" if ok else "（未声明：主张范围被改动）"))
    if br.get("boosts", 0) > bs.get("boosts", 0):
        iss(issues, "high", "boost_added", where,
            f"绝对化表述 {bs.get('boosts', 0)} → {br.get('boosts', 0)}：结论被加强")
    miss_causal = [c for c in cs.get("causal", []) if c not in cr.get("causal", [])]
    if miss_causal and cr.get("correlational"):
        iss(issues, "medium", "causal_downgraded", where,
            "因果表述被降级为相关表述：" + ", ".join(miss_causal[:4])
            + " → " + ", ".join(cr["correlational"][:3]))
    if cr.get("causal") and not cs.get("causal"):
        iss(issues, "high", "correlation_upgraded", where,
            "原文没有因果线索，改后出现：" + ", ".join(cr["causal"][:4]))
    return rec


def check_edits(edits: list, seg_index: dict, para_of_seg: dict,
                src_paras: list, rev_paras: list, issues: list) -> tuple:
    rows, declared_paras, declared_strength = [], set(), set()
    for i, e in enumerate(edits, 1):
        eid = f"e{i:04d}"
        sid = str(e.get("seg_id") or e.get("segment") or "")
        etype = str(e.get("type") or e.get("edit_type") or "")
        before = str(e.get("before") or e.get("source") or e.get("original") or "")
        after = str(e.get("after") or e.get("revised") or e.get("replacement") or "")
        reason = str(e.get("reason") or e.get("note") or e.get("explanation") or "")
        pid = para_of_seg.get(sid, "")
        where = f"{eid} {sid or '?'}"
        if not sid or not etype or (not before and not after):
            iss(issues, "high", "edit_field_missing", where,
                "修改条目缺少 seg_id/type/before/after 之一")
        if sid and sid not in seg_index:
            iss(issues, "medium", "edit_seg_unknown", where, f"seg_id {sid} 不在第一步的段落清单里")
        if etype and etype not in EDIT_TYPE_SET:
            iss(issues, "medium", "edit_type_unknown", where, f"未知修改类型 {etype}")
        if len(reason.strip()) < REASON_MIN_CHARS:
            iss(issues, "low", "edit_reason_too_short", where, "修改理由过短或缺失")
        if etype == "no-change" and norm_ws(before) != norm_ws(after):
            iss(issues, "medium", "no_change_claim", where, "标注为 no-change 但 before/after 不同")
        seg = seg_index.get(sid)
        if seg and before:
            if norm_ws(before) not in norm_ws(seg.get("text", "")):
                if flat(before) and flat(before) in flat(seg.get("text", "")):
                    iss(issues, "low", "edit_before_whitespace_variant", where,
                        "原文片段只能按忽略空白的方式匹配")
                else:
                    iss(issues, "high", "edit_before_not_found", where,
                        "before 片段在对应原句里找不到", before[:80])
        if after:
            para = next((p for p in rev_paras if p["para_id"] == pid), None)
            pool = para["text"] if para else " ".join(p["text"] for p in rev_paras)
            if norm_ws(after) not in norm_ws(pool):
                if flat(after) and flat(after) in flat(pool):
                    iss(issues, "low", "edit_after_whitespace_variant", where,
                        "改文片段只能按忽略空白的方式匹配")
                else:
                    iss(issues, "high", "edit_after_not_found", where,
                        "after 片段在润色后的对应段落里找不到", after[:80])
        if before and after and etype != "no-change":
            ms, xs = diff_multiset(protected_multiset(before)["number"],
                                   protected_multiset(after)["number"])
            if ms or xs:
                iss(issues, "high", "edit_protected_changed", where,
                    f"该修改动了数值：丢失 {ms}，新增 {xs}")
            cs = pk.cues(before)
            cr = pk.cues(after)
            strength_edit = (bool(cs.get("hedges")) and not cr.get("hedges")) or \
                            (bool(cs.get("boosts")) and not cr.get("boosts")) or \
                            (bool(cs.get("quantifiers")) and not cr.get("quantifiers"))
            if strength_edit and etype in STRENGTH_TYPES:
                declared_strength.add(pid)
        if pid:
            declared_paras.add(pid)
        rows.append({"edit_id": eid, "seg_id": sid, "para_id": pid, "type": etype,
                     "before": before, "after": after, "reason": reason,
                     "declared_strength_change": pid in declared_strength})
    for pid in declared_strength:
        for r in rows:
            if r["para_id"] == pid:
                r["declared_strength_change"] = True
    return rows, declared_paras, declared_strength


def check_terms(rows: list, rev_text: str, issues: list) -> tuple:
    stats = {"rows": len(rows), "unified": 0, "drifted": []}
    for row in rows:
        pref = pk.norm(str(row.get("preferred") or row.get("term") or ""))
        if not pref:
            continue
        variants = [v for v in variants_of(row)
                    if flat(v) != flat(pref) and v.lower() not in ("", "none")]
        stray = []
        for v in variants:
            fv, fp = flat(v), flat(pref)
            if fv == fp or fv.rstrip("s") == fp.rstrip("s"):
                continue
            if re.match(r"^[A-Z][A-Z0-9]{1,5}$", pk.norm(v)) and pref.lower() != v.lower():
                # 缩写是允许在首次定义后使用的独立形态，由 prep 的缩写规则负责
                continue
            n = count_forms(rev_text, [v])
            if n:
                stray.append(f"{v}×{n}")
        if stray:
            stats["drifted"].append({"preferred": pref, "stray": stray})
            iss(issues, "medium", "term_not_unified", f"term:{pref}",
                f"首选写法 {pref} 之外仍出现：" + ", ".join(stray))
        else:
            stats["unified"] += 1
    return stats, stats["drifted"]


def align_paragraphs(src: list, rev: list) -> tuple:
    """按序号对齐；数量不同时用 difflib 做一次段落配对。"""
    if len(src) == len(rev):
        return [(s, {"para_id": s["para_id"], "text": r, "kind": s.get("kind", ""),
                     "seg_ids": s.get("seg_ids") or []}) for s, r in zip(src, rev)], False
    sm = difflib.SequenceMatcher(None, [flat(p["text"])[:200] for p in src],
                                 [flat(p)[:200] for p in rev])
    pairs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((src[i1 + k], {"para_id": src[i1 + k]["para_id"],
                                            "text": rev[j1 + k], "kind": "", "seg_ids": []}))
        elif tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                s = src[i1 + k] if i1 + k < i2 else None
                r = rev[j1 + k] if j1 + k < j2 else ""
                rid = s["para_id"] if s else f"r{j1 + k + 1:04d}"
                pairs.append((s, {"para_id": rid, "text": r, "kind": "", "seg_ids": []}))
        elif tag == "delete":
            for k in range(i1, i2):
                pairs.append((src[k], {"para_id": src[k]["para_id"], "text": "",
                                       "kind": "", "seg_ids": []}))
        else:
            for k in range(j1, j2):
                pairs.append((None, {"para_id": f"r{k + 1:04d}", "text": rev[k],
                                     "kind": "", "seg_ids": []}))
    return pairs, True


# ---------------------------------------------------------------------- build

def build(arg_case, arg_work, arg_revised, arg_edits, arg_glossary, out_dir) -> dict:
    issues, uncertainty, evidence = [], [], []
    case, ctx = pk.load_case(arg_case)
    case_id = ctx.get("case_id")
    contract = ctx.get("contract") or {}
    segments = pk.read_json(os.path.join(arg_work, "segments.json"))
    if isinstance(segments, dict):
        segments = segments.get("segments") or []
    src_paras = group_segments(segments) if segments else []
    seg_index = {s.get("seg_id"): s for s in segments or []}
    para_of_seg = {s.get("seg_id"): (s.get("para_id") or "") for s in segments or []}

    revised_path = arg_revised or find_file(arg_work, REVISED_CANDIDATES)
    edits_path = arg_edits or find_file(arg_work, EDITS_CANDIDATES)
    gloss_path = arg_glossary or find_file(arg_work, GLOSSARY_CANDIDATES)

    status = "failed"
    reason = ""
    rev_text = ""
    if not src_paras:
        reason, status = "no_segments", "failed"
        iss(issues, "high", "segments_missing", "work/segments.json",
            "第一步的段落清单缺失：请先运行 polish_prep.py")
    elif not revised_path or not os.path.isfile(revised_path):
        reason, status = "no_revised_text", "failed"
        iss(issues, "high", "revised_missing", "work", "找不到润色后的全文（revised.md）")
    else:
        rev_text, note = pk.read_text_any(revised_path)
        if not norm_ws(rev_text):
            reason, status = "empty_revised_text", "failed"
            iss(issues, "high", "revised_empty", "revised.md", "润色后的全文为空")
        else:
            status = "ok"
            if note:
                uncertainty.append(f"revised text read via {note}")

    if status == "failed":
        check = {"status": status, "reason": reason, "metrics": {}, "issues": issues,
                 "unresolved": ["润色全文缺失，没有任何可核验的成品"]}
        pk.dump_json(os.path.join(out_dir, "check.json"), check)
        pk.dump_text(os.path.join(out_dir, "review.md"),
                     "# 复核说明\n\n未找到可交付的润色全文（%s），本次没有产出。\n" % reason)
        pk.emit_result(os.path.join(out_dir, "result.json"), case_id, status,
                       {"status_detail": f"failed: {reason}", "reason": reason},
                       uncertainty=uncertainty, contract=contract,
                       extra_top={"issues": issues})
        return {"status": status, "reason": reason, "issues_by_level":
                {lv: sum(1 for i in issues if i["level"] == lv) for lv in LEVELS}}

    edits_raw, edit_problems = load_edits(edits_path)
    for p in edit_problems:
        iss(issues, "medium", "edits_unreadable", "work/edits.jsonl", p)
    if not edits_path or not edits_raw:
        iss(issues, "high", "edits_missing", "work",
            "没有可用的逐句修改清单（edits.jsonl 缺失或为空）：交付要求每处修改都带原文、改文、类型与理由")
    locked = load_locked_glossary(gloss_path)
    if not locked:
        iss(issues, "medium", "glossary_locked_missing", "work",
            "没有锁定术语表（glossary.tsv）：术语全篇一致性无法核验")

    rev_paras_raw = section_paragraphs(rev_text)
    pairs, realigned = align_paragraphs(src_paras, rev_paras_raw)
    rev_paras = [{"para_id": r["para_id"], "text": r["text"], "kind": r.get("kind", ""),
                  "seg_ids": r.get("seg_ids") or []} for _s, r in pairs]
    if realigned:
        iss(issues, "medium", "paragraph_count_changed", "document",
            f"段落数 {len(src_paras)} → {len(rev_paras_raw)}，已按内容重新配对；润色不应改动段落结构")

    edit_rows, declared_paras, declared_strength = check_edits(
        edits_raw, seg_index, para_of_seg, src_paras, rev_paras, issues)
    frags_by_para = {}
    for r in edit_rows:
        if r["type"] in STRENGTH_TYPES and r["before"]:
            frags_by_para.setdefault(r["para_id"], []).append(r["before"])

    para_stats, sim_all_src, sim_all_rev = [], [], []
    unexplained = 0
    for src, rev in pairs:
        rid = rev["para_id"]
        stext = (src or {}).get("text", "")
        rtext = rev.get("text", "")
        changed = flat(stext) != flat(rtext)
        if src is None:
            iss(issues, "medium", "paragraph_added", rid, "润色稿多出一个段落")
        if rev.get("text", "") == "" and src is not None:
            iss(issues, "high", "paragraph_dropped", src["para_id"], "润色稿缺少该段落")
            continue
        seg_ids = (src or {}).get("seg_ids") or []
        covered = any((para_of_seg.get(r["seg_id"]) or r["para_id"]) == (src or {}).get("para_id")
                      for r in edit_rows)
        declared = bool(covered and (src or {}).get("para_id") in declared_paras)
        prot = check_protected(stext, rtext, rid, issues, edit_rows)
        strength = check_strength(stext, rtext, rid, issues,
                                  frags_by_para.get((src or {}).get("para_id"), []))
        ratio = difflib.SequenceMatcher(None, flat(stext), flat(rtext)).ratio() if (stext or rtext) else 1.0
        if changed and not covered:
            unexplained += 1
            iss(issues, "medium", "unexplained_change", rid,
                "该段落与原稿不同，但没有任何一条修改说明覆盖它")
        para_stats.append({"para_id": rid, "kind": (src or {}).get("kind", ""),
                           "section": (src or {}).get("section", ""),
                           "seg_ids": seg_ids, "changed": changed,
                           "declared": declared, "similarity": round(ratio, 4),
                           "chars_before": len(stext), "chars_after": len(rtext),
                           "protected": prot, "strength": strength})
        sim_all_src.append(stext)
        sim_all_rev.append(rtext)

    doc_prot = check_protected(" \n ".join(sim_all_src), " \n ".join(sim_all_rev),
                               "document", issues, edit_rows)
    terms_stat, drifted = check_terms(locked, rev_text, issues)

    by_kind = {}
    for i in issues:
        by_kind[i["level"]] = by_kind.get(i["level"], 0) + 1
    src_chars = sum(len(p["text"]) for p in src_paras)
    rev_chars = len(rev_text)
    protected_total = sum(len(v) for v in protected_multiset(" \n ".join(sim_all_src)).values())
    protected_missing = sum(len(k["missing"]) for k in doc_prot["by_kind"].values())
    protected_extra = sum(len(k["extra"]) for k in doc_prot["by_kind"].values())
    edits_with_reason = sum(1 for r in edit_rows if len(r["reason"].strip()) >= REASON_MIN_CHARS)
    sim = difflib.SequenceMatcher(None, flat(" ".join(sim_all_src)),
                                  flat(" ".join(sim_all_rev))).ratio()
    metrics = {
        "paragraphs_source": len(src_paras), "paragraphs_revised": len(rev_paras_raw),
        "segments_source": len(segments), "segments_indexed": len(seg_index),
        "chars_source": src_chars, "chars_revised": rev_chars,
        "similarity": round(sim, 4), "minimal_edit_rate": round(sim, 4),
        "protected_total": protected_total, "protected_missing": protected_missing,
        "protected_extra": protected_extra,
        "protected_preserved_rate": round((protected_total - protected_missing) / protected_total, 4)
        if protected_total else 1.0,
        "edits": len(edit_rows), "edits_with_reason": edits_with_reason,
        "edits_per_1k_chars": round(len(edit_rows) * 1000.0 / max(src_chars, 1), 3),
        "edit_type_histogram": {t: sum(1 for r in edit_rows if r["type"] == t)
                                for t in sorted({r["type"] for r in edit_rows})},
        "paragraphs_changed": sum(1 for p in para_stats if p["changed"]),
        "paragraphs_declared": sum(1 for p in para_stats if p["declared"]),
        "unexplained_changes": unexplained,
        "terms_locked": terms_stat["rows"], "terms_unified": terms_stat["unified"],
        "terms_drifted": len(drifted),
        "term_unified_rate": round(terms_stat["unified"] / terms_stat["rows"], 4)
        if terms_stat["rows"] else 1.0,
        "issues_high": by_kind.get("high", 0), "issues_medium": by_kind.get("medium", 0),
        "issues_low": by_kind.get("low", 0),
    }
    status = "partial" if by_kind.get("high") else "ok"
    evidence.append({"kind": "protected_ledger", "source": "document",
                     "note": "数值/单位/引用/图表指向/公式/DOI/URL 逐项对账，明细见 consistency.json"})
    evidence.append({"kind": "edit_list", "path": "edits.jsonl",
                     "note": f"{len(edit_rows)} 条修改说明，每条带原文、改文、类型与理由"})
    uncertainty.append("自动核验只覆盖可机械比对的部分：语法是否真的改对、语域是否贴合目标文体、"
                       "改写是否仍是作者本意，需要人工评审判断。")
    if not locked:
        uncertainty.append("未提供锁定术语表，术语全篇一致性只按第一步的候选清单核验。")
    if realigned:
        uncertainty.append("润色稿的段落数与原稿不一致，已按内容重新配对，段落级指标可能有偏差。")

    check = {"status": status, "metrics": metrics, "issues": issues,
             "unresolved": [
                 "语义忠实度与学术语气属人工评审范围，自动核验不覆盖。",
                 "限定强度只按词表线索计数比对：换用同义限定词不会触发，语义级加强/削弱可能漏报。",
                 "术语一致性只针对锁定术语表，表外术语的漂移不在核验范围内。",
             ]}
    pk.dump_json(os.path.join(out_dir, "check.json"), check)
    pk.dump_json(os.path.join(out_dir, "consistency.json"),
                 {"version": VERSION, "metrics": metrics, "paragraphs": para_stats,
                  "protected_document": doc_prot, "terms": {"locked": locked, "drifted": drifted}})
    pk.dump_text(os.path.join(out_dir, "revised.md"), rev_text if rev_text.endswith("\n") else rev_text + "\n")
    if edit_rows:
        pk.dump_jsonl(os.path.join(out_dir, "edits.jsonl"), edit_rows)
    if locked:
        head = "term\tpreferred\tvariants\tstatus\tnote\n"
        lines = [head]
        for r in locked:
            lines.append("\t".join([str(r.get("term", "")), str(r.get("preferred", "")),
                                    "|".join(variants_of(r)), str(r.get("status", "locked")),
                                    str(r.get("note", ""))]) + "\n")
        pk.dump_text(os.path.join(out_dir, "glossary.tsv"), "".join(lines))

    diff_lines = ["# 逐句修改清单\n",
                  f"共 {len(edit_rows)} 条修改说明，覆盖 {len(declared_paras)} 个段落。\n",
                  "| 编号 | 段落 | 类型 | 原文 | 改文 | 理由 |", "| --- | --- | --- | --- | --- | --- |"]
    for r in edit_rows:
        diff_lines.append("| {eid} | {pid} | {t} | {b} | {a} | {r} |".format(
            eid=r["edit_id"], pid=r["para_id"] or "-", t=r["type"] or "-",
            b=(r["before"] or "").replace("|", "\\|").replace("\n", " ")[:160],
            a=(r["after"] or "").replace("|", "\\|").replace("\n", " ")[:160],
            r=(r["reason"] or "").replace("|", "\\|").replace("\n", " ")[:160]))
    pk.dump_text(os.path.join(out_dir, "diff.md"), "\n".join(diff_lines) + "\n")

    rev_lines = ["# 润色复核报告\n",
                 f"- 状态：**{status}**（high {metrics['issues_high']} / medium {metrics['issues_medium']} / low {metrics['issues_low']}）",
                 f"- 段落 {metrics['paragraphs_source']} → {metrics['paragraphs_revised']}，"
                 f"字符 {metrics['chars_source']} → {metrics['chars_revised']}",
                 f"- 不可变成分：{metrics['protected_total']} 项，保全率 {metrics['protected_preserved_rate']}",
                 f"- 修改说明：{metrics['edits']} 条（带理由 {metrics['edits_with_reason']} 条），"
                 f"最小编辑相似度 {metrics['similarity']}",
                 f"- 术语：锁定 {metrics['terms_locked']} 条，统一 {metrics['terms_unified']} 条",
                 "\n## 逐段情况\n",
                 "| 段落 | 类型 | 是否改动 | 有无说明 | 相似度 | 不可变成分 | 限定强度 |",
                 "| --- | --- | --- | --- | --- | --- | --- |"]
    for p in para_stats:
        miss = sum(len(v["missing"]) for v in p["protected"]["by_kind"].values())
        rev_lines.append("| {pid} | {k} | {c} | {d} | {s} | {m} | h{h}→{h2} b{b}→{b2} |".format(
            pid=p["para_id"], k=p["kind"] or "-", c="是" if p["changed"] else "否",
            d="有" if p["declared"] else "无", s=p["similarity"],
            m=("丢失 " + str(miss)) if miss else "全部保留",
            h=p["strength"]["source"]["hedges"], h2=p["strength"]["revised"]["hedges"],
            b=p["strength"]["source"]["boosts"], b2=p["strength"]["revised"]["boosts"]))
    if issues:
        rev_lines.append("\n## 待处理问题\n")
        for i in issues:
            rev_lines.append(f"- **{i['level']}** `{i['kind']}` @ {i['where']}：{i['detail']}"
                             + (f"（片段：`{i['span']}`）" if i["span"] else ""))
    rev_lines.append("\n## 核验边界\n")
    for u in check["unresolved"]:
        rev_lines.append(f"- {u}")
    pk.dump_text(os.path.join(out_dir, "review.md"), "\n".join(rev_lines) + "\n")

    primary = {
        "status_detail": status,
        "paragraphs": len(rev_paras_raw),
        "edits": len(edit_rows),
        "similarity": metrics["similarity"],
        "protected_preserved_rate": metrics["protected_preserved_rate"],
        "issues_high": metrics["issues_high"], "issues_medium": metrics["issues_medium"],
        "next_step": ("交付 revised.md / diff.md / edits.jsonl / glossary.tsv / consistency.json；"
                      "high 项必须修掉后重跑第三步" if by_kind.get("high") else
                      "可以交付；如需更严，按 review.md 的 low 项人工复核"),
    }
    pk.emit_result(os.path.join(out_dir, "result.json"), case_id, status, primary,
                   evidence=evidence, uncertainty=uncertainty,
                   contract=contract, extra_top={"issues": issues})
    return {"status": status, "metrics": metrics, "issues_by_level": by_kind}


def main() -> int:
    ap = argparse.ArgumentParser(description="w02 polish step 3: verify and export")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--revised", default="")
    ap.add_argument("--edits", default="")
    ap.add_argument("--glossary", default="")
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    for d in (a.work, a.out):
        if d:
            os.makedirs(d, exist_ok=True)
    try:
        summary = build(a.case, a.work, a.revised, a.edits, a.glossary, a.out)
    except Exception as exc:  # 明确失败，不静默
        pk.pjson({"status": "failed", "reason": "assemble_failed", "detail": str(exc),
                  "hint": "检查 work/segments.json 与 revised.md 是否存在且可读"})
        return 2
    pk.pjson(summary)
    if summary.get("status") == "failed":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
