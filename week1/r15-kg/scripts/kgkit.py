"""kgkit: 文献知识图谱 Skill 的共用核（schema 宽容的读取层 + 通用工具）。

设计要点
--------
1. 输入 schema 宽容：平台的固定案例只保证"有 corpus-manifest / material / primary-material /
   secondary-material 这几份 JSON"，字段名不保证统一。所以这里的读取层按**候选键**逐个尝试，
   而不是硬编码字段名；读到什么记什么，读不到就记进 warnings（不猜、不补造）。
2. 证据一律是"逐字片段 + 位置"：source_id + paragraph_id + 原文短引，位置用组织方的段落 ID，
   绝不把自建页码冒充原 PDF 页。
3. 纯标准库；本文件被 kg_prep.py / kg_assemble.py / kg_query.py 共用。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

VERSION = "kgkit/1.0"

# --------------------------------------------------------------------------- 基础工具

_WS = re.compile(r"[ \t\u00a0\u3000]+")
_SOFT_HYPHEN = re.compile(r"[\u00ad\u2010\u2011]")


def norm(s):
    """压缩空白、去软连字符；不改字符本身（证据比对的第一级）。"""
    if s is None:
        return ""
    return _WS.sub(" ", _SOFT_HYPHEN.sub("-", str(s))).strip()


_PUNCT = {ord(c): None for c in "，。；：！？、“”‘’（）《》【】—…·,.;:!?\"'()[]{}<>-–—`"}


def norm_hard(s):
    """去标点、去空白、折叠大小写；用于宽容比对。"""
    return norm(s).translate(_PUNCT).replace(" ", "").lower()


def sha256_text(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_SENT = re.compile(r"(?<=[。！？；])\s*|(?<=[.!?])\s+")


def sentences(text):
    out = []
    for part in _SENT.split(norm(text)):
        part = part.strip()
        if part:
            out.append(part)
    return out


_TOK = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?%?")


def tokens(text):
    return [t.lower() for t in _TOK.findall(norm(text))]


def cjk_ratio(s):
    s = norm(s)
    if not s:
        return 0.0
    return len(re.findall(r"[\u4e00-\u9fff]", s)) / len(s)


def strip_tags(s):
    return norm(re.sub(r"<[^>]{1,80}>", " ", str(s or "")))


# --------------------------------------------------------------------------- schema 宽容读取

def _first(d, keys, default=None):
    """按候选键顺序取值；支持 a.b 形式的浅路径。"""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
        if "." in k:
            cur, ok = d, True
            for part in k.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and cur not in (None, "", [], {}):
                return cur
    return default


def as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    if isinstance(x, str):
        return [x]
    return []


_PARA_KEYS = ("paragraphs", "paragraph", "passages", "elements", "blocks", "body.paragraphs")
_TEXT_KEYS = ("text", "content", "value", "body", "#text", "plain_text", "paragraph_text", "string")
_PID_KEYS = ("paragraph_id", "para_id", "pid", "id", "xml_id", "xml:id", "@id", "pid_id")
_SECTION_KEYS = ("section", "section_title", "sec", "title", "heading", "parent_section")


def paragraph_text(p):
    """把一段的各种可能形态收敛成一个字符串。"""
    if isinstance(p, str):
        return norm(p)
    if not isinstance(p, dict):
        return ""
    raw = _first(p, _TEXT_KEYS)
    if raw is None:
        # JATS-ish：一段由若干 inline 节点组成
        for k in ("runs", "inline", "children", "spans", "content"):
            items = as_list(_first(p, (k,)))
            if items:
                parts = [paragraph_text(x) for x in items]
                return norm(" ".join(x for x in parts if x))
        return ""
    if isinstance(raw, list):
        return norm(" ".join(paragraph_text(x) for x in raw))
    return strip_tags(raw)


def iter_paragraphs(node, section=None, depth=0):
    """深度遍历：把任何嵌套结构里的段落挖出来，带上祖先标题当 section。"""
    if depth > 8 or node is None:
        return
    if isinstance(node, str):
        return
    if isinstance(node, list):
        for x in node:
            yield from iter_paragraphs(x, section, depth + 1)
        return
    if not isinstance(node, dict):
        return
    here = _first(node, _SECTION_KEYS) or section
    if isinstance(here, dict):
        here = _first(here, ("title", "text", "name")) or section
    text = paragraph_text(node)
    pid = _first(node, _PID_KEYS)
    has_child_paras = any(k in node for k in _PARA_KEYS)
    if text and len(text) >= 20 and (pid or not has_child_paras):
        yield {"paragraph_id": str(pid) if pid else None, "section": norm(here) if here else None,
               "text": text}
    for k in _PARA_KEYS + ("sections", "sec", "content", "document", "article", "items",
                           "materials", "children", "data"):
        if k in node:
            yield from iter_paragraphs(node[k], here, depth + 1)


_PAPER_LIST_KEYS = ("papers", "documents", "items", "materials", "corpus", "records", "entries")
_SOURCE_KEYS = ("source_id", "source", "id", "paper_id", "document_id", "doc_id", "sourceId")
_DOI_KEYS = ("doi", "DOI", "paper_doi")
_AUTHOR_KEYS = ("authors", "author", "creators", "author_list")
_TITLE_KEYS = ("title", "paper_title", "name", "article_title")
_LICENSE_KEYS = ("license", "licence", "rights", "copyright")


def _authors(node):
    raw = _first(node, _AUTHOR_KEYS)
    out = []
    for a in as_list(raw):
        if isinstance(a, dict):
            nm = _first(a, ("name", "full_name", "text", "literal", "given"))
            sur = _first(a, ("surname", "family", "last"))
            if nm and sur and str(sur) not in str(nm):
                nm = f"{nm} {sur}"
            if nm:
                out.append(norm(nm))
        elif a:
            out.append(norm(a))
    if not out and isinstance(raw, str) and raw.strip():
        out = [x.strip() for x in re.split(r"[;,]", raw) if x.strip()]
    return out


def _paper_from(node, fallback_index, warnings, hint_source=None):
    sid = _first(node, _SOURCE_KEYS) or hint_source
    paras = list(iter_paragraphs(node))
    if not paras:
        return None
    pid_seen = sum(1 for p in paras if p["paragraph_id"])
    if not sid:
        warnings.append(f"第 {fallback_index} 篇材料没有 source_id 字段，"
                        f"已按输入顺序命名为 paper-{fallback_index}（请核对 corpus-manifest）")
        sid = f"paper-{fallback_index}"
    if pid_seen == 0:
        warnings.append(f"{sid}: 段落没有 paragraph_id 字段，"
                        f"已按出现顺序编号 {sid}#p0001 形式；下游只能定位到该编号")
    for i, p in enumerate(paras, start=1):
        if not p["paragraph_id"]:
            p["paragraph_id"] = f"{sid}#p{i:04d}"
        p["source_id"] = str(sid)
    return {
        "source_id": str(sid),
        "title": norm(_first(node, _TITLE_KEYS) or ""),
        "doi": norm(_first(node, _DOI_KEYS) or ""),
        "authors": _authors(node),
        "license": norm(_first(node, _LICENSE_KEYS) or ""),
        "paragraphs": paras,
    }


def load_papers(*docs):
    """把若干份 JSON 文档并成 papers 列表；返回 (papers, warnings)。"""
    papers, warnings, seen = [], [], set()
    for di, doc in enumerate(docs, start=1):
        if doc is None:
            continue
        candidates = None
        for k in _PAPER_LIST_KEYS:
            v = doc.get(k) if isinstance(doc, dict) else None
            if isinstance(v, list) and v and all(isinstance(x, (dict, str)) for x in v):
                candidates = v
                break
        if candidates is None:
            candidates = [doc]
        for i, node in enumerate(candidates, start=1):
            if isinstance(node, str):
                node = {"text": node}
            if not isinstance(node, dict):
                continue
            p = _paper_from(node, f"{di}{i}", warnings)
            if not p:
                continue
            key = p["source_id"]
            if key in seen:
                warnings.append(f"重复的 source_id {key}：保留第一份，丢弃后一份")
                continue
            seen.add(key)
            papers.append(p)
    for p in papers:
        p["paragraph_count"] = len(p["paragraphs"])
    return papers, warnings


def load_manifest(doc, warnings):
    """从 corpus-manifest.json 里抽每篇的 DOI/作者/许可证/哈希，用于交叉核对。"""
    out = {}
    if not isinstance(doc, dict):
        return out
    nodes = None
    for k in _PAPER_LIST_KEYS:
        if isinstance(doc.get(k), list):
            nodes = doc[k]
            break
    for node in as_list(nodes if nodes is not None else doc):
        if not isinstance(node, dict):
            continue
        sid = _first(node, _SOURCE_KEYS)
        if not sid:
            continue
        out[str(sid)] = {
            "doi": norm(_first(node, _DOI_KEYS) or ""),
            "title": norm(_first(node, _TITLE_KEYS) or ""),
            "authors": _authors(node),
            "license": norm(_first(node, _LICENSE_KEYS) or ""),
            "source_sha256": norm(_first(node, ("source_sha256", "sha256", "hash")) or ""),
            "role": norm(_first(node, ("role", "kind", "tier")) or ""),
        }
    if not out:
        warnings.append("corpus-manifest.json 里没解析出条目：DOI/许可证核对被跳过")
    return out


# --------------------------------------------------------------------------- case 读取

CASE_MATERIAL_KEYS = ("material", "material_path", "materials", "material_json", "paragraphs")
CASE_PRIMARY_KEYS = ("primary_material", "primary", "primary_path", "primary_material_path")
CASE_SECONDARY_KEYS = ("secondary_material", "secondary", "secondary_path", "secondary_material_path")
CASE_MANIFEST_KEYS = ("corpus_manifest", "corpus", "manifest", "corpus_manifest_path", "manifest_path")
CASE_CORPUS_DIR_KEYS = ("material_dir", "corpus_dir", "data_dir", "input_dir")


def _resolve(path, base):
    if not path:
        return None
    path = str(path)
    if os.path.isabs(path) and os.path.exists(path):
        return path
    for cand in (os.path.join(base, path), path):
        if os.path.exists(cand):
            return os.path.abspath(cand)
    return None


def load_case(path, key_variants=None):
    """读 case.json，返回 (case, ctx)。ctx 里带已解析的文件路径与契约。"""
    case = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
    base = os.path.dirname(os.path.abspath(path)) if path and os.path.exists(path) else os.getcwd()
    ctx = {"case_id": case.get("case_id") or case.get("id") or "case",
           "case_path": os.path.abspath(path) if path and os.path.exists(path) else None,
           "base": base,
           "contract": case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {},
           "task": norm(case.get("task") or case.get("question") or ""),
           "notes": []}

    def pick(keys, extra=()):
        raw = _first(case, tuple(keys) + tuple(extra))
        p = _resolve(raw, base)
        if raw and not p:
            ctx["notes"].append(f"case 里给了 {raw!r} 但该路径不存在")
        return p

    d = pick(CASE_CORPUS_DIR_KEYS)
    ctx["material"] = pick(CASE_MATERIAL_KEYS)
    ctx["primary"] = pick(CASE_PRIMARY_KEYS)
    ctx["secondary"] = pick(CASE_SECONDARY_KEYS)
    ctx["manifest"] = pick(CASE_MANIFEST_KEYS)

    # 目录给定或字段缺失时，按文件名在 base / material 同目录里找
    dirs = [x for x in (d, base, os.path.dirname(ctx["material"] or "")) if x]
    names = {"material": ("material.json", "materials.json", "paragraphs.json"),
             "primary": ("primary-material.json", "primary_material.json", "primary.json"),
             "secondary": ("secondary-material.json", "secondary_material.json", "secondary.json"),
             "manifest": ("corpus-manifest.json", "corpus_manifest.json", "manifest.json")}
    for key, cands in names.items():
        if ctx.get(key):
            continue
        for dd in dirs:
            for nm in cands:
                p = os.path.join(dd, nm)
                if os.path.exists(p):
                    ctx[key] = os.path.abspath(p)
                    break
            if ctx.get(key):
                break
    # 兜底：把 base 下所有 *material*.json / *manifest*.json 收进来
    extra_files = []
    for dd in dirs[:2]:
        if not os.path.isdir(dd):
            continue
        for nm in sorted(os.listdir(dd)):
            if not nm.endswith(".json"):
                continue
            if nm in ("case.json", "task.json", "challenge.json", "config.json"):
                continue
            p = os.path.join(dd, nm)
            if p not in extra_files and os.path.abspath(p) != ctx["case_path"]:
                extra_files.append(p)
    ctx["extra_json"] = extra_files
    return case, ctx


def read_json(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # 读不动的输入要报出来，不能静默当空
        return {"__load_error__": f"{os.path.basename(path)}: {type(e).__name__}: {e}"}


# --------------------------------------------------------------------------- 结果输出

def emit_result(out_path, case_id, status, primary, evidence=None, uncertainty=None,
                artifacts=None, contract=None, extra_top=None):
    """按平台契约写 result.json：primary_result 的同名字段提到顶层、契约字段补齐。"""
    doc = {"schema": VERSION, "case_id": case_id, "status": status,
           "primary_result": primary or {},
           "evidence": evidence or [], "uncertainty": uncertainty or [],
           "artifacts": [], "change_log": []}
    for k, v in (primary or {}).items():
        if k not in doc:
            doc[k] = v
    if contract:
        for k, spec in contract.items():
            if k in doc:
                continue
            doc[k] = (spec or {}).get("default") if isinstance(spec, dict) else None
    if extra_top:
        for k, v in extra_top.items():
            doc.setdefault(k, v)
    arts = []
    base = os.path.dirname(os.path.abspath(out_path))
    for a in artifacts or []:
        p = a if isinstance(a, str) else a.get("path")
        if not p:
            continue
        ap = p if os.path.isabs(p) else os.path.join(base, p)
        entry = {"path": os.path.basename(ap), "role": (a.get("role") if isinstance(a, dict) else ""),
                 "media_type": (a.get("media_type") if isinstance(a, dict) else "text/plain")}
        if os.path.exists(ap):
            entry["bytes"] = os.path.getsize(ap)
            entry["sha256"] = sha256_file(ap)
        arts.append(entry)
    doc["artifacts"] = arts
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


def dump_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def dump_jsonl(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_jsonl(path):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                rows.append({"__parse_error__": f"line {i}: {e}", "raw": line[:120]})
    return rows


def pjson(obj, ascii_only=True):
    print(json.dumps(obj, ensure_ascii=ascii_only))


def json_dump_narrow(obj):
    return json.dumps(obj, ensure_ascii=True)


def add_repo_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
