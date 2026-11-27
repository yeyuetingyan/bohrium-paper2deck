---
name: paper-method
description: 把实验材料（配置、日志、脚本、数据说明、事实底稿）写成期刊可投稿的「方法与实验」章节，并逐条核验：数值/单位/划分/版本/种子/命令是否与材料对得上、六类要素是否齐备、限制是否具体到失效场景。用于写 methods 章节、补实验设置、整理参数表、做复现清单，或检查已有章节里的数值与配置是否自洽。
---

# paper-method — 方法与实验章节写作与核验

一句话：**先把材料里的事实抽成清单，再写章节，最后用脚本把「写得全、写得准、做得着、说得住」逐条对账。**

## 何时触发

- 要把一份实验记录（`config.yaml` / `train.log` / 训练脚本 / 数据说明 / 事实底稿）写成方法章节。
- 要检查已有 methods 章节：数值是不是材料里的、划分和版本对不对、复现清单缺不缺项。
- 要整理参数表（每个参数的取值 + 来源文件与行号）。
- 要把「做得着」变成清单：版本、环境、种子、命令、检查点。

## 输入

`/input/case.json`（或 `--case` 指向的文件）里常见：

| 字段 | 说明 |
|---|---|
| `case_id` | 案例标识，会回填进 `result.json` |
| `task` | 任务描述 |
| `audience` / `genre` / `language` | 读者、体裁、语言 |
| `format_constraints` | 篇幅/格式约束 |
| `output_contract` | 期望产出的文件清单（脚本按它回填 `result.json`） |
| `material_files` / `materials` / `material` | 材料文件路径列表（相对 case 文件所在目录） |

材料按扩展名识别：`.yaml/.yml/.toml/.ini/.cfg/.json` → 配置；`.log/.out` → 日志；`.py/.sh/.ipynb` → 代码；`.md/.txt/.tex/.bib/.pdf` → 文档。**顺序很重要**：材料顺序决定 `fact_id` 编号，换顺序会让已有的 `source_map.json` 全部对不上。

## 三步流程

```bash
# 1) 确定性抽取：把材料变成可引用的行/句/参数/步骤/对照/限制清单
python scripts/method_prep.py --case /input/case.json --out /app/work

# 2) Agent 读 work/facts.md + work/*_candidates.*，写六份交付物（放进同一个 work 目录）
#    methods.md  params.tsv  elements.json  gaps.json  repro.json  source_map.json

# 3) 硬核验 + 导出
python scripts/method_assemble.py --case /input/case.json --work /app/work --out /app/output
```

第一步**不调用任何模型**，只做确定性抽取；第二步由 Agent 完成；第三步同样确定性，负责核验与导出。

## 写作协议（7 条）

1. **只写材料里有的数值。** 素材没给的参数不要凭经验补；必须补时写进 `gaps.json` 交作者确认。
2. **每个数值都要能指回来源。** `params.tsv` 的 `source` 列写「文件:行号」；正文数值必须能在材料里逐字找到。
3. **六类要素齐备**：方法步骤、实验设置、参数与来源、数据集与划分、对照实验、可复现性与限制条件——`elements.json` 逐类标明 `found`、`count`、所在小节与证据。
4. **每步写清输入/动作/输出/判断**，方法步骤里要出现可执行入口（脚本名或命令）。
5. **冲突不许静默吞掉。** 同名参数在配置与日志里取值不同（如 `batch_size` 32 vs 64）时，正文选定一个并写理由，同时在 `gaps.json` 里作为 `high` 冲突交作者确认。
6. **限制要具体到失效场景**：写「稀疏注意力在 batch_size < 8 时收益不稳定」，不写「性能有待进一步研究」。笼统说法要么改具体，要么明确标为待确认。
7. **只写文件，不写对话。** 章节正文进 `methods.md`，依据进 `source_map.json`，待确认进 `gaps.json`。

## 六份交付物（Agent 写，放进 `/app/work`）

