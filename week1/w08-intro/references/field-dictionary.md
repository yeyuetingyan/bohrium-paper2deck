# 字段字典（paper-intro）

三部分：**输入**（case.json）→ **中间产物**（`/app/work`）→ **交付物**（`/app/output`）。
所有 JSON 均为 UTF-8、无 BOM、`\n` 换行。

## 一、输入 `case.json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 案例标识，会原样写进 `result.json`。 |
| `task` | str | 任务描述（截取前 1200 字符写进 `context.json.task_excerpt`）。 |
| `audience` | str | 目标读者。 |
| `genre` | str | 文体（如 `journal-article`）。 |
| `language` | str | 语言代码。 |
| `format_constraints` | str[] | 格式约束（引用制式、数字写法等），写进 `context.json` 供 Agent 遵守。 |
| `material_path` / `material_text` / `material` | str | 科研材料路径或内联文本。 |
| `bibliography_path` / `bibliography` / `bib` | str | 文献库路径（`.bib`）或内联文献数组。 |
| `output_contract` | obj | 需要交付的字段；核验器按它回填 `result.json` 顶层键。 |

### 文件名兜底

`material_path` 与 `bibliography_path` 都缺省时，脚本会在 case 同目录按顺序找：

- 材料：`material.md` `material.txt` `material.json` `manuscript.md` `paper.md` `document.md` `draft.md` `source.md` `notes.md` `facts.md` `input.md` `primary-material.json` `material.tex` …
- 文献：`bibliography.bib` `refs.bib` `references.bib` `library.bib` `bibliography.json` `references.json` …

命中时会在 `context.json.notes` 与 `prep.json.warnings` 里留痕，不静默。

### 文献记录字段（`references.json.records[]`）

| 字段 | 说明 |
|---|---|
| `key` | 引用键（BibTeX key 或按位置生成的 `auto:N`）。 |
| `raw` | 原始条目文本。 |
| `authors` / `year` / `title` / `venue` / `doi` / `url` / `type` / `source` | 解析出的元数据；解析不到的写 null 并在 `prep_check.json` 里计数。 |

### 编号普查（`references.json.census`）

| 字段 | 说明 |
|---|---|
| `numbering_basis` | `bibtex`（文献自带编号）或 `positional`（按出现顺序映射，**假设，需复核**）。 |
| `positional_number_map` | `{ "1": "chen2020stability", ... }`。 |
| `citations_in_material` | 材料里出现的引用标记数。 |
| `citations_used_keys` | 材料引用解析到的 key。 |
| `unresolved_in_material` | 材料里解析不到文献表的引用。 |
| `bib_keys` / `dois_in_bibliography` / `dois_in_material` | 对照用清单。 |

## 二、中间产物（`/app/work`）

### `facts.jsonl` — 可引材料句

| 字段 | 说明 |
|---|---|
| `fact_id` | `f<sent_id>`，如 `fm-p001s2`。 |
| `sent_id` / `para_id` | 句子号 / 段落号（`m-p001`）。 |
| `text` | 句子原文。 |
| `anchor_text` | 比 `text` 更短的逐字锚点，写论断时用它当 `source.quote` 最稳。 |
| `score` / `reasons` | 可引性打分与理由（有引用 +0.4、有数字 +0.2、有归属 +0.3、有局限 +0.3、有空白线索 +0.4、有贡献线索 +0.4 …）。 |
| `cues` | 线索统计（attribution/limitation/hedge/negation/quantifier/gap_cue/contrib_cue/numbers/citations）。 |
| `protected` | 该句里必须原样保留的成分：`{number:[...], citation:[...], crossref:[...], formula:[...]}`。 |

### 其余中间文件

