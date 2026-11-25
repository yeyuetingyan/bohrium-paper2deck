---
name: paper2deck
description: 把一篇科研论文 PDF 转成可编辑、可核验的学术汇报幻灯：抽取论文主线与图表，按"一页一主张"组织页面，生成保留模板版式的 PPTX 与讲稿备注，输出页级证据映射、渲染预览与 result.json。当任务要求"论文转 PPT""组会/答辩汇报""paper to slides""学术汇报幻灯片"，或给定论文 PDF（可带模板、页数与时长约束）要求产出演示文稿时使用。
---

# Paper2Deck

把连续的论文叙述改写成页级的学术表达：**每页一个主张，主张背后挂论文中的图、表或结论，并能在给定模板里放映与编辑。**

不要做的事：不做论文精读结论的生成，不做科研绘图美化，不做语言润色；不要提交预制答案。

## 何时触发

- 输入含 `paper.pdf`（或论文路径）与"做成 PPT / slides / 汇报"的要求；
- 评测环境给出 `/input/case.json`，字段含论文、模板、页数上限、受众、时长、`output_contract`；
- 用户要求"按模板排版""保留图表编号""带讲稿备注"。

## 输入

优先读 `/input/case.json` 与 `task.md`，不要凭字段名猜内容：

| 字段（常见命名） | 含义 | 缺失时 |
|---|---|---|
| `paper_path` / `pdf` / `input.paper` | 论文 PDF 绝对路径 | 在 `/input` 下找唯一 `.pdf` |
| `template_path` / `template` | 模板 PPTX/POTX | 无模板，使用内置版式 |
| `max_slides` / `slide_count` | 页数上限 | 默认 10–12 页 |
| `audience` / `duration_min` | 受众、时长 | 默认"同领域研究生，15 分钟" |
| `output_contract` | 必须回填的字段 | 以 `result.json` 的 `claims`/`evidence_map` 为准 |

只读取实际文件；`case.json` 中的领域标签不能当作论文内容的证据。

## 输出（写到 `/app/output/`）

```
output/
├── deck.pptx          # 可编辑演示文件（必需）
├── deck.pdf           # 渲染件（有渲染器时必需）
├── preview/slide-*.png
├── evidence.json      # 页级证据映射
├── result.json        # 结构化结果（case_id、status、claims、artifacts、uncertainty）
└── check.json         # 自检报告
```

## 流程

设 `SKILL` 为本文件所在目录，`W=/app/work`，`O=/app/output`。

**1. 抽取论文结构**（一次调用，产出机器可读事实）

```bash
python "$SKILL/scripts/extract_paper.py" "$PAPER" --out "$W/paper.json" --figdir "$W/figures"
```

得到 `sections`（带页码）、`figures`（裁好的 PNG + 图注 + 页码）、`tables`（单元格 + 渲染图）、`page_text`。
加密 PDF 返回 `status=error, reason=encrypted_pdf`：直接报告，不要伪造内容。

**2. 读 `paper.json` 写 `plan.json`**（唯一的"创作"步骤，由模型完成）

先读 `references/outline-patterns.md` 选叙事骨架，再按 `references/plan-schema.md` 写页计划。硬约束：

- 每页 `claim` 是一句可被论文支持的主张；标题不复述 claim；
- 内容页 3–5 条要点，每条 ≤ 60 字，层级 ≤ 2；
- 每个内容页必须有 `evidence`，且 `page` 为整数页码；
- `notes` 不复述页面文字，写"过渡 + 强调 + 可能被追问的补充证据"；
- 数字、单位、方法名、图号必须来自 `paper.json`；不确定就写进 `uncertainty`，不要凑。

**3. 校验计划**

```bash
python "$SKILL/scripts/validate_plan.py" "$W/plan.json" --paper "$W/paper.json"
```

`status=fail` 必须改完再继续；提前失败比生成一份错版便宜。

**4. 生成 PPTX**

```bash
python "$SKILL/scripts/build_deck.py" "$W/plan.json" --out "$O/deck.pptx" \
  --evidence "$O/evidence.json" ${TEMPLATE:+--template "$TEMPLATE"}
```

- 有模板：走模板模式，只填模板占位符，保留母版配色、页脚与页号；找不到合适版式才回退内置版式（会在 `warnings` 里说明）。
- 无模板：内置 16:9 版式，自动按真实字体度量收缩字号，不静默截断。

