#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract structured content from a research paper PDF.

Outputs paper.json with:
  meta, sections (page-anchored), figures (cropped PNG + caption + page),
  tables (cell text + caption + page), equations, figure/table index and
  per-page raw text.

Figure capture works for **vector figures** (most journal PDFs draw figures with
paths, not embedded bitmaps): the region above a figure caption is located from
the page's drawing/image bounding boxes and rendered as PNG. Raster figures are
covered by the same region render.

Usage:
  python extract_paper.py paper.pdf --out paper.json [--figdir figures] [--dpi 200]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF
    import fitz


HEADING_WORDS = {
    "abstract", "introduction", "related work", "background", "method",
    "methods", "methodology", "approach", "experiments", "experimental setup",
    "results", "results and discussion", "discussion", "analysis",
    "conclusion", "conclusions", "limitations", "future work",
    "references", "acknowledgments", "acknowledgements", "appendix",
}

CAP_RE = re.compile(
    r"^\s*(?P<kind>Figure|Fig\.?|Table|Scheme|Algorithm)\s*\.?\s*"
    r"(?P<num>[0-9]{1,3}|[IVX]{1,5})(?P<sub>[a-z])?"
    r"(?P<sep>\s*[.:|]?\s*)(?P<cap>.*)$",
    re.IGNORECASE,
)
NUM_HEAD_RE = re.compile(r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(?P<title>[A-Z][^.]{2,90})$")
EQ_TAG_RE = re.compile(r"^\s*\(\s*(\d{1,3})\s*\)\s*$")

BAD_TITLE = re.compile(
    r"(arxiv|doi:|https?://|preprint|received|accepted|published|copyright|"
    r"under review|proceedings of|vol\.\s*\d|@|\{|\})", re.IGNORECASE)

NON_TEXT_LINE = re.compile(r"^[\W\d_]+$")
MAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def dehyphen(s: str) -> str:
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", s or "")


def _chars_of(span):
    """Character boxes of a span, for both 'dict' and 'rawdict' output."""
    chars = span.get("chars")
    if chars:
        return [(c.get("c", ""), c.get("bbox")) for c in chars]
    text = span.get("text", "")
    bb = span.get("bbox")
    if not text or not bb:
        return []
    x0, y0, x1, y1 = bb
    step = (x1 - x0) / max(1, len(text))
    return [(ch, (x0 + i * step, y0, x0 + (i + 1) * step, y1)) for i, ch in enumerate(text)]


def span_text(span):
    """Re-insert the spaces that a PDF may have dropped between glyphs.

    Journal PDFs frequently emit "GPTusedthesamelearningrate" as one run of
    glyphs. Measuring the gap between consecutive character boxes recovers the
    real word boundaries instead of guessing from letter case.
    """
    chars = _chars_of(span)
    if not chars:
        return span.get("text", "")
    size = float(span.get("size") or 10.0)
    thresh = max(0.9, 0.16 * size)
    out = []
    prev_x1 = None
    for ch, bb in chars:
        if bb is None:
            out.append(ch)
            continue
        x0, _y0, x1, _y1 = bb
        if prev_x1 is not None and ch != " " and out and out[-1] != " ":
            if x0 - prev_x1 > thresh:
                out.append(" ")
        out.append(ch)
        prev_x1 = x1
    return "".join(out)


def page_lines(page):
    """Return visual lines with font size / bold info, column-ordered."""
    data = page.get_text("rawdict")
    width = page.rect.width
    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if span_text(s).strip()]
            if not spans:
                continue
            raw = ""
            prev_x1 = None
            for s in spans:
                text = span_text(s)
                bb = s.get("bbox")
                if prev_x1 is not None and bb and bb[0] - prev_x1 > max(0.9, 0.16 * float(s.get("size") or 10)):
                    raw += " "
                raw += text
                if bb:
                    prev_x1 = bb[2]
            text = norm(raw)
            if not text:
                continue
            size = max(float(s.get("size") or 0) for s in spans)
            bold = any("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16)
                       for s in spans)
            x0, y0, x1, y1 = line["bbox"]
            col = 0 if (x0 + x1) / 2 < width * 0.5 else 1
            if x1 - x0 > width * 0.55:            # full-width line: column 0
                col = 0
            # rotated text (arXiv sidebar watermark) has a taller-than-wide box
            rotated = (y1 - y0) > (x1 - x0) * 1.6
            lines.append({"text": text, "size": round(size, 1), "bold": bold,
                          "x0": round(x0, 1), "y0": round(y0, 1),
                          "x1": round(x1, 1), "y1": round(y1, 1),
                          "col": col, "page": page.number + 1,
                          "rotated": rotated})
    lines.sort(key=lambda d: (d["page"], d["col"], d["y0"], d["x0"]))
    return lines


