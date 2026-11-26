---
name: paper-translate
description: 把科研论文/材料翻译成目标语言，交付段落级双语对照、锁定术语表与译文核验清单。先按语义边界切段并抽取候选术语，锁定译名后逐段翻译（携带上下文），再机械核验数字单位、引用标记、图表公式编号、否定与限定是否与原文一致。当任务要求"文献翻译""双语对照""全文翻译""术语一致""译名统一""译文核验""翻译质检""段落对齐翻译"时使用。
---

# PaperTranslate：术语锁定的段落级双语对照翻译

翻译科研文献，难的不是把句子说顺，而是四件事：**术语稳**（同一术语在标题、摘要、正文、图注里始终同一译名，术语表是被执行的而不是写在提示里的）、**段落全**（跨页跨栏跨章节不漏段、不重复、不错位，段号与原文一一对应）、**关系准**（指代、否定与限定、因果让步、数字单位、公式与文献编号与原文一致）、**可核验**（每段能指回原文并说明译法依据，译不准的明确标注）。本 Skill 只做这四件事，不做领域判断，也不替读者改写结论。

## 何时触发

- 输入是论文 PDF（或 txt/md）并要求翻译、双语对照、译文质检；
- 要求"术语统一""译名锁定""段落不漏""译文可核对""标注不确定处"；
- 评测环境给出 `/input/case.json`（可能含 `paper_path`、`target_language`、`max_pages`、`output_contract`）。

## 输入

- `/input/case.json`：字段名不固定，`paper_path` / `pdf` / `input.paper` 均可；`target_language` / `language` / `lang` 指定目标语言（缺省 `zh`）；`max_pages` 限页数；`output_contract` 是需要回填的字段名。
- 同目录 `task.md`：以题面为准。
- 找不到 `case.json` 时，脚本在 `/input` 下取第一个 `.pdf`，再退化到 `.md` / `.txt`。
- 不依据 `case.json` 的领域标签推断内容；只读实际文件。

## 输出（写到 `/app/output/`）

```
output/
├── bilingual.md      段落级双语对照：段号 / 页码 / 类型 / 原文 / 译文 / 译法依据 / 待确认
├── translation.zh.md 纯译文（保留段号，便于通读）
├── translation.json  段级结构（机器可读，含每段核验结果与状态）
├── segments.json     分段表：段号↔页码↔原文↔不变量，供独立复核
├── glossary.tsv      锁定后的术语表（term / zh / 出现次数 / 页码 / 状态）
├── check.json        核验汇总：覆盖率、不变量通过率、术语一致率、否定保留率、待确认清单
├── review.md         待人工确认清单（人读版）
└── result.json       case_id / status / primary_result / evidence / uncertainty / artifacts
```

## 三步流程

```bash
SKILL=/skills/weekly-skill          # 或本目录
# 1) 切段 + 抽候选术语（确定性，无模型调用）
python "$SKILL/scripts/translate_prep.py" --case /input/case.json --out /app/work

# 2) 翻译（由 Agent 完成，见下节"翻译协议"）：
#    读 /app/work/segments.md，锁定 /app/work/glossary_draft.tsv 的 zh 列，
#    逐段翻译并写入 /app/work/translations.json

# 3) 装配 + 核验 + 出结果（确定性，无模型调用）
python "$SKILL/scripts/translate_assemble.py" --case /input/case.json \
    --segments /app/work/segments.json --translations /app/work/translations.json \
    --glossary /app/work/glossary_draft.tsv --out /app/output
```

若第 3 步 `check.json` 里 `unresolved` 非空，按 `review.md` 修 `translations.json` 对应段后**重跑第 3 步**（不用重新切段）。

| 脚本 | 参数 | 默认 | 说明 |
|---|---|---|---|
| `translate_prep.py` | `--case` | `/input/case.json` | 不存在时退化到 `--pdf` |
| | `--pdf` | 由 case 解析 | 直接指定材料（PDF / txt / md） |
| | `--out` | `/app/work` | 中间产物目录 |
| | `--tgt-lang` | `zh` | 目标语言 |
| | `--max-pages` | 60 | 超出截断并记入 warnings |
| | `--glossary` | 无 | 已有术语表（`term<TAB>zh`），并入锁定 |
| `translate_assemble.py` | `--segments` | `/app/work/segments.json` | 第 1 步产物 |
| | `--translations` | 必填 | Agent 写的逐段译文 |
| | `--glossary` | 同目录自动查找 | `glossary_locked.tsv` → `glossary_draft.tsv` |
| | `--out` | `/app/output` | 结果目录 |

## 翻译协议（Agent 必须遵守）

1. **先锁术语，再动手翻译。** 打开 `/app/work/glossary_draft.tsv`，给每个候选术语补 `zh` 列。`status=suggested` 的必填；`needs_review` 的若判断不是术语，删掉该行或把 `zh` 留空即可（留空 = 不锁定）。**锁定后全篇不得换译名**；确需改，改完必须整篇重译并重跑核验。
2. **逐段翻译，不合并、不省略。** `segments.md` 里每个 `### [段号]` 都要有一条译文，段号原样照抄。段号格式：正文 `p<页>b<块>`、表格行 `p<页>t<表>r<行>`。
3. **携带上下文。** 段首若以 `*（当前章节：…）*` 提示章节，或该段在 `prep.json.self_check` 里被标为 `cross_page_continuation`，翻译时必须知道上一段说了什么（代词、省略主语、承接连词都靠它）。
4. **表格行按格翻译。** `kind=table_row` 的段以 ` | ` 分隔单元格，逐格翻译后仍用 ` | ` 连接，单元格个数不得变。
5. **不变量原样保留**（每段下方 `> 必须原样保留 —— …` 会列出来）：
   - 数字与单位：数值不得改动、不得省略单位；`28.4`、`512`、`ms`、`mol/L` 原样出现；
   - 引用标记：`[12]`、`[12-15]`、`(Smith et al., 2020)`、`\cite{key}` 原样保留，不得改写为"某研究"；
   - 图表公式编号：`Table 1` → `表 1`、`Fig. 3` → `图 3`、`Eq. (4)` → `式 (4)`，**编号数字必须一致**；
   - 公式片段：`x_i`、`\alpha`、`α`、`y = ax + b` 这类片段原样搬进译文，不翻译变量名；
   - 否定与限定：`not / no / never / without / only / may / suggest / assume` 这类词必须在译文里有对应（否则核验会报 `negation_lost`）。
