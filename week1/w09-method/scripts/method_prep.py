#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""method_prep —— 方法与实验章节写作：确定性第一步。

把散落的科研材料（配置文件、实验日志、代码、数据集说明、事实底稿）整理成
「要素清单 + 候选步骤/参数/设置/划分/数据集/对照/限制 + 冲突清单 + 追问候选」，
交给 Agent 去写章节。本步不调用模型，输出可复核、可重跑。

用法：
  python method_prep.py --case /input/case.json --out /app/work [--max-chars 400000]

退出码：0 正常；2 材料不可用（reason 写在 prep.json 里）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import methodkit as mk  # noqa: E402

VERSION = "method_prep/1.0"

ELEMENTS = [
    ("steps", "方法步骤", "有序、可执行、每步有输入/操作/输出/判断条件"),
    ("settings", "实验设置", "硬件、软件版本、运行环境、随机种子、重复次数"),
    ("params", "参数与来源", "参数名称、取值、单位、作用对象、来源（配置/日志/作者确认）"),
    ("datasets", "数据集与划分", "名称、版本、规模、预处理、划分比例与随机方式"),
    ("baselines", "对照实验", "基线对象与版本、同预算条件、评价指标与统计方式"),
    ("repro_limits", "可复现性与限制", "代码版本、环境、命令、数据获取方式；限制指向具体失效场景"),
]

STEP_CUES = re.compile(
    r"(?m)^\s*(?:(?:step|阶段|步骤)\s*\d+[:.、)]|\d{1,2}[.、)]\s+\S|#{2,4}\s*\S|\[(?:stage|phase|step)[^\]]{0,30}\])",
    re.I,
)
CODE_STEP = re.compile(r"(?m)^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_][\w]{2,})\s*\(")
CODE_STEP_ZH = re.compile(r"(?m)^\s*(?:#+\s*)?(?:[Ss]tep\s*\d+[:.]|阶段\s*\d+|步骤\s*\d+)[:：]?\s*(?P<name>.{2,60})")
LOG_STAGE = re.compile(
    r"(?m)^\s*(?:\[(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]\s*)?"
    r"(?P<tag>\[[A-Za-z_\- ]{2,20}\]|={3,}|>>>)\s*(?P<msg>.{2,120})")
DECISION_CUE = mk.DECISION_CUE
INPUT_CUE = mk.INPUT_CUE
OUTPUT_CUE = mk.OUTPUT_CUE
BASELINE_CUE = mk.BASELINE_CUE
REPEAT_RE = mk.REPEAT_RE
METRIC_CUE = mk.METRIC_CUE
STAT_CUE = mk.STAT_CUE
REPRO_CUE = mk.REPRO_CUE

# 对照名里常见但不能当"某个对照方法"的泛词
BAD_BASELINE = {"model", "models", "method", "methods", "approach", "approaches", "baseline",
                "baselines", "control", "our", "the", "this", "these", "those", "existing",
                "prior", "previous", "their", "its", "and", "with", "without", "vs", "versus",
                "compared", "comparison", "study", "work", "paper", "results"}


def load_unreadable(ctx):
    """没有任何可读文本 → 给出 reason（区分「读不出来」与「就是空的」）。"""
    mats = ctx.get("materials") or []
    if not mats:
        return "no_material", "没有找到任何材料文件。请确认 materials/ 目录或 case.json 里的材料路径。"
    bad = [m for m in mats if not (m.get("text") or "").strip()]
    if not bad:
        return None, None
    broke = [m for m in bad
             if any(k in (m.get("note") or "") for k in ("failed", "undecodable", "unreadable"))]
    if broke:
        notes = ",".join(sorted({(m.get("note") or "") for m in broke}))
        return "unreadable_material", "材料存在但读不出文字层（%s）。若为扫描件请提供文本版。" % notes
    names = ",".join(sorted({(m.get("name") or "") for m in bad}))
    return "empty_material", "材料文件没有内容（%s）。" % names


