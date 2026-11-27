# 核验规则（verification-rules）

`scripts/intro_assemble.py` 的检查项清单、判定口径、**刻意宽容处**与**刻意不检查处**。

## 一、结构

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `section_missing` | high | 四节（研究背景 / 相关工作 / 研究空白 / 贡献）缺一节。 |
| `section_order` | medium | 四节顺序不对。 |
| `section_too_short` | medium | 某节 < 80 字符（空转）。 |

## 二、引用完整性

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `citation_unresolved` | high | 正文引用了文献表里没有的条目。 |
| `reference_uncited` | medium（>1 条）/ low | 文献表里有条目未被正文引用（不是错，但需说明取舍）。 |
| `citation_map_missing` | medium | 没写 `citation_map.json`。 |
| `citation_map_entry_missing` | medium | 正文用到的条目在 `citation_map.json` 里没有。 |
| `citation_metadata_mismatch` | medium | `citation_map` 的年份/来源与 `.bib` 不一致。 |
| `citation_map_unknown_key` | high | `citation_map` 里的 key 不在文献表里（疑似编造）。 |

## 三、论断绑定

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `claims_missing` / `claim_row_invalid` | high | 没有 `claims.jsonl` / 行不是 JSON 对象。 |
| `claim_text_missing` | high | 论断没有 `text`。 |
| `claim_text_not_in_introduction` | high | 论断句在正文里找不到逐字对应。 |
| `claim_text_whitespace_variant` | low | 论断句与正文只差空白/标点（相似度 ≥ 0.92）。 |
| `claim_without_citation` | high | 背景/相关工作类论断既无引用也未标注为作者判断。 |
| `gap_claim_without_citation` | high | 「研究空白」小节的论断没有引用。 |
| `contribution_claim_without_citation` | low（有锚点）/ medium（无锚点） | 贡献句没有引用。 |
| `own_result_without_citation` | low（有锚点）/ medium（无锚点） | 本文结果句没有引用。 |
| `claim_marked_uncertain` | low | 无引用但显式标注为作者判断（可接受）。 |
| `claim_citation_unknown` | high | 论断引用了文献表外的 key。 |
| `claim_source_quote_missing` | medium | 没给逐字来源引文。 |
| `claim_source_not_in_material` | high | 来源引文在材料里找不到逐字对应。 |
| `claim_source_from_draft` | high | 来源引文来自正文而不是科研材料。 |
| `claim_number_not_in_material` | high | 论断里出现材料外的数字。 |

## 四、贡献

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `contributions_missing` | medium | 没有 `contributions.jsonl`。 |
| `contribution_text_missing` | high | 贡献条目没有 `text`。 |
| `contribution_anchor_missing` | high | 贡献条目没有锚点（正文/图表/结果）。 |
| `contribution_anchor_kind_unknown` | medium | 锚点 `kind` 不在允许集合内。 |
| `contribution_anchor_quote_not_found` | high | 锚点引文在正文里逐字找不到。 |
| `contribution_anchor_empty` | medium | 锚点存在但没有引文。 |
| `contribution_overclaim` | medium | 贡献句用了绝对化词（`first/best/novel/首次/最优`）。 |

## 五、分组

见 `grouping-rules.md`：`groups_missing` `group_members_missing` `group_member_unknown` `group_dimension_missing` `group_comparison_missing` `group_summary_short` `group_summary_overclaim` `cited_work_not_grouped`。

## 六、研究空白

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `gaps_file_missing` / `gap_statement_missing` | medium | 没有空白文件 / 条目没有 `statement`。 |
| `gap_without_refs` | high | 空白没有 `from_refs`。 |
| `gap_ref_unknown` | high | `from_refs` 里有文献表外的 key。 |
| `gap_filling_missing` | medium | 没有写 `how_filled`。 |

## 七、不变量

| 检查项 | 级别 | 触发条件 |
|---|---|---|
| `boilerplate_background` | low | 出现 `in recent years...` / `has attracted extensive attention` / `受到广泛关注` 这类空转套话。 |
| `number_not_in_material` | high | 正文里出现材料外的数字。 |
| `crossref_not_in_material` | low | 正文提到的图表指向在材料里找不到。 |
| `term_not_unified` | low | 同一术语在正文里有多种写法（同一篇里 `PCE` 与 `power conversion efficiency` 混用等）。 |

## 八、刻意宽容处（不算错）

- **编号与 key 混用**：正文写 `[3]`、分组写 BibTeX key，会被归一到同一条文献。
- **`23.5%` 与 `23.5 %`**：去空白与大小写后再比，视为同一成分。
- **标题格式**：`## 2. Related work`、`**Related Work**`、`相关工作` 都认。
- **贡献句/本文结果句没有引用**：只给 low 提示，前提是给了锚点。
- **文献表里有未引用条目**：只给提示；确实不适合引用的，在 `review.md` 说明取舍即可。

## 九、刻意不检查处（需要人工判断）

1. **论断是否真的被引文支持**——引文逐字存在，不等于它能支撑这句话。
2. **分组是否合理**——维度是否切得对、有没有更自然的分法。
3. **研究空白是否成立**——"没人做过"这类判断需要领域知识。
4. **贡献是否真有价值、是否与实验设计匹配**。
5. **转述语气是否忠实**——是否把"可能"写成了"表明"。
6. **语言质量**——语法、用词、句式，本 Skill 不做润色。

`check.json.unresolved` 与 `review.md` 里会把这些边界原文写出，避免"脚本全绿"被误读成"文章没问题"。

## 十、状态与退出码

| 条件 | `status` | 退出码 |
|---|---|---|
| 正文为空或缺失 | `failed` | 2 |
| 存在 high 级问题 | `partial` | 0 |
| 无 high | `ok` | 0 |

medium/low 不改变状态，但都会进 `check.json.issues` 与 `review.md` 的待处理清单。