def body_size(all_lines):
    counter = Counter()
    for ln in all_lines:
        if ln.get("rotated"):
            continue
        counter[ln["size"]] += len(ln["text"])
    return counter.most_common(1)[0][0] if counter else 10.0


def is_heading(ln, body, max_size):
    t = ln["text"]
    if ln.get("rotated") or len(t) > 110 or len(t) < 3:
        return False
    if BAD_TITLE.search(t) or NON_TEXT_LINE.match(t):
        return False
    if t[0] in "•·-–—*▪" or t[:2] in ("e.g", "i.e"):
        return False
    if re.match(r"^\d+\s*$", t):
        return False
    low = t.lower().strip(" .:0123456789")
    if low in HEADING_WORDS:
        return True
    if NUM_HEAD_RE.match(t) and ln["size"] >= body * 0.98:
        return True
    if ln["bold"] and ln["size"] >= body * 1.02 and len(t) < 80:
        return True
    # a large unnumbered line still counts, but only if clearly larger than body
    # and not a sentence fragment (they end with a period or start lowercase)
    if (ln["size"] >= max(body * 1.35, max_size * 0.9) and len(t) < 90
            and not t.endswith(".") and not t[0].islower()):
        return True
    return False


def detect_title(lines, body):
    """Join the multi-line title that most PDFs break across 1-3 lines."""
    first_page = [l for l in lines if l["page"] == 1 and not l.get("rotated")]
    if not first_page:
        return ""
    page_h = max(l["y1"] for l in first_page)
    top_zone = [l for l in first_page if l["y0"] < page_h * 0.42]
    cands = [l for l in top_zone
             if l["size"] >= body * 1.25 and len(l["text"]) > 8
             and not BAD_TITLE.search(l["text"])]
    if not cands:
        cands = [l for l in top_zone if l["size"] >= body * 1.15 and len(l["text"]) > 12
                 and not BAD_TITLE.search(l["text"])]
    if not cands:
        return ""
    top = max(c["size"] for c in cands)
    group = sorted([c for c in cands if abs(c["size"] - top) < 0.7], key=lambda d: d["y0"])
    # keep the consecutive run starting at the first line, gaps < 1.2 line heights
    parts = [group[0]]
    for prev, cur in zip(group, group[1:]):
        if cur["y0"] - prev["y0"] <= max(28.0, prev["size"] * 1.9):
            parts.append(cur)
        else:
            break
    if len(parts) == 1 and len(parts[0]["text"]) < 14 and len(group) > 1:
        parts = group[:2]
    title = norm(" ".join(p["text"] for p in parts))
    if MAIL_RE.search(title):
        return ""
    return title[:300]


def _canon_label(kind_word: str, num: str, sub: str = "") -> str:
    word = {"fig": "Figure", "figure": "Figure", "tab": "Table", "table": "Table",
            "scheme": "Scheme", "algorithm": "Algorithm"}.get(kind_word.lower().rstrip("."),
                                                              kind_word.title())
    return f"{word} {num}{(sub or '')}".strip()


