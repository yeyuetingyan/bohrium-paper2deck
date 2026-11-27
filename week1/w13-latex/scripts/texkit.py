#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""texkit —— LaTeX 写作与编译 Skill 的共用核（纯标准库）。

包含四块能力：
1. 文本与 IO 基础（归一化、编码回退、JSON/JSONL 读写、结果导出）；
2. LaTeX 源码静态解析（注释剔除、括号与环境配对、导言区、标签/引用/文献、
   数学区域、表格、不可变成分）；
3. BibTeX 解析与文献对账；
4. TeX 工具链探测、多轮编译、编译日志解析与错误分类。

所有函数都不依赖第三方库；只有在需要真正编译时才调用外部 TeX 引擎。
"""

import io
import json
import os
import re
import shutil
import subprocess
import time

VERSION = "texkit/1.0"

# --------------------------------------------------------------------------
# 一、文本基础
# --------------------------------------------------------------------------

_WS = re.compile(r"[ \t\u00a0]+")


def norm(s):
    """压缩行内空白、去软连字符；保留换行与空行。"""
    if s is None:
        return ""
    s = s.replace("\u00ad", "").replace("\ufeff", "")
    lines = [_WS.sub(" ", ln).rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines)


def norm_hard(s):
    """去标点空白并小写 —— 比对用。"""
    if s is None:
        return ""
    s = norm(s).lower()
    s = re.sub(r"[\s\.,;:!\?\(\)\[\]\{\}<>\"'`~^|/\\\-\+\*=_、。，；：！？（）【】《》「」『』…—－]+", "", s)
    return s


def flat(s):
    """只去空白（保留标点）—— 多重集比对用。"""
    if s is None:
        return ""
    return re.sub(r"\s+", "", s)


def sha256_text(s):
    import hashlib

    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def sha256_16(s):
    return sha256_text(s)[:16]


def sha256_file(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lines_of(text):
    return (text or "").split("\n")


def line_of_index(text, idx):
    """字符下标 → 行号（1 基）与列号（1 基）。"""
    if idx is None or idx < 0:
        return (None, None)
    head = (text or "")[:idx]
    line = head.count("\n") + 1
    col = idx - (head.rfind("\n") + 1) + 1
    return (line, col)


# --------------------------------------------------------------------------
# 二、IO
# --------------------------------------------------------------------------


def read_json(path):
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return {"__load_error__": "%s: %s" % (type(exc).__name__, exc)}


def read_jsonl(path):
    """读 JSONL；也接受 JSON 数组形态（[ {...}, ... ]），两种写法都当行记录处理。"""
    out = []
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            raw = fh.read().strip()
    except Exception:  # noqa: BLE001
        return []
    if not raw:
        return out
    if raw.startswith("["):
        try:
            doc = json.loads(raw)
            if isinstance(doc, list):
                return doc
        except Exception:  # noqa: BLE001
            return [{"__line_error__": "json array"}]
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001
            out.append({"__line_error__": ln[:200]})
    return out


def load_jsonl(path):
    return read_jsonl(path)


def dump_json(path, obj, indent=2):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent, sort_keys=False)
        fh.write("\n")
    return path


def dump_jsonl(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def dump_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text or "")
    return path


def pjson(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


TEXT_EXTS = (".tex", ".bib", ".bbl", ".cls", ".sty", ".bst", ".txt", ".md", ".cfg", ".def", ".log", ".ltx",
             ".docx", ".doc", ".odt", ".rtf", ".pdf")
_BIN_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".bbl", ".aux", ".out", ".toc", ".synctex")


def _read_bytes_text(raw):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8:replace"


def read_text_any(path):
    """读任意文本文件，返回 (text, note)。读不动时 note 以 unreadable: 开头。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except Exception as exc:  # noqa: BLE001
        return "", "unreadable:%s: %s" % (type(exc).__name__, exc)
    if not raw:
        return "", "empty"
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        # Word 稿子：zipfile + word/document.xml（纯标准库），坏包/旧 .doc 一律如实报 unreadable，
        # 绝不能把压缩包的字节当文本解出来（那会把“读不出”伪装成“有内容”）。
        try:
            import zipfile
            import re as _re

            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = _re.sub(r"</w:p>", "\n", xml)
            txt = _re.sub(r"<[^>]+>", "", xml)
            if not txt.strip():
                return "", "unreadable:docx:no_text"
            return norm(txt), "docx:xml"
        except Exception as exc:  # noqa: BLE001
            return "", "unreadable:docx: %s" % exc
    if ext in (".doc", ".odt", ".rtf"):
        return "", "unreadable:no_extractor:%s" % ext
    if ext == ".pdf":
        try:
            import fitz  # type: ignore

            doc = fitz.open(path)
            txt = "\n".join(pg.get_text() for pg in doc)
            doc.close()
            if not txt.strip():
                return "", "unreadable:no_text_layer"
            return norm(txt), "pdf:fitz"
        except Exception as exc:  # noqa: BLE001
            return "", "unreadable:pdf:%s" % exc
    text, enc = _read_bytes_text(raw)
    if not text.strip():
        return "", "empty"
    return norm(text), "text:%s" % enc


CASE_MATERIAL_KEYS = (
    "material_files", "materials", "material", "sources", "files", "project_files",
    "tex_files", "inputs",
)
CASE_FILE_FALLBACK = {
    "main_tex": ("main.tex", "paper.tex", "manuscript.tex", "article.tex", "document.tex", "ms.tex"),
    "bib": ("references.bib", "refs.bib", "bibliography.bib", "library.bib"),
    "template": ("template.cls", "journal.cls", "main.cls"),
}


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def load_case(path):
    """读 case.json，返回 (case, ctx)。ctx 里有 base/case_id/contract/material_paths 等。"""
    case = read_json(path)
    if "__load_error__" in case:
        case = {}
    base = os.path.dirname(os.path.abspath(path))
    ctx = {
        "case_path": os.path.abspath(path),
        "base": base,
        "case_id": _first(case, ("case_id", "id", "caseId")) or os.path.basename(base),
        "contract": _first(case, ("output_contract", "outputContract", "contract")) or {},
        "task": _first(case, ("task", "task_text", "instruction")) or "",
        "audience": _first(case, ("audience", "readers")) or "",
        "genre": _first(case, ("genre", "doc_type", "type")) or "",
        "language": _first(case, ("language", "lang")) or "",
        "template": _first(case, ("template", "template_class", "journal")) or "",
        "engine": _first(case, ("engine", "tex_engine", "compiler")) or "",
        "format_constraints": _first(case, ("format_constraints", "constraints")) or {},
        "main_file": _first(case, ("main_file", "main", "main_tex", "entry", "root_file")) or "",
        "notes": [],
        "extra_json": {},
    }
    mats = []
    for m in _as_list(_first(case, CASE_MATERIAL_KEYS)):
        if isinstance(m, str):
            mats.append(m)
        elif isinstance(m, dict):
            p = _first(m, ("path", "file", "name", "src"))
            if p:
                mats.append(p)
    # 文件名兜底：case 目录与 base 下常见名
    if not mats:
        for cand in CASE_FILE_FALLBACK["main_tex"]:
            if os.path.exists(os.path.join(base, cand)):
                mats.append(cand)
                ctx["notes"].append("material_files 未声明，按文件名兜底找到 %s" % cand)
                break
    ctx["material_paths"] = [os.path.normpath(os.path.join(base, m)) for m in mats]
    # 目录里其它 json
    try:
        for fn in sorted(os.listdir(base)):
            if fn.lower().endswith(".json") and fn.lower() not in ("case.json", "config.json", "challenge.json"):
                ctx["extra_json"][fn] = read_json(os.path.join(base, fn))
    except Exception:  # noqa: BLE001
        pass
    return case, ctx


