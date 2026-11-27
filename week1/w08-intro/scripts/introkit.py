#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""introkit —— 引言与相关工作写作 Skill 的共用核（纯标准库）。

设计原则
--------
1. 只做确定性的事情：切分、清点、比对、定位。判断与写作交给 Agent。
2. 输入 schema 不保证统一：候选键 + 文件名兜底 + 深度递归，读到什么用什么，
   读不到的一律记进 warnings，不猜、不补造。
3. 所有证据都是「逐字片段 + 位置」；位置只用材料自身的段号/编号。
4. 写文件一律 newline="\\n"，避免 CRLF 污染提交包。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

VERSION = "introkit/1.0"

# ---------------------------------------------------------------- 基础工具

_WS = re.compile(r"[ \t\u00a0\u3000]+")
_SOFT_HYPHEN = re.compile(r"[\u00ad\u200b-\u200d\ufeff]")


def norm(s) -> str:
    """压缩行内空白、去软连字符、合并折行；**保留空行作为段落分隔**。不改字符本身。"""
    if s is None:
        return ""
    s = _SOFT_HYPHEN.sub("", str(s))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    paras, cur = [], []
    for raw in s.split("\n"):
        line = _WS.sub(" ", raw).strip()
        if not line:
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        # 折行合并：上一行没有句末标点且本行以小写/数字/中文开头
        if cur and not re.search(r"[.。!！?？;；:：]$", cur[-1]) \
                and re.match(r"^[a-z0-9\-\u4e00-\u9fff]", line) \
                and not re.match(r"^(fig|table|tab|eq|ref|doi)\b", line, re.I):
            cur[-1] = cur[-1] + " " + line
        else:
            cur.append(line)
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(p.strip() for p in paras if p.strip()).strip()


def norm_hard(s) -> str:
    """去标点与空白并小写，用于宽容比对。"""
    s = norm(s).lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[\"'`’“”‘(),.;:!?\[\]{}<>《》〈〉、，。；：！？（）【】\-_/\\|~^=+*&%$#@]+", "", s)
    return s


def flat(s) -> str:
    """只去空白（保留标点与数字），用于不可变成分的多重集比对。"""
    return re.sub(r"\s+", "", norm(s))


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_16(s: str) -> str:
    return sha256_text(s)[:16]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 句子切分

_ABBREV = [
    "et al.", "e.g.", "i.e.", "cf.", "vs.", "etc.", "approx.", "Fig.", "Figs.",
    "Eq.", "Eqs.", "No.", "Nos.", "Ref.", "Refs.", "Sec.", "Secs.", "Tab.",
    "Dr.", "Prof.", "Mr.", "Ms.", "St.", "Inc.", "Ltd.", "Univ.", "al.",
]
_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|(?<=[.])\s+(?=[A-Z\u4e00-\u9fff])")


def sentences(text: str):
    """按中英句末标点切句；对常见缩写与小数点做保护。返回 (句子, 起始偏移) 列表。"""
    if not text:
        return []
    sentinel = "\x01"
    tmp = text
    guards = []
    for i, a in enumerate(_ABBREV):
        token = sentinel + str(i) + sentinel
        for m in re.finditer(re.escape(a), tmp):
            pass
        tmp = tmp.replace(a, token)
    # 小数点：数字.数字
    tmp = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + sentinel + "D" + sentinel + m.group(2), tmp)

    parts = []
    start = 0
    for m in _SENT_SPLIT.finditer(tmp):
        seg = tmp[start:m.start()]
        if seg.strip():
            parts.append((start, seg))
        start = m.end()
    tail = tmp[start:]
    if tail.strip():
        parts.append((start, tail))

    out = []
    for off, seg in parts:
        s = seg
        for i, a in enumerate(_ABBREV):
            s = s.replace(sentinel + str(i) + sentinel, a)
        s = s.replace(sentinel + "D" + sentinel, ".")
        s = s.replace(sentinel, "")
        s = s.strip()
        if s:
            out.append((s, off))
    return out


def tokens(s: str):
    """英文词 / 中文词组 / 数字（含百分号与小数）"""
    return re.findall(r"[A-Za-z][A-Za-z\-']*|\d+(?:[.,]\d+)?%?|[\u4e00-\u9fff]{1,6}", s or "")


def cjk_ratio(s: str) -> float:
    s = s or ""
    if not s:
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    return cjk / max(1, len(s))


def strip_tags(s: str) -> str:
    return re.sub(r"</?[A-Za-z][A-Za-z0-9\-]*(?:\s[^<>]*)?/?>", "", s or "")


# ---------------------------------------------------------------- IO

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        if default is not None:
            return default
        return {"__load_error__": "%s: %s" % (type(exc).__name__, exc), "__path__": str(path)}


def read_jsonl(path):
    out = []
    if not path or not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                out.append({"__load_error__": "invalid json line", "__raw__": line[:200]})
    return out