def collect_captions(lines):
    """Caption blocks with a canonical label and a bbox (multi-line merged)."""
    caps = []
    for idx, ln in enumerate(lines):
        t = ln["text"]
        m = CAP_RE.match(t)
        if not m:
            continue
        tail = (m.group("cap") or "").strip()
        if tail and tail[0].islower() and not m.group("sep").strip():
            continue                       # glued body text, not a caption
        word = m.group("kind")
        num = m.group("num")
        kind = "table" if word.lower().startswith("tab") else "figure"
        # headings such as "Figure 1: ..." inside a running head are rare; require
        # the caption to be either short, or to start on its own line
        if len(t) > 200 and not tail:
            continue
        x1 = ln["x1"]
        y0, y1 = ln["y0"], ln["y1"]
        text = norm(tail)
        size = ln["size"]
        # continuation lines: right below, same column, no caption label of its own
        j = idx + 1
        while j < len(lines):
            nxt = lines[j]
            if nxt["page"] != ln["page"] or nxt["col"] != ln["col"]:
                break
            if nxt["y0"] - y1 > max(14.0, size * 1.7):
                break
            if CAP_RE.match(nxt["text"]):
                break
            if nxt["rotated"]:
                j += 1
                continue
            text = norm(text + " " + nxt["text"])
            y1 = nxt["y1"]
            x1 = max(x1, nxt["x1"])
            j += 1
        caps.append({"label": _canon_label(word, num, m.group("sub") or ""),
                     "kind": kind, "text": text, "page": ln["page"],
                     "x0": ln["x0"], "y0": y0, "x1": x1, "y1": y1, "size": size})
    # dedupe identical labels on the same page: keep the longest caption text
    best, order = {}, []
    for cap in caps:
        key = (cap["kind"], cap["label"], cap["page"])
        if key not in best:
            best[key] = dict(cap)
            order.append(key)
        elif len(cap["text"]) > len(best[key]["text"]):
            keep = dict(cap)
            keep["y0"] = min(best[key]["y0"], cap["y0"])
            best[key] = keep
    return [best[k] for k in order]


def _page_graphics(page, min_w=6.0, min_h=6.0):
    """Bounding boxes of vector drawings + raster images on a page."""
    boxes = []
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r is None or r.width < min_w or r.height < min_h:
                continue
            boxes.append((r.x0, r.y0, r.x1, r.y1))
    except Exception:
        pass
    try:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") == 1:
                x0, y0, x1, y1 = b["bbox"]
                if x1 - x0 >= min_w and y1 - y0 >= min_h:
                    boxes.append((x0, y0, x1, y1))
    except Exception:
        pass
    return boxes


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _cluster_boxes(boxes, gap=12.0):
    """Union graphics boxes that touch or nearly touch into figure clusters."""
    clusters = []
    for box in sorted(boxes, key=lambda b: b[1]):
        placed = False
        for c in clusters:
            if (box[1] <= c[3] + gap and box[3] >= c[1] - gap and
                    box[0] <= c[2] + gap and box[2] >= c[0] - gap):
                c[0] = min(c[0], box[0]); c[1] = min(c[1], box[1])
                c[2] = max(c[2], box[2]); c[3] = max(c[3], box[3])
                placed = True
                break
        if placed:
            # merging may make two clusters overlap; fuse repeatedly
            changed = True
            while changed:
                changed = False
                for i in range(len(clusters)):
                    for j in range(i + 1, len(clusters)):
                        a, b = clusters[i], clusters[j]
                        if (a[1] <= b[3] + gap and a[3] >= b[1] - gap and
                                a[0] <= b[2] + gap and a[2] >= b[0] - gap):
                            a[0] = min(a[0], b[0]); a[1] = min(a[1], b[1])
                            a[2] = max(a[2], b[2]); a[3] = max(a[3], b[3])
                            clusters.pop(j)
                            changed = True
                            break
                    if changed:
                        break
        else:
            clusters.append([box[0], box[1], box[2], box[3]])
    return [tuple(c) for c in clusters]


