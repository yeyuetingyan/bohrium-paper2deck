#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""noteskit：把论文的块级解析结果组织成「与原文结构对齐」的结构化笔记。

设计约束（对应赛题四个关注点）：
- 对得上：章节骨架只来自论文自己的标题层级，不套通用模板；
- 留得住：研究问题 / 数据 / 方法条件 / 主要发现 / 局限逐项落字段，条件单独成表；
- 找得回：每条笔记是原文句子的逐字摘录 + 页码 + 块号 + 内容哈希，可回查；
- 用得上：输出可 grep 的 Markdown、机器可读 JSON 与倒排索引。

所有笔记文本都是原文摘录，脚本不做释义改写；角色标签（目的/方法/结果/局限）
是按线索词给的候选，允许下游人工或 Agent 复核。
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

import paperkit as pk

# ---------------------------------------------------------------- 文本处理

MARK = "\x00"          # 句点占位符：保护缩写/小数/姓名首字母，切句后还原
PROTECT = [
    (re.compile(r"\b(e\.g|i\.e|et al|Fig|Figs|Eq|Eqs|Ref|Refs|Sec|Secs|vs|approx|"
                r"Dr|Prof|No|cf|al|resp|etc)\.", re.I), r"\1" + MARK),
    (re.compile(r"(\d)\.(\d)"), r"\1" + MARK + r"\2"),
    (re.compile(r"([A-Z])\.(?=[A-Z]\.)"), r"\1" + MARK),        # 姓名缩写 A. Vaswani
]

SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
CJK_SPLIT = re.compile(r"(?<=[。！？；])")


def split_sentences(text: str):
    """按句切分，保护缩写、小数、姓名首字母，避免把 Fig. 2 或 3.5 拆开。"""
    if not text:
        return []
    t = text
    for pat, rep in PROTECT:
        t = pat.sub(rep, t)
    parts = []
    for chunk in t.split("\n"):
        if pk.cjk_ratio(chunk) > 0.3:
            parts.extend(p for p in CJK_SPLIT.split(chunk) if p.strip())
        else:
            parts.extend(p for p in SENT_SPLIT.split(chunk) if p.strip())
    out = []
    for p in parts:
        p = p.replace(MARK, ".").strip()
        # 中文句更短也承载完整信息，阈值按字符类型分开
        floor = 18 if pk.cjk_ratio(p) > 0.3 else 30
        if len(p) >= floor or (len(p) >= 12 and re.search(r"\d", p)):
            out.append(pk.norm(p))
    return out


STOP = set("""
a an the and or but if then than that this these those of in on at to for from by with as is are was were be been
being it its their our we us they them he she his her you your i not no nor so such can could may might must
shall should will would do does did done have has had into over under about across between within without
which who whom whose what when where why how all any both each few more most other some only own same very
also however therefore thus hence while whereas because since although though yet still just even much many
paper work study article report results result show shows shown presented present propose proposed using used
use based approach method methods model models table figure fig section eq equation appendix algorithm
two three four five one first second third new different large small high low
""".split())

ABBR_RE = re.compile(r"\b([A-Za-z][A-Za-z\-]{2,}(?:\s+[A-Za-z][A-Za-z\-]{2,}){0,3})\s*"
                     r"\(([A-Z][A-Z0-9\-]{1,7})s?\)")
DEF_RE = re.compile(r"\b([A-Z][A-Za-z\-]{2,}(?:\s+[a-z][A-Za-z\-]{1,}){0,2})\s+"
                    r"(?:is|are|refers to|denotes|means|stands for)\s+(?:a|an|the)\s+")

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s,;)}\]]+")

DATA_CUES = re.compile(r"\b(dataset|datasets|corpus|corpora|benchmark|benchmarks|"
                       r"data set|training data|annotated|corpus of)\b", re.I)
METHOD_CUES = re.compile(r"\b(we (?:train|use|apply|fine-?tune|optimize|implement|adopt|"
                         r"introduce|design|build)|our (?:model|method|approach|architecture|"
                         r"framework|algorithm)|architecture|algorithm|objective|loss function|"
                         r"hyperparameter)\b", re.I)
