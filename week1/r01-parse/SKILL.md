---
name: paper-parse-md
description: 把科研 PDF 解析成带页码锚点的结构化 Markdown（标题层级、段落、GFM 表格、图表题注与图片、页眉页脚剔除），并输出块级锚点表、自检报告与 result.json。当任务要求"文献文档解析""PDF 转 Markdown/文本""提取章节与表格""保留原文定位"或给出论文 PDF 要求逐段可回溯的解析结果时使用。
---

# PaperParse：文献文档解析（PDF → 可回溯 Markdown）

一页 PDF 被正确读出来，至少要满足四件事：**提得全**（不漏行、不把页眉页脚混进正文）、**排得对**（双栏按栏序、跨栏分段）、**拆得清**（标题层级、表格行列）、**核得回**（每块能指回页码）。本 Skill 只做这四件事，不解释论文的科学含义，也不生成结论。

## 何时触发

- 输入是论文 PDF，要求转成 Markdown、纯文本、结构化 JSON 或"可继续加工"的文档；
- 要求保留章节层级、表格、图注、页码定位；
- 评测环境给出 `/input/case.json`（可能含 `paper_path`、`max_pages`、`output_contract`）。

## 输入

- `/input/case.json`：字段名不固定，`paper_path` / `pdf` / `input.paper` 都可能是论文路径；`max_pages` 限制页数；`output_contract` 是需要回填的字段名。
- 同目录的 `task.md`：以题面为准。
- 找不到 `case.json` 时，脚本在 `/input` 下取第一个 `.pdf`。

不要依据 `case.json` 里的领域标签推断论文内容；只读实际文件。

## 输出（写到 `/app/output/`）

```
output/
├── document.md      # 结构化 Markdown：<!-- page N --> 锚点、标题层级、段落、GFM 表格、图表
├── blocks.json      # 块级锚点：id / page / kind / hash / quote（逐块回溯）
├── figures/         # 图与"结构不可靠表格"的页面渲染图（PNG）
├── check.json       # 自检：逐页块数、空页、表格可用性、扫描页、题名与作者
└── result.json      # case_id / status / primary_result / evidence / uncertainty / artifacts
```

## 流程

```bash
SKILL=/skills/weekly-skill          # 或本目录
python "$SKILL/scripts/parse_document.py" --case /input/case.json --out /app/output
```

一次调用完成解析、自检与结果组装。参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--case` | `/input/case.json` | 不存在时自动退化到 `--pdf` 或 `/input` 下首个 PDF |
| `--pdf` | 由 case 解析 | 直接指定论文 |
| `--out` | `/app/output` | 输出目录 |
| `--max-pages` | 60 | 超出部分截断并在 `warnings` 记录 |

## 解析规则（评分要点）

1. **栏序**：以行中线判定左右栏；整宽行（>72% 页宽）作为分带边界，带内先左栏后右栏。跨栏标题与通栏图不会串栏。
2. **页眉页脚**：跨页重复出现且位于页面上/下 8% 的行、纯页码行判为版式信息剔除，剔除条数记入 `check.json.running_head_lines_dropped`。
3. **标题层级**：编号（`3.1`）决定层级；`Abstract/Introduction/...` 等规范词为一级；加粗短行（不含邮箱、符号、冒号结尾）为候选标题。章节号被排成独立一行时与下一行合并。
4. **表格**：先用 PyMuPDF 定位表格几何，再**按单元格矩形回收原文词序**重建单元格（`23.75` 不会被拆成 `23` 与 `.`）。无横线的三线表若一个单元格压着多行，按基线拆行。重建结果逐格做可靠性检查（列数、空单元、拆开的小数点、跨行括号、多行挤压）；不可靠则改为**页面渲染图 + 题注 + 明确说明**，绝不输出可能改写数值的表格。
5. **图表**：过滤图标级小图（<90×60 pt），按题注邻近关系绑定编号；题注折行按"未以句末标点结束"续接。
6. **页锚点**：每页起始写 `<!-- page N -->`，配合 `blocks.json` 的 `page + block id` 可定位到块。
7. **诚实边界**：无文字层的页记入 `uncertainty`（需 OCR，本次不伪造内容）；加密 PDF 直接 `status=failed`；页数超限截断并记录。

## 证据与回溯

`blocks.json` 每条记录含 `id`（如 `p3b12`）、`page`、`kind`（heading/paragraph/table/figure）、`quote`（前 160 字符）、`hash`（内容哈希）。`result.json.evidence` 取图、表、标题块的前 40 条，形如：

```json
{"page": 8, "kind": "table", "block": "p8b7", "quote": "The Transformer achieves better BLEU scores ..."}
```

核对方式：按 `page` 打开 PDF 对应页，按 `quote` 检索即可确认该块真实存在。

## 异常处理

| 情况 | 处理 |
|---|---|
| PDF 加密 | `status=failed`，`reason=encrypted_pdf`，不生成占位内容 |
| 无文字层/扫描页 | 该页无块，`uncertainty` 标注页码，提示需 OCR |
| 表格结构不可靠 | 渲染图 + 题注 + 说明；`check.json` 计入 `tables_as_image` |
| 页数超限 | 截断并在 `warnings` 记录，`status=partial` |
| `case.json` 缺失 | 退化到 `/input` 首个 PDF；仍找不到则 `status=failed` |
| 双栏误判 | 单页栏数判定要求每栏至少 3 行；不足则按整页 y 序输出 |

## 自检

`check.json` 中应满足：`empty_pages` 为空（除扫描页）、`blocks_per_page` 每页 > 0、`figures` 与论文图号数量相当、`tables_markdown + tables_as_image` 等于检测到的表数。`status` 为 `ok` 仅当无扫描页且无空页。

## 最小示例

`examples/example_case.json` 指向一份本地 PDF，可直接跑：

```bash
python scripts/parse_document.py --case examples/example_case.json --out /tmp/demo
```

示意输出见 `examples/expected_shape.json`（**示例数据，不是正式案例结果**）。

## 限制

- 只处理文本型 PDF；扫描件需先 OCR（评测环境提供 OCR 工具，本 Skill 不内置）；
- 数学公式按文本原样保留（上下标可能降级为普通字符），不做 LaTeX 还原；
- 无框线且列宽随内容变化的表格可能被判为不可靠，此时给渲染图而非重排；
- 参考文献逐条提取依赖编号格式，跨页续行可能合并，需人工抽查。