6. **译不准就标注，不要含糊。** 术语无通行译法、原文残缺、公式为图片、指代无法确定时，在译文里保留原文并加方括号说明，同时在 `note` 字段写清依据。**不要编造数值、单位或结论。**
7. **写文件，不写对话。** 译文落到 `/app/work/translations.json`，格式三选一：

```json
{ "p1b4": "译文……",
  "p1b7": { "zh": "译文……", "note": "「only in structure」译为「仅在结构上」，保留限定范围" } }
```

也可写成 `{"translations": {...}}` 或 `{"segments": [{"seg_id": "p1b4", "zh": "…", "note": "…"}]}`。
文件必须是**合法 JSON**（UTF-8、无尾逗号、无未转义换行）。

## 规则（评分要点）

1. **段号就是契约**：段号由版面位置生成，与原文一一对应；核验脚本按段号比对，漏一段立刻报 `missing_translation`。
2. **表格区域只译一次**：表格区域已从正文里挖掉，单元格文本只作为 `table_row` 段出现，避免同一批数字被正文和表格各译一遍（重复翻译）。
3. **折行接续已合并**：版面折行切出的半句在切段阶段就并回上一段（`merged_from` 记录被并入的段号），所以"段"接近语义段落而非视觉行。
4. **术语一致率是算出来的**：对每个锁定术语，统计它在哪些段出现、译文里有没有出现对应译名，得出 `term_consistency_rate`；不达标会写进 `unresolved`。
5. **数字等价比对**：允许 `1.0≡1`、千分位与全角半角差异；但 `mL` 写成"毫升"、`512` 写成"五百一十二"会被判为不一致并列入待确认——这是刻意的严格口径，宁可让人看一眼。
6. **已是目标语言的段自动免译**：`cjk_ratio ≥ 0.5` 的段标记 `skip_translate`，原样保留并计入覆盖率，避免中英混排材料被"翻译"坏。
7. **核验只覆盖能机械比对的东西**：语义忠实度、学术语气、长句切分仍需人工复核，这一条写在 `result.json.uncertainty` 里，不冒充质量认证。

## 异常与降级

| 情况 | 处理 |
|---|---|
| 扫描件 / 页面无文字层 | 该页记入 `prep.json.skipped_pages` 与 `warnings`；整篇无文字层时 `prep.json.status=failed`，`segments.json` 为空 |
| 加密 PDF | `prep.json` 写 `{"status":"failed","reason":"encrypted_pdf","hint":"…解密后的副本…"}` 并**以退出码 2 结束**（不抛裸异常）；不尝试破解 |
| PDF 损坏 / 非 PDF | `reason=damaged_pdf`，同样退出码 2 |
| 材料是 txt / md | 按空行切段，直接进同一套装配与核验流程 |
| 原文已是目标语言 | 段标记免译，计入覆盖率，不重复翻译 |
| 页数超 `--max-pages` | 截断并在 `warnings` 与 `uncertainty` 说明"这是部分结果" |
| 表格抽取失败 | 表格区域不参与挖除，单元格文本作为正文段翻译，`warnings` 记录 |
| 译文 JSON 不合法 | 脚本报错退出（非 0），按报错行修正后重跑第 3 步 |
| 未译段 / 术语未锁定 | `status=partial`，`review.md` 列出段号与缺失术语 |

**材料不可读时怎么办**：`prep` 退出码 2 表示"没得翻，不是脚本坏了"——不要再重试同一份文件，直接让第 3 步照常运行（它会把 `prep.json` 的 `reason`/`hint`/`skipped_pages` 一路带进 `result.json.uncertainty`），交付一份诚实的 `status=failed` 结果，并在此说明需换可读副本或先做 OCR。

## 示例（可现场复现，非正式案例结果）

```bash
cd <skill 目录>
python examples/make_sample_paper.py /tmp/sample.pdf          # 合成演示论文（纯标准库）
python scripts/translate_prep.py --pdf /tmp/sample.pdf --out /tmp/work
python scripts/translate_assemble.py --segments /tmp/work/segments.json \
    --translations examples/example_translations.json \
    --glossary examples/example_glossary.tsv --out /tmp/out
# → status=ok，覆盖率 100%，不变量通过率 100%，术语一致率 100%
```

`examples/` 里的 `example_translations.json`、`example_glossary.tsv` 都是**演示样例**（原文由脚本现场生成，非任何真实论文），用来演示接口与全流程；正式案例的原文与答案由评测平台提供。

## 依赖

- Python ≥ 3.9（3.14 实测），仅用标准库 + `PyMuPDF`（`fitz`，用于 PDF 版面解析；缺失时 txt/md 路径仍可用）。
- 无网络依赖、无外部服务、无数据库；`glossary.tsv` 与 `segments.json` 都是纯文本，可进版本管理。
- 术语表格式见 `references/glossary-format.md`；核验口径与评分对应关系见 `references/verification-rules.md`。