def dump_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def dump_jsonl(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def dump_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def pjson(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------- 不可变成分

NUM_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*"
    r"(%|‰|°C|℃|K|h|hr|hrs|min|mins|s|ms|ns|ps|nm|µm|um|mm|cm|m|mg|µg|ug|g|kg|mol|mmol|M|mM|µM|uM|"
    r"mL|µL|uL|L|eV|keV|V|mV|mA|A|W|mW|kW|J|kJ|Pa|kPa|MPa|GPa|bar|mbar|Hz|kHz|MHz|GHz|rpm|Da|kDa|"
    r"mol%|wt%|vol%|at%|ppm|ppb|fold|times|倍|度|小时|分钟|秒|毫秒|纳米|微米|毫米|厘米|克|毫克|升|毫升|"
    r"伏|毫伏|瓦|毫瓦|焦|帕|千帕|兆帕|赫兹|千赫|兆赫|转/分|天|周|月|年)"
    r"(?![A-Za-z0-9])"
)
CITATION_RES = [
    ("numeric", re.compile(r"\[(\d+(?:\s*[-,–]\s*\d+)*)\]")),
    ("author-year", re.compile(r"\(([A-Z][A-Za-z\u00c0-\u024f'\-]+(?:\s+(?:et al\.|and|&)\s*[A-Za-z\u00c0-\u024f'\-]*)?,?\s*\d{4}[a-z]?(?:\s*;\s*[^()]{0,80})?)\)")),
    # 叙事式作者-年份（不在括号里）：Peters et al. (2018a)、Dai and Le (2015)、Harper (2009)
    # 这类写法在 ACL/Nature 系排版里最常见，漏掉会让整篇引用"对不上"
    ("narrative", re.compile(r"\b([A-Z][A-Za-z\u00c0-\u024f'\-]+(?:\s+(?:et al\.|and|&)\s*[A-Z][A-Za-z\u00c0-\u024f'\-]*)?)\s*[，（(]\s*(\d{4}[a-z]?)\s*[)）]")),
    ("latex", re.compile(r"\\(?:cite|citep|citet|autoref)\{([^}]+)\}")),
    ("bracket-key", re.compile(r"\[([A-Za-z][A-Za-z0-9_:.\-]{1,40}(?:,\s*[A-Za-z][A-Za-z0-9_:.\-]{0,40})*)\]")),
]

# 方括号里的"看起来像引用、其实不是"的标记（NLP/模型专用 token、全大写缩写）
BRACKET_KEY_DENY = {
    "cls", "sep", "mask", "unk", "pad", "eos", "bos", "num", "date", "url", "id", "ids",
    "m", "s", "n", "x", "y", "k", "v", "t", "true", "false", "none", "null",
}

# `(NIPS 2017)` / `(December 2018)` / `(Fig. 2, 2018)` 这类不是作者-年份引用：
# 括号里的第一个词是月份、会议/期刊缩写或常见非姓词时，整个匹配丢弃。
AY_DENY = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "spring", "summer", "autumn", "winter",
    "fig", "figure", "table", "eq", "equation", "section", "sec", "chapter", "appendix",
    "nips", "neurips", "icml", "iclr", "acl", "emnlp", "naacl", "coling", "cvpr", "iccv",
    "eccv", "aaai", "ijcai", "kdd", "sigir", "www", "ieee", "acm", "springer", "arxiv",
    "the", "this", "that", "these", "those", "we", "our", "it", "they", "see", "cf", "e.g", "i.e",
}


def _ay_token_denied(name: str):
    """括号里/句中的"作者名"其实是月份、会议缩写、图表指代等非姓词。"""
    head = re.split(r"[\s,]+", str(name or "").strip())[0].lower().strip(".")
    return head in AY_DENY

# `(NIPS 2017)` / `(December 2018)` / `(Fig. 2, 2018)` 这类不是作者-年份引用：
# 括号里的第一个词是月份、会议/期刊缩写或常见非姓词时，整个匹配丢弃。
AY_DENY = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "spring", "summer", "autumn", "winter",
    "fig", "figure", "table", "eq", "equation", "section", "sec", "chapter", "appendix",
    "nips", "neurips", "icml", "iclr", "acl", "emnlp", "naacl", "coling", "cvpr", "iccv",
    "eccv", "aaai", "ijcai", "kdd", "sigir", "www", "ieee", "acm", "springer", "arxiv",
    "the", "this", "that", "these", "those", "we", "our", "it", "they", "see", "cf", "e.g", "i.e",
}


def _bracket_key_is_fake(keys):
    """[CLS] / [MASK] / [SEP] 这类是全大写且带不出年份的专有标记，不是引用。"""
    for k in keys:
        kk = k.strip()
        if not kk:
            continue
        low = kk.lower()
        if low in BRACKET_KEY_DENY:
            continue
        if kk.isupper() and len(kk) <= 6 and not re.search(r"\d", kk):
            continue
        return False
    return True
CROSSREF_RE = re.compile(
    r"\b(Fig(?:ure)?s?|Tab(?:le)?s?|Eq(?:uation)?s?|Sec(?:tion)?s?|Chap(?:ter)?s?|"
    r"Supp(?:lementary)?(?:\s+(?:Fig|Table|Note|Section))?|Scheme|Algorithm|Appendix)"
    r"\.?\s*(\d+[A-Za-z]?(?:\s*[–-]\s*\d+[A-Za-z]?)?)", re.I)
FORMULA_RE = re.compile(r"\\[a-zA-Z]+(?:\{[^}]*\})*|\b[A-Za-z]\s*=\s*[^,.;]{1,40}")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")


def protected_spans(text: str):
    """返回 {kind: [字符串...]}（按出现顺序，保序去重时用 multiset 比对更稳，这里保留原始序列）。"""
    text = text or ""
    out = {
        "number": [m.group(0).strip() for m in NUM_RE.finditer(text)],
        "citation": [],
        "crossref": [m.group(0).strip() for m in CROSSREF_RE.finditer(text)],
        "formula": [m.group(0).strip() for m in FORMULA_RE.finditer(text)],
        "url": [m.group(0).strip() for m in URL_RE.finditer(text)],
        "doi": [m.group(0).strip() for m in DOI_RE.finditer(text)],
    }
    for _kind, rx in CITATION_RES:
        out["citation"].extend(m.group(0).strip() for m in rx.finditer(text))
    return out


# ---------------------------------------------------------------- 引用解析

def _split_numbers(spec: str):
    """把 [3-5,8] 这样的编号表达展开成编号列表。"""
    nums = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[–-]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 0 <= a <= b and b - a <= 200:
                nums.extend(str(x) for x in range(a, b + 1))
            continue
        if re.match(r"^\d+$", part):
            nums.append(part)
    return nums


def parse_citations(text: str):
    """返回 [{raw, kind, keys, spans:[[start,end]]}]；keys 对 numeric 是编号字符串。"""
    text = text or ""
    found = {}
    for kind, rx in CITATION_RES:
        for m in rx.finditer(text):
            raw = m.group(0)
            if kind == "numeric":
                keys = _split_numbers(m.group(1))
            elif kind == "latex":
                keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
            elif kind == "narrative":
                if _ay_token_denied(m.group(1)):
                    continue
                keys = ["%s %s" % (m.group(1), m.group(2))]
            elif kind == "author-year":
                inner = m.group(1)
                if _ay_token_denied(inner):
                    continue
                keys = [inner.strip()]
            else:  # bracket-key
                keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
                if _bracket_key_is_fake(keys):
                    continue
            rec = found.setdefault(raw, {"raw": raw, "kind": kind, "keys": keys, "spans": []})
            rec["spans"].append([m.start(), m.end()])
    return list(found.values())


