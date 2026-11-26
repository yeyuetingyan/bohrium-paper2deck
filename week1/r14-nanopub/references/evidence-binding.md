# 证据定位方法

这个 Skill 的"对得上"只认一件事：**证据片段能在原文里逐字找到**。本文件说明定位怎么做、为什么这样做、以及遇到问题时先查哪里。

## 1. 为什么是"逐字"而不是"意思对得上"

如果允许改写的证据，核验就退化成了模型自证：Agent 说什么就是什么，下游无法回查。逐字引用把"可信"从**自述**挪到**可复现的字符串比对**上——任何人拿 `src_id` + `char_start/char_end` 都能在原文里把那一小段抠出来看一眼。所以核验器对证据的唯一态度是逐字比对，没有"语义相似"这条路。

## 2. 三级定位

| 级别 | 手段 | 何时用 |
|---|---|---|
| 1 | `itemgetter("text")` 精确比对 `quote` 与 `sources[i].text` 的切片 | 常规 |
| 2 | 归一化后比对（压空白、去标点、去软连字符、大小写折叠）| 原文含换行/连字符/hyphenation |
| 3 | 全文搜索 `source["text"].find(quote)` 找回偏移 | 偏移记错了但内容对 |

核验器实际的行为：

- 级别 1 命中且偏移正确 → 通过，`quote_whitespace_variant` 不报。
- 只在级别 2 命中 → `quote_whitespace_variant`（low）：内容对，但空白或标点与原文不同（常见于跨行断句）。
- 级别 3 命中但 `char_start/char_end` 与真实位置不符 → `quote_offset_wrong`（medium）：内容对、位置错，下游点击回查会落空。
- 三级都不中 → `quote_not_found`（high）：这条断言的证据是改写或臆造的，必须重写。

## 3. 推荐的操作顺序

1. 打开 `work/candidates.md`，每条候选下面都有 ```` ```text ```` 代码块，**块里就是逐字原文**，直接复制，不要手打。
2. `src_id` 与建议的字符区间也印在候选下面（"影射证据位置：1 页 / p1b4 / 字符 61–181"）。复制原文后，偏移用 `text.find(quote)` 重算最稳：

   ```python
   import json
   src = {s["src_id"]: s for s in json.load(open("work/sources.json", encoding="utf-8"))["sources"]}
   s = src["p1b4"]; q = "The document contains a title block, …"
   start = s["text"].find(q)
   assert start >= 0, "这句不在该 source 里，换片段"
   print(start, start + len(q))
   ```

3. 一个 `src_id` 装不下你要说的意思时，**不是**把两个 source 拼起来当证据，而是拆成两条断言，各自绑定自己的片段。

## 4. 片段大小

- 上限 `MAX_QUOTE = 240` 字符且 ≤2 句：超了报 `quote_not_minimal`（medium）。整段照抄会让你看起来"有证据"，但下游无法判断到底哪句话支撑了断言。
- 下限 `MIN_QUOTE = 12` 字符：太短报 `quote_too_short`（medium），比如只抄一个数字（`28.4`）而不带它所在的表格行或句子。
- 表格行例外：表格行的 `text` 用 ` | ` 连接单元格（`Full attention | 28.4 | 412`），这类证据短是正常的，`quote_too_short` 不会报——但要在 `statement` 里写清它来自哪张表的哪一行。

## 5. 主体与客体的落地

- `assertion.subject` 必须能在证据里逐字找到（大小写不敏感）→ 否则 `subject_not_in_evidence`（medium）。
- 常见踩坑：证据写 `Both are layout artefacts…`，主体却写 `Both failure modes` —— 原文没有"failure modes"这几个字。**改成原文里真有的词（`Both`）**。
- 证据写 `latency grows linearly`，主体写 `latency growth` —— 词形不同。改成 `latency`。
- 客体同理，但允许归一化：把 `quadratically` 归一成 `quadratic growth` 是合理的，显式写 `object_normalized: true` 即可（报 low 的 `object_not_in_evidence`）。

## 6. 反向核验（"证据真的支撑这条断言吗"）

逐字比对只能证明"原文说了这句话"，证明不了"这句话支撑你这个判断"。所以还有几个联动检查：

- `direction_conflict`（high）：断言 `polarity: negative`，而证据本体里没有任何否定线索（not / no / without / 不 / 无 / 未 …）。
- `verify_direction`（low）：断言写肯定，但证据本体含否定线索（`not measured`）——提示核对否定作用的对象是不是被正确转述了。
- `condition_dropped`（medium）：证据本体有条件线索（`Because the budget is fixed`），而 `assertion.conditions` 是空的。
- `overbroad`（medium）：证据里有模糊限定（may / suggest / typically / 往往），断言却写成无限定的绝对判断，且没给 `confidence.basis`。

线索扫描**直接扫证据片段本体**，不依赖候选阶段标注——这是刻意的：只要证据里有"because"，丢条件就一定会被抓到，与上游怎么分类无关。
