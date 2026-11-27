# 核验规则（paper-latex）

级别口径：**high** 表示成果不可用或说了不算（会拉低 `status` 到 `partial`/`failed`）；
**medium** 表示缺东西、需要补；**low** 是提示。

## 一、静态结构（prep 给行号）

| kind | 级别 | 判据 |
|---|---|---|
| `brace_unbalanced` | high | 全文件 `{`/`}` 计数不等（带 `depth`） |
| `end_without_begin` | high | `\end{X}` 没有对应的 `\begin{X}` |
| `unclosed_env` | high | `\begin{X}` 没有 `\end{X}`（给行号） |
| `placeholder_left` | medium | 残留 `TODO` / `FIXME` / `XXX` |
| `package_order` | medium | `cleveref`/`nameref` 在 `hyperref` **之前**加载 |
| `table_column_mismatch` | high | `tabular` 声明列数与某行的 `&` 数不符（列出每行实际格数） |
| `table_no_rules` | low | `table`/`tabular` 没有 `\hline`/`\toprule` 等横线 |
| `unbalanced_math` | high | `$` 个数为奇数 |
| `numbered_math_no_label` | medium | 带编号公式（`equation`/`align`）没有 `\label` |
| `missing_input` | high | `\input`/`\include` 指向的文件不在材料里 |
| `cjk_without_support` | high | 含 CJK 但没有 `ctex`/`xeCJK`/`fontspec` |
| `no_tex_engine` | low | 本机探测不到引擎（不影响静态核验） |

## 二、交付稿（assemble）

| kind | 级别 | 判据 |
|---|---|---|
| `revised_missing` | high | 没有 `revised.tex` 或为空（退出码 2） |
| `no_documentclass` | high | `revised.tex` 里没有 `\documentclass` |
| `brace_unbalanced` | high | 交付稿花括号不配对 |
| `end_without_begin` / `unclosed_env` | high | 交付稿环境不配对 |
| `unresolved_input_in_deliverable` | medium | 交付稿仍 `\input` 未随包交付的子文件 |
| `undefined_ref` / `undefined_citation` | high | 引用闭环破裂 |
| `unused_label` / `uncited_bib_entry` | low | 残留 |
| `no_citations` | medium | 既无引用也无文献库 |

## 三、不变量与交付完整性

| kind | 级别 | 判据 |
|---|---|---|
| `protected_dropped_undeclared` | high | 主文件范围内的数值/引用/编号少了，且 `changes.jsonl` 里没说明 |
| `protected_added_undeclared` | medium | 多出材料里没有的数值 |
| `checklist_missing` | medium | 没有 `checklist.json` |
| `template_item_unaddressed` | medium | 模板必填项仍缺失且清单里没说明 |
| `changes_missing` | high | 没有 `changes.jsonl`，**或清单为空** |
| `change_row_invalid` / `change_kind_unknown` | high / medium | 改动条目结构或 type 不合法 |
| `change_reason_too_short` | low | 理由短于 6 字符 |
| `source_map_missing` | medium | 没有 `source_map.json` |
| `source_map_quote_missing` | low | 某条映射没写引文（短于 8 字符） |
| `source_map_quote_not_in_material` | high | 引文在材料与交付稿里都找不到（锚点型条目除外） |
| `diagnosis_missing` | medium | 没有 `diagnosis.json` |
| `diagnosis_state_unknown` | low | `state` 不在 `fixed`/`needs_confirm`/`accepted` |
| `prep_high_unaddressed` | high | prep 报的 high 没有在诊断里给出处置 |
| `compile_plan_missing` | low | 没有 `compile_plan.json` |
| `compile_plan_incomplete` | medium | 计划缺 `engine`/`commands`/`passes` |

## 四、真编译（有引擎时）

| kind | 级别 | 判据 |
|---|---|---|
| `compile_error:<category>` | high | 日志里解析出的每条错误（分类见 `log-parsing.md`） |
| `compile_undefined_refs` | high | 日志显示未定义交叉引用 |
| `compile_undefined_cites` | high | 日志显示未定义文献 |
| `compile_needs_rerun` | low | 日志提示 `Rerun` |
| `compile_overfull` | low | `Overfull \hbox` |
| `compile_not_attempted` | low | 本机无引擎，未编译（**如实标注，不伪造**） |

## 五、刻意宽容（不报或降级）

- `23.5 %` ≡ `23.5%`；全角/半角标点、空白与换行差异一律等价。
- 注释掉的 `%` 行不参与环境与括号计数。
- `source_map` 中 `kind ∈ ANCHOR_KINDS` 的条目是**指针**（`\label`/公式/图表/引用号），不核对引文。
- 子文件被内联进主文件造成的重复计数，不判为「丢失」（见 `invariants.md` 的 `protected_scope`）。
- `table_no_rules` 只报 low：三线表不是论文硬性要求。
- 取不到行号时只给文件（TeX 日志本身可能没给 `l.NN`）。

## 六、刻意不检查（写进 `unresolved`）

1. 编译是否通过取决于运行环境是否有 TeX 引擎；报告如实标注 `compile.status`。
2. 论文用词、论证与公式语义不在自动核验范围。
3. 模板的完整合规性（页边距、字号、行距）需人工比对模板说明。
4. PDF 排版美观、图表清晰度、图像内容不在范围。
5. 「改动是否最优」不判断：只判断改动是否被登记、是否守住了不变量。