| 文件 | 内容 |
|---|---|
| `methods.md` | 章节正文，六个小节：`1. Methods` / `2. Experimental Settings` / `3. Parameters` / `4. Datasets` / `5. Baselines` / `6. Reproducibility and Limitations` |
| `params.tsv` | 制表符表，表头 `name value unit source`；每行一个参数，来源写文件:行号 |
| `elements.json` | `{"schema":"method-elements/1.0","elements":{<六键>:{found,count,section,evidence,artifact}}}` |
| `gaps.json` | `{"schema":"method-gaps/1.0","gaps":[{gap_id,element,severity,question,action,conflict?}]}` |
| `repro.json` | `{"schema":"method-repro/1.0",versions,environment,seeds,commands,checkpoint,data_files}` |
| `source_map.json` | 每个正文段落一条：`{para_id,section,fact_ids[],evidence:[{fact_id,quote,source,line}]}`，引文逐字取自材料 |

## 输出（`/app/output`）

`methods.md`、`params.tsv`、`elements.json`、`gaps.json`、`repro.json`、`source_map.json`（核验后回写）、`consistency.json`（逐段一致性账）、`check.json`（`status/metrics/checks/issues/unresolved`）、`review.md`（人读报告）、`diff.md`（改动说明）、`result.json`（回填 `output_contract` 全部字段 + `case_id` + 证据 + 不确定性 + 产物哈希）。

## 核验口径（`check.json` 里的检查项）

- **数值**：`number_not_in_material`（正文出现材料外的数字）、`number_unit_mismatch`、`protected_token_not_in_material`（版本/路径/种子这类不可变成分改写）、`seed_missing`、`version_missing`。
- **参数**：`param_value_not_in_material`（数值型取值与材料数值集合精确比对）、`param_value_empty`、`param_row_invalid`、`param_candidates_uncovered`（配置里的参数没进表）、`param_source_missing`、`conflict_unreported` / `conflict_value_unwritten`。
- **划分/对照/限制**：`split_mismatch`、`split_terms_incomplete`、`baseline_not_in_text`、`baseline_not_in_material`、`limit_not_written`、`limit_too_vague`、`boilerplate_phrase`。
- **复现**：`repro_incomplete`（版本/环境/种子/命令四项）、`repro_number_not_in_material`、`repro_command_not_in_material`。
- **来源映射**：`source_fact_unknown`、`source_quote_not_found`、`source_quote_too_short`、`source_quote_not_minimal`、`paragraph_unmapped`。
- **结构**：`section_missing`、`section_too_short`、`section_order`、`no_headings`、`steps_too_few`、`step_no_command`、`step_no_io`、`element_absent_silent`、`element_not_declared`、`element_not_written`。

**状态**：无 high 且无 medium → `ok`；有 high → `partial`；正文缺失或为空 → `failed`（退出码 2）。

## 异常与降级

| 情形 | `prep.json` 的 reason | 退出码 |
|---|---|---|
| 找不到 case 文件 | `no_case` | 2 |
| 没有任何材料 | `no_material` | 2 |
| 材料文件是空的 | `empty_material` | 2 |
| 材料存在但读不出文字层（扫描件、坏文件） | `unreadable_material` | 2 |
| 有文字但凑不出正文（只剩标题/残片） | `no_paragraphs` | 2 |

**退出码 2 = 材料没得写，不是脚本坏了**，别对同一份材料反复重试；补齐材料再跑。`1` 表示参数或环境问题（例如 `--case` 指向不存在的路径）。

## 最小调用示例

包内 `examples/` 自带一套合成案例（`example_case.json` + `sample_materials/` 五份材料 + 六份示例交付物 + `example_rejected.jsonl` 九条反例）：

```bash
python scripts/method_prep.py --case examples/example_case.json --out /tmp/work
python scripts/method_assemble.py --case examples/example_case.json --work /tmp/work \
  --methods examples/example_methods.md --params examples/example_params.tsv \
  --elements examples/example_elements.json --gaps examples/example_gaps.json \
  --repro examples/example_repro.json --source-map examples/example_source_map.json --out /tmp/out
# → status ok / high 0 / medium 0 / low 1
```

示例输出是**示意**，用于演示字段形态，不代表任何真实实验数据。

## 依赖

- Python ≥ 3.9，脚本只用标准库。
- 材料里含 PDF 时需要 `PyMuPDF`（`pip install pymupdf`）；`examples/` 里的合成材料不需要。

## 参考

- `references/field-dictionary.md`：输入 / 中间产物 / 交付物的每个字段。
- `references/element-checklist.md`：六类要素的判定标准与常见缺口。
- `references/param-rules.md`：参数抽取、来源标注、冲突处置规则。
- `references/verification-rules.md`：全部检查项判据 + 刻意宽容处 + 刻意不检查处。
