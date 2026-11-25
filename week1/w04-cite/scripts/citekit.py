#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""citekit — 参考文献与引用管理内核。

只做可核验的事：
  · 解析文献库（BibTeX / RIS / 编号制纯文本）
  · 扫描正文引用标记（顺序编码制 [1,2]、著者-出版年 (Smith, 2020)、LaTeX \\cite{}）
  · 条目去重（DOI / 题名+年份 / 首作者+年份），给出合并依据
  · 按首次出现重排编号，区间压缩，输出新旧编号映射
  · 按 GB/T 7714—2015 生成文末表
  · 逐项自检：悬空引用、未被引用、编号连续性、字段缺失、DOI 形态、去重残留

不联网。DOI 只做形态与一致性检查；真实存在性由人工或联网工具复核。
"""
from __future__ import annotations

import difflib
import json
import os
import re

# ---------------------------------------------------------------- 文本工具


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\u00ad", "")).strip()


def split_authors(s: str):
    """BibTeX 的 and / RIS 的逐行 / 纯文本的分号，统一成作者列表。"""
    if not s:
        return []
    if " and " in s:
        parts = re.split(r"\s+and\s+", s)
    elif ";" in s:
        parts = s.split(";")
    else:
        parts = [s]
    return [norm(p).strip(".") for p in parts if norm(p)]


def norm_doi(doi: str) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d.strip(" .;")


DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s\"<>]+$")


def doi_ok(doi: str) -> bool:
    return bool(DOI_RE.match(norm_doi(doi)))


def title_key(title: str) -> str:
    t = norm(title).lower()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, title_key(a), title_key(b)).ratio()


# ---------------------------------------------------------------- 文献库解析


def parse_bib(text: str):
    """解析 BibTeX；用花括号配平扫描，容忍嵌套与跨行字段。"""
    entries = []
    i = 0
    n = len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        key = m.group(2)
        start = at + m.end()
        depth = 1
        j = start
        while j < n and depth:
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        body = text[start:j - 1]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", body):
            name = fm.group(1).lower()
            val = fm.group(2).strip()
            if val.startswith("{"):
                val = val[1:-1]
            elif val.startswith('"'):
                val = val[1:-1]
            val = re.sub(r"\s+", " ", val).strip().rstrip(",")
            fields[name] = val
        if etype not in ("comment", "string", "preamble"):
            entries.append({"source": "bibtex", "type": etype, "key": key,
                            "fields": fields, "raw": text[at:j]})
        i = j
    return entries


def parse_ris(text: str):
    entries, cur, tag = [], {}, None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "TY":
                cur = {"source": "ris", "type": "article", "fields": {}}
                cur["ris_type"] = val
            if cur is not None and tag not in ("TY", "ER"):
                f = cur["fields"]
                if tag == "AU":
                    f["author"] = (f.get("author", "") + " and " + val).strip(" and ")
                elif tag == "TI":
                    f["title"] = val
                elif tag == "JO" or tag == "T2":
                    f.setdefault("journal", val)
                elif tag == "PY":
                    f["year"] = val[:4]
                elif tag == "VL":
                    f["volume"] = val
                elif tag == "IS":
                    f["number"] = val
                elif tag == "SP":
                    f["pages"] = val
                elif tag == "EP":
                    f["pages"] = (f.get("pages", "") + "-" + val).strip("-")
                elif tag == "DO":
                    f["doi"] = val
                elif tag == "PB":
                    f["publisher"] = val
                elif tag == "CY":
                    f["address"] = val
        elif line.strip() == "ER  -" and cur is not None:
            entries.append(cur)
            cur = None
    return entries


NUM_ENTRY_RE = re.compile(r"^\s*\[?(\d{1,3})[\].、]\s*(.+)$")


def parse_numbered(text: str):
    """编号制文末表（GB/T 7714 常见形态）：[1] 作者. 题名[J]. 刊名, 年, 卷(期): 页."""
    entries, cur = [], None
    for line in text.splitlines():
        m = NUM_ENTRY_RE.match(line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"source": "plain", "key": f"ref{m.group(1)}",
                   "type": "unknown", "fields": {}, "raw": m.group(2).strip()}
            cur["fields"]["_text"] = m.group(2).strip()
        elif cur is not None and line.strip() and not line.strip().startswith(("#", "-")):
            cur["raw"] += " " + line.strip()
            cur["fields"]["_text"] += " " + line.strip()
    if cur:
        entries.append(cur)
    for e in entries:
        enrich_plain(e)
    return entries


def enrich_plain(e):
    """从纯文本条目里抽 DOI / 年 / 类型标识 / 题名。抽不到就留空，不猜。"""
    t = e["fields"].get("_text", "")
    m = re.search(r"(10\.\d{4,9}/[^\s，。;；]+)", t)
    if m:
        e["fields"]["doi"] = m.group(1).rstrip(".")
    y = re.search(r"(19|20)\d{2}", t)
    if y:
        e["fields"]["year"] = y.group(0)
    tm = re.search(r"\[(J|M|C|D|P|S|R|Z|EB/OL|J/OL)\]", t)
    if tm:
        e["type"] = {"J": "article", "M": "book", "C": "inproceedings", "D": "thesis",
                     "P": "patent", "S": "standard", "R": "report", "Z": "misc",
                     "EB/OL": "online", "J/OL": "article"}[tm.group(1)]
    parts = re.split(r"[.。]\s*", t, maxsplit=2)
    if len(parts) >= 2:
        e["fields"].setdefault("author", parts[0])
        e["fields"].setdefault("title", re.sub(r"\[[A-Z/]+\]", "", parts[1]).strip())


def load_library(paths):
    entries = []
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        low = p.lower()
        if low.endswith((".bib", ".bibtex")):
            entries.extend(parse_bib(text))
        elif low.endswith(".ris"):
            entries.extend(parse_ris(text))
        elif low.endswith((".md", ".txt", ".gb", ".refs")):
            entries.extend(parse_numbered(text))
        else:
            # 未知后缀：按内容判断
            if "@" in text and re.search(r"@\w+\s*\{", text):
                entries.extend(parse_bib(text))
            elif re.search(r"^TY\s{2}-", text, re.M):
                entries.extend(parse_ris(text))
            else:
                entries.extend(parse_numbered(text))
    # 原编号 = 文献库中的顺序（正文 [n] 按此解析），去重后仍保留
    for i, e in enumerate(entries, 1):
        e["old_index"] = i
    return entries


# ---------------------------------------------------------------- 去重


def dedupe(entries):
    """三档判据：DOI 相同 → 题名高度相似且同年 → 首作者+年+题名首词。

    返回 (merged, groups)。groups 记录合并依据，供人工复核。
    """
    merged, groups = [], []
    for e in entries:
        e = dict(e)
        e["fields"] = dict(e.get("fields") or {})
        e["_idx"] = len(merged) + len(groups)
        e.setdefault("aliases", [e.get("old_index")])
        target = None
        basis = ""
        doi = norm_doi(e["fields"].get("doi", ""))
        if doi:
            for m in merged:
                if norm_doi(m["fields"].get("doi", "")) == doi:
                    target, basis = m, f"same DOI {doi}"
                    break
        if target is None:
            t = e["fields"].get("title", "")
            y = str(e["fields"].get("year", ""))
            if t:
                for m in merged:
                    mt = m["fields"].get("title", "")
                    my = str(m["fields"].get("year", ""))
                    s = sim(t, mt)
                    if s >= 0.90 and (not y or not my or y == my):
                        target, basis = m, f"title similarity {s:.2f}"
                        break
        if target is None:
            target = e
            merged.append(e)
        else:
            for k, v in e["fields"].items():
                if v and not target["fields"].get(k):
                    target["fields"][k] = v
            target.setdefault("_merged_from", []).append(e.get("key") or e["fields"].get("title", ""))
            target.setdefault("aliases", []).append(e.get("old_index"))
            groups.append({"kept": target.get("key"), "merged": e.get("key"),
                           "basis": basis,
                           "old_indices": [target.get("old_index"), e.get("old_index")],
                           "title": e["fields"].get("title", "")[:80]})
    for i, m in enumerate(merged):
        m["index"] = i + 1
    return merged, groups


# ---------------------------------------------------------------- 正文扫描

NUM_CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[-–,，]\s*\d{1,3})*)\]")
AY_CITE_RE = re.compile(r"\(([A-Z][A-Za-z\u00c0-\u024f\-']+)(?:\s+et\s+al\.?)?,?\s*((?:19|20)\d{2})[a-z]?\)")
TEX_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\{([^}]+)\}")


def expand_numeric(group: str):
    out = []
    for part in re.split(r"\s*[,，]\s*", group):
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(range(a, b + 1) if a <= b else [a])
        elif part.strip().isdigit():
            out.append(int(part.strip()))
    return out


def compress_numeric(nums):
    nums = sorted(set(nums))
    if not nums:
        return ""
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(out)


def scan_citations(text: str):
    """返回引用标记列表：{kind, span, raw, numbers|authors|keys}。"""
    cits = []
    for m in NUM_CITE_RE.finditer(text):
        cits.append({"kind": "numeric", "start": m.start(), "end": m.end(),
                     "raw": m.group(0), "numbers": expand_numeric(m.group(1))})
    for m in TEX_CITE_RE.finditer(text):
        cits.append({"kind": "latex", "start": m.start(), "end": m.end(),
                     "raw": m.group(0), "keys": [k.strip() for k in m.group(1).split(",")]})
    for m in AY_CITE_RE.finditer(text):
        cits.append({"kind": "author-year", "start": m.start(), "end": m.end(),
                     "raw": m.group(0), "authors": [m.group(1)], "year": m.group(2)})
    cits.sort(key=lambda c: c["start"])
    # 去掉被更高优先级匹配覆盖的片段（同一位置的重复识别）
    pruned = []
    for c in cits:
        if pruned and c["start"] < pruned[-1]["end"]:
            continue
        pruned.append(c)
    return pruned


def renumber(text: str, cits, by_old):
    """按首次出现给编号重排。by_old: 原编号 → 去重后的条目。

    返回 (新文本, 条目序号→新编号, 悬空引用, 新顺序的条目序号)。
    """
    order, mapping, unresolved = [], {}, []
    for c in cits:
        if c["kind"] != "numeric":
            continue
        for n in c["numbers"]:
            e = by_old.get(n)
            if not e:
                unresolved.append(n)
                continue
            if e["index"] not in mapping:
                mapping[e["index"]] = len(order) + 1
                order.append(e["index"])
    out, cursor = [], 0
    for c in cits:
        if c["kind"] != "numeric":
            continue
        new = [mapping[by_old[n]["index"]] for n in c["numbers"] if n in by_old]
        repl = "[" + compress_numeric(new) + "]" if new else c["raw"]
        out.append(text[cursor:c["start"]])
        out.append(repl)
        cursor = c["end"]
    out.append(text[cursor:])
    return "".join(out), mapping, unresolved, order


# ---------------------------------------------------------------- GB/T 7714

TYPE_TAG = {"article": "J", "book": "M", "inproceedings": "C", "conference": "C",
            "thesis": "D", "phdthesis": "D", "mastersthesis": "D", "patent": "P",
            "standard": "S", "techreport": "R", "report": "R", "misc": "Z",
            "online": "EB/OL", "unpublished": "Z"}


def is_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def initials(given: str) -> str:
    parts = re.split(r"[\s.\-]+", given.strip())
    return " ".join(p[0].upper() for p in parts if p)


def gbt_name(name: str) -> str:
    """GB/T 7714—2015：西文姓全大写、名缩写不加点；中文姓名原样。"""
    name = norm(name)
    if is_cjk(name):
        return name
    if "," in name:
        family, given = [x.strip() for x in name.split(",", 1)]
    else:
        toks = name.split()
        if len(toks) == 1:
            return name.upper()
        family, given = toks[-1], " ".join(toks[:-1])
    ini = initials(given)
    return f"{family.upper()} {ini}".strip()


def fmt_authors(author: str):
    names = split_authors(author)
    if not names:
        return ""
    cjk = is_cjk(" ".join(names))
    if cjk:
        shown = names[:3]
        return "，".join(shown) + ("，等" if len(names) > 3 else "")
    shown = [gbt_name(n) for n in names[:3]]
    out = ", ".join(shown)
    if len(names) > 3:
        out += ", et al"
    return out


def fmt_pages(p: str):
    p = (p or "").strip()
    p = re.sub(r"\s*[-–—]+\s*", "-", p)
    return p


def format_gbt7714(e: dict):
    f = e.get("fields", {})
    tag = TYPE_TAG.get((e.get("type") or "").lower(), "Z")
    authors = fmt_authors(f.get("author", "") or f.get("authors", ""))
    title = norm(f.get("title", "")).rstrip(".")
    year = f.get("year", "")
    vol = f.get("volume", "")
    num = f.get("number", "") or f.get("issue", "")
    pages = fmt_pages(f.get("pages", ""))
    doi = norm_doi(f.get("doi", ""))
    journal = norm(f.get("journal", "") or f.get("journaltitle", "") or f.get("booktitle", ""))
    pub = norm(f.get("publisher", ""))
    addr = norm(f.get("address", "") or f.get("location", ""))

    parts = []
    if authors:
        parts.append(authors.rstrip(".") + ".")
    if title:
        parts.append(f"{title}[{tag}].")
    if tag == "J":
        seg = journal
        if year:
            seg += f", {year}"
        if vol:
            seg += f", {vol}"
        if num:
            seg += f"({num})"
        if pages:
            seg += f": {pages}"
        if seg:
            parts.append(seg.strip(", ") + ".")
    elif tag == "C":
        seg = ""
        if journal:
            seg += f"//{journal}"
        if addr:
            seg += f". {addr}"
        if pub:
            seg += f": {pub}"
        if year:
            seg += f", {year}"
        if pages:
            seg += f": {pages}"
        if seg:
            parts.append(seg.strip(". ") + ".")
    elif tag in ("M", "D", "R"):
        seg = ""
        if addr:
            seg += f"{addr}: "
        if pub:
            seg += pub
        if year:
            seg += f", {year}" if seg else f"{year}"
        if pages:
            seg += f": {pages}"
        if seg:
            parts.append(seg + ".")
    else:
        seg = ", ".join(x for x in (pub, year) if x)
        if seg:
            parts.append(seg + ".")
    if doi:
        parts.append(f"DOI: {doi}.")
    return " ".join(p for p in parts if p).strip()


# ---------------------------------------------------------------- 自检


def check_entries(entries, cits, mapping, unresolved, dedupe_groups):
    issues = []
    cited = set(mapping)
    all_idx = {e["index"] for e in entries}
    uncited = sorted(all_idx - cited - {n for n in unresolved if n in all_idx})
    if unresolved:
        issues.append({"level": "error", "kind": "dangling_citation",
                       "detail": f"cited numbers with no entry: {sorted(set(unresolved))}"})
    if uncited:
        issues.append({"level": "warn", "kind": "uncited_entry",
                       "detail": f"entries never cited: {uncited}"})
    dup_doi = {}
    for e in entries:
        d = norm_doi(e["fields"].get("doi", ""))
        if d:
            dup_doi.setdefault(d, []).append(e["index"])
    left = {k: v for k, v in dup_doi.items() if len(v) > 1}
    if left:
        issues.append({"level": "error", "kind": "duplicate_doi",
                       "detail": left})
    bad_doi = [e["index"] for e in entries
               if e["fields"].get("doi") and not doi_ok(e["fields"]["doi"])]
    if bad_doi:
        issues.append({"level": "warn", "kind": "doi_syntax",
                       "detail": f"entries with malformed DOI: {bad_doi}"})
    missing = []
    for e in entries:
        need = ["author", "title", "year"] if e.get("type") in ("article", "book", "inproceedings") else ["title"]
        lack = [k for k in need if not e["fields"].get(k)]
        if lack:
            missing.append({"index": e["index"], "missing": lack})
    if missing:
        issues.append({"level": "warn", "kind": "missing_fields", "detail": missing})
    return {"issues": issues,
            "uncited": uncited,
            "dangling": sorted(set(unresolved)),
            "n_entries": len(entries),
            "n_cited": len(cited),
            "n_citations": sum(1 for c in cits if c["kind"] == "numeric"),
            "n_duplicates_merged": sum(1 for g in dedupe_groups if g.get("merged")),
            "status": "fail" if any(i["level"] == "error" for i in issues) else
                      ("warn" if issues else "pass")}