# --------------------------------------------------------------------------
# 三、LaTeX 静态解析
# ------------------------------------------------------------------------------


def strip_comments(src):
    """删掉 % 注释（保留 \\% 与 % 前的转义），保持行数与字符位置基本不变（注释内容换成空格）。"""
    out = []
    for ln in (src or "").split("\n"):
        m = re.search(r"(?<!\\)%", ln)
        if m:
            keep = ln[: m.start()]
            out.append(keep + " " * (len(ln) - len(keep)))
        else:
            out.append(ln)
    return "\n".join(out)


def _n_backslashes(s, i):
    """i 前面连续反斜杠的个数。"""
    n = 0
    j = i - 1
    while j >= 0 and s[j] == "\\":
        n += 1
        j -= 1
    return n


def _escaped(s, i):
    """位置 i 的字符是否被反斜杠转义：前面连续反斜杠为奇数个才算转义。

    真实论文里 `\\\\{` 很常见（换行后紧跟花括号），旧实现只看前一个字符是不是反斜杠，
    会把这类整体漏算，导致一堆假 `brace_unbalanced`。
    """
    return _n_backslashes(s, i) % 2 == 1


def brace_balance(src):
    """返回括号不平衡的位置列表：[{index, line, col, char, depth}]。"""
    clean = strip_comments(src)
    depth = 0
    bad = []
    for i, ch in enumerate(clean):
        if ch == "{" and not _escaped(clean, i):
            depth += 1
        elif ch == "}" and not _escaped(clean, i):
            depth -= 1
            if depth < 0:
                ln, col = line_of_index(clean, i)
                bad.append({"index": i, "line": ln, "col": col, "char": "}", "depth": depth})
                depth = 0
    if depth > 0:
        bad.append({"index": None, "line": None, "col": None, "char": "{", "depth": depth})
    return bad


ENV_BEGIN_RE = re.compile(r"\\begin\s*\{([^}]+)\}")
ENV_END_RE = re.compile(r"\\end\s*\{([^}]+)\}")
SELF_CLOSING = {"document"} - {"document"}  # 占位：无真正自闭合环境


def environments(src):
    """扫环境配对，返回 (envs, problems)。envs 每项 {name, begin_line, end_line}。"""
    clean = strip_comments(src)
    stack = []
    envs = []
    problems = []
    for m in re.finditer(r"\\(begin|end)\s*\{([^}]+)\}", clean):
        kind, name = m.group(1), m.group(2).strip()
        ln, _ = line_of_index(clean, m.start())
        if kind == "begin":
            stack.append((name, ln))
        else:
            if not stack:
                problems.append({"kind": "end_without_begin", "env": name, "line": ln})
                continue
            top_name, top_ln = stack[-1]
            if top_name == name:
                stack.pop()
                envs.append({"name": name, "begin_line": top_ln, "end_line": ln})
            else:
                # 尝试在栈里找
                pos = None
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        pos = i
                        break
                if pos is None:
                    problems.append({"kind": "end_without_begin", "env": name, "line": ln, "open": top_name})
                else:
                    for j in range(len(stack) - 1, pos - 1, -1):
                        problems.append(
                            {"kind": "unclosed_env", "env": stack[j][0], "line": stack[j][1], "closed_by": name}
                        )
                    stack = stack[:pos]
                    envs.append({"name": name, "begin_line": ln, "end_line": ln})
    for name, ln in stack:
        problems.append({"kind": "unclosed_env", "env": name, "line": ln})
    return envs, problems


DOC_CLASS_RE = re.compile(r"\\documentclass\s*(\[[^\]]*\])?\s*\{([^}]+)\}")
PACKAGE_RE = re.compile(r"\\usepackage\s*(\[[^\]]*\])?\s*\{([^}]+)\}")
MAGIC_ENGINE_RE = re.compile(r"%\s*!TEX\s+(?:program|TS-program)\s*=\s*([A-Za-z]+)")
MAGIC_ROOT_RE = re.compile(r"%\s*!TEX\s+root\s*=\s*(\S+)")


def document_class(src):
    m = DOC_CLASS_RE.search(strip_comments(src))
    if not m:
        return None
    return {"options": (m.group(1) or "").strip("[]"), "name": m.group(2).strip(),
            "line": line_of_index(src, m.start())[0]}


def packages(src):
    clean = strip_comments(src)
    out = []
    for i, m in enumerate(PACKAGE_RE.finditer(clean)):
        opts = (m.group(1) or "").strip("[]")
        for name in m.group(2).split(","):
            name = name.strip()
            if name:
                out.append({"name": name, "options": opts, "order": i,
                            "line": line_of_index(clean, m.start())[0]})
    return out


def magic_engine(src):
    m = MAGIC_ENGINE_RE.search(src or "")
    return m.group(1) if m else None


def magic_root(src):
    m = MAGIC_ROOT_RE.search(src or "")
    return m.group(1) if m else None


INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def inputs(src):
    clean = strip_comments(src)
    out = []
    for m in INPUT_RE.finditer(clean):
        out.append({"target": m.group(1).strip(), "line": line_of_index(clean, m.start())[0]})
    return out


LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref|vref)\s*\{([^}]+)\}")


def labels(src):
    clean = strip_comments(src)
    out = []
    for m in LABEL_RE.finditer(clean):
        out.append({"key": m.group(1).strip(), "line": line_of_index(clean, m.start())[0]})
    return out


def refs(src):
    clean = strip_comments(src)
    out = []
    for m in REF_RE.finditer(clean):
        for key in m.group(1).split(","):
            key = key.strip()
            if key:
                out.append({"key": key, "command": m.group(0).split("{")[0].strip("\\"),
                            "line": line_of_index(clean, m.start())[0]})
    return out


CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|parencite|textcite|autocite|footcite|supercite)"
    r"\s*(?:\[[^\]]*\]){0,2}\s*\{([^}]+)\}"
)


def citations(src):
    clean = strip_comments(src)
    out = []
    for m in CITE_RE.finditer(clean):
        for key in m.group(1).split(","):
            key = key.strip()
            if key:
                out.append({"key": key, "command": m.group(0).split("{")[0].strip("\\"),
                            "line": line_of_index(clean, m.start())[0]})
    return out


BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^}]+)\}")
ADDBIB_RE = re.compile(r"\\addbibresource\s*(\[[^\]]*\])?\s*\{([^}]+)\}")
BIBSTYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^}]+)\}")


def bibliography_directives(src):
    clean = strip_comments(src)
    out = {"bibliography": [], "addbibresource": [], "style": None}
    for m in BIBLIOGRAPHY_RE.finditer(clean):
        for name in m.group(1).split(","):
            if name.strip():
                out["bibliography"].append({"target": name.strip(), "line": line_of_index(clean, m.start())[0]})
    for m in ADDBIB_RE.finditer(clean):
        out["addbibresource"].append({"target": m.group(2).strip(), "line": line_of_index(clean, m.start())[0]})
    m = BIBSTYLE_RE.search(clean)
    if m:
        out["style"] = m.group(1).strip()
    return out


MATH_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*", "multline",
             "multline*", "eqnarray", "eqnarray*", "split", "cases", "array", "displaymath", "math")
# 只有这些环境真的吃编号；array/cases/split/math 只是排版容器，不该要求 \label
NUMBERED_MATH_ENVS = ("equation", "align", "gather", "multline", "eqnarray")


