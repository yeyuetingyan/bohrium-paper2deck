#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一份两页的合成演示 PDF，供 examples/ 现场复现用（纯标准库，无第三方依赖）。

为什么不在仓库里放 PDF：平台的 Skill 资源预检只接受 UTF-8 文本文件，
二进制样例会被判为 unsupported Skill resource。样例改为脚本生成：

    python examples/make_sample_pdf.py examples/sample.pdf
    python scripts/parse_document.py --case examples/example_case.json --out /tmp/demo

内容为合成文本（虚构的稀疏注意力实验），不是任何真实论文，也不含真实实验数据。
"""
from __future__ import annotations

import sys

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 64.0
BODY_W = PAGE_W - 2 * MARGIN

TITLE = "Sparse Attention Routing for Long-Document Summarization"
AUTHORS = "Demo Author, Second Author"
AFFIL = "Institute of Synthetic Examples, Nowhere"

ABSTRACT = (
    "We describe a synthetic paper used to exercise a PDF parser. The document "
    "contains a title block, an abstract, numbered sections, running text, and a "
    "ruled table with numeric cells. All numbers are invented for demonstration "
    "and must not be cited as experimental results. The text is long enough to "
    "wrap over several lines and to cross a page boundary, so that column order, "
    "line joining, and page anchors can be checked."
)

S1 = (
    "In this paper we study whether a sparse routing layer can match full self-attention "
    "on long-document summarization under a fixed token budget. A common design keeps a "
    "window of recent tokens and routes the rest through a sparse index; we adopt the same "
    "structure so that the synthetic example exercises headings, paragraphs and a table. "
    "The question is narrow on purpose: it asks what a reader must be able to recover from "
    "the note skeleton, not whether the numbers are real."
)

S1B = (
    "Two failure modes motivate the checks performed by the parser: running heads "
    "leaking into body text, and table cells being split at decimal points. Both "
    "are layout artefacts rather than content, and both are detectable without any "
    "knowledge of the subject matter. Self-attention makes the second failure more "
    "likely, because numbers and decimal points sit next to each other in the table."
)

S2 = (
    "The routing layer scores each chunk with a small bilinear model and keeps the "
    "top-k chunks under a token budget of 4096 tokens. Chunk scores are recomputed "
    "every four layers. Because the budget is fixed, latency grows linearly with "
    "document length rather than quadratically, which is the only property the "
    "synthetic table is meant to illustrate."
)

S3 = (
    "Sparse routing reaches 27.8 BLEU at 156 ms latency on the synthetic benchmark, "
    "improving over a Window-512 baseline by 0.9 BLEU while reducing latency by 17%. "
    "Full self-attention still scores 28.4 BLEU, so the routing layer trades 0.6 BLEU "
    "for a 62% latency reduction. These numbers are placeholders chosen to look "
    "plausible, not measurements."
)

S4 = (
    "A limitation of this synthetic study is that no real dataset was used, so the "
    "numbers cannot be generalized beyond the page. Future work should repeat the "
    "comparison on an open benchmark. The example itself is reproducible from this "
    "script alone: no external data, no network access, and no binary assets."
)

TABLE = [
    ["Method", "BLEU", "Latency (ms)"],
    ["Full attention", "28.4", "412"],
    ["Window-512", "26.9", "187"],
    ["Sparse routing", "27.8", "156"],
]


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, size: float, width: float, bold: bool = False) -> list:
    """按估算字宽折行（Times 平均字宽约 0.5 em，粗体略宽）。"""
    per_char = size * (0.53 if bold else 0.50)
    max_chars = max(12, int(width / per_char))
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Page:
    def __init__(self):
        self.ops = []
        self.y = PAGE_H - MARGIN

    def text(self, x, y, s, size, bold=False):
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size:.1f} Tf {x:.1f} {y:.1f} Td ({_esc(s)}) Tj ET")

    def para(self, text, size=10.0, bold=False, lead=1.45, gap=6.0, x=MARGIN):
        for line in _wrap(text, size, BODY_W, bold):
            self.y -= size * lead
            self.text(x, self.y, line, size, bold)
        self.y -= gap

    def heading(self, text, size=11.5):
        self.y -= 6.0
        self.y -= size * 1.4
        self.text(MARGIN, self.y, text, size, bold=True)
        self.y -= 4.0

    def caption(self, text, size=9.0):
        for line in _wrap(text, size, BODY_W):
            self.y -= size * 1.35
            self.text(MARGIN, self.y, line, size, bold=False)
        self.y -= 4.0

    def table(self, rows, col_w, row_h=16.0, size=9.0):
        x0 = MARGIN
        top = self.y
        n_rows, n_cols = len(rows), len(rows[0])
        width = sum(col_w)
        # 外框 + 横线
        for r in range(n_rows + 1):
            y = top - r * row_h
            self.ops.append(f"0.6 w {x0:.1f} {y:.1f} m {x0 + width:.1f} {y:.1f} l S")
        # 竖线
        x = x0
        for c in range(n_cols + 1):
            self.ops.append(f"0.6 w {x:.1f} {top:.1f} m {x:.1f} {top - n_rows * row_h:.1f} l S")
            if c < n_cols:
                x += col_w[c]
        # 单元格文字
        for r, row in enumerate(rows):
            base = top - r * row_h - row_h + 4.6
            cx = x0 + 3.0
            for c, cell in enumerate(row):
                self.text(cx, base, cell, size, bold=(r == 0))
                cx += col_w[c]
        self.y = top - n_rows * row_h - 6.0


def build_pages():
    p1 = Page()
    for line in _wrap(TITLE, 14.0, BODY_W, bold=True):
        p1.y -= 14.0 * 1.35
        p1.text(MARGIN, p1.y, line, 14.0, bold=True)
    p1.y -= 15.0
    p1.text(MARGIN, p1.y, AUTHORS, 10.0, bold=False)
    p1.y -= 13.0
    p1.text(MARGIN, p1.y, AFFIL, 9.0, bold=False)
    p1.y -= 14.0
    p1.heading("Abstract", 11.0)
    p1.para(ABSTRACT)
    p1.heading("1  Introduction")
    p1.para(S1)
    p1.para(S1B)

    p2 = Page()
    p2.heading("2  Method")
    p2.para(S2)
    p2.heading("3  Results")
    p2.para(S3)
    p2.caption("Table 1: Synthetic configurations. Numbers are placeholders, not measurements.")
    p2.table(TABLE, col_w=[190.0, 90.0, 120.0])
    p2.heading("4  Conclusion")
    p2.para(S4)
    return [p1, p2]


def build_pdf(pages, path):
    n = len(pages)
    objs = []
    page_ids = [5 + 2 * i for i in range(n)]

    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold /Encoding /WinAnsiEncoding >>")

    for i, page in enumerate(pages):
        content = "\n".join(page.ops).encode("latin-1", "replace")
        page_id = page_ids[i]
        content_id = page_id + 1
        objs.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
             f"/Contents {content_id} 0 R >>").encode())
        objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                    + content + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for idx, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
    with open(path, "wb") as f:
        f.write(out)
    return path


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    build_pdf(build_pages(), out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