# author-year / narrative 引用的年份后缀（2018a/2018b）在文献表里通常体现为同姓同年多条，
# 归一成 surname+year 才能与文献表派生出的 key 对上。
_AY_SPLIT = re.compile(r"^([A-Z][A-Za-z\u00c0-\u024f'\-]+)")


def _ay_key(spec: str):
    """把 'Peters et al., 2018a' / 'Radford et al. 2018' 归一成 'peters2018'。"""
    s = str(spec or "").strip()
    ym = re.search(r"(19|20)\d{2}", s)
    nm = _AY_SPLIT.match(s)
    if ym and nm:
        return re.sub(r"[^a-z0-9]", "", (nm.group(1) + ym.group(0)).lower())
    return ""


def citation_key_of(kind: str, key: str):
    """统一的引用标识。

    numeric -> n:<num>；author-year / narrative -> k:<姓><年>（与文献表派生的 key 同形）；
    latex / bracket-key -> k:<lower key>。
    """
    if kind == "numeric":
        return "n:" + str(key).strip()
    if kind in ("author-year", "narrative"):
        ay = _ay_key(key)
        if ay:
            return "k:" + ay
    return "k:" + re.sub(r"\s+", " ", str(key).strip().lower())


# ---------------------------------------------------------------- 文献表

_BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,]+),", re.I)
_BIB_FIELD_RE = re.compile(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", re.I)
_REF_LINE_RE = re.compile(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s+(.*)$")
AUTHOR_YEAR_RE = re.compile(r"([A-Z][A-Za-z\u00c0-\u024f'\-]+)(?:\s+(?:et al\.|and|&)\s*[A-Za-z\u00c0-\u024f'\-]*)?[,\s]*\(?(\d{4}[a-z]?)\)?")


def parse_bibtex(text: str, warnings=None):
    """极简 BibTeX 解析，够用即可（不引第三方库）。"""
    out = []
    if not text:
        return out
    for m in _BIB_ENTRY_RE.finditer(text):
        etype, key = m.group(1).lower(), m.group(2).strip()
        depth, i = 1, m.end()
        start = i
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        fields = {}
        for fm in _BIB_FIELD_RE.finditer(body):
            name = fm.group(1).lower()
            val = fm.group(2).strip()
            if val.startswith("{") and val.endswith("}"):
                val = val[1:-1]
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            fields[name] = norm(val)
        out.append({
            "key": key,
            "type": etype,
            "authors": fields.get("author", ""),
            "year": (fields.get("year", "") or "").strip(),
            "title": fields.get("title", ""),
            "venue": fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or "",
            "doi": fields.get("doi", ""),
            "url": fields.get("url", ""),
            "raw": norm(text[m.start():i]),
            "source": "bibtex",
        })
    if not out and warnings is not None:
        warnings.append("bibliography: 未能从文本中解析出任何 BibTeX 条目")
    return out


def parse_reference_list(text: str, warnings=None):
    """解析编号参考文献列表：'[12] A. Author... (2021).' 或 '12. A. Author...'"""
    out = []
    if not text:
        return out
    lines = [ln for ln in (text or "").split("\n")]
    cur_num, cur = None, []
    blocks = []
    for ln in lines:
        m = _REF_LINE_RE.match(ln)
        if m:
            if cur_num is not None and cur:
                blocks.append((cur_num, " ".join(cur)))
            cur_num = m.group(1) or m.group(2)
            cur = [m.group(3).strip()]
        elif cur_num is not None and ln.strip():
            cur.append(ln.strip())
        elif ln.strip() and cur_num is None:
            blocks.append((None, ln.strip()))
    if cur_num is not None and cur:
        blocks.append((cur_num, " ".join(cur)))
    for num, body in blocks:
        ay = AUTHOR_YEAR_RE.search(body)
        year = ay.group(2) if ay else ""
        authors = ay.group(1) if ay else ""
        out.append({
            "key": ("n:" + str(num)) if num is not None else ("auto:" + sha256_16(body)),
            "num": num,
            "authors": authors,
            "year": year,
            "title": "",
            "venue": "",
            "doi": (DOI_RE.search(body).group(0) if DOI_RE.search(body) else ""),
            "url": (URL_RE.search(body).group(0) if URL_RE.search(body) else ""),
            "raw": body,
            "source": "reference-list",
        })
    if not out and warnings is not None:
        warnings.append("bibliography: 参考文献列表为空或无法识别")
    return out


def _looks_like_reference_entry(ln: str):
    """一行看起来像参考文献条目吗？（编号 + 至少 20 字符）"""
    m = _REF_LINE_RE.match(ln)
    return bool(m and len((m.group(3) or "").strip()) >= 20)


# 供 split_material_references 用：在**任意位置**切出 "[12] " 这样的条目边界。
# 条目正文首字符可能是非 ASCII 大写字母（`[16] Łukasz`），所以不能用 [A-Z]，
# 改用"任意 Unicode 字母"（[^\W\d_]）。
_REF_SPLIT_RE = re.compile(r"(?<![\d\]])\[(\d{1,3})\]\s+(?=[^\W\d_])")


def split_numbered_references(tail: str):
    """把文献段切成 [(num, text)]：先按行，行内再按 [n] / n. 边界切（条目常被挤在同一行）。"""
    flat = "\n".join(tail.split("\n"))
    marks = [(m.start(), m.end(), int(m.group(1))) for m in _REF_SPLIT_RE.finditer(flat)]
    if not marks:
        # 退路：整行式 "12. Author ..."
        marks = []
        pos = 0
        for ln in flat.split("\n"):
            m = _REF_LINE_RE.match(ln)
            if m:
                num = int(m.group(1) or m.group(2))
                marks.append((pos, pos + len(ln) - len(m.group(3)), num))
            pos += len(ln) + 1
    entries = []
    for i, (s, e, num) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(flat)
        body = " ".join(flat[e:end].split())
        if body:
            entries.append((num, body))
    return entries


REFERENCE_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?"
    r"(references?|reference\s+list|bibliography|works\s+cited|"
    r"参考文献|引用文献|文献列表)\b\s*[:：]?",
    re.I)

# 无编号文献表：条目之间用空行分隔（arXiv / ACL 系排版；也见于平台给的"事实底稿"）
_REF_UNNUMBERED_SPLIT = re.compile(r"\n\s*\n")
# 条目开头常见的编号前缀："[3] " / "3. " / "3) "
_REF_PREFIX_RE = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)、])\s*")
# 条目里"作者段 + 年份"的两种常见写法
_REF_FIRST_SURNAME_RE = re.compile(r"[A-Z][A-Za-z\u00c0-\u024f'\-]{1,30}")
_REF_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})[a-z]?(?!\d)")