def build_units(indexed):
    """把材料拆成行级单元与句子级单元，供后续引用定位。"""
    lines, facts = [], []
    for mat in indexed:
        text = mat["text"] or ""
        if mat["kind"] in ("config", "log", "code"):
            body = mk.norm_preserve_lines(text)
        else:
            body = mk.norm(text)
        mat["text_norm"] = body
        for ln_no, line in enumerate(body.split("\n"), 1):
            if line.strip():
                lines.append({"src_id": mat["src_id"], "name": mat["name"], "kind": mat["kind"],
                              "line": ln_no, "text": line.strip()})
        for sn, sent in enumerate(mk.sentences(body), 1):
            if len(sent) < 15:
                continue
            prot = mk.protected_spans(sent)
            score = 0.0
            score += 0.5 if prot["number"] else 0.0
            score += 0.3 if prot["path"] else 0.0
            score += 0.3 if prot["cmd"] else 0.0
            score += 0.2 if prot["version"] else 0.0
            score += 0.4 if mk.LIMIT_CUE.search(sent) else 0.0
            score += 0.3 if mk.METRIC_CUE.search(sent) else 0.0
            score += 0.3 if mk.BASELINE_CUE.search(sent) else 0.0
            score += 0.2 if mk.REPRO_CUE.search(sent) else 0.0
            score += 0.3 if STEP_CUES.search(sent) else 0.0
            score += 0.2 if DECISION_CUE.search(sent) else 0.0
            facts.append({
                "fact_id": "f-%s-s%03d" % (mat["src_id"], sn), "src_id": mat["src_id"],
                "name": mat["name"], "kind": mat["kind"], "text": sent,
                "chars": len(sent), "score": round(min(1.0, score), 3),
                "protected": {k: v for k, v in prot.items() if v},
                "cues": {
                    "limit": bool(mk.LIMIT_CUE.search(sent)),
                    "metric": bool(mk.METRIC_CUE.search(sent)),
                    "stat": bool(mk.STAT_CUE.search(sent)),
                    "baseline": bool(mk.BASELINE_CUE.search(sent)),
                    "repro": bool(mk.REPRO_CUE.search(sent)),
                    "decision": bool(mk.DECISION_CUE.search(sent)),
                },
            })
    return lines, facts