def _pick_region(clusters, cap):
    """Which graphics cluster belongs to this caption?"""
    cands = []
    for c in clusters:
        inter = _overlap(c[0], c[2], cap["x0"] - 8, cap["x1"] + 8)
        width = c[2] - c[0]
        if inter < 0.5 * min(width, cap["x1"] - cap["x0"] + 16):
            continue
        if c[3] <= cap["y0"] + 8 and c[3] >= cap["y0"] - 340:
            cands.append((cap["y0"] - c[3], c, "above"))
        elif c[1] >= cap["y1"] - 8 and c[1] <= cap["y1"] + 340:
            cands.append((c[1] - cap["y1"], c, "below"))
    if not cands:
        return None, ""
    cands.sort(key=lambda t: t[0])
    for _d, c, side in cands:
        w, h = c[2] - c[0], c[3] - c[1]
        if w >= 70 and h >= 45:
            return c, side
    return None, ""


def extract_figures(doc, out_dir, dpi, captions, lines):
    """Render the graphic region that belongs to each figure caption.

    Works for vector figures (journal PDFs draw figures with paths): graphics
    boxes are clustered, and the cluster directly above the caption (or directly
    below it, for caption-on-top layouts) is rendered as a PNG.
    """
    os.makedirs(out_dir, exist_ok=True)
    figures = []
    cluster_cache = {}
    for idx, cap in enumerate(captions):
        if cap["kind"] != "figure":
            continue
        pno = cap["page"]
        page = doc[pno - 1]
        if pno not in cluster_cache:
            cluster_cache[pno] = _cluster_boxes(_page_graphics(page))
        clusters = cluster_cache[pno]
        box, side = _pick_region(clusters, cap)
        if box is None:
            continue
        rect = fitz.Rect(box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4) & page.rect
        if rect.width < 70 or rect.height < 45:
            continue
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        stem = re.sub(r"\W+", "", cap["label"]).lower() or "fig%d" % (idx + 1)
        fname = "fig_%s_p%d.png" % (stem, pno)
        pix.save(os.path.join(out_dir, fname))
        figures.append({"id": "fig_%s" % stem,
                        "page": pno,
                        "image": os.path.join(os.path.basename(out_dir), fname).replace("\\", "/"),
                        "bbox": [round(v, 1) for v in (rect.x0, rect.y0, rect.x1, rect.y1)],
                        "clip": {"x0": round(rect.x0, 1), "y0": round(rect.y0, 1),
                                 "x1": round(rect.x1, 1), "y1": round(rect.y1, 1)},
                        "page_size": [round(page.rect.width, 1), round(page.rect.height, 1)],
                        "width_px": pix.width, "height_px": pix.height,
                        "caption": cap["text"], "label": cap["label"],
                        "cluster": len(clusters), "caption_side": side, "source": "region"})
    figures.sort(key=lambda f: (f["page"], f["bbox"][1]))
    return figures


def extract_tables(doc, out_dir=None, dpi=200):
    tables = []
    for page in doc:
        try:
            found = page.find_tables()
        except Exception:
            continue
        for tab in getattr(found, "tables", []):
            try:
                rows = [[norm(c) for c in row] for row in tab.extract()]
            except Exception:
                continue
            rows = [r for r in rows if any(r)]
            if len(rows) < 2 or sum(len("".join(r)) for r in rows) < 20:
                continue
            bbox = [round(v, 1) for v in tab.bbox]
            image = ""
            if out_dir:
                try:
                    r = fitz.Rect(*tab.bbox)
                    r = fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2) & page.rect
                    scale = dpi / 72.0
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=r, alpha=False)
                    fname = f"tab_p{page.number+1}_{len(tables)+1}.png"
                    pix.save(os.path.join(out_dir, fname))
                    image = os.path.join(os.path.basename(out_dir), fname).replace("\\", "/")
                except Exception:
                    image = ""
            tables.append({"id": f"tab_p{page.number+1}_{len(tables)+1}",
                           "page": page.number + 1,
                           "bbox": bbox,
                           "image": image,
                           "rows": rows,
                           "n_rows": len(rows), "n_cols": max(len(r) for r in rows)})
    return tables


def collect_equations(lines):
    """Display equations: a tagged line `(12)` plus the lines just above it."""
    eqs = []
    for i, ln in enumerate(lines):
        if not EQ_TAG_RE.match(ln["text"]):
            continue
        num = EQ_TAG_RE.match(ln["text"]).group(1)
        body = []
        for prev in reversed(lines[max(0, i - 4):i]):
            if prev["page"] != ln["page"] or prev["y0"] < ln["y0"] - 70:
                break
            body.append(prev["text"])
        eqs.append({"id": f"eq{num}", "label": f"Equation {num}", "page": ln["page"],
                    "y0": ln["y0"], "text": norm(" ".join(reversed(body)))[:300]})
    return eqs


