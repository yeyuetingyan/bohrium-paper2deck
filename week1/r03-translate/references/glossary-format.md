# 术语表格式（glossary.tsv）

## 为什么要有它

"术语一致"不能靠提示词祈祷，得靠一个**被执行的工件**：翻译前把译名定下来，翻译后按这个表逐条核对。本 Skill 的两个脚本都读它——`translate_prep.py` 用它合并既有译名，`translate_assemble.py` 用它算 `term_consistency_rate` 并检查每段是否落到了锁定译名。

## 文件形态

UTF-8、制表符分隔、**首行是表头**、无 BOM。列的含义：

| 列 | 必需 | 说明 |
|---|---|---|
| `term` | 是 | 源语言术语，原样照抄（含连字符、大小写、希腊字母） |
| `zh` | 建议 | 锁定译名。留空 = 不锁定；填写后全篇不得换译名 |
| `freq` | 否 | 在原文出现的次数（`prep` 自动统计） |
| `pages` | 否 | 出现的页码，逗号分隔（`prep` 自动统计） |
| `sections` | 否 | 出现过的章节标题，逗号分隔 |
| `status` | 否 | `suggested` / `needs_review` / `locked` / `skip` |
| `note` | 否 | 译法依据、为什么不译、与哪个术语联动 |

`zh` 为空时该术语不参与一致性检查；`status=skip` 表示"判定为普通词组，不锁定"。

## 例子

```tsv
term	zh	freq	pages	sections	status	note
perovskite solar cell	钙钛矿太阳能电池	12	1,2,3	Introduction,Results	locked	通行译名，与 perovskite 单用保持同一词根
passivation	钝化	9	2,3	Results	locked	"表面钝化"是固定搭配，不译"钝化处理"
stability	稳定性	15	1,2,3,4	-	locked	与 degradation 区分：前者是性质，后者是过程
degradation	衰减	8	2,3	Results	locked	材料语境下用"衰减"而不用"降解"
Ag/AgCl	Ag/AgCl	3	2	Methods	skip	电极名，保留原文
the as-prepared film	刚制备的薄膜	4	2	Methods	needs_review	原文含定冠词，译名待确认是否统一
```

## 从候选到锁定

`translate_prep.py` 产出的 `glossary_draft.tsv` 里 `zh` 是空的，`status` 只会是 `suggested`（多词短语、含后缀/连字符的术语、句中重复大写、高频长词）或 `needs_review`（出现 1–2 次的疑似术语）。**Agent 要做的就是把 `zh` 补齐**：

1. 先给 `suggested` 全部补译名；
2. `needs_review` 的逐条判断：是术语就补译名并把 `status` 改 `locked`；不是就把 `status` 改 `skip` 或直接删行；
3. 已经在上文锁定过的词根（例如 `passivation` 已定为"钝化"），派生词要与之呼应（`passivated surface` → "钝化表面"），把这条依赖写进 `note`；
4. 缩写第一次出现时给出"中文（英文缩写）"形式并锁定，后文只有缩写出现时不再重复展开。

## 一致性怎么算

对每个 `zh` 非空的术语：

- **出现段**：源文本中包含该术语（大小写不敏感、连字符与空格等价）的段；
- **命中段**：这些段的译文里出现了锁定译名（或其去掉"的/性"等后缀的稳定形式）；
- `term_consistency_rate = 命中段数 / 出现段总数`，按术语求平均；
- 未命中的段写进 `check.json.unresolved`，条目形如 `{"seg_id": "p2b9", "issue": "term_not_locked", "term": "passivation", "expect": "钝化"}`。

`term_consistency_rate < 1.0` 不代表必然有错——可能是术语出现在引文、公式或已是目标语言的段里。`review.md` 会把这类段连同原文、译文、期望译名一起列出来供人一眼确认。

## 与既有材料对接

若用户/上游已经有一份术语表（CSV、TB 混排、Excel 导出的 TSV），把它规整成本文件形态即可；用 `--glossary` 传给 `translate_prep.py`，它会把译名并进 `glossary_draft.tsv`（同 `term` 覆盖，并保留原 `note`）。这样"用户自己的译名习惯"优先于模型猜测。