def math_regions(src):
    """抽取数学区域：$...$、$$...$$、\\(...\\)、\\[...\\]、带编号的公式环境。"""
    clean = strip_comments(src)
    out = []
    for m in re.finditer(r"\$\$(.+?)\$\$", clean, re.S):
        out.append({"kind": "display", "env": None, "body": m.group(1).strip(),
                    "line": line_of_index(clean, m.start())[0], "numbered": False})
    for m in re.finditer(r"(?<!\$)\$(?!\$)([^$]+?)(?<!\$)\$(?!\$)", clean):
        out.append({"kind": "inline", "env": None, "body": m.group(1).strip(),
                    "line": line_of_index(clean, m.start())[0], "numbered": False})
    for m in re.finditer(r"\\\[(.+?)\\\]", clean, re.S):
        out.append({"kind": "display", "env": None, "body": m.group(1).strip(),
                    "line": line_of_index(clean, m.start())[0], "numbered": False})
    for m in re.finditer(r"\\\((.+?)\\\)", clean, re.S):
        out.append({"kind": "inline", "env": None, "body": m.group(1).strip(),
                    "line": line_of_index(clean, m.start())[0], "numbered": False})
    for env in MATH_ENVS:
        if env == "math":
            continue
        pat = re.compile(r"\\begin\s*\{%s\}(.+?)\\end\s*\{%s\}" % (re.escape(env), re.escape(env)), re.S)
        for m in pat.finditer(clean):
            out.append({"kind": "environment", "env": env, "body": m.group(1).strip(),
                        "line": line_of_index(clean, m.start())[0],
                        "numbered": (not env.endswith("*")) and env in NUMBERED_MATH_ENVS})
    out.sort(key=lambda d: d.get("line") or 0)
    return out


TABULAR_RE = re.compile(
    r"\\begin\s*\{(tabular|tabularx|longtable|table|table\*)\}(\{(?:[^{}]|\{[^{}]*\})*\})?", re.S)


SPEC_WRAP_RE = re.compile(r"[pmb]\s*\{[^{}]*\}|@\s*\{[^{}]*\}|[<>]\s*\{[^{}]*\}")


def _skip_group(s, i):
    """从 s[i]=='{' 跳到配对的 '}' 之后。"""
    depth = 0
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def count_columns(spec):
    """数 tabular 的列数。

    真实表的列声明比 `{lll}` 复杂得多：
      - `p{2.2cm}` / `m{...}` / `b{...}` / `x{42}`（作者自定义的 `\\newcolumntype`）都带参数组；
      - `@{...}` / `>{...}` / `<{...}` / `!{...}` 是**修饰**不是列；
      - `tabularx` 的写法是 `{l}{width}`，第二个组不是列声明。
    所以按字符扫描：字母计一列并跳过它的参数组，修饰符只跳过参数组。
    """
    sp = (spec or "").strip()
    if sp.startswith("{"):
        parts = re.findall(r"\{((?:[^{}]|\{[^{}]*\})*)\}", sp)
        if parts:
            sp = parts[0]
    n = 0
    i = 0
    while i < len(sp):
        ch = sp[i]
        if ch in "@><!":
            i += 1
            while i < len(sp) and sp[i].isspace():
                i += 1
            if i < len(sp) and sp[i] == "{":
                i = _skip_group(sp, i)
            continue
        if ch.isalpha():
            n += 1
            i += 1
            while i < len(sp) and sp[i].isspace():
                i += 1
            if i < len(sp) and sp[i] == "{":
                i = _skip_group(sp, i)
            continue
        i += 1
    return n or None


MULTICOL_RE = re.compile(r"\\multicolumn\s*\{(\d+)\}")
MULTIROW_RE = re.compile(r"\\multirow\s*\{(\d+)\}")
CELL_SPLIT_RE = re.compile(r"(?<!\\)&")


def count_cells(row):
    """数一行的真实列数：**未被转义的** `&` 数 + 1，再把 `\\multicolumn{n}` 补成 n 列。

    必须跳过 `\\&`（正文里的字面 &，如 "LTR \\& No NSP"），否则每行都会多算一格。
    """
    n = len(CELL_SPLIT_RE.split(row))
    for m in MULTICOL_RE.finditer(row):
        n += max(0, int(m.group(1)) - 1)
    return n


def tables(src):
    clean = strip_comments(src)
    out = []
    for m in TABULAR_RE.finditer(clean):
        env, spec = m.group(1), (m.group(2) or "")
        end_pat = re.compile(r"\\end\s*\{%s\}" % re.escape(env))
        e = end_pat.search(clean, m.end())
        body = clean[m.end(): e.start()] if e else ""
        rows = [r for r in re.split(r"\\\\", body) if r.strip() and "\\hline" not in r or r.strip().strip("\\hline").strip()]
        ncols = count_columns(spec)
        out.append({
            "env": env, "spec": spec, "ncols": ncols,
            "line": line_of_index(clean, m.start())[0],
            "rows": len([r for r in rows if "&" in r or r.strip()]),
            "has_hlines": "\\hline" in body or "\\toprule" in body,
            "has_caption": "\\caption" in body,
            "has_label": "\\label" in body,
            "body_head": norm(body)[:200],
            # 把本表**自己的**正文范围带出去：调用方若重新 search 整个文件，
            # 会拿到同文件里第一张表的正文，拿错误的行去对错误的列数。
            "body_start": m.end(), "body_end": (e.start() if e else m.end()),
            "body": body,
        })
    return out


def _unit_alt():
    return (r"%|°C|°|℃|K|h|min|s|ms|us|ns|nm|um|µm|mm|cm|km|mg|g|kg|ng|pL|nL|uL|µL|mL|L"
            r"|mol|mM|nM|uM|µM|eV|keV|MeV|GeV|V|kV|mV|mA|µA|uA|A|W|kW|mW|J|kJ|mJ|Pa|kPa|GPa|MPa"
            r"|bar|mbar|Hz|kHz|MHz|GHz|rpm|Da|kDa|ppm|ppb|wt%|vol%|at%|mol%|sccm|Torr|psi|fold|years|yr|days")


NUM_RE = re.compile(
    r"(?P<val>[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d{1,3}|\s*[×x]\s*10\s*\^?\s*[-+]?\d+)?)"
    r"(?:\s*(?P<unit>" + _unit_alt() + r"))?"
)


def numbers(text):
    return [m.group(0).strip() for m in NUM_RE.finditer(strip_comments(text or ""))]


CITATION_TOKEN_RE = re.compile(r"\\(?:cite|citep|citet|parencite|textcite|autocite)\s*(?:\[[^\]]*\]){0,2}\s*\{[^}]+\}")
CROSSREF_TOKEN_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|nameref)\s*\{[^}]+\}")
LABEL_TOKEN_RE = re.compile(r"\\label\s*\{[^}]+\}")
URL_TOKEN_RE = re.compile(r"\\url\s*\{[^}]+\}|https?://\S+")
DOI_TOKEN_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
FORMULA_TOKEN_RE = re.compile(r"\$\$[^$]+\$\$|\$[^$]+\$|\\\[[^\]]+\\\]|\\\([^)]+\\\)", re.S)

PROTECTED_KINDS = ("number", "citation", "crossref", "label", "url", "doi", "formula")


