#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""translate_assemble.py — 装配双语对照结果，并逐段核验不变量与术语一致性。

它做三件事：
  1. 装配：把 Agent 的逐段译文与原文按 seg_id 严格对齐，产出段落级双语对照；
  2. 核验：对每段比对数字单位、引用标记、图表公式编号、否定与限定、术语锁定情况；
  3. 交底：把"必须人工确认"的段落列成清单，而不是含糊放过。

输入：
    --segments    translate_prep.py 产出的 segments.json
    --translations Agent 写的逐段译文 JSON（见下）
    --glossary    术语表（term<TAB>zh…），缺省自动找同目录 glossary_draft.tsv / glossary_locked.tsv
    --case        /input/case.json（读 output_contract 与 case_id）
翻译文件接受的三种写法（任选其一）：
    {"p1b2": "中文译文", "p1b3": {"zh": "中文译文", "note": "译法依据"}}
    {"segments": [{"seg_id": "p1b2", "zh": "中文译文", "note": ""}, ...]}
    {"translations": {"p1b2": "中文译文"}}

输出（--out，默认 /app/output）：
    bilingual.md      段落级双语对照（含段号、页码、原文、译文、译法依据）
    translation.zh.md 纯译文（段号保留，便于通读）
    translation.json  段级结构（机器可读，含每段核验结果）
    glossary.tsv      锁定后的术语表（含出现次数与页码）
    check.json        核验汇总：覆盖率、不变量通过率、术语一致率、需人工确认清单
    review.md         人工确认清单（人读版）
    result.json       按题目 output_contract 回填的结构化结果
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paperkit as pk          # noqa: E402
import translate_prep as tp    # noqa: E402

VERSION = "translatekit/1.0"

FULLWIDTH = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９（）［］，．％－＋"}
FULLWIDTH[ord("　")] = ord(" ")

CONTRACT_ALIASES = {
    "translation": "translation.json", "translations": "translation.json",
    "bilingual": "bilingual.md", "bilingual_md": "bilingual.md",
    "bilingual_translation": "bilingual.md", "aligned": "bilingual.md",
    "segments": "segments.json", "segment_table": "segments.json",
    "glossary": "glossary.tsv", "terms": "glossary.tsv",
    "terminology": "glossary.tsv", "term_table": "glossary.tsv",
    "check": "check.json", "checks": "check.json", "self_check": "check.json",
    "verification": "check.json", "review": "review.md",
    "review_list": "review.md", "notes": "review.md",
    "result_md": "bilingual.md",
}


def norm_digits(s: str) -> str:
    s = (s or "").translate(FULLWIDTH)
    return re.sub(r"\s+", "", s)


def nums_of(text: str):
    """数字+单位的多重集（保留重复，供计数比对）。"""
    out = []
    for m in tp.NUM_RE.finditer(text or ""):
        tok = norm_digits(m.group(0))
        if re.search(r"\d", tok):
            out.append(tok)
    return out


def _num_equal(a: str, b: str) -> bool:
    """数字比对：允许译文把 1,000 写成 1000、把 "10 × 10" 写成 "10×10"。"""
    a = a.replace(",", "").replace("×", "x")
    b = b.replace(",", "").replace("×", "x")
    if a == b:
        return True
    na, nb = re.match(r"^([\d.]+)(.*)$", a), re.match(r"^([\d.]+)(.*)$", b)
    if na and nb:
        va, vb = na.group(1).rstrip("."), nb.group(1).rstrip(".")
        if va == vb.rstrip("0") or va.rstrip("0") == vb:   # 1.0 vs 1
            return True
    return False


def multiset_missing(src_items, tgt_text):
    """src_items 里没在译文中出现的项（考虑等价写法）。"""
    hay = norm_digits(tgt_text)
    missing = []
    for item in src_items:
        n = norm_digits(item)
        if not n:
            continue
        if n in hay:
            continue
        if any(_num_equal(n, cand) for cand in re.findall(r"\d[\d.,]*(?:[a-zA-Z%°]+)?", hay)):
            continue
        missing.append(item)
    return missing


