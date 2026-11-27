---
name: paper-latex
description: 把论文的 LaTeX 源码改到能编译、能复现、能继续编辑：先静态核验（括号/环境/宏包顺序/表格列数/公式编号/交叉引用与文献），再由 Agent 逐处修好并登记改动，最后用本机 TeX 引擎真编译出 PDF 并解析日志定位文件与行号。触发词：LaTeX 编译报错、tex 改稿、交叉引用与 bib 不一致、表格列数不对、模板必填项缺失、复现编译环境、写 methods.tex、投稿前格式整理。
---

# paper-latex：LaTeX 写作与编译

把一份 LaTeX 工程改到「编译得通、改得对、交得可用、复现得了」，并且**每一步都有证据**：
静态核验给文件与行号，真编译给引擎与轮次，改动登记给 before/after 与理由。
**本机没有 TeX 引擎时如实标注 `compile.status = "not_attempted"`，绝不伪造编译成功或 PDF。**

## 何时触发

- 交来的 `.tex` 编不过，或编译日志里有一堆报错需要逐条定位到文件与行号。
- 公式、表格、交叉引用、文献条目对不上（编号乱、列数不符、`\cite` 找不到 bib 条目）。
- 要按某个期刊模板补齐必填项，或需要一份可复现的编译命令与轮次说明。
- 已经有 PDF 但拿不到源码，需要交回「可继续编辑的源码」。

## 输入

运行时读 `/input/case.json`：

| 字段 | 说明 |
|---|---|
| `case_id` | 案例标识，必须回填到 `result.json` |
| `material_files` | 材料文件列表（`.tex` / `.bib` / `.bbl` / `.cls` / `.sty` / 图片 / `factsheet.md`…）。**顺序即契约**，决定内部编号，不要重排 |
| `output_contract` | 期望产物字段（`revised` / `changes` / `diagnosis` / `checklist` / `source_map` / `check` / `review`…） |
| `style` / `engine` | 可选；`engine` 会覆盖自动推荐的引擎 |
| `format_constraints` | 可选；模板相关约束 |

材料顺序决定内部编号：`main.tex` 排在第 1 位时标签/公式编号从该文件起算。
**若把材料改成别的顺序，先前生成的 `source_map.json` 会全部对不上。**

## 三步流程

```bash
# 1) 静态核验：解析工程、清点编号与引用、给出行号级问题
python scripts/tex_prep.py --case /input/case.json --out /app/work

# 2) Agent 读 work/structure.md 与 work/issues.jsonl，写出六份交付物（放在 /app/work）
#    revised.tex / changes.jsonl / diagnosis.json / checklist.json / source_map.json / compile_plan.json

# 3) 核验 + 真编译（有引擎时）+ 导出
python scripts/tex_assemble.py --case /input/case.json --work /app/work --out /app/output
```

`tex_assemble.py` 参数：`--revised --changes --diagnosis --checklist --source-map --plan`
（默认在 `--work` 找），`--engine pdflatex|xelatex|lualatex`、`--max-passes`、`--timeout`、
`--no-compile`（只做静态核验，适合无引擎环境）。编译产物落在 `/app/output/_build/`。

## 写作协议（7 条）

1. **只改该改的**：能只改标点就别重写段落；每处改动都要能对上 `issues.jsonl` 里的一条问题或模板要求。
2. **数值不许动**：正文里的数字、单位、编号一律原样保留；确实是材料写错才改，且必须在 `changes.jsonl` 里说明并给出材料依据。
3. **引用与文献不许凭空补**：bib 里没有的 key，要么补进 `.bib`（材料里有出处），要么把引用删掉并登记；不要换一个看起来像的 key。
4. **交叉引用必须闭环**：`\ref`/`\cref` 指向的 `\label` 要么存在，要么改引用，要么补 label；不许留悬空引用。
5. **提交可继续编辑的源码**：合入 `\input` 的子文件、附上 `.bib` 与模板类文件；不要只交 PDF，也不要贴日志当成果。
6. **诊断要写到根因**：每条问题给 `file` / `line` / `root_cause` / `fix` / `state`（`fixed` / `needs_confirm` / `accepted`）。
7. **只写文件，不写对话**：所有产物写进 `/app/output`；不要把正文粘在回复里。

## 交付物

| 文件 | 内容 |
|---|---|
| `revised.tex` | 改好的完整源码，能直接编译 |
| `changes.jsonl` | 逐处改动：`before` / `after` / `kind` / `reason`（kind ∈ fix_error / template / structure / math / table / citation / reference / content / style） |
| `diagnosis.json` | 逐条诊断：`kind` / `level` / `file` / `line` / `root_cause` / `fix` / `state` / `evidence` |
| `checklist.json` | 模板必填项对照：`requirement` / `present` / `where` |
| `source_map.json` | 数值与论断的来源定位：`item` / `value` / `quote` / `source` / `kind` |
| `compile_plan.json` | 复现计划：`engine` / `commands` / `passes` / `requires` / `expected_outputs` |

## 输出清单