def _first_author_surname(raw: str):
    """取第一作者的**姓**。

    文献表里三种排版都要照顾：
      * `Vaswani, Ashish. …` / `Ba, J. L. …`（姓在前）→ 第一个逗号前那一段
      * `Alan Akbik, Duncan Blythe, and Roland Vollgraf.`（名在前，ACL/arXiv 常见）
        → 第一作者段是 `Alan Akbik`，姓是段内最后一个词
      * `Wilson L. Taylor. 1953. Cloze procedure… Journalism Bulletin, 30(4)`（作者后紧跟年份与刊名）
        → **先在最前面的年份处截断**，否则会把刊名 `Bulletin` 当成姓
    """
    s = _REF_PREFIX_RE.sub("", str(raw or "").strip())
    s = re.sub(r"^(?:and|&)\s+", "", s, flags=re.I)
    ym = _REF_YEAR_RE.search(s[:220])
    if ym:
        s = s[:ym.start()]
    seg = re.split(r",|\band\b|&", s, maxsplit=1)[0].strip()
    toks = re.findall(r"[A-Z][A-Za-z\u00c0-\u024f'\-]{1,30}", seg)
    if not toks:
        return ""
    return toks[-1] if len(toks) >= 2 else toks[0]


def ref_key_from_raw(raw: str):
    """从一条参考文献原文里派生稳定、可读的 key：首作者姓 + 年份（如 peters2018）。

    作者-年份式引用（`Peters et al. (2018)`）与文献表派生的 key 同形，才能真正对上；
    抽不到年份就退回首作者姓，再抽不到才交给调用方用哈希兜底。
    """
    sur = _first_author_surname(raw)
    ym = _REF_YEAR_RE.search(_REF_PREFIX_RE.sub("", str(raw or "").strip())[:220])
    yr = ym.group(1) if ym else ""
    return re.sub(r"[^a-z0-9]", "", (sur + yr).lower())


def split_unnumbered_references(tail: str):
    """切**无编号**文献表：按空行分段，每段一条；段内若还有内嵌的 "[n] " 则回退给编号解析。"""
    tail = (tail or "").strip()
    if not tail:
        return []
    blocks = [b.strip() for b in _REF_UNNUMBERED_SPLIT.split(tail) if b.strip()]
    # 段太长说明没有分段（整表挤成一段）→ 视为解析失败，避免造出一堆假条目
    if blocks and max(len(b) for b in blocks) > 1500:
        return []
    # 有些排版把一条文献拆成两块、甚至三块（BERT 的 arXiv 版：`Alan Akbik, … Vollgraf.` +
    # 空行 + `2018. Contextual string embeddings…`）。合并规则：**只有当"当前块看起来是
    # 一条新文献的开头"（首字母大写 + 块内含 19xx/20xx 年份）而且"上一块也已经含年份"时
    # 才断条**，其余一律并入上一块。这样被排版拆散的条目能自动拼回。
    merged = []
    for b in blocks:
        if merged:
            prev = merged[-1]
            prev_has_year = bool(_REF_YEAR_RE.search(prev[:220]))
            starts_upper = bool(re.match(r"^[A-Z\u00c0-\u024f]", b))
            cur_has_year = bool(_REF_YEAR_RE.search(b[:220]))
            if not (prev_has_year and starts_upper and cur_has_year):
                merged[-1] = prev + " " + b
                continue
        merged.append(b)
    blocks = merged
    out = []
    for i, b in enumerate(blocks, 1):
        b = " ".join(b.split())
        if len(b) < 25:
            continue
        if "@" in b and _BIB_ENTRY_RE.search(b):
            continue
        num = None
        pm = _REF_PREFIX_RE.match(b)
        if pm:
            num = pm.group(1) or pm.group(2)
            b = _REF_PREFIX_RE.sub("", b).strip()
        out.append((int(num) if num else None, b))
    return out


def split_material_references(text: str):
    """材料末尾常自带参考文献表（真实初稿/事实底稿的普遍写法）。

    切出 (正文, entries)。entries 是 `[(num 或 None, 条目原文)]`。
    三种形态都认：
      1. 编号式、条目被排版挤在同一行（`[1] A. Author... [2] B. Author...`）
      2. 编号式、一行一条（`[1] ...` / `12. ...`）
      3. **无编号**式、条目之间用空行分隔（arXiv / ACL 系排版：`Author, A. Title. Venue, 2018.`）
    找不到、或文献段不像文献表时返回 (text, [])。
    标题只认文本**后半部分**的，避免把正文里的 "references" 一词误当分节。
    """
    if not text:
        return text, []
    hits = [m for m in REFERENCE_HEADING_RE.finditer(text) if m.start() >= len(text) * 0.35]
    if not hits:
        return text, []
    m = hits[-1]
    body, tail = text[:m.start()].rstrip(), text[m.end():].strip()
    if not tail:
        return text, []
    # 先试编号式
    entries = [(n, t) for n, t in split_numbered_references(tail)]
    numbered_ok = (len(entries) >= 3 and [n for n, _ in entries][:3] == [1, 2, 3])
    if not numbered_ok:
        entries = split_unnumbered_references(tail)
    if len(entries) < 3:
        return text, []
    if numbered_ok:
        first_three = [n for n, _ in entries][:3]
        if first_three != [1, 2, 3]:
            return text, []
    else:
        # 无编号式：要求至少一半条目能派生出"姓+年"或至少能看出是文献条目
        ok = 0
        for _n, t in entries:
            if _REF_YEAR_RE.search(t[:200]) and _REF_FIRST_SURNAME_RE.search(t):
                ok += 1
        if ok < len(entries) * 0.5:
            return text, []
    return body, entries