REF_ZH = {"figure": "图", "fig": "图", "figs": "图", "figures": "图",
          "table": "表", "tables": "表", "scheme": "图", "schemes": "图",
          "chart": "图", "algorithm": "算法", "algorithms": "算法",
          "equation": "式", "equations": "式", "eq": "式", "eqs": "式",
          "section": "节", "sections": "节", "sec": "节",
          "appendix": "附录"}


def ref_kept(ref: str, tgt_text: str) -> bool:
    m = re.match(r"^(?P<label>[A-Za-z\.\s]+?)\s*(?P<num>[\dIVXS.]+)$", ref.strip())
    if not m:
        return True
    label = re.sub(r"[.\s]+", "", m.group("label")).lower()
    num = m.group("num")
    hay = norm_digits(tgt_text)
    if num in hay:
        # 数字在，且带了中文标签 或 保留了英文标签 → 视为保留
        zh = REF_ZH.get(label, "")
        if zh and (zh + num) in hay:
            return True
        if re.search(re.escape(m.group("label").strip()), tgt_text, re.IGNORECASE):
            return True
        # 只要有该编号出现且译文里存在任一"引用类"中文词，也算弱通过
        if zh and zh in hay:
            return True
        return False
    return False


def load_translations(path: str):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    if isinstance(raw, dict) and isinstance(raw.get("segments"), list):
        for item in raw["segments"]:
            if isinstance(item, dict) and item.get("seg_id"):
                out[str(item["seg_id"])] = item
    else:
        src = raw.get("translations") if isinstance(raw, dict) and isinstance(raw.get("translations"), dict) else raw
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(v, dict):
                    out[str(k)] = v
                else:
                    out[str(k)] = {"zh": "" if v is None else str(v)}
    return raw, out


def load_glossary(paths):
    terms = {}
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                terms[parts[0].strip()] = {"zh": parts[1].strip(),
                                           "status": parts[5].strip() if len(parts) > 5 and parts[5].strip() else "locked"}
    return terms


