# 强度守恒规则（strength rules）

润色最容易造成实质伤害的地方，不是错别字，而是**悄悄改掉作者主张的强度**。本文件说明脚本如何判定"强度有没有被动过"，以及 Agent 该怎么做才算合规。

## 一、被跟踪的六类线索

| 类别 | 词表（节选） | 为什么重要 |
|---|---|---|
| **限定 hedge** | may, might, could, would, seems, appears, suggests, indicates, likely, probably, approximately, about, roughly, relatively, partially, 可能, 初步, 约, 大致, 较为 | 删掉限定词＝把"可能"说成"一定" |
| **绝对化 boost** | demonstrate, prove, establish, confirm, clearly, obviously, always, never, all, every, none, best, optimal, 证明, 总是, 从不, 所有, 最优, 必然 | 加上绝对化词＝把结论说死 |
| **量词 quantifier** | all, every, each, any, no, none, most, many, some, few, at least, 所有, 全部, 大多数, 仅, 部分, 每个, 任何, 均, 皆 | 改变覆盖范围（"多数样品"→"所有样品"） |
| **否定 negation** | not, no, never, neither, nor, without, fail, unable, 不, 未, 无, 非, 没有 | 漏掉一个 not ＝结论反转 |
| **条件 conditional** | if, unless, when, under, provided, assuming, in the case of, 若, 如果, 当, 在…条件下 | 丢掉条件＝把有条件的结论说成普适 |
| **因果 causal** | because, since, due to, caused by, leads to, results in, attributed to, 因为, 由于, 导致, 引起, 归因于 | 因果降级成相关 / 相关升格成因果，都是换主张 |
| **相关 correlational** | correlates with, associated with, related to, co-occurs, 相关, 关联 | 与因果互为"降级/升格"的两端 |

## 二、判定规则

### 1. 线索词"消失"才是改动
脚本对**同一段**比原文与改后文本，取原文线索词中"改后文本里连词形变化都不再出现"的那些（`shows` vs `show`、`indicates` vs `indicate` 视为同一词，不报）。

- 消失的是 **hedge** → `hedging_strengthened`
  - 已在修改说明里声明 → `low`（提示复核）
  - 未声明 → **`high`**（结论被加强了）
- 消失的是 **boost** → 未声明时 `hedging_softened_undeclared`（`medium`）
- 消失的是 **全称量词**（all/every/always/none/never/any/each/no/所有/全部/总是/从不/任何/每个/均/皆）→ 已声明 `low`，未声明 `medium`（`universal_quantifier_removed`）
- 新增全称量词 → `quantifier_strengthened`（**high**）
- 新增 boost → `boost_added`（**high**）
- **negation / conditional 计数下降** → `negation_lost` / `conditional_lost`（**high**），不分是否声明

### 2. "已声明"的判定口径
只有当消失的线索词**出现在该段落内 `hedging`/`register`/`clarity`/`word-choice` 四类修改条目的 `before` 片段里**（子串匹配），才算已声明。换句话说：

```json
{"seg_id":"p0012b1","type":"hedging","before":"clearly caused by","after":"attributed to","reason":"原文的 clearly 属于超出证据的断言，改为归因表述；因果方向不变"}
```

这一条同时做了两件事：把 `clearly` 的删除**声明**出来，并且说明**因果方向没有变**。

### 3. 因果与相关
- 原文有因果线索、改后只剩相关线索 → `causal_downgraded`（`medium`）
- 原文没有因果线索、改后出现因果词 → `correlation_upgraded`（**high**）

## 三、Agent 的合规做法

1. **默认不动强度**：语言润色的目标是"同一句话说得更规范"，不是"把话说得更硬/更软"。
2. 确实需要动强度时，**单独写一条 `hedging` 类型记录**，`reason` 里说明依据（例如"原文数据只支持相关性，故删去 caused by"）。
3. 不要用"顺手把 `may` 删掉读起来更利落"这类理由——`may` 是作者的立场，不是冗词。
4. 数字、单位、引用编号、图表指向与强度同等重要：它们是**不可变成分**，任何改动都会被 `protected_token_changed` / `number_invented` 拦下。

## 四、样例（合成稿件里刻意埋的对照）

| 位置 | 原文 | 合规改法 | 说明 |
|---|---|---|---|
| `p0012b1` | `clearly caused by` | `attributed to` + 一条 `hedging` 说明 | 削弱超出证据的断言，已声明 |
| `p0012b2` | `always reduces` | `reduces` + 一条 `hedging` 说明 | 去掉全称量词，已声明 |
| `p0012b3` | `may depend on` | **保持原样** | 限定词不得被删 |
| 反向案例 `b1` | `may depend on` → `will depend on` | ✗ | `hedging_strengthened`（high） |
| 反向案例 `b9` | `caused by` → `associated with`（无说明） | ✗ | `causal_downgraded`（medium） |