def extract_params(indexed, lines):
    """从配置文件与日志抽参数（确定性），并把正文里的 `key = value` 也纳入候选。"""
    rows = []
    for mat in indexed:
        if mat["kind"] == "config":
            for r in mk.parse_config(mat["text_norm"], source=mat["name"]):
                r["src_id"] = mat["src_id"]
                r["material_kind"] = "config"
                rows.append(r)
        if mat["kind"] == "log":
            for r in mk.parse_log_kv(mat["text_norm"], source=mat["name"]):
                r["src_id"] = mat["src_id"]
                r["material_kind"] = "log"
                rows.append(r)
        if mat["kind"] == "code":
            # 代码里只认明确声明的参数：环境变量与 argparse 默认值。
            # 泛化的 `key = value` 会把 ap/out/__name__ 这类中间变量误当超参数。
            for m in mk.ENV_PARAM_RE.finditer(mat["text_norm"]):
                rows.append({"key": m.group("k"), "key_path": m.group("k"), "value": m.group("v"),
                             "line": mat["text_norm"][:m.start()].count("\n") + 1,
                             "source": mat["name"], "src_id": mat["src_id"], "material_kind": "code"})
            for m in mk.ARGPARSE_DEFAULT_RE.finditer(mat["text_norm"]):
                rows.append({"key": m.group("k"), "key_path": m.group("k"), "value": m.group("v"),
                             "line": mat["text_norm"][:m.start()].count("\n") + 1,
                             "source": mat["name"], "src_id": mat["src_id"], "material_kind": "code"})
    for ln in lines:
        if ln["kind"] == "code":
            continue
        for m in mk.PARAM_RE.finditer(ln["text"]):
            key = m.group("key")
            if "." in key and not re.match(r"^[a-z_]", key):
                continue
            if mk.is_junk_param_key(key, m.group("val")):
                continue
            rows.append({"key": key, "key_path": key, "value": m.group("val"),
                         "line": ln["line"], "source": ln["name"], "src_id": ln["src_id"],
                         "material_kind": ln["kind"], "from_text": True})
    kept, seen = [], {}
    for r in rows:
        key = (r.get("key") or "").strip()
        if mk.is_junk_param_key(key, r.get("value")):
            continue
        val = mk.clean_value(str(r.get("value", "")).strip())
        if val == "":
            continue
        # 同一来源同一行若既有结构化解析又有正文扫描，保留结构化那一条：
        # 正文扫描按逗号截断，会把 CUDA_VISIBLE_DEVICES=0,1 读成 0，凭空造出参数冲突。
        sig = (key.lower(), r.get("src_id"), r.get("line"))
        prev = seen.get(sig)
        if prev is not None:
            if r.get("from_text"):
                continue
            if not prev.get("from_text"):
                continue
            kept = [x for x in kept if x is not prev]
        seen[sig] = r
        kept.append(r)
    out = []
    for r in kept:
        key = (r.get("key") or "").strip()
        val = mk.clean_value(str(r.get("value", "")).strip())
        unit = ""
        um = re.search(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(%s)\s*$" % mk.NUM_UNITS, val)
        if um:
            unit = um.group(2)
        out.append({
            "param_id": "", "key": key, "key_path": r.get("key_path") or key,
            "value": val, "unit": unit, "section": r.get("section") or "",
            "source": r.get("source") or "", "src_id": r.get("src_id") or "",
            "line": r.get("line") or 0, "material_kind": r.get("material_kind") or "",
            "origin": "text_scan" if r.get("from_text") else "structured",
            "status": "candidate",
        })
    for i, r in enumerate(sorted(out, key=lambda x: (x["key"].lower(), str(x["value"]))), 1):
        r["param_id"] = "p%03d" % i
    return out


def extract_settings(indexed, lines, facts):
    versions, seeds, hw, envs, repeats = [], [], [], [], []
    for mat in indexed:
        for m in mk.VERSION_RE.finditer(mat["text_norm"]):
            versions.append({"name": m.group("name").lower(), "version": m.group("ver"),
                             "src_id": mat["src_id"], "source": mat["name"]})
        for m in mk.SEED_RE.finditer(mat["text_norm"]):
            seeds.append({"seed": m.group("seed"), "src_id": mat["src_id"], "source": mat["name"]})
        for m in mk.HW_RE.finditer(mat["text_norm"]):
            hw.append({"raw": m.group(0).strip(), "card": m.group("card"), "count": (m.group("count") or "").strip(),
                       "memory": (m.group("mem") or ""), "src_id": mat["src_id"], "source": mat["name"]})
        for ln in lines:
            if ln["src_id"] != mat["src_id"]:
                continue
            for m in re.finditer(r"\b(?:CUDA_VISIBLE_DEVICES|OMP_NUM_THREADS|PYTHONPATH|HF_HOME|"
                                 r"TRANSFORMERS_CACHE|WANDB_|NCCL_|MKL_NUM_THREADS)\s*=\s*(\S+)", ln["text"]):
                envs.append({"raw": m.group(0), "src_id": ln["src_id"], "source": ln["name"], "line": ln["line"]})
    for f in facts:
        for m in REPEAT_RE.finditer(f["text"]):
            repeats.append({"raw": m.group(0).strip(), "n": m.group("n"), "src_id": f["src_id"], "fact_id": f["fact_id"]})
    dedup = lambda rows, key: list({key(r): r for r in rows}.values())  # noqa: E731
    return {
        "versions": dedup(versions, lambda r: (r["name"], r["version"])),
        "seeds": dedup(seeds, lambda r: (r["seed"], r["src_id"])),
        "hardware": dedup(hw, lambda r: mk.flat(r["raw"]).lower()),
        "env_vars": dedup(envs, lambda r: r["raw"]),
        "repeats": dedup(repeats, lambda r: mk.flat(r["raw"]).lower()),
    }


def extract_splits(indexed):
    """划分线索：只认比例式与明确的百分比占比。

    早先的宽口径会把「训练 12 个 epoch」「test 8」这种无关数字当成划分规模，
    于是核验器会拿它去正文里找，凭空报 split_mismatch。
    """
    out, seen = [], set()
    kw = re.compile(r"(?:划分|比例|split|ratio|训练|验证|测试|train(?:ing)?|val(?:id(?:ation)?)?|"
                    r"test(?:ing)?|dev)", re.I)
    time_like = re.compile(r"^\d{2}:\d{2}:\d{2}$")
    for mat in indexed:
        for m in mk.SPLIT_RATIO_RE.finditer(mat["text_norm"]):
            raw = m.group("ratio") or m.group("ratio2") or ""
            ratio = re.sub(r"\s+", "", raw)
            if not ratio or ratio in seen:
                continue
            if time_like.match(ratio):
                continue  # 09:12:03 是日志时间戳，不是划分比例
            ctx = mat["text_norm"][max(0, m.start() - 30):m.end() + 30]
            if not kw.search(ctx):
                continue  # 没有划分语境的 2:3 多半是别的东西
            if ratio in seen:
                continue
            seen.add(ratio)
            head = mat["text_norm"][max(0, m.start() - 40):m.end() + 20]
            out.append({"part": "ratio", "value": ratio, "quote": mk.norm(head),
                        "src_id": mat["src_id"], "source": mat["name"]})
        for m in re.finditer(r"(?P<part>train|training|val|valid|validation|dev|test|testing|训练|验证|测试)"
                             r"\s*(?:set|集|split|划分|部分)?\s*(?:占|:|=|为)?\s*(?P<pct>\d{1,3}(?:\.\d+)?)\s*%",
                             mat["text_norm"], re.I):
            tag = "%s=%s%%" % (m.group("part").lower(), m.group("pct"))
            if tag in seen:
                continue
            seen.add(tag)
            out.append({"part": m.group("part").lower(), "value": "%s%%" % m.group("pct"),
                        "optional": True, "src_id": mat["src_id"], "source": mat["name"]})
    return out


def extract_datasets(indexed, lines):
    out, seen = [], set()
    for mat in indexed:
        for m in mk.DATASET_RE.finditer(mat["text_norm"]):
            name = m.group("name")
            if len(name) < 3 or name.lower() in ("the", "this", "table", "figure", "version"):
                continue
            if not name[-1].isalnum():
                continue
            key = (name.lower(), m.group("ver"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "version": m.group("ver"), "src_id": mat["src_id"], "source": mat["name"]})
    for ln in lines:
        for m in re.finditer(r"\b(?P<name>[A-Za-z][\w\-]{2,30}(?:[-_][A-Za-z0-9]+)*)\s*\((?P<role>train|val|valid|test|dev|训练|验证|测试)[^)]{0,20}\)", ln["text"], re.I):
            key = (m.group("name").lower(), m.group("role").lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": m.group("name"), "version": "", "role": m.group("role").lower(),
                        "src_id": ln["src_id"], "source": ln["name"], "line": ln["line"]})
    return out


