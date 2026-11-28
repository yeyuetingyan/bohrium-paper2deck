# plan.json 规范

`build_deck.py` 的输入。所有字段大小写敏感，路径相对 `plan.json` 所在目录。

> 也可以先用 `plan_assist.py <paper.json> --out plan.json` 生成一份**已通过校验的骨架**，再让模型改写措辞、补 `notes`。骨架里的要点都在写入前用"去空白近似匹配"回查过页文本，查不到的不产出；`assist.json` 会列出 `next_steps` 与 `warnings`（例如某章未识别、某表注定位不到）。

## deck

| 字段 | 类型 | 说明 |
|---|---|---|
| `short_title` | str | 页脚左端文字，建议 ≤ 56 字符（按词边界截断） |
| `kicker` | str | 标题页顶部小字，如"组会汇报" |
| `max_slides` | int | 页数上限，超出会被截断并告警 |
| `template` | str/null | 模板路径；命令行 `--template` 优先 |
| `audience` / `duration_min` | str/int | 写入 result.json，供评审对照 |

## slides[]

公共字段：`id`（唯一）、`type`、`kicker`、`title`、`claim`、`notes`、`evidence`。

- `claim`：本页主张，一句陈述句。`figure/table/comparison` 页未给 `subtitle` 时，claim 会显示为副标题。
- `notes`：40–120 字，讲稿。不复述要点，写过渡、强调与追问预案。
- `evidence`：`[{page:int, kind:"figure|table|section|text|equation", label:str, quote:str}]`。

### type = title

| 字段 | 说明 |
|---|---|
| `title` | 论文标题（原文，不求翻译） |
| `subtitle` | 一句中文副标题：方法名 + 做了什么 |
| `authors` / `venue` | 作者、期刊会议与年份 |
| `takeaway` | 一句话结论，≤ 30 字 |

### type = bullets

| 字段 | 说明 |
|---|---|
| `bullets` | `[{text, level}]`，3–5 条，level 0/1 |
| `side` | 可选 `{title, text}`，右侧主张卡片，text ≤ 60 字 |

### type = figure

| 字段 | 说明 |
|---|---|
| `figure` | `{path, label:"Figure 1", caption, clip?, page_size?}` |
| `bullets` | 可选 2–4 条读图要点，显示在右侧 |
| `subtitle` | 可选；**若与标题末尾重复建议留空**（构建器会自动去重，避免双行标题压住副标题） |

`path` 用 `paper.json` 中 `figures[].image`；表格渲染图（`tab_*.png`）也走这里，`label` 写 `"Table 2"`。
`clip`（`{x0,y0,x1,y1}`，PDF 坐标）与 `page_size`（`[width,height]`）来自 `paper.json`，构建时按比例裁掉图注与邻栏；缺省则整图等比缩放。

### type = table

| 字段 | 说明 |
|---|---|
| `table` | `{rows: [[...]], header: true, label, caption}` |

仅当单元格解析可信时使用；多级表头、跨列合并常被解析错，改用表格渲染图。

### type = comparison

| 字段 | 说明 |
|---|---|
| `columns` | `[{title, items:[{text}]}]`，2–3 栏，每栏 3–4 条 |

适合"本文 vs 基线""编码器 vs 解码器""优点 vs 局限"。

### type = section

| 字段 | 说明 |
|---|---|
| `number` | 章节号，如 "02" |

### type = closing

| 字段 | 说明 |
|---|---|
| `title` | 常用"谢谢，欢迎讨论" |
| `claim` | 一句话总结 |
| `footer` | 材料来源（作者、会议、arXiv 号） |

## 完整示例

见 `examples/example_plan.json`。校验命令：

```bash
python scripts/validate_plan.py plan.json --paper paper.json
```

常见错误：缺 `claim`、`evidence.page` 不是整数、`figure.path` 不存在、页数超 `max_slides`。
