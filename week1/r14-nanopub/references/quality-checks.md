# 质量检查判据（21 类）

`nanoassemble.py` 对每条断言跑下列检查，结果写进 `output/assertions.jsonl` 的 `validation.issues[]` 与 `output/check.json`。

严重度影响状态：**每条断言** 无问题 → `ok`；只有 medium / low → `partial`；有任何 high → `failed`（这条断言的证据或结构不可用）。**整体** `result.json.status`：有断言带 high → `partial`；全部干净 → `ok`；一条断言都没有、或上游材料不可读 → `failed`。medium / low 不改变整体状态，只进 `review.md` 供人跟进。

## 结构完整性

| issue | 严重度 | 触发条件 | 怎么修 |
|---|---|---|---|
| `invalid_json_line` | high | `assertions.jsonl` 某行不是合法 JSON | 修那一行（`detail` 里有行首 120 字符） |
| `assertion_field_missing` | high | `assertion` 缺 `subject` / `relation` / `object` / `polarity` / `statement` | 补字段 |
| `evidence_field_missing` | high | `evidence` 缺 `src_id` / `quote` / `char_start` / `char_end` | 补字段 |
| `evidence_source_unknown` | high | `src_id` 不在 `work/sources.json` 里 | 用真实 `src_id` |
| `missing_evidence_quote` | high | `evidence.quote` 为空 | 从 `candidates.md` 复制逐字原文 |
| `provenance_incomplete` | medium | `provenance` 缺 `paper_title` / `authors` / `year` / `source_file` / `source_sha256` / `version` / `section` / `page` 之一 | 补出处字段（`year` 拿不准就写文档生成年或显式 `null` 并在 `confidence.basis` 说明） |

## 证据可回查

| issue | 严重度 | 触发条件 | 怎么修 |
|---|---|---|---|
| `quote_not_found` | high | 证据三级比对都不中（被改写或臆造）| 重抄逐字原文 |
| `quote_whitespace_variant` | low | 只归一化后匹配（空白/标点/连字符不同）| 想要更干净就按原文重抄 |
| `quote_offset_wrong` | medium | 内容能全文搜到，但 `char_start/char_end` 与真实位置不符 | 用 `text.find(quote)` 重算偏移 |
| `quote_not_minimal` | medium | 证据 >240 字符或 >2 句 | 缩到真正支撑该断言的那一小段 |
| `quote_too_short` | medium | 证据 <12 字符 | 带上所依附的整句（表格行例外） |
| `subject_not_in_evidence` | medium | 主体不能逐字（大小写不敏感）在证据里找到 | 换成原文里真有的主体表述 |
| `object_not_in_evidence` | low | 客体不能在证据里找到且未声明归一化 | 改词，或写 `assertion.object_normalized: true` |

## 语义方向与条件

| issue | 严重度 | 触发条件 | 怎么修 |
|---|---|---|---|
| `relation_not_in_vocab` | high | `relation` 不在受控词表里 | 改用词表里的关系（`detail` 里给了最接近的候选） |
| `direction_conflict` | high | `polarity: negative` 但证据本体无否定线索 | 改方向，或换一条真是否定的证据 |
| `verify_direction` | low | 断言肯定、证据本体含否定线索 | 核对被否定的到底是哪个成分（`not measured` 否定的是"实测"，不是"数值存在"） |
| `condition_dropped` | medium | 证据本体有条件线索而 `assertion.conditions` 为空 | 把条件写进 `conditions`（`because` / `when` / `if` / `under` / 样品范围 / 温度 / 预算…） |
| `overbroad` | medium | 证据有模糊限定，断言无限定词且无 `confidence.basis` | 断言里带上限定，或写明置信依据 |
| `absolutes_without_quantifier` | low | 证据含 all / never / every / 必然 / 唯一 等，`quantifier` 仍是 `unspecified` | 写明量化范围 |

## 重复与置信

| issue | 严重度 | 触发条件 | 怎么修 |
|---|---|---|---|
| `duplicate_assertion` | medium | 与已有断言的词元 Jaccard ≥ **0.85** | 合并两条，或改成真正不同的一件事 |
| `confidence_without_basis` | low | `confidence.basis` 为空 | 写清"凭什么" |

## 指标定义

| 指标 | 算法 |
|---|---|
| `quote_verified_rate` | 证据逐字可回查的断言数 / 断言总数 |
| `minimal_evidence_rate` | 12 ≤ 证据长度 ≤ 240 且 ≤2 句的断言数 / 总数 |
| `relation_vocab_rate` | 关系在词表内且无 `direction_conflict` 的断言数 / 总数 |
| `provenance_complete_rate` | 出处字段齐全的断言数 / 总数 |
| `condition_kept_rate` | （证据无条件线索的断言数 + 条件已写入的断言数）/ 总数 |
| `duplicate_rate` | 命中 `duplicate_assertion` 的断言数 / 总数 |
| `candidate_coverage` | `candidates_used` / `candidates_available`（用掉的候选 / 全部候选）|
| `avg_statement_clauses` | 每条断言的子句数均值（越高越说明没拆细）|
| `avg_quote_chars` | 证据平均字符数 |

## 刻意不检查的（诚实边界）

1. **断言的学术真伪** —— 只保证证据里说了这句话，不保证这句话本身对。
2. **跨句语义蕴含** —— 需要推理才能得出的结论必须拆成多条，不做蕴含判定。
3. **叙述质量** —— 文风、连贯性、读者友好度不在范围内。
4. **术语翻译是否"译对"** —— 这是 r03 类任务的边界；本 Skill 只负责断言与证据的对应关系。
5. **`indirect` 证据的正当性** —— 只把它列进 `unresolved` 请人确认，不做自动裁决。

自动检查覆盖不到的，一律写进 `check.json.unresolved` 与 `result.json.uncertainty`：**宁可自曝边界，也不冒充质量认证。**
