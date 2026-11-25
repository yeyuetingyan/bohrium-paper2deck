# PaperParse：文献文档解析 Skill

把科研 PDF 还原成**可回溯的结构化 Markdown**：标题层级、段落顺序、GFM 表格、图表题注与图片、页码锚点，附块级锚点表与自检报告。属于玻尔产品周赛北化分站赛第一期「阅读01｜文献文档解析」参赛作品，只含 Skill 与运行资源，不含预制案例答案。

## 1. 适用条件

- 输入是文本型论文 PDF（期刊、会议、预印本），要求转 Markdown / 结构化文本；
- 关注双栏顺序、页眉页脚、章节层级、表格行列、图表题注、逐块定位；
- 不适用：扫描件（需 OCR）、公式 LaTeX 还原、语义理解与结论抽取（那是别的题）。

## 2. 依赖

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | ≥ 3.9 | 运行 |
| PyMuPDF（`pymupdf`/`fitz`） | ≥ 1.23（实测 1.28/2.1） | 文本层、词框、表格几何、页面渲染 |
| 字体 | 无要求 | 仅输出 PNG 与 Markdown，不排版 |

```bash
python -m pip install pymupdf
```

无网络调用、无外部服务；只在输出目录写文件。

## 3. 调用

```bash
python scripts/parse_document.py --case /input/case.json --out /app/output
# 或
python scripts/parse_document.py --pdf paper.pdf --out out --max-pages 40
```

`case.json` 字段容错：`paper_path` / `pdf` / `input.paper` 均可；`max_pages` 限页；`output_contract` 的字段会原样保留在 `result.json`（缺失的字段填 `null` 并写入 `uncertainty`）。

## 4. 产物

| 文件 | 说明 |
|---|---|
| `document.md` | 正文 Markdown，页起始 `<!-- page N -->`，表格为 GFM，不可靠表格为图片 + 说明 |
| `blocks.json` | 块级锚点（`p3b12` 形式），含 page / kind / quote / hash |
| `figures/*.png` | 图与不可靠表格的页面渲染图（180 dpi） |
| `check.json` | 逐页块数、空页、表格可用性、扫描页、题名/作者、被剔除的版式行数 |
| `result.json` | `case_id` / `status` / `primary_result` / `evidence` / `uncertainty` / `artifacts` |

## 5. 方法要点

1. **行 → 段**：PyMuPDF 按 span 取字并保留空白 span（否则单词间空格丢失），再按行距与列归属聚段；
2. **栏序**：整宽行切分带，带内左栏在前右栏在后；单页需两栏各≥3 行才判双栏，避免误切；
3. **版式噪声**：跨页重复的短行、页边纯页码、出版方声明（permission/copyright/arXiv 戳记）剔除并计数；
4. **表格**：表格几何来自 `page.find_tables()` 的单元格矩形，**单元格文本按原文词框重建**，再逐格做可靠性判定；不可靠即降级为渲染图，宁缺不错；
5. **锚点**：每块记录页码与内容哈希，`quote` 取前 160 字符，供人工或下游程序回查。

## 6. 限制与已知边界

- 数学公式保留为文本，上标/希腊字母可能与原文形式不同（例如 `d2` 实为 `d²`），这类差异写入 `uncertainty` 的通用说明而不逐条列；
- 无框线、列宽随内容浮动的表格多数会降级为图片；有横线的三线表通常可还原；
- 参考文献按 `[n]` 编号起条，跨页续行可能合并为一条，需抽查；
- 中文 PDF 的栏序判定同样适用，但中西文混排的行内空格可能与原版面略有差异；
- 仅实测于英文 arXiv 论文（Attention Is All You Need, 15 页，双栏、4 表 2 图），其他版式需按 `check.json` 复核。

## 7. 自查

跑完先看 `check.json`：`empty_pages` 应为空、`scanned_pages` 应为空、`tables_markdown + tables_as_image` 等于表数；再看 `document.md` 的标题列表是否与论文目录一致；最后抽查 3 个 `blocks.json` 条目，按页码回原文核对 `quote`。

## 8. 维护

- 版本 `paperkit/1.0`（2026-11-25）；解析内核在 `scripts/paperkit.py`，任务入口在 `scripts/parse_document.py`；
- 新增版式支持只需扩展 `PDFDoc.ordered()/paragraphs()`，不改调用接口；
- 已知用例：arXiv:1706.03762（15 页，双栏，4 表 2 图，311 块，29 个标题，1 表可还原、3 表降级为图）。
