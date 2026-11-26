# 修改类型表（edit taxonomy）

`edits.jsonl` 的 `type` 只能取下列 10 个值之一，取其它值会被判 `edit_type_unknown`（medium）。分类的意义是：**让评审一眼看出这处改动是"形式"还是"主张"**——越是靠近主张的类型，核验越严。

| type | 中文 | 判定口径（什么算这一类） | 典型例子 | 是否计入"强度声明" |
|---|---|---|---|---|
| `grammar` | 语法 | 主谓一致、时态、单复数、冠词、介词搭配 | `results shows` → `results show`；`a investigations` → `an investigation` | 否 |
| `syntax` | 句法 | 语序、从句结构、悬垂修饰、平行结构 | `Comparing the samples, the efficiency was higher` → `Comparing the samples, we found a higher efficiency` | 否 |
| `punctuation` | 标点 | 逗号/分号/冒号/连字符/引号、标点前后空格、逗号拼接 | `,however,` → `, however,`；`Fig 2` → `Fig. 2`（**注：`Fig. 2` 本身属于不可变成分，形式统一要改在同一处并写进 reason**） | 否 |
| `word-choice` | 用词 | 词义不贴、搭配不当、中式搭配、冗余动词 | `conduct an investigation of` → `investigate`；`make a conclusion` → `conclude` | 是 |
| `terminology` | 术语 | 按锁定术语表统一写法、缩写首次出现补全称 | `spin coating` → `spin-coating`；`PSC` → `perovskite solar cells`（首次出现处） | 否 |
| `register` | 语域 | 口语/套话/翻译腔 → 学术书面语；句式冗长松散 | `In recent years, with the rapid development of…` → 直接陈述；`It is worth noting that` → 直陈 | 是 |
| `hedging` | 限定 | 明确改变主张强度（加强或削弱），**必须单独成条** | `clearly caused by` → `attributed to`；`always reduces` → `reduces`；`may` → `could` | 是 |
| `clarity` | 清晰度 | 指代不明、长句切分、逻辑连接词补全，不改主张 | 拆句、把 `this` 明确成 `this passivation strategy` | 是 |
| `consistency` | 一致性 | 同一概念在全文中的写法/单位/大小写/编号统一（非术语表覆盖范围） | `PCE` 与 `power conversion efficiency` 混用；`behaviour`/`behavior` 混用 | 否 |
| `no-change` | 未改动 | 语句经检查确认无需修改，**仅用于说明"这处我看过且不改"**，`before` 必须等于 `after`；若两者不同会被判 `no_change_claim`（medium） | — | 否 |

## 四条硬规则

1. **一处修改一条记录**：不要把同一段里的多处改动合成一条（`before`/`after` 会跨过无关文本，核验容易误判）。同一句里的多处改动写多条，`seg_id` 相同即可。
2. **`before`/`after` 必须逐字**：必须是原文/改后文本里真实存在的连续片段，不是转述。空白差异会降级成 `edit_before_whitespace_variant`（low），但若核验脚本在去空白后仍找不到，就是 `edit_before_not_found`（high）。
3. **`hedging` 类型是强度改动的"声明"**：`hedging` 与 `register`/`clarity`/`word-choice` 四类（合称 `STRENGTH_TYPES`）的 `before` 片段构成"已声明"集合。删掉 `may`/`clearly`/`always` 这类线索词时，只有该词**出现在这四类修改的 `before` 片段里**，才按"已声明"记 low；否则记 high/medium。
4. **不可变成分不得改动**：`before` 里出现数字/单位/引用/交叉引用时，`after` 必须逐字一致（`23.5 %` ≡ `23.5%`），否则 `edit_protected_changed`（high）。确实需要统一 `Fig 2` → `Fig. 2` 时，请在 `reason` 里写明"仅为格式统一，编号未变"。

## 与核验脚本的对应

| 违规 | 检查项 | 级别 |
|---|---|---|
| 类型不在上表 | `edit_type_unknown` | medium |
| 缺 `seg_id`/`type`/`before`/`after` | `edit_field_missing` | high |
| `seg_id` 不在 `segments.json` | `edit_seg_unknown` | medium |
| `before`/`after` 找不到 | `edit_before_not_found` / `edit_after_not_found` | high |
| 仅空白差异 | `edit_before_whitespace_variant` / `edit_after_whitespace_variant` | low |
| `reason` 不足 6 字符 | `edit_reason_too_short` | low |
| `no-change` 的 `before` ≠ `after` | `no_change_claim` | medium |
| 条目自身改了数值 | `edit_protected_changed` | high |
| 修改清单缺失或为空 | `edits_missing` | high |