def load_bibliography(*docs):
    """从任意 JSON / 文本形态的文献材料里提取记录。返回 (records, warnings)。"""
    warnings = []
    records = []
    for doc in docs:
        if doc is None:
            continue
        if isinstance(doc, str):
            if "@" in doc and _BIB_ENTRY_RE.search(doc):
                records.extend(parse_bibtex(doc, warnings))
            else:
                records.extend(parse_reference_list(doc, warnings))
            continue
        if isinstance(doc, dict):
            picked = False
            for key in ("references", "bibliography", "bib", "entries", "items", "records", "works", "papers", "literature"):
                val = doc.get(key)
                if isinstance(val, list):
                    for rec in val:
                        records.append(_norm_ref_record(rec))
                    picked = True
                    break
            if not picked:
                if doc.get("__load_error__"):
                    warnings.append("bibliography: %s" % doc["__load_error__"])
                else:
                    warnings.append("bibliography: JSON 里没有找到文献列表字段（references/bibliography/entries…）")
            continue
        if isinstance(doc, list):
            for rec in doc:
                if isinstance(rec, (list, tuple)) and len(rec) == 2 and isinstance(rec[1], str):
                    rec = {"num": rec[0], "raw": rec[1], "source": "material_tail"}
                records.append(_norm_ref_record(rec))
    # 去重：同一条文献被两种来源重复列出时才合并。
    # **注意不能只用 key 当签名**——真实文献表里"同一作者同一年"的不同文献很常见
    # （`Kaiser & Bengio 2016` 与 `Kaiser & Sutskever 2016` 都会派生出 kaiser2016），
    # 只用 key 去重会把它们当成重复条目丢掉，导致编号 17/24 凭空消失。
    # 因此优先用 DOI，其次用条目原文本身；key 只在没有原文时兜底。
    seen, uniq = set(), []
    used_keys = {}
    for r in records:
        raw_norm = norm_hard(r.get("raw") or "")
        sig = (r.get("doi") or "").lower() or ("raw:" + sha256_16(raw_norm) if raw_norm else "") or \
              (r.get("key") or "").lower() or \
              (norm_hard(r.get("title") or "") + "|" + str(r.get("year") or ""))
        if sig in seen:
            continue
        seen.add(sig)
        # key 撞车（不同文献派生出同一个姓+年）时加字母后缀区分：luong2015 → luong2015a/b
        k = (r.get("key") or "").lower()
        if k and not k.startswith(("auto:", "raw:", "n:")):
            if k in used_keys:
                used_keys[k] += 1
                suffix = "abcdefghijklmnopqrstuvwxyz"[min(used_keys[k] - 1, 25)]
                r = dict(r)
                r["key"] = k + suffix
                r["key_suffix"] = suffix
            else:
                used_keys[k] = 1
        uniq.append(r)
    return uniq, warnings


def _norm_ref_record(rec):
    if not isinstance(rec, dict):
        return {"key": "raw:" + sha256_16(str(rec)), "raw": str(rec), "source": "inline"}
    raw_known = norm(rec.get("raw") or rec.get("text") or "")
    authors = rec.get("authors") or rec.get("author") or rec.get("creators") or ""
    if isinstance(authors, list):
        parts = []
        for a in authors:
            if isinstance(a, dict):
                parts.append(a.get("family") or a.get("name") or a.get("literal") or "")
            else:
                parts.append(str(a))
        authors = "; ".join(p for p in parts if p)
    year = rec.get("year") or rec.get("issued") or rec.get("date") or ""
    if isinstance(year, dict):
        year = str(year.get("year") or year.get("date-parts") or "")
    title = norm(rec.get("title") or rec.get("name") or "")
    doi = rec.get("doi") or rec.get("DOI") or ""
    # 只有 raw 没有结构化字段时（如材料末尾的文献表），从 raw 里尽量补出来
    if raw_known and not (title or authors or year or doi):
        ay = AUTHOR_YEAR_RE.search(raw_known)
        if ay:
            authors = authors or ay.group(1)
            year = year or ay.group(2)
        if not authors:
            fm = _REF_FIRST_SURNAME_RE.search(_REF_PREFIX_RE.sub("", raw_known))
            if fm:
                authors = fm.group(0)
        if not year:
            ym = _REF_YEAR_RE.search(_REF_PREFIX_RE.sub("", raw_known)[:220])
            if ym:
                year = ym.group(1)
        dm = DOI_RE.search(raw_known)
        if dm:
            doi = dm.group(0)
        if not title:
            cand = re.split(r"(?<=[.。])\s+", raw_known)
            seg = next((x for x in cand if len(x) >= 25), "")
            seg = re.sub(r"^(?:\[?\d+\]?[.)]?\s*)", "", seg).strip()
            title = norm(seg)
    if raw_known and not (rec.get("key") or rec.get("id") or rec.get("citekey")):
        # 可读稳定 key：首作者姓 + 年份（如 peters2018）。**必须与 author-year 引用的
        # citation_key_of() 同形**，否则正文写 "Peters et al. (2018)"、文献表派生出别的 key，
        # 明明对得上却被判成 unresolved。派生不出才退回首作者姓，最后才用哈希。
        key = ref_key_from_raw(raw_known)
        if not key:
            ay2 = AUTHOR_YEAR_RE.search(raw_known)
            if ay2:
                key = re.sub(r"[^a-z0-9]", "", (ay2.group(1) + ay2.group(2)).lower())
        if not key:
            fm2 = _REF_FIRST_SURNAME_RE.search(_REF_PREFIX_RE.sub("", raw_known))
            if fm2:
                key = re.sub(r"[^a-z]", "", fm2.group(0).lower())
        if not key:
            key = "auto:" + sha256_16(raw_known)
    else:
        key = str(rec.get("key") or rec.get("id") or rec.get("citekey"))
    return {
        "key": key,
        "num": rec.get("num") or rec.get("number") or rec.get("index"),
        "authors": norm(authors) if isinstance(authors, str) else str(authors),
        "year": re.sub(r"[^0-9a-z]", "", str(year).lower())[:4],
        "title": title,
        "venue": norm(rec.get("venue") or rec.get("journal") or rec.get("container-title") or rec.get("booktitle") or rec.get("publisher") or ""),
        "doi": doi,
        "url": (rec.get("url") or rec.get("link") or ""),
        "raw": raw_known,
        "source": rec.get("source") or "json",
    }


