#!/usr/bin/env python3
"""nanoextract.py — 第一步：把论文切成"可独立判断真假"的候选断言，并保住原文位置。

确定性脚本，不调用模型。做三件事：
  1. 版面解析：按段落/标题/题注/表格行抽出 source 单元（每单元带页码、章节、类型、锚点）；
  2. 句子级切分 + 复合句拆解：把并列、转折、因果的复合句拆成更小的可选断言单位；
  3. 语言线索标注：模糊限定、绝对化、否定、条件、量化、比较、数值、模态、归属——
     这些线索决定"这句话能不能被当成无条件的断言"，是后面核验过宽/丢条件的依据。

产出（默认写 /app/work）：
  sources.json      全部 source 单元（原文逐字 + 位置 + 锚点 + sha256）
  candidates.jsonl  每条候选断言一行，带 cand_id / 位置 / 线索 / 关系提示
  candidates.md     人（或 Agent）读的版本：每条候选附"必须原样引用"和线索说明
  context.json      论文级元数据（标题、作者、年份线索、章节树、来源文件指纹）
  prep.json         统计与告警（页数、source 数、候选数、跳过页）
  prep_check.json   自检（空句、跨页断句、锚点缺失）

用法：
  python nanoextract.py --case /input/case.json --out /app/work [--pdf path] [--max-pages 60]
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

# ---------------------------------------------------------------- 线索词表

HEDGE = [
    "may", "might", "could", "can", "possibly", "perhaps", "likely", "unlikely",
    "suggest", "suggests", "suggested", "appear", "appears", "appeared", "seem", "seems",
    "tend", "tends", "typically", "generally", "usually", "often", "sometimes",
    "often", "in some cases", "probably", "presumably", "approximately", "about",
    "roughly", "on average", "in part", "relatively", "somewhat", "tendency",
    "可能", "或许", "大概", "往往", "通常", "一般", "倾向", "似乎", "看似", "大致", "约",
]
ABSOLUTE = [
    "prove", "proves", "proven", "demonstrate", "demonstrates", "establish", "establishes",
    "always", "never", "all", "none", "every", "completely", "entirely", "definitively",
    "conclusively", "unambiguously", "must", "certainly", "undoubtedly", "clearly shows",
    "证明", "证实", "必然", "完全", "绝对", "毫无疑问", "总是", "从不", "唯一", "确凿",
]
NEGATION = [
    "not", "no", "never", "none", "neither", "nor", "without", "cannot", "can't", "didn't",
    "doesn't", "don't", "isn't", "wasn't", "aren't", "lack", "lacks", "failed to", "unable",
    "不", "无", "未", "没有", "并未", "并非", "没", "非",
]
CONDITION = [
    "if", "when", "whenever", "under", "provided", "assuming", "given that", "in the presence of",
    "in the absence of", "at ph", "at room temperature", "after", "before", "during", "upon",
    "for samples", "for cells", "in the range", "below", "above", "depending on", "unless",
    "条件", "当", "若", "在…条件下", "在", "随着", "低于", "高于", "取决于", "仅当",
]
QUANTIFIER = [
    "all", "most", "many", "several", "some", "few", "none", "both", "each", "every",
    "majority", "minority", "part of", "subset", "significant", "significantly",
    "全部", "大多数", "许多", "若干", "少数", "每个", "显著",
]
COMPARATIVE = [
    "higher", "lower", "greater", "smaller", "larger", "more", "less", "fewer", "better",
    "worse", "faster", "slower", "stronger", "weaker", "increase", "increased", "decrease",
    "decreased", "reduce", "reduced", "enhance", "enhanced", "improve", "improved",
    "outperform", "exceed", "compared with", "compared to", "than", "relative to",
    "更", "较高", "较低", "增加", "减少", "提升", "降低", "优于", "相比",
]
MODAL = [
    "should", "would", "must", "need", "require", "requires", "be expected", "is expected",
    "应", "需要", "必须", "预期",
]
ATTRIBUTION = [
    "et al", "according to", "reported", "have shown", "has shown", "previous studies",
    "prior work", "it was found", "we report", "we show", "we demonstrate", "we found",
    "据", "文献", "已有研究", "前人", "本文",
]
CAUSAL = [
    "because", "since", "due to", "as a result", "therefore", "thus", "hence", "owing to",
    "leads to", "results in", "causes", "caused", "attributed to", "driven by", "enables",
    "因为", "由于", "因此", "所以", "导致", "使得", "源于",
]
CONTRAST = ["but", "however", "whereas", "while", "although", "though", "yet", "in contrast",
            "nevertheless", "而", "但是", "然而", "虽然", "尽管"]

# 非断言：方法/致谢/引用罗列/纯结构句
NON_CLAIM = [
    r"^(we|authors?|this (paper|study|work|section|article))\b.{0,40}\b(describe|present|organi[sz]e|introduce|discuss|report the (structure|outline))\b",
    r"^(the )?(rest|remainder|following) (of )?(this|the) (paper|article|section)\b",
    r"\b(supplementary|supporting) (information|material|note)\b",
    r"^(see|refer to)\b",
    r"^(we|i) thank\b",
    r"^(this work was|this research was) (supported|funded)\b",
    r"^(figure|fig\.?|table|eq\.?|equation|scheme)\s*\d+\s*[.:]?\s*$",
    r"^\s*(acknowledg|references|bibliography|author contributions|conflicts? of interest|data availability|funding)\b",
    r"^(本文|文章)(组织|结构|介绍|如下)",
    r"^(参见|详见)",
]

# 关系受控词表（可被 references/relation_vocab.json 覆盖/扩展）
DEFAULT_RELATIONS = {
    "increase": ["increase", "increased", "increases", "enhance", "enhanced", "improve",
                 "improved", "higher", "promote", "boost", "raise", "gains", "growth"],
    "decrease": ["decrease", "decreased", "decreases", "reduce", "reduced", "lower",
                 "suppress", "inhibit", "retard", "loss", "decline", "drop"],
    "no_effect": ["no (significant )?(change|difference|effect)", "unchanged", "comparable",
                  "similar", "comparable to", "not affected", "independent of"],
    "cause": ["cause", "causes", "lead to", "leads to", "result in", "results in", "due to",
              "drive", "drives", "induce", "induces", "trigger", "responsible for"],
    "correlate": ["correlate", "correlates", "associated with", "correlation", "covary",
                  "track with", "accompanied by"],
    "measure": ["measured", "determined", "calculated", "estimated", "quantified", "obtained",
                "recorded", "observed a value", "is"],
    "compare": ["compared with", "compared to", "than", "versus", "vs", "relative to",
                "outperform", "exceed"],
    "require": ["require", "requires", "needed", "necessary", "depends on", "dependent on",
                "relies on", "prerequisite"],
    "compose": ["consist of", "consists of", "composed of", "comprises", "contains",
                "is a", "is an", "belongs to", "part of"],
    "method_of": ["using", "by means of", "via", "through", "prepared by", "measured by",
                  "synthesized by"],
}

# 谓词线索：有这些词才像"可以判断真假的一句话"
PREDICATE = [
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "shows", "show",
    "found", "find", "reports", "report", "observed", "observe", "measured", "measure",
    "increase", "increased", "decrease", "decreased", "reduce", "reduced", "improve",
    "improved", "require", "requires", "depends", "depend", "consist", "consists",
    "contain", "contains", "allow", "allows", "enable", "enables", "limit", "limits",
    "compare", "compared", "outperform", "exceed", "differ", "differs", "cause", "causes",
    "lead", "leads", "result", "results", "remains", "remain", "grows", "grow", "maintains",
    "达到", "表明", "显示", "发现", "测得", "提高", "降低", "增加", "减少", "取决", "包含",
    "需要", "允许", "限制", "导致", "高于", "低于", "优于", "保持", "存在", "具有", "为",
]
AFFIL_RE = re.compile(r"(universit|institut|department|laborator|college|academy|school|"
                      r"center|centre|hospital|@\w+\.\w+)", re.IGNORECASE)
SENT_END = re.compile(r"[.!?。！？]\s*$")

SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])\s*|(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff(])|(?<=[.!?])$")
CLAUSE_SPLIT_RE = re.compile(
    r"\s*(?:,\s*(?=(?:and|but|whereas|while|which|and the|and it)\b)|;\s*|\s+but\s+|\s+whereas\s+|\s+while\s+"
    r"|\s+and\s+(?=[a-z]{3,}\s)|\s+然而\s*|；|，而)\s*", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def looks_meta(text, authors=""):
    """作者/单位/脚注一类的版面元信息：不是断言候选。"""
    t = pk.norm(text)
    if not t:
        return True
    if AFFIL_RE.search(t):
        return True
    if authors and pk.norm(authors).lower() in t.lower() and not SENT_END.search(t):
        return True
    words = t.split()
    if len(words) <= 30 and not SENT_END.search(t):
        caps = sum(1 for w in words if w[:1].isupper() or re.match(r"^[\u4e00-\u9fff]{2,4}$", w))
        if caps >= 2 and not re.search(r"\b(is|are|was|were|shows?|found|report|use[sd]?|we)\b",
                                       t, re.IGNORECASE):
            return True
    return False


def looks_like_claim(text, kind="body"):
    """是否是"带谓词、能判断真假"的一句话（只判形态，不判语义）。

    返回 (verdict, note)：verdict=False 表示不像断言（会被标记）；
    note 记录"形态可疑但保留"的原因，供人工一眼看见。
    """
    t = pk.norm(text)
    if not t:
        return False, "empty"
    words = re.findall(r"[A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-']*", t)
    if kind == "table_row":
        cells = [c for c in t.split("|") if c.strip()]
        return (len(cells) >= 2, None if len(cells) >= 2 else "too_few_cells")
    note = None
    if re.match(r"^[a-z]", t):
        note = "mid_sentence_start"       # 多半是排版折行断句，需回上一句看上下文
    if kind in ("caption", "figure"):
        return True, note                 # 题注天然短，不按词数卡
    if len(words) < 5:
        return False, "too_few_words"
    low = " " + t.lower() + " "
    if any(re.search(r"(?<![\w])" + re.escape(w.lower()) + r"(?![\w])", low) for w in PREDICATE):
        return True, note
    # 兜底：形如第三人称单数/过去式的谓词（stresses / reported / reduced …）
    if re.search(r"\b[A-Za-z]{4,}(?:s|es|ed)\b", t):
        return True, note
    if re.search(r"[\u4e00-\u9fff]{1,3}(达到|表明|显示|测得|提高|降低|增加|减少|取决|包含|需要|"
                 r"允许|限制|导致|高于|低于|优于|保持|存在|具有)", t):
        return True, note
    return False, "no_predicate"



def load_vocab():
    """优先读 references/relation_vocab.json，读不到就用内置表。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "references", "relation_vocab.json"),
                 os.path.join(os.getcwd(), "references", "relation_vocab.json")):
        if os.path.exists(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    vocab = json.load(f)
                rel = vocab.get("relations") if isinstance(vocab, dict) else None
                if isinstance(rel, dict) and rel:
                    return {k: list(v) for k, v in rel.items()}
            except Exception:
                pass
    return {k: list(v) for k, v in DEFAULT_RELATIONS.items()}


def split_sentences(text):
    """带偏移量的句子切分：返回 [(sent, start, end)]，偏移相对 text。"""
    out, pos = [], 0
    for m in SENT_SPLIT_RE.finditer(text or ""):
        piece = text[pos:m.end()]
        if piece.strip():
            out.append((pk.norm(piece), pos, m.end()))
        pos = m.end()
    if pos < len(text or "") and text[pos:].strip():
        out.append((pk.norm(text[pos:]), pos, len(text)))
    return out


def split_compound(sent, start):
    """复合句拆解：按并列/转折/分号切成分句，保留各自偏移。

    只有当**每一片都还是独立的一句**（首字母大写或中文、不是以连词开头、≥5 词、有谓词）
    才认为拆分有意义；否则原样返回，避免切出 "order, line joining" 这类碎片。
    """
    pieces, pos = [], 0
    for m in CLAUSE_SPLIT_RE.finditer(sent):
        piece = sent[pos:m.start()]
        if piece.strip():
            pieces.append((pk.norm(piece), start + pos, start + m.start()))
        pos = m.end()
    if pos < len(sent) and sent[pos:].strip():
        pieces.append((pk.norm(sent[pos:]), start + pos, start + len(sent)))
    if len(pieces) < 2:
        return [(pk.norm(sent), start, start + len(sent))]
    for piece, _, _ in pieces:
        if re.match(r"^(and|but|while|whereas|which|that|or|以及|并且|而且)\b", piece, re.IGNORECASE):
            return [(pk.norm(sent), start, start + len(sent))]
        if not re.match(r"^[A-Z0-9\u4e00-\u9fff]", piece):
            return [(pk.norm(sent), start, start + len(sent))]
        ok, _ = looks_like_claim(piece)
        if not ok:
            return [(pk.norm(sent), start, start + len(sent))]
    return pieces


def cues(sent):
    low = " " + sent.lower() + " "
    def hit(words):
        return [w for w in words if re.search(r"(?<![\w])" + re.escape(w.lower()) + r"(?![\w])", low)]
    return {
        "hedges": hit(HEDGE),
        "absolutes": hit(ABSOLUTE),
        "negation": bool(hit(NEGATION)),
        "negation_words": hit(NEGATION)[:5],
        "conditions": hit(CONDITION)[:6],
        "quantifiers": hit(QUANTIFIER)[:6],
        "comparatives": hit(COMPARATIVE)[:8],
        "modals": hit(MODAL)[:4],
        "attribution": hit(ATTRIBUTION)[:4],
        "causal": hit(CAUSAL)[:4],
        "contrast": hit(CONTRAST)[:4],
        "numbers": [n.strip() for n in pk.NUM_RE.findall(sent) if re.search(r"\d", n)][:10],
    }


def relation_hints(sent, vocab):
    low = sent.lower()
    hits = []
    for rel, words in vocab.items():
        for w in words:
            if re.search(r"(?<![\w])" + re.escape(w.lower()) + r"(?![\w])", low):
                hits.append(rel)
                break
    return hits


def is_non_claim(sent):
    for pat in NON_CLAIM:
        if re.search(pat, sent.strip(), re.IGNORECASE):
            return pat
    return None


def claim_type(section, kind, sent, c):
    s = (section or "").lower()
    if kind in ("caption", "figure"):
        return "figure_claim"
    if kind == "table_row":
        return "measurement"
    if "abstract" in s:
        return "summary_claim"
    if "conclusion" in s or "discussion" in s:
        return "conclusion_claim"
    if "method" in s or "experimental" in s or "materials" in s:
        return "method_claim"
    if c["causal"]:
        return "causal_claim"
    if c["comparatives"]:
        return "comparative_claim"
    if c["numbers"]:
        return "measurement"
    return "result_claim"


def claim_score(sent, kind, c):
    """0~1：越高越值得成为一条断言候选。"""
    n_words = len(re.findall(r"[A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-']*", sent))
    score = 0.35
    if kind in ("body", "abstract", "caption", "table_row"):
        score += 0.15
    if c["numbers"]:
        score += 0.15
    if c["comparatives"]:
        score += 0.12
    if c["causal"]:
        score += 0.1
    if c["negation"]:
        score += 0.05
    if c["hedges"]:
        score += 0.05
    if n_words >= 8:
        score += 0.15
    if n_words >= 25:
        score -= 0.15          # 太长的句子多半是复合句，应继续拆
    if n_words < 5:
        score -= 0.3
    return round(max(0.0, min(1.0, score)), 3)


def build_sources(pdf_path, max_pages):
    doc = pk.PDFDoc(pdf_path, max_pages=max_pages)
    warnings = list(doc.warnings)
    skipped, sources = [], []
    section = ""
    for pno in range(1, doc.page_count + 1):
        boxes = []
        try:
            rows_by_table = doc.tables(out_dir=None)
        except Exception:
            rows_by_table = []
        from collections import defaultdict
        for t in (rows_by_table or []):
            if t.get("page") == pno and t.get("bbox"):
                boxes.append(tuple(t["bbox"]))
        try:
            paras = doc.paragraphs(pno, skip_boxes=boxes or None)
        except Exception as exc:
            warnings.append(f"page {pno}: paragraph extraction failed ({exc})")
            paras = []
        if not paras:
            skipped.append({"page": pno, "reason": "no_text_layer"})
            warnings.append(f"page {pno}: no extractable text (scanned?)")
            continue
        idx = 0
        headings_on_page = []
        for p in paras:
            text = p["text"]
            if not text:
                continue
            idx += 1
            if p.get("heading"):
                section = text
                headings_on_page.append((p.get("y0", 0.0), text))
                kind = "heading"
            elif pk.caption_like(text):
                kind = "caption"
            else:
                kind = "body"
            sid = f"p{pno}b{idx}"
            sources.append({
                "src_id": sid, "page": pno, "section": section, "kind": kind,
                "text": text, "chars": len(text),
                "anchor": pk.anchor(pno, text, kind="text" if kind != "caption" else "caption", block=sid),
                "sha256_16": pk.sha256_text(text),
            })
        # 表格行也作为 source（它们通常是可判断真假的测量断言）
        for t_i, t in enumerate(rows_by_table or [], start=1):
            if t.get("page") != pno:
                continue
            t_y = (t.get("bbox") or [0, 0, 0, 0])[1]
            t_sec = [s for y, s in headings_on_page if y <= t_y]
            t_section = t_sec[-1] if t_sec else section
            for r_i, row in enumerate(t.get("rows") or [], start=1):
                cells = [pk.norm(str(c)) for c in row if str(c).strip()]
                if len(cells) < 2:
                    continue
                text = " | ".join(cells)
                sid = f"p{pno}t{t_i}r{r_i}"
                sources.append({
                    "src_id": sid, "page": pno, "section": t_section, "kind": "table_row",
                    "text": text, "chars": len(text),
                    "anchor": pk.anchor(pno, text, kind="table", block=sid),
                    "sha256_16": pk.sha256_text(text),
                })
    meta = {
        "title": doc.detect_title(),
        "authors": doc.detect_authors(),
        "page_count": doc.page_count,
        "skipped_pages": skipped,
        "warnings": warnings,
    }
    return doc, sources, meta


def build_candidates(sources, vocab, authors=""):
    cands, self_check = [], []
    for s in sources:
        if s["kind"] in ("heading",):
            continue
        if looks_meta(s["text"], authors):
            self_check.append({"src_id": s["src_id"], "issue": "skipped_meta_block",
                               "text": s["text"][:60]})
            continue
        for si, (sent, st, en) in enumerate(split_sentences(s["text"]), start=1):
            if len(sent) < 8:
                self_check.append({"src_id": s["src_id"], "issue": "very_short_segment",
                                   "text": sent[:60]})
                continue
            bad = is_non_claim(sent)
            ok_shape, shape_reason = looks_like_claim(sent, s["kind"])
            for ci, (piece, pst, pen) in enumerate(split_compound(sent, st), start=1):
                c = cues(piece)
                cid = f"{s['src_id']}s{si}" + (f"c{ci}" if ci > 1 else "")
                ok_piece, note = looks_like_claim(piece, s["kind"])
                reason = bad if (bad and ci == 1) else (None if ok_piece else note)
                cands.append({
                    "cand_id": cid,
                    "src_id": s["src_id"], "page": s["page"], "section": s["section"],
                    "kind": s["kind"],
                    "sent_index": si, "clause_index": ci,
                    "char_start": pst, "char_end": pen,
                    "text": piece,
                    "split_of": f"{s['src_id']}s{si}" if ci > 1 else None,
                    "cues": c,
                    "relation_hints": relation_hints(piece, vocab),
                    "claim_type": claim_type(s["section"], s["kind"], piece, c),
                    "claim_score": claim_score(piece, s["kind"], c),
                    "non_claim_pattern": reason,
                    "shape_note": note if ok_piece else None,
                })
    return cands, self_check


def write_md(cands, sources, path, tgt_lang="zh"):
    by_id = {s["src_id"]: s for s in sources}
    lines = ["# 候选断言清单（第一步产出）", "",
             "规则：**每条候选只能引用同一 src_id 的原文片段**作证据；`text` 即原文逐字内容，"
             "不要改写后再当证据引用；`char_start/char_end` 是该片段在本 source 内的字符偏移。", ""]
    for c in cands:
        s = by_id.get(c["src_id"], {})
        lines.append(f"## {c['cand_id']}　第 {c['page']} 页　{c['section'] or '—'}　{c['kind']}　"
                     f"类型 {c['claim_type']}　评分 {c['claim_score']}")
        lines.append("")
        lines.append("```text")
        lines.append(c["text"])
        lines.append("```")
        cues = c["cues"]
        notes = []
        if cues["hedges"]:
            notes.append("模糊限定: " + ", ".join(cues["hedges"][:4]) + "（断言不得写成无条件的结论）")
        if cues["absolutes"]:
            notes.append("绝对化用词: " + ", ".join(cues["absolutes"][:4]))
        if cues["negation"]:
            notes.append("含否定: " + ", ".join(cues["negation_words"]))
        if cues["conditions"]:
            notes.append("条件/范围: " + ", ".join(cues["conditions"]))
        if cues["quantifiers"]:
            notes.append("量化: " + ", ".join(cues["quantifiers"]))
        if cues["comparatives"]:
            notes.append("比较: " + ", ".join(cues["comparatives"][:5]))
        if cues["numbers"]:
            notes.append("数值: " + ", ".join(cues["numbers"]))
        if cues["attribution"]:
            notes.append("归属: " + ", ".join(cues["attribution"]))
        if c["relation_hints"]:
            notes.append("关系提示: " + ", ".join(c["relation_hints"]))
        if c["split_of"]:
            notes.append(f"由 {c['split_of']} 拆出的并列分句")
        if c["non_claim_pattern"]:
            notes.append("**疑似非断言**（方法/结构/致谢类），除非确有结论否则不要保留")
        if c.get("shape_note") == "mid_sentence_start":
            notes.append("**句首是小写**：多半是排版折行切断的句子尾巴，请回上一句取完整上下文")
        elif c.get("shape_note"):
            notes.append(f"形态提示: {c['shape_note']}")
        lines.append("- " + ("；".join(notes) if notes else "无线索"))
        lines.append(f"- 影射证据位置：{s.get('anchor', {}).get('page', c['page'])} 页 / {c['src_id']} / "
                     f"字符 {c['char_start']}–{c['char_end']}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None):
    ap = argparse.ArgumentParser(description="论文 → 候选断言 + 原文位置（确定性）")
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--out", default="/app/work")
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="低于该分的候选仍会写出，但标记 low_priority")
    args = ap.parse_args(argv)

    case, ctx = pk.load_case(args.case)
    src = args.pdf or ctx.get("paper")
    os.makedirs(args.out, exist_ok=True)
    if not src or not os.path.exists(src):
        result = {"status": "failed", "reason": "no_material",
                  "detail": f"case={args.case} paper={src}", "candidate_count": 0}
        with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(json.dumps(result, ensure_ascii=True))
        return 2

    vocab = load_vocab()
    try:
        doc, sources, meta = build_sources(src, args.max_pages)
    except Exception as exc:
        msg, name = str(exc), type(exc).__name__
        if "encrypted" in msg.lower():
            reason, hint = "encrypted_pdf", "PDF 已加密：请提供解密副本，本 Skill 不尝试破解。"
        elif "damaged" in msg.lower() or "cannot open" in msg.lower():
            reason, hint = "damaged_pdf", "文件损坏或不是有效 PDF。"
        else:
            reason, hint = "parse_failed", "版面解析失败：可改用文本版副本重试。"
        result = {"schema": VERSION, "status": "failed", "reason": reason,
                  "detail": f"{name}: {msg}", "hint": hint, "candidate_count": 0,
                  "source_count": 0, "page_count": 0}
        with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(json.dumps(result, ensure_ascii=True))
        return 2

    cands, self_check = build_candidates(sources, vocab)
    for c in cands:
        c["low_priority"] = c["claim_score"] < args.min_score

    first_page_text = " ".join(s["text"] for s in sources[:12])
    years = YEAR_RE.findall(first_page_text) or YEAR_RE.findall(" ".join(s["text"] for s in sources))
    context = {
        "schema": VERSION,
        "source_file": os.path.basename(src),
        "source_path": src,
        "source_sha256": pk.sha256_file(src) if os.path.exists(src) else None,
        "title": meta["title"],
        "authors": meta["authors"],
        "year_candidates": years[:3],
        "page_count": meta["page_count"],
        "sections": sorted({s["section"] for s in sources if s["section"]}),
        "counts": {"sources": len(sources), "candidates": len(cands),
                   "candidates_by_kind": dict(Counter(c["kind"] for c in cands)),
                   "candidates_by_type": dict(Counter(c["claim_type"] for c in cands))},
    }

    with open(os.path.join(args.out, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "source_file": os.path.basename(src),
                   "page_count": meta["page_count"], "sources": sources},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "candidates.jsonl"), "w", encoding="utf-8") as f:
        for c in cands:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    write_md(cands, sources, os.path.join(args.out, "candidates.md"))
    with open(os.path.join(args.out, "context.json"), "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "relation_vocab.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "relations": vocab}, f, ensure_ascii=False, indent=1)

    prep = {
        "schema": VERSION,
        "status": "ok" if cands else "failed",
        "source_file": os.path.basename(src),
        "page_count": meta["page_count"],
        "source_count": len(sources),
        "candidate_count": len(cands),
        "by_kind": dict(Counter(s["kind"] for s in sources)),
        "candidates_by_type": dict(Counter(c["claim_type"] for c in cands)),
        "sections": context["sections"],
        "skipped_pages": meta["skipped_pages"],
        "warnings": meta["warnings"][:20],
        "title": meta["title"], "authors": meta["authors"],
        "year_candidates": context["year_candidates"],
        "outputs": {"sources_json": "sources.json", "candidates_jsonl": "candidates.jsonl",
                    "candidates_md": "candidates.md", "context_json": "context.json",
                    "relation_vocab_json": "relation_vocab.json"},
        "next_step": ("读 candidates.md，逐条决定保留/丢弃并写成 work/assertions.jsonl："
                      "每条含 assertion{subject,relation,object,polarity,conditions,quantifier,statement}、"
                      "evidence{src_id,quote,char_start,char_end,directness}、provenance{...}、"
                      "confidence{basis}；再运行 nanoassemble.py 核验并导出。"),
    }
    if not sources:
        prep["reason"] = "no_text_layer"
        prep["hint"] = ("这份材料抽不出任何文字层（扫描件或图片型 PDF）。本 Skill 不做 OCR："
                        "请先 OCR 或改用带文字层的文本版，不要重跑同一份文件。")
        prep["next_step"] = "材料不可用：换一份带文字层的文件。"
    elif not cands:
        prep["reason"] = "no_candidates"
        prep["hint"] = ("有文字层但没有识别出候选断言。确认文档含结论性陈述；"
                        "若用了 --min-score，可放宽到 0 再跑一次。")
    with open(os.path.join(args.out, "prep.json"), "w", encoding="utf-8") as f:
        json.dump(prep, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "prep_check.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": VERSION, "case_id": ctx.get("case_id"),
                   "checks": self_check[:200]}, f, ensure_ascii=False, indent=1)

    _keys = ["status", "page_count", "source_count", "candidate_count", "candidates_by_type"]
    if prep["status"] != "ok":
        _keys += ["reason", "hint"]
    print(json.dumps({k: prep[k] for k in _keys if k in prep}, ensure_ascii=True))
    return 0 if prep["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
