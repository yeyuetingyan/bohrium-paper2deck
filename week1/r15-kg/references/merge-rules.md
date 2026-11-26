# 合并规则（merge-rules）

跨篇图谱最容易出错的不是"漏抽"，而是**错误合并**。本文件给出合并的判断标准、四类典型陷阱，以及核验器会怎么记账。

## 一、什么情况下可以合并（`decision: merge`）

同时满足才合并：

1. **同一对象**：两处写法指向同一个科研对象，而不是"看起来像"。
2. **原文可证**：至少一条位置证据能说明二者是同一对象（缩写定义句、全称/缩写对照、同一段的同位语等）。
3. **条件不冲突**：合并的是**实体本身**，不是它带条件的数值结论。同名指标在不同条件下测得的数值永远不能合并。
4. **给出依据**：`reason` 写清依据，`evidence` 给位置；跨篇合并要写 `cross_paper: true`。

常见的可合并情形：

| 情形 | 例子 | 依据来源 |
|---|---|---|
| 全称与缩写 | `methylamine (MA)` ↔ `MA` | 缩写定义句（`ACRONYM_DEF_RE` 候选 `mc-*`） |
| 同一物质的不同书写 | `MAPbI3` ↔ `CH3NH3PbI3` ↔ `Methylammonium lead iodide` | 原文对照出现 |
| 同一方法的别名 | `X-ray diffraction` ↔ `XRD` | 缩写定义句 |

## 二、什么情况下必须分开（`decision: keep_separate`）

| 陷阱类型 | 候选 kind | 例子 | 为什么不能合并 |
|---|---|---|---|
| 同名指标、条件不同 | `same_metric_different_conditions` | 两篇都写 `T80`，一篇 45% RH、一篇 85% RH | 合并等于把两套条件与数值糊成一个结论（触发 `merge_across_conditions`，HIGH） |
| 同名不同物 | `same_metric_different_conditions` / 手工 | 一篇的 `MA` 指 methylamine，另一篇的 `MA` 指 methylammonium（A 位阳离子） | 名字相同、对象不同 |
| 跨篇趋势相反 | `cross_paper_tension` | 一篇说"湿度导致衰减"，另一篇说"封装后 1000 h 不衰减" | 这是**分歧**，要保留而不是平均 |
| 通用术语但样品不同 | 手工 | 两篇都做"旋涂钙钛矿"，但分别是 MAPbI3 与 Cs0.05FA0.95PbI3 | 相同通用方法/材料术语**不代表**同一物理样品、模型实例、数据集或实验条件 |
| 同篇多格式 | — | 同一篇的 XML 与 Markdown | **不算跨篇证据**，不能拿来支持"跨篇一致" |

`keep_separate` 也必须逐条给理由（`keep_separate_without_reason`，MED）。候选号写法最稳：

```json
{"decision": "keep_separate", "members": [], "candidate_ids": ["mn-002"],
 "reason": "同名指标 efficiency 在两篇的报告条件不同（45% RH vs 85% RH），不得合并",
 "evidence": [{"source_id": "synth-primary-0001", "paragraph_id": "p-2-003", "quote": "45% relative humidity"}]}
```

## 三、核验器怎么记账

`check_merges()` 会：

1. 逐条核验裁决行的字段、成员数、证据位置。
2. 统计 `merge_candidates` / `merge_addressed`；**未裁决的候选**记 `merge_candidate_unaddressed`（MED）。
3. 生成 `conflicts_preserved`：把"prep 发现的冲突候选"与"Agent 显式 keep_separate 的记录"合并成一张清单，连同证据一起写进 `graph.json.must_not_merge`。查询 `type=conflicts` 直接读它。
4. 对 `decision=merge` 的行，检查同名指标是否跨条件合并（`merge_across_conditions`，HIGH）。

## 四、一个可照抄的裁决骨架

```jsonl
{"decision":"merge","members":["MAPbI3","CH3NH3PbI3"],"canonical":"MAPbI3","cross_paper":false,
 "reason":"原文以 CH3NH3PbI3 全称定义后统一使用 MAPbI3，同一物质",
 "evidence":[{"source_id":"synth-primary-0001","paragraph_id":"p-1-002","quote":"Methylammonium lead iodide (CH3NH3PbI3)"}]}
{"decision":"keep_separate","members":["T80"],"candidate_ids":["mn-001"],"cross_paper":true,
 "reason":"两篇的 T80 报告条件不同（45% RH vs 85% RH），数值与结论不得合并",
 "evidence":[{"source_id":"synth-primary-0001","paragraph_id":"p-2-003","quote":"T80"}]}
```

要点：**合并的兴趣点在于"证明是同一个"，而不是"看起来是同名"**。说不清就分开——分开只会少一条合并，错误合并会污染整张图谱。