def build_sections(lines, body):
    sections, cur = [], None
    max_size = max([l["size"] for l in lines[:200] if not l.get("rotated")] or [body])
    for ln in lines:
        if is_heading(ln, body, max_size):
            title = norm(ln["text"]).lstrip("•·-–—*▪ ").strip()
            if not title:
                continue
            if sections and sections[-1]["title"].lower() == title.lower():
                continue
            if any(p["title"].lower() == title.lower() for p in sections):
                continue
            cur = {"title": title, "page": ln["page"],
                   "level": 2 if re.match(r"^\d+\.\d+", title) else 1,
                   "text": ""}
            sections.append(cur)
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + ln["text"]).strip()
    for s in sections:
        s["text"] = dehyphen(norm(s["text"]))[:6000]
    return [s for s in sections if len(s["text"]) > 40 or s["level"] == 1]


def attach_captions(tables, captions):
    for t in tables:
        best, bestd = None, 1e9
        for c in captions:
            if c["kind"] != "table" or c["page"] != t["page"]:
                continue
            d = abs(c["y0"] - t["bbox"][1]) if c["y0"] >= t["bbox"][1] else abs(t["bbox"][3] - c["y0"])
            if d < bestd:
                best, bestd = c, d
        if best and bestd < 220:
            t["caption"], t["label"] = best["text"], best["label"]
        else:
            t["caption"], t["label"] = "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="paper.json")
    ap.add_argument("--figdir", default="figures")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--max-pages", type=int, default=40)
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    if doc.needs_pass:
        print(json.dumps({"status": "error", "reason": "encrypted_pdf"}, ensure_ascii=False))
        return 2
    if doc.page_count == 0:
        print(json.dumps({"status": "error", "reason": "empty_pdf"}, ensure_ascii=False))
        return 2

    pages = list(doc)[: args.max_pages]
    lines = []
    for p in pages:
        lines.extend(page_lines(p))
    body = body_size(lines)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    fig_dir = args.figdir if os.path.isabs(args.figdir) else os.path.join(out_dir, args.figdir)
    captions = collect_captions(lines)
    figures = extract_figures(doc, fig_dir, args.dpi, captions, lines)
    tables = extract_tables(doc, fig_dir, args.dpi) if hasattr(doc[0], "find_tables") else []
    attach_captions(tables, captions)
    equations = collect_equations(lines)

    index = {}
    for f in figures:
        if f["label"]:
            index.setdefault(f["label"], {"kind": "figure", "page": f["page"], "image": f["image"]})
    for t in tables:
        if t.get("label"):
            index.setdefault(t["label"], {"kind": "table", "page": t["page"], "image": t.get("image", "")})
    for e in equations:
        index.setdefault(e["label"], {"kind": "equation", "page": e["page"], "image": ""})

    meta = doc.metadata or {}
    result = {
        "schema": "paper-extract/v1",
        "meta": {"path": os.path.abspath(args.pdf), "pages": doc.page_count,
                 "title": detect_title(lines, body),
                 "pdf_title": norm(meta.get("title", "")),
                 "authors": norm(meta.get("author", "")),
                 "body_font_pt": round(body, 1),
                 "figures": len(figures), "tables": len(tables),
                 "captions": len(captions), "equations": len(equations)},
        "sections": build_sections(lines, body),
        "figures": figures,
        "tables": tables,
        "equations": equations,
        "index": index,
        "captions": [{"label": c["label"], "kind": c["kind"], "page": c["page"],
                      "text": c["text"]} for c in captions],
        "page_text": {str(p.number + 1): norm(p.get_text())[:4000] for p in pages},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "ok", "sections": len(result["sections"]),
                      "figures": len(figures), "tables": len(tables),
                      "equations": len(equations),
                      "pages": doc.page_count, "out": args.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