**5. 渲染预览**

```bash
python "$SKILL/scripts/render_preview.py" "$O/deck.pptx" --out "$O/preview" --json "$O/render.json"
```

优先 LibreOffice，Windows 回退 WPS COM。`status=no_renderer` 时保留 PDF 缺失的说明，不要假装渲染过。

**6. 自检**

```bash
python "$SKILL/scripts/check_deck.py" "$O/deck.pptx" --plan "$W/plan.json" \
  --paper "$W/paper.json" --json "$O/check.json"
```

报告溢出、缺讲稿、页码越界等问题。溢出优先改文案或减要点，不要靠缩到 9pt 以下。

**7. 组装结果**

```bash
python "$SKILL/scripts/make_result.py" --case-id "$CASE_ID" --deck "$O/deck.pptx" \
  --plan "$W/plan.json" --evidence "$O/evidence.json" --check "$O/check.json" \
  --render "$O/render.json" --pdf "$O/deck.pdf" --out "$O/result.json" \
  --status ok
```

必须如实填 `status`：`ok` / `partial`（如缺渲染、缺图）/ `failed`。`uncertainty` 写清缺什么、影响哪一页。

## 页计划要点（详见 references/plan-schema.md）

```json
{"deck": {"max_slides": 10, "template": null, "short_title": "…"},
 "slides": [
   {"id": "s2", "type": "bullets", "kicker": "01 · 问题", "title": "…",
    "claim": "…", "bullets": [{"text": "…", "level": 0}],
    "notes": "…", "evidence": [{"page": 2, "kind": "section",
    "label": "Introduction", "quote": "原文短句"}]}]}
```

`type` ∈ `title | section | bullets | figure | table | comparison | closing`。
图页用 `figure`（`path` 指向 `paper.json` 里的 `image`），表页优先用表格渲染图放进 `figure`，单元格解析不可靠时不要硬填 `table`。

## 证据规则（评分核心）

1. 一条证据 = 页码 + 类型（figure/table/section/text）+ 标签 + 原文短句；
2. 图注、表注原样保留编号与单位，不改写数值；
3. 示意图不得当作实验数据陈述；他人的结果不得写成"本文结果"；
4. 页脚自动生成"来源：图 1 p.3 · 表 2 p.8"，与 `evidence.json` 一致；
5. 自己的推断（如"外推能力有限"）必须标注"本页为分析，非原文结论"。

## 异常处理

| 情况 | 处理 |
|---|---|
| PDF 加密/损坏 | 报告 `failed`，说明原因，不生成占位内容 |
| 图片抽不出 | 用要点页替代，`uncertainty` 记录，不编造图像 |
| 表格解析错列 | 用表格渲染图（`tab_*.png`），不做"修正" |
| 模板占位符不足 | 回退内置版式，在 `warnings` 与 `uncertainty` 说明 |
| 页数超限 | 合并次要页（背景→方法），保主线：问题-方法-结果-局限 |
| 字体缺失 | 正文 Arial / Noto Sans CJK SC，导出后检查换行与溢出 |
| 无渲染器 | 保留 `render.json` 的 `no_renderer`，不伪造预览 |

## 预算与自保

评测预算通常为 64 次模型调用、900 秒、单次 16384 token。建议：抽取 1 次、写计划 1–2 次、构建/检查 ≤ 3 轮。**先落一版可打开的 8 页，再增量改进**；每轮都覆盖 `output/`，不要留半成品。

## 最小示例

`examples/example_plan.json` 是一份 4 页的示意计划（标题页 + 问题 + 结果 + 结论），其中的文本与页码均为**示例数据，不是正式案例结果**。可直接：

```bash
python "$SKILL/scripts/validate_plan.py" "$SKILL/examples/example_plan.json"
python "$SKILL/scripts/build_deck.py" "$SKILL/examples/example_plan.json" --out /tmp/demo.pptx
```

## 限制

- 只处理文本型 PDF；扫描件需先 OCR（评测环境提供 OCR 工具，本 Skill 不内置）；
- 复杂多栏排版、公式图片化时，章节切分可能偏粗，需人工核对 `paper.json`；
- 模板模式依赖占位符语义（标题/正文/图片），非标准模板可能回退内置版式；
- 不负责论文结论的正确性，只负责"转写忠实 + 可核验"。
