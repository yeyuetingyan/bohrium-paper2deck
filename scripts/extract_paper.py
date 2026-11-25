#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract structured content from a research paper PDF.

Outputs paper.json with:
  meta, sections (page-anchored), figures (cropped PNG + caption + page),
  tables (cell text + caption + page), and per-page raw text.

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
    r"^\s*(?P<label>(?:Figure|Fig\.?|Table|Scheme|Algorithm)\s*"
    r"(?P<num>[0-9]{1,3}|[IVX]{1,5})[a-z]?)\s*[.:|]?\s*(?P<cap>.*)$",
    re.IGNORECASE,
)
NUM_HEAD_RE = re.compile(r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(?P<title>[A-Z][^.]{2,90})$")
EQ_RE = re.compile(r"^\s*\(?\d{1,2}\)?\s*$")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def page_lines(page):
    """Return visual lines with font size / bold info, column-ordered."""
    data = page.get_text("dict")
    width = page.rect.width
    lines = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = norm("".join(s["text"] for s in spans))
            if not text:
                continue
            size = max(s["size"] for s in spans)
            bold = any("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16)
                       for s in spans)
            x0, y0, x1, y1 = line["bbox"]
            col = 0 if (x0 + x1) / 2 < width * 0.5 else 1
            # single-column full-width lines count as column 0
            if x1 - x0 > width * 0.55:
                col = 0
            lines.append({"text": text, "size": round(size, 1), "bold": bold,
                          "x0": round(x0, 1), "y0": round(y0, 1),
                          "x1": round(x1, 1), "y1": round(y1, 1),
                          "col": col, "page": page.number + 1})
    lines.sort(key=lambda d: (d["page"], d["col"], d["y0"], d["x0"]))
    return lines


def body_size(all_lines):
    counter = Counter()
    for ln in all_lines:
        counter[ln["size"]] += len(ln["text"])
    return counter.most_common(1)[0][0] if counter else 10.0


def is_heading(ln, body, max_size):
    t = ln["text"]
    if len(t) > 110 or len(t) < 3:
        return False
    low = t.lower().strip(" .:0123456789")
    if low in HEADING_WORDS:
        return True
    if NUM_HEAD_RE.match(t) and ln["size"] >= body * 0.98:
        return True
    if ln["bold"] and ln["size"] >= body * 1.05 and len(t) < 80:
        return True
    if ln["size"] >= max(body * 1.25, max_size * 0.85) and len(t) < 90:
        return True
    return False


BAD_TITLE = re.compile(
    r"(arxiv|doi:|https?://|preprint|received|accepted|published|copyright|"
    r"under review|proceedings of|vol\.\s*\d)", re.IGNORECASE)


def detect_title(lines, body):
    first_page = [l for l in lines if l["page"] == 1]
    if not first_page:
        return ""
    cands = [l for l in first_page
             if l["size"] >= body * 1.35 and len(l["text"]) > 10
             and not BAD_TITLE.search(l["text"])]
    if not cands:
        return ""
    cands.sort(key=lambda d: (-d["size"], d["y0"]))
    top = cands[0]["size"]
    parts = [l["text"] for l in cands
             if abs(l["size"] - top) < 0.6 and l["y0"] < cands[0]["y0"] + 120]
    parts.sort(key=lambda t: len(t), reverse=True)
    title = parts[0] if parts else cands[0]["text"]
    if len(title) < 14 and len(parts) > 1:
        title = norm(" ".join(parts[:2]))
    return title[:300]


def collect_captions(lines):
    caps = []
    for ln in lines:
        m = CAP_RE.match(ln["text"])
        if not m:
            continue
        label = norm(m.group("label"))
        num = m.group("num")
        kind = "table" if label.lower().startswith("table") else "figure"
        caps.append({"label": f"{label.split()[0].rstrip('.')} {num}",
                     "kind": kind, "text": norm(m.group("cap")),
                     "page": ln["page"], "y0": ln["y0"]})
    # merge continuation lines (caption wrapped over 2-3 lines)
    merged = []
    for cap in caps:
        if merged and cap["page"] == merged[-1]["page"] and \
                0 <= cap["y0"] - merged[-1]["y0"] <= 42 and cap["kind"] == merged[-1]["kind"]:
            merged[-1]["text"] = norm(merged[-1]["text"] + " " + cap["text"])
            merged[-1]["y0"] = cap["y0"]
        else:
            merged.append(dict(cap))
    return merged


def extract_figures(doc, out_dir, dpi, captions):
    os.makedirs(out_dir, exist_ok=True)
    figures = []
    seen = set()
    for page in doc:
        pno = page.number + 1
        page_caps = [c for c in captions if c["page"] == pno and c["kind"] == "figure"]
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue
            r = max(rects, key=lambda rr: rr.width * rr.height)
            if r.width < 90 or r.height < 60:      # icons / rules / logos
                continue
            seen.add(xref)
            scale = dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=r, alpha=False)
            fname = f"fig_p{pno}_{len(figures)+1}.png"
            pix.save(os.path.join(out_dir, fname))
            cap = None
            best = 1e9
            for c in page_caps:
                d = abs(c["y0"] - (r.y1 if c["y0"] >= r.y1 else r.y0))
                if d < best and d < 120:
                    best, cap = d, c
            figures.append({"id": f"fig{pno}_{len(figures)+1}",
                            "page": pno,
                            "image": os.path.join(os.path.basename(out_dir), fname).replace("\\", "/"),
                            "bbox": [round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1)],
                            "width_px": pix.width, "height_px": pix.height,
                            "caption": cap["text"] if cap else "",
                            "label": cap["label"] if cap else ""})
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
                    image = fname
                except Exception:
                    image = ""
            tables.append({"id": f"tab_p{page.number+1}_{len(tables)+1}",
                           "page": page.number + 1,
                           "bbox": bbox,
                           "image": image,
                           "rows": rows,
                           "n_rows": len(rows), "n_cols": max(len(r) for r in rows)})
    return tables