# ---------------------------------------------------------------- 线索词表

ATTRIBUTION = re.compile(r"\b(reported|proposed|showed|demonstrated|found|observed|suggested|argued|"
                         r"introduced|developed|achieved|investigated|studied|reviewed|noted|concluded|"
                         r"established|reported that|et al\.)\b", re.I)
LIMITATION = re.compile(r"\b(however|but|nevertheless|still|remains?|limitation|limited|"
                        r"lack|absent|unclear|not\s+yet|insufficient|cannot|unable|"
                        r"only|solely|fail(?:s|ed)?\s+to|suffer(?:s|ed)?\s+from|"
                        r"hinder(?:s|ed)?|shortcoming|drawback|constraint|scalab\w+|"
                        r"degrad\w+|instab\w+)\b", re.I)
BOILERPLATE = re.compile(
    r"(in\s+recent\s+years[, ]|with\s+the\s+rapid\s+development|has\s+attracted\s+(?:more\s+and\s+more\s+|increasing\s+)?attention|"
    r"attracted\s+extensive\s+attention|has\s+become\s+a\s+hot\s+topic|is\s+of\s+great\s+importance|"
    r"plays?\s+an?\s+(?:important|vital|crucial|significant)\s+role|"
    r"近年来|受到广泛关注|引起广泛关注|具有重要意义|扮演着重要角色|随着.{0,8}的发展|研究热点)", re.I)
OVERCLAIM = re.compile(r"\b(first|first-ever|best|highest|most\s+\w+|novel|unprecedented|unique|"
                       r"for\s+the\s+first\s+time|prove[sd]?|always|never|optimal|superior|"
                       r"首次|最优|最佳|前所未有|独一无二|证明|总是|从未)", re.I)
HEDGE = re.compile(r"\b(may|might|could|would|suggest\w*|indicate\w*|appear\w*|likely|possibly|"
                   r"potential\w*|approximately|about|roughly|tend\w*|seem\w*|"
                   r"可能|或许|大约|初步|提示|倾向于)", re.I)
NEGATION = re.compile(r"\b(not|no|never|none|neither|nor|without|cannot|n't|fail\w*\s+to|"
                      r"不|没有|未|无|非|从不)", re.I)
QUANTIFIER = re.compile(r"\b(all|every|each|any|none|no|most|many|some|several|few|both|"
                        r"at\s+least|at\s+most|more\s+than|less\s+than|"
                        r"所有|全部|每个|任何|大多数|少数|若干|至少|至多)", re.I)
SUPPORT = re.compile(r"\b(support\w*|consistent\s+with|in\s+line\s+with|confirm\w*|corroborat\w*|"
                     r"in\s+agreement\s+with|as\s+evidenced\s+by|"
                     r"支持|一致|印证|吻合)", re.I)
CONFLICT = re.compile(r"\b(conflict\w*|contradict\w*|inconsistent|disagree\w*|"
                      r"differ\w*|opposite|in\s+contrast|"
                      r"冲突|矛盾|相反|不一致)", re.I)
GAP_CUE = re.compile(r"\b(gap|remains?\s+unknown|remains?\s+unclear|has\s+not\s+been|"
                     r"no\s+study|few\s+studies|little\s+is\s+known|"
                     r"underexplored|unaddressed|not\s+been\s+(?:reported|studied|explored)|"
                     r"空白|尚未|未被|缺少研究|研究不足)", re.I)
CONTRIB_CUE = re.compile(r"\b(we\s+(?:propose|present|introduce|develop|report|show|demonstrate|find|"
                         r"build|design|evaluate|quantify|provide)|this\s+(?:work|paper|study)|"
                         r"herein|our\s+(?:work|approach|method|study)|"
                         r"本文|我们(?:提出|设计|开发|构建|报告|展示|证明|发现))", re.I)

# 四节标题模式（供 assemble 定位小节；中英双语，容忍编号与粗体标记）。
# **不要要求标题后面就是行尾**：正文经 norm() 折行合并后，标题常与正文同处一行
# （`## 2. Related Work These works differ…`），要求行尾会让整节定位不到。
SECTION_PATTERNS = (
    ("background", re.compile(r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:\d+[.、)][ \t]*)?"
                              r"(research\s+background|background|introduction|研究背景|引言|背景)\b[ \t]*[:：]?", re.I)),
    ("related_work", re.compile(r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:\d+[.、)][ \t]*)?"
                                r"(related\s+works?|literature\s+review|state\s+of\s+the\s+art|"
                                r"相关工作|文献综述|研究现状)\b[ \t]*[:：]?", re.I)),
    ("gap", re.compile(r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:\d+[.、)][ \t]*)?"
                       r"(research\s+gap|knowledge\s+gap|gaps?|研究空白|空白|研究缺口|未解决的问题)\b[ \t]*[:：]?", re.I)),
    ("contributions", re.compile(r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?(?:\d+[.、)][ \t]*)?"
                                 r"(contributions?|我们的贡献|本文贡献|贡献|主要工作)\b[ \t]*[:：]?", re.I)),
)


def cues(text: str):
    t = text or ""
    return {
        "attribution": len(ATTRIBUTION.findall(t)),
        "limitation": len(LIMITATION.findall(t)),
        "boilerplate": [m.group(0) for m in BOILERPLATE.finditer(t)],
        "overclaim": [m.group(0) for m in OVERCLAIM.finditer(t)],
        "hedge": [m.group(0) for m in HEDGE.finditer(t)],
        "negation": len(NEGATION.findall(t)),
        "quantifier": [m.group(0) for m in QUANTIFIER.finditer(t)],
        "support": len(SUPPORT.findall(t)),
        "conflict": len(CONFLICT.findall(t)),
        "gap_cue": [m.group(0) for m in GAP_CUE.finditer(t)],
        "contrib_cue": [m.group(0) for m in CONTRIB_CUE.finditer(t)],
        "numbers": len(NUM_RE.findall(t)),
        "citations": len(parse_citations(t)),
    }


