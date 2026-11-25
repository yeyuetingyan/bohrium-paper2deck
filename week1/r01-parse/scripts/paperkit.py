#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paperkit — 共享文档解析内核（供 week1 各 Skill 复用）。

只做四件事，每件都可单独调用、可复现：
  1. load_case()      读 /input/case.json（或任意 case 文件），容错取字段、解析材料路径
  2. PDFDoc           逐页抽取带坐标的文本行，按栏序重排，去页眉页脚，识别标题层级/图/表
  3. to_markdown()    把版面还原成带页码锚点的 Markdown（表格用 GFM，表格不可靠时保留渲染图）
  4. emit_result()    按 output_contract 组装 result.json（status / 证据 / 不确定项 / 产物哈希）

约定：不联网、不写 Skill 目录以外的位置；解析不确定的内容写入 uncertainty，不猜测补齐。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from collections import Counter

try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF < 1.24
    import fitz

VERSION = "paperkit/1.0"

# ---------------------------------------------------------------- 基础工具

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def norm(s: str) -> str:
    """压缩空白，去掉软连字符；不改动字符本身。"""
    s = (s or "").replace("\u00ad", "")
    return re.sub(r"[ \t\u3000]+", " ", s.replace("\r", " ")).strip()


def cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    return len(CJK_RE.findall(s)) / max(1, len(s))


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SENT_SPLIT = re.compile(r"(?<=[。！？；.!?])\s+|(?<=[。！？；])")


def sentences(text: str):
    parts = [norm(p) for p in SENT_SPLIT.split(text or "") if norm(p)]
    return parts


NUM_RE = re.compile(
    r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:\s?[×x]\s?10\s?\^?\s?[-−]?\d+)?"
    r"\s?(?:%|‰|K|k|M|G|m|cm|mm|nm|µm|μmol|mol|kg|g|mg|s|ms|h|Hz|kHz|MHz|"
    r"eV|V|mA|A|Pa|kPa|MPa|K|°C|mL|L|µL|μL|rpm|Da|kDa|bp|kb|Mb|GB|MB)?"
)


def numbers(text: str):
    """抽取数字+单位的字面量，用于翻译/润色后的保真核对。"""
    return [m.group(0).strip() for m in NUM_RE.finditer(text or "")]


HEDGE_WORDS = [
    "可能", "或许", "似乎", "提示", "表明", "倾向于", "在一定程度上", "初步",
    "尚不能", "无关", "不显著", "有限", "有待", "推测",
    "may", "might", "could", "suggest", "indicate", "appear", "likely",
    "possibly", "consistent with", "we speculate", "not significant",
]
ABSOLUTE_WORDS = ["证明", "证实", "必然", "完全", "毫无疑问", "prove", "proves",
                  "demonstrate", "confirms", "always", "never", "undoubtedly"]


def hedges(text: str):
    low = (text or "").lower()
    return [w for w in HEDGE_WORDS if w.lower() in low]


def absolutes(text: str):
    low = (text or "").lower()
    return [w for w in ABSOLUTE_WORDS if w.lower() in low]


# ---------------------------------------------------------------- case 读取

CASE_PAPER_KEYS = ("paper_path", "pdf", "pdf_path", "paper", "input_paper", "document")
CASE_TEMPLATE_KEYS = ("template_path", "template", "template_pptx")
CASE_LIMIT_KEYS = ("max_slides", "slide_count", "max_pages", "page_limit")
CASE_AUDIENCE_KEYS = ("audience", "duration_min", "venue")