`/app/output/` 下：`revised.tex`、`changes.jsonl`、`diagnosis.json`、`checklist.json`、
`source_map.json`、`compile_plan.json`、`compile.json`（引擎、轮次、逐轮 rc 与耗时、PDF 路径）、
`compile.log`（原始日志）、`diff.md`、`review.md`、`check.json`、`result.json`；
编译产物另有 `_build/revised.pdf`。

## 核验口径

**结构（prep + assemble）**：`brace_unbalanced`、`end_without_begin`、`unclosed_env`、`env_mismatch`、
`placeholder_left`、`package_order`（`cleveref`/`nameref` 应在 `hyperref` 之后）、`table_column_mismatch`、
`table_no_rules`、`unbalanced_math`、带编号公式缺 `label`、`no_documentclass`、`unresolved_input_in_deliverable`。

**引用与文献**：`undefined_ref`、`undefined_citation`、`unused_label`、`uncited_bib_entry`、`no_citations`。

**不变量**：`protected_dropped_undeclared`（high，只在**主文件**范围内判缺失）、
`protected_added_undeclared`（medium，新增数值必须有来源）。口径写在 `check.json.metrics.protected_scope`。

**交付完整性**：`checklist_missing`、`template_item_unaddressed`、`changes_missing`（空清单同样是 high）、
`change_kind_unknown`、`change_reason_too_short`、`source_map_quote_missing`、
`source_map_quote_not_in_material`（high，引文必须能在材料或交付稿里逐字找到）、`diagnosis_missing`、
`diagnosis_state_unknown`、`prep_high_unaddressed`、`compile_plan_missing`、`compile_plan_incomplete`。

**真编译（有引擎时）**：`compile_error:<category>`（`missing_package` / `missing_class` / `missing_bst` /
`missing_file` / `wrong_engine` / `math_syntax` / `brace_error` / `env_mismatch` / `citation` /
`reference` / `font_error` / `encoding` / `template_requirement`）、`compile_undefined_refs`、
`compile_undefined_cites`、`compile_needs_rerun`、`compile_overfull`；
无引擎时只报 low 的 `compile_not_attempted`。

**刻意宽容**：`23.5 %` ≡ `23.5%`、`\\` 与换行差异、注释行、空白变体、`source_map` 里指向标签/公式的“锚点型”映射不要求逐字。
**刻意不检查**：论文用词与论证质量、公式语义、模板页边距字号的完整合规、PDF 排版美观。

## 状态与退出码

`check.json.status`：无 high 且无 medium → `ok`；有 high → `partial`；缺交付稿或编译失败 → `failed`。
`tex_prep.py` 与 `tex_assemble.py` 的退出码：`0` 正常、`2` 材料不可用/交付缺失。

## 异常与降级

| reason | 含义 | 处理 |
|---|---|---|
| `no_case` | 没给 case.json | 补 case 再跑 |
| `no_material` | 没有可读材料 | 检查 `material_files` |
| `empty_material` | 材料文件是空的 | 补正文内容 |
| `unreadable_material` | 有字节但抽不出文字层（坏包/扫描件） | 换可读版本 |
| `no_tex` | 材料里没有 `.tex` 源码 | 先拿到源码；只有 PDF 时先转写 |
| `engine_timeout` | 引擎超时（MiKTeX 首次按需装宏包很慢） | 先预热一次，或调大 `--timeout` |

**退出码 2 = 材料没得改，不要对着同一份材料反复重试。**

## 最小调用示例

包内 `examples/` 自带一个**带真实缺陷的合成工程**（`sample_project/`）与已经修好的六份交付物：

```bash
python scripts/tex_prep.py --case examples/example_case.json --out /tmp/w
python scripts/tex_assemble.py --case examples/example_case.json --work /tmp/w \
  --revised examples/example_revised.tex --changes examples/example_changes.json \
  --diagnosis examples/example_diagnosis.json --checklist examples/example_checklist.json \
  --source-map examples/example_source_map.json --plan examples/example_compile_plan.json \
  --out /tmp/o
```

**示例输出是示意**：`examples/example_*.json` 里的数值来自合成材料，不代表任何真实论文。
`examples/example_rejected.json` 列出 9 条「只破坏一处」的反例与核验器实际报出的问题；
`examples/fixtures/*.log` 是**构造的日志夹具**，只用于测试日志解析器，不是真实编译产物。

## 依赖

Python ≥ 3.9（纯标准库即可完成静态核验与导出）。
真编译需要本机有 TeX 引擎（`pdflatex` / `xelatex` / `lualatex`）与 `bibtex`/`biber`；
读 PDF 材料需要 PyMuPDF（`fitz`）。
引擎目录可用环境变量 `TEX_BIN_DIRS` / `MIKTEX_BIN_DIRS` / `TEXLIVE_BIN_DIRS` 指定（`;` 分隔）。

## 参考文档

- `references/field-dictionary.md`：输入、中间产物、交付物的全部字段
- `references/log-parsing.md`：日志解析规则与连锁错误归并口径
- `references/invariants.md`：不变量（数值/引用/编号）的记账口径
- `references/verification-rules.md`：全部检查项、宽容处与不检查处
