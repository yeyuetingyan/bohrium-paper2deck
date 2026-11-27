#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""methodkit —— 方法与实验章节写作 Skill 的共用核（纯标准库）。

职责：
  * 文本归一化 / 句子切分 / 数值与不可变成分的定位
  * 材料读取（多种形态：配置文件、日志、代码、说明文档、数据集说明）
  * 确定性解析：配置键值、日志键值、命令行、版本、随机种子、硬件、划分
  * case.json 的宽容读取（候选键 + 文件名兜底 + 同目录材料目录扫描）
  * 结构化结果落盘（result.json / jsonl / tsv），写文件一律 LF

不联网、不调用模型、只读输入、只写调用方指定的输出目录。
"""

from __future__ import annotations

import io
import json
import os
import re
import hashlib

VERSION = "methodkit/1.0"

# ---------------------------------------------------------------- 文本工具

_WS = re.compile(r"[ \t\u00a0\u3000]+")
_SOFT_HYPHEN = re.compile(r"(\w)-\n(\w)")
_ABBREV = re.compile(
    r"\b(?:et al|e\.g|i\.e|cf|vs|Fig|Figs|Eq|Eqs|Ref|Refs|Sec|Secs|Tab|No|approx|Dr|Mr|Ms|Prof|Inc|Ltd|etc)\.(?!\d)",
    re.I,
)
_SENT = re.compile(r"(?<=[。！？；!?;])\s*|(?<=[.])\s+(?=[A-Z\u4e00-\u9fff])")
_SENT_KEEP = re.compile(r"(.+?(?:[。！？；!?;.](?=\s|$)|\n|$))", re.S)


def norm(text):
    """压掉行内空白、合并硬折行，**保留空行作为段落/块分隔**。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SOFT_HYPHEN.sub(r"\1\2", text)
    blocks = []
    for raw in text.split("\n\n"):
        lines = [_WS.sub(" ", ln).strip() for ln in raw.split("\n")]
        lines = [ln for ln in lines if ln]
        if lines:
            blocks.append(" ".join(lines))
    return "\n\n".join(blocks)