COND_CUES = re.compile(r"\b(assum|under the|setting|condition|constraint|budget|limit(?:ed)? to|"
                       r"only when|requires?|given|provided that|at most|no more than|"
                       r"fixed (?:length|budget)|window|resolution)\w*\b", re.I)
RESULT_CUES = re.compile(r"\b(improv|outperform|achiev|reach|increase|decreas|reduc|gain|"
                         r"better than|higher than|lower than|BLEU|accuracy|F1|perplexity|"
                         r"precision|recall|speed-?up|state[- ]of[- ]the[- ]art)\w*\b|"
                         r"提高|提升|降低|减少|达到|优于|超过|准确率|命中率|成功率|百分点", re.I)
LIMIT_CUES = re.compile(r"\b(limitation|limited|cannot|can not|future work|do not|does not|"
                        r"fail(?:s|ed)? to|remains? (?:an? )?(?:open|unclear|challeng)|"
                        r"drawback|weakness|only (?:on|for|when)|restricted to)\b|"
                        r"局限|不足|未能|无法|有待|未来工作|进一步研究|仅适用", re.I)
RQ_CUES = re.compile(r"\b(we (?:propose|introduce|present|address|study|investigate|examine|ask)|"
                     r"this (?:paper|work|study) (?:studies|investigates|addresses|asks|examines|proposes)|"
                     r"in this (?:paper|work) we (?:propose|study|address)|our goal|the goal of|"
                     r"research question|we focus on)\b|"
                     r"本文(?:研究|提出|关注|讨论|旨在)|本研究|我们提出|旨在|研究问题|目标是", re.I)
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s?%|\s?×|\s?x\b)?")
CUE_BEFORE_NUM = re.compile(r"(BLEU|accuracy|F1|perplexity|precision|recall|points?|"
                            r"percentage|speed|seconds|minutes|hours|GPU|parameters?|tokens?|"
                            r"examples?|samples?|documents?|pages?)", re.I)

ROLE_RULES = [
    ("limitation", LIMIT_CUES),
    ("result", RESULT_CUES),
    ("method", METHOD_CUES),
    ("data", DATA_CUES),
    ("purpose", RQ_CUES),
]

# 这些章节是文献表或致谢，不属于论文内容，记条数但不生成笔记
SKIP_SECTION_RE = re.compile(r"^\s*(?:\d+\.?\s*)?(references|bibliography|文献表|参考文献|"
                             r"acknowledg\w*|致谢)\b", re.I)

STRONG_LIMIT = re.compile(r"\b(limitation|limited (?:to|by)|future work|drawback|weakness|"
                          r"cannot (?:handle|scale|capture)|fails? to|remains? (?:an? )?"
                          r"(?:open|unclear|challeng)\w*|restricted to|"
                          r"we do not|does not (?:support|handle|cover))\b|"
                          r"局限|不足|未能|有待|未来工作|进一步研究", re.I)

COND_TIGHT = re.compile(r"\b(assum\w*|under the (?:setting|condition|constraint|budget)|"
                        r"given (?:that|a|the)|provided that|at most|no more than|"
                        r"budget of|fixed (?:length|budget|window)|window of|resolution of|"
                        r"only when|requires? (?:that|a|the)|depends? on|"
                        r"batch size|learning rate|warmup|dropout|beam size|"
                        r"hyperparameter|configuration|trained? (?:on|with|for) \d|"
                        r"\d+ (?:GPUs?|layers?|heads?|steps?))\b|"
                        r"假设|前提|条件下|预算|不超过|仅限于|窗口|设置", re.I)


def classify(sentence: str) -> str:
    for role, pat in ROLE_RULES:
        if pat.search(sentence):
            return role
    return "other"


def numbers_in(sentence: str):
    out = []
    clean = re.sub(r"\[[0-9,\s\-–]+\]", "", sentence)      # 去掉引用编号，避免把 [13] 当数值
    offset = 0
    for m in NUM_RE.finditer(clean):
        val = m.group(1)
        if len(val) <= 1 and not m.group(2):
            continue
        unit = (m.group(2) or "").strip()
        ctx = clean[max(0, m.start() - 28):m.start()]
        label = ""
        mm = CUE_BEFORE_NUM.search(ctx)
        if mm:
            label = mm.group(1)
        out.append({"value": val, "unit": unit, "label": label,
                    "quote": pk.norm(clean[max(0, m.start() - 40):m.end() + 20])})
    return out[:6]


