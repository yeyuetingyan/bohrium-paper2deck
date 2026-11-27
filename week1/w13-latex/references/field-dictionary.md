# 字段字典（paper-latex）

## 输入

`/input/case.json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 案例标识，必须回填进 `result.json` |
| `material_files` | list[str] | 材料路径列表；**顺序即编号契约**，不要重排 |
| `output_contract` | dict | 期望产物字段；未产出的键会进 `uncertainty` |
| `engine` | str | 可选，强制引擎（`pdflatex` / `xelatex` / `lualatex`） |
| `style` | str | 可选，体裁提示 |
| `format_constraints` | dict | 可选，模板约束 |

材料类型识别：`.tex` / `.bib` / `.bbl` / `.cls` / `.sty` / `.bst` / `.log` 直接读文本；
`.pdf` 走 PyMuPDF 抽文字层（无文字层 → `unreadable:no_text_layer`）；
`.docx` 走 zipfile 读 `word/document.xml`；`.doc` / `.odt` / `.rtf` → `unreadable:no_extractor`。

`main_file`（可选）显式指定主文件；**真实工程的主文件常常不叫 `main.tex`**
（如 `ms.tex`、`residual_v1_arxiv_release.tex`），此时靠这个字段点名，否则退化为
「有 `\documentclass` 的、最长的那个 .tex」。

文献来源按优先级合并并去重（`key` 唯一）：`.bib` → **`.bbl`（bibtex 产物）** →
**正文里的 `\begin{thebibliography}`** → `case.json` 内联 bib。
arXiv 源码包常常**只带 `.bbl` 不带 `.bib`**，甚至直接手写 `thebibliography`；
只认 `.bib` 会把这类论文的全部引用误判成"文献库里找不到"。

## 中间产物（`/app/work`）

| 文件 | 内容 |
|---|---|
| `files.json` | 每个材料：`path` / `rel` / `ext` / `kind` / `text` / `note` / `lines` / `sha256_16` |
| `project.json` | `main_file` / `document_class` / `packages[]` / `environments[]` / `inputs[]` / `magic` |
| `labels.json` | 每个 `\label`：`key` / `file` / `line` |
| `citations.json` | 每个 `\cite`/`\ref`：`raw` / `keys[]` / `file` / `line` / `kind` |
| `bib.json` | 文献库条目：`key` / `type` / `title` / `year` / `source_file` / `raw` |
| `numbers.json` | **结构化数值账本**：`{schema, main_file, main:{items,count}, by_file:{rel:{…}}, all:{…}}` |
| `issues.jsonl` | 静态问题：`level` / `kind` / `file` / `line` / `detail` / `hint` |
| `checklist_draft.json` | 模板必填项草稿：`requirement` / `present` / `where` |
| `toolchain.json` | `available` / `engines{name:path}` / `bib_tools{name:path}` / `perl` / `latexmk` |
| `structure.md` | 人/Agent 读的工程概览：文件清单、宏包、标签与引用、数值清单、问题清单 |
| `prep.json` | `status` / `reason` / `hint` / `next_step`（7 步）/ 计数 |
| `prep_check.json` | 自检：文件数、`.tex` 数、解析异常 |

## Agent 交付物（也放 `/app/work`）

### `revised.tex`
改好的完整源码。应当能直接编译；若合入了 `\input` 的子文件，就不要再依赖原相对路径。

### `changes.jsonl`（逐处改动，一行一条）

| 字段 | 说明 |
|---|---|
| `before` | 原文片段（必须能在原文件里逐字找到） |
| `after` | 改后片段 |
| `kind` | `fix_error` / `template` / `structure` / `math` / `table` / `citation` / `reference` / `content` / `style` |
| `reason` | 改动理由（≥6 字符），中文可写 |

### `diagnosis.json`

`{"schema":"tex-diagnosis/1.0","items":[…]}`，每条：

`kind` / `level`（high/medium/low） / `file` / `line` / `root_cause` / `fix` /
`state`（`fixed` / `needs_confirm` / `accepted`） / `evidence`。

**prep 报出的每条 high 都要在这里有对应条目**，否则报 `prep_high_unaddressed`。

### `checklist.json`

`{"schema":"tex-checklist/1.0","items":[{"requirement":…,"present":bool,"where":…}]}`。
`present=false` 的项必须在 `checklist.json` 里有说明（否则 `template_item_unaddressed`）。

### `source_map.json`

`{"schema":"tex-source-map/1.0","items":[…]}`，每条：

`item` / `value` / `quote` / `source` / `kind`。

- `kind` 属于 `ANCHOR_KINDS`（`label` / `anchor` / `formula_ref` / `figure` / `table_ref` / `crossref` / `ref` / `citation`）
  时视为**指针**，不核对引文。
- 其余种类（数值、论断、事实）的 `quote` 必须能在材料或交付稿里逐字找到（`norm_hard` 比对），
  否则报 high `source_map_quote_not_in_material`。

### `compile_plan.json`

| 字段 | 说明 |
|---|---|
| `engine` | 计划使用的引擎 |
| `commands` | 计划执行的命令列表（**空列表会报 `compile_plan_incomplete`**） |
| `passes` | 计划轮次（0 会报不完整） |
| `requires` | 需要的宏包/工具 |
| `expected_outputs` | 期望产物（如 `revised.pdf`） |

## 产物（`/app/output`）

| 文件 | 内容 |
|---|---|
| `revised.tex` | 交付源码 |
| `changes.jsonl` / `diagnosis.json` / `checklist.json` / `source_map.json` / `compile_plan.json` | 原样回填 |
| `compile.json` | `status` / `engine` / `passes[{n,kind,cmd,rc,failed,timeout,seconds,errors,log_excerpt}]` / `errors[]` / `warnings` / `artifacts{pdf,pdf_bytes,log,bib_log}` / `reason` / `hint` |
| `compile.log` | 原始编译日志（含每轮分节标题） |
| `diff.md` | 改动对照表 |
| `review.md` | 人读报告：逐条问题 + 状态 + 核验边界 |
| `check.json` | `status` / `metrics` / `issues[]` / `unresolved[]` |
| `result.json` | 契约字段 + `schema` / `case_id` / `status` / `primary_result` / `evidence` / `uncertainty` / `artifacts` / `change_log` |
| `_build/` | 真编译产物：`revised.pdf` / `.aux` / `.log` / `.blg` |

`check.json.metrics` 键：`packages`、`inputs_in_deliverable`、`environments`、`labels`、`refs`、
`citations`、`bib_entries`、`protected_scope`、`protected_before`、`protected_after`、
`protected_dropped`、`protected_added`、`template_items`、`template_missing`、`changes`、
`source_map_items`、`prep_high`、`diagnosis_items`、`diagnosis_unhandled_high`、
`compile_plan_rounds`、`compile_status`、`compile_pages`、`compile_passes`、
`issues_high`、`issues_medium`、`issues_low`。