def protected_spans(text):
    """抽取不可变成分，返回 {kind: [字符串...]}（保序去重）。"""
    src = strip_comments(text or "")
    bags = {}

    def add(kind, val):
        val = (val or "").strip()
        if not val:
            return
        bags.setdefault(kind, [])
        if val not in bags[kind]:
            bags[kind].append(val)

    for m in FORMULA_TOKEN_RE.finditer(src):
        add("formula", m.group(0))
    masked = FORMULA_TOKEN_RE.sub(lambda m: " " * len(m.group(0)), src)
    for m in NUM_RE.finditer(masked):
        add("number", m.group(0).strip())
    for m in CITATION_TOKEN_RE.finditer(masked):
        add("citation", m.group(0))
    for m in CROSSREF_TOKEN_RE.finditer(masked):
        add("crossref", m.group(0))
    for m in LABEL_TOKEN_RE.finditer(masked):
        add("label", m.group(0))
    for m in URL_TOKEN_RE.finditer(masked):
        add("url", m.group(0))
    for m in DOI_TOKEN_RE.finditer(masked):
        add("doi", m.group(0))
    return bags


def tokens_multiset(text):
    """不可变成分的多重集（去空白后），用于守恒比对。"""
    bags = protected_spans(text)
    out = {}
    for kind, vals in bags.items():
        for v in vals:
            key = "%s:%s" % (kind, flat(v))
            out[key] = out.get(key, 0) + 1
    return out


# --------------------------------------------------------------------------
# 四、BibTeX
# --------------------------------------------------------------------------

BIB_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s}]+)\s*,", re.I)
BBL_ITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^}]+)\}")
THEBIB_RE = re.compile(r"\\begin\s*\{thebibliography\}(?:\[[^\]]*\])?(.*?)\\end\s*\{thebibliography\}", re.S)


def bbl_entries(text, source=""):
    """解析 `.bbl`（bibtex 的产物）或正文里的 `thebibliography` 环境，返回 [{key, type, fields, line}]。

    arXiv 的源码包常常**只带 `.bbl` 不带 `.bib`**（Attention 更是直接手写 thebibliography）。
    只认 `.bib` 会把这类论文的全部引用判成"文献库里找不到"，全是假 high。
    """
    src = strip_comments(text or "")
    out = []
    seen = set()

    def add(key, line, raw):
        key = (key or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        fields = {}
        ym = re.search(r"\(?(\d{4})[a-z]?\)?", raw or "")
        if ym:
            fields["year"] = ym.group(1)
        out.append({"key": key, "type": "bblitem", "fields": fields, "line": line,
                    "source": source, "raw": norm(raw or "")[:300]})

    for m in THEBIB_RE.finditer(src):
        base = line_of_index(src, m.start())[0]
        body = m.group(1)
        for bm in BBL_ITEM_RE.finditer(body):
            ln = base + (line_of_index(body, bm.start())[0] or 1) - 1
            nxt = BBL_ITEM_RE.search(body, bm.end())
            add(bm.group(1), ln, body[bm.end(): nxt.start() if nxt else len(body)])
    for bm in BBL_ITEM_RE.finditer(src):
        ln = line_of_index(src, bm.start())[0]
        nxt = BBL_ITEM_RE.search(src, bm.end())
        add(bm.group(1), ln, src[bm.end(): nxt.start() if nxt else len(src)])
    return out


def bib_entries(text):
    """解析 .bib，返回 [{key, type, fields{...}, line}]。"""
    src = text or ""
    out = []
    for m in BIB_ENTRY_RE.finditer(src):
        etype, key = m.group(1).lower(), m.group(2).strip()
        if etype in ("comment", "preamble", "string"):
            continue
        depth = 1
        i = m.end()
        while i < len(src) and depth > 0:
            ch = src[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = src[m.end(): max(m.end(), i - 1)]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|[^,\n]+)", body):
            name = fm.group(1).lower()
            val = fm.group(2).strip()
            if val.startswith("{") and val.endswith("}"):
                val = val[1:-1]
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            fields[name] = norm(val)
        out.append({"key": key, "type": etype, "fields": fields, "line": line_of_index(src, m.start())[0]})
    return out


def bib_keys(text):
    return [e["key"] for e in bib_entries(text)]


# --------------------------------------------------------------------------
# 五、工具链与编译
# --------------------------------------------------------------------------

ENGINES = ("pdflatex", "xelatex", "lualatex", "latex", "tectonic")
BIB_TOOLS = ("bibtex", "biber")

_ENGINE_HINT_DIRS = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "MiKTeX", "miktex", "bin", "x64"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "MiKTeX 2.9", "miktex", "bin", "x64"),
    os.path.join(os.environ.get("APPDATA", ""), "TinyTeX", "bin", "windows"),
    os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Programs", "MiKTeX", "miktex", "bin", "x64"),
    r"C:\texlive\2024\bin\windows",
    r"C:\texlive\2023\bin\windows",
    r"D:\下载\MiKTeX\miktex\bin\x64",
    "/usr/bin",
    "/usr/local/bin",
    "/opt/texlive/2024/bin/x86_64-linux",
)


def env_bin_dirs():
    """从环境变量收集额外可执行目录：`TEX_BIN_DIRS` / `MIKTEX_BIN_DIRS` / `TEXLIVE_BIN_DIRS`。

    分隔符用 `os.pathsep`（Windows 是 `;`、POSIX 是 `:`）——**绝不能用 `[;:]` 去切 Windows 路径**，
    否则 `D:\\下载\\MiKTeX\\...` 会被从盘符处切开，变成一个"无盘符的相对路径"，
    在 Windows 上还能 `isdir()` 通过（相对当前盘），最后执行的是错的引擎路径。
    """
    out = []
    for name in ("TEX_BIN_DIRS", "MIKTEX_BIN_DIRS", "TEXLIVE_BIN_DIRS"):
        raw = os.environ.get(name) or ""
        seps = os.pathsep if os.pathsep in raw else ("\n" if "\n" in raw else None)
        parts = raw.split(seps) if seps else [raw]
        for part in parts:
            part = part.strip().strip('"')
            if part and os.path.isdir(part):
                out.append(part)
    return out


def which(name, extra_dirs=None):
    p = shutil.which(name)
    if p:
        return p
    for d in list(extra_dirs or []) + env_bin_dirs() + list(_ENGINE_HINT_DIRS):
        if not d:
            continue
        for cand in (os.path.join(d, name), os.path.join(d, name + ".exe"), os.path.join(d, name + ".cmd")):
            if os.path.exists(cand):
                return cand
    return None


def _run(cmd, cwd=None, timeout=180, env=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, env=env)
        out = p.stdout.decode("utf-8", "replace")
        return {"cmd": cmd, "rc": p.returncode, "out": out, "seconds": round(time.time() - t0, 2),
                "timeout": False}
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace")
        return {"cmd": cmd, "rc": None, "out": out, "seconds": round(time.time() - t0, 2), "timeout": True}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": cmd, "rc": None, "out": "", "error": "%s: %s" % (type(exc).__name__, exc),
                "seconds": round(time.time() - t0, 2), "timeout": False}


def detect_toolchain(extra_dirs=None):
    """探测本机 TeX 工具链，返回 {engines{name:path}, bib_tools{...}, perl, latexmk, available}。"""
    dirs = list(extra_dirs or []) + env_bin_dirs()
    engines = {}
    for e in ENGINES:
        p = which(e, dirs)
        if p:
            engines[e] = p
    bib_tools = {}
    for b in BIB_TOOLS:
        p = which(b, dirs)
        if p:
            bib_tools[b] = p
    info = {
        "engines": engines,
        "bib_tools": bib_tools,
        "perl": which("perl", dirs),
        "latexmk": which("latexmk", dirs),
        "kpathsea": which("kpsewhich", dirs),
        "available": bool(engines),
        "extra_dirs": [d for d in dirs if d],
    }
    if engines:
        first = list(engines.items())[0]
        r = _run([first[1], "--version"], timeout=30)
        info["version_output"] = (r.get("out") or "").strip().split("\n")[0][:200]
    return info