| 文件 | 关键字段 |
|---|---|
| `number_citations.jsonl` | `number` `span` `offset` `citation` `citation_keys` `para_id` `note` —— 材料里"数字 + 紧随引用"的绑定对，用来防止把数字挂到错的文献上。 |
| `ref_groups.jsonl` | `group_id` `members[]` `size` `shared_terms[]` `venues[]` `years[]` `note` —— 文献聚类候选（供参考，不代替你的分组判断）。 |
| `gap_candidates.jsonl` | `candidate_id` `text` `kind` `gap_cue` `limitation_hits` `para_id` `note`。 |
| `contribution_candidates.jsonl` | `candidate_id` `text` `cues` `para_id` `note`。 |
| `terms.jsonl` | `term` `preferred` `variants[]` `note`。 |
| `context.json` | `version` `case_id` `audience` `genre` `language` `format_constraints` `contract` `task_excerpt` `material_source` `material_path` `material_chars` `bibliography_source` `bibliography_path` `section_patterns[]`。 |
| `prep.json` | `status` `version` `case_id` `paragraphs` `sentences` `facts` `number_citations` `references` `ref_groups` `gap_candidates` `contribution_candidates` `terms` `numbering_basis` `citations_in_material` `unresolved_citations_in_material` `material_source` `audience` `genre` `warnings[]` `next_step[]`。失败时另有 `reason` / `hint`。 |
| `prep_check.json` | `paragraphs` `sentences` `empty_paragraphs` `duplicate_para_ids` `very_long_sentences` `facts_without_anchor_text` `facts_without_number_or_citation` `unresolved_citations_in_material` `numbering_basis` `references_without_authors` `references_without_doi` `references_without_year` `bibliography_empty`。 |
| `facts.md` | 人/Agent 读的清单：逐条原文 + 必须原样保留成分 + 文献记录 + 编号映射 + 数字-引用绑定对。 |

## 三、Agent 要写的六份文件（仍写在 `/app/work`）

### `introduction.md`

四节正文，标题需按 **研究背景 → 相关工作 → 研究空白 → 贡献** 顺序出现（中英文标题均可，可带编号与 `#` 标记）。

### `claims.jsonl`

| 字段 | 必填 | 说明 |
|---|---|---|
| `claim_id` | ✓ | 论断标识。 |
| `claim_kind` | ✓ | `background_fact` / `related_work` / `gap` / `contribution` / `own_result` / `uncertain`（作者判断）。 |
| `text` | ✓ | 论断句，**必须逐字出现在 `introduction.md` 里**。 |
| `citations` | ✓ | `["n:3"]`（编号）或 `["chen2020stability"]`（key）；编号与 key 会归一到同一文献。 |
| `source.para_id` / `source.quote` | ✓ | 逐字来源引文，必须能在材料里 `find()` 到。 |
| `result_anchor` | 贡献/结果句建议给 | `{"section","contrib_id","result","quote"}`。 |

### `contributions.jsonl`

`contrib_id` / `text` / `anchors[{kind, ref, quote}]`；`kind` ∈ `section` / `result` / `figure` / `table` / `metric`。

### `groups.jsonl`

`group_id` / `dimension` / `members[]` / `compare_on` / `summary`。
`summary` 是要给出**比较结论**的一段话，不是文献列表；含 `best/always/novel/最优` 这类词会被 `group_summary_overclaim` 点名。

### `citation_map.json`

数组或对象，元素：`key`（正文里的编号或 key）/ `bibtex_key` / `authors` / `year` / `venue` / `title` / `doi`。
元数据与 `.bib` 不一致会报 `citation_metadata_mismatch`；出现文献表外的 key 会报 `citation_map_unknown_key`。

### `gaps.jsonl`

`gap_id` / `statement` / `from_refs[]` / `how_filled`。

### `terms.jsonl`

`term` / `preferred` / `variants[]` / `note`。

## 四、交付物（`/app/output`）

| 文件 | 说明 |
|---|---|
| `introduction.md` | 定稿正文（从 work 复制）。 |
| `claims.jsonl` / `contributions.jsonl` / `groups.jsonl` / `gaps.jsonl` | 绑定与锚点表（从 work 复制）。 |
| `citation_map.json` | 引用元数据对照。 |
| `diff.md` | 逐节字符数与变更概览。 |
| `check.json` | `{status, metrics, issues[], unresolved[]}`。 |
| `review.md` | 人工复核清单 + 核验边界。 |
| `result.json` | `schema` `case_id` `status` `primary_result` `evidence` `uncertainty` `artifacts[]`（带 `path`/`role`/`bytes`/`sha256`）`change_log` + 契约字段 + `issues`。 |

### `check.json.metrics`

`chars_introduction` `sections_found` `sections_missing` `citations_in_introduction` `citation_keys_used`
`citations_unresolved` `references_total` `references_uncited` `citation_map_entries`
`claims` `claims_with_citation` `claims_with_source` `claims_source_verified_rate`
`contributions` `contributions_with_anchor` `groups` `grouped_keys` `cited_grouped_rate` `gaps`
`numbers_in_introduction` `numbers_not_in_material` `boilerplate_hits`
`issues_high` `issues_medium` `issues_low`。

### `issues[]` 的记录形态

`{level: high|medium|low, kind: "<检查项>", where: "<段落/节/key>", detail: "<中文说明>"}`
检查项清单见 `verification-rules.md`。
