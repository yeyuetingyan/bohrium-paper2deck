# 字段字典（field-dictionary）

本文件定义第二步 Agent 要写的四份文件，以及第三步导出的图谱字段。字段名大小写敏感；缺字段会被核验器记 `*_field_missing`。

## 1. `entities.jsonl`（一行一个实体）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `entity_id` | string | 是 | 图谱内唯一 id，建议 `e-<slug>` |
| `label` | string | 是 | 规范化显示名，必须是原文出现过的字符串 |
| `type` | string | 是 | 取自 `entity_types.json`：`researcher` / `material` / `method` / `task` / `metric` / `condition` / `dataset` / `conclusion` |
| `aliases` | string[] | 否 | 同一对象的其它写法（缩写、全称、大小写变体）。**只放能确证同一性的写法** |
| `note` | string | 否 | 为什么归并这些写法（人读，核验时会一起导出） |
| `occurrences` | object[] | 是（至少 1 条） | 每个出现位置：`source_id`、`paragraph_id`、`quote`（逐字） |

## 2. `relations.jsonl`（一行一条边）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `subject` | string | 是 | 主语实体 label 或 alias |
| `relation` | string | 是 | 取自 `relation_vocab.json`（14 个有向关系） |
| `object` | string | 是 | 宾语实体 label 或 alias |
| `source_id` | string | 是 | 证据所在论文 |
| `paragraph_id` | string | 是 | 证据所在段落（组织方 JATS 段落 ID） |
| `quote` | string | 是 | 与段落正文**逐字一致**的片段（建议 ≥12 字符、≤400 字符、≤3 句） |
| `conditions` | string[] | 否 | 该结论成立的条件（温度、湿度、时长、光照等），值取自原文 |
| `evidence_kind` | string | 否 | `direct`（本文实验/结论）或 `reported`（转述他人）。段落含 `reported / et al.` 时必填 |

## 3. `merges.jsonl`（一行一条合并裁决）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `decision` | string | 是 | `merge` 或 `keep_separate` |
| `members` | string[] | 是（`keep_separate` 可为空） | 参与裁决的写法；写进图谱时以 `canonical` 为准 |
| `canonical` | string | `merge` 时必填 | 合并后节点的显示名 |
| `candidate_ids` | string[] | 否 | 直接点名 `mc-*` / `mn-*` 候选号，比按标签匹配更可靠 |
| `cross_paper` | bool | 跨篇必填 | 跨篇合并必须显式 `true` |
| `reason` | string | 是 | 合并依据，或"为何不合并"（同名不同物、条件不同、样品不同…） |
| `evidence` | object[] | `merge` 时必填 | 至少一条位置证据：`source_id` / `paragraph_id` / `quote` |

## 4. `queries.json`

```json
{"queries": [
  {"id": "q1", "type": "neighbors", "question": "与 T80 直接相连的有哪些实体？",
   "args": {"entity": "T80", "depth": 1}, "expect": "列出边与各自证据位置"}
]}
```

- `type` 取 `entity` / `neighbors` / `path` / `relation` / `keyword` / `evidence` / `conflicts` / `subgraph` / `stats`。
- `args` 因类型而异（见 `references/query-templates.md`）。
- 至少 3 条；每条都要真跑，`query_results.json` 会记录 `row_count`、`rows`、`answer`、`has_evidence`。

## 5. 导出的 `graph.json`

| 字段 | 说明 |
|---|---|
| `nodes[]` | `id` / `label` / `type` / `aliases` / `source_ids` / `occurrences` / `degree` |
| `edges[]` | `subject` / `relation` / `object` / `source_id` / `paragraph_id` / `quote` / `conditions` / `evidence_kind` / `cross_paper` |
| `must_not_merge[]` | 显式保留的不可合并记录：`labels` / `kind` / `reason` / `action` / `cross_paper` / `evidence` |
| `caveats[]` | 图谱能力边界（语义级判断不在范围内等） |

## 6. `result.json`（各题统一契约）

顶层：`schema` / `case_id` / `status`（`ok` / `partial` / `failed`）/ `primary_result` / `evidence` / `uncertainty` / `artifacts`（每项带 `bytes` 与 `sha256`）/ `change_log`，并按 `output_contract` 回填契约字段（本题为 `graph` / `entities` / `relations` / `queries` / `check`）。