# ---------------------------------------------------------------- 结构

MATH_CHARS = set("∇∂∑∏∫∞≈≠≤≥∈∉∼∝√±×÷·⋅→←↔⊂⊆∪∩αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩˆ")


def looks_like_math(text: str) -> bool:
    """公式行：符号密、字母占比低、以等号结尾。这类行常被版式误判成标题。"""
    t = text.strip()
    if not t:
        return False
    if sum(1 for ch in t if ch in MATH_CHARS) >= 2:
        return True
    if len(t) >= 8 and sum(ch.isalpha() or ch.isspace() for ch in t) / len(t) < 0.6:
        return True
    return bool(re.search(r"[=:≈≤≥]\s*$", t))


def heading_ok(text: str) -> bool:
    """标题过滤：排除公式、项目符号、小写起头的行内小标题、句号结尾的正文首句。"""
    t = text.strip()
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", t))
    if len(t) < (2 if has_cjk else 3) or len(t) > 100:
        return False
    if re.match(r"^[•·▪◦\-–—*∙]", t):
        return False
    if looks_like_math(t) or t[0].islower():
        return False
    if t.endswith(".") and not re.match(r"^\d", t):
        return False
    if t.count("(") != t.count(")"):
        return False
    return True


def build_blocks(doc):
    """按页取块，保留全文（paperkit 的 blocks 只存前 160 字，笔记需要整句）。"""
    tabs = doc.tables(out_dir=None)
    figs = doc.figures(out_dir=None)
    blocks = []
    for page in doc.pages:
        pno = page.number + 1
        boxes = [tuple(t["bbox"]) for t in tabs if t["page"] == pno]
        boxes += [tuple(f["bbox"]) for f in figs if f["page"] == pno]
        for para in doc.paragraphs(pno, skip_boxes=boxes):
            text = pk.norm(para["text"])
            if not text:
                continue
            math = looks_like_math(text)
            bid = f"p{pno}b{len(blocks) + 1}"
            blocks.append({
                "id": bid, "page": pno, "text": text,
                "heading": bool(para["heading"]) and heading_ok(text) and not math,
                "math": math,
                "level": int(para.get("level") or 0),
                "y0": round(float(para.get("y0") or 0.0), 1),
                "hash": pk.sha256_text(text)[:16],
            })
    return blocks, tabs, figs


def clean_headings(blocks, title=""):
    """统一清理：题名区的大字、摘要里的单个加粗词、项目符号行都不算章节标题。"""
    start = None
    abstract_y = None
    for i, b in enumerate(blocks):
        if b["heading"] and re.match(r"^(abstract|摘要)\b", b["text"], re.I):
            abstract_y = b["y0"]
        if b["heading"] and (re.match(r"^(abstract|摘要)\b", b["text"], re.I) or
                             re.match(r"^1\.?\s+\S", b["text"])):
            start = i
            break
    known = {w.lower() for w in pk.HEADING_WORDS}
    for i, b in enumerate(blocks):
        above_abstract = (abstract_y is not None and b["page"] == 1 and
                          b["y0"] < abstract_y - 1.0 and b["text"] != title)
        if (start is not None and i < start) or above_abstract:
            b["front"] = True                 # 题名、作者、单位：不建章节、不产笔记
            b["heading"] = False
            continue
        if not b["heading"]:
            continue
        words = b["text"].split()
        if len(words) <= 1 and not re.match(r"^\d", b["text"]) \
                and b["text"].strip().lower().strip(".:") not in known:
            b["heading"] = False
    return blocks


