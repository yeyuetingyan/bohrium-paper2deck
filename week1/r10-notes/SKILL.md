---
name: paper-notes
description: 把论文 PDF 变成与原文结构对齐、每条可回查的结构化笔记（论文卡片、章节笔记、研究问题、数据、前提条件、含数值的关键发现、局限、术语表、检索索引）。当任务要求"文献总结""结构化笔记""论文卡片""章节摘要""知识点提取""证据链接""可检索笔记"或要求为后续写作/综述准备可复用笔记时使用。
---

# PaperNotes：与原文结构对齐的可回查笔记

读一篇论文并写笔记，难的不是压缩，而是四件事：**对得上**（骨架跟着论文自己的章节走）、**留得住**（研究问题、数据、方法条件、发现、局限都在）、**找得回**（每条能指到页码与块号）、**用得上**（能检索、能比较、能接着写）。本 Skill 只做这四件事，不做领域判断，也不替读者下结论。

## 何时触发

- 输入是论文 PDF，要求生成摘要、笔记、卡片、章节总结、知识点清单；
- 要求"每条结论有出处""能回到原文核对""笔记可检索"；
- 评测环境给出 `/input/case.json`（可能含 `paper_path`、`max_pages`、`output_contract`）。

## 输入

- `/input/case.json`：字段名不固定，`paper_path` / `pdf` / `input.paper` 均可；`max_pages` 限页数；`output_contract` 是需要回填的字段名。
- 同目录 `task.md`：以题面为准。
- 找不到 `case.json` 时，脚本在 `/input` 下取第一个 `.pdf`。

不依据 `case.json` 的领域标签推断内容；只读实际文件。

## 输出（写到 `/app/output/`）

```
output/
├── notes.md        人读版：论文卡片 / 结构树 / 章节笔记 / 关键发现 / 条件 / 局限 / 术语
├── notes.json      机器可读：sections[] 与 fields{}，每条含 anchor
├── anchors.json    全部笔记的锚点（page / block / quote / hash），供逐条回查
├── concepts.json   术语与缩写（首次出现位置 + 频次）
├── index.json      倒排索引（词 → 块号），供后续检索
├── check.json      自检：锚点命中率、字段覆盖、结构识别、扫描页
└── result.json     case_id / status / primary_result / evidence / uncertainty / artifacts
```

## 流程

```bash
SKILL=/skills/weekly-skill          # 或本目录
python "$SKILL/scripts/build_notes.py" --case /input/case.json --out /app/output
```

一次调用完成解析、切章、抽字段、建锚点、写索引与自检。参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--case` | `/input/case.json` | 不存在时退化到 `--pdf` 或 `/input` 下首个 PDF |
| `--pdf` | 由 case 解析 | 直接指定论文 |
| `--out` | `/app/output` | 输出目录 |
| `--max-pages` | 80 | 超出截断并在 `uncertainty` 说明 |

## 规则（评分要点）

1. **章节只来自论文本身**：标题层级取自版式与编号（`3.2.1` 为三级）；公式行、项目符号行、句号结尾的正文首句、摘要里的单个加粗词都不算标题；题名/作者区不建章节、不产笔记。
2. **笔记是原文摘录，不是转写**：每条都是句中逐字文本 + 页码 + 块号；`anchor_check` 逐条验证 quote 能在对应块中命中（连字 ﬁ/ﬂ、软连字符、不间断空格已归一）。版式断块切出的半句碎片（小写起头、或没有句末标点）不进笔记。
3. **五类字段各有线索词**：研究问题（we propose / 本文研究…）、数据（dataset / 语料库…）、前提与条件（assume / 批大小 / 预算 / 假设…）、发现（数值 + 比较词）、局限（limitation / future work / 局限…）。线索词是中英双语，命中与否写入 `check.json.field_coverage`。
4. **参考文献与致谢不产笔记**：记入 `check.json` 的 `skipped`，避免文献表污染笔记。
5. **数值不认引用编号**：抽数值前先去掉 `[13]` 这类引用标记，避免把文献序号当成实验指标；表格题注句不当作发现。
6. **无标题论文不硬造结构**：全文没有可识别标题时，输出单一节并标记 `structure=false`，在 `uncertainty` 写明。
7. **诚实边界**：扫描件（无文字层）直接 `status=failed` 并提示需 OCR；加密 PDF `status=failed`；页数截断记入 `warnings`。

## 证据与回查

每条笔记形如：

```json
{"text": "Our model achieves 28.4 BLEU ...", "role": "result",
 "anchor": {"page": 1, "block": "p1b25", "quote": "Our model achieves 28.4 BLEU ...", "hash": "9f2c..."}}
```

回查方式：按 `page` 打开 PDF，用 `quote` 检索；`block` 是该页第几个正文块，`hash` 是块文本前 16 位 SHA-256，可用于判断笔记是否被改动过。

## 异常处理

| 情况 | 处理 |
|---|---|
| 加密 PDF | `status=failed`，`reason=encrypted_pdf` |
| 无文字层 / 扫描页 | `status=failed`（全文无字）或 `status=partial` + `uncertainty` 标页码 |
| 无标题 | 单节输出，`structure=false`，不编造章节名 |
| 双栏错序 | 解析层已按栏序重排；仍错时 `check.json` 的块序可复核 |
| 字段缺失 | `field_coverage` 记 false 并写 `uncertainty`，不用空话填充 |
| `case.json` 缺失 | 退化到 `/input` 首个 PDF；再找不到 `status=failed` |

## 自检

`check.json` 应满足：`anchor_valid == anchor_checked`（允许万分之几的连字差异并在 `anchor_invalid_examples` 列出）、`field_coverage.structure` 为 true（除非论文确实无标题）、`scanned_pages` 为空；`notes.md` 的章节顺序应与论文目录一致。

## 最小示例

仓库不放二进制样例（平台预检只接受 UTF-8 文本），演示论文现场生成：

```bash
python examples/make_sample_pdf.py examples/sample.pdf
python scripts/build_notes.py --case examples/example_case.json --out /tmp/demo
```

示意输出见 `examples/expected_shape.json`（**示例数据，不是正式案例结果**）。

## 限制

- 笔记条目是**原文句子的摘录**，不做同义改写；需要浓缩时由上层 Agent 在引用这些条目的前提下自行概括；
- 角色标签（目的/方法/结果/局限）按线索词给出，是候选而非判定，`notes.md` 已注明需复核；
- 数学公式只按文本保留，公式内的记号不解释；
- 表格与图的正文不进入笔记，只记录题注（`notes.json.captions`）；
- 章节切分依赖版式标题；纯排版无标题的旧扫描论文只能给出单节结构。