# ---------------------------------------------------------------- 案例读取

CASE_MATERIAL_KEYS = (
    "material", "materials", "manuscript", "paper", "paper_path", "document", "source",
    "source_text", "fact_sheet", "facts", "notes", "draft", "input", "input_text",
    "material_path", "manuscript_path", "document_path", "primary_material", "research_material",
)
CASE_BIB_KEYS = ("bibliography", "bib", "bibtex", "references", "reference_list", "library", "works", "literature")
CASE_FILE_FALLBACK = {
    "material_path": [
        "material.md", "material.txt", "material.json", "manuscript.md", "manuscript.txt",
        "paper.md", "paper.txt", "document.md", "draft.md", "source.md", "notes.md",
        "facts.md", "fact-sheet.md", "fact_sheet.md", "input.md", "primary-material.json",
        "primary-material.md", "material.tex",
    ],
    "bibliography_path": [
        "bibliography.bib", "refs.bib", "references.bib", "library.bib", "bibliography.json",
        "references.json", "references.txt", "reference-list.txt", "bibliography.md",
    ],
}


def _first(d, keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    for k in keys:
        if "." in k:
            cur = d
            ok = True
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and cur not in (None, "", [], {}):
                return cur
    return None


def _read_any_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        import zipfile
        try:
            with zipfile.ZipFile(path) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            return strip_tags(xml)
        except Exception as exc:  # noqa: BLE001
            return None, "docx read failed: %s" % exc
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
        except Exception:  # noqa: BLE001
            return None, "pdf read needs PyMuPDF (fitz) which is unavailable"
        try:
            doc = fitz.open(path)
            pages = [doc[i].get_text("text") for i in range(min(len(doc), 200))]
            doc.close()
            return "\n".join(pages), ""
        except Exception as exc:  # noqa: BLE001
            return None, "pdf read failed: %s" % exc
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read(), ""
        except UnicodeDecodeError:
            continue
        except Exception as exc:  # noqa: BLE001
            return None, "read failed: %s" % exc
    return None, "decode failed for all encodings"


def load_case(path):
    """读 case.json，解析材料与文献路径。返回 (case, ctx)。"""
    case = read_json(path, default={})
    base = os.path.dirname(os.path.abspath(path))
    warnings = []
    ctx = {
        "case_id": None, "case_path": os.path.abspath(path), "base": base,
        "contract": {}, "task": "", "notes": [], "warnings": warnings,
        "material_path": None, "bibliography_path": None, "material_text": "",
        "audience": "", "genre": "", "format_constraints": [], "lang": "",
    }

    if isinstance(case, dict) and case.get("__load_error__"):
        warnings.append("case.json: %s" % case["__load_error__"])
        case = {}

    ctx["case_id"] = (case.get("case_id") or case.get("id") or case.get("caseId")
                      or case.get("challenge_id") or None)
    ctx["contract"] = _first(case, ("output_contract", "outputContract", "contract", "outputs")) or {}
    if not isinstance(ctx["contract"], dict):
        ctx["contract"] = {}
    ctx["task"] = norm(_first(case, ("task", "task_text", "instruction", "instructions", "prompt")) or "")
    ctx["audience"] = norm(_first(case, ("audience", "reader", "readers", "target_audience", "venue", "target_venue", "journal")) or "")
    ctx["genre"] = norm(_first(case, ("genre", "style", "register", "section", "writing_type", "document_type")) or "")
    fc = _first(case, ("format_constraints", "constraints", "format", "requirements", "citation_style", "style_guide"))
    if isinstance(fc, list):
        ctx["format_constraints"] = [norm(x) if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in fc]
    elif isinstance(fc, str):
        ctx["format_constraints"] = [norm(fc)]
    elif isinstance(fc, dict):
        ctx["format_constraints"] = ["%s: %s" % (k, norm(v) if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in fc.items()]
    ctx["lang"] = norm(_first(case, ("language", "lang", "target_language")) or "")

    # 材料：先取 case 内联文本，其次路径
    inline = _first(case, ("material_text", "material", "materials", "manuscript_text", "facts", "notes", "draft", "source_text", "document_text", "input_text"))
    mat_path = _first(case, ("material_path", "manuscript_path", "paper_path", "document_path", "input_path", "source_path", "material_file", "manuscript_file"))
    if isinstance(inline, dict):
        inline = None if not inline else None
    if isinstance(inline, list) and inline and all(isinstance(x, str) for x in inline):
        inline = "\n\n".join(inline)
    if isinstance(inline, str) and inline.strip():
        ctx["material_text"] = norm(inline)
        ctx["material_source"] = "case_inline"
    elif isinstance(mat_path, str) and mat_path.strip():
        p = mat_path if os.path.isabs(mat_path) else os.path.join(base, mat_path)
        if os.path.exists(p):
            txt, err = _read_any_text(p)
            if txt is None:
                ctx["material_source"] = "unreadable"
                warnings.append("material 读取失败: %s" % err)
            else:
                ext = os.path.splitext(p)[1].lstrip(".").lower()
                ctx["material_text"] = norm(txt)
                ctx["material_path"] = p
                if not (txt or "").strip():
                    ctx["material_source"] = "file:%s:empty" % ext
                else:
                    ctx["material_source"] = "file:" + ext
        else:
            warnings.append("material 路径不存在: %s" % mat_path)
            ctx["material_source"] = "missing"
    else:
        for cand in CASE_FILE_FALLBACK["material_path"]:
            p = os.path.join(base, cand)
            if os.path.exists(p):
                txt, err = _read_any_text(p)
                if txt is None:
                    ctx["material_source"] = "unreadable:%s" % cand
                    warnings.append("material 读取失败(%s): %s" % (cand, err))
                else:
                    ext = os.path.splitext(p)[1].lstrip(".").lower()
                    ctx["material_text"] = norm(txt)
                    ctx["material_path"] = p
                    if not (txt or "").strip():
                        ctx["material_source"] = "file:%s:empty" % ext
                    else:
                        ctx["material_source"] = "file:" + ext
                    ctx["notes"].append("material 由文件名兜底命中: %s" % cand)
                break
        else:
            ctx["material_source"] = "missing"

    # 文献：先内联，其次路径（.bib 文本）
    bib_inline = _first(case, CASE_BIB_KEYS)
    bib_path = _first(case, ("bibliography_path", "bib_path", "references_path", "bibtex_path", "library_path"))
    ctx["bib_docs"] = []
    ctx["bib_from_material"] = False
    if isinstance(bib_inline, str) and bib_inline.strip():
        ctx["bib_docs"].append(bib_inline)
        ctx["bibliography_source"] = "case_inline"
    elif isinstance(bib_inline, (list, dict)) and bib_inline:
        ctx["bib_docs"].append(bib_inline)
        ctx["bibliography_source"] = "case_inline"
    # 材料末尾常自带编号参考文献表（真实初稿的普遍写法）：剥出来当文献库，并从正文里摘掉
    if ctx.get("material_text"):
        body, ref_entries = split_material_references(ctx["material_text"])
        if ref_entries:
            ctx["material_text"] = body
            ctx["bib_from_material"] = True
            ctx["notes"].append("文献表取自材料末尾的编号列表（%d 条，已从正文剥除）" % len(ref_entries))
            if not ctx["bib_docs"]:
                ctx["bib_docs"].append(ref_entries)
                ctx["bibliography_source"] = "material_tail"
    if isinstance(bib_path, str) and bib_path.strip():
        p = bib_path if os.path.isabs(bib_path) else os.path.join(base, bib_path)
        if os.path.exists(p):
            txt, err = _read_any_text(p)
            if txt is None:
                warnings.append("bibliography 读取失败: %s" % err)
            else:
                ctx["bibliography_path"] = p
                ctx["bib_docs"].append(txt)
                ctx["bibliography_source"] = (ctx.get("bibliography_source") or "") + "+file:" + os.path.splitext(p)[1].lstrip(".").lower()
        else:
            warnings.append("bibliography 路径不存在: %s" % bib_path)
    elif not ctx["bib_docs"]:
        for cand in CASE_FILE_FALLBACK["bibliography_path"]:
            p = os.path.join(base, cand)
            if os.path.exists(p):
                txt, err = _read_any_text(p)
                if txt is not None:
                    ctx["bibliography_path"] = p
                    ctx["bib_docs"].append(txt)
                    ctx["bibliography_source"] = "file:" + os.path.splitext(p)[1].lstrip(".").lower()
                    ctx["notes"].append("bibliography 由文件名兜底命中: %s" % cand)
                break

    # 同目录其它 json（可能是拆开的材料）
    extra = []
    try:
        for name in sorted(os.listdir(base)):
            if not name.lower().endswith(".json"):
                continue
            if name.lower() in ("case.json", "task.json", "challenge.json", "config.json", "submission.json"):
                continue
            p = os.path.join(base, name)
            extra.append({"name": name, "path": p, "data": read_json(p, default={})})
    except Exception:  # noqa: BLE001
        pass
    ctx["extra_json"] = extra
    for e in extra:
        data = e["data"]
        if isinstance(data, dict):
            if not ctx["bib_docs"] and any(k in data for k in CASE_BIB_KEYS):
                ctx["bib_docs"].append(data)
                ctx["notes"].append("bibliography 取自额外文件 %s" % e["name"])
            if not ctx["material_text"] and isinstance(data.get("text"), str):
                ctx["material_text"] = norm(data["text"])
                ctx["notes"].append("material 取自额外文件 %s" % e["name"])
    return case, ctx


# ---------------------------------------------------------------- 结果输出

CONTRACT_ALIASES = {
    "introduction": "introduction.md",
    "intro": "introduction.md",
    "related_work": "introduction.md",
    "related": "introduction.md",
    "manuscript": "introduction.md",
    "draft": "introduction.md",
    "text": "introduction.md",
    "citations": "citation_map.json",
    "citation_map": "citation_map.json",
    "references": "citation_map.json",
    "bibliography": "citation_map.json",
    "claims": "claims.jsonl",
    "claim_map": "claims.jsonl",
    "fact_map": "claims.jsonl",
    "facts": "claims.jsonl",
    "groups": "groups.jsonl",
    "grouping": "groups.jsonl",
    "contributions": "contributions.jsonl",
    "contribution": "contributions.jsonl",
    "gaps": "gaps.jsonl",
    "gap": "gaps.jsonl",
    "check": "check.json",
    "checks": "check.json",
    "review": "review.md",
    "report": "review.md",
    "diff": "diff.md",
    "changes": "diff.md",
    "trace": "review.md",
}


def emit_result(out_path, case_id, status, primary, evidence=None, uncertainty=None,
                artifacts=None, contract=None, extra_top=None):
    """写 result.json：契约字段补齐 + primary_result 同名字段提到顶层。"""
    outdir = os.path.dirname(os.path.abspath(out_path)) or "."
    produced = sorted(os.listdir(outdir)) if os.path.isdir(outdir) else []
    result = {
        "schema": "introkit-result/1.0",
        "case_id": case_id,
        "status": status,
        "primary_result": primary,
        "evidence": evidence or [],
        "uncertainty": list(uncertainty or []),
        "artifacts": artifacts or [],
        "change_log": [],
        "tool_version": VERSION,
    }
    unmapped = []
    if isinstance(contract, dict) and contract:
        for key, spec in contract.items():
            target = CONTRACT_ALIASES.get(str(key).strip().lower())
            if target and target in produced:
                result.setdefault(key, target)
            elif target:
                result.setdefault(key, target)
            else:
                unmapped.append(key)
                if isinstance(spec, dict) and "default" in spec:
                    result.setdefault(key, spec["default"])
                else:
                    result.setdefault(key, None)
    if unmapped:
        result["uncertainty"].append("output_contract fields not mapped to a produced file: " + ", ".join(sorted(unmapped)))
    if isinstance(primary, dict):
        for k, v in primary.items():
            result.setdefault(k, v)
    if extra_top:
        for k, v in extra_top.items():
            result[k] = v
    dump_json(out_path, result)
    return result