def sectionize(blocks):
    """按论文自己的标题切章节：标题层级来自编号与版式，不套模板。"""
    has_heading = any(b["heading"] for b in blocks)
    sections = [{"id": "front",
                 "title": "（题名与摘要之前）" if has_heading else "（全文·未检出章节标题）",
                 "level": 0, "page": blocks[0]["page"] if blocks else 0, "blocks": []}]
    stack = []
    for b in blocks:
        if b["heading"]:
            lvl = b["level"] if b["level"] > 0 else 1
            while stack and stack[-1]["level"] >= lvl:
                stack.pop()
            sec = {"id": f"s{len(sections)}", "title": b["text"], "level": lvl,
                   "page": b["page"], "blocks": [b["id"]], "heading_id": b["id"]}
            sections.append(sec)
            stack.append(sec)
        else:
            (stack[-1] if stack else sections[0])["blocks"].append(b["id"])
    if len(sections) > 1 and not sections[0]["blocks"] and sections[0]["title"].startswith("（"):
        sections = sections[1:]
    return sections


# ---------------------------------------------------------------- 笔记

def note(sentence, block, rule, role=None):
    return {"text": sentence, "rule": rule, "role": role or classify(sentence),
            "anchor": {"page": block["page"], "block": block["id"],
                       "quote": sentence[:200], "hash": block["hash"]}}


def collect(blocks, sections, title=""):
    by_id = {b["id"]: b for b in blocks}
    sec_of = {}
    for s in sections:
        for bid in s["blocks"]:
            sec_of[bid] = s["id"]

    rq, data, cond, findings, limits, section_notes = [], [], [], [], [], {}
    skipped = []
    for s in sections:
        # 题名区与参考文献/致谢不生成笔记：前者是版式信息，后者不是论文内容。
        # 只有存在真正的章节时，"front" 才是题名区；全文无标题时它就是正文本身。
        is_front = s["id"] == "front" and len(sections) > 1
        if is_front or s["title"] == title or SKIP_SECTION_RE.match(s["title"]):
            section_notes[s["id"]] = []
            skipped.append({"section": s["title"], "blocks": len(s["blocks"]),
                            "reason": "front matter" if (is_front or s["title"] == title)
                                      else "references/acknowledgements"})
            continue
        sents = []
        for bid in s["blocks"]:
            b = by_id[bid]
            if b["heading"] or b.get("math"):
                continue
            for sent in split_sentences(b["text"]):
                sents.append((sent, b))
        section_notes[s["id"]] = []
        for sent, b in sents:
            role = classify(sent)
            section_notes[s["id"]].append(note(sent, b, "role_cue", role))
            if RQ_CUES.search(sent) and len(rq) < 3:
                rq.append(note(sent, b, "rq_cue"))
            if DATA_CUES.search(sent) and not STRONG_LIMIT.search(sent) \
                    and not re.match(r"^future work", sent, re.I) and len(data) < 6:
                data.append(note(sent, b, "dataset_cue"))
            if COND_TIGHT.search(sent) and len(cond) < 8:
                cond.append(note(sent, b, "condition_cue"))
            if RESULT_CUES.search(sent) and NUM_RE.search(re.sub(r"\[[0-9,\s\-–]+\]", "", sent)) \
                    and not re.match(r"^(table|figure|fig\.|表|图)\s*\d", sent, re.I) \
                    and len(findings) < 10:
                n = note(sent, b, "number+cue")
                n["numbers"] = numbers_in(sent)
                findings.append(n)
            if STRONG_LIMIT.search(sent) and len(limits) < 8:
                limits.append(note(sent, b, "limitation_cue"))
    return {"research_question": rq, "data": data, "conditions": cond,
            "findings": findings, "limitations": limits,
            "sections": section_notes, "skipped": skipped}


