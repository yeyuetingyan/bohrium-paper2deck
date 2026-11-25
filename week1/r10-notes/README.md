# PaperNotes：文献总结与结构化笔记 Skill

把论文 PDF 变成**与原文结构对齐、每条可回查**的笔记：论文卡片、章节笔记、研究问题、数据、前提条件、含数值的关键发现、局限、术语表、检索索引。属于玻尔产品周赛北化分站赛第一期「阅读10｜文献总结与结构化笔记」参赛作品，只含 Skill 与运行资源，不含预制案例答案。

## 1. 适用条件

- 输入是文本型论文 PDF，要求做摘要、笔记、论文卡片、章节总结、知识点清单；
- 关心"笔记与论文自身章节是否对得上""每条结论能否回到原文"；
- 不适用：扫描件（需 OCR）、公式语义解释、跨论文比较与综述写作（属于上层任务）。

## 2. 依赖

| 组件 | 版本 | 用途 |
|---|---|---|
| Python | ≥ 3.9 | 运行 |
| PyMuPDF（`pymupdf`/`fitz`） | ≥ 1.23（实测 1.28） | 文本层、词框、块序、表格几何 |

```bash
python -m pip install pymupdf
```

无网络调用、无外部服务；只在输出目录写文件。

## 3. 调用

```bash
python scripts/build_notes.py --case /input/case.json --out /app/output
python scripts/build_notes.py --pdf paper.pdf --out out --max-pages 40
```

`case.json` 字段容错：`paper_path` / `pdf` / `input.paper` 均可；`max_pages` 限页；`output_contract` 的字段会原样保留在 `result.json`（缺失字段填 `null` 并写入 `uncertainty`）。

## 4. 产物

| 文件 | 说明 |
|---|---|
| `notes.md` | 人读版：论文卡片、结构树、章节笔记、关键发现表、条件、局限、术语表、自查 |
| `notes.json` | 机器可读：`sections[]`（标题/层级/页码/块/笔记）+ `fields{}` + `captions[]` |
| `anchors.json` | 全部笔记的锚点（page / block / quote / hash） |
| `concepts.json` | 术语：缩写、定义句、连字符复合词、中文高频术语，含首次出现位置 |
| `index.json` | 倒排索引（词 → 块号），上限 4000 词，用于后续检索 |
| `check.json` | 自检：锚点命中率、字段覆盖、结构识别、扫描页、被跳过的章节 |
| `result.json` | `case_id` / `status` / `primary_result` / `evidence` / `uncertainty` / `artifacts` |

## 5. 方法要点

1. **块 → 章节**：先按页取块（保留全文，不用截断的摘要字段），再按版式标题切章；标题层级来自编号（`3.2.1` = 三级）。公式行、项目符号行、句尾带句号的正文句、摘要中的单个加粗词一律不算标题；题名与作者区不建章节。
2. **笔记 = 原文句子 + 锚点**：脚本不做同义改写，`text` 是句中逐字文本，`anchor.quote` 是同一句，`anchor.hash` 是块文本前 16 位哈希。这样"笔记与原文是否一致"可以机器校验，而不是靠自述。
3. **字段靠线索词，不靠猜测**：研究问题、数据、条件、发现、局限各有一组中英双语线索；命中与否写入 `field_coverage`，缺失就报缺失。
4. **数值只从正文取**：抽数值前剔除 `[13]` 这类引用编号；表格题注句（`Table 2: ...`）不计入发现，避免把表头当结论。
5. **参考文献不产笔记**：`References` / `致谢` 章节只记条数（`check.json.skipped`）。
6. **中文支持**：中文按句号/分号切句（阈值 18 字），标题允许 2 字（"摘要"），术语用 3–5 字高频组合并去掉被更长术语包含的片段。

## 6. 实测记录（2026-11-25，本机）

真实论文（公开 PDF，仅本地解析，未联网；"笔记"为逐字摘录的完整句，半句碎片已剔除）：

| 论文 | 页 | 识别章节 | 笔记 | 锚点命中 | 发现 | 术语 |
|---|---|---|---|---|---|---|
| Attention Is All You Need | 15 | 29 | 123 | 123/123 | 5 | 24 |
| RAG (arXiv 2005.11401) | 19 | 50 | 209 | 209/209 | 10 | 55 |
| BERT (arXiv 1810.04805) | 16 | 43 | 226 | 226/226 | 10 | 58 |
| JMLR 19-346（蒙特卡洛梯度估计） | 62 | 76 | 372 | 399/400 | 10 | 37 |
| JMLR 20-1364（Stable-Baselines3） | 8 | 7 | 53 | 53/53 | 2 | 14 |

边界样本（合成，用于验证失败路径）：

| 样本 | 结果 |
|---|---|
| 无章节标题的两页文档 | `partial`，单节 24 条笔记，`structure=false` |
| 中文论文（摘要/引言/方法/结果/结论，逐行排布） | `ok`，6 节 5 条笔记，题名与作者正确；逐行排版时跨行句会被截短 |
| 扫描件（无文字层） | `failed`，`reason=no_text_layer`，提示需 OCR |
| AES-256 加密 PDF | `failed`，`reason=encrypted_pdf` |

唯一一处锚点未命中（JMLR 19-346，400 条中的 1 条）已在 `check.json.anchor_invalid_examples` 中列出原句与块文本，供人工复核。

## 7. 限制

- 笔记是原文摘录，不做压缩；需要更短的摘要时，应由上层 Agent 在引用这些条目的前提下改写，而不是由脚本臆造；
- 角色标签（目的/方法/结果/局限）是线索词给出的候选，`notes.md` 顶部已注明需复核；
- 表格与图的正文不进入笔记，只记录题注；
- 双栏论文的栏序由解析层处理，极端版式（跨栏插图的旧排版）仍可能错序，`check.json` 的块序可用于复核；
- 公式只按文本保留，不做 LaTeX 还原。

## 8. 自查

1. `check.json.anchor_valid == anchor_checked`（否则看 `anchor_invalid_examples`）；
2. `field_coverage` 五项是否有 false——有就说明该论文没有报告，或线索词没覆盖，需人工看对应章节；
3. `section_titles` 与论文目录逐条对照，多出来的多半是标题误判，少了的多半是标题被版式吞掉；
4. 抽查 `notes.md` 中 3 条发现，按 `[p12b345]` 回原文核对数值。

## 9. 维护

- 版本 `noteskit/1.0`（2026-11-25）；解析内核 `scripts/paperkit.py`，笔记逻辑 `scripts/noteskit.py`，入口 `scripts/build_notes.py`；
- 增补线索词只需改 `noteskit.py` 顶部的正则常量，不动流程；
- 新增版式支持改 `heading_ok()` / `clean_headings()`，并在 `examples/` 增加对应样本说明。