# ---- 日志解析 -------------------------------------------------------------

LOG_ERROR_PATTERNS = [
    (re.compile(r"^!\s*LaTeX Error:\s*(?P<msg>.+)$", re.M), "latex_error"),
    (re.compile(r"^!\s*Package\s+(?P<pkg>[\w\-\.]+)\s+Error:\s*(?P<msg>.+)$", re.M), "package_error"),
    (re.compile(r"^!\s*Class\s+(?P<pkg>[\w\-\.]+)\s+Error:\s*(?P<msg>.+)$", re.M), "class_error"),
    (re.compile(r"^!\s*Undefined control sequence\.?$", re.M), "undefined_control_sequence"),
    (re.compile(r"^!\s*Missing \\?\$? ?inserted\.?$", re.M), "math_mode_error"),
    (re.compile(r"^!\s*Extra \}", re.M), "extra_brace"),
    (re.compile(r"^!\s*Missing \}", re.M), "missing_brace"),
    (re.compile(r"^!\s*Emergency stop", re.M), "emergency_stop"),
    (re.compile(r"^!\s*==>\s*Fatal error occurred", re.M), "fatal_error"),
    (re.compile(r"^!\s*I can't find file `(?P<f>[^']+)'", re.M), "missing_file"),
    (re.compile(r"^!\s*File `(?P<f>[^']+)' not found", re.M), "missing_file"),
    (re.compile(r"^!\s*Font\s.*?not loadable", re.M), "font_error"),
    (re.compile(r"\\begin\{(?P<a>[^}]+)\} ended by \\end\{(?P<b>[^}]+)\}", re.M), "env_mismatch"),
    (re.compile(r"^!\s*LaTeX Warning: There were undefined references", re.M), "undefined_references"),
]
LOG_FILELINE_RE = re.compile(r"^(?P<file>[^\s:][^:]*\.(?:tex|sty|cls|def|ltx|bib)):(?P<line>\d+):\s*(?P<msg>.+)$")
LOG_LNUM_RE = re.compile(r"^l\.(?P<line>\d+)\s*(?P<ctx>.*)$", re.M)
LOG_CTX_FILE_RE = re.compile(r"^\((?P<file>[^()\s]+\.(?:tex|sty|cls|def|ltx))", re.M)
LOG_WARN_REFS = re.compile(r"LaTeX Warning: Reference `(?P<key>[^']+)' on page .* undefined", re.M)
LOG_WARN_CITES = re.compile(r"LaTeX Warning: Citation `(?P<key>[^']+)'.* undefined", re.M)
LOG_WARN_RERUN = re.compile(r"Rerun to get (?:cross-references|outline|labels) right", re.I)
LOG_WARN_BIBCITE = re.compile(r"Please \(re\)run (Biber|BibTeX)", re.I)
LOG_WARN_OVERFULL = re.compile(r"Overfull \\hbox \((?P<pts>[\d.]+)pt too wide\) in paragraph at lines (?P<a>\d+)--(?P<b>\d+)")
LOG_WARN_UNDERFULL = re.compile(r"Underfull \\hbox")
LOG_WARN_BOX = re.compile(r"(?:Overfull|Underfull) \\[hv]box")

MISSING_PKG_RE = re.compile(r"File `(?P<f>[\w\-\.]+\.sty)' not found")
MISSING_CLS_RE = re.compile(r"File `(?P<f>[\w\-\.]+\.cls)' not found")
MISSING_BST_RE = re.compile(r"File `(?P<f>[\w\-\.]+\.bst)' not found")
GENERIC_MISSING_FILE_RE = re.compile(r"File `(?P<f>[^']+)' not found")
ENCODING_HINT_RE = re.compile(r"Unicode character .* not set up", re.I)

# 日志里的文件嵌套：TeX 用 (file.tex ... ) 表示"正在读"，右括号表示读完。
_FILE_OPEN_RE = re.compile(
    r"\((?:\"|')?([^()\s\"']+\.(?:tex|sty|cls|def|ltx|cfg|fd|bib|bbl|aux|toc|out|clo|ldf))"
)


def track_file_events(text):
    """解析日志的括号嵌套，返回按位置排序的事件列表 [(pos, file_or_None, is_push)]。"""
    events = []
    stack = []
    i = 0
    n = len(text or "")
    while i < n:
        ch = text[i]
        if ch == "(":
            m = _FILE_OPEN_RE.match(text, i)
            if m:
                stack.append(m.group(1))
                events.append((i, m.group(1), True))
                i = m.end()
                continue
            stack.append(None)
            events.append((i, None, True))
        elif ch == ")":
            if stack:
                stack.pop()
                events.append((i, None, False))
        i += 1
    return events


def _file_at(events, pos, prefer_tex=True, default=None):
    """求日志某位置处"当前正在读的文件"：优先最内层的 .tex，否则最内层文件。"""
    stack = []
    for p, f, is_push in events:
        if p >= pos:
            break
        if is_push:
            stack.append(f)
        elif stack:
            stack.pop()
    for f in reversed(stack):
        if f and f.lower().endswith(".tex"):
            return f
    for f in reversed(stack):
        if f:
            return f
    return default


def parse_log(log_text, default_file=None):
    """解析 LaTeX 日志，返回 {errors:[...], warnings:{refs[], cites[], rerun, bib, overfull[]}, summary{}}。

    每条错误尽量定位到 **文件:行号**：文件来自日志的括号嵌套栈（最内层 .tex），
    行号来自 `l.NN` 上下文；若日志用 -file-line-error，则直接采用 `file:line:` 形态。
    """
    text = log_text or ""
    errors = []
    events = track_file_events(text)
    lines = text.split("\n")

    for pat, kind in LOG_ERROR_PATTERNS:
        for m in pat.finditer(text):
            ln, _ = line_of_index(text, m.start())
            entry = {"kind": kind, "log_line": ln, "raw": m.group(0).strip()[:300]}
            gd = m.groupdict() if m.groupdict() else {}
            if gd.get("msg"):
                entry["message"] = norm(gd["msg"])[:300]
            if gd.get("pkg"):
                entry["package"] = gd["pkg"]
            if gd.get("f"):
                entry["missing"] = gd["f"]
            # 找 l.NN 上下文（若中间插入另一条 ! 错误，说明本条没有独立行号）
            lm = _next_lnum_after(text, m.end())
            if lm:
                entry["line"] = int(lm.group("line"))
                entry["context"] = norm(lm.group("ctx"))[:200]
            f = _file_at(events, m.start(), default=default_file)
            if f:
                entry["file"] = f
            errors.append(entry)

    # 「File `x' not found」多数只有一次 LaTeX Error 行，错误行本身要带上缺失文件名。
    # 注意：一次缺失文件通常会同时触发 `! LaTeX Error: File ... not found` 与 `! Emergency stop.`，
    # 这两条是**同一个根因**，合并成一条（保留更具体的 LaTeX Error）。
    missing_any = GENERIC_MISSING_FILE_RE.search(text)
    if missing_any:
        for e in errors:
            if e["kind"] in ("latex_error", "emergency_stop") and "missing" not in e:
                e["missing"] = missing_any.group("f")

    # 文件:行号 形态（-file-line-error）
    for m in LOG_FILELINE_RE.finditer(text):
        errors.append({"kind": "fileline", "file": m.group("file"), "line": int(m.group("line")),
                       "message": norm(m.group("msg"))[:300], "raw": m.group(0)[:300]})

    # 同一行被两个 kind 命中（env_mismatch 与 latex_error）时保留更具体的 env_mismatch，
    # 但不丢弃任何独立根因；插入型连锁错误保留并标注 cascade。
    errors = _merge_related_errors(errors)
    errors = _drop_chained_inserts(errors)

    refs = [m.group("key") for m in LOG_WARN_REFS.finditer(text)]
    cites = [m.group("key") for m in LOG_WARN_CITES.finditer(text)]
    overfull = [{"pts": float(m.group("pts")), "lines": [int(m.group("a")), int(m.group("b"))]}
                for m in LOG_WARN_OVERFULL.finditer(text)]
    warnings = {
        "undefined_refs": sorted(set(refs)),
        "undefined_cites": sorted(set(cites)),
        "rerun": bool(LOG_WARN_RERUN.search(text)),
        "bib_rerun": bool(LOG_WARN_BIBCITE.search(text)),
        "overfull": overfull,
        "underfull": len(LOG_WARN_UNDERFULL.findall(text)),
    }
    summary = {
        "log_lines": len(lines),
        "errors": len(errors),
        "undefined_refs": len(warnings["undefined_refs"]),
        "undefined_cites": len(warnings["undefined_cites"]),
        "pages": None,
        "output_pdf": None,
    }
    m = re.search(r"Output written on .*?\((?P<pages>\d+) pages?,\s*(?P<bytes>\d+) bytes\)", text)
    if m:
        summary["pages"] = int(m.group("pages"))
        summary["output_pdf"] = int(m.group("bytes"))
    return {"errors": errors, "warnings": warnings, "summary": summary}