def norm_preserve_lines(text):
    """只压行内空白，保留换行（用于配置文件/日志这类行敏感材料）。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_WS.sub(" ", ln).rstrip() for ln in text.split("\n"))


def norm_hard(text):
    """去标点空白并小写，用于宽容比对。"""
    if not text:
        return ""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def flat(text):
    """仅去空白，用于不可变成分的多重集比对。"""
    return re.sub(r"\s+", "", text or "")


def sentences(text):
    """切句；保护常见缩写与小数点。"""
    if not text:
        return []
    guard = _ABBREV.sub(lambda m: m.group(0).replace(".", "\x01"), text)
    guard = re.sub(r"(?<=\d)\.(?=\d)", "\x01", guard)
    out = []
    for piece in _SENT.split(guard):
        if piece is None:
            continue
        s = piece.strip()
        if s:
            out.append(s.replace("\x01", "."))
    return out


_TOK = re.compile(r"[A-Za-z][A-Za-z0-9_\-\.]*|[\u4e00-\u9fff]{1,6}|\d+(?:\.\d+)?%?")


def tokens(text):
    return _TOK.findall(text or "")


def cjk_ratio(text):
    if not text:
        return 0.0
    n = len(re.findall(r"[\u4e00-\u9fff]", text))
    return n / max(1, len(text))


def strip_tags(text):
    return re.sub(r"</?[A-Za-z][^>]{0,20}>", "", text or "")


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_16(text):
    return sha256_text(text)[:16]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 不可变成分

NUM_UNITS = (
    "%|°C|℃|K|h|hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs|ms|us|µs|ns|"
    "nm|µm|um|mm|cm|m|km|mg|g|kg|t|ml|mL|µL|uL|L|l|mol|mmol|µmol|M|mM|nM|"
    "eV|keV|MeV|V|mV|mA|A|W|kW|mW|J|kJ|mJ|Pa|kPa|MPa|GPa|bar|atm|Torr|"
    "Hz|kHz|MHz|GHz|rpm|Da|kDa|Å|angstrom|ppm|ppb|"
    "mol%|wt%|vol%|at%|fold|times|倍|度|小时|分钟|秒|天|周|月|年|"
    "GiB|MiB|KiB|GB|MB|KB|TB|TiB|FPS|fps|IPS|TOPS|FLOPs|GFLOPs|TFLOPs|"
    "steps|epochs|epoch|iterations|iters|tokens|samples|images|params|layers|heads|dim|"
    "µg|ng|pg|px|dpi|bpm|°|℃"
)
NUM_RE = re.compile(
    r"(?P<val>(?<![\w.])[-+]?\d+(?:[.,]\d+)?"
    r"(?:[eE][-+]?\d{1,3}|(?:\s*[×x]\s*10\s*\^?\s*[-+]?\d+))?)"
    r"(?:\s*(?P<unit>%s))?(?![\w])" % NUM_UNITS
)

CITATION_RES = (
    ("numeric", re.compile(r"(?<![\d\]])\[(\d{1,3}(?:\s*[-,–]\s*\d{1,3})*)\]")),
    ("author-year", re.compile(r"\(([A-Z][A-Za-z\u00c0-\u024f'\-]+(?:\s+(?:et al\.|and|&)\s*[A-Z][A-Za-z\u00c0-\u024f'\-]*)?),\s*(\d{4}[a-z]?)\)")),
    ("latex", re.compile(r"\\(?:cite|citep|citet|ref|eqref)\{([^}]{1,80})\}")),
    ("bracket-key", re.compile(r"(?<![\d\]])\[([A-Za-z][A-Za-z0-9_:\-\.]{2,40})\]")),
)
CROSSREF_RE = re.compile(
    r"\b(Fig(?:ure)?s?|Tab(?:le)?s?|Eq(?:uation)?s?|Sec(?:tion)?s?|Chap(?:ter)?s?|"
    r"Alg(?:orithm)?s?|App(?:endix)?|Sect\.|图|表|式|节)\s*\.?\s*(\d+(?:\.\d+)*)",
    re.I,
)
FORMULA_RE = re.compile(r"\\[A-Za-z]{2,}|\$[^$]{2,80}\$|\b[A-Za-z]\s*=\s*[-+]?[\d.]")
URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")

# 参数名：snake_case / kebab-case / 带等号或冒号
PARAM_RE = re.compile(
    r"(?P<key>[A-Za-z][A-Za-z0-9]*(?:[_\-\.][A-Za-z0-9]+){1,4})\s*(?P<sep>[=:])\s*(?P<val>[^\s,;\)\]\}]{1,48})"
)
# 版本：python 3.9.7 / torch 2.1.0 / CUDA 11.8 / v1.2.3 / Ubuntu 22.04
VERSION_RE = re.compile(
    r"\b(?P<name>python|py|torch|pytorch|tensorflow|tf|cuda|cudnn|numpy|scipy|sklearn|"
    r"transformers|jax|mindspore|paddle|paddlepaddle|ubuntu|centos|debian|windows|macos|"
    r"node|npm|gcc|clang|java|jdk|docker|k8s|kubernetes|nvidia|driver|apex|deepspeed|"
    r"fairseq|mmcv|mmdet|opencv|pillow|pandas|matplotlib|seaborn|wandb|mlflow)\s*"
    r"(?:version\s*)?[:=]?\s*v?(?P<ver>\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.]+)?)",
    re.I,
)
SEED_RE = re.compile(
    r"(?:\bseed\b|\brandom[_\s-]?seed\b|\bmanual[_\s-]?seed\b|随机种子|种子)[^\d\n]{0,12}?(?P<seed>\d{1,10})",
    re.I,
)
HW_RE = re.compile(
    r"\b(?P<count>\d{1,2}\s*[x×]\s*)?(?P<card>A100|A800|H100|H800|V100|P100|T4|RTX\s?\d{3,4}|"
    r"3090|4090|TPU\s?v?\d?|Ascend\s?\d{3,4}|昇腾\s?\d{3,4}|CPU|GPU)\b(?:\s*(?P<mem>\d{1,3})\s?(?:GB|G))?",
    re.I,
)
PATH_RE = re.compile(r"(?:^|[\s`\"'(])(?P<path>(?:[\w.\-]+/){1,6}[\w.\-]+\.(?:py|yaml|yml|json|jsonl|csv|tsv|txt|md|sh|cfg|ini|toml|h5|pt|pth|ckpt|bin))")
CMD_RE = re.compile(r"(?<![A-Za-z0-9_])(?P<cmd>(?:CUDA_VISIBLE_DEVICES=\S+\s+)*(?:python[0-9.]*|python3|bash|sh|sbatch|torchrun|deepspeed|accelerate)\s+[^\n`\"]{3,160})")
SPLIT_RE = re.compile(
    r"(?P<part>train|training|val|valid|validation|dev|test|testing|训练|验证|测试)\s*(?:set|集|split|划分|部分)?\s*[:=]?\s*"
    r"(?P<frac>\d{1,3}(?:\.\d+)?\s*%|\d+\s*/\s*\d+|\d{1,3}(?:\.\d+)?)",
    re.I,
)
SPLIT_RATIO_RE = re.compile(
    r"(?P<ratio>\d{1,3}\s*[:/]\s*\d{1,3}(?:\s*[:/]\s*\d{1,3}){1,2})"
    r"(?:\s*(?:的)?\s*(?:比例|划分|split|ratio))?"
    r"|(?:比例|划分|split|ratio)\s*(?:是|为|:|=)?\s*"
    r"(?P<ratio2>\d{1,3}\s*[:/]\s*\d{1,3}(?:\s*[:/]\s*\d{1,3}){1,2})",
    re.I,
)
SPLIT_PART_RE = re.compile(
    r"(?P<part>train|training|val|valid|validation|dev|test|testing|训练|验证|测试)",
    re.I,
)
# 旧式宽口径（保留兼容，实际抽取已改用上面两条）
SPLIT_RE = re.compile(
    r"(?P<part>train|training|val|valid|validation|dev|test|testing|训练|验证|测试)\s*(?:set|集|split|划分|部分)?\s*[:=]?\s*"
    r"(?P<frac>\d{1,3}(?:\.\d+)?\s*%|\d+\s*/\s*\d+|\d{1,3}(?:\.\d+)?)",
    re.I,
)
# 数据集：名字必须以字母数字收尾，版本必须以 v 或数字起头（否则会把 train_file 之类切出 al_file、er 这种碎片）
DATASET_RE = re.compile(
    r"\b(?P<name>[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)\s*[（(]?\s*"
    r"(?:dataset|数据集|benchmark|corpus|语料库)?\s*[（(]?\s*"
    r"(?:v|version|版本)\s*[:=：]?\s*(?P<ver>v?\d[\w.\-]{0,15})",
    re.I,
)
# 代码里的参数只认「明确声明」两种形态：环境变量与 argparse 默认值。
ENV_PARAM_RE = re.compile(
    r"environ(?:\.setdefault)?\s*[\[(]\s*[\"'](?P<k>[A-Za-z_][A-Za-z0-9_]{1,40})[\"']\s*,?\s*[\"']?(?P<v>[^\"')\n,]{0,40})"
)
ARGPARSE_DEFAULT_RE = re.compile(
    r"add_argument\(\s*[\"']--?(?P<k>[A-Za-z0-9_\-]{2,40})[\"'][^)]{0,200}?default\s*=\s*(?P<v>[^,)\n]{1,40})"
)
JUNK_PARAM_KEYS = {
    "ap", "args", "arg", "parser", "out", "key", "value", "buckets", "required", "ratios",
    "opts", "self", "data", "df", "doc", "text", "rows", "result", "res", "name", "path",
    "root", "base", "tmp", "cfg", "conf", "config", "kwargs", "params", "item", "items",
}


def is_junk_param_key(key, val=""):
    """过滤代码/正文扫描里冒出来的中间变量：它们不是超参数，只是实现细节。"""
    k = (key or "").strip()
    if not k or len(k) < 2:
        return True
    if k.startswith("__") or k.endswith("__"):
        return True
    if k.lower() in JUNK_PARAM_KEYS:
        return True
    v = (val or "").strip()
    if v in ("[]", "{}", "()", "None", "True", "False") and k.islower():
        return True
    if v.count("{") != v.count("}") or v.count("[") != v.count("]") or v.count("(") != v.count(")"):
        return True
    if re.match(r"^(?:argparse|os\.|sys\.|print|len|str|int|float|dict|list)\b", v):
        return True
    return False
EPOCH_RE = re.compile(r"\b(?:epochs?|轮次|训练轮数|iters?|iterations?|steps?)\s*[:=]?\s*(?P<n>\d{1,7})", re.I)
# 中英混排里不要用 \b：CJK 与 CJK 之间没有词边界，会漏掉"限制""基线"这类中文线索。
LB = r"(?<![A-Za-z0-9])"
RB = r"(?![A-Za-z0-9])"
LIMIT_CUE = re.compile(
    LB + r"(?:limitation|limitations|caveat|fails?|failure|only when|unless|does not|cannot|"
         r"degrad\w*|restrict\w*|assumption|scope of|not applicable|insufficient)\b"
         r"|(?:局限|限制|不足|失效|仅适用|不适用|无法|不能|漏掉|不建议|不稳定|明显下降|退化|受限)",
    re.I,
)
VAGUE_LIMIT = re.compile(
    r"(?:future\s+work\s+will|more\s+research\s+is\s+needed|有?待进一步|需要更多研究|受限于时间|"
    r"由于时间关系|更深入的研究|有待完善|尚需研究)",
    re.I,
)
COND_CUE = re.compile(
    LB + r"(?:when|if|under|above|below|beyond|exceed\w*|smaller than|larger than)\b"
         r"|(?:高于|低于|超过|小于|大于|当|在.{0,12}时|条件下)",
    re.I,
)
BOILERPLATE = re.compile(
    r"(?:comprehensive\s+experiments\s+(?:are|were)\s+conducted|"
    r"extensive\s+experiments\s+(?:show|demonstrate)|"
    r"我们进行了(?:大量|充分)的实验|实验结果表明该方法(?:是)?有效的|"
    r"achieving\s+state-of-the-art\s+performance\s+on\s+all|"
    r"取得了(?:优异|良好)的(?:效果|性能))",
    re.I,
)
OVERCLAIM = re.compile(
    LB + r"(?:proves?|guarantee[sd]?|always|never|perfect|best|optimal|first\s+time|"
         r"completely\s+solves?)\b|(?:证明|保证|总是|从不|最优|首次)",
    re.I,
)
HEDGE = re.compile(
    LB + r"(?:may|might|could|suggest[s]?|appear[s]?|tend[s]?|likely|approximately|about|"
         r"roughly|around|up\s+to|at\s+most|at\s+least)\b|(?:可能|大约|初步|大致|左右)",
    re.I,
)
NEGATION = re.compile(LB + r"(?:not|no|never|without|neither|nor|none|cannot|unable)\b|不|无|未|非", re.I)
QUANTIFIER = re.compile(LB + r"(?:all|every|each|any|some|most|none|both|several|few)\b|所有|全部|每个|任何|大多数|仅|只有")

# 方法与实验章节专用线索
METRIC_CUE = re.compile(LB + r"(?:accuracy|f1|precision|recall|auc|rmse|mae|mape|bleu|rouge|psnr|ssim|"
                        r"latency|throughput|loss|perplexity|mAP|IoU|ndcg)\b|(?:准确率|精确率|召回率|误差|时延|吞吐)", re.I)
STAT_CUE = re.compile(LB + r"(?:mean|median|std|std\.?\s*dev|standard\s+deviation|confidence interval|"
                      r"95%\s*CI|t-test|wilcoxon|bootstrap)\b|(?:平均值|中位数|标准差|置信区间|显著性)", re.I)
REPRO_CUE = re.compile(LB + r"(?:download|reproduce|checkpoint|code\s+version|commit|"
                       r"requirements\.txt|environment\.ya?ml|dockerfile|install)\b|(?:获取|复现|安装|开源)", re.I)
STEP_CUES = re.compile(
    r"(?m)^\s*(?:(?:step|阶段|步骤)\s*\d+[:.、)]|\d{1,2}[.、)]\s+\S|#{2,4}\s*\S|\[(?:stage|phase|step)[^\]]{0,30}\])",
    re.I,
)
DECISION_CUE = re.compile(LB + r"(?:if|whether|check|verify|ensure|until)\b|(?:当|若|判断|检查|确认|直到)", re.I)
INPUT_CUE = re.compile(LB + r"(?:input|read|load|parse|take|accept)\b|(?:输入|读取|载入|加载)", re.I)
OUTPUT_CUE = re.compile(LB + r"(?:output|write|save|dump|export|emit|produce)\b|(?:输出|写入|保存|导出|生成)", re.I)
BASELINE_CUE = re.compile(
    r"(?P<name>[A-Za-z][\w\-]{2,30})[\s\u4e00-\u9fff（(【:：,，]{1,8}?(?P<kind>baselines?|基线|对照|control)s?(?![A-Za-z])"
    r"|(?P<kind2>baselines?|基线|对照|control)s?(?![A-Za-z])[\s）)】:：]{0,3}(?P<name2>[A-Za-z][\w\-]{2,30})"
    r"|(?:compared\s+(?:with|to)|versus|vs\.?|对比|相比|比较)[\s（(]{0,3}(?P<name3>[A-Za-z][\w\-]{2,30})",
    re.I,
)
REPEAT_RE = re.compile(r"(?:repeat|重复|runs?|试次|次数|trials?|seeds?\s*[:=]?\s*\d+\s*(?:seeds|次))\s*[:=]?\s*(?P<n>\d{1,4})", re.I)
LIMIT_VAGUE = re.compile(
    r"(?:future\s+work\s+will|more\s+research\s+is\s+needed|有?待进一步|需要更多研究|受限于时间|"
    r"由于时间关系|更深入的研究|有待完善|尚需研究)",
    re.I,
)

PROTECTED_KINDS = ("number", "unit", "citation", "crossref", "formula", "url", "doi", "version", "seed", "path", "cmd", "hw")


def numbers(text):
    """返回 [{raw,val,unit,start,end}]；raw 去空白。"""
    out = []
    for m in NUM_RE.finditer(text or ""):
        val = m.group("val")
        unit = (m.group("unit") or "").strip()
        out.append({
            "raw": (val + (" " + unit if unit else "")),
            "val": val.replace(",", ""),
            "unit": unit,
            "start": m.start(),
            "end": m.end(),
        })
    return out


def _spots(text, regex, group=None, kind=""):
    out = []
    for m in regex.finditer(text or ""):
        raw = m.group(group) if group else m.group(0)
        if raw is None:
            continue
        out.append({"kind": kind, "raw": raw.strip(), "start": m.start(), "end": m.end()})
    return out


def protected_spans(text):
    """把不可变成分按类型抓出来（供"逐字守恒"核验）。"""
    t = text or ""
    res = {k: [] for k in PROTECTED_KINDS}
    res["number"] = [n["raw"] for n in numbers(t)]
    res["citation"] = [m.group(0) for r in CITATION_RES for m in r[1].finditer(t)]
    res["crossref"] = [m.group(0) for m in CROSSREF_RE.finditer(t)]
    res["formula"] = [m.group(0) for m in FORMULA_RE.finditer(t)]
    res["url"] = [m.group(0) for m in URL_RE.finditer(t)]
    res["doi"] = [m.group(0) for m in DOI_RE.finditer(t)]
    res["version"] = [m.group("name") + " " + m.group("ver") for m in VERSION_RE.finditer(t)]
    res["seed"] = [m.group("seed") for m in SEED_RE.finditer(t)]
    res["path"] = [m.group("path") for m in PATH_RE.finditer(t)]
    res["cmd"] = [m.group("cmd").strip() for m in CMD_RE.finditer(t)]
    res["hw"] = [m.group(0).strip() for m in HW_RE.finditer(t)]
    for k in res:
        seen, uniq = set(), []
        for v in res[k]:
            key = flat(v).lower()
            if key and key not in seen:
                seen.add(key)
                uniq.append(v)
        res[k] = uniq
    return res


def numbers_with_sources(text, where):
    out = []
    for n in numbers(text or ""):
        out.append({"raw": n["raw"], "val": n["val"], "unit": n["unit"], "where": where})
    return out


# ---------------------------------------------------------------- 配置/日志解析

_YAML_KV = re.compile(r"^(?P<indent>\s*)(?:-\s+)?(?P<key>[A-Za-z_][\w\-\.]*)\s*:\s*(?P<val>.*)$")
_KV_ANY = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_\-\.]{1,40})\s*(?P<sep>[=:])\s*(?P<val>[^\s#;]{1,64})")


def _strip_inline_comment(v):
    out = []
    quote = None
    for i, ch in enumerate(v):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or v[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).strip()


def _scalar(v):
    v = _strip_inline_comment(v).strip().strip(",")
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    if v.lower() in ("true", "yes", "null", "none", "~"):
        return v
    return v


def parse_config(text, source="config"):
    """朴素 YAML/INI/JSON 子集解析 → [{key, key_path, value, line, source, section}]。

    只做确定性的键值抽取，不做语义推断；解析不出的行原样跳过。
    """
    t = norm_preserve_lines(text)
    rows = []
    if not t.strip():
        return rows
    stripped = t.strip()
    if stripped[:1] in "{[":
        try:
            data = json.loads(stripped)
        except Exception:
            data = None
        if data is not None:
            def walk(node, prefix):
                if isinstance(node, dict):
                    for k, v in node.items():
                        walk(v, prefix + [str(k)])
                elif isinstance(node, list):
                    for i, v in enumerate(node):
                        walk(v, prefix + ["[%d]" % i])
                else:
                    rows.append({
                        "key": prefix[-1] if prefix else "",
                        "key_path": ".".join(prefix),
                        "value": ("" if node is None else str(node)),
                        "line": 0,
                        "source": source,
                        "section": prefix[0] if len(prefix) > 1 else "",
                    })
            walk(data, [])
            return rows
    stack = []  # (indent, key)
    for ln_no, line in enumerate(t.split("\n"), 1):
        if not line.strip() or line.strip().startswith(("#", "//", ";")):
            continue
        if line.strip().startswith("- "):
            item = line.strip()[2:].strip()
            kvm = _KV_ANY.match(item)
            if kvm and kvm.group("key"):
                rows.append({
                    "key": kvm.group("key"), "key_path": ".".join([s[1] for s in stack] + [kvm.group("key")]),
                    "value": _scalar(kvm.group("val")), "line": ln_no, "source": source,
                    "section": stack[-1][1] if stack else "",
                })
            continue
        m = _YAML_KV.match(line)
        if not m:
            continue
        indent = len(m.group("indent").replace("\t", "    "))
        key = m.group("key")
        val = m.group("val").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if val == "" or val.startswith("#"):
            stack.append((indent, key))
            continue
        path = [s[1] for s in stack] + [key]
        rows.append({
            "key": key, "key_path": ".".join(path), "value": _scalar(val),
            "line": ln_no, "source": source, "section": stack[-1][1] if stack else "",
        })
    return rows


def parse_log_kv(text, source="log"):
    """从日志/说明里抓 key=value / key: value（带行号）。"""
    rows = []
    for ln_no, line in enumerate(norm_preserve_lines(text).split("\n"), 1):
        if not line.strip():
            continue
        for m in _KV_ANY.finditer(line):
            key = m.group("key")
            if len(key) < 2 or key.lower() in ("http", "https"):
                continue
            rows.append({
                "key": key, "key_path": key, "value": _scalar(m.group("val")),
                "line": ln_no, "source": source, "sep": m.group("sep"),
            })
    return rows


def merge_params(*row_lists):
    """合并参数行；同名同值去重，同名不同值全部保留（冲突留给核验）。"""
    seen, out = set(), []
    for rows in row_lists:
        for r in rows or []:
            sig = (r.get("key", "").lower(), flat(str(r.get("value", ""))).lower(),
                   r.get("source", ""), str(r.get("line", "")))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(r)
    return out


SERIES_KEYS = {"epoch", "epochs_ran", "step", "steps", "iter", "iteration", "batch", "loss",
               "train_loss", "val_loss", "acc", "accuracy", "lr_step", "time", "timestamp",
               "elapsed", "duration", "epoch_time"}


def clean_value(v):
    """清掉从行里带出来的尾随标点（如 `20):` → `20`），不动正常取值。"""
    v = (v or "").strip().strip('"\'')
    if re.match(r"^[-+]?\d+(?:[.,]\d+)?[^\w]*$", v):
        v = re.sub(r"[^\w.+-]+$", "", v)
    return v


def param_conflicts(rows):
    """同名不同值：返回 [{key, values:[{value,sources}]}]。

    只把「同一个键在材料里出现两种以上取值」当冲突；逐轮的序列型键（epoch/loss…）
    与取值多于 3 种的键不报冲突（它们是日志序列，不是配置分歧）。
    """
    by_key = {}
    for r in rows or []:
        k = (r.get("key") or "").lower()
        if not k:
            continue
        v = clean_value(str(r.get("value", "")))
        if v == "" or len(v) > 40:
            continue
        by_key.setdefault(k, {}).setdefault(mk_flat(v), []).append(
            {"value": v, "source": r.get("source"), "line": r.get("line")})
    out = []
    for k, vals in by_key.items():
        if k in SERIES_KEYS or len(vals) < 2 or len(vals) > 3:
            continue
        out.append({"key": k, "values": [
            {"value": v[0]["value"], "sources": [{"source": x["source"], "line": x["line"]} for x in v]}
            for v in vals.values()]})
    return out


def mk_flat(text):
    return re.sub(r"\s+", "", text or "")


def parse_split(text):
    return [{"part": m.group("part").lower(), "value": m.group("frac").strip()} for m in SPLIT_RE.finditer(text or "")]


# ---------------------------------------------------------------- 输入读取

TEXT_EXTS = (".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
             ".log", ".csv", ".tsv", ".tex", ".bib", ".py", ".sh", ".r", ".m", ".ipynb")

CASE_TEXT_KEYS = ("material", "materials", "manuscript", "draft", "document", "text", "task_material",
                  "content", "source_text", "paper", "notes", "config_text", "log_text")
CASE_DIR_KEYS = ("materials_dir", "material_dir", "files_dir", "docs_dir", "input_dir")
CASE_LIST_KEYS = ("material_files", "materials", "files", "documents", "sources", "configs", "logs")


def read_text_any(path):
    """读任意文本/PDF/DOCX；返回 (text, note)。"""
    low = path.lower()
    if low.endswith(".docx"):
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = xml.replace("</w:p>", "\n")
            return re.sub(r"<[^>]+>", "", xml), "docx"
        except Exception as e:
            return "", "docx_failed:%s" % e
    if low.endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            parts = []
            for pg in doc:
                parts.append(pg.get_text("text"))
            return "\n".join(parts), "pdf"
        except Exception as e:
            return "", "pdf_failed:%s" % e
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read(), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            return "", "read_failed:%s" % e
    return "", "undecodable"


def _file_kind(path):
    low = path.lower()
    for ext, kind in ((".yaml", "config"), (".yml", "config"), (".toml", "config"),
                      (".ini", "config"), (".cfg", "config"), (".json", "config"),
                      (".log", "log"), (".log.txt", "log"), (".out", "log"),
                      (".csv", "table"), (".tsv", "table"), (".txt", "doc"),
                      (".py", "code"), (".sh", "code"), (".ipynb", "code"),
                      (".md", "doc"), (".txt", "doc"), (".tex", "doc"), (".bib", "doc"), (".pdf", "doc")):
        if low.endswith(ext):
            return kind
    return "doc"


def discover_materials(base, case):
    """从 case 字段、materials 目录、同目录散文件里收集材料。"""
    found, warnings = [], []
    seen = set()

    def add(path, via):
        ap = os.path.abspath(path)
        if not os.path.isfile(ap) or ap.lower() in seen:
            return
        if os.path.basename(ap).lower() in ("case.json", "challenge.json", "config.json", "task.md"):
            return
        seen.add(ap.lower())
        text, note = read_text_any(ap)
        found.append({
            "name": os.path.basename(ap), "path": ap, "kind": _file_kind(ap),
            "text": text, "note": note, "via": via, "bytes": os.path.getsize(ap),
        })

    # 1) case 里显式列出的文件
    for key in CASE_LIST_KEYS:
        v = case.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    p = item.get("path") or item.get("file") or item.get("name")
                    sub = item.get("text") or item.get("content")
                    if p and isinstance(p, str):
                        cand = p if os.path.isabs(p) else os.path.join(base, p)
                        if os.path.isfile(cand):
                            add(cand, "case:%s" % key)
                        elif sub:
                            found.append({"name": os.path.basename(p), "path": "", "kind": _file_kind(p),
                                          "text": sub, "note": "inline", "via": "case:%s" % key, "bytes": len(sub)})
                            seen.add(p.lower())
                    elif sub:
                        nm = str(item.get("name") or "inline-%d" % (len(found) + 1))
                        found.append({"name": nm, "path": "", "kind": _file_kind(nm),
                                      "text": sub, "note": "inline", "via": "case:%s" % key, "bytes": len(sub)})
                elif isinstance(item, str):
                    cand = item if os.path.isabs(item) else os.path.join(base, item)
                    if os.path.isfile(cand):
                        add(cand, "case:%s" % key)
                    else:
                        warnings.append("材料路径不存在：%s（来自 %s）" % (item, key))
        elif isinstance(v, str) and v:
            if v.lower().endswith(TEXT_EXTS):
                cand = v if os.path.isabs(v) else os.path.join(base, v)
                if os.path.isfile(cand):
                    add(cand, "case:%s" % key)

    # 2) materials 目录
    for key in CASE_DIR_KEYS:
        d = case.get(key)
        if isinstance(d, str) and d:
            dd = d if os.path.isabs(d) else os.path.join(base, d)
            if os.path.isdir(dd):
                for fn in sorted(os.listdir(dd)):
                    if fn.lower().endswith(TEXT_EXTS):
                        add(os.path.join(dd, fn), "dir:%s" % key)

    # 3) 约定目录名 + 同目录散文件兜底
    for dname in ("materials", "material", "input", "inputs", "files", "data"):
        dd = os.path.join(base, dname)
        if os.path.isdir(dd):
            for root, _dirs, files in os.walk(dd):
                for fn in sorted(files):
                    if fn.lower().endswith(TEXT_EXTS):
                        add(os.path.join(root, fn), "auto:%s" % dname)
    if not found:
        for fn in sorted(os.listdir(base)):
            if fn.lower().endswith(TEXT_EXTS):
                add(os.path.join(base, fn), "auto:flat")
    return found, warnings


def load_case(path):
    """读 case.json → (case, ctx)。ctx 含材料清单、契约、约束、告警。"""
    warnings, notes = [], []
    with open(path, "r", encoding="utf-8-sig") as fh:
        case = json.load(fh)
    base = os.path.dirname(os.path.abspath(path))
    ctx = {
        "case_id": case.get("case_id") or case.get("id") or os.path.splitext(os.path.basename(path))[0],
        "case_path": os.path.abspath(path),
        "base": base,
        "contract": case.get("output_contract") or case.get("contract") or {},
        "task": case.get("task") or case.get("instruction") or "",
        "audience": case.get("audience") or "",
        "genre": case.get("genre") or case.get("style") or "",
        "language": case.get("language") or case.get("lang") or "",
        "format_constraints": case.get("format_constraints") or case.get("constraints") or {},
        "notes": notes,
        "warnings": warnings,
        "extra_json": {},
    }
    materials, mw = discover_materials(base, case)
    ctx["materials"] = materials
    ctx["warnings"].extend(mw)
    for fn in sorted(os.listdir(base)):
        if fn.lower().endswith(".json") and fn.lower() not in (
                "case.json", "challenge.json", "config.json", os.path.basename(ctx["case_path"]).lower()):
            try:
                with open(os.path.join(base, fn), "r", encoding="utf-8-sig") as fh:
                    ctx["extra_json"][fn] = json.load(fh)
            except Exception as e:
                ctx["warnings"].append("额外 json 读取失败 %s: %s" % (fn, e))
    if not materials:
        ctx["warnings"].append("没有发现任何材料文件（请检查 materials/ 目录或 case.json 的路径字段）")
    return case, ctx


def material_index(materials):
    """给材料编号并生成稳定的来源标签。"""
    out = []
    for i, m in enumerate(materials, 1):
        sid = "m-%03d" % i
        body = m.get("text") or ""
        out.append({
            "src_id": sid, "name": m.get("name"), "path": m.get("path"), "kind": m.get("kind"),
            "note": m.get("note"), "via": m.get("via"), "bytes": m.get("bytes"),
            "chars": len(body), "sha256_16": sha256_16(body), "text": body,
        })
    return out


# ---------------------------------------------------------------- 输出

CONTRACT_ALIASES = {
    "methods": "methods.md", "method": "methods.md", "manuscript": "methods.md",
    "chapter": "methods.md", "draft": "methods.md", "revised": "methods.md",
    "params": "params.tsv", "parameters": "params.tsv", "param_table": "params.tsv",
    "elements": "elements.json", "coverage": "elements.json",
    "gaps": "gaps.json", "questions": "gaps.json", "open_items": "gaps.json",
    "repro": "repro.json", "reproducibility": "repro.json", "checklist": "repro.json",
    "datasets": "datasets.json", "baselines": "baselines.json", "settings": "settings.json",
    "source_map": "source_map.json", "consistency": "consistency.json",
    "check": "check.json", "review": "review.md", "diff": "diff.md", "notes": "notes.md",
}


def dump_json(path, obj):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def dump_jsonl(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows or []:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def dump_text(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text is not None else "")


def read_json(path):
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as e:
        return {"__load_error__": str(e)}


def load_jsonl(path):
    """读 JSONL；也接受 JSON 数组形态（[ {...}, ... ]），两种写法都当行记录处理。"""
    rows = []
    try:
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            raw = fh.read().strip()
    except OSError:
        return []
    if not raw:
        return rows
    if raw.startswith("["):
        try:
            doc = json.loads(raw)
            if isinstance(doc, list):
                return doc
        except Exception as e:  # noqa: BLE001
            return [{"__parse_error__": "json array: %s" % e}]
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            rows.append({"__parse_error__": ln[:200]})
    return rows


def pjson(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def emit_result(out_path, case_id, status, primary, evidence=None, uncertainty=None,
                artifacts=None, contract=None, extra_top=None):
    """写 result.json：契约字段补齐 + primary_result 同名字段提到顶层 + artifacts 记 sha256。"""
    contract = contract or {}
    produced = dict(extra_top or {})
    missing = []
    for key, spec in contract.items():
        target = CONTRACT_ALIASES.get(key.lower(), key)
        if target in produced:
            continue
        cand = os.path.join(os.path.dirname(out_path), target)
        if os.path.isfile(cand):
            produced[target] = target
        else:
            default = spec.get("default") if isinstance(spec, dict) else None
            produced[target] = default
            missing.append(key)
    uncertainty = list(uncertainty or [])
    if missing:
        uncertainty.append("output_contract fields not produced: %s" % ", ".join(sorted(missing)))
    arts = []
    for a in artifacts or []:
        p = a if isinstance(a, str) else a.get("path")
        if not p:
            continue
        ap = p if os.path.isabs(p) else os.path.join(os.path.dirname(out_path), p)
        rec = a if isinstance(a, dict) else {"path": p}
        if os.path.isfile(ap):
            rec = dict(rec)
            rec["path"] = p
            rec.setdefault("role", "artifact")
            rec["bytes"] = os.path.getsize(ap)
            rec["sha256"] = sha256_file(ap)
        arts.append(rec)
    doc = {
        "schema": "methodkit-result/1.0",
        "case_id": case_id,
        "status": status,
        "primary_result": primary,
        "evidence": evidence or [],
        "uncertainty": uncertainty,
        "artifacts": arts,
        "change_log": [{"tool": VERSION, "action": "assemble", "status": status}],
    }
    for k, v in produced.items():
        doc.setdefault(k, v)
    if isinstance(primary, dict):
        for k, v in primary.items():
            doc.setdefault(k, v)
    dump_json(out_path, doc)
    return doc