def build_sections(lines, body):
    sections, cur = [], None
    max_size = max(l["size"] for l in lines[:200])
    for ln in lines:
        if is_heading(ln, body, max_size) and not BAD_TITLE.search(ln["text"]):
            title = norm(ln["text"])
            if sections and sections[-1]["title"].lower() == title.lower():
                continue
            cur = {"title": title, "page": ln["page"],
                   "level": 2 if re.match(r"^\d+\.\d+", title) else 1,
                   "text": ""}
            sections.append(cur)
        elif cur is not None:
            cur["text"] = (cur["text"] + " " + ln["text"]).strip()
    for s in sections:
        s["text"] = norm(s["text"])[:6000]
    return [s for s in sections if len(s["text"]) > 40 or s["level"] == 1]


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
    figures = extract_figures(doc, fig_dir, args.dpi, captions)
    tables = extract_tables(doc, fig_dir, args.dpi) if hasattr(doc[0], "find_tables") else []

    # attach captions to tables by proximity
    for t in tables:
        best, bestd = None, 1e9
        for c in captions:
            if c["kind"] != "table" or c["page"] != t["page"]:
                continue
            d = abs(c["y0"] - t["bbox"][1])
            if d < bestd:
                best, bestd = c, d
        if best and bestd < 160:
            t["caption"], t["label"] = best["text"], best["label"]
        else:
            t["caption"], t["label"] = "", ""

    meta = doc.metadata or {}
    result = {
        "schema": "paper-extract/v1",
        "meta": {"path": os.path.abspath(args.pdf), "pages": doc.page_count,
                 "title": detect_title(lines, body),
                 "pdf_title": norm(meta.get("title", "")),
                 "authors": norm(meta.get("author", "")),
                 "body_font_pt": round(body, 1)},
        "sections": build_sections(lines, body),
        "figures": figures,
        "tables": tables,
        "captions": [{"label": c["label"], "kind": c["kind"], "page": c["page"],
                      "text": c["text"]} for c in captions],
        "page_text": {str(p.number + 1): norm(p.get_text())[:4000] for p in pages},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": "ok", "sections": len(result["sections"]),
                      "figures": len(figures), "tables": len(tables),
                      "pages": doc.page_count, "out": args.out}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