ERROR_CATEGORIES = (
    "missing_package", "missing_class", "missing_bst", "missing_file", "wrong_engine",
    "math_syntax", "brace_error", "env_mismatch", "citation", "reference",
    "font_error", "encoding", "template_requirement", "unknown",
)


ERR_MARK_RE = re.compile(r"^!", re.M)
CHAIN_MARK_RE = re.compile(r"^!\s*(?:Emergency stop|==>\s*Fatal error occurred)", re.M)


def _next_lnum_after(text, pos, window=400):
    """取紧随本条错误之后的 `l.NN`。

    中间若夹着**另一条真正的错误**（`!` 开头的行）则本条没有独立行号；
    但 `! Emergency stop.` / `!  ==> Fatal error occurred` 是同一根因的连锁标记，
    不阻断行号归属（缺宏包时 TeX 往往在这两行之后才打印 `l.NN`）。
    """
    seg = text[pos:pos + window]
    m = LOG_LNUM_RE.search(seg)
    if not m:
        return None
    head = CHAIN_MARK_RE.sub("", seg[: m.start()])
    if ERR_MARK_RE.search(head):
        return None
    return m


def _merge_related_errors(errors):
    """把同一根因的多条错误合并。

    - 缺文件引发的 `! Emergency stop.` 并入前一条带 missing 的错误（同文件、中间无其它错误）；
    - 同一行被两个不同 kind 命中（如 `\\begin{} ended by \\end{}`）只保留更具体的那个。
    """
    ordered = sorted(errors, key=lambda e: e.get("log_line") or 0)
    keep = []
    for e in ordered:
        if e.get("kind") == "emergency_stop":
            prev = keep[-1] if keep else None
            if prev is not None and (prev.get("missing") or prev.get("kind") == "missing_file"):
                prev.setdefault("merged", [])
                prev["merged"].append("emergency_stop")
                continue
        if keep:
            prev = keep[-1]
            same_line = (prev.get("log_line") or 0) == (e.get("log_line") or 0)
            merged_lines = abs((prev.get("log_line") or 0) - (e.get("log_line") or 0)) <= 2
            spec_rank = {"env_mismatch": 4, "missing_file": 3, "package_error": 2, "class_error": 2,
                         "latex_error": 1, "undefined_control_sequence": 1}
            if same_line and prev.get("file") == e.get("file"):
                if spec_rank.get(e.get("kind"), 0) > spec_rank.get(prev.get("kind"), 0):
                    prev.setdefault("merged", [])
                    prev["merged"].append(e.get("kind"))
                    keep[-1] = e
                    continue
                prev.setdefault("merged", [])
                prev["merged"].append(e.get("kind"))
                continue
            # `! LaTeX Error: File ... not found` 之后紧跟的 Undefined control sequence 是同一根因
            if (merged_lines and prev.get("missing") and e.get("kind") == "undefined_control_sequence"
                    and prev.get("file") == e.get("file") and not e.get("line")):
                prev.setdefault("merged", [])
                prev["merged"].append("undefined_control_sequence")
                continue
        keep.append(e)
    return keep


def _drop_chained_inserts(errors):
    """TeX 的 `<inserted text>` 会连报多条同类错误（Missing $ → Missing }）。

    **不隐藏任何一条报错**：只给同一根因链条上的后续条目打上 `cascade_of`（根因条目的 log_line）
    与 `cascade: True`，便于报告里说明"哪条是根因、哪些是它引发的连锁"。
    """
    insert_kinds = ("math_mode_error", "missing_brace", "extra_brace")
    seen_roots = {}
    for e in errors:
        if e.get("kind") in insert_kinds:
            key = e.get("file")
            root = seen_roots.get(key)
            if root is not None and abs((root.get("log_line") or 0) - (e.get("log_line") or 0)) <= 8:
                e["cascade"] = True
                e["cascade_of"] = root.get("log_line")
                root.setdefault("cascade_count", 0)
                root["cascade_count"] = (root.get("cascade_count") or 0) + 1
            else:
                seen_roots[key] = e
    return errors