def concepts(blocks):
    """术语表：缩写展开、定义句、高频技术词与复合术语，按归一化键去重。"""
    found = {}

    def add(term, kind, definition, block, count=1):
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", term.lower())
        if len(key) > 4 and key.endswith("s") and not key.endswith("ss"):
            key = key[:-1]                       # 复数与单数合并：sub-layer / sub-layers
        if not key or key in STOP or len(key) < 3:
            return
        rec = found.get(key)
        if rec:
            rec["count"] += count
            if definition and not rec.get("definition"):
                rec["definition"] = definition
            return
        found[key] = {"term": term.strip(), "key": key, "kind": kind,
                      "definition": definition, "count": count,
                      "anchor": {"page": block["page"], "block": block["id"],
                                 "quote": pk.norm(definition or term)[:200],
                                 "hash": block["hash"]}}

    for b in blocks:
        for m in ABBR_RE.finditer(b["text"]):
            add(m.group(1), "abbreviation", f"{m.group(1)} ({m.group(2)})", b)
        for m in DEF_RE.finditer(b["text"]):
            subject = m.group(1).strip()
            start = m.start()
            end = b["text"].find(".", m.end())
            definition = b["text"][start:end + 1] if end > 0 else subject
            if len(definition) > 220 or len(subject.split()) > 4:
                continue
            if subject.split()[0].lower() in ("the", "this", "that", "these", "those",
                                              "another", "each", "one", "our", "their",
                                              "there", "it"):
                continue
            if subject.split()[0].lower().endswith("ing"):     # 动名词开头是句子，不是术语
                continue
            add(subject, "definition", definition, b)

    # 高频词与复合术语：只保留高辨识度的形态——缩写、连字符复合词、句中大写词
    text_all = "\n".join(b["text"] for b in blocks)
    ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
    HYPHEN = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")
    MIDCAP = re.compile(r"(?<=[a-z,;]\s)([A-Z][a-z]{2,})\b")
    SKIP_ACR = {"THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM", "OUR", "ALL", "NOT"}

    def first_block_of(word):
        for b in blocks:
            if word in b["text"]:
                return b
        return blocks[0]

    for word, c in Counter(m.group(0) for m in ACRONYM.finditer(text_all)).most_common(40):
        if c >= 2 and word not in SKIP_ACR:
            add(word, "acronym", "", first_block_of(word), c)
    for word, c in Counter(m.group(0) for m in HYPHEN.finditer(text_all)).most_common(40):
        if c >= 3:
            add(word, "compound", "", first_block_of(word), c)

    # 中文术语：反复出现的 3–4 字组合，去掉含虚词的候选，并去掉被更长术语包含的片段
    CJK_STOP = set("的了是在和与及等我们这那有为对以其把被从到而并且或")
    grams = Counter()
    for run in re.findall(r"[\u4e00-\u9fff]{2,12}", text_all):
        for n in (5, 4, 3):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if any(ch in CJK_STOP for ch in g):
                    continue
                grams[g] += 1
    picked = []
    for g, c in sorted(grams.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        if c < 3:
            continue
        if any(g in p or p in g for p in picked):
            continue
        picked.append(g)
    for g in picked[:20]:
        add(g, "cjk_term", "", first_block_of(g), grams[g])

    out = list(found.values())
    out.sort(key=lambda d: (-d["count"], d["term"].lower()))
    return out[:60]


def fallback_title(doc) -> str:
    """detect_title 失败时（题名字号被页脚戳记盖过等）按首页最大字号回收。"""
    first = [l for l in doc.lines if l["page"] == 1]
    cands = [l for l in first if len(l["text"]) > 10 and not pk.BAD_TITLE.search(l["text"])]
    if not cands:
        return ""
    best = max(l["size"] for l in cands)
    cands = sorted([l for l in cands if abs(l["size"] - best) < 0.6], key=lambda l: l["y0"])
    parts = [cands[0]["text"]]
    for nxt in cands[1:]:
        if nxt["y0"] - cands[0]["y0"] < 60:
            parts.append(nxt["text"])
    return pk.norm(" ".join(parts))[:300]


def meta(blocks, doc):
    """题录信息从首页原始文本取：解析器会剔除页脚的 arXiv 戳与会议行，但题录要用。"""
    raw = doc.pages[0].get_text() if doc.pages else ""
    if doc.page_count > 1:
        raw += "\n" + doc.pages[1].get_text()

    venue_years, other_years = [], []
    for line in raw.splitlines():
        if re.match(r"^\s*arXiv:", line, re.I):        # arXiv 戳记里的日期是版本日期，不是发表年
            continue
        venue = bool(re.search(r"conference|proceedings|journal|symposium|workshop|"
                               r"submitted|published|©|copyright|nips|neurips|acl|emnlp|"
                               r"iclr|icml|aaai|ieee|acm|springer|elsevier", line, re.I))
        for y in YEAR_RE.findall(line):
            y = int(y)
            if 1950 <= y <= 2026:
                (venue_years if venue else other_years).append(y)

    arx = ARXIV_RE.search(raw) or ARXIV_RE.search(" ".join(b["text"] for b in blocks[:200]))
    doi = DOI_RE.search(raw)

    if venue_years:
        year = str(max(venue_years))
    elif arx:
        yy = int(arx.group(1)[:2])
        year = str(2000 + yy) if yy < 90 else str(1900 + yy)
    else:
        year = str(max(other_years)) if other_years else ""

    authors = re.sub(r"[\s∗†‡\*¶§]+$", "", doc.detect_authors() or "")
    name_re = re.compile(r"^[A-Z][a-z\u00c0-\u017f\-]+\s+[A-Z][a-z\u00c0-\u017f\-]+[\s∗†‡\d\*,]*$")
    if authors:
        idx = next((i for i, b in enumerate(blocks) if authors.split()[0] in b["text"]), 0)
        extra = [b["text"] for b in blocks[idx + 1:idx + 12] if name_re.match(b["text"])]
        if extra:
            authors = f"{authors} 等（首页另见 {len(extra)} 位作者）"
    else:
        names = [b["text"] for b in blocks if b.get("front") and name_re.match(b["text"])]
        if names:
            authors = names[0]
            if len(names) > 1:
                authors += f" 等（首页另见 {len(names) - 1} 位作者）"
        else:
            for b in blocks:
                if not b.get("front"):
                    continue
                t = b["text"]
                if 4 <= len(t) <= 60 and re.fullmatch(r"[\u4e00-\u9fff、，,\s（）()·A-Za-z0-9\.\-]+", t) \
                        and re.search(r"[\u4e00-\u9fff]{2,4}[、，]", t):
                    authors = t
                    break

    return {
        "title": doc.detect_title() or fallback_title(doc),
        "authors": authors,
        "year": year,
        "arxiv": arx.group(1) if arx else "",
        "doi": doi.group(0).rstrip(".") if doi else "",
        "pages": doc.page_count,
    }


LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
             "\u00a0": " ", "\u2009": " ", "\u202f": " "}


