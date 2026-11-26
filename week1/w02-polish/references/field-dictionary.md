# 字段字典

本文件列出 Skill 运行时各产物与中间文件的字段。所有 JSON/JSONL 一律以 UTF-8 写盘、行尾 `\n`。

## 1. 输入：`case.json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 案例标识，必须回填进 `result.json` 顶层 |
| `manuscript_path` | str | 稿件路径；缺失时按候选名兜底（`manuscript.md` / `draft.md` / `document.md` / `source.md` / `paper.md` / `material.md` / `text.md` / `input.md`，含 `.txt`/`.tex`/`.docx` 变体） |
| `style` | str | 目标文体：`journal-article` / `thesis` / `grant-proposal` / `reviewer-response` / `abstract`；**此项优先于题面文本里的任何体裁词** |
| `audience` | str | 读者群，仅记录，不参与体裁判定 |
| `target_language` | str | 目标语言，仅记录 |
| `glossary` | list | 任务给定术语表，优先级最高（`status=prescribed`） |
| `output_contract` | dict | 键 → `{type, default}`；w02 为 7 键：`manuscript`(text)、`edits`(records)、`diff`(text)、`glossary`(text)、`consistency`(json)、`check`(json)、`review`(text) |

## 2. `work/segments.json`（列表）

每个元素是一句：

| 字段 | 说明 |
|---|---|
| `seg_id` | `p<四位段号>b<句号>`，例如 `p0002b1`；**这是修改清单的契约键** |
| `para_id` | `p<四位段号>` |
| `index` | 段内句序（从 1 起） |
| `kind` | `heading` / `front-matter` / `list` / `caption` / `environment` / `body` |
| `section` | 所属章节（最近的祖先标题） |
| `text` | 原文（逐字） |
| `chars` / `sha256_16` | 字符数与内容哈希前 16 位 |
| `cjk_ratio` | 中文字符占比 |
| `cues` | `{hedges, boosts, negation, quantifiers, conditions, causal, correlational, numbers, citations}`，各为命中的线索词列表 |
| `balance` | `{hedges, boosts, causal, correlational, conditional, negation, quantifier}` 计数（强度守恒比对用） |
| `protected` | `{number, citation, crossref, formula, url, doi}`，各为需逐字保留的字符串列表 |

## 3. `work/issues.jsonl`（每行一条候选问题）

| 字段 | 说明 |
|---|---|
| `seg_id` | 命中句 |
| `type` / `kind` | 问题类别，见下表 |
| `severity` | `high` / `medium` / `low` |
| `span` | 原文片段（标点类问题会向后多带 12 个字符以便定位） |
| `detail` | 人类可读说明 |
| `hint` | 改写建议 |

`type` 取值：`subject_verb_agreement`、`redundant_nominalization`、`comma_splice`、`translationese`、`punctuation`、`colon_case`、`spelling_variant`、`absolute_claim`、`term_variant`、`unit_spacing_inconsistent`、`acronym_used_before_definition`、`acronym_undefined`、`hyphenation`、`capitalization`。

## 4. `work/glossary_draft.tsv` 与锁定的 `glossary.tsv`

制表符分隔，表头固定：`term  preferred  variants  status  note`。

| 列 | 说明 |
|---|---|
| `term` | 候选术语（原文写法） |
| `preferred` | 全篇统一使用的写法（Agent 填写） |
| `variants` | 其它出现过的写法，`|` 分隔 |
| `status` | `suggested`（候选） / `prescribed`（任务给定） / `locked`（已锁定，核验以此为准） |
| `note` | 备注（如首次出现位置、缩写来源） |

## 5. `edits.jsonl`（Agent 产出，每行一处修改）

| 字段 | 说明 |
|---|---|
| `edit_id` | 由核验脚本补齐（`e0001`…） |
| `seg_id` | 必须存在于 `segments.json` |
| `para_id` | 由核验脚本补齐 |
| `type` | 修改类型，见 `edit-taxonomy.md` |
| `before` | **原文逐字片段**（必须在对应句子里能找到） |
| `after` | 改后逐字片段（纯删除写空串） |
| `reason` | 修改理由，≥6 字符 |
| `declared_strength_change` | 由核验脚本标记：该条是否属于"声明了强度改动"的类型 |

## 6. `check.json`

```
{ "status": "ok|partial|failed",
  "metrics": { ... },
  "issues": [ {"level","kind","where","detail"} ],
  "unresolved": [ 三条固定边界说明 ] }
```

`metrics` 主要键：`paragraphs_source`、`paragraphs_revised`、`segments_source`、`segments_indexed`、`chars_source`、`chars_revised`、`similarity`、`minimal_edit_rate`、`protected_total`、`protected_missing`、`protected_extra`、`protected_preserved_rate`、`edits`、`edits_with_reason`、`edits_per_1k_chars`、`edit_type_histogram`、`paragraphs_changed`、`paragraphs_declared`、`unexplained_changes`、`terms_locked`、`terms_unified`、`terms_drifted`、`term_unified_rate`、`issues_high`、`issues_medium`、`issues_low`。

## 7. `consistency.json`

```
{ "version", "metrics", "paragraphs": [...], "protected_document": {...}, "terms": [...] }
```

`paragraphs[i]` 字段：`para_id`、`kind`、`section`、`seg_ids`、`changed`、`declared`、`similarity`、`chars_before`、`chars_after`、`protected`、`strength`（内含 `hedges_removed` / `boosts_removed` / `universals_removed` / `declared_fragments`）。

## 8. `result.json`（契约回填后的主结果）

顶层：`schema`、`case_id`、`status`、`primary_result`、`evidence`、`uncertainty`、`artifacts`、`change_log`，以及 7 个契约键 `manuscript` / `edits` / `diff` / `glossary` / `consistency` / `check` / `review`（映射到实际文件名），另加 `issues`。

`primary_result`：`status_detail`、`paragraphs`、`edits`、`similarity`、`protected_preserved_rate`、`issues_high`、`issues_medium`、`next_step`。

`artifacts[i]`：`path`、`role`、`media_type`、`bytes`、`sha256`。