def classify_error(entry, log_text=None):
    """给一条日志错误分类，附 hint 与常见修法。返回 {category, hint, fix}。"""
    kind = entry.get("kind")
    msg = (entry.get("message") or entry.get("raw") or "").lower()
    log_text = log_text or ""
    if kind in ("missing_file",) or entry.get("missing"):
        blob = entry.get("missing") or ""
        target = blob or (GENERIC_MISSING_FILE_RE.search(log_text).group("f") if GENERIC_MISSING_FILE_RE.search(log_text) else "")
        if target.lower().endswith(".sty"):
            return {"category": "missing_package", "hint": "缺少宏包 %s" % target,
                    "fix": "在导言区 \\usepackage{...}；若平台未预装该宏包，改用等价宏包或去掉依赖"}
        if target.lower().endswith(".cls"):
            return {"category": "missing_class", "hint": "缺少模板类 %s" % target,
                    "fix": "确认模板文件是否随工程提供；缺失时把 .cls 放进工程根目录或改用可用模板"}
        if target.lower().endswith(".bst"):
            return {"category": "missing_bst", "hint": "缺少参考文献样式 %s" % target,
                    "fix": "换用发行的 .bst，或用 \\bibliographystyle{plain} 等通用样式"}
        if target:
            return {"category": "missing_file", "hint": "缺少文件：%s" % target,
                    "fix": "检查 \\input/\\include/\\includegraphics 的路径与文件名大小写"}
        return {"category": "missing_file", "hint": "缺少文件（日志未指明名字）",
                "fix": "用 -file-line-error 重跑，或看日志里 Enter file name 附近"}
    if kind == "undefined_control_sequence":
        return {"category": "missing_package", "hint": "未定义的控制序列（多半是缺宏包或拼错命令）",
                "fix": "看 logs 里 l.NN 那行用的命令属于哪个宏包，补 \\usepackage 或改拼写"}
    if kind in ("package_error", "class_error"):
        return {"category": "template_requirement", "hint": "宏包/类报错：%s" % (entry.get("message") or ""),
                "fix": "按宏包说明补必需选项；注意选项顺序与 hyperref 加载位置"}
    if kind in ("extra_brace", "missing_brace"):
        return {"category": "brace_error", "hint": "花括号不配对", "fix": "按 l.NN 定位，补齐或删除多余的 {}"}
    if kind == "math_mode_error":
        return {"category": "math_syntax", "hint": "数学模式/符号书写有误",
                "fix": "检查 $ 配对、上下标 {}、以及 & 是否只在表格/对齐环境里"}
    if kind == "env_mismatch":
        return {"category": "env_mismatch",
                "hint": "环境配对错误：\\begin{%s} 被 \\end{%s} 关闭" % (entry.get("a"), entry.get("b")),
                "fix": "补齐缺失的 \\end{%s}，或把关闭环境改成 %s" % (entry.get("a"), entry.get("a"))}
    if kind == "missing_brace":
        return {"category": "brace_error", "hint": "缺少 }（常由数学模式错误连锁触发）",
                "fix": "先修上游的 $ / {} 错误，再重新编译"}
    if kind == "extra_brace":
        return {"category": "brace_error", "hint": "多余的 }", "fix": "按 l.NN 找到并删除多余的括号"}
    if kind == "font_error":
        return {"category": "font_error", "hint": "字体不可用", "fix": "改用可用的字体包（如去掉 fontspec 或换 XeLaTeX/pdfLaTeX 引擎）"}
    if ENCODING_HINT_RE.search(msg):
        return {"category": "encoding", "hint": "字符未设置（编码/引擎问题）",
                "fix": "文件存为 UTF-8，或用 XeLaTeX + fontspec 处理非 ASCII 字符"}
    if kind in ("emergency_stop", "fatal_error"):
        return {"category": "unknown", "hint": "编译致命中止", "fix": "先解决同次日志中更早的第一条错误"}
    if kind == "undefined_references":
        return {"category": "reference", "hint": "存在未定义引用", "fix": "补 \\label 或再编译一轮"}
    if kind == "latex_error":
        return {"category": "unknown", "hint": entry.get("message") or "LaTeX 错误", "fix": "按 l.NN 上下文定位"}
    return {"category": "unknown", "hint": (entry.get("message") or entry.get("raw") or "")[:200], "fix": "人工核对日志"}


def classify_errors(parsed, log_text=None):
    out = []
    for e in parsed.get("errors") or []:
        c = classify_error(e, log_text)
        merged = dict(e)
        merged.update(c)
        out.append(merged)
    return out


def needs_rerun(parsed):
    w = parsed.get("warnings") or {}
    return bool(w.get("rerun") or w.get("undefined_refs") or w.get("undefined_cites"))


