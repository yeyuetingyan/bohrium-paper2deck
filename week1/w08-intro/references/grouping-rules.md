# 相关工作分组规则（grouping-rules）

"相关工作"最常见的失败形态是**逐篇摘要拼接**：五段话，每段一篇文献，段与段之间没有比较。
本文说明什么样的分组才算"分得清"，以及核验器会怎么查。

## 一、什么叫分组

一组 = **一个问题 / 一条技术路线 / 一类方法**下的一批文献，并且给出**比较维度**。

```json
{
  "group_id": "gr2",
  "dimension": "device-level engineering",
  "members": ["nguyen2021hysteresis", "jones2023peai"],
  "compare_on": "hysteresis suppression versus open-circuit voltage gain",
  "summary": "Hysteresis suppression improves measurement reliability while PEAI passivation raises the open-circuit voltage; both were demonstrated on single devices with a fixed growth route."
}
```

| 字段 | 要求 |
|---|---|
| `dimension` | 这一组是按**什么**聚到一起的（问题/方法/路线/场景），不能写"一些研究"。 |
| `members` | 组内文献，必须是文献表里的 key。 |
| `compare_on` | 这组文献**比的是什么**（效率 / 稳定性 / 制备通量 / 表征量…）。 |
| `summary` | 一段**带比较结论**的话：谁在哪方面更好、代价是什么、共同局限是什么。 |

## 二、核验器查什么

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `groups_missing` | high | 没有 `groups.jsonl`，或一条都没有。 |
| `group_members_missing` | high | 某组没有成员。 |
| `group_member_unknown` | high | 成员不在文献表里（疑似编造）。 |
| `group_dimension_missing` | medium | 没给 `dimension`。 |
| `group_comparison_missing` | medium | 没给 `compare_on`。 |
| `group_summary_short` | low | `summary` 太短（< 120 字符），大概率只是罗列。 |
| `group_summary_overclaim` | medium | `summary` 里出现 `best/highest/novel/always/first/最优/证明/总是` 这类绝对化词。 |
| `cited_work_not_grouped` | medium | 正文引用了某文献，但它没进任何分组（相关工作漏项）。 |

`cited_grouped_rate = |已分组 ∩ 已引用| / |已引用|`，全量覆盖为 1.0。

## 三、分组的四条纪律

1. **同一维度可比**：把"器件级工程"和"膜生长路线"放进同一组，比出来的结论没有意义。宁可多分两组，也不要混维。
2. **结论要有代价**：好的比较结论会写"谁强在哪、代价是什么"，例如"旋涂晶粒大但均匀性差"。只有褒奖没有代价，通常意味着没真比较。
3. **不要用绝对化词**：`best`/`novel`/`first` 不是比较，是宣称。核验器会点名。
4. **被引文献都要有归属**：正文里引到的文献，至少出现在一个组里；确实不适合分组的，在 `review.md` 里说明取舍。

## 四、常见错误对照

| 现象 | 检查项 | 修法 |
|---|---|---|
| 五段话、每段一篇文献 | `group_comparison_missing` + `group_summary_short` | 合并成"按维度分组"，每组一段带结论的比较 |
| 分组里塞了没引用的"陪衬"文献 | `group_member_unknown`（若是编造）/ `reference_uncited`（若是表内未引） | 要么真的引它，要么删掉 |
| 摘要句是"XX 等人研究了 A，YY 等人研究了 B" | `group_summary_short` | 补比较结论 |
| 摘要句写"这是目前最好的方法" | `group_summary_overclaim` | 改成可核对的具体比较 |

## 五、与空白的衔接

研究空白必须**从这里长出来**：`gaps.jsonl[].from_refs` 引的文献，应当正是上面某一组里"都做了什么但没做到什么"的那些条目。
若空白句引了某文献，而该文献既不在任何分组里、也没在正文出现过，核验器会在引用完整性与分组成熟度上同时留痕。
