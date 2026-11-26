#!/usr/bin/env python3
"""Step 1 of `academic-polish`: deterministic preparation.

Splits the manuscript into paragraphs and sentences, inventories everything that
must survive polishing (numbers, units, citations, cross references, formulas,
URLs/DOIs), marks hedging / boosting / negation / quantifier / conditional
cues, detects the target style profile, harvests terminology candidates, and
lists deterministic edit candidates.

Nothing here rewrites the text: the Agent performs the actual editing on the
inventory produced by this step, and step 3 verifies it.

Usage:
  python polish_prep.py --case /input/case.json --out /app/work [--manuscript X]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import polishkit as pk  # noqa: E402

STYLE_HINTS = {
    "abstract": ["abstract", "摘要"],
    "grant-proposal": ["grant", "proposal", "funding", "基金", "申请书", "申请书"],
    "reviewer-response": ["reviewer", "response", "rebuttal", "审稿", "回复"],
    "thesis": ["thesis", "dissertation", "chapter", "学位论文", "章节"],
    "journal-article": ["journal", "article", "paper", "manuscript", "论文", "期刊"],
}

# ---------------------------------------------------------------- detectors

ABSOLUTE_WORDS = ["prove", "proves", "proven", "always", "never", "all ", "none",
                  "every", "must", "first", "best", "optimal", "unique",
                  "unprecedented", "clearly", "obviously", "undoubtedly",
                  "证明", "总是", "从不", "所有", "必然", "首创", "最优", "毫无疑问"]

TRANSlationese = [
    (re.compile(r"\bin recent years,?\s+with the (?:rapid|fast) development of\b"),
     "word-choice", "high", "中式英语开篇套话，建议直接给出研究对象与问题"),
    (re.compile(r"\bhas attracted (?:more and more|increasing) attention\b"),
     "word-choice", "medium", "宣传化套话，建议改为具体的研究现状陈述"),
    (re.compile(r"\bit is (?:worth|important) (?:noting|to note) that\b"),
     "word-choice", "low", "冗余插入语，多数情况下可删除"),
    (re.compile(r"\bplay(?:s|ed)? an important role in\b"),
     "word-choice", "medium", "空泛表述，建议给出具体作用机制"),
    (re.compile(r"\bin order to\b"), "word-choice", "low", "可简化为 to（最小编辑）"),
    (re.compile(r"\b(?:research|study) results? (?:show|shows|indicate|indicates)\b"),
     "word-choice", "medium", "中式直译，建议改为 The results show 或直接陈述发现"),
    (re.compile(r"\bmake a conclusion\b"), "word-choice", "medium", "搭配错误，应为 draw/reach a conclusion"),
    (re.compile(r"\bconducted? (?:a |an |the )?(?:research|investigation|study)\b"),
     "word-choice", "medium", "中式搭配，建议使用 performed a study 或具体动词"),
    (re.compile(r"\bvery (?:important|significant|useful|good)\b"),
     "register", "medium", "口语化程度副词，建议用具体程度或删除"),
    (re.compile(r"\bmore and more\b"), "register", "medium", "口语化表述，建议改为 increasingly"),
    (re.compile(r"\bobviously\b"), "register", "medium", "宣传化副词，学术文本通常删除"),
    (re.compile(r"\b(?:first|earliest) (?:time|report) to\b"), "register", "high",
     "优先权断言需文献支撑，否则改为收敛表述"),
]

NOMINALIZATION = re.compile(
    r"\b(?:conduct|conducts|conducted|perform|performs|performed|carry out|carries out|"
    r"carried out|make|makes|made|do|does|did|give|gives|gave)\s+"
    r"(?:an?|the)?\s*(investigation|analysis|comparison|evaluation|assessment|examination|"
    r"discussion|calculation|measurement|determination|exploration|optimization)s?\s+of\b",
    re.IGNORECASE)

COMMA_SPLICE = re.compile(
    r",\s+(?:however|therefore|thus|moreover|furthermore|consequently|meanwhile|nevertheless)\s+",
    re.IGNORECASE)

AGREEMENT = [
    (re.compile(r"\b(?:these|those)\s+\w+\s+(?:is|was)\b", re.IGNORECASE), "these/those + 单数动词"),
    (re.compile(r"\b(?:this|that)\s+\w+s\s+(?:are|were)\b", re.IGNORECASE), "this/that + 复数动词"),
    (re.compile(r"\bresults?\s+(?:shows|indicates|demonstrates)\b", re.IGNORECASE), "results + 单数动词"),
    (re.compile(r"\b(?:studies|experiments|data)\s+(?:shows|indicates|demonstrates|reveals)\b",
                re.IGNORECASE), "复数主语 + 单数动词"),
    (re.compile(r"\b(?:each|every|neither|either)\s+\w+s\s+(?:are|were|have)\b", re.IGNORECASE),
     "each/every + 复数动词"),
    (re.compile(r"\bthere (?:is|was)\s+\w+s\b", re.IGNORECASE), "there is + 复数名词"),
]

PUNCT_PATTERNS = [
    (re.compile(r"[ \t]+[,.;:!?]"), "punctuation", "low", "标点前多余空格"),
    (re.compile(r"[,;:](?=[A-Za-z\u4e00-\u9fff])"), "punctuation", "low", "标点后缺少空格"),
    (re.compile(r"(?<=\d)-(?=\d)"), "punctuation", "low", "数字区间建议使用连接号（–）"),
    (re.compile(r"\d\s+%"), "punctuation", "low", "百分号前不应有空格"),
    (re.compile(r"\.\.+|,,|;;"), "punctuation", "low", "重复标点"),
    (re.compile(r"[(（][^()（）]{0,200}$"), "punctuation", "medium", "括号未闭合"),
    (re.compile(r"\b(\w+) \1\b", re.IGNORECASE), "grammar", "medium", "重复词"),
]

EN_VARIANTS = [
    ("behaviour", "behavior"), ("colour", "color"), ("analyse", "analyze"),
    ("analysed", "analyzed"), ("analysing", "analyzing"), ("modelling", "modeling"),
    ("labelled", "labeled"), ("catalogue", "catalog"), ("centre", "center"),
    ("fibre", "fiber"), ("metre", "meter"), ("defence", "defense"),
]

COLON_CAP = re.compile(r":\s+[a-z]")
SPACE_BEFORE_UNIT = re.compile(r"\b\d+(?:\.\d+)?(?P<u>nm|mm|cm|kg|mg|mL|min|s|h|K|V|W)\b")


def detect_style(ctx: dict, text: str) -> tuple:
    """Return (style_key, source, notes). The declared style wins when present."""
    notes = []
    declared = pk.norm(str(ctx.get("style") or "")).lower()
    if declared:
        for key, hints in STYLE_HINTS.items():
            if key in declared or any(h in declared for h in hints):
                return key, "case_metadata_style", notes
        notes.append("case declared an unknown style %r; falling back to hints" % declared)
    raw = " ".join(str(x) for x in [ctx.get("task"), ctx.get("genre")] if x)
    low = raw.lower()
    for key, hints in STYLE_HINTS.items():
        for h in hints:
            if h in low:
                notes.append("style inferred from task text")
                return key, "case_task", notes
    head = (text or "")[:400].lower()
    for key, hints in STYLE_HINTS.items():
        for h in hints:
            if h in head:
                notes.append("style inferred from manuscript lead")
                return key, "manuscript_lead", notes
    notes.append("style not declared by the case; defaulted to journal-article")
    return "journal-article", "default", notes


def split_paragraphs(text: str) -> list:
    """Paragraph units; keeps markdown headings and LaTeX sectioning intact."""
    text = (text or "").replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", text)
    out = []
    for b in blocks:
        b = b.strip("\n")
        if not b.strip():
            continue
        out.append(b)
    return out


def para_kind(p: str) -> str:
    s = p.strip()
    if re.match(r"^#{1,6}\s+\S", s):
        return "heading"
    if re.match(r"^\\(?:sub)*section\*?\{", s) or re.match(r"^\\(?:chapter|part)\*?\{", s):
        return "heading"
    if re.match(r"^\\(?:begin|end)\{", s):
        return "environment"
    if re.match(r"^(?:\d+(?:\.\d+)*)[.)]?\s+\S{0,60}$", s):
        return "heading"
    if re.match(r"^(?:Abstract|摘要|Keywords|关键词|References|参考文献|Acknowledg\w*)\b", s, re.I):
        return "front-matter"
    if re.match(r"^(?:[-*+]\s|\d+[.)]\s)", s):
        return "list"
    if re.match(r"^(?:Table|Figure|Fig\.|表|图)\s*\d", s, re.I):
        return "caption"
    return "body"


def section_of(p: str, current: str) -> str:
    k = para_kind(p)
    if k == "heading":
        return re.sub(r"^#{1,6}\s+", "", p.strip())[:80]
    return current


def detect_issues(seg_id: str, text: str, gl_terms: list) -> list:
    issues = []
    low = text.lower()

    for rx, label in AGREEMENT:
        m = rx.search(text)
        if m:
            issues.append({
                "seg_id": seg_id, "type": "grammar", "severity": "high",
                "kind": "subject_verb_agreement", "span": m.group(0),
                "detail": label, "hint": "修正主谓一致，不改变句子承载的信息",
            })

    m = NOMINALIZATION.search(text)
    if m:
        issues.append({
            "seg_id": seg_id, "type": "word-choice", "severity": "medium",
            "kind": "redundant_nominalization", "span": m.group(0),
            "detail": "动词+名词化结构冗余", "hint": "还原为单个动词（最小编辑）",
        })

    m = COMMA_SPLICE.search(text)
    if m:
        issues.append({
            "seg_id": seg_id, "type": "punctuation", "severity": "medium",
            "kind": "comma_splice", "span": m.group(0).strip(),
            "detail": "逗号连接两个独立分句", "hint": "改分号、句号或补连接词",
        })

    for rx, etype, sev, detail in TRANSlationese:
        m = rx.search(low)
        if m:
            issues.append({
                "seg_id": seg_id, "type": etype, "severity": sev,
                "kind": "translationese", "span": text[m.start():m.end()],
                "detail": detail, "hint": "按目标文体改写，且不得改变原意与限定强度",
            })

    for rx, etype, sev, detail in PUNCT_PATTERNS:
        m = rx.search(text)
        if m:
            span = text[m.start():m.end() + 12] if len(m.group(0)) < 4 else m.group(0)[:60]
            issues.append({
                "seg_id": seg_id, "type": etype, "severity": sev,
                "kind": "punctuation", "span": span[:60],
                "detail": detail, "hint": "按目标期刊/模板规范统一",
            })

    if COLON_CAP.search(text):
        m = COLON_CAP.search(text)
        issues.append({
            "seg_id": seg_id, "type": "punctuation", "severity": "low",
            "kind": "colon_case", "span": text[max(0, m.start() - 20):m.end() + 10],
            "detail": "冒号后首字母大小写不一致", "hint": "按目标文体统一",
        })

    for a, b in EN_VARIANTS:
        if re.search(rf"\b{a}\b", low) and re.search(rf"\b{b}\b", low):
            issues.append({
                "seg_id": seg_id, "type": "consistency", "severity": "medium",
                "kind": "spelling_variant", "span": f"{a} / {b}",
                "detail": "同一语料混用英式与美式拼写", "hint": "按目标期刊语言统一",
            })
            break

    hits = [w for w in ABSOLUTE_WORDS if w in low]
    if hits:
        issues.append({
            "seg_id": seg_id, "type": "register", "severity": "medium",
            "kind": "absolute_claim", "span": ", ".join(sorted(set(h.strip() for h in hits))),
            "detail": "绝对化表述需与证据强度匹配", "hint": "除非有本句数据/文献支撑，否则收敛为限定表述",
        })

    for row in gl_terms:
        for var in row.get("variants") or []:
            if var and var.lower() in low and row["preferred"].lower() not in low:
                issues.append({
                    "seg_id": seg_id, "type": "terminology", "severity": "high",
                    "kind": "term_variant", "span": var,
                    "detail": f"使用了非首选写法（首选：{row['preferred']}）",
                    "hint": "统一为术语表首选写法",
                })
    return issues


def _word_forms(form: str) -> list:
    """Case- and plural-tolerant surface forms of a term."""
    f = pk.norm(form).lower()
    out = {f}
    if f.endswith("ies"):
        out.add(f[:-3] + "y")
    if f.endswith("s") and not f.endswith("ss"):
        out.add(f[:-1])
    else:
        out.add(f + "s")
    return sorted(out)


ACRONYM_FORM_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")


def canon_singular(s: str) -> str:
    f = pk.norm(s).lower()
    if f.endswith("ies"):
        return f[:-3] + "y"
    if f.endswith("s") and not f.endswith("ss"):
        return f[:-1]
    return f


def _full_form_of(row: dict) -> str:
    cands = [c for c in [row.get("preferred"), row.get("term")]
             if c and not ACRONYM_FORM_RE.match(pk.norm(c))]
    cands += [v for v in (row.get("variants") or []) if v and not ACRONYM_FORM_RE.match(pk.norm(v))]
    if not cands:
        return ""
    return max(cands, key=len)


def scan_unit_spacing(segments: list) -> list:
    """Report a unit only when the manuscript writes it BOTH attached and spaced."""
    styles = {}
    for s in segments:
        for m in pk.NUM_RE.finditer(s["text"]):
            unit = m.group("unit")
            if not unit:
                continue
            key = unit.lower()
            if key == "%" or key.startswith("°"):
                continue  # per cent and degrees are conventionally attached
            gap = s["text"][m.end("val"):m.start("unit")]
            st = styles.setdefault(key, {"attached": [], "spaced": []})
            st["attached" if gap == "" else "spaced"].append((s["seg_id"], m.group(0).strip()))
    out = []
    for key, st in sorted(styles.items()):
        if st["attached"] and st["spaced"]:
            seg_sp, sample_sp = st["spaced"][0]
            _seg_at, sample_at = st["attached"][0]
            out.append({
                "seg_id": seg_sp, "type": "punctuation", "severity": "low",
                "kind": "unit_spacing_inconsistent", "span": f"{sample_sp} / {sample_at}",
                "detail": (f"单位 {key} 在稿件中既有空格写法（{sample_sp}）"
                           f"又有紧贴写法（{sample_at}）"),
                "hint": f"全篇统一数值与单位 {key} 的间距写法",
            })
    return out


def scan_terminology(segments: list, rows: list) -> list:
    """Manuscript-level terminology issues (not per sentence)."""
    issues = []
    text_all = "\n".join(s["text"] for s in segments)
    low_all = text_all.lower()

    def occurrences(form: str) -> int:
        return sum(len(re.findall(rf"\b{re.escape(f)}\b", low_all)) for f in _word_forms(form))

    def first_seg_containing(needle: str) -> str:
        n = needle.lower()
        for s in segments:
            if n in s["text"].lower():
                return s["seg_id"]
        return segments[0]["seg_id"] if segments else ""

    for row in rows:
        pref = row.get("preferred") or row.get("term") or ""
        if not pref:
            continue
        acronyms = [v for v in (row.get("variants") or []) if v and ACRONYM_FORM_RE.match(pk.norm(v))]
        if row.get("kind") == "acronym":
            full = _full_form_of(row)
            acronyms = acronyms or [v for v in (row.get("variants") or []) if v]
        else:
            full = pref
        # acronym handling: only complain when the acronym is undefined or used too early
        if acronyms and row.get("kind") == "acronym":
            acr = acronyms[0]
            status = row.get("acronym_status", "ok")
            if status == "defined_after_use":
                issues.append({
                    "seg_id": first_seg_containing(acr), "type": "terminology",
                    "severity": "high", "kind": "acronym_used_before_definition", "span": acr,
                    "detail": f"缩写 {acr} 先于全称 {full} 出现",
                    "hint": f"在首次使用处给出全称 {full}（{acr}），其后统一用缩写",
                })
            elif full and occurrences(full) == 0:
                issues.append({
                    "seg_id": first_seg_containing(acr), "type": "terminology",
                    "severity": "medium", "kind": "acronym_undefined", "span": acr,
                    "detail": f"缩写 {acr} 在稿件中找不到全称定义",
                    "hint": f"首次出现时给出全称 {full}（{acr}）",
                })
            continue
        pref_hits = occurrences(pref)
        for var in row.get("variants") or []:
            if not var or ACRONYM_FORM_RE.match(pk.norm(var)):
                continue
            if canon_singular(var) == canon_singular(pref):
                continue
            var_hits = occurrences(var)
            if var_hits == 0:
                continue
            sev = "medium" if pref_hits else "low"
            kind = "term_variant_drift" if pref_hits else "term_never_preferred"
            detail = (f"同一概念存在多种写法：{pref} / {var}"
                      + ("（首选写法也在使用）" if pref_hits else "（首选写法全篇未出现）"))
            issues.append({
                "seg_id": first_seg_containing(var), "type": "terminology", "severity": sev,
                "kind": kind, "span": var, "detail": detail,
                "hint": f"全篇统一为 {pref}",
            })
    seen, out = set(), []
    for i in issues:
        key = (i["kind"], i["span"], i["seg_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out


# ---------------------------------------------------------------- glossary

ACRONYM_DEF = re.compile(r"([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z][A-Za-z\-]*){0,4})\s*\(([A-Z][A-Z0-9]{1,5})\)")
ACRONYM_USE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\b")
HYPHEN_TERM = re.compile(r"\b([A-Za-z]{3,})-([A-Za-z]{3,})\b")

PHRASE_STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "at", "by", "for", "with",
               "to", "from", "as", "that", "this", "these", "those", "we", "our", "their",
               "is", "are", "was", "were", "be", "been", "using", "used", "use", "shows",
               "show", "showed", "based", "such", "than", "then", "which", "where",
               "reach", "reaches", "reached", "achieve", "achieves", "achieved", "obtain",
               "obtains", "obtained", "report", "reports", "reported", "define", "defines",
               "defined", "improve", "improves", "improved", "increase", "increases",
               "increased", "measure", "measures", "measured", "record", "records",
               "recorded", "give", "gives", "gave", "take", "takes", "took", "call", "calls",
               "called", "term", "terms", "termed", "known", "referred", "abbreviated",
               "hereafter", "herein", "yield", "yields", "yielded", "exhibit", "exhibits",
               "exhibited", "perform", "performs", "performed", "conduct", "conducts",
               "conducted", "deliver", "delivers", "delivered", "attain", "attains", "attained"}


def trim_full_form(raw: str) -> str:
    """Trim a captured full form to the noun phrase that actually names the acronym.

    Walks backwards from the acronym, keeping at most four content words and
    stopping at the first stop word. Returns "" when nothing usable remains.
    """
    words = [w for w in pk.norm(raw).split() if w]
    keep = []
    for w in reversed(words):
        if w.lower() in PHRASE_STOP or not re.match(r"^[A-Za-z][A-Za-z\-]*$", w):
            break
        keep.insert(0, w)
        if len(keep) >= 4:
            break
    if not keep or len(keep) > 4:
        return ""
    return " ".join(keep)


def glossary_candidates(segments: list) -> tuple:
    """Harvest terminology candidates: acronyms, hyphenation pairs, phrases."""
    text = "\n".join(s["text"] for s in segments)
    rows = {}
    notes = []

    # acronym definitions and their first use
    defs = {}
    for m in ACRONYM_DEF.finditer(text):
        acr = m.group(2)
        full = trim_full_form(m.group(1))
        if not full:
            continue
        defs.setdefault(acr, {"full": full, "at": m.start()})
    first_use = {}
    for m in ACRONYM_USE.finditer(text):
        acr = m.group(1)
        first_use.setdefault(acr, m.start())

    for acr, info in sorted(defs.items()):
        fu = first_use.get(acr)
        status = "ok"
        note = f"首次出现位置 {info['at']}"
        if fu is not None and fu < info["at"]:
            status = "defined_after_use"
            note = f"缩写在第 {fu} 字符处先于全称定义（{info['at']}）被使用"
            notes.append(f"{acr}: 缩写先于全称定义")
        rows[info["full"]] = {
            "term": info["full"], "preferred": info["full"], "variants": [acr],
            "freq": len(re.findall(rf"\b{re.escape(acr)}\b", text)),
            "status": "suggested", "note": note, "kind": "acronym",
            "acronym_status": status,
        }

    # hyphenation variants: "spin-coating" vs "spin coating"
    hyph = {}
    for m in HYPHEN_TERM.finditer(text):
        a, b = m.group(1).lower(), m.group(2).lower()
        if a in PHRASE_STOP or b in PHRASE_STOP:
            continue
        joined = f"{a}-{b}"
        spaced = f"{a} {b}"
        hyph.setdefault(joined, 0)
        hyph[joined] += 1
        if re.search(rf"\b{re.escape(spaced)}\b", text, re.IGNORECASE):
            key = joined
            if key not in rows:
                rows[key] = {
                    "term": key, "preferred": key, "variants": [spaced],
                    "freq": hyph[joined], "status": "suggested",
                    "note": "连字符与空格两种写法并存，需统一", "kind": "hyphenation",
                }

    # repeated multiword phrases: flag when the same phrase has several surface forms
    groups = {}
    for m in re.finditer(r"\b([A-Za-z][A-Za-z\-]{2,}(?:\s+[A-Za-z][A-Za-z\-]{2,}){1,3})\b", text):
        phrase = m.group(1)
        words = phrase.split()
        if any(w.lower() in PHRASE_STOP for w in words):
            continue
        key = phrase.lower()
        groups.setdefault(key, {})
        groups[key][phrase] = groups[key].get(phrase, 0) + 1
    for key, forms in sorted(groups.items()):
        total = sum(forms.values())
        if total < 2 or len(key) < 8:
            continue
        if len(forms) > 1:
            if key not in rows:
                rows[key] = {
                    "term": key, "preferred": key,
                    "variants": [f for f in sorted(forms) if f != key],
                    "freq": total, "status": "suggested",
                    "note": "同一术语存在大小写/形态差异，需统一", "kind": "capitalization",
                }
    return list(rows.values()), notes


def merge_case_glossary(rows: list, ctx: dict) -> tuple:
    """Merge a case-provided glossary into the harvested candidates."""
    prescribed = pk.parse_glossary(ctx.get("glossary"))
    notes = []
    index = {}
    for r in rows:
        for form in [r.get("term"), r.get("preferred")] + list(r.get("variants") or []):
            if form:
                index.setdefault(canon_singular(form), r)
    for p in prescribed:
        pref = pk.norm(p.get("preferred") or p.get("term") or "")
        variants = [pk.norm(v) for v in (p.get("variants") or []) if pk.norm(v)]
        if not pref:
            continue
        row = index.get(canon_singular(pref))
        if row is None:
            for v in variants:
                row = index.get(canon_singular(v))
                if row is not None:
                    break
        if row is not None:
            row["preferred"] = pref
            row["status"] = "prescribed"
            row["source"] = "case"
            for v in variants:
                if v not in (row.get("variants") or []):
                    row.setdefault("variants", []).append(v)
            if p.get("note"):
                row["note"] = p["note"]
            for form in [pref] + variants:
                index.setdefault(canon_singular(form), row)
        else:
            new_row = {
                "term": pref, "preferred": pref, "variants": variants,
                "freq": 0, "status": "prescribed", "kind": "case_glossary",
                "note": p.get("note") or "", "source": "case",
            }
            rows.append(new_row)
            for form in [pref] + variants:
                index.setdefault(canon_singular(form), new_row)
    if prescribed:
        notes.append(f"case supplied {len(prescribed)} glossary entr(ies)")
    return rows, notes


def write_glossary_tsv(path: str, rows: list) -> None:
    lines = ["term\tpreferred\tvariants\tfreq\tstatus\tkind\tsource\tnote"]
    for r in sorted(rows, key=lambda x: (-x.get("freq", 0), x.get("term", ""))):
        lines.append("\t".join([
            r.get("term", ""), r.get("preferred", "") or "",
            "|".join(r.get("variants") or []), str(r.get("freq", 0)),
            r.get("status", "suggested"), r.get("kind", ""), r.get("source", "harvested"),
            (r.get("note") or "").replace("\t", " "),
        ]))
    pk.dump_text(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------- main

def build(arg_case: str, arg_manuscript: str, out_dir: str, max_segments: int) -> dict:
    case, ctx = pk.load_case(arg_case)
    if arg_manuscript:
        ctx["manuscript_path"] = arg_manuscript
        ctx["inline_text"] = ""
    text, source_kind, path, notes = pk.load_manuscript(ctx)

    if not text.strip():
        reason = "no_material"
        hint = ("未找到稿件：请在 case.json 中给出稿件路径（如 manuscript_path），"
                "或用 --manuscript 显式指定；支持 .md/.txt/.tex/.docx（.pdf 需 PyMuPDF）")
        if source_kind.endswith(":empty"):
            reason = "empty_material"
            hint = "稿件文件存在但内容为空：请确认上传的是正式稿件，补齐后重跑第一步"
        elif source_kind.startswith("file:"):
            reason = "unreadable_material"
            hint = ("稿件存在但读不出文字（可能损坏、加密、或是没有文字层的扫描件）："
                    "请提供可解析的稿件；.pdf 需要 PyMuPDF（fitz）")
        prep = {
            "status": "failed", "reason": reason,
            "detail": source_kind,
            "hint": hint,
            "next_step": "补齐输入后重跑第一步；不要凭空生成稿件内容",
            "notes": notes,
        }
        pk.dump_json(os.path.join(out_dir, "prep.json"), prep)
        return prep

    style_key, style_source, style_notes = detect_style(ctx, text)
    notes.extend(style_notes)
    profile = pk.STYLE_PROFILES[style_key]

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        prep = {"status": "failed", "reason": "no_segments",
                "hint": "稿件读取成功但没有可切分的段落", "notes": notes}
        pk.dump_json(os.path.join(out_dir, "prep.json"), prep)
        return prep

    segments = []
    section = ""
    counter = 0
    truncated = False
    for pi, para in enumerate(paragraphs):
        kind = para_kind(para)
        section = section_of(para, section)
        para_id = f"p{pi + 1:04d}"
        if kind in ("heading", "front-matter"):
            segs = [pk.norm(para)]
        else:
            segs = pk.sentences(para)
            if not segs:
                segs = [pk.norm(para)]
        for si, s in enumerate(segs):
            if counter >= max_segments:
                truncated = True
                break
            counter += 1
            seg_id = f"{para_id}b{si + 1}"
            prot = pk.protected_spans(s)
            segments.append({
                "seg_id": seg_id,
                "para_id": para_id,
                "index": counter,
                "kind": kind if kind != "body" or len(segs) == 1 else "sentence",
                "section": section,
                "text": s,
                "chars": len(s),
                "sha256_16": pk.sha256_16(s),
                "cjk_ratio": round(pk.cjk_ratio(s), 3),
                "cues": pk.cues(s),
                "balance": pk.hedge_balance(s),
                "protected": prot,
            })
        if truncated:
            break

    gl_rows, gl_notes = glossary_candidates(segments)
    gl_rows, merge_notes = merge_case_glossary(gl_rows, ctx)
    notes.extend(gl_notes)
    notes.extend(merge_notes)
    issues = []
    for s in segments:
        if s["kind"] == "heading":
            continue
        issues.extend(detect_issues(s["seg_id"], s["text"], []))
    issues.extend(scan_terminology(segments, gl_rows))
    issues.extend(scan_unit_spacing(segments))

    by_type = {}
    for i in issues:
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1

    pk.dump_json(os.path.join(out_dir, "segments.json"), segments)
    pk.dump_jsonl(os.path.join(out_dir, "issues.jsonl"), issues)
    write_glossary_tsv(os.path.join(out_dir, "glossary_draft.tsv"), gl_rows)

    ctx_out = {
        "source": {"kind": source_kind, "path": path, "chars": len(text),
                   "sha256": pk.sha256_text(text), "paragraphs": len(paragraphs)},
        "style": {"key": style_key, "zh": profile["zh"], "source": style_source,
                  "rules": profile["rules"]},
        "target_language": ctx.get("target_language") or ("zh" if pk.cjk_ratio(text) > 0.5 else "en"),
        "audience": ctx.get("audience"),
        "contract": sorted((ctx.get("contract") or {}).keys()),
        "counts": {"segments": len(segments), "issues": len(issues), "terms": len(gl_rows),
                   "issues_by_type": by_type},
        "notes": notes,
    }
    pk.dump_json(os.path.join(out_dir, "context.json"), ctx_out)

    # human/agent readable segment sheet
    md = ["# 待润色句段清单（第一步产物，未做任何改写）", ""]
    md.append(f"- 文体：**{profile['zh']}**（{style_key}，来源：{style_source}）")
    md.append(f"- 目标语言：{ctx_out['target_language']}　句段数：{len(segments)}　候选问题：{len(issues)}　术语候选：{len(gl_rows)}")
    md.append("")
    md.append("> 每条给出一句原文、必须原样保留的成分（数字/单位/引用/图表指向/公式）"
              "以及需要守住的限定强度。第 3 步会逐条核对。")
    md.append("")
    for s in segments:
        md.append(f"## {s['seg_id']}　[{s['kind']}]　{s.get('section') or '-'}")
        md.append("")
        md.append("```text")
        md.append(s["text"])
        md.append("```")
        b = s["balance"]
        md.append(f"限定强度：hedge={b['hedges']} boost={b['boosts']} neg={b['negation']} "
                  f"quant={b['quantifier']} cond={b['conditional']} "
                  f"causal={b['causal']} corr={b['correlational']}")
        prot = s["protected"]
        keep = []
        for k in ("number", "citation", "crossref", "formula", "url", "doi"):
            if prot.get(k):
                keep.append(f"{k}: " + " / ".join(prot[k][:8]))
        md.append("必须原样保留：" + ("；".join(keep) if keep else "（无标记成分）"))
        mine = [i for i in issues if i["seg_id"] == s["seg_id"]]
        if mine:
            md.append("候选修改点：")
            for i in mine:
                md.append(f"- [{i['type']}/{i['severity']}] {i['kind']}：{i['detail']}"
                          f"（片段：`{i['span'][:60]}`）")
        md.append("")
    pk.dump_text(os.path.join(out_dir, "segments.md"), "\n".join(md))

    empties = [s["seg_id"] for s in segments if not s["text"].strip()]
    dupes = {}
    for s in segments:
        dupes.setdefault(s["sha256_16"], []).append(s["seg_id"])
    dup_segs = {k: v for k, v in dupes.items() if len(v) > 1}
    prep_check = {
        "empty_segments": empties,
        "duplicate_segments": dup_segs,
        "segments_truncated": truncated,
        "issues_without_span": [i for i in issues if not i.get("span")][:20],
        "notes": notes,
    }
    pk.dump_json(os.path.join(out_dir, "prep_check.json"), prep_check)

    prep = {
        "status": "ok",
        "source": source_kind,
        "paragraphs": len(paragraphs),
        "segments": len(segments),
        "issues": len(issues),
        "issues_by_type": by_type,
        "terms": len(gl_rows),
        "style": style_key,
        "target_language": ctx_out["target_language"],
        "next_step": [
            "阅读 work/segments.md（每段附必须保留成分与限定强度）",
            "锁定 work/glossary_draft.tsv：把 status 改为 locked，preferred 填定稿写法",
            "逐句润色，写 work/edits.jsonl（每处修改：seg_id/type/before/after/reason）",
            "把润色后的完整稿件写 work/revised.md（按段落顺序）",
            "运行第三步 polish_assemble.py 做硬核验并产出交付物",
        ],
        "notes": notes,
    }
    pk.dump_json(os.path.join(out_dir, "prep.json"), prep)
    return prep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--manuscript", default="")
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--max-segments", type=int, default=2000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    prep = build(a.case, a.manuscript, a.out, a.max_segments)
    pk.pjson({k: v for k, v in prep.items() if k != "next_step"})
    return 0 if prep.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
