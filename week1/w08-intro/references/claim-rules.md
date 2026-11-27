# 论断绑定规则（claim-rules）

引言里每一句实质判断都要落到两样东西上：**一条材料原文**（来源）与**一条参考文献**（引用）。
本文说明这两条绑定怎么给、核验器怎么查、哪些情况是允许的例外。

## 一、两种绑定

```
论断句 (claims.jsonl[].text)
├── source.quote  → 科研材料里的逐字片段（"事实从哪来"）
└── citations[]   → 文献表里的条目编号或 key（"谁说的"）
```

- `source.quote` 必须能在 `material.md`（或平台给的材料）里**逐字**找到；改一个词就算 `claim_source_not_in_material`。
- 材料之外的任何内容都不许写进正文：数字对不上会报 `number_not_in_material`。
- 引文**不能取自正文自己**（`introduction.md`）——那会报 `claim_source_from_draft`。这条是为了防止"自我引用式"的循环论证。

## 二、`claim_kind` 与引用要求

| `claim_kind` | 含义 | 引用要求 | 没有引用时 |
|---|---|---|---|
| `background_fact` | 领域背景事实 | 必须 | `claim_without_citation`（high） |
| `related_work` | 某文献做了什么 | 必须 | `claim_without_citation`（high） |
| `gap` | 研究空白/未解决问题 | **必须**（要由已引文献的缺口推出） | `gap_claim_without_citation`（high） |
| `contribution` | 本文贡献 | 不要求 | 有 `result_anchor` → low 提示；无 → medium |
| `own_result` | 本文结果 | 不要求 | 有 `result_anchor` → low 提示；无 → medium |
| `uncertain` | 明确标注为作者判断/待确认 | 不要求 | `claim_marked_uncertain`（low，可接受） |

判定顺序很重要：先看引用；没有引用时，再按"所在小节 + `claim_kind`"决定是 medium 还是 high。
**在「研究空白」小节里的断言，无论怎么写，都必须带引用**——空白的合法性完全由"已有文献没做到"来支撑。

## 三、论断句与正文必须逐字一致

`text` 会与 `introduction.md` 做归一化比对（压空白、去软连字符）：

- 完全一致 → 通过。
- 只差空白或标点 → `claim_text_whitespace_variant`（low）。
- 对不上 → `claim_text_not_in_introduction`（high）。

**为什么要逐字**：如果清单里的句子和正文里的句子不是同一句，那么"这条论断有来源"就成了空头支票——审稿人无法把两者对上。

## 四、数字与引用标记

- 论断句里的每个数字都会与 `source.quote` 和整份材料比对；材料里没有的数字报 `number_not_in_material`（high）。
- 材料里"数字 + 紧随引用"的绑定关系由 `number_citations.jsonl` 给出（如 `25%` 跟在 `[1]` 前），写论断时按这个对应关系挂引用，不要把 A 文献的数字挂到 B 文献上。
- 引用标记、单位、图表指向在 `protected` 里列出，属于**必须原样保留**的成分。

## 五、引用键的两种写法

正文里写编号 `[3]`、清单里写 `["n:3"]`，分组里写 `["chen2020stability"]` 都可以：核验器会把它们归一到同一条文献（`canon()`）。
但**归一不等于随便**：

- 编号必须来自 `references.json.census.positional_number_map`（或文献自带编号）；
- key 必须真实存在于文献表；
- 否则报 `claim_citation_unknown` / `citation_unresolved`（high）。

## 六、`result_anchor`：贡献句的"落点"

贡献句与本文结果句不需要引用（它们讲的是"我们做了什么"），但必须能落到正文或结果上：

```json
"result_anchor": {"section": "4. Contributions", "contrib_id": "k2",
                  "result": "device metrics",
                  "quote": "reaches 23.5% power conversion efficiency, an open-circuit voltage of 1.12 V"}
```

- 有锚点：核验器给一条 low 提示（提醒你"这里没有引用是正常的，但要确保锚点正确"）。
- 没有锚点：medium `contribution_claim_without_citation` / `own_result_without_citation`。
- 贡献条目自身的 `anchors[].quote` 必须能在正文里逐字找到，否则 `contribution_anchor_quote_not_found`（high）。

## 七、_quote 从哪来最稳

`facts.md` 每条材料句都给了 `anchor_text`——比整句更短、更容易逐字命中。**优先用 `anchor_text` 当 `source.quote`**，能少踩两类坑：

1. 整句里夹着别处也出现过的数字，容易被判"挂错绑定"；
2. 整句里的引用标记位置与你要引的文献不一致。

## 八、常见错误对照

| 现象 | 实际命中的检查项 | 修法 |
|---|---|---|
| 引文被"顺了一遍" | `claim_source_not_in_material` | 从 `facts.md` 复制 `anchor_text`，不要改写 |
| 引用写成 `[13]` 但文献表只有 12 条 | `citation_unresolved` | 核对 `positional_number_map` |
| 空白句写得很有力却没有引用 | `gap_claim_without_citation` | 加 `from_refs` 或用 `claim_kind: uncertain` 降级为作者判断 |
| 正文改了数字，清单没改 | `claim_text_not_in_introduction` | 两处一起改 |
| 引用来自自己刚写的正文 | `claim_source_from_draft` | 引文必须来自科研材料 |