def extract_steps(indexed, lines):
    out = []
    for mat in indexed:
        body = mat["text_norm"]
        if mat["kind"] == "code":
            for m in CODE_STEP.finditer(body):
                line = body[:m.start()].count("\n") + 1
                out.append({"text": "函数 %s" % m.group("name"), "name": m.group("name"), "kind": "code_function",
                            "src_id": mat["src_id"], "source": mat["name"], "line": line, "quote": body[m.start():m.start() + 90]})
            for m in CODE_STEP_ZH.finditer(body):
                line = body[:m.start()].count("\n") + 1
                out.append({"text": m.group("name").strip(), "kind": "code_comment",
                            "src_id": mat["src_id"], "source": mat["name"], "line": line, "quote": m.group(0)[:90]})
        for m in STEP_CUES.finditer(body):
            line = body[:m.start()].count("\n") + 1
            tail = body[m.end():m.end() + 120].split("\n")[0].strip()
            txt = (m.group(0).strip() + " " + tail).strip()
            if len(txt) < 6:
                continue
            out.append({"text": txt[:160], "kind": "listed_step", "src_id": mat["src_id"],
                        "source": mat["name"], "line": line, "quote": txt[:160]})
        for m in LOG_STAGE.finditer(body):
            line = body[:m.start()].count("\n") + 1
            msg = "%s %s" % (m.group("tag").strip(), m.group("msg").strip())
            out.append({"text": msg[:160], "kind": "log_stage", "src_id": mat["src_id"],
                        "source": mat["name"], "line": line, "quote": m.group(0).strip()[:160]})
        for m in mk.CMD_RE.finditer(body):
            line = body[:m.start()].count("\n") + 1
            out.append({"text": m.group("cmd").strip()[:200], "kind": "command", "src_id": mat["src_id"],
                        "source": mat["name"], "line": line, "quote": m.group("cmd").strip()[:200]})
        for ln in lines:
            if ln["src_id"] != mat["src_id"]:
                continue
            for m in mk.PATH_RE.finditer(ln["text"]):
                if not m.group("path").lower().endswith(".py"):
                    continue
                out.append({"text": "脚本 %s" % m.group("path"), "kind": "script_path", "src_id": ln["src_id"],
                            "source": ln["name"], "line": ln["line"], "quote": ln["text"][:160]})
    seen, uniq = set(), []
    for i, s in enumerate(out, 1):
        sig = (s["kind"], mk.flat(s["text"]).lower())
        if sig in seen or len(s["text"]) < 4:
            continue
        seen.add(sig)
        s["step_id"] = "s%03d" % (len(uniq) + 1)
        s["has_input_cue"] = bool(INPUT_CUE.search(s["text"]))
        s["has_output_cue"] = bool(OUTPUT_CUE.search(s["text"]))
        s["has_decision_cue"] = bool(DECISION_CUE.search(s["text"]))
        uniq.append(s)
    return uniq