def assemble(args):
    with open(args.segments, encoding="utf-8") as f:
        segdoc = json.load(f)
    segments = segdoc["segments"]
    tgt_lang = args.tgt_lang or segdoc.get("target_language") or "zh"
    raw, translations = load_translations(args.translations)
    glossary = load_glossary([args.glossary] if args.glossary else [
        os.path.join(os.path.dirname(args.translations), "glossary_locked.tsv"),
        os.path.join(os.path.dirname(args.translations), "glossary_draft.tsv")])

    case, ctx = pk.load_case(args.case)
    case_id = ctx.get("case_id") or segdoc.get("case_id") or "case"
    contract = (ctx.get("contract") or {}) if isinstance(ctx.get("contract"), dict) else {}

    # 上游 prep.json 的失败原因/跳页/告警必须一路带到最终结果里，
    # 否则"为什么一个字都没翻"在下游无从得知（decisions: fail-closed 但不失联）
    prep_ctx = {}
    for cand in (os.path.join(os.path.dirname(os.path.abspath(args.segments)), "prep.json"),
                 os.path.join(os.path.dirname(os.path.abspath(args.translations)), "prep.json")):
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    prep_ctx = json.load(f)
            except Exception:
                prep_ctx = {}
            break

    os.makedirs(args.out, exist_ok=True)
    by_id = {s["seg_id"]: s for s in segments}

    # ---------------- 术语在原文里的出现情况（用于一致率）
    term_hits = {}
    for term in glossary:
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", re.IGNORECASE)
        hits = [s["seg_id"] for s in segments if pat.search(s["text"])]
        if hits:
            term_hits[term] = hits

    per_seg, result_segs = [], []
    tot_inv, ok_inv = 0, 0
    tot_term, ok_term = 0, 0
    neg_total, neg_ok = 0, 0
    missing_ids, extra_ids, unresolved = [], [], []

    for seg in segments:
        sid = seg["seg_id"]
        entry = translations.get(sid)
        zh = ""
        note = ""
        if entry:
            zh = str(entry.get("zh") or entry.get("target") or entry.get("translation") or "").strip()
            note = str(entry.get("note") or entry.get("basis") or "").strip()
        src_text = seg["text"]
        inv = seg["invariants"]
        issues = []

        if not zh:
            if seg.get("skip_translate"):
                zh = src_text                     # 原文已是目标语言，按"免译"处理
                note = note or "原文已是目标语言，按免译处理并原样保留"
            else:
                issues.append({"kind": "missing_translation", "severity": "high"})

        # 1) 数字与单位
        miss_nums = multiset_missing(inv["numbers"], zh) if zh else list(inv["numbers"])
        if miss_nums:
            issues.append({"kind": "number_mismatch", "severity": "high",
                           "missing": miss_nums[:12]})
        # 2) 引用标记
        miss_cites = [c for c in inv["citations"] if norm_digits(c) not in norm_digits(zh)] if zh else list(inv["citations"])
        if miss_cites:
            issues.append({"kind": "citation_mismatch", "severity": "medium",
                           "missing": miss_cites[:8]})
        # 3) 图表公式编号
        miss_refs = [r for r in inv["refs"] if zh and not ref_kept(r, zh)]
        if miss_refs:
            issues.append({"kind": "reference_mismatch", "severity": "medium",
                           "missing": miss_refs[:8]})
        # 4) 公式片段
        miss_forms = [fm for fm in inv["formulas"]
                      if zh and fm not in zh and re.search(r"[_^={}\\α-ω]", fm)]
        if miss_forms:
            issues.append({"kind": "formula_missing", "severity": "medium",
                           "missing": miss_forms[:8]})
        # 5) 否定与限定
        if inv["negation_en"]:
            neg_total += 1
            has_zh_neg = any(c in zh for c in tp.NEG_CUES_ZH) or \
                any(re.search(r"(?<![a-z])" + re.escape(c) + r"(?![a-z])", zh.lower())
                    for c in inv["negation_en"])
            if not has_zh_neg:
                issues.append({"kind": "negation_lost", "severity": "high",
                               "source_cues": inv["negation_en"][:8]})
            else:
                neg_ok += 1
        # 6) 术语锁定
        seg_terms = [t for t, hits in term_hits.items() if sid in hits]
        miss_terms = [t for t in seg_terms if glossary[t]["zh"] not in zh]
        if seg_terms:
            tot_term += 1
            if not miss_terms:
                ok_term += 1
            else:
                issues.append({"kind": "term_not_locked", "severity": "high",
                               "terms": miss_terms[:8],
                               "expected": {t: glossary[t]["zh"] for t in miss_terms[:8]}})
        # 7) 译文语言与"没翻"检测（只对含足够自然语言的段生效：
        #    纯数字表格行、指标名行本来就该保持拉丁字符，不算"没翻"）
        src_words = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", src_text)
        prose_like = len(src_words) >= 5 and seg["kind"] not in ("table_row", "table")
        if zh and not seg.get("skip_translate"):
            cr = pk.cjk_ratio(zh)
            if prose_like and cr < 0.15 and tgt_lang.startswith("zh"):
                issues.append({"kind": "target_not_cjk", "severity": "high",
                               "cjk_ratio": round(cr, 3),
                               "hint": "该段原文为成句英文，译文却几乎不含中文，疑似漏译或原文照搬"})
            if prose_like and pk.norm(zh) == pk.norm(src_text):
                issues.append({"kind": "identical_to_source", "severity": "high"})
            if re.search(r"(TODO|待翻译|XXX|\bTBD\b)", zh, re.IGNORECASE):
                issues.append({"kind": "placeholder_left", "severity": "high"})

        sev = {i["severity"] for i in issues}
        tot_inv += 1
        if "high" not in sev:
            ok_inv += 1
        if sev:
            unresolved.append({"seg_id": sid, "page": seg["page"],
                               "issues": [i["kind"] for i in issues],
                               "severity": "high" if "high" in sev else "medium"})
        per_seg.append({"seg_id": sid, "page": seg["page"], "kind": seg["kind"],
                        "section": seg.get("section") or "", "source": src_text,
                        "target": zh, "note": note,
                        "terms": seg_terms, "issues": issues})
        result_segs.append({"seg_id": sid, "page": seg["page"], "kind": seg["kind"],
                            "source": src_text, "target": zh,
                            "terms_locked": [t for t in seg_terms if t not in miss_terms],
                            "status": "ok" if not sev else ("fail" if "high" in sev else "warn")})

    covered = sum(1 for s in per_seg if s["target"])
    for sid in translations:
        if sid not in by_id:
            extra_ids.append(sid)
    for s in segments:
        if not translations.get(s["seg_id"]) and not s.get("skip_translate"):
            missing_ids.append(s["seg_id"])

    # ---------------- 写双语对照
    bi = [f"# 段落级双语对照（{segdoc.get('source', 'material')} → {tgt_lang}）", "",
          f"- 段数：{len(segments)}　已译：{covered}　"
          f"锁定术语：{len(glossary)}　案例：`{case_id}`",
          "- 段号 `p<页>b<块>`（正文）/ `p<页>t<表>r<行>`（表格行），与原文一一对应。",
          "- `译法依据 / 待确认` 行由翻译过程记录；空表示按锁定术语与直译口径处理。", ""]
    cur_page = None
    for s in per_seg:
        if s["page"] != cur_page:
            cur_page = s["page"]
            bi += ["", f"---", "", f"## 第 {cur_page} 页", ""]
        bi += [f"### [{s['seg_id']}] · {s['kind']} · page {s['page']}"
               + (f" · {s['section']}" if s["section"] else ""), "",
               "**原文**", "", "> " + s["source"].replace("\n", "\n> "), "",
               "**译文**", "", "> " + (s["target"] or "（未译）").replace("\n", "\n> "), ""]
        if s["note"]:
            bi += ["*译法依据：* " + s["note"], ""]
        if s["issues"]:
            label = "；".join(f"{i['kind']}" + (f" {i.get('missing') or i.get('terms') or ''}"
                                                if (i.get("missing") or i.get("terms")) else "")
                              for i in s["issues"])
            bi += [f"*待确认（{label}）*", ""]
    bilingual = "\n".join(bi)

    zh_only = [f"# 译文（{tgt_lang}）", ""]
    for s in per_seg:
        zh_only += [f"### [{s['seg_id']}] page {s['page']}", "",
                    s["target"] or "（未译）", ""]
    zh_text = "\n".join(zh_only)

    # ---------------- 汇总
    metrics = {
        "segments_total": len(segments),
        "segments_translated": covered,
        "coverage_rate": round(covered / len(segments), 4) if segments else 0.0,
        "invariant_pass_rate": round(ok_inv / tot_inv, 4) if tot_inv else 0.0,
        "term_consistency_rate": round(ok_term / tot_term, 4) if tot_term else None,
        "negation_kept_rate": round(neg_ok / neg_total, 4) if neg_total else None,
        "terms_locked": len(glossary),
        "terms_with_hits": len(term_hits),
        "by_kind": dict(Counter(s["kind"] for s in segments)),
    }
    high = [u for u in unresolved if u["severity"] == "high"]
    if not segments:
        status = "failed"
    elif covered == 0:
        status = "failed"
    elif missing_ids or high:
        status = "partial"
    else:
        status = "ok"

    check = {"schema": VERSION, "case_id": case_id, "status": status,
             "metrics": metrics,
             "missing_translations": missing_ids[:50],
             "unknown_seg_ids_in_translations": extra_ids[:50],
             "glossary_used": {t: v["zh"] for t, v in list(glossary.items())[:200]},
             "unresolved": unresolved,
             "limits": [
                 "自动核验只覆盖可机械比对的不变量（数字单位、引用、图表公式编号、否定线索、术语锁定）；"
                 "语义正确性、学术语气与长句切分仍需人工复核。",
                 "数字等价判定允许 1.0≡1、千分位与全角半角差异；单位改写（如 mL→毫升）视为不一致并列入待确认。",
             ]}

    review = ["# 待人工确认清单", "",
              f"总体状态：**{status}**　覆盖率 {metrics['coverage_rate']:.1%}　"
              f"不变量通过率 {metrics['invariant_pass_rate']:.1%}"
              + (f"　术语一致率 {metrics['term_consistency_rate']:.1%}"
                 if metrics["term_consistency_rate"] is not None else ""), ""]
    if not unresolved:
        review += ["自动核验未发现高/中风险项。", ""]
    else:
        review += ["| 段号 | 页 | 问题 | 级别 |", "|-|-|-|-|"]
        for u in unresolved:
            review.append(f"| `{u['seg_id']}` | {u['page']} | {', '.join(u['issues'])} | {u['severity']} |")
        review += ["", "修复方式：改 `translations.json` 对应段后重跑 "
                       "`translate_assemble.py`，核验会重新计算。", ""]
    if missing_ids:
        review += [f"未译段（{len(missing_ids)}）：" + ", ".join(f"`{i}`" for i in missing_ids[:40]), ""]

    gl_out = ["# term\tzh\tfreq\tpages\tsections\tstatus\tnote"]
    for term, info in sorted(glossary.items(), key=lambda kv: (-len(term_hits.get(kv[0], [])), kv[0])):
        hits = term_hits.get(term, [])
        pages = sorted({by_id[h]["page"] for h in hits}) if hits else []
        status_t = info.get("status") or "locked"
        if hits and any(glossary[term]["zh"] not in
                        next((p["target"] for p in per_seg if p["seg_id"] == h), "")
                        for h in hits):
            status_t = "inconsistent"
        gl_out.append(f"{term}\t{info['zh']}\t{len(hits)}\t"
                      f"{','.join(str(p) for p in pages)}\t\t{status_t}\t")

    paths = {}
    def dump(name, text):
        p = os.path.join(args.out, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        paths[name] = p
        return p

    dump("bilingual.md", bilingual)
    dump("translation.zh.md", zh_text)
    dump("glossary.tsv", "\n".join(gl_out) + "\n")
    dump("review.md", "\n".join(review))
    # 分段表随结果一起交付：平台收的是输出目录，段号↔页码↔原文的对应关系要能独立复核
    seg_out = dict(segdoc)
    seg_out["segments"] = [{k: s.get(k) for k in
                            ("seg_id", "page", "index_on_page", "kind", "section", "text",
                             "heading", "is_caption", "caption_kind", "table_label",
                             "row_index", "cjk_ratio", "chars", "invariants",
                             "skip_translate", "merged_from")} for s in segments]
    with open(os.path.join(args.out, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(seg_out, f, ensure_ascii=False, indent=1)
    paths["segments.json"] = os.path.join(args.out, "segments.json")
    with open(os.path.join(args.out, "translation.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "case_id": case_id, "status": status,
                   "target_language": tgt_lang, "metrics": metrics,
                   "segments": result_segs}, f, ensure_ascii=False, indent=1)
    paths["translation.json"] = os.path.join(args.out, "translation.json")
    with open(os.path.join(args.out, "check.json"), "w", encoding="utf-8") as f:
        json.dump(check, f, ensure_ascii=False, indent=1)
    paths["check.json"] = os.path.join(args.out, "check.json")

    # ---------------- result.json（按 output_contract 回填）
    primary = {
        "target_language": tgt_lang,
        "translation": {"bilingual": "bilingual.md", "plain": "translation.zh.md",
                        "segments": len(segments), "translated": covered},
        "bilingual": "bilingual.md",
        "glossary": {t: v["zh"] for t, v in list(glossary.items())[:200]},
        "segments": [{"seg_id": s["seg_id"], "page": s["page"],
                      "target": s["target"]} for s in per_seg],
        "check": metrics,
        "status_detail": (status if status != "failed" else
                          f"failed: {prep_ctx.get('reason') or ('no_segments' if not segments else 'coverage_zero')}"),
    }
    evidence = []
    for s in per_seg[:200]:
        if s["target"]:
            evidence.append({"seg_id": s["seg_id"], "page": s["page"],
                             "kind": s["kind"],
                             "source_quote": s["source"][:200],
                             "target_excerpt": s["target"][:200],
                             "terms": s["terms"]})
    uncertainty = []
    if metrics["term_consistency_rate"] is not None and metrics["term_consistency_rate"] < 1:
        uncertainty.append({"item": "部分段的术语未按锁定译名出现",
                            "impact": "术语一致性得分受影响，见 check.json.unresolved"})
    if metrics["coverage_rate"] < 1:
        uncertainty.append({"item": f"覆盖率 {metrics['coverage_rate']:.1%}",
                            "impact": "未译段见 check.json.missing_translations"})
    if metrics["negation_kept_rate"] is not None and metrics["negation_kept_rate"] < 1:
        uncertainty.append({"item": "存在否定/限定线索可能丢失的段落",
                            "impact": "需人工确认语义方向，见 review.md"})
    uncertainty.append({"item": "自动核验不覆盖语义忠实度与学术语气",
                        "impact": "机器核验通过不等于译文可直接引用"})
    # 上游材料的坏消息要一路带到底
    if prep_ctx.get("status") == "failed":
        uncertainty.append({"item": "材料不可读，本轮没有产出译文",
                            "reason": prep_ctx.get("reason", "unknown"),
                            "detail": str(prep_ctx.get("detail", ""))[:200],
                            "impact": prep_ctx.get("hint", "请更换可读的材料副本后重跑")})
    if prep_ctx.get("skipped_pages"):
        skipped = prep_ctx["skipped_pages"]
        uncertainty.append({"item": f"{len(skipped)} 页无可抽取文字层（已跳过）",
                            "pages": [s.get("page") for s in skipped][:20],
                            "impact": "这部分内容未翻译；若原文确为扫描件，需先 OCR 再把文本版交回本 Skill"})
    for w in prep_ctx.get("warnings", [])[:5]:
        uncertainty.append({"item": "上游告警: " + str(w)[:160],
                            "impact": "该部分结果可能不完整或抽取有偏"})

    artifacts = [(paths["bilingual.md"], "bilingual-alignment", "text/markdown"),
                 (paths["translation.json"], "segment-level-translation", "application/json"),
                 (paths["glossary.tsv"], "locked-terminology", "text/tab-separated-values"),
                 (paths["check.json"], "verification-report", "application/json"),
                 (paths["review.md"], "human-review-list", "text/markdown"),
                 (paths["translation.zh.md"], "target-only-text", "text/markdown"),
                 (paths["segments.json"], "segment-index", "application/json")]

    unmapped = []
    if contract:
        for key in contract:
            if key in ("schema", "case_id", "status", "primary_result", "evidence",
                       "uncertainty", "artifacts", "change_log"):
                continue
            alias = CONTRACT_ALIASES.get(key.lower())
            if alias and alias in paths:
                primary.setdefault(key, alias)
            else:
                unmapped.append(key)
    if unmapped:
        uncertainty.append({"item": "output_contract 字段未自动映射: " + ", ".join(unmapped),
                            "impact": "已按默认字段交付，评审如需特定命名请对照 primary_result"})

    result = pk.emit_result(os.path.join(args.out, "result.json"), case_id, status,
                            primary, evidence=evidence, uncertainty=uncertainty,
                            artifacts=artifacts, contract=contract)
    return status, metrics, result


def main(argv=None):
    ap = argparse.ArgumentParser(description="装配双语对照并核验翻译结果")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--segments", default="/app/work/segments.json")
    ap.add_argument("--translations", required=True)
    ap.add_argument("--glossary", default=None)
    ap.add_argument("--out", default="/app/output")
    ap.add_argument("--tgt-lang", default=None)
    args = ap.parse_args(argv)
    status, metrics, result = assemble(args)
    print(json.dumps({"status": status, **{k: v for k, v in metrics.items()
                                           if k != "by_kind"}}, ensure_ascii=True))
    return 0 if status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