def _cmp_text(s: str) -> str:
    for k, v in LIGATURES.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def anchor_check(notes, by_id):
    checked = valid = 0
    bad = []
    for group in notes.values():
        if not isinstance(group, list):
            continue
        for n in group:
            if not isinstance(n, dict) or "anchor" not in n:
                continue
            checked += 1
            b = by_id.get(n["anchor"]["block"])
            q = _cmp_text(n["anchor"]["quote"])
            if b and q and q in _cmp_text(b["text"]):
                valid += 1
            else:
                bad.append({"block": n["anchor"]["block"],
                            "page": n["anchor"]["page"],
                            "quote": q[:90],
                            "block_text": (b["text"][:140] if b else "<block not found>")})
    return checked, valid, bad[:3]


def build_index(blocks):
    idx = defaultdict(set)
    for b in blocks:
        toks = re.findall(r"[a-z][a-z\-]{2,}", b["text"].lower())
        for t in toks:
            if t not in STOP:
                idx[t].add(b["id"])
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", b["text"]):
            for i in range(len(run) - 1):
                idx[run[i:i + 2]].add(b["id"])
    return {k: sorted(v) for k, v in sorted(idx.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:4000]}


# ---------------------------------------------------------------- 渲染

def render_md(m, sections, notes, conc, check, blocks_by_id):
    L = []
    L.append(f"# 论文笔记：{m['title'] or '（未识别题名）'}")
    L.append("")
    L.append("> 本笔记全部条目都是原文句子摘录，附页码与块号；块号可在 `notes.json`/`index.json` 中回查。"
             "角色标签（目的/方法/结果/局限）是按线索词给的候选，需人工复核。")
    L.append("")
    L.append("## 论文卡片")
    L.append("")
    L.append("| 字段 | 内容 | 依据 |")
    L.append("|---|---|---|")
    L.append(f"| 题名 | {m['title'] or '—'} | 版式首块 |")
    L.append(f"| 作者 | {m['authors'] or '—'} | 版式首块 |")
    L.append(f"| 年份 | {m['year'] or '—'} | 首页文本 |")
    L.append(f"| arXiv | {m['arxiv'] or '—'} | 首页文本 |")
    L.append(f"| DOI | {m['doi'] or '—'} | 首页文本 |")
    L.append(f"| 页数 / 章节 | {m['pages']} 页 / {len(sections)} 节 | 解析结果 |")
    L.append("")
    L.append("## 结构（与原文标题一致）")
    L.append("")
    for s in sections:
        rows = len(notes["sections"].get(s["id"], []))
        indent = "  " * max(0, min(3, s["level"] - 1))
        mark = ""
        if any(k["section"] == s["title"] for k in notes.get("skipped", [])):
            mark = "（不生成笔记）"
        L.append(f"{indent}- `{s['id']}` {s['title']}（p{s['page']}，{len(s['blocks'])} 块，{rows} 条笔记）{mark}")
    L.append("")
    L.append("## 章节笔记")
    for s in sections:
        rows = notes["sections"].get(s["id"], [])
        if not rows:
            continue
        title = s["title"]
        if len(rows) < 3:                      # 太少的节只留一行，细节在 notes.json
            L.append("")
            L.append(f"### {title}（p{s['page']}）")
            L.append(f"- 本节仅 {len(rows)} 条可摘录句，未展开：{'；'.join(r['text'][:90] for r in rows)}")
            continue
        L.append("")
        L.append(f"### {title}（p{s['page']}）")
        for role in ("purpose", "method", "data", "result", "limitation", "other"):
            hits = [r for r in rows if r["role"] == role][:4]
            if not hits:
                continue
            label = {"purpose": "目的", "method": "方法", "data": "数据",
                     "result": "结果", "limitation": "局限", "other": "陈述"}[role]
            L.append(f"- **{label}**")
            for r in hits:
                L.append(f"  - {r['text']} `[{r['anchor']['block']} · p{r['anchor']['page']}]`")
    L.append("")
    L.append("## 关键发现（含数值）")
    L.append("")
    if notes["findings"]:
        L.append("| # | 原文摘录 | 数值 | 位置 |")
        L.append("|---|---|---|---|")
        for i, f in enumerate(notes["findings"], 1):
            nums = "; ".join(f"{n['label'] + ' ' if n['label'] else ''}{n['value']}{n['unit']}"
                             for n in f.get("numbers", [])) or "—"
            L.append(f"| {i} | {f['text'][:160]} | {nums} | {f['anchor']['block']} p{f['anchor']['page']} |")
    else:
        L.append("（未检出含数值的结果句；见 `check.json` 的字段覆盖）")
    L.append("")
    L.append("## 研究问题")
    L.append("")
    for r in notes["research_question"]:
        L.append(f"- {r['text']} `[{r['anchor']['block']} · p{r['anchor']['page']}]`")
    L.append("")
    L.append("## 数据与材料")
    L.append("")
    for r in notes["data"]:
        L.append(f"- {r['text']} `[{r['anchor']['block']} · p{r['anchor']['page']}]`")
    L.append("")
    L.append("## 前提与条件（结论成立的范围）")
    L.append("")
    for r in notes["conditions"]:
        L.append(f"- {r['text']} `[{r['anchor']['block']} · p{r['anchor']['page']}]`")
    L.append("")
    L.append("## 局限与未决")
    L.append("")
    for r in notes["limitations"]:
        L.append(f"- {r['text']} `[{r['anchor']['block']} · p{r['anchor']['page']}]`")
    L.append("")
    L.append("## 知识点（术语 / 缩写）")
    L.append("")
    L.append("| 术语 | 类型 | 次数 | 定义或首次出现 | 位置 |")
    L.append("|---|---|---|---|---|")
    for c in conc[:30]:
        L.append(f"| {c['term']} | {c['kind']} | {c['count']} | "
                 f"{(c['definition'] or '')[:90]} | {c['anchor']['block']} p{c['anchor']['page']} |")
    L.append("")
    L.append("## 自查")
    L.append("")
    L.append(f"- 锚点校验：{check['anchor_valid']}/{check['anchor_checked']} 条摘录能在对应块中逐字命中；")
    L.append(f"- 字段覆盖：{', '.join(k for k, v in check['field_coverage'].items() if v) or '无'}；")
    L.append(f"- 未覆盖：{', '.join(k for k, v in check['field_coverage'].items() if not v) or '无'}。")
    L.append("")
    return "\n".join(L)