def extract_baselines(facts):
    out, seen = [], set()
    for f in facts:
        for m in BASELINE_CUE.finditer(f["text"]):
            name = (m.group("name") or m.group("name2") or m.group("name3") or "").strip()
            if len(name) < 3 or name.lower() in BAD_BASELINE:
                continue
            k = name.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append({"name": name, "fact_id": f["fact_id"], "src_id": f["src_id"],
                        "quote": f["text"][:160], "metric": bool(METRIC_CUE.search(f["text"])),
                        "stat": bool(STAT_CUE.search(f["text"]))})
    return out


def extract_limits(facts):
    """限制与不确定：命中限制线索，或命中笼统措辞（有待进一步研究/未来工作）的句子。"""
    out = []
    for f in facts:
        hit = mk.LIMIT_CUE.search(f["text"])
        vague = mk.VAGUE_LIMIT.search(f["text"])
        if not hit and not vague:
            continue
        out.append({"fact_id": f["fact_id"], "src_id": f["src_id"], "quote": f["text"][:200],
                    "concrete": bool(hit) and not vague and bool(mk.COND_CUE.search(f["text"])),
                    "vague": bool(vague)})
    return out


def build_checklist(params, settings, splits, datasets, steps, baselines, limits):
    status = {}
    status["steps"] = {"found": bool(steps), "count": len(steps),
                       "detail": "候选步骤 %d 条（代码函数/编号步骤/日志阶段/命令/脚本路径）" % len(steps)}
    hardware = settings.get("hardware") or []
    versions = settings.get("versions") or []
    seeds = settings.get("seeds") or []
    status["settings"] = {"found": bool(hardware or versions or seeds), "count": len(hardware) + len(versions) + len(seeds),
                          "detail": "硬件 %d / 软件版本 %d / 随机种子 %d / 重复次数 %d"
                                    % (len(hardware), len(versions), len(seeds), len(settings.get("repeats") or [])),
                          "missing_parts": [k for k, v in (("hardware", hardware), ("versions", versions), ("seeds", seeds))
                                            if not v]}
    status["params"] = {"found": bool(params), "count": len(params),
                        "detail": "候选参数 %d 条（配置文件/日志/正文键值）" % len(params)}
    status["datasets"] = {"found": bool(datasets or splits), "count": len(datasets),
                          "detail": "数据集候选 %d 条 / 划分线索 %d 条" % (len(datasets), len(splits)),
                          "missing_parts": [k for k, v in (("datasets", datasets), ("splits", splits)) if not v]}
    status["baselines"] = {"found": bool(baselines), "count": len(baselines),
                           "detail": "对照候选 %d 条" % len(baselines),
                           "missing_parts": ([] if any(b.get("metric") for b in baselines) else ["metrics"])}
    repro = [f for f in limits if not f.get("vague")]
    status["repro_limits"] = {"found": bool(limits), "count": len(limits),
                              "detail": "限制线索 %d 条（其中含具体条件的 %d 条）" % (len(limits), len(repro))}
    return status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-chars", type=int, default=400000)
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)

    def fail(reason, detail="", hint=""):
        mk.dump_json(os.path.join(out, "prep.json"), {
            "schema": "method-prep/1.0", "tool": VERSION, "status": "failed",
            "reason": reason, "detail": detail, "hint": hint, "next_step": [],
        })
        print(mk.pjson({"status": "failed", "reason": reason, "detail": detail, "hint": hint}))
        return 2

    try:
        case, ctx = mk.load_case(a.case)
    except Exception as e:
        return fail("no_case", "case.json 读取失败：%s" % e, "确认 --case 指向可读的 /input/case.json")

    reason, detail = load_unreadable(ctx)
    if reason:
        hint = {"no_material": "把材料放进 materials/ 目录，或在 case.json 里用 material_files/materials 列出路径。",
                "unreadable_material": "材料读不出文字层；请提供文本或带文字层的 PDF。",
                "empty_material": "材料文件是空的；补上正文内容再跑。"}.get(reason, "")
        return fail(reason, detail, hint)

    indexed = mk.material_index(ctx["materials"])
    total = sum(m["chars"] for m in indexed)
    if total < 40:
        return fail("no_paragraphs", "材料总字符数只有 %d，剩不下可用的正文（多半只有标题或残片）。" % total,
                    "确认材料里包含方法与实验正文，而不是只有标题。")
    if total > a.max_chars:
        ctx["warnings"].append("材料总字符 %d 超过 --max-chars %d，已按上限截断。" % (total, a.max_chars))
        for m in indexed:
            m["text"] = m["text"][: max(1000, a.max_chars // max(1, len(indexed)))]

    lines, facts = build_units(indexed)
    if not lines and not facts:
        return fail("no_paragraphs", "材料里没有任何可用的行/句子。", "确认材料是文本内容而非纯二进制。")

    params = extract_params(indexed, lines)
    settings = extract_settings(indexed, lines, facts)
    splits = extract_splits(indexed)
    datasets = extract_datasets(indexed, lines)
    steps = extract_steps(indexed, lines)
    baselines = extract_baselines(facts)
    limits = extract_limits(facts)
    conflicts = mk.param_conflicts(params)
    checklist = build_checklist(params, settings, splits, datasets, steps, baselines, limits)

    gaps = []
    for key, label, _desc in ELEMENTS:
        st = checklist.get(key) or {}
        if not st.get("found"):
            gaps.append({"gap_id": "g-%s" % key, "element": key, "label": label,
                         "question": "材料里未见「%s」相关信息，请向作者确认或明确标注为未报告。" % label,
                         "severity": "high" if key in ("settings", "params") else "medium"})
        for part in st.get("missing_parts") or []:
            gaps.append({"gap_id": "g-%s-%s" % (key, part), "element": key, "label": label,
                         "question": "「%s」的 %s 部分在材料里没有线索，请确认。" % (label, part),
                         "severity": "medium"})
    for c in conflicts:
        gaps.append({"gap_id": "g-conflict-%s" % c["key"], "element": "params", "label": "参数与来源",
                     "question": "参数 `%s` 在不同来源出现不同取值（%s），请确认以哪一处为准。"
                                 % (c["key"], " / ".join(str(v["value"]) for v in c["values"])),
                     "severity": "high", "conflict": c})

    # ---- 落盘
    mk.dump_json(os.path.join(out, "sources.json"), {
        "schema": "method-sources/1.0",
        "case_id": ctx["case_id"],
        "materials": [{k: v for k, v in m.items() if k != "text"} for m in indexed],
        "total_chars": total,
        "audience": ctx.get("audience"), "genre": ctx.get("genre"),
        "language": ctx.get("language"), "format_constraints": ctx.get("format_constraints"),
        "warnings": ctx["warnings"] + (ctx.get("notes") or []),
    })
    mk.dump_jsonl(os.path.join(out, "facts.jsonl"), sorted(facts, key=lambda f: -f["score"]))
    with io.open(os.path.join(out, "params_candidates.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("param_id\tkey\tkey_path\tvalue\tunit\tsource\tsrc_id\tline\tmaterial_kind\torigin\tstatus\n")
        for r in params:
            fh.write("\t".join(str(r.get(k, "")) for k in
                               ("param_id", "key", "key_path", "value", "unit", "source", "src_id", "line",
                                "material_kind", "origin", "status")) + "\n")
    mk.dump_json(os.path.join(out, "settings_candidates.json"), settings)
    mk.dump_json(os.path.join(out, "splits_candidates.json"), {"splits": splits})
    mk.dump_jsonl(os.path.join(out, "datasets_candidates.jsonl"), datasets)
    mk.dump_jsonl(os.path.join(out, "steps_candidates.jsonl"), steps)
    mk.dump_jsonl(os.path.join(out, "baselines_candidates.jsonl"), baselines)
    mk.dump_jsonl(os.path.join(out, "limits_candidates.jsonl"), limits)
    mk.dump_json(os.path.join(out, "conflicts.json"), {"conflicts": conflicts})
    mk.dump_json(os.path.join(out, "elements_checklist.json"), {
        "schema": "method-elements/1.0", "elements": checklist,
        "definitions": [{"key": k, "label": l, "definition": d} for k, l, d in ELEMENTS],
    })
    mk.dump_json(os.path.join(out, "gap_candidates.json"), {"gaps": gaps})
    mk.dump_json(os.path.join(out, "context.json"), {
        "schema": "method-context/1.0", "case_id": ctx["case_id"], "case_path": ctx["case_path"],
        "contract": ctx["contract"], "task": (ctx.get("task") or "")[:2000],
        "audience": ctx.get("audience"), "genre": ctx.get("genre"), "language": ctx.get("language"),
        "materials": [{"src_id": m["src_id"], "name": m["name"], "kind": m["kind"], "chars": m["chars"]}
                      for m in indexed],
        "counts": {"params": len(params), "steps": len(steps), "facts": len(facts),
                   "datasets": len(datasets), "baselines": len(baselines), "limits": len(limits),
                   "splits": len(splits), "conflicts": len(conflicts)},
        "warnings": ctx["warnings"], "notes": ctx.get("notes") or [],
    })

    md = ["# 材料要素清单（method_prep 产出，供写作与核验使用）", ""]
    md.append("## 1. 材料")
    for m in indexed:
        md.append("- `%s` %s（%s，%d 字符，sha256_16 %s）" % (m["src_id"], m["name"], m["kind"], m["chars"], m["sha256_16"]))
    md += ["", "## 2. 六类要素齐备度"]
    for key, label, _d in ELEMENTS:
        st = checklist[key]
        md.append("- **%s**：%s —— %s" % (label, "有线索" if st["found"] else "未见线索", st["detail"]))
    md += ["", "## 3. 参数候选（写入 params.tsv 的原料）", "",
           "| param_id | key | value | unit | 来源 | 行 |", "|---|---|---|---|---|---|"]
    for r in params[:120]:
        md.append("| %s | `%s` | %s | %s | %s | %s |" % (r["param_id"], r["key_path"], r["value"], r["unit"], r["source"], r["line"]))
    if conflicts:
        md += ["", "## 4. 参数冲突（必须写进正文或追问清单）"]
        for c in conflicts:
            md.append("- `%s`：%s" % (c["key"], " / ".join("%s（%s）" % (v["value"], ", ".join(
                "%s:%s" % (s["source"], s["line"]) for s in v["sources"])) for v in c["values"])))
    md += ["", "## 5. 步骤候选"]
    for s in steps[:60]:
        md.append("- `%s` [%s] %s（%s:%s）" % (s["step_id"], s["kind"], s["text"], s["source"], s["line"]))
    md += ["", "## 6. 实验设置候选"]
    md.append("- 硬件：%s" % ("；".join(h["raw"] for h in (settings["hardware"] or [])[:20]) or "（未见）"))
    md.append("- 软件版本：%s" % ("；".join("%s %s" % (v["name"], v["version"]) for v in (settings["versions"] or [])[:20]) or "（未见）"))
    md.append("- 随机种子：%s" % ("；".join(s["seed"] for s in (settings["seeds"] or [])[:20]) or "（未见）"))
    md.append("- 环境变量：%s" % ("；".join(e["raw"] for e in (settings["env_vars"] or [])[:20]) or "（未见）"))
    md.append("- 重复次数线索：%s" % ("；".join(r["raw"] for r in (settings["repeats"] or [])[:20]) or "（未见）"))
    md += ["", "## 7. 数据集与划分"]
    for d in datasets[:40]:
        md.append("- %s（版本 %s）%s:%s" % (d["name"], d.get("version") or "未标", d["source"], d.get("line", "")))
    for s in splits[:40]:
        md.append("- 划分：%s = %s（%s）" % (s["part"], s["value"], s["source"]))
    md += ["", "## 8. 对照候选"]
    for b in baselines[:40]:
        md.append("- %s（指标线索 %s / 统计线索 %s）" % (b["name"], b["metric"], b["stat"]))
    md += ["", "## 9. 限制条件线索"]
    for l in limits[:40]:
        md.append("- [%s%s] %s" % ("具体" if l["concrete"] else "笼统", "，疑似套话" if l["vague"] else "", l["quote"][:160]))
    md += ["", "## 10. 追问候选（写进 gaps.json）"]
    for g in gaps[:60]:
        md.append("- (%s) %s" % (g["severity"], g["question"]))
    md += ["", "> 本文件由确定性脚本生成，**不含编造数值**；所有条目均可按 来源+行号 回查。"]
    mk.dump_text(os.path.join(out, "facts.md"), "\n".join(md) + "\n")

    mk.dump_json(os.path.join(out, "prep_check.json"), {
        "params_with_source": sum(1 for r in params if r["src_id"]),
        "params_conflicts": len(conflicts),
        "elements_present": [k for k, _l, _d in ELEMENTS if checklist[k]["found"]],
        "elements_absent": [k for k, _l, _d in ELEMENTS if not checklist[k]["found"]],
        "materials": len(indexed),
    })
    mk.dump_json(os.path.join(out, "prep.json"), {
        "schema": "method-prep/1.0", "tool": VERSION, "status": "ok",
        "reason": None,
        "next_step": [
            "1) 读 work/facts.md 与 work/params_candidates.tsv，理解材料里到底有什么、缺什么。",
            "2) 写 work/methods.md：方法步骤 / 实验设置 / 参数 / 数据集与划分 / 对照实验 / 复现与限制 六节。",
            "3) 写 work/params.tsv：参数表（param_id/key/value/unit/scope/source/line/status），正文数值必须与之一致。",
            "4) 写 work/elements.json：六类要素逐条给出自评齐备度与对应来源。",
            "5) 写 work/gaps.json：材料缺口与人工确认项（含参数冲突裁决）。",
            "6) 写 work/repro.json：复现清单（代码版本/环境/命令/数据获取）。",
            "7) 最后运行 method_assemble.py 做硬核验并产出交付物。",
        ],
        "counts": {"materials": len(indexed), "lines": len(lines), "facts": len(facts),
                   "params": len(params), "steps": len(steps), "datasets": len(datasets),
                   "baselines": len(baselines), "limits": len(limits), "splits": len(splits),
                   "conflicts": len(conflicts), "gaps": len(gaps)},
        "checklist": checklist,
        "warnings": ctx["warnings"],
    })
    print(mk.pjson({"status": "ok", "materials": len(indexed), "facts": len(facts), "params": len(params),
                    "steps": len(steps), "datasets": len(datasets), "baselines": len(baselines),
                    "limits": len(limits), "splits": len(splits), "conflicts": len(conflicts),
                    "elements_absent": [k for k, _l, _d in ELEMENTS if not checklist[k]["found"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
