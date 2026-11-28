#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a deterministic plan.json skeleton from paper.json.

The narrative step still belongs to the model, but everything that can be derived
from the paper — page order, per-slide claims taken from real sentences, figure
and table pages with verbatim captions, evidence anchors with page numbers —
is cheap to derive and easy to get wrong by hand. This script produces a plan
that already validates, so the model only has to sharpen the wording.

Every `evidence[].quote` is verified to be a literal substring of the source
page text; a quote that cannot be verified is dropped and recorded in the report
instead of being invented.

Usage:
  python plan_assist.py paper.json --out plan.json [--case case.json]
                                   [--max-slides 10] [--json assist.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_paper import norm, dehyphen  # noqa: E402

SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")

PRIORITY_SECTIONS = [
    ("problem", ("abstract", "introduction", "background", "motivation")),
    ("method", ("method", "methods", "approach", "methodology", "model",
                "architecture", "framework", "system", "proposed")),
    ("results", ("experiment", "experiments", "evaluation", "results",
                 "analysis", "ablation", "comparison")),
    ("limits", ("limitation", "limitations", "discussion", "conclusion",
                "conclusions", "future work")),
]

CLAIM_VERBS = re.compile(
    r"\b(we|this paper|this work|our|the (?:paper|model|method|approach))\b", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\bF1\b|\bBLEU\b|\baccuracy\b|\bEM\b", re.I)
HEADING_WORD_SET = {
    "abstract", "introduction", "related work", "background", "method",
    "methods", "methodology", "approach", "experiments", "experimental setup",
    "results", "results and discussion", "discussion", "analysis",
    "conclusion", "conclusions", "limitations", "future work", "model",
    "architecture", "framework", "system", "proposed", "evaluation",
    "ablation studies", "training", "pre-training",
}


def load_json(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def page_index(paper):
    """{page_no: normalized text} plus a whitespace-free variant for glued PDFs."""
    pages, flat = {}, {}
    for k, v in (paper.get("page_text") or {}).items():
        try:
            pno = int(k)
        except (TypeError, ValueError):
            continue
        body = norm(v)
        pages[pno] = body
        flat[pno] = re.sub(r"\s+", "", body)
    return pages, flat


def _page_order(pages, hint):
    return sorted(pages, key=lambda p: (abs(p - hint), p))


def find_quote(text, pages, flat, hint=1, min_chars=40):
    """Locate `text` (or a shorter prefix of it) on a real page.

    Returns (page, exact_quote) or None. Nothing is returned unless the string
    really occurs in that page's text, so a returned quote is always verifiable.
    """
    if not text:
        return None
    cand = [text]
    words = text.split()
    for cut in (30, 24, 18, 12, 8):
        if len(words) > cut:
            cand.append(" ".join(words[:cut]))
    seen = set()
    for frag in cand:
        frag = norm(frag).rstrip("…,;:")
        if len(frag) < min_chars and frag is not cand[0]:
            continue
        if len(frag) < 24 or frag in seen:
            continue
        seen.add(frag)
        flat_frag = re.sub(r"\s+", "", frag)
        for pno in _page_order(pages, hint):
            if frag in pages[pno]:
                return pno, frag
        for pno in _page_order(pages, hint):
            if len(flat_frag) >= 24 and flat_frag in flat[pno]:
                return pno, frag
    return None


def sentences(text):
    text = norm(dehyphen(text))
    return [s.strip() for s in SENT_SPLIT.split(text) if len(s.strip()) > 25]


def pick_quote(section, pages, flat, limit=160):
    """Longest verified sentence from the section, anchored to its true page."""
    best = None
    for sent in sentences(section.get("text", "")):
        for cand in ([sent] if len(sent) <= limit
                     else [sent[:limit].rsplit(" ", 1)[0]]):
            hit = find_quote(cand, pages, flat, section.get("page", 1))
            if hit and (best is None or len(hit[1]) > len(best[1])):
                best = hit
    if best:
        return best
    return find_quote(norm(section.get("text", ""))[:limit], pages, flat,
                      section.get("page", 1))


SKIP_SECTIONS = ("references", "reference", "bibliography", "acknowledgments",
                 "acknowledgements", "附录", "参考文献", "致谢")
MIN_SECTION_CHARS = 40
LEAD_NUM_RE = re.compile(r"^\d+(?:\.\d+)+")
URL_RE = re.compile(r"https?://|www\.")


def classify(section):
    low = section["title"].lower().strip(" .:0123456789")
    if any(k in low for k in SKIP_SECTIONS):
        return "other"
    for tag, keys in PRIORITY_SECTIONS:
        for k in keys:
            if k in low:
                return tag
    return "other"


def useful_sections(sections):
    """Drop author fragments and other noise, keep sections worth a slide."""
    out = []
    for s in sections:
        low = s["title"].lower().strip()
        if any(k in low for k in SKIP_SECTIONS):
            continue
        body = (s.get("text") or "").strip()
        if len(body) < MIN_SECTION_CHARS:
            # keep only genuine structural headings with little text
            if not (low.strip(" .:0123456789") in HEADING_WORD_SET
                    or re.match(r"^\d+(\.\d+)?\s", s["title"])
                    or re.match(r"^\d+(?:\.\d+)+", s["title"])):
                continue
        if s["title"].endswith(".") and not re.match(r"^[\d.\s]", s["title"]):
            continue
        out.append(s)
    return out


def best_by_tag(sections):
    """One representative section per narrative role (prefer the fullest one)."""
    out = {}
    for s in sections:
        tag = classify(s)
        if tag == "other":
            continue
        cur = out.get(tag)
        if cur is None:
            out[tag] = s
        else:
            # prefer a level-1 section, then the one with the most body text
            key_new = (0 if s.get("level", 1) == 1 else 1, -len(s.get("text") or ""))
            key_cur = (0 if cur.get("level", 1) == 1 else 1, -len(cur.get("text") or ""))
            if key_new < key_cur:
                out[tag] = s
    return out


CLAUSE_SPLIT = re.compile(r"(?<=[;,])\s+(?=(?:and|but|while|whereas|which|that|yet|so)\b|[A-Z])")


def clause_candidates(sent, limit):
    """Long abstract sentences still yield a usable slide line: cut at a clause."""
    parts = [p for p in CLAUSE_SPLIT.split(sent) if len(p) >= 30]
    out = []
    for p in parts:
        if len(p) <= limit:
            out.append(p)
        else:
            cut = p[:limit].rsplit(" ", 1)[0]
            if len(cut) >= 30:
                out.append(cut)
    return out


def bullets_from(section, pages, flat, n=4, limit=76):
    """Short, verifiable phrases taken from the section's own text."""
    out = []
    for sent in sentences(section.get("text", "")):
        if len(sent) < 30 or URL_RE.search(sent):
            continue
        if LEAD_NUM_RE.match(sent):        # "4.1 GLUE The General ..." 小节标记
            continue
        pieces = [sent] if len(sent.split()) <= 28 else clause_candidates(sent, limit)
        for piece in pieces:
            body = piece if len(piece) <= limit else piece[:limit].rsplit(" ", 1)[0]
            body = body.lstrip("•·-–—*▪ ").strip()
            body = re.sub(r"^\d{1,2}(?=[A-Z])", "", body).strip()   # 上标脚注编号
            if len(body) < 24:
                continue
            # a fragment that starts mid-sentence reads as an accident on a slide
            if body[0].islower() and not re.match(r"^[a-z]+\(|^[A-Z]{2,}", body):
                continue
            # verify the text as it appears in the paper, before adding the cut
            # mark: the ellipsis we append is not in the source and never matches
            if not find_quote(body, pages, flat, section.get("page", 1)):
                continue
            text = body if body == sent else body.rstrip(" ,;:.") + "…"
            if any(text == b["text"] for b in out):
                continue
            out.append({"text": text, "level": 0})
            if len(out) >= n:
                return out
    return out


def claim_from(section, fallback):
    for sent in sentences(section.get("text", "")):
        if CLAIM_VERBS.search(sent) and 40 <= len(sent) <= 170:
            return sent[:150]
    for sent in sentences(section.get("text", "")):
        if 40 <= len(sent) <= 170:
            return sent[:150]
    return fallback


def notes_for(kind, title, evidence):
    """Draft speaker notes: transition + emphasis + likely question."""
    ev = evidence[0] if evidence else {}
    where = ("%s（p.%s）" % (ev.get("label") or ev.get("kind", ""), ev.get("page", ""))
             if ev else "论文正文")
    return ("过渡：上一页交代了背景，这一页落到%s。强调：这里只陈述论文自身给出的"
            "内容，依据见 %s；如有追问，先回到该页原文再回答，不要替作者补充未报告的"
            "实验或数值。" % (title, where))


def fallback_method(sections, taken):
    """A paper often names the method section after its own model (e.g. "BERT")."""
    taken_ids = {id(s) for s in taken}
    cands = []
    for s in sections:
        if id(s) in taken_ids or classify(s) != "other":
            continue
        low = s["title"].lower().strip()
        if any(k in low for k in SKIP_SECTIONS) or len(s.get("text") or "") < 800:
            continue
        if s.get("level", 1) != 1:
            continue
        cands.append(s)
    if not cands:
        return None
    # prefer a section on the early pages (method usually follows related work)
    cands.sort(key=lambda s: (0 if 2 <= s["page"] <= 8 else 1, -len(s.get("text") or "")))
    return cands[0]


def shorten(text, n):
    """Cut at a word boundary and mark the cut, instead of chopping mid-word."""
    text = norm(text)
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (cut or text[:n].rstrip()) + "…"


def build(paper, case, max_slides, want_figures, want_tables):
    meta = paper.get("meta", {})
    pages, flat = page_index(paper)
    sections = paper.get("sections", [])
    figures = paper.get("figures", [])
    tables = paper.get("tables", [])
    title = meta.get("title") or meta.get("pdf_title") or "未命名论文"

    by_tag = best_by_tag(useful_sections(sections))

    slides = []
    warnings = []
    used_quotes = []

    def add(slide):
        slides.append(slide)

    arxiv = ""
    m = re.search(r"(\d{4}\.\d{4,5})", os.path.basename(meta.get("path", "")) or "")
    if m:
        arxiv = "arXiv:%s" % m.group(1)

    add({"id": "s1", "type": "title", "title": title,
         "subtitle": "", "authors": meta.get("authors", ""), "venue": arxiv,
         "takeaway": "", "evidence": []})

    problem = by_tag.get("problem")
    if problem:
        ev = []
        hit = pick_quote(problem, pages, flat)
        if hit:
            ev.append({"page": hit[0], "kind": "section",
                       "label": problem["title"], "quote": hit[1]})
            used_quotes.append(hit)
        add({"id": "s2", "type": "bullets", "kicker": "01 · 问题",
             "title": problem["title"][:58],
             "claim": claim_from(problem, "本页说明论文要解决的问题与动机。"),
             "bullets": bullets_from(problem, pages, flat, 4),
             "notes": notes_for("problem", "研究问题", ev), "evidence": ev})
    else:
        warnings.append("未识别到摘要/引言章节，问题页由模型补写")

    method = by_tag.get("method") or fallback_method(sections, list(by_tag.values()))
    if method:
        ev = []
        hit = pick_quote(method, pages, flat)
        if hit:
            ev.append({"page": hit[0], "kind": "section",
                       "label": method["title"], "quote": hit[1]})
            used_quotes.append(hit)
        add({"id": "s3", "type": "bullets", "kicker": "02 · 方法",
             "title": method["title"][:58],
             "claim": claim_from(method, "本页说明论文采用的方法主线。"),
             "bullets": bullets_from(method, pages, flat, 4),
             "notes": notes_for("method", "方法", ev), "evidence": ev})
    else:
        warnings.append("未识别到方法章节，方法页由模型补写")

    # an overview figure belongs right after the method framing
    def fig_score(f):
        cap = (f.get("caption") or "").lower()
        s = 0
        for kw in ("overview", "architecture", "framework", "illustration",
                   "procedure", "pipeline", "schematic", "workflow", "model"):
            if kw in cap:
                s += 2
        if f.get("label", "").lower().endswith("1"):
            s += 1
        return -s

    figs = sorted(figures, key=fig_score)[:want_figures]
    figs.sort(key=lambda f: f["page"])
    for i, f in enumerate(figs, start=1):
        cap = norm(f.get("caption") or "")
        ev = []
        hit = find_quote(cap[:200], pages, flat, f["page"], min_chars=30)
        if hit:
            ev.append({"page": hit[0], "kind": "figure", "label": f.get("label", ""),
                       "quote": hit[1]})
            used_quotes.append(hit)
        else:
            warnings.append("%s 的图注无法在页文本中逐字定位（evidence 留空，请人工核对）"
                            % (f.get("label") or f.get("id")))
        # the title already carries the caption head: don't repeat it as subtitle
        head = shorten(cap, 60)
        fig_title = (f.get("label") or "图") + "｜" + (head or "论文插图")
        subtitle = ""
        if head and not fig_title.replace("…", "").endswith(head.replace("…", "")):
            subtitle = head
        add({"id": "f%d" % i, "type": "figure", "kicker": "03 · 证据",
             "title": fig_title, "subtitle": subtitle,
             "claim": cap[:120] or "本页展示论文原图，按图注陈述。",
             "figure": {"path": f["image"], "label": f.get("label", ""), "caption": cap,
                        "clip": f.get("clip"), "page_size": f.get("page_size")},
             "bullets": [],
             "notes": notes_for("figure", f.get("label", "图"), ev), "evidence": ev})

    # tables without a locatable caption are dropped: an unverifiable table page
    # is worse than a missing one
    tabs = sorted(tables, key=lambda t: -(t.get("n_cols", 0) * t.get("n_rows", 0)))
    tabs = tabs[:max(want_tables * 3, want_tables)]
    tabs.sort(key=lambda t: t["page"])
    picked_tabs = []
    for t in tabs:
        cap = norm(t.get("caption") or "")
        ev = []
        hit = find_quote(cap[:200], pages, flat, t["page"], min_chars=30)
        if hit:
            ev.append({"page": hit[0], "kind": "table", "label": t.get("label", ""),
                       "quote": hit[1]})
        elif t.get("rows"):
            first = " ".join(c for c in t["rows"][0] if c)[:120]
            hit = find_quote(first, pages, flat, t["page"], min_chars=20)
            if hit:
                ev.append({"page": hit[0], "kind": "table", "label": t.get("label", ""),
                           "quote": hit[1]})
        if not ev:
            warnings.append("%s 的表注无法在页文本中逐字定位，已跳过该表页"
                            % (t.get("label") or t.get("id")))
            continue
        used_quotes.append(hit)
        picked_tabs.append((t, cap, ev))
        if len(picked_tabs) >= want_tables:
            break
    for i, (t, cap, ev) in enumerate(picked_tabs, start=1):
        add({"id": "t%d" % i, "type": "figure", "kicker": "04 · 结果",
             "title": (t.get("label") or "表") + "｜" + (shorten(cap, 52) or "论文结果表"),
             "claim": cap[:120] or "本页展示论文结果表，数值按原表照录。",
             "figure": {"path": t.get("image") or "", "label": t.get("label", ""),
                        "caption": cap},
             "bullets": [],
             "notes": notes_for("table", t.get("label", "表"), ev), "evidence": ev})

    results = by_tag.get("results")
    if results:
        ev = []
        hit = pick_quote(results, pages, flat)
        if hit:
            ev.append({"page": hit[0], "kind": "section",
                       "label": results["title"], "quote": hit[1]})
            used_quotes.append(hit)
        add({"id": "s4", "type": "bullets", "kicker": "05 · 结果",
             "title": results["title"][:58],
             "claim": claim_from(results, "本页汇总论文报告的主要结果。"),
             "bullets": bullets_from(results, pages, flat, 4),
             "notes": notes_for("results", "结果", ev), "evidence": ev})

    limits = by_tag.get("limits")
    if limits:
        ev = []
        hit = pick_quote(limits, pages, flat)
        if hit:
            ev.append({"page": hit[0], "kind": "section",
                       "label": limits["title"], "quote": hit[1]})
            used_quotes.append(hit)
        add({"id": "s5", "type": "bullets", "kicker": "06 · 局限",
             "title": limits["title"][:58],
             "claim": claim_from(limits, "本页列出论文自述的局限与讨论要点。"),
             "bullets": bullets_from(limits, pages, flat, 3),
             "notes": notes_for("limits", "局限", ev), "evidence": ev})
    else:
        warnings.append("未识别到讨论/结论章节，局限页由模型补写")

    add({"id": "s9", "type": "closing", "title": "谢谢，欢迎讨论",
         "claim": "", "footer": (arxiv + " · " if arxiv else "") + title[:60],
         "notes": "", "evidence": []})

    if max_slides and len(slides) > max_slides:
        # keep the narrative skeleton: title, one framing slide, then evidence
        # slides, one discussion slide, then the closing
        order = ["title", "bullets", "figure", "closing"]
        ranked = []
        for want in order:
            for s in slides:
                if s["type"] == want and s not in ranked:
                    ranked.append(s)
        bullets = [s for s in ranked if s["type"] == "bullets"]
        figs_used = [s for s in ranked if s["type"] == "figure"]
        head = [s for s in ranked if s["type"] == "title"]
        tail = [s for s in ranked if s["type"] == "closing"]
        room = max_slides - len(head) - len(tail)
        keep_bullets = bullets[:1] + bullets[1:] if room <= 1 else bullets
        picked = []
        # interleave: framing slides first, then figures, keeping the last bullet
        if room >= 2 and len(bullets) >= 2:
            picked = bullets[:-1]
            room -= len(picked)
        if room > 0:
            picked += figs_used[:room]
            room -= len(picked)
        if room > 0:
            picked += bullets[-1:]
        slides = head + picked[:max_slides - len(head) - len(tail)] + tail
        if slides[-1]["type"] != "closing":
            slides = slides[:max_slides - 1] + tail
        warnings.append("按 max_slides=%d 截断，已保留标题/正文/图/结论页" % max_slides)

    deck = {
        "short_title": shorten(title, 56),
        "kicker": case.get("kicker") or "论文汇报",
        "max_slides": max_slides or len(slides),
        "template": case.get("template_path") or case.get("template"),
        "audience": case.get("audience") or "同领域研究生与导师",
        "duration_min": case.get("duration_min") or 12,
        "source_paper": os.path.basename(meta.get("path", "")),
    }
    report = {
        "schema": "plan-assist/v1",
        "slides": len(slides),
        "sections_seen": len(sections),
        "figures_available": len(figures), "figures_used": len(figs),
        "tables_available": len(tables), "tables_used": len(tabs),
        "quotes_verified": len(used_quotes),
        "warnings": warnings,
        "next_steps": [
            "补 title 页的 subtitle 与 takeaway（一句中文：方法名 + 做了什么 / 核心结论）",
            "逐页把 bullets 改写成可讲述的短语（每条 ≤60 字），保留论文里的数字与单位",
            "逐页把 notes 改写成过渡 + 强调 + 追问预案（不要复述页面文字）",
            "确认每页 evidence 的页码与图/表编号，删掉与本页无关的锚点",
            "python scripts/validate_plan.py plan.json --paper paper.json 必须 status=pass",
        ],
    }
    return {"deck": deck, "slides": slides}, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paper")
    ap.add_argument("--out", default="plan.json")
    ap.add_argument("--case", default=None)
    ap.add_argument("--max-slides", type=int, default=0)
    ap.add_argument("--figures", type=int, default=3)
    ap.add_argument("--tables", type=int, default=2)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    paper = load_json(args.paper)
    if not paper:
        print(json.dumps({"status": "error", "reason": "paper_json_missing",
                          "path": args.paper}, ensure_ascii=False))
        return 2
    case = load_json(args.case) if args.case else {}
    max_slides = args.max_slides or int(case.get("max_slides") or 0)
    plan, report = build(paper, case, max_slides, args.figures, args.tables)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "ok", "out": args.out, **{k: report[k] for k in
                      ("slides", "figures_used", "tables_used", "quotes_verified")}},
                     ensure_ascii=False))
    if report["warnings"]:
        for w in report["warnings"]:
            print("warning:", w)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
