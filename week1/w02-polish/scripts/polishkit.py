"""polishkit — shared core for the `academic-polish` skill.

Pure standard library. No network, no external services, no writes outside the
output directory. Every helper is deterministic so that two runs on the same
input produce byte-identical inventories.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile

VERSION = "polishkit/1.0"

# ---------------------------------------------------------------- basic text

_WS = re.compile(r"[ \t\u00a0\u3000]+")
_SOFT_HYPHEN = re.compile(r"[\u00ad\u200b\ufeff]")
_LINE_JOIN = re.compile(r"(?<=[A-Za-z,\-])[ \t]*\n[ \t]*(?=[a-z])")


def norm(s: str) -> str:
    """Collapse runs of spaces, drop soft hyphens/zero-width marks."""
    if not s:
        return ""
    s = _SOFT_HYPHEN.sub("", str(s))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _LINE_JOIN.sub(" ", s)
    s = _WS.sub(" ", s)
    return s.strip()


def norm_hard(s: str) -> str:
    """Aggressive normalisation used for tolerant comparisons."""
    s = norm(s).lower()
    s = re.sub(r"[\s\u2010-\u2015\-_]+", "", s)
    s = re.sub(r"[^\w\u4e00-\u9fff%./]+", "", s)
    return s


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


_SENT = re.compile(r"(?<=[。！？；])|(?<=[.!?;])\s+|(?<=[.!?;])(?=[A-Z\u4e00-\u9fff])")
_ABBREV = ("et al.", "e.g.", "i.e.", "cf.", "vs.", "Fig.", "Eq.", "No.", "approx.",
           "Ref.", "al.", "Dr.", "Prof.", "etc.", "resp.", "Sec.", "Tab.")


def sentences(text: str) -> list:
    """Split into sentences, keeping abbreviations from breaking the split."""
    text = norm(text)
    if not text:
        return []
    guard = "\u0001"
    tmp = text
    for i, a in enumerate(_ABBREV):
        tmp = tmp.replace(a, a.replace(".", guard + str(i % 10) + guard))
    tmp = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + guard + "d" + guard + m.group(2), tmp)
    parts = [p for p in _SENT.split(tmp) if p and p.strip()]
    out = []
    for p in parts:
        p = re.sub(guard + r"\d?" + guard, ".", p)
        p = p.replace(guard + "d" + guard, ".").strip()
        if p:
            out.append(p)
    return out


_TOK = re.compile(r"[A-Za-z][A-Za-z'\-]*|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]")


def tokens(text: str) -> list:
    return _TOK.findall(text or "")


def cjk_ratio(s: str) -> float:
    s = s or ""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    letters = len(re.findall(r"[A-Za-z]", s))
    total = cjk + letters
    return (cjk / total) if total else 0.0


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]{1,40}>", "", s or "")
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')


# ---------------------------------------------------------------- lexicons

HEDGE_EN = ["may", "might", "could", "can", "would", "should", "possibly",
            "perhaps", "likely", "unlikely", "appears", "appear", "seems",
            "seem", "suggests", "suggest", "indicates", "indicate", "tends",
            "tend", "often", "sometimes", "generally", "typically", "usually",
            "relatively", "partially", "approximately", "about", "roughly",
            "preliminary", "potential", "potentially", "tentative", "assumed",
            "hypothesised", "hypothesized", "proposed", "candidate", "putative",
            "broadly", "largely", "mostly", "in part", "to some extent",
            "consistent with", "associated with", "correlates", "correlate",
            "correlated", "implies", "implied", "would appear"]

HEDGE_ZH = ["可能", "或许", "也许", "大概", "似乎", "好像", "倾向于", "往往",
            "通常", "一般", "部分", "初步", "潜在", "大致", "约", "左右",
            "相对", "较为", "在一定程度上", "有望", "推测", "假设", "提示",
            "表明可能", "相关性"]

BOOST_EN = ["demonstrate", "demonstrates", "demonstrated", "prove", "proves",
            "proven", "establish", "establishes", "established", "confirm",
            "confirms", "confirmed", "reveal", "reveals", "revealed", "show",
            "shows", "showed", "clearly", "obviously", "undoubtedly",
            "certainly", "definitely", "always", "never", "all", "none",
            "every", "must", "will", "significantly", "dramatically",
            "substantially", "markedly", "essential", "crucial", "novel",
            "first", "unique", "unprecedented", "best", "optimal", "robust",
            "guarantee", "guarantees", "therefore", "thus", "hence",
            "conclusively", "unambiguously", "strongly"]

BOOST_ZH = ["证明", "证实", "表明", "显示", "揭示", "明确", "显然", "必然",
            "一定", "总是", "从不", "所有", "全部", "每一个", "显著", "大幅",
            "极大地", "至关重要", "关键", "首创", "独一无二", "前所未有",
            "最优", "鲁棒", "确保", "因此", "从而", "结论性地"]

NEG_EN = ["not", "no", "never", "none", "neither", "nor", "cannot", "can't",
          "doesn't", "does not", "did not", "didn't", "is not", "isn't",
          "are not", "aren't", "was not", "wasn't", "were not", "weren't",
          "without", "fail", "fails", "failed", "unable", "unaffected",
          "insensitive", "independent of", "irrespective"]

NEG_ZH = ["不", "未", "无", "非", "没有", "并非", "不能", "无法", "尚未",
          "不具备", "无关", "不受"]

QUANT_EN = ["all", "none", "every", "each", "any", "some", "most", "many",
            "few", "several", "both", "either", "neither", "no", "only",
            "majority", "minority", "always", "never", "sometimes", "often",
            "rarely", "occasionally", "at least", "at most", "up to", "over",
            "more than", "less than", "exactly"]

QUANT_ZH = ["所有", "全部", "每个", "任何", "某些", "大多数", "多数", "少数",
            "几个", "若干", "两者", "仅", "只", "至少", "至多", "不超过",
            "超过", "恰好", "偶尔", "经常", "很少"]

COND_EN = ["if", "when", "unless", "provided that", "provided", "assuming",
           "given", "under", "in the case of", "in case", "where", "whenever",
           "subject to", "depending on", "as long as"]
COND_ZH = ["如果", "若", "假设", "在…条件下", "在...条件下", "条件", "当", "只要",
           "除非", "取决于", "在以下情况"]

CAUSAL_EN = ["because", "because of", "due to", "owing to", "since",
             "as a result", "resulted in", "result in", "resulting in", "results in",
             "leads to", "led to", "causes", "caused by", "caused", "causing",
             "therefore", "thus", "hence", "attributed to", "attributable to",
             "stems from", "stem from", "arises from", "arise from", "give rise to",
             "gives rise to", "as a consequence", "consequently", "so that"]
CORREL_EN = ["correlates with", "correlated with", "correlation",
             "associated with", "association", "accompanied by",
             "coincided with", "linked to", "related to"]

STYLE_PROFILES = {
    "journal-article": {
        "zh": "期刊论文",
        "rules": [
            "第三人称、被动语态与主动语态混合使用，但同一章节内保持一致",
            "过去时叙述已完成的实验；现在时陈述普遍结论与图表内容",
            "避免口语化缩写（don't / isn't）、感叹号与第一人称复数过度使用",
            "限定词强度必须与证据强度匹配，不得把 associated with 升格为 causes",
        ],
    },
    "thesis": {
        "zh": "学位论文",
        "rules": [
            "章节内视角统一，可用第一人称单数，但需与全文一致",
            "概念首次出现给出全称与缩写，后续统一使用缩写",
            "结论部分允许总结性表述，但仍需保留限定条件",
        ],
    },
    "grant-proposal": {
        "zh": "基金申请书",
        "rules": [
            "突出目标、意义与可行性，但不得用宣传化措辞替代数据",
            "避免绝对化断言（首次/最优/前所未有），除非有文献或数据支撑",
            "未来工作计划使用将来时；已有基础使用过去时",
        ],
    },
    "reviewer-response": {
        "zh": "审稿回复",
        "rules": [
            "逐条对应审稿意见，先复述问题再给出改动与位置",
            "语气客观礼貌，避免防御性表述；不同意时给出证据与理由",
            "明确标注哪些改动进入正文、哪些为澄清",
        ],
    },
    "abstract": {
        "zh": "英文摘要",
        "rules": [
            "单段、无引用、无缩写未定义；长度受期刊限制",
            "一般过去时报告结果，现在时陈述结论与意义",
            "限定强度与正文一致，不得在摘要中拔高结论",
        ],
    },
}

EDIT_TYPES = {
    "grammar": "语法错误修正（主谓一致、时态、语态、单复数、冠词、介词）",
    "syntax": "句法结构调整（悬垂修饰、平行结构、长句切分、残缺句）",
    "punctuation": "标点与排版规范（逗号拼接、连字符、破折号、单位与数字间距）",
    "word-choice": "用词与搭配修正（含中式英语、直译腔、冗余名词化）",
    "terminology": "术语统一（同一概念全篇统一写法、缩写首次出现形式）",
    "register": "语气与语域调整（口语化、宣传化、绝对化、人称误用）",
    "hedging": "限定强度调整（仅允许在标注证据后朝收敛方向调整）",
    "clarity": "清晰度提升（指代消解、逻辑连接、信息重心）",
    "consistency": "全篇一致性（时态、拼写变体、大小写、连字符、编号格式）",
    "no-change": "无需修改（保留原文，须给出保留理由）",
}

PROTECTED_KINDS = ("number", "unit", "citation", "crossref", "formula", "url", "doi")

# ---------------------------------------------------------------- extraction

NUM_RE = re.compile(
    r"(?<![\w.])(?P<val>[+-]?\d+(?:[.,]\d+)?(?:\s*[×x]\s*10\s*(?:\^|\*\*)?\s*[+-]?\d+)?)"
    r"(?:\s*(?P<unit>%|°C|C\b|K\b|h\b|hr\b|hrs\b|min\b|mins\b|s\b|ms\b|ns\b|ps\b|fs\b|"
    r"nm\b|µm\b|um\b|mm\b|cm\b|m\b|km\b|mg\b|g\b|kg\b|µg\b|ug\b|mol\b|mmol\b|M\b|mM\b|"
    r"µM\b|nM\b|mL\b|ml\b|L\b|µL\b|uL\b|mol/L\b|g/L\b|mg/mL\b|eV\b|meV\b|keV\b|V\b|mV\b|"
    r"A\b|mA\b|µA\b|W\b|mW\b|kW\b|kW/m2\b|mW/cm2\b|J\b|kJ\b|MJ\b|Pa\b|kPa\b|MPa\b|GPa\b|"
    r"bar\b|mbar\b|Torr\b|Hz\b|kHz\b|MHz\b|GHz\b|rpm\b|Da\b|kDa\b|mol%|wt%|vol%|at%|"
    r"volts?\b|hours?\b|minutes?\b|seconds?\b|days?\b|weeks?\b|months?\b|years?\b|"
    r"times\b|fold\b))?",
)

CITATION_RES = [
    re.compile(r"\[\s*\d+(?:\s*[-,–]\s*\d+)*\s*\]"),
    re.compile(r"\[[A-Za-z][^\]]{0,60}?\d{4}[a-z]?\]"),
    re.compile(r"\([A-Z][A-Za-z'\-]+(?:\s+(?:and|&|et al\.)\s+[A-Z][A-Za-z'\-]+)*,?\s*(?:19|20)\d{2}[a-z]?(?:\s*;\s*[^()]{0,60})?\)"),
    re.compile(r"\\cite[a-z]*\{[^}]{1,120}\}"),
    re.compile(r"\\ref\{[^}]{1,60}\}"),
    re.compile(r"\\label\{[^}]{1,60}\}"),
]

CROSSREF_RE = re.compile(
    r"\b(?:Fig(?:ure)?s?|Tab(?:le)?s?|Eq(?:uation)?s?|Sec(?:tion)?s?|Chap(?:ter)?s?|"
    r"Supp(?:lementary)?\s+(?:Fig(?:ure)?|Tab(?:le)?)|Scheme|Algorithm)\s*\.?\s*"
    r"(?:S?\d+[a-z]?(?:\s*[–\-]\s*\d+[a-z]?)?|[IVX]+)\b",
    re.IGNORECASE,
)

FORMULA_RE = re.compile(
    r"\$[^$]{1,120}\$|\\\([^)]{1,120}\\\)|\\\[[^\]]{1,200}\\\]|"
    r"\b[A-Za-z]\s*(?:=|\u2248|\u2264|\u2265|\u221d|\u00d7)\s*[-\w\\.]+"
)

URL_RE = re.compile(r"https?://[^\s)>\]]+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")

LATEX_CMD_RE = re.compile(r"\\[A-Za-z]{2,}\*?(?:\[[^\]]*\])?(?:\{[^{}]{0,80}\})?")


def protected_spans(text: str) -> dict:
    """Collect spans that must survive polishing unchanged."""
    out = {"number": [], "citation": [], "crossref": [], "formula": [], "url": [], "doi": []}
    for m in NUM_RE.finditer(text or ""):
        val = m.group("val")
        unit = m.group("unit") or ""
        if unit:
            out["number"].append((val + " " + unit).strip())
        elif re.match(r"^\d", val):
            out["number"].append(val)
    for rx in CITATION_RES:
        for m in rx.finditer(text or ""):
            out["citation"].append(m.group(0))
    for m in CROSSREF_RE.finditer(text or ""):
        out["crossref"].append(norm(m.group(0)))
    for m in FORMULA_RE.finditer(text or ""):
        out["formula"].append(norm(m.group(0)))
    for m in URL_RE.finditer(text or ""):
        out["url"].append(m.group(0))
    for m in DOI_RE.finditer(text or ""):
        out["doi"].append(m.group(0))
    for k in out:
        out[k] = sorted(set(x for x in out[k] if x))
    return out


def _lex_hits(text: str, en: list, zh: list) -> list:
    low = " " + (text or "").lower() + " "
    hits = []
    for w in en:
        if " " in w:
            if w in low:
                hits.append(w)
        else:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
                hits.append(w)
    for w in zh:
        if w in (text or ""):
            hits.append(w)
    return sorted(set(hits))


def cues(text: str) -> dict:
    """Linguistic cues that carry meaning and must be conserved."""
    t = text or ""
    return {
        "hedges": _lex_hits(t, HEDGE_EN, HEDGE_ZH),
        "boosts": _lex_hits(t, BOOST_EN, BOOST_ZH),
        "negation": _lex_hits(t, NEG_EN, NEG_ZH),
        "quantifiers": _lex_hits(t, QUANT_EN, QUANT_ZH),
        "conditions": _lex_hits(t, COND_EN, COND_ZH),
        "causal": _lex_hits(t, CAUSAL_EN, []),
        "correlational": _lex_hits(t, CORREL_EN, []),
        "numbers": protected_spans(t)["number"],
        "citations": protected_spans(t)["citation"],
    }


def hedge_balance(text: str) -> dict:
    """Strength signature of a sentence: how many hedges vs boosts."""
    c = cues(text)
    return {
        "hedges": len(c["hedges"]),
        "boosts": len(c["boosts"]),
        "causal": len(c["causal"]),
        "correlational": len(c["correlational"]),
        "conditional": len(c["conditions"]),
        "negation": len(c["negation"]),
        "quantifier": len(c["quantifiers"]),
    }


# ---------------------------------------------------------------- io helpers

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"__load_error__": "missing", "path": path}
    except Exception as exc:  # pragma: no cover - defensive
        return {"__load_error__": type(exc).__name__, "path": path, "detail": str(exc)[:200]}


def read_jsonl(path: str) -> list:
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"__load_error__": "bad_json_line", "raw": line[:200]})
    return rows


def dump_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def dump_jsonl(path: str, rows: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def dump_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def pjson(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------- input docs

DOCX_PARAGRAPH = re.compile(r"</w:p>")
DOCX_BREAK = re.compile(r"<w:br\s*/>")
TAG = re.compile(r"<[^>]+>")


def read_docx(path: str) -> str:
    """Extract paragraphs from a .docx using only the standard library."""
    with zipfile.ZipFile(path) as z:
        try:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        except KeyError:
            return ""
    xml = DOCX_BREAK.sub("\n", xml)
    xml = DOCX_PARAGRAPH.sub("\n\n", xml)
    xml = re.sub(r"<w:tab\s*/>", "\t", xml)
    text = TAG.sub("", xml)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    lines = [norm(ln) for ln in text.split("\n")]
    out = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()


def read_text_any(path: str) -> tuple:
    """Read a manuscript from any of the supported container formats.

    Returns (text, note). ``note`` is empty on success and carries the reason
    when the file could not be read as text.
    """
    if not path or not os.path.exists(path):
        return "", "missing"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx":
            txt = read_docx(path)
            return (txt, "" if txt.strip() else "docx_no_text")
        if ext == ".pdf":
            try:
                import fitz  # PyMuPDF, present in the pinned image
            except Exception:
                return "", "pdf_requires_pymupdf"
            doc = fitz.open(path)
            if getattr(doc, "needs_pass", False):
                return "", "encrypted_pdf"
            pages = []
            for i in range(len(doc)):
                pages.append(doc[i].get_text("text"))
            txt = "\n\n".join(p for p in pages if p and p.strip())
            doc.close()
            return (norm(txt), "" if txt.strip() else "no_text_layer")
        with open(path, "r", encoding="utf-8-sig") as fh:
            return (fh.read().replace("\r\n", "\n"), "")
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="gb18030") as fh:
                return (fh.read().replace("\r\n", "\n"), "decoded_as_gb18030")
        except Exception as exc:
            return "", "undecodable:" + type(exc).__name__
    except Exception as exc:
        return "", "read_failed:" + type(exc).__name__


_TEXT_KEYS = ("manuscript", "text", "draft", "document", "document_text", "content",
              "source_text", "original", "original_text", "body", "paper_text")
_PATH_KEYS = ("manuscript_path", "document_path", "draft_path", "source_path",
              "paper_path", "file", "path", "input_path", "pdf", "txt", "md")


def _first(d: dict, keys) -> object:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
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


def _resolve(base: str, p: str) -> str:
    if not p:
        return ""
    p = str(p)
    if os.path.isabs(p):
        return p
    cand = os.path.join(base, p)
    if os.path.exists(cand):
        return cand
    return cand


def load_case(path: str) -> tuple:
    """Load /input/case.json and resolve the task + manuscript context."""
    case = read_json(path)
    base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
    ctx = {
        "case_id": None,
        "case_path": path,
        "base": base,
        "contract": {},
        "task": None,
        "style": None,
        "audience": None,
        "target_language": None,
        "glossary": None,
        "manuscript_path": "",
        "inline_text": "",
        "notes": [],
        "extra_json": {},
    }
    if isinstance(case, dict) and "__load_error__" not in case:
        ctx["case_id"] = case.get("case_id") or case.get("id") or case.get("caseId")
        contract = case.get("output_contract") or case.get("outputs") or {}
        if isinstance(contract, dict):
            ctx["contract"] = contract
        ctx["style"] = _first(case, ("style", "genre", "register", "target_style", "document_type"))
        ctx["audience"] = _first(case, ("audience", "readers", "target_audience"))
        ctx["target_language"] = _first(case, ("target_language", "language", "lang", "output_language"))
        gl = _first(case, ("glossary", "terms", "terminology", "glossary_path", "terminology_path"))
        if isinstance(gl, (list, dict)):
            ctx["glossary"] = gl
        elif isinstance(gl, str):
            ctx["glossary"] = _resolve(base, gl)
        ctx["task"] = _first(case, ("task", "instruction", "prompt", "request", "spec"))
        p = _first(case, _PATH_KEYS)
        if isinstance(p, str):
            ctx["manuscript_path"] = _resolve(base, p)
        elif isinstance(p, list) and p and isinstance(p[0], str):
            ctx["manuscript_path"] = _resolve(base, p[0])
        t = _first(case, _TEXT_KEYS)
        if isinstance(t, str) and t.strip():
            ctx["inline_text"] = t
        # file-name fallback: look for the usual manuscript containers next to case.json
        if not ctx["manuscript_path"]:
            for name in ("manuscript.md", "manuscript.txt", "manuscript.tex", "manuscript.docx",
                         "draft.md", "draft.txt", "document.md", "document.txt", "source.md",
                         "source.txt", "paper.md", "paper.txt", "material.md", "material.txt",
                         "text.md", "text.txt", "input.md", "input.txt"):
                cand = os.path.join(base, name)
                if os.path.exists(cand):
                    ctx["manuscript_path"] = cand
                    ctx["notes"].append("manuscript located by file-name fallback: " + name)
                    break
        # extra json files in the same directory (glossary candidates, style guides)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not name.lower().endswith(".json"):
                continue
            if name in ("case.json", "task.json", "challenge.json", "config.json"):
                continue
            ctx["extra_json"][name] = os.path.join(base, name)
    elif isinstance(case, dict):
        ctx["notes"].append("case.json could not be parsed: " + str(case.get("__load_error__")))
    else:
        ctx["notes"].append("case.json missing or not an object")
    return case, ctx


def load_manuscript(ctx: dict) -> tuple:
    """Return (text, source_kind, path, notes).

    source_kind 取值：``file:<ext>``（读到了正文）、``file:<ext>:empty``（文件存在但没内容）、
    ``file:<ext>:unreadable``（文件存在但读不出文字，如损坏/加密/无文字层）、
    ``case_inline_text``（正文写在 case.json 里）、``none``（根本没找到稿件）。
    """
    notes = list(ctx.get("notes") or [])
    path = ctx.get("manuscript_path") or ""
    if path:
        text, note = read_text_any(path)
        if note and note != "decoded_as_gb18030":
            notes.append("manuscript read note: " + note)
        elif note:
            notes.append("manuscript " + note)
        kind = "file:" + os.path.splitext(path)[1].lower().lstrip(".")
        if text.strip():
            return text, kind, path, notes
        if os.path.exists(path):
            clean = (not note) or note == "decoded_as_gb18030"
            return "", kind + (":empty" if clean else ":unreadable"), path, notes
    inline = ctx.get("inline_text") or ""
    if inline.strip():
        return inline, "case_inline_text", "", notes
    return "", "none", path, notes


def parse_glossary(gl) -> list:
    """Normalise a glossary into [{term, preferred, variants, note}]."""
    rows = []
    if isinstance(gl, dict):
        if "entries" in gl and isinstance(gl["entries"], list):
            gl = gl["entries"]
        elif "terms" in gl and isinstance(gl["terms"], list):
            gl = gl["terms"]
        else:
            for k, v in gl.items():
                if isinstance(v, str):
                    rows.append({"term": k, "preferred": v, "variants": [], "note": ""})
                elif isinstance(v, dict):
                    rows.append({
                        "term": k,
                        "preferred": v.get("preferred") or v.get("zh") or v.get("en") or k,
                        "variants": v.get("variants") or [],
                        "note": v.get("note") or "",
                    })
            return rows
        return parse_glossary(gl)
    if isinstance(gl, str):
        data = read_json(gl)
        return parse_glossary(data) if "__load_error__" not in data else []
    if isinstance(gl, list):
        for item in gl:
            if isinstance(item, str):
                rows.append({"term": item, "preferred": item, "variants": [], "note": ""})
            elif isinstance(item, dict):
                term = item.get("term") or item.get("source") or item.get("from") or ""
                if not term:
                    continue
                pref = (item.get("preferred") or item.get("target") or item.get("to")
                        or item.get("canonical") or term)
                variants = item.get("variants") or item.get("aliases") or []
                if isinstance(variants, str):
                    variants = [variants]
                rows.append({"term": term, "preferred": pref, "variants": list(variants),
                             "note": item.get("note") or ""})
    return rows


# ---------------------------------------------------------------- result io

def emit_result(out_path: str, case_id, status, primary, evidence=None, uncertainty=None,
                artifacts=None, contract=None, extra_top=None) -> dict:
    """Write result.json with contract keys mapped and gaps recorded honestly."""
    out_dir = os.path.dirname(os.path.abspath(out_path))
    result = {
        "schema": "polish-result/1.0",
        "case_id": case_id,
        "status": status,
        "primary_result": primary,
        "evidence": evidence or [],
        "uncertainty": list(uncertainty or []),
        "artifacts": artifacts or [],
        "change_log": [],
    }
    unmapped = []
    if isinstance(contract, dict):
        for key, spec in contract.items():
            if key in result:
                continue
            fn = CONTRACT_ALIASES.get(key)
            hit = None
            if fn:
                for cand in fn:
                    p = os.path.join(out_dir, cand)
                    if os.path.exists(p):
                        hit = cand
                        break
            if hit:
                result[key] = hit
            else:
                default = spec.get("default") if isinstance(spec, dict) else None
                result[key] = default
                unmapped.append(key)
    if unmapped:
        result["uncertainty"].append(
            "output_contract fields not produced as files: " + ", ".join(sorted(unmapped)))
    if isinstance(primary, dict):
        for k, v in primary.items():
            result.setdefault(k, v)
    if isinstance(extra_top, dict):
        for k, v in extra_top.items():
            result.setdefault(k, v)
    dump_json(out_path, result)
    return result


CONTRACT_ALIASES = {
    "manuscript": ["revised.md", "revised.txt", "manuscript_revised.md", "polished.md"],
    "revised": ["revised.md", "revised.txt", "manuscript_revised.md"],
    "revised_text": ["revised.md", "revised.txt"],
    "diff": ["diff.md", "edits.md", "changes.md"],
    "edits": ["edits.jsonl", "diff.jsonl"],
    "changes": ["diff.md", "changes.md", "edits.jsonl"],
    "glossary": ["glossary.tsv", "glossary.json", "terms.tsv"],
    "terms": ["glossary.tsv", "glossary.json"],
    "consistency": ["consistency.json", "check.json"],
    "check": ["check.json"],
    "review": ["review.md"],
    "segments": ["segments.json"],
    "bilingual": ["bilingual.md"],
    "report": ["review.md", "report.md"],
}