def _dig(d, keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    for parent in ("input", "inputs", "case", "task", "materials", "files"):
        sub = d.get(parent)
        if isinstance(sub, dict):
            got = _dig(sub, keys, None)
            if got is not None:
                return got
    return default


def load_case(path: str):
    """读 case.json；返回 (case_dict, ctx)。ctx 里放解析后的绝对路径与契约。"""
    case = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
    base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
    contract = case.get("output_contract") or _dig(case, ("output_contract",), {}) or {}

    def resolve(p):
        if not p:
            return None
        p = os.path.expanduser(str(p))
        if os.path.isabs(p):
            return p
        for cand in (os.path.join(base, p), os.path.join("/input", p), p):
            if os.path.exists(cand):
                return os.path.abspath(cand)
        return os.path.abspath(os.path.join(base, p))

    paper = resolve(_dig(case, CASE_PAPER_KEYS))
    if not paper or not os.path.exists(paper):
        guess = find_files(base, (".pdf",)) or find_files("/input", (".pdf",))
        paper = guess[0] if guess else None

    ctx = {
        "case": case,
        "case_id": str(case.get("case_id") or case.get("id") or
                       _dig(case, ("case_id", "id"), "case")),
        "base": base,
        "paper": paper,
        "template": resolve(_dig(case, CASE_TEMPLATE_KEYS)),
        "audience": _dig(case, CASE_AUDIENCE_KEYS),
        "limits": {k: _dig(case, (k,)) for k in CASE_LIMIT_KEYS if _dig(case, (k,))},
        "contract": contract,
        "notes": _dig(case, ("notes", "instructions", "brief", "prompt")),
        "language": str(_dig(case, ("language", "lang", "target_language"), "") or ""),
    }
    return case, ctx


def find_files(root: str, exts):
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(tuple(exts)):
                out.append(os.path.join(dirpath, f))
    return out


# ---------------------------------------------------------------- PDF 解析

HEADING_WORDS = {
    "abstract", "introduction", "related work", "background", "method",
    "methods", "methodology", "approach", "experiments", "experimental setup",
    "results", "results and discussion", "discussion", "analysis",
    "conclusion", "conclusions", "limitations", "future work",
    "references", "acknowledgments", "acknowledgements", "appendix",
    "摘要", "引言", "前言", "相关工作", "方法", "实验", "结果", "讨论",
    "结论", "参考文献", "致谢", "附录",
}

CAP_RE = re.compile(
    r"^\s*(?P<label>(?:Figure|Fig\.?|Table|Scheme|Algorithm|图|表)\s*"
    r"(?P<num>[0-9]{1,3}|[IVX]{1,5})[a-z]?)\s*[.:|：]?\s*(?P<cap>.*)$",
    re.IGNORECASE,
)
# 题注标签后紧跟分隔符（"Table 1:" / "Table 1." / "Table 1 |"），用于区分正文引用
CAP_SEP_RE = re.compile(
    r"^\s*(?:Figure|Fig\.?|Table|Scheme|Algorithm|图|表)\s*"
    r"(?:[0-9]{1,3}|[IVX]{1,5})[a-z]?\s*[.:|：]", re.IGNORECASE)


def caption_like(text: str) -> bool:
    """判断一行是否像图/表题注，排除"Table 1 reports ..."这类正文引用句。

    题注的形态：标签后有分隔符，或标签后直接接短语；正文引用句通常是
    "Table 1 reports/shows/compares ..."，标签后直接跟小写动词，且整句很长。
    """
    m = CAP_RE.match(text)
    if not m:
        return False
    cap = (m.group("cap") or "").strip()
    if len(text) > 300 or len(cap.split()) > 45:
        return False
    if not CAP_SEP_RE.match(text) and cap[:1].islower():
        return False
    return True


NUM_HEAD_RE = re.compile(r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(?P<title>[A-Z\u4e00-\u9fff][^.;:!?]{2,70})$")

BAD_TITLE = re.compile(
    r"(arxiv|doi:|https?://|preprint|received|accepted|published|copyright|"
    r"under review|proceedings of|vol\.\s*\d|issn|isbn)", re.IGNORECASE)

# 出版方/会议/arXiv 的版式声明，属于板材信息，不是论文正文
BOILERPLATE = re.compile(
    r"(provided proper attribution|permission to|reproduce the tables|journalistic|"
    r"scholarly works|all rights reserved|copyright\s*©|©\s?\d{4}|"
    r"proceedings of the|conference on neural information|"
    r"arxiv:\d{4}\.\d{4,5}|under review|preprint\b|"
    r"this work is licensed|creative commons|corresponding author)",
    re.IGNORECASE)


class PDFDoc:
    """逐页结构化抽取。lines 保留坐标，便于锚点与栏序重排。"""

    def __init__(self, path: str, max_pages: int = 60, dpi: int = 180):
        self.path = path
        self.dpi = dpi
        self.warnings = []
        self.doc = fitz.open(path)
        if self.doc.needs_pass:
            raise RuntimeError("encrypted_pdf")
        self.page_count = self.doc.page_count
        self.pages = list(self.doc)[:max_pages]
        if max_pages and self.page_count > max_pages:
            self.warnings.append(f"truncated to first {max_pages} of {self.page_count} pages")
        self.size = self.pages[0].rect if self.pages else fitz.Rect(0, 0, 612, 792)
        self.lines = []
        for p in self.pages:
            self.lines.extend(self._page_lines(p))
        self.body_pt = self._body_size()
        self.running = self._detect_running_heads()

    # -- 行抽取
    def _page_lines(self, page):
        data = page.get_text("dict")
        width = page.rect.width
        out = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                all_spans = line.get("spans", [])
                spans = [s for s in all_spans if s.get("text", "").strip()]
                if not spans:
                    continue
                # 保留空白 span，否则单词之间的空格会丢失
                text = norm("".join(s.get("text", "") for s in all_spans))
                if not text:
                    continue
                size = max(s["size"] for s in spans)
                bold = any("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16)
                           for s in spans)
                x0, y0, x1, y1 = line["bbox"]
                out.append({
                    "text": text, "size": round(size, 1), "bold": bold,
                    "x0": round(x0, 1), "y0": round(y0, 1),
                    "x1": round(x1, 1), "y1": round(y1, 1),
                    "w": width, "page": page.number + 1,
                    "dir": line.get("dir", (1, 0)),
                })
        return out

    def _body_size(self):
        c = Counter()
        for ln in self.lines:
            c[ln["size"]] += len(ln["text"])
        return c.most_common(1)[0][0] if c else 10.0

    def _detect_running_heads(self):
        """跨页重复出现的短行（页眉/页脚/页码）→ 文本集合，供过滤。"""
        counter = Counter()
        pages = {ln["page"] for ln in self.lines}
        for ln in self.lines:
            t = ln["text"]
            if len(t) <= 80 and (ln["y0"] < self.size.height * 0.08 or
                                 ln["y1"] > self.size.height * 0.92):
                counter[re.sub(r"\d+", "#", t.lower())] += 1
        need = max(3, int(len(pages) * 0.5))
        return {k for k, v in counter.items() if v >= need}

    def is_running(self, ln):
        t = re.sub(r"\d+", "#", ln["text"].lower())
        return (len(ln["text"]) <= 80 and t in self.running and
                (ln["y0"] < self.size.height * 0.08 or
                 ln["y1"] > self.size.height * 0.92))

    def is_boilerplate(self, ln):
        """版式声明、arXiv 戳记、页边孤立的页码：不属于正文。"""
        t = ln["text"]
        if BOILERPLATE.search(t):
            return True
        if re.fullmatch(r"[-\u2013\u2014·\s]*\d{1,3}[-\u2013\u2014·\s]*", t) and (
                ln["y0"] < self.size.height * 0.08 or ln["y1"] > self.size.height * 0.92):
            return True
        return False

    # -- 结构判定
    def is_heading(self, ln):
        t = ln["text"]
        if len(t) > 120 or len(t) < 2:
            return False
        if re.fullmatch(r"[\d\W]{1,6}", t):
            return False
        if BAD_TITLE.search(t) or re.match(r"^(Provided|Permission|Copyright|©|\u00a9)", t, re.I):
            return False
        if not self._heading_ok(t):
            return False
        low = t.lower().strip(" .:：0123456789")
        if low in HEADING_WORDS:
            return True
        if NUM_HEAD_RE.match(t) and ln["size"] >= self.body_pt * 0.95 and len(t) < 90:
            return True
        if ln["bold"] and ln["size"] >= self.body_pt * 0.95 and len(t) < 70:
            if t.endswith((":", "：")) or re.search(r"[∗†‡@]", t):
                return False
            return True
        if ln["size"] >= self.body_pt * 1.2 and len(t) < 90:
            return True
        return False

    @staticmethod
    def _heading_ok(t: str) -> bool:
        """粗筛：含过多标点/邮箱/网址的行不是标题。"""
        if "@" in t or "http" in t.lower():
            return False
        punct = sum(1 for ch in t if ch in ",;，；、")
        if punct >= 3:
            return False
        return True

    def heading_level(self, ln):
        t = ln["text"]
        low = t.lower().strip(" .:：0123456789")
        if low in HEADING_WORDS:
            return 1
        m = re.match(r"^(\d+(?:\.\d+)*)", t)
        if m:
            return min(3, m.group(1).count(".") + 1)
        if ln["size"] >= self.body_pt * 1.45:
            return 1
        if ln["size"] >= self.body_pt * 1.18:
            return 2
        return 2

    def detect_title(self):
        first = [l for l in self.lines if l["page"] == 1]
        if not first:
            return ""
        cands = [l for l in first if l["size"] >= self.body_pt * 1.35
                 and len(l["text"]) > 10 and not BAD_TITLE.search(l["text"])]
        if not cands:
            return ""
        cands.sort(key=lambda d: (-d["size"], d["y0"]))
        top = cands[0]
        parts = [l["text"] for l in cands
                 if abs(l["size"] - top["size"]) < 0.6 and l["y0"] < top["y0"] + 120]
        parts.sort(key=len, reverse=True)
        title = parts[0] if parts else top["text"]
        if len(title) < 14 and len(parts) > 1:
            title = norm(" ".join(parts[:2]))
        return title[:300]

    def detect_authors(self):
        """题名下方、摘要之前的一行作者/单位；不越过 Abstract 标题。"""
        first = [l for l in self.lines if l["page"] == 1]
        if not first:
            return ""
        title = self.detect_title()
        if not title:
            return ""
        ti = next((i for i, l in enumerate(first) if l["text"] == title), None)
        if ti is None:
            return ""
        for l in first[ti + 1: ti + 5]:
            t = l["text"]
            low = t.lower().strip(" .:：")
            if low in HEADING_WORDS:
                return ""
            if t.endswith((".", "。")) or len(t) > 120:
                continue
            if re.search(r"@|university|institute|department|laborator|大学|学院|研究所", t, re.I):
                continue
            if len(t) > 8:
                return t[:200]
        return ""

    # -- 阅读顺序：先分带，再按栏
    def ordered(self, page_no: int):
        lines = [l for l in self.lines if l["page"] == page_no and not self.is_running(l)]
        if not lines:
            return []
        width = self.size.width
        narrow = [l for l in lines if (l["x1"] - l["x0"]) < width * 0.62]
        two_col = False
        if len(narrow) >= 0.6 * len(lines) and len(lines) >= 6:
            left = [l for l in narrow if (l["x0"] + l["x1"]) / 2 < width * 0.5]
            right = [l for l in narrow if (l["x0"] + l["x1"]) / 2 >= width * 0.5]
            two_col = len(left) >= 3 and len(right) >= 3
        if not two_col:
            return sorted(lines, key=lambda d: (d["y0"], d["x0"]))
        # 全宽行作为分带边界
        bands, cur = [], []
        for l in sorted(lines, key=lambda d: d["y0"]):
            wide = (l["x1"] - l["x0"]) > width * 0.72
            if wide:
                if cur:
                    bands.append(("cols", cur))
                    cur = []
                bands.append(("wide", [l]))
            else:
                cur.append(l)
        if cur:
            bands.append(("cols", cur))
        ordered = []
        for kind, group in bands:
            if kind == "wide":
                ordered.extend(group)
                continue
            left = sorted([g for g in group if (g["x0"] + g["x1"]) / 2 < width * 0.5],
                          key=lambda d: d["y0"])
            right = sorted([g for g in group if (g["x0"] + g["x1"]) / 2 >= width * 0.5],
                           key=lambda d: d["y0"])
            ordered.extend(left + right)
        return ordered

    # -- 段落合并
    def paragraphs(self, page_no: int, skip_boxes=None):
        lines = [l for l in self.ordered(page_no) if not self.is_boilerplate(l)]
        if skip_boxes:
            def inside(ln):
                cx = (ln["x0"] + ln["x1"]) / 2
                cy = (ln["y0"] + ln["y1"]) / 2
                return any(x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2
                           for (x0, y0, x1, y1) in skip_boxes)
            lines = [l for l in lines if not inside(l)]
        # 章节号常被排版成独立一行（"1" 在左缘），与下一行标题合并
        merged_lines = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            if re.fullmatch(r"\d{1,2}(?:\.\d{1,2}){0,2}", ln["text"].strip()) and i + 1 < len(lines):
                nxt = lines[i + 1]
                if abs(nxt["y0"] - ln["y0"]) < ln["size"] * 4 and \
                        (self.is_heading(nxt) or nxt["bold"] or nxt["size"] >= ln["size"] * 1.05):
                    combined = dict(nxt)
                    combined["text"] = f"{ln['text'].strip()} {nxt['text']}"
                    merged_lines.append(combined)
                    i += 2
                    continue
            merged_lines.append(ln)
            i += 1
        lines = merged_lines
        paras, cur = [], []
        for ln in lines:
            if self.is_heading(ln) or caption_like(ln["text"]):
                if cur:
                    paras.append(cur)
                    cur = []
                paras.append([ln])
                continue
            if cur:
                prev = cur[-1]
                same_col = abs((prev["x0"] + prev["x1"]) / 2 -
                               (ln["x0"] + ln["x1"]) / 2) < self.size.width * 0.12
                gap = ln["y0"] - prev["y1"]
                if same_col and gap < max(4.0, prev["size"] * 0.75) and not prev["text"].endswith(("。", ".", "?", "！")):
                    cur.append(ln)
                    continue
                if same_col and gap < prev["size"] * 1.8:
                    cur.append(ln)
                    continue
                paras.append(cur)
                cur = [ln]
            else:
                cur = [ln]
        if cur:
            paras.append(cur)
        out = []
        for group in paras:
            text = ""
            for ln in group:
                if text and cjk_ratio(ln["text"]) > 0.3:
                    text += ln["text"]          # 中文行间不加空格
                elif text and text.endswith("-"):
                    text = text[:-1] + ln["text"]
                else:
                    text = (text + " " + ln["text"]).strip()
            out.append({"text": norm(text), "page": page_no,
                        "y0": group[0]["y0"], "size": group[0]["size"],
                        "bold": all(g["bold"] for g in group),
                        "heading": self.is_heading(group[0]) and len(group) == 1,
                        "level": self.heading_level(group[0]) if self.is_heading(group[0]) else 0})
        return out

    # -- 图表
    def captions(self):
        """识别图/表题注，并把折行续接的尾巴接上（以句末标点为界）。"""
        lines = sorted([l for l in self.lines if not self.is_running(l)],
                       key=lambda d: (d["page"], d["y0"], d["x0"]))
        caps = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            if not caption_like(ln["text"]):
                i += 1
                continue
            m = CAP_RE.match(ln["text"])
            label = norm(m.group("label"))
            head = label.split()[0].rstrip(".")
            kind = "table" if head.lower().startswith(("table", "表")) else "figure"
            text = norm(m.group("cap"))
            y1 = ln["y1"]
            j = i + 1
            guard = 0
            while j < len(lines) and guard < 4 and not text.endswith((".", "。", "!", "?", "！", "？", ")", "）", "]")) \
                    and lines[j]["page"] == ln["page"] and 0 <= lines[j]["y0"] - y1 <= max(16, ln["size"] * 1.8):
                text = norm(text + " " + lines[j]["text"])
                y1 = lines[j]["y1"]
                j += 1
                guard += 1
            caps.append({"label": label, "kind": kind, "text": text,
                         "page": ln["page"], "y0": ln["y0"], "y1": y1})
            i = j
        return caps

    def figures(self, out_dir=None):
        caps = self.captions()
        figs, seen = [], set()
        for page in self.pages:
            pno = page.number + 1
            page_caps = [c for c in caps if c["page"] == pno and c["kind"] == "figure"]
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
                if r.width < 90 or r.height < 60:
                    continue
                seen.add(xref)
                fname = f"fig_p{pno}_{len(figs)+1}.png"
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    pix = page.get_pixmap(matrix=fitz.Matrix(self.dpi / 72.0, self.dpi / 72.0),
                                          clip=r, alpha=False)
                    pix.save(os.path.join(out_dir, fname))
                cap, best = None, 1e9
                for c in page_caps:
                    d = abs(c["y0"] - (r.y1 if c["y0"] >= r.y1 else r.y0))
                    if d < best and d < 120:
                        best, cap = d, c
                figs.append({"id": f"fig_p{pno}_{len(figs)+1}", "page": pno,
                             "file": fname if out_dir else "",
                             "bbox": [round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1)],
                             "label": cap["label"] if cap else "",
                             "caption": cap["text"] if cap else ""})
        figs.sort(key=lambda f: (f["page"], f["bbox"][1]))
        return figs

    def tables(self, out_dir=None):
        caps = self.captions()
        out = []
        for page in self.pages:
            try:
                found = page.find_tables()
            except Exception:
                continue
            for tab in getattr(found, "tables", []):
                try:
                    rows = cells_from_words(page, tab)
                    if not rows:
                        rows = [[norm(c) for c in row] for row in tab.extract()]
                except Exception:
                    continue
                rows = [r for r in rows if any(r)]
                if len(rows) < 2:
                    continue
                bbox = [round(v, 1) for v in tab.bbox]
                cap, best = None, 1e9
                for c in caps:
                    if c["kind"] != "table" or c["page"] != page.number + 1:
                        continue
                    d = abs(c["y0"] - bbox[1])
                    if d < best:
                        best, cap = d, c
                fname = ""
                if out_dir:
                    try:
                        r = fitz.Rect(*tab.bbox)
                        r = fitz.Rect(r.x0 - 2, r.y0 - 2, r.x1 + 2, r.y1 + 2) & page.rect
                        pix = page.get_pixmap(matrix=fitz.Matrix(self.dpi / 72.0, self.dpi / 72.0),
                                              clip=r, alpha=False)
                        fname = f"tab_p{page.number+1}_{len(out)+1}.png"
                        pix.save(os.path.join(out_dir, fname))
                    except Exception:
                        fname = ""
                out.append({"id": f"tab_p{page.number+1}_{len(out)+1}",
                            "page": page.number + 1, "bbox": bbox,
                            "file": fname, "rows": rows,
                            "n_rows": len(rows),
                            "n_cols": max(len(r) for r in rows),
                            "label": cap["label"] if cap and best < 160 else "",
                            "caption": cap["text"] if cap and best < 160 else "",
                            "reliable": table_reliable(rows)})
        return out

    def page_text(self, pno: int):
        return "\n".join(p["text"] for p in self.paragraphs(pno))


def _cell_text(words):
    """单元格内的词按阅读顺序拼接：CJK 之间不加空格，标点前不加空格。"""
    words = sorted(words, key=lambda w: (round((w[1] + w[3]) / 2, 0), w[0]))
    out = ""
    for w in words:
        t = w[4]
        if not out:
            out = t
            continue
        if cjk_ratio(out[-1]) > 0.3 and cjk_ratio(t[0]) > 0.3:
            out += t
        elif t[0] in ",.;:)]}%，。；：）":
            out += t
        else:
            out += " " + t
    return norm(out)


def _y_groups(words):
    """把单元格内的词按基线聚类成若干文本行。"""
    if not words:
        return []
    words = sorted(words, key=lambda w: (w[1] + w[3]) / 2)
    heights = [w[3] - w[1] for w in words]
    tol = max(2.5, 0.6 * (sum(heights) / len(heights)))
    groups, cur, last = [], [], None
    for w in words:
        yc = (w[1] + w[3]) / 2
        if last is not None and yc - last > tol:
            groups.append(cur)
            cur = []
        cur.append(w)
        last = yc
    if cur:
        groups.append(cur)
    return groups


def cells_from_words(page, tab):
    """用检测到的单元格矩形收集词，重建行列表；比 tab.extract() 保真。

    表格线检测给出行列几何，词序仍取原文，因此 "88.3" 不会被拆成 "883"+"."。
    若一个单元格实际压着多行文本（无横线的三线表常见），按基线把它拆成多行。
    """
    try:
        rects = [fitz.Rect(c) for c in tab.cells]
    except Exception:
        return None
    if not rects:
        return None
    words = page.get_text("words")
    rows = {}
    for r in rects:
        rows.setdefault(round(r.y0, 1), []).append(r)
    grid = []
    for key in sorted(rows):
        line_cells = sorted(rows[key], key=lambda r: r.x0)
        cell_words = []
        for r in line_cells:
            inside = [w for w in words
                      if r.x0 - 0.5 <= (w[0] + w[2]) / 2 <= r.x1 + 0.5
                      and r.y0 - 0.5 <= (w[1] + w[3]) / 2 <= r.y1 + 0.5]
            cell_words.append(_y_groups(inside))
        counts = [len(g) for g in cell_words]
        if counts and max(counts) > 1 and len(set(counts)) == 1:
            for i in range(counts[0]):          # 多行单元格逐行拆开
                grid.append([_cell_text(g[i]) for g in cell_words])
        else:
            grid.append([_cell_text(w for g in groups for w in g) for groups in cell_words])
    grid = [g for g in grid if any(g)]
    if grid:
        n = max(len(g) for g in grid)
        grid = [g + [""] * (n - len(g)) for g in grid]
        keep = [c for c in range(n) if any(g[c].strip() for g in grid)]
        grid = [[g[c] for c in keep] for g in grid]
    return grid


def table_reliable(rows) -> bool:
    """单元格能否直接写成 Markdown 而不至于改写数值/归属。

    以下任一情况判为不可靠，改用页面渲染图并标注：
      · 列数不一致（>1 种）
      · 空单元格超过 45%
      · 数字与小数点被拆开（"23 . 75"）
      · 单元格里挤进了多行内容（>6 个词 或 >100 字符）
      · 出现 " -" 这类断裂的负号/连字符
    宁可少给结构，也不给错结构。
    """
    if not rows or len(rows) < 2:
        return False
    widths = [len(r) for r in rows]
    if len(set(widths)) > 1 and max(widths) - min(widths) > 1:
        return False
    cells = [c for r in rows for c in r]
    if not cells:
        return False
    if sum(1 for c in cells if not c) / len(cells) > 0.45:
        return False
    for c in cells:
        if re.search(r"\d\s+[.,]\s*\d", c):        # 小数点被拆开
            return False
        if re.search(r"\s-\S", c):                  # 负号/连字符与词分离
            return False
        if c.count("(") != c.count(")"):            # 括号跨行断裂
            return False
        if re.search(r"(·\s*){2,}|^\W|[0-9)\]]\s+O\(", c):   # 运算符/括号拼接断裂
            return False
        if len(c) > 100 or len(c.split()) >= 10:    # 多行内容挤进一个单元格
            return False
    return True


def to_gfm(rows) -> str:
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    def esc(c):
        return (c or "").replace("|", "\\|").replace("\n", " ")
    head = rows[0]
    body = rows[1:]
    out = ["| " + " | ".join(esc(c) for c in head) + " |",
           "|" + "|".join(["---"] * n) + "|"]
    for r in body:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------- Markdown

def to_markdown(doc_obj: PDFDoc, figdir_rel: str = "figures", include_page_marks: bool = True):
    """把版面还原为 Markdown。返回 (markdown, blocks, figures, tables)。

    blocks 是块级锚点表：{id, page, y0, kind, chars, hash}，供证据回溯。
    """
    figs = doc_obj.figures(out_dir=figdir_rel if figdir_rel else None)
    tabs = doc_obj.tables(out_dir=figdir_rel if figdir_rel else None)
    title_text = doc_obj.detect_title()
    cap_by_page = {}
    for c in doc_obj.captions():
        cap_by_page.setdefault(c["page"], []).append(c)

    md = []
    blocks = []
    for p in doc_obj.pages:
        pno = p.number + 1
        if include_page_marks:
            md.append(f"<!-- page {pno} -->")
        items = []
        boxes = [(t["bbox"][0], t["bbox"][1], t["bbox"][2], t["bbox"][3])
                 for t in tabs if t["page"] == pno]
        boxes += [(f["bbox"][0], f["bbox"][1], f["bbox"][2], f["bbox"][3])
                  for f in figs if f["page"] == pno]
        for para in doc_obj.paragraphs(pno, skip_boxes=boxes):
            items.append(("para", para))
        for t in [t for t in tabs if t["page"] == pno]:
            items.append(("table", t))
        for f in [f for f in figs if f["page"] == pno]:
            items.append(("figure", f))
        for kind, obj in items:
            if "y0" not in obj:
                obj["y0"] = (obj.get("bbox") or [0, 0, 0, 0])[1]
        items.sort(key=lambda kv: kv[1].get("y0", 0.0))

        # 图/表题注已随图、表一起输出，正文里重复的那一行跳过
        used_labels = {f["label"] for f in figs if f["page"] == pno and f["label"]}
        used_labels |= {t["label"] for t in tabs if t["page"] == pno and t["label"]}
        items = [(k, o) for (k, o) in items
                 if not (k == "para" and caption_like(o.get("text", "")) and
                         norm(CAP_RE.match(o["text"]).group("label")) in used_labels)]

        for kind, obj in items:
            bid = f"p{pno}b{len(blocks)+1}"
            if kind == "para":
                text = obj["text"]
                if not text:
                    continue
                if obj["heading"]:
                    level = 1 if text == title_text else min(6, max(2, obj["level"] + 1))
                    md.append(f"{'#' * level} {text}")
                    blocks.append({"id": bid, "page": pno, "y0": obj["y0"],
                                   "kind": "heading", "chars": len(text),
                                   "hash": sha256_text(text), "quote": text[:160]})
                else:
                    md.append(text)
                    blocks.append({"id": bid, "page": pno, "y0": obj["y0"],
                                   "kind": "paragraph", "chars": len(text),
                                   "hash": sha256_text(text), "quote": text[:160]})
            elif kind == "table":
                label = obj["label"] or "Table"
                cap = obj["caption"]
                md.append(f"**{label}** {cap}".strip())
                if obj["reliable"]:
                    md.append(to_gfm(obj["rows"]))
                    blocks.append({"id": bid, "page": pno, "y0": obj["y0"],
                                   "kind": "table", "chars": sum(len(c) for r in obj["rows"] for c in r),
                                   "hash": sha256_text(to_gfm(obj["rows"])),
                                   "quote": cap[:160], "cells": obj["n_rows"] * obj["n_cols"]})
                else:
                    if obj["file"]:
                        md.append(f"![{label}]({figdir_rel}/{obj['file']})")
                    md.append("> 表格结构未能可靠还原（合并单元格或列数不一致），保留页面渲染图，数值未改写。")
                    blocks.append({"id": bid, "page": pno, "y0": obj["y0"],
                                   "kind": "table-image", "chars": 0,
                                   "hash": sha256_text(cap), "quote": cap[:160],
                                   "note": "cells unreliable; image kept"})
            else:
                label = obj["label"] or "Figure"
                if obj["file"]:
                    md.append(f"![{label}]({figdir_rel}/{obj['file']})")
                if obj["caption"]:
                    md.append(f"**{label}** {obj['caption']}")
                blocks.append({"id": bid, "page": pno, "y0": obj["y0"],
                               "kind": "figure", "chars": len(obj["caption"]),
                               "hash": sha256_text(obj["caption"]),
                               "quote": obj["caption"][:160]})
        md.append("")
    text = "\n".join(md)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text, blocks, figs, tabs


# ---------------------------------------------------------------- 证据与输出

def anchor(page: int, quote: str, kind: str = "text", block: str = "", label: str = ""):
    a = {"page": int(page), "kind": kind, "quote": (quote or "")[:400]}
    if block:
        a["block"] = block
    if label:
        a["label"] = label
    return a


def verify_anchor(doc_obj: PDFDoc, a: dict):
    """锚点是否能在指定页找到（去空白、忽略大小写）。返回 (ok, reason)。"""
    page = a.get("page")
    quote = a.get("quote") or ""
    if not isinstance(page, int) or page < 1 or page > doc_obj.page_count:
        return False, "page_out_of_range"
    if not quote:
        return False, "empty_quote"
    hay = re.sub(r"\s+", "", doc_obj.page_text(page)).lower()
    needle = re.sub(r"\s+", "", quote).lower()
    if needle[:60] in hay:
        return True, "exact"
    # 允许跨页续接：看相邻页
    for p in (page - 1, page + 1):
        if 1 <= p <= doc_obj.page_count:
            if needle[:60] in re.sub(r"\s+", "", doc_obj.page_text(p)).lower():
                return True, f"nearby_page_{p}"
    return False, "not_found"


def emit_result(out_path: str, case_id: str, status: str, primary: dict,
                evidence=None, uncertainty=None, artifacts=None,
                contract=None, extra_top=None):
    """组装 result.json：保留 output_contract 的全部字段名，缺的填空并记入 uncertainty。"""
    result = {
        "schema": VERSION,
        "case_id": case_id,
        "status": status,
        "primary_result": primary,
        "evidence": evidence or [],
        "uncertainty": uncertainty or [],
        "artifacts": [],
        "change_log": [{"at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                        "note": f"{VERSION} run"}],
    }
    base = os.path.dirname(os.path.abspath(out_path))
    for path, role, mtype in (artifacts or []):
        if path and os.path.exists(path):
            result["artifacts"].append({
                "path": os.path.relpath(path, base).replace("\\", "/"),
                "role": role, "media_type": mtype,
                "bytes": os.path.getsize(path), "sha256": sha256_file(path)})
        elif path:
            result["artifacts"].append({"path": path, "role": role, "status": "missing"})
    if isinstance(contract, dict) and contract:
        missing = []
        for key, spec in contract.items():
            if key in result:
                continue
            if key in primary:                     # primary_result 里已有同名字段
                result[key] = primary[key]
                continue
            result[key] = spec.get("default") if isinstance(spec, dict) else None
            missing.append(key)
        if missing:
            result["uncertainty"].append({
                "item": f"output_contract fields not produced: {', '.join(missing)}",
                "impact": "reviewer must check whether the contract expects different names"})
    if extra_top:
        result.update(extra_top)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    return result
