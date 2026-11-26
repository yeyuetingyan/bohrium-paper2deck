# 证据规则（evidence-rules）

"连得对 + 查得到回得去"靠的是同一件事：**每条边都能在原文里逐字找到，且位置可指出**。本文件列出核验器实际执行的检查、级别与通过条件；`kg_assemble.py` 的 `check.json.issues` 里出现的 `kind` 都能在这里对上。

## 一、位置与引文

| 检查项 | 级别 | 触发条件 | 怎么过 |
|---|---|---|---|
| `occurrence_location_unknown` / `relation_location_unknown` | HIGH | 没写 `source_id` 或 `paragraph_id`，或该段落不在输入材料里 | 位置只能来自 `passages.json` |
| `occurrence_quote_not_found` / `relation_quote_not_found` | HIGH | 引文不是该段落正文的逐字片段（改写过、补过字、换了标点顺序） | 从 `passages.md` 里**复制粘贴**原文片段 |
| `*_quote_whitespace_variant` | LOW | 只差空白/换行/软连字符 | 允许；脚本会归一后比对 |
| `relation_quote_too_short` | LOW | 引文 < 12 字符 | 给足以核对结论的片段 |
| `relation_quote_not_minimal` | MED | 引文 > 400 字符或 > 3 句 | 缩到覆盖主宾的最小片段 |
| `quote_lacks_subject` / `quote_lacks_object` | MED | 引文里找不到主语/宾语（别名也算） | 换一段同时含两者的引文 |
| `direction_suspect` | LOW | 引文里宾语出现在主语之前 | 友好提示；确认方向没反即可 |

## 二、条件（条件的三种错法）

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `condition_dropped` | MED | 引文里出现了条件值（如 `85%`、`300 h`），但 `conditions` 整批为空 |
| `condition_subset_incomplete` | LOW | 引文里还有条件值没进 `conditions` |
| `conditions_from_paragraph` | LOW | `conditions` 的值不在引文里、只在本段别处出现 |
| `condition_not_in_source` | HIGH | 条件值在该段原文里根本找不到 |
| `condition_from_other_source` | HIGH | 条件值不出现在本条证据所在段落，却出现在**另一篇**：两篇条件不得混用 |

要点：条件必须**跟着它约束的那条边**走。同一条边在不同论文里条件不同，就写成两条边（各自的 `source_id` / `conditions`），不要合成一条。

## 三、关系与转述

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `relation_not_in_vocab` | HIGH | `relation` 不在 `relation_vocab.json` 里（例如随手写 `correlates`） |
| `relation_duplicate` | MED | 同一组主宾+关系重复出现 |
| `subject_not_found` / `object_not_found` | HIGH | 边的两端在实体表里找不到（补进 `entities.jsonl` 或改写法） |
| `attribution_unmarked` | MED | 段落含 `reported / according to / et al.` 线索，但没写 `evidence_kind` |
| `merge_evidence_quote_not_found` | HIGH | 合并裁决的 `evidence.quote` 逐字对不上 |

## 四、合并裁决

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `merge_without_evidence` | HIGH | `decision=merge` 但没给位置证据 |
| `merge_members_too_few` / `merge_members_missing` | HIGH | 合并只有 1 个成员，或成员与候选号都为空 |
| `merge_across_conditions` | HIGH | 同名指标在不同论文里报告条件不同（如 `T80` 在 45% 与 85% RH 下），却要合并成一个节点 |
| `cross_paper_merge_unflagged` | MED | 跨篇合并没写 `cross_paper: true` |
| `merge_candidate_unaddressed` | MED | 候选（`mc-*` / `mn-*`）没有任何裁决行覆盖 |
| `keep_separate_without_reason` | MED | 判为不合并但没写理由 |
| `merge_member_not_in_graph` | MED | 成员写法既不在实体表也不在候选里（会提示先建实体） |

## 五、查询

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `query_count_below_min` | HIGH | 少于 3 条查询（题面硬要求） |
| `query_no_result` | MED | 查询零结果（要么改查询，要么在图谱里补该内容） |
| `query_result_without_evidence` | HIGH | 结果行不带 `source_id` / `paragraph_id` / 引文（`stats` 类查询豁免） |
| `query_problem` | MED | 查询脚本自身报错（参数写错等） |

## 六、逐字 vs 归一

- **必须逐字**：`quote`（引文）、`occurrences[].quote`。脚本先做空白归一，再要求完全一致。
- **允许归一**：实体 label 与 alias 的大小写、连字符、括号写法；数字的 `1.0` ≡ `1`、千分位与全角/半角。
- **不做判断**：引文是否"足以支撑"该关系，属语义判断，不在自动核验范围；脚本只保证"这句话确实在原文里、方向和条件与原文一致"。
