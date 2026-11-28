#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build an editable academic slide deck from a plan.json.

Design goals
------------
1. Every slide carries ONE claim; body text is a speaking outline, not paragraphs.
2. Each slide records page-level evidence (paper page / figure / table / quote),
   printed in the footer and exported to evidence.json.
3. Speaker notes are separated from slide text: transition + emphasis + backup.
4. Text never overflows: measured with real font metrics, font size shrinks in
   bounded steps; if it still does not fit, the overflow is reported, not hidden.
5. Works with a supplied template (master/layout/theme preserved) or standalone.

Usage:
  python build_deck.py plan.json --out out/deck.pptx [--template tpl.pptx]
                                  [--evidence out/evidence.json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from PIL import Image, ImageFont

# ---------------------------------------------------------------- typography
NAVY = RGBColor(0x14, 0x2B, 0x45)
INK = RGBColor(0x1A, 0x1A, 0x1A)
GRAY = RGBColor(0x5A, 0x64, 0x70)
LIGHT = RGBColor(0xE8, 0xEC, 0xF1)
ACCENT = RGBColor(0x0F, 0x6E, 0x7E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BG = RGBColor(0xFA, 0xFB, 0xFC)

LATIN_FONT = "Arial"
EA_FONT = "Noto Sans CJK SC"

SW, SH = 13.333, 7.5          # 16:9 inches
M = 0.62                       # outer margin
CW = SW - 2 * M                # content width

_FONT_CACHE = {}


def _font(size_pt, bold=False):
    key = (round(size_pt, 1), bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = None
    try:
        import matplotlib
        base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        path = os.path.join(base, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    except Exception:
        path = None
    if not path or not os.path.exists(path):
        path = "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    try:
        f = ImageFont.truetype(path, int(size_pt * 4))   # 4 px per pt at 288 dpi
    except Exception:
        f = None
    _FONT_CACHE[key] = f or "fallback"
    return _FONT_CACHE[key]


def text_width_pt(text, size_pt, bold=False):
    f = _font(size_pt, bold)
    total = 0.0
    if f == "fallback":
        return len(text) * size_pt * 0.55
    for ch in text:
        if ord(ch) > 0x2E7F:              # CJK / full-width
            total += size_pt * 1.0
        else:
            total += f.getlength(ch) / 4.0
    return total


def wrap_count(text, size_pt, width_pt, bold=False):
    """Number of rendered lines for a paragraph at a fixed width."""
    if not text:
        return 1
    lines, cur = 1, 0.0
    for ch in text:
        w = size_pt * 1.0 if ord(ch) > 0x2E7F else _font(size_pt, bold).getlength(ch) / 4.0 \
            if _font(size_pt, bold) != "fallback" else size_pt * 0.55
        if cur + w > width_pt:
            lines += 1
            cur = w
        else:
            cur += w
    return lines


# ---------------------------------------------------------------- utilities
def set_run_font(run, size, bold=False, color=INK, italic=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    f.name = LATIN_FONT
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
    if ea is None:
        from lxml import etree
        ea = etree.SubElement(rPr, "{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
    ea.set("typeface", EA_FONT)


def add_box(slide, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE):
    shp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    if shp.has_text_frame:
        shp.text_frame.text = ""
    return shp


def add_text(slide, x, y, w, h, text, size=18, bold=False, color=INK,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.12,
             space_after=0, italic=False):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = line_spacing
    if space_after:
        p.space_after = Pt(space_after)
    r = p.add_run()
    r.text = text
    set_run_font(r, size, bold, color, italic)
    return tb


def add_bullets(slide, x, y, w, h, items, size=18, color=INK, sub_size=None,
                bullet_color=ACCENT, anchor=MSO_ANCHOR.TOP):
    """items: [{'text':..., 'level':0}] with measured fitting."""
    sub_size = sub_size or max(13, size - 3)
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    first = True
    for it in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        lvl = int(it.get("level", 0))
        sz = size if lvl == 0 else sub_size
        p.line_spacing = 1.12
        p.space_after = Pt(9 if lvl == 0 else 4)
        if lvl > 0:
            p.level = 1
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(int(Inches(0.34))))
        mark = "•  " if lvl == 0 else "–  "
        run = p.add_run()
        run.text = mark
        set_run_font(run, sz, True, bullet_color if lvl == 0 else GRAY)
        run2 = p.add_run()
        run2.text = it["text"]
        set_run_font(run2, sz, lvl == 0 and False, color if lvl == 0 else GRAY)
    return tb


def fit_bullets(items, w_in, h_in, start=20, floor=13, sub_ratio=0.86):
    """Largest size at which bullets fit inside the box."""
    w_pt, h_pt = w_in * 72, h_in * 72
    size = start
    while size >= floor:
        total = 0.0
        for it in items:
            lvl = int(it.get("level", 0))
            sz = size if lvl == 0 else size * sub_ratio
            indent = 0 if lvl == 0 else 18
            total += wrap_count(("•  " if lvl == 0 else "–  ") + it["text"], sz,
                                w_pt - indent) * sz * 1.12
            total += (8 if lvl == 0 else 4)
        if total <= h_pt:
            return round(size, 1)
        size -= 0.5
    return floor


# ---------------------------------------------------------------- chrome
def chrome(slide, deck, page_no, total, evidence_line=""):
    """Accent rail, footer, page number, evidence line."""
    add_box(slide, 0, 0, 0.11, SH, fill=ACCENT)
    # footer
    add_box(slide, M, SH - 0.62, CW, 0.012, fill=LIGHT)
    add_text(slide, M, SH - 0.55, CW - 1.0, 0.26,
             deck.get("short_title", ""), 9, False, GRAY)
    add_text(slide, SW - M - 0.8, SH - 0.55, 0.8, 0.26,
             f"{page_no} / {total}", 9, False, GRAY, PP_ALIGN.RIGHT)
    if evidence_line:
        add_text(slide, M, SH - 0.30, CW - 0.9, 0.24, evidence_line, 8.5, False, ACCENT)


def evidence_line(ev):
    """Compact, deduplicated source line: 图 1 p.3 · 表 2 p.8 · §Results p.8"""
    if not ev:
        return ""
    seen, parts = set(), []
    for e in ev:
        kind = e.get("kind", "")
        lab = (e.get("label") or "").strip()
        page = e.get("page")
        if kind in ("figure", "table"):
            num = re.sub(r"^(figure|fig\.?|table)\s*", "", lab, flags=re.I).strip()
            tag = ("图 " if kind == "figure" else "表 ") + num
        elif kind == "section":
            name = re.sub(r"^\d+(\.\d+)*\.?\s*", "", lab).strip()
            tag = "§" + name[:40] if name else "§"
        else:
            tag = "正文"
        item = f"{tag} p.{page}" if page else tag
        if item not in seen:
            seen.add(item)
            parts.append(item)
    return "来源：" + " · ".join(parts[:3])


def xy_crop(rect, pw, ph):
    """Fractional (left, top, right, bottom) crop for a PDF-space rect."""
    if isinstance(rect, dict):
        rect = (rect.get("x0", 0), rect.get("y0", 0), rect.get("x1", 0), rect.get("y1", 0))
    try:
        x0, y0, x1, y1 = [float(v) for v in rect]
    except (TypeError, ValueError):
        return None
    if not pw or not ph:
        return None
    l = min(max(x0 / pw, 0.0), 1.0)
    t = min(max(y0 / ph, 0.0), 1.0)
    r = min(max(x1 / pw, 0.0), 1.0)
    b = min(max(y1 / ph, 0.0), 1.0)
    return (l, t, r, b)


def add_figure_image(slide, img_path, x, y, w_avail, h_avail, crop=None):
    """Place an image inside the box, optionally cropping the source first.

    Figure regions captured from a PDF often include the caption or a sliver of
    the surrounding column; cropping to the detected region keeps the slide
    readable without distorting the artwork.
    """
    from PIL import Image as _Image
    with _Image.open(img_path) as im:
        iw, ih = im.size
        full_ar = iw / ih
        if crop:
            l, t, r, b = crop
            if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
                crop = None
            else:
                box = (int(l * iw), int(t * ih), int(r * iw), int(b * ih))
                if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                    im2 = im.crop(box)
                    iw, ih = im2.size
                    out = img_path + ".crop.png"
                    im2.save(out)
                    img_path = out
                else:
                    crop = None
    ar = iw / ih
    if ar > full_ar * 2.2:                 # clip looks degenerate
        img_path, ar = img_path.replace(".crop.png", ""), full_ar
    w, h = w_avail, w_avail / ar
    if h > h_avail:
        h, w = h_avail, h_avail * ar
    x = x + (w_avail - w) / 2
    slide.shapes.add_picture(img_path, Inches(x), Inches(y), Inches(w), Inches(h))
    return w, h


def slide_header(slide, kicker, title, subtitle=None):
    add_text(slide, M, 0.42, CW, 0.28, kicker or "", 12, True, ACCENT)
    # Title sizing: keep within two lines, and reserve the room those two lines
    # actually take. Measured width underestimates bold type, so apply a margin.
    size = 30
    while size > 21 and wrap_count(title, size, CW * 72 * 0.94, True) > 2:
        size -= 1
    lines = max(1, min(2, wrap_count(title, size, CW * 72 * 0.94, True)))
    add_text(slide, M, 0.72, CW, 1.0, title, size, True, NAVY, line_spacing=1.02)
    y = 0.72 + lines * (size * 1.16 / 72.0) + 0.05
    if subtitle:
        sub_lines = max(1, min(2, wrap_count(subtitle, 13, CW * 72 * 0.98)))
        add_text(slide, M, y, CW, 0.4, subtitle, 13, False, GRAY)
        y += sub_lines * 0.235 + 0.05
    add_box(slide, M, y + 0.05, 1.05, 0.035, fill=ACCENT)
    return y + 0.24


# ---------------------------------------------------------------- layouts
def base_slide(prs, use_layout=None):
    if use_layout is not None:
        return prs.slides.add_slide(use_layout)
    blank = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    return prs.slides.add_slide(blank)


def layout_title(s, sl, deck):
    add_box(s, 0, 0, SW, SH, fill=NAVY)
    add_box(s, 0, 0, 0.14, SH, fill=ACCENT)
    add_text(s, M + 0.25, 1.55, CW - 0.9, 0.32,
             deck.get("kicker", "学术汇报"), 13, True, RGBColor(0x8F, 0xC7, 0xD1))
    title = sl.get("title", "")
    size = 40
    while size > 26 and wrap_count(title, size, (CW - 0.9) * 72, True) > 3:
        size -= 2
    add_text(s, M + 0.25, 1.95, CW - 0.9, 2.0, title, size, True, WHITE, line_spacing=1.05)
    y = 1.95 + 0.62 * wrap_count(title, size, (CW - 0.9) * 72, True)
    if sl.get("subtitle"):
        add_text(s, M + 0.25, y + 0.15, CW - 1.4, 0.9, sl["subtitle"], 16, False,
                 RGBColor(0xD5, 0xDF, 0xE8), line_spacing=1.2)
    meta = " · ".join(x for x in [sl.get("authors", ""), sl.get("venue", "")] if x)
    if meta:
        add_text(s, M + 0.25, SH - 1.35, CW - 1.4, 0.3, meta, 12, False,
                 RGBColor(0x9F, 0xAE, 0xBE))
    if sl.get("takeaway"):
        add_box(s, M + 0.25, SH - 0.95, 0.05, 0.30, fill=ACCENT)
        add_text(s, M + 0.45, SH - 0.97, CW - 1.4, 0.36, sl["takeaway"], 13, True, WHITE)


def layout_section(s, sl, deck):
    add_box(s, 0, 0, SW, SH, fill=BG)
    add_box(s, 0, 0, 0.11, SH, fill=ACCENT)
    add_text(s, M, 2.7, 1.2, 0.9, sl.get("number", ""), 54, True, RGBColor(0xC9, 0xD3, 0xDD))
    add_text(s, M + 1.25, 2.62, CW - 1.6, 1.0, sl.get("title", ""), 32, True, NAVY)
    if sl.get("claim"):
        add_text(s, M + 1.25, 3.62, CW - 1.6, 0.8, sl["claim"], 15, False, GRAY)


def layout_bullets(s, sl, deck):
    y = slide_header(s, sl.get("kicker"), sl.get("title", ""), sl.get("subtitle"))
    items = sl.get("bullets") or []
    bottom = SH - 0.85
    h = bottom - y
    size = fit_bullets(items, CW, h, 22, 15)
    if items:
        # start right under the title: centring left a dead band on short lists
        add_bullets(s, M, y + 0.18, CW, h - 0.2, items, size=size,
                    anchor=MSO_ANCHOR.TOP)
    else:
        # an empty body reads as a broken page; say so in the deck itself
        add_text(s, M, y + h / 2 - 0.2, CW, 0.4,
                 "（本页要点待补：论文该节无可用短句）", 13, False, GRAY, PP_ALIGN.CENTER)
    return size


def layout_bullets_side(s, sl, deck):
    """Body bullets with a callout card on the right (used when plan says side)."""
    y = slide_header(s, sl.get("kicker"), sl.get("title", ""), sl.get("subtitle"))
    items = sl.get("bullets", [])
    h = SH - 0.95 - y
    size = fit_bullets(items, CW * (0.62 if sl.get("side") else 1.0) - 0.15, h, 22, 14)

    if sl.get("side"):
        # callout card on the right
        cx, cw = M + CW * 0.655, CW * 0.345
        add_box(s, cx, y + 0.05, cw, h - 0.1, fill=RGBColor(0xF1, 0xF6, 0xF8))
        add_box(s, cx, y + 0.05, 0.045, h - 0.1, fill=ACCENT)
        add_text(s, cx + 0.22, y + 0.2, cw - 0.44, 0.3, sl["side"].get("title", ""), 12, True, ACCENT)
        add_text(s, cx + 0.22, y + 0.55, cw - 0.44, h - 0.75,
                 sl["side"].get("text", ""), 12.5, False, INK, line_spacing=1.2,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_bullets(s, M, y + 0.05, CW * 0.615, h, items, size=size,
                    anchor=MSO_ANCHOR.MIDDLE)
    else:
        add_bullets(s, M, y + 0.05, CW, h, items, size=size, anchor=MSO_ANCHOR.MIDDLE)
    return size


def layout_figure(s, sl, deck):
    fig = sl.get("figure") or {}
    y = slide_header(s, sl.get("kicker"), sl.get("title", ""), sl.get("subtitle"))
    bottom = SH - (1.05 if fig.get("caption") else 0.8)
    avail_h = bottom - y - 0.05
    with_caption = bool(fig.get("caption"))

    img_path = fig.get("path")
    if img_path and not os.path.isabs(img_path) and deck.get("base_dir"):
        img_path = os.path.join(deck["base_dir"], img_path)
    if img_path and os.path.exists(img_path):
        crop = None
        if fig.get("clip") and fig.get("page_size"):
            crop = xy_crop(fig["clip"], fig["page_size"][0], fig["page_size"][1])
        side_items = sl.get("bullets", [])
        w_area = CW * (0.60 if side_items else 1.0)
        w, h = add_figure_image(s, img_path, M, y + 0.02, w_area, avail_h, crop)
        if side_items:
            add_bullets(s, M + CW * 0.635, y + 0.05, CW * 0.365, avail_h,
                        side_items, size=fit_bullets(side_items, CW * 0.365, avail_h, 15, 11))
        cap_y = y + 0.02 + h + 0.06
    else:
        add_box(s, M, y, CW, avail_h, fill=LIGHT)
        add_text(s, M, y + avail_h / 2 - 0.2, CW, 0.4,
                 "[图缺失：请检查 PDF 图像提取] " + (fig.get("label") or ""), 13, False, GRAY,
                 PP_ALIGN.CENTER)
        cap_y = y + avail_h - 0.4

    if with_caption and cap_y < SH - 0.95:
        cap = f"{fig.get('label', '')}  {fig['caption']}"
        size = 10.5
        while size > 8 and wrap_count(cap, size, (CW * (0.60 if sl.get('bullets') else 1.0)) * 72) > 2:
            size -= 0.5
        add_text(s, M, cap_y, CW * (0.60 if sl.get("bullets") else 1.0), 0.45,
                 cap, size, False, GRAY, line_spacing=1.05)


def layout_table(s, sl, deck):
    tab = sl.get("table") or {}
    y = slide_header(s, sl.get("kicker"), sl.get("title", ""), sl.get("subtitle"))
    rows = tab.get("rows") or []
    if not rows:
        add_text(s, M, y, CW, 0.5, "[表缺失]", 14, False, GRAY)
        return
    n_rows, n_cols = len(rows), max(len(r) for r in rows)
    bottom = SH - (1.05 if tab.get("caption") else 0.85)
    avail_h = bottom - y
    row_h = min(0.42, avail_h / n_rows)
    size = 12
    while size > 8 and row_h < (size / 72.0) * 1.55:
        size -= 0.5
    total_h = row_h * n_rows
    total_w = min(CW, 1.35 * n_cols + 2.2)
    left = M + (CW - total_w) / 2
    tbl = s.shapes.add_table(n_rows, n_cols, Inches(left), Inches(y),
                             Inches(total_w), Inches(total_h)).table
    for c in range(n_cols):
        tbl.columns[c].width = Emu(int(Inches(total_w) / n_cols))
    for ri, row in enumerate(rows):
        tbl.rows[ri].height = Emu(int(Inches(row_h)))
        for ci in range(n_cols):
            cell = tbl.cell(ri, ci)
            cell.text = ""
            cell.margin_left = Inches(0.07)
            cell.margin_right = Inches(0.05)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if (ri == 0 and tab.get("header", True)) else (
                RGBColor(0xF4, 0xF7, 0xF9) if ri % 2 else WHITE)
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if ci == 0 else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(row[ci]) if ci < len(row) else ""
            set_run_font(r, size, ri == 0 and tab.get("header", True),
                         WHITE if (ri == 0 and tab.get("header", True)) else INK)
    if tab.get("caption"):
        cap = f"{tab.get('label', '')}  {tab['caption']}"
        add_text(s, M, y + total_h + 0.08, CW, 0.4, cap, 10, False, GRAY)


def layout_comparison(s, sl, deck):
    """Two boxes side by side: left list vs right list."""
    y = slide_header(s, sl.get("kicker"), sl.get("title", ""), sl.get("subtitle"))
    cols = sl.get("columns") or []
    n = max(1, len(cols))
    gap = 0.3
    cw = (CW - gap * (n - 1)) / n
    h = SH - 0.95 - y - 0.05
    for i, col in enumerate(cols):
        x = M + i * (cw + gap)
        card_fill = RGBColor(0xF1, 0xF6, 0xF8) if i % 2 == 0 else RGBColor(0xF7, 0xF6, 0xF2)
        add_box(s, x, y, cw, h, fill=card_fill)
        add_box(s, x, y, cw, 0.05, fill=ACCENT if i % 2 == 0 else NAVY)
        add_text(s, x + 0.25, y + 0.18, cw - 0.5, 0.4, col.get("title", ""), 14, True, NAVY)
        items = [{"text": t} if isinstance(t, str) else t for t in col.get("items", [])]
        add_bullets(s, x + 0.25, y + 0.62, cw - 0.5, h - 0.8, items, size=13.5)


def layout_closing(s, sl, deck):
    add_box(s, 0, 0, SW, SH, fill=NAVY)
    add_box(s, 0, 0, 0.14, SH, fill=ACCENT)
    add_text(s, M + 0.25, 2.15, CW - 1.2, 0.35,
             sl.get("kicker", "结论"), 13, True, RGBColor(0x8F, 0xC7, 0xD1))
    add_text(s, M + 0.25, 2.55, CW - 1.2, 1.2, sl.get("title", "谢谢"), 36, True, WHITE)
    if sl.get("claim"):
        add_text(s, M + 0.25, 3.75, CW - 1.4, 1.4, sl["claim"], 17, False,
                 RGBColor(0xD5, 0xDF, 0xE8), line_spacing=1.3)
    if sl.get("footer"):
        add_text(s, M + 0.25, SH - 1.15, CW - 1.4, 0.4, sl["footer"], 11, False,
                 RGBColor(0x9F, 0xAE, 0xBE))


LAYOUTS = {"title": layout_title, "section": layout_section, "bullets": layout_bullets,
           "figure": layout_figure, "table": layout_table, "comparison": layout_comparison,
           "closing": layout_closing}


# ---------------------------------------------------------------- template mode
def find_layout(prs, kind):
    names = {
        "title": ["title slide", "标题幻灯片", "标题"],
        "section": ["section header", "节标题", "分节"],
        "bullets": ["title and content", "标题和内容", "内容"],
        "figure": ["title and content", "标题和内容", "内容", "title only", "仅标题"],
        "table": ["title and content", "标题和内容", "内容", "title only", "仅标题"],
        "comparison": ["two content", "两栏内容", "比较"],
        "closing": ["title slide", "标题幻灯片", "标题"],
    }.get(kind, ["title and content", "标题和内容"])
    for want in names:
        for lay in prs.slide_layouts:
            if want in (lay.name or "").lower():
                return lay
    return None


def fill_placeholders(slide, sl):
    """Fill title/body/picture placeholders when a template layout was used."""
    filled = set()
    for ph in slide.placeholders:
        t = ph.placeholder_format.type
        idx = ph.placeholder_format.idx
        name = (ph.name or "").lower()
        if idx in filled:
            continue
        if "title" in name or idx == 0:
            ph.text_frame.text = sl.get("title", "")
            filled.add(idx)
        elif "subtitle" in name:
            ph.text_frame.text = sl.get("subtitle", "")
            filled.add(idx)
        elif "body" in name or "content" in name or idx == 1:
            items = sl.get("bullets") or []
            tf = ph.text_frame
            tf.text = ""
            for i, it in enumerate(items):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = ("•  " if int(it.get("level", 0)) == 0 else "–  ") + it["text"]
                p.level = int(it.get("level", 0))
            filled.add(idx)


def _placeholder(slide, kinds):
    """First placeholder whose type is in kinds (PP_PLACEHOLDER members)."""
    for ph in slide.placeholders:
        if ph.placeholder_format.type in kinds:
            return ph
    return None


def fit_placeholder_title(ph, max_lines=2, min_pt=18):
    """Shrink template title text until it fits the placeholder box."""
    tf = ph.text_frame
    text = tf.text.strip()
    if not text:
        return
    w_in = ph.width / 914400.0 - 0.1
    h_in = ph.height / 914400.0 - 0.05
    size = 40
    while size > min_pt:
        lines = wrap_count(text, size, w_in * 72, True)
        if lines <= max_lines and lines * size * 1.05 / 72.0 <= h_in:
            break
        size -= 1
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.size = Pt(size)


def render_template_slide(prs, sl, deck, kind):
    """Template-preserving slide: fills the template's own placeholders.

    Returns None when the template has no suitable layout, so the caller can
    fall back to the built-in layouts instead of emitting an empty slide.
    """
    lay = find_layout(prs, kind)
    if lay is None:
        return None
    s = prs.slides.add_slide(lay)
    W = prs.slide_width / 914400.0
    H = prs.slide_height / 914400.0

    title_ph = _placeholder(s, (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE))
    if title_ph is None:
        for ph in s.placeholders:
            if ph.placeholder_format.idx == 0:
                title_ph = ph
                break
    if title_ph is not None:
        title_ph.text_frame.text = sl.get("title", "")
        try:
            fit_placeholder_title(title_ph, 2)
        except Exception:
            pass

    if kind == "title":
        sub = _placeholder(s, (PP_PLACEHOLDER.SUBTITLE,))
        if sub is not None:
            bits = [x for x in (sl.get("subtitle"), sl.get("authors"), sl.get("venue")) if x]
            sub.text_frame.text = "\n".join(bits)
        if sl.get("takeaway"):
            add_text(s, 0.7, H - 1.05, W - 1.4, 0.4, sl["takeaway"], 13, True,
                     RGBColor(0x0F, 0x6E, 0x7E))
        if sl.get("notes"):
            s.notes_slide.notes_text_frame.text = sl["notes"]
        return s

    body_ph = None
    for ph in s.placeholders:
        if ph.placeholder_format.type in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT) \
                or ph.placeholder_format.idx == 1:
            body_ph = ph
            break

    box = None
    if body_ph is not None:
        box = (body_ph.left / 914400.0, body_ph.top / 914400.0,
               body_ph.width / 914400.0, body_ph.height / 914400.0)

    items = sl.get("bullets") or []
    fig = sl.get("figure") or {}
    tab = sl.get("table") or {}

    if fig.get("path") and os.path.exists(fig["path"]):
        iw, ih = Image.open(fig["path"]).size
        if box:
            x, y, w, h = box
        else:
            x, y, w, h = 0.7, 1.6, W - 1.4, H - 2.4
        cap_h = 0.42 if fig.get("caption") else 0.0
        bullet_h = 0.0
        if items:
            bullet_h = max(0.9, min(1.5, 0.36 * len(items) + 0.35))
        avail_h = h - cap_h - bullet_h
        pw = min(w, avail_h * iw / ih)
        ph_ = pw * ih / iw
        s.shapes.add_picture(fig["path"], Inches(x + (w - pw) / 2), Inches(y),
                             Inches(pw), Inches(ph_))
        if fig.get("caption"):
            add_text(s, x, y + ph_ + 0.04, w, 0.36,
                     f"{fig.get('label', '')}  {fig['caption']}", 10, False, GRAY)
        if items:
            by = y + ph_ + cap_h + 0.08
            add_bullets(s, x, by, w, max(0.6, y + h - by), items,
                        size=fit_bullets(items, w, max(0.6, y + h - by), 14, 10))
    elif tab.get("rows") and box:
        x, y, w, h = box
        n_rows = len(tab["rows"])
        n_cols = max(len(r) for r in tab["rows"])
        row_h = min(0.38, (h - 0.5) / max(1, n_rows))
        tbl = s.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y),
                                 Inches(w), Inches(row_h * n_rows)).table
        for c in range(n_cols):
            tbl.columns[c].width = Emu(int(Inches(w) / n_cols))
        for ri, row in enumerate(tab["rows"]):
            tbl.rows[ri].height = Emu(int(Inches(row_h)))
            for ci in range(n_cols):
                cell = tbl.cell(ri, ci)
                cell.text = str(row[ci]) if ci < len(row) else ""
                cell.margin_left = Inches(0.06)
                for p in cell.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(11)
    elif items and body_ph is not None:
        tf = body_ph.text_frame
        tf.text = ""
        size = 18
        while size > 12 and sum(wrap_count(("•  " + it["text"]), size,
                                           (box[2] - 0.3) * 72) * size * 1.15
                                for it in items) > (box[3] - 0.15) * 72:
            size -= 0.5
        for i, it in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = ("•  " if int(it.get("level", 0)) == 0 else "–  ") + it["text"]
            p.level = int(it.get("level", 0))
            for r in p.runs:
                r.font.size = Pt(size)

    if sl.get("subtitle") and kind != "title":
        add_text(s, 0.7, 1.12, W - 1.4, 0.4, sl["subtitle"], 12, False, GRAY)

    src = evidence_line(sl.get("evidence"))
    has_footer_ph = any(ph.placeholder_format.type in
                        (PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER)
                        for ph in s.placeholders)
    if src and not has_footer_ph:
        add_text(s, 0.7, H - 0.34, W - 1.4, 0.24, src, 8.5, False, ACCENT)
    if sl.get("notes"):
        s.notes_slide.notes_text_frame.text = sl["notes"]
    return s


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=None)
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(args.plan))

    def _resolve(p):
        if not p:
            return p
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))

    for sl in plan.get("slides", []):
        for key in ("figure", "table"):
            obj = sl.get(key)
            if isinstance(obj, dict) and obj.get("path"):
                obj["path"] = _resolve(obj["path"])
    deck = plan.get("deck", {})
    slides = plan.get("slides", [])
    if not slides:
        print(json.dumps({"status": "error", "reason": "no_slides"}, ensure_ascii=False))
        return 2

    max_slides = int(deck.get("max_slides", 0) or 0)
    warnings = []
    if max_slides and len(slides) > max_slides:
        warnings.append(f"slides {len(slides)} > max_slides {max_slides}; trimmed")
        slides = slides[:max_slides]

    template = args.template or deck.get("template")
    use_template = bool(template and os.path.exists(template))
    if use_template:
        prs = Presentation(template)
    else:
        prs = Presentation()
    if not prs.slide_width or prs.slide_width < Inches(12):
        prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
    else:
        # keep template geometry, but recompute content width for the actual size
        pass

    total = len(slides)
    evidence_map = {}
    size_report = []

    for i, sl in enumerate(slides):
        kind = sl.get("type", "bullets")
        # a page-level claim doubles as the subtitle when none was given — but for
        # figure/table pages the claim is usually the caption, which the title
        # already carries, so reuse it only when it adds something new.
        if kind in ("figure", "table", "comparison") and not sl.get("subtitle") \
                and sl.get("claim"):
            claim = re.sub(r"\s+", " ", sl["claim"]).strip()
            title_norm = re.sub(r"\s+", " ", sl.get("title") or "").replace("…", "").strip()
            if claim and not title_norm.endswith(claim.replace("…", "")) \
                    and claim[:40] not in title_norm:
                sl["subtitle"] = claim
        s = None
        got = None
        if use_template:
            s = render_template_slide(prs, sl, deck, kind)
        if s is None:
            s = base_slide(prs, None)
            fun = LAYOUTS.get(kind, layout_bullets)
            try:
                got = fun(s, sl, deck)
            except Exception as e:                       # never fail the whole deck
                tb = traceback.format_exc().strip().splitlines()[-3:]
                warnings.append(f"slide {i+1} ({kind}) render error: {e!r} | " +
                                " <- ".join(x.strip() for x in tb))
                got = None
            if kind not in ("title", "section", "closing"):
                chrome(s, deck, i + 1, total, evidence_line(sl.get("evidence")))
        elif not use_template:
            pass
        if isinstance(got, (int, float)):
            size_report.append({"slide": i + 1, "body_pt": got})
        if sl.get("notes"):
            s.notes_slide.notes_text_frame.text = sl["notes"]
        evidence_map[sl.get("id", f"s{i+1}")] = {
            "page": sl.get("page"),
            "claim": sl.get("claim", ""),
            "evidence": sl.get("evidence", []),
        }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    prs.save(args.out)
    if args.evidence:
        with open(args.evidence, "w", encoding="utf-8") as f:
            json.dump({"schema": "evidence-map/v1", "slides": evidence_map}, f,
                      ensure_ascii=False, indent=1)

    print(json.dumps({"status": "ok", "out": args.out, "slides": total,
                      "template": bool(use_template), "warnings": warnings,
                      "body_sizes": size_report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
