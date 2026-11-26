# 断言与记录的字段字典

`nanokit/1.0`。三个地方共用同一套字段：Agent 写的 `work/assertions.jsonl`、核验后的 `output/assertions.jsonl`、契约里的 `result.json`。

## 1. 一条断言记录

```json
{
  "cand_id": "p1b4s2",
  "assertion": {
    "subject": "The document",
    "relation": "compose",
    "object": "a title block, an abstract, numbered sections and running text",
    "polarity": "positive",
    "quantifier": "unspecified",
    "conditions": [],
    "statement": "该演示文档由标题块、摘要、编号章节与正文组成。",
    "object_normalized": true
  },
  "evidence": {
    "src_id": "p1b4",
    "quote": "The document contains a title block, an abstract, numbered sections, running text, and a ruled table with numeric cells.",
    "char_start": 61,
    "char_end": 181,
    "directness": "direct"
  },
  "provenance": {
    "paper_title": "Sparse Attention Routing for Long-Document Summarization",
    "authors": ["Demo Author", "Second Author"],
    "year": 2026,
    "source_file": "sample.pdf",
    "source_sha256": "…",
    "version": "synthetic-demo-1",
    "section": "Abstract",
    "page": 1,
    "identifier": "demo:synthetic-paper"
  },
  "confidence": { "basis": "证据片段逐字回查一致", "level": "high" }
}
```

### `assertion`

| 字段 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `subject` | 是 | 自由文本 | 断言主体。**必须逐字出现在证据片段里**（大小写不敏感）；出现不了就要改写主语，或换成证据里真正出现的主体 |
| `relation` | 是 | 受控词表 | 见 `relation_vocab.json`；不在词表里报 `relation_not_in_vocab`（high） |
| `object` | 是 | 自由文本 | 断言客体。默认也要求能在证据里找到；归一化转述请加 `object_normalized: true` |
| `polarity` | 是 | `positive` / `negative` | 断言的肯定/否定方向。为 `negative` 而证据里没有否定线索 → `direction_conflict`（high） |
| `quantifier` | 否 | `unspecified` / `all` / `every` / `some` / `most` / `none` | 证据里有 all / never / 必然 之类绝对化用词而这里留空 → `absolutes_without_quantifier`（low） |
| `conditions` | 否 | 字符串数组 | 原文的 because / when / if / under / 样品范围 / 温度 / 预算等限定。证据含条件线索而这里为空 → `condition_dropped`（medium） |
| `statement` | 是 | 一句话 | 人能读的断言表述。一句话只讲一件事；含"和/以及"的并列请拆成多条 |
| `object_normalized` | 否 | `true` | 逃生阀：客体确属归一化转述（如把 `quadratically` 归一成 `quadratic growth`），显式声明后不再报 `object_not_in_evidence` |

### `evidence`

| 字段 | 必填 | 说明 |
|---|---|---|
| `src_id` | 是 | 取自 `work/sources.json`。**证据只能来自同一个 `src_id` 的 `text`** |
| `quote` | 是 | 逐字引用，含标点与大小写。长度须在 12–240 字符且不超过 2 句 |
| `char_start` / `char_end` | 是 | 该片段在 **source 文本**内的字符偏移（不是整页偏移）。用 `text.find(quote)` 定位最稳 |
| `directness` | 否 | `direct`（原文直接陈述）/ `indirect`（需要一步转述）。间接证据会写进 `unresolved` 提示人工确认 |

### `provenance`（"追得回"就靠它）

`paper_title` / `authors` / `year` / `source_file` / `source_sha256` / `version` / `section` / `page` 全部必填（`identifier` 可选）。任何一个为空 → `provenance_incomplete`（medium）。

### `confidence`

`basis` 必填（空则报 `confidence_without_basis`，low）：写清这条断言凭什么成立（逐字引用、表格数值、题注原文、一步归一化…）。`level` 取 `high` / `medium` / `low`。

## 2. 核验后新增的字段

`output/assertions.jsonl` 在保留上述结构之外追加：

| 字段 | 说明 |
|---|---|
| `nanopub_id` | `"np:" + sha256(subject\|relation\|object\|polarity\|src_id\|quote\|source_sha256)[:16]`。同样内容 → 同样 id（可作去重键） |
| `validation.status` | `ok` / `partial` / `failed` |
| `validation.issues[]` | 命中的检查项 `{issue, severity, detail}` |
| `validation.evidence_verified` | 证据是否逐字可回查（bool） |
| `validation.quote_chars` / `quote_sentences` | 证据长度与句数 |
| `validation.quote_cues` | 从**证据本体**重扫出的线索：`conditions` / `hedges` / `absolutes` / `negation` |

## 3. `sources.json` 的 source 单元

```json
{"src_id": "p1b4", "page": 1, "section": "Abstract", "kind": "body",
 "text": "We describe … a ruled table with numeric cells.",
 "chars": 243, "anchor": {"page": 1, "quote": "We describe …", "kind": "text"},
 "sha256_16": "…"}
```

`src_id` 命名规则：正文/题注 `p<页>b<块序号>`，表格行 `p<页>t<表序号>r<行序号>`；句子级候选另加 `s<句序号>`（`p1b4s2` = 第 1 页第 4 块第 2 句）。`kind` ∈ `heading` / `caption` / `body` / `table_row`。

## 4. `check.json`

```json
{"schema": "nanokit/1.0", "case_id": "…", "status": "ok",
 "metrics": {…见下…},
 "unresolved": [{"nanopub_id": "…", "why": "…", "action": "…"}],
 "sources_summary": {"sources": 21, "pages": 2, "source_file": "sample.pdf"}}
```

`metrics` 键：`assertion_count`、`candidates_available`、`candidates_used`、`candidate_coverage`、`quote_verified_rate`、`minimal_evidence_rate`、`relation_vocab_rate`、`provenance_complete_rate`、`condition_kept_rate`、`duplicate_rate`、`avg_statement_clauses`、`avg_quote_chars`、`with_issues`、`by_relation`、`by_source_kind`。

## 5. 受控关系词表

`references/relation_vocab.json`（schema `nanokit-relation-vocab/1.0`）定义 15 个关系与它们的中英线索词：

| relation | 含义 | 方向约定 |
|---|---|---|
| `increase` | 某量增大 | object 是**被测的量**，不是原因 |
| `decrease` | 某量减小 | 同上 |
| `no_effect` | 无显著影响 | 证据须有否定或"无差异"表述 |
| `cause` | 因果关系 | subject 是因，object 是果 |
| `correlate` | 相关（非因果） | 不要写成 cause |
| `measure` | 测量/记录某值 | object 是数值或可量化描述 |
| `compare` | 比较两个对象 | 差异方向写进 statement |
| `require` | 需要/依赖 | object 是被依赖项 |
| `compose` | 由…组成 | object 是成分清单 |
| `method_of` | 是…的方法 | subject 是方法，object 是目标 |
| `enable` | 使…成为可能 | — |
| `limit` | 限制/构成瓶颈 | — |
| `differ` | 与…不同 | object 是参照物 |
| `outperform` | 优于 | object 是参照方法 |
| `trade_off` | 与…存在权衡 | object 是被牺牲的一侧 |

词表可以替换：`nanoextract.py` 的 `load_vocab()` 按顺序找 `../references/relation_vocab.json`（相对脚本所在目录）与 `./references/relation_vocab.json`（相对当前工作目录），都找不到才用内置默认表。要换成自己的词表，把 `references/relation_vocab.json` 放进工作目录即可。