def engine_hint(engine):
    """按引擎名给出推荐用途与典型命令。"""
    e = (engine or "").lower()
    if e.startswith("xelatex"):
        return {"flags": ["-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "-no-shell-escape"],
                "note": "Unicode/字体支持好，适合中文与 fontspec", "bib": "biber"}
    if e.startswith("lualatex"):
        return {"flags": ["-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "-no-shell-escape"],
                "note": "Unicode 好、纯 Lua 实现，兼容性略窄", "bib": "biber"}
    if e.startswith("tectonic"):
        return {"flags": ["--keep-logs", "--halt-on-error"], "note": "自动多轮与按需下载，需联网", "bib": "auto"}
    return {"flags": ["-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "-no-shell-escape"],
            "note": "标准 pdfLaTeX，宏包生态最广", "bib": "bibtex"}


def build_command(engine_path, main_file, outdir=None, flags=None, engine_name=None):
    cmd = [engine_path]
    cmd += flags or engine_hint(engine_name or os.path.basename(engine_path)).get("flags", [])
    if outdir:
        cmd += ["-output-directory", outdir]
    cmd += [main_file]
    return cmd


def pick_engine(toolchain, engine=None, src=""):
    """决定用哪个引擎：显式指定 > 源码 magic > 有 fontspec/xeCJK 或中文 → xelatex > pdflatex。"""
    engines = (toolchain or {}).get("engines") or {}
    if engine and engine in engines:
        return engine
    magic = magic_engine(src or "")
    if magic and magic in engines:
        return magic
    if re.search(r"[\u4e00-\u9fff]", src or "") or re.search(r"\\usepackage(\[[^\]]*\])?\{(fontspec|xeCJK)\}", src or ""):
        for cand in ("xelatex", "lualatex", "pdflatex"):
            if cand in engines:
                return cand
    for cand in ("pdflatex", "xelatex", "lualatex", "latex", "tectonic"):
        if cand in engines:
            return cand
    return next(iter(engines), None)


def pick_bib_tool(toolchain, src="", prefer=None):
    """按文献指令选工具：\\addbibresource/\\printbibliography → biber；\\bibliography → bibtex。"""
    tools = (toolchain or {}).get("bib_tools") or {}
    if prefer and prefer in tools:
        return prefer
    if re.search(r"\\(addbibresource|printbibliography)", src or ""):
        for cand in ("biber", "bibtex"):
            if cand in tools:
                return cand
    for cand in ("bibtex", "biber"):
        if cand in tools:
            return cand
    return None


def compile_project(project_dir, main_file, engine=None, outdir=None, bib_tool=None,
                    max_passes=4, timeout=180, env=None, keep_log=True):
    """多轮编译：engine → (bibtex/biber) → engine …，直到引用收敛或达上限。

    返回 {status, engine, passes:[{n, kind, cmd, rc, seconds, log_excerpt}], errors, warnings,
          artifacts{...}, log_text, toolchain}。status ∈ ok / failed / not_attempted。
    """
    tc = detect_toolchain()
    src_text = _safe_read(os.path.join(project_dir, main_file))
    eng = pick_engine(tc, engine, src_text)
    report = {"status": "not_attempted", "engine": eng, "passes": [], "errors": [], "warnings": {},
              "artifacts": {}, "log_text": "", "toolchain": {"available": tc["available"],
                                                             "engines": sorted(tc["engines"].keys()),
                                                             "bib_tools": sorted(tc["bib_tools"].keys())}}
    if not tc["available"]:
        report["reason"] = "no_tex_engine"
        report["hint"] = "本机未找到 TeX 引擎（pdflatex/xelatex/lualatex/tectonic），未执行编译"
        return report
    eng_path = tc["engines"].get(eng) or list(tc["engines"].values())[0]
    outdir = outdir or project_dir
    os.makedirs(outdir, exist_ok=True)
    job = os.path.splitext(os.path.basename(main_file))[0]
    # arXiv 惯例：工程里常自带预编译完成的 `<job>.bbl`（作者不想让评审跑 bibtex）。
    # 有它就该直接用，不必（也常常无法）跑 bibtex —— 缺 .bib 数据源时 bibtex 只会失败。
    bbl_ready = False
    for cand in (os.path.join(outdir, job + ".bbl"), os.path.join(project_dir, job + ".bbl")):
        if os.path.exists(cand):
            if os.path.abspath(cand) != os.path.abspath(os.path.join(outdir, job + ".bbl")):
                try:
                    _copy_bin(cand, os.path.join(outdir, job + ".bbl"))
                except Exception:  # noqa: BLE001
                    continue
            bbl_ready = True
            break
    merged_log = []
    passes = 0
    last = None
    bib_done = False
    while passes < max_passes:
        passes += 1
        cmd = build_command(eng_path, main_file, outdir=outdir, engine_name=eng)
        r = _run(cmd, cwd=project_dir, timeout=timeout, env=env)
        merged_log.append("=== pass %d engine %s (rc=%s) ===\n%s" % (passes, eng, r.get("rc"), r.get("out") or ""))
        last = r
        parsed = parse_log(r.get("out") or "", default_file=main_file)
        report["errors"] = classify_errors(parsed, r.get("out") or "")
        report["warnings"] = parsed.get("warnings") or {}
        report["passes"].append({"n": passes, "kind": "engine", "cmd": cmd, "rc": r.get("rc"),
                                 "timeout": bool(r.get("timeout")),
                                 "seconds": r.get("seconds"), "errors": len(report["errors"]),
                                 "log_excerpt": (r.get("out") or "")[-1500:]})
        if r.get("timeout"):
            report["reason"] = "engine_timeout"
            report["hint"] = ("引擎在 %ss 内没有返回；首次使用 MiKTeX 常因按需安装宏包而变慢，"
                              "可先跑一次预热，或把 timeout 调大。" % timeout)
            break
        if r.get("rc") not in (0,) and report["errors"]:
            break
        # 需要跑 bib？—— bibtex/biber 都要在 .aux 所在目录（outdir）跑；
        # bibtex 还要靠 BIBINPUTS 才找得到工程目录里的 .bib。
        aux = os.path.join(outdir, job + ".aux")
        # 只有 aux 里真的出现 `\bibdata{...}`（= 用了 \bibliography 且给了数据库）才需要跑 bibtex。
        # 只出现 `\citation{...}` 的场景多半是手写 `\begin{thebibliography}`（很多 arXiv 论文这样），
        # 此时跑 bibtex 只会产出空 .bbl 并记一次失败，毫无必要。
        aux_txt = _safe_read(aux) or ""
        has_bibdata = bool(re.search(r"\\bibdata\{[^}]*\S[^}]*\}", aux_txt))
        want_bib = (not bbl_ready) and has_bibdata
        if want_bib and not bib_done:
            tool = pick_bib_tool(tc, src_text, prefer=bib_tool)
            # pick_bib_tool 返回的是“名字”（bibtex/biber），这里必须换成**绝对路径**，
            # 否则 subprocess 用该名字去 PATH 找 → WinError 2（子进程继承不到我们探测出的目录）。
            tool_path = tc["bib_tools"].get(tool) if tool else None
            base = os.path.splitext(os.path.basename(main_file))[0]
            if tool_path:
                denv = dict(env or os.environ)
                denv["BIBINPUTS"] = os.pathsep.join([project_dir, outdir, denv.get("BIBINPUTS", "")]).strip(os.pathsep)
                denv["BSTINPUTS"] = os.pathsep.join([project_dir, outdir, denv.get("BSTINPUTS", "")]).strip(os.pathsep)
                br = _run([tool_path, base], cwd=outdir, timeout=timeout, env=denv)
                bout = br.get("out") or ""
                failed_markers = ("I couldn't open", "I found no \\bibdata", "I found no \\bibstyle",
                                  "I found no \\citation", "error message", "Error:", "fatal error")
                br["failed"] = any(m in bout for m in failed_markers)
                merged_log.append("=== bib %s (rc=%s failed=%s) ===\n%s" % (tool, br.get("rc"), br["failed"], bout))
                report["passes"].append({"n": passes, "kind": "bib", "cmd": [tool, base], "rc": br.get("rc"),
                                         "failed": br["failed"], "error": br.get("error"),
                                         "timeout": bool(br.get("timeout")), "seconds": br.get("seconds"),
                                         "log_excerpt": bout[-800:]})
                bib_done = True
        if not needs_rerun(parsed):
            break
    txt = "\n".join(merged_log)
    report["log_text"] = txt
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(main_file))[0] + ".pdf")
    logfile = os.path.join(outdir, os.path.splitext(os.path.basename(main_file))[0] + ".log")
    report["artifacts"] = {
        "pdf": pdf if os.path.exists(pdf) else None,
        "pdf_bytes": os.path.getsize(pdf) if os.path.exists(pdf) else 0,
        "log": logfile if os.path.exists(logfile) else None,
        "bib_log": (os.path.join(outdir, os.path.splitext(os.path.basename(main_file))[0] + ".blg")
                    if os.path.exists(os.path.join(outdir, os.path.splitext(os.path.basename(main_file))[0] + ".blg")) else None),
    }
    if report["artifacts"]["pdf"] and not report["errors"]:
        report["status"] = "ok"
    else:
        report["status"] = "failed"
    return report


def _copy_bin(src, dst):
    with open(src, "rb") as fh:
        data = fh.read()
    with open(dst, "wb") as fh:
        fh.write(data)
    return len(data)


def _safe_read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def save_log(report, path):
    return dump_text(path, report.get("log_text") or "")


# --------------------------------------------------------------------------
# 六、结果导出
# --------------------------------------------------------------------------

CONTRACT_ALIASES = {
    "main": "main.tex",
    "manuscript": "main.tex",
    "tex": "main.tex",
    "source": "main.tex",
    "revised": "revised.tex",
    "revised_tex": "revised.tex",
    "changes": "changes.jsonl",
    "edits": "changes.jsonl",
    "diagnosis": "diagnosis.json",
    "errors": "diagnosis.json",
    "compile": "compile.json",
    "build": "compile.json",
    "compile_report": "compile.json",
    "log": "compile.log",
    "source_map": "source_map.json",
    "mapping": "source_map.json",
    "checklist": "checklist.json",
    "elements": "checklist.json",
    "check": "check.json",
    "review": "review.md",
    "report": "review.md",
    "diff": "diff.md",
    "patch": "patch.diff",
    "bibliography": "references.bib",
    "bib": "references.bib",
    "tokens": "tokens.json",
}


def emit_result(out_path, case_id, status, primary, evidence=None, uncertainty=None,
                artifacts=None, contract=None, extra_top=None):
    """按契约回填 result.json。缺的契约键填 default 并在 uncertainty 里说明。"""
    doc = {
        "schema": "tex-result/1.0",
        "case_id": case_id,
        "status": status,
        "primary_result": primary or {},
        "evidence": evidence or [],
        "uncertainty": list(uncertainty or []),
        "artifacts": artifacts or [],
        "change_log": primary.get("change_log") if isinstance(primary, dict) else None,
    }
    produced = {os.path.basename(a.get("path", "")) for a in (artifacts or [])}
    unmapped = []
    if isinstance(contract, dict):
        for key, spec in contract.items():
            fname = CONTRACT_ALIASES.get(key, key if re.search(r"\.\w+$", key) else key + ".json")
            for cand in (fname, key, key + ".md", key + ".tex"):
                if cand in produced:
                    if os.path.exists(os.path.join(os.path.dirname(out_path), cand)):
                        doc[key] = cand
                    break
            else:
                default = (spec or {}).get("default") if isinstance(spec, dict) else None
                doc[key] = default
                unmapped.append(key)
    if unmapped:
        doc["uncertainty"].append("output_contract fields not produced: " + ", ".join(sorted(unmapped)))
    if extra_top:
        doc.update(extra_top)
    if isinstance(primary, dict):
        for k, v in primary.items():
            if k not in doc:
                doc[k] = v
    return dump_json(out_path, doc)


def now_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_record(path, role="", media_type=""):
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    mt = media_type or {
        ".md": "text/markdown", ".json": "application/json", ".jsonl": "application/x-ndjson",
        ".tex": "application/x-tex", ".bib": "application/x-bibtex", ".log": "text/plain",
        ".pdf": "application/pdf", ".txt": "text/plain", ".tsv": "text/tab-separated-values",
        ".diff": "text/x-diff",
    }.get(ext, "text/plain")
    return {"path": os.path.basename(path), "role": role, "media_type": mt,
            "bytes": os.path.getsize(path), "sha256": sha256_file(path)}
