# Paper2Deck：论文转学术 PPT Skill

把一篇论文 PDF 转成可编辑、可核验、可放映的学术汇报幻灯：抽取论文主线与图表，按"一页一主张"组织页面，在给定模板中填充占位符，输出 PPTX、讲稿备注、页级证据映射、渲染预览与 `result.json`。

本仓库为玻尔产品周赛（北化分站赛第一期）"论文转学术 PPT"赛题（`ppt-c7b80f0d`）的参赛作品，仅包含 Skill 本体与运行必需资源，不含任何预制案例答案或正式测试结果。

```text
.
├── SKILL.md                    # 入口：触发条件、输入输出、7 步流程、异常处理
├── README.md                   # 本文件：安装、依赖、用法、限制、维护
├── scripts/
│   ├── extract_paper.py        # PDF → paper.json + 裁剪图 + 表格渲染图
│   ├── validate_plan.py        # 页计划静态校验（硬约束不通过即 fail）
│   ├── build_deck.py           # plan.json → deck.pptx（内置版式 / 模板模式）
│   ├── render_preview.py       # pptx → PDF + 逐页 PNG（LibreOffice 优先，WPS 回退）
│   ├── check_deck.py           # 溢出、缺讲稿、页码越界、证据一致性自检
│   └── make_result.py          # 汇总为 result.json
├── references/
│   ├── plan-schema.md          # 页计划字段与约束
│   ├── outline-patterns.md     # 叙事骨架选择（问题—方法—证据—局限 等）
│   └── evidence-rules.md       # 证据映射与引用规则
└── examples/example_plan.json  # 4 页示意计划（示例数据，非正式案例结果）
```

## 1. 适用条件

- 输入为文本型论文 PDF；需要产出学术汇报（组会、答辩、会议）幻灯；
- 可选给定 PPTX/POTX 模板、页数上限、受众与时长；
- 不适用：扫描件（需先 OCR）、以科研绘图设计为目的的任务、论文语言润色。

## 2. 依赖与安装

| 依赖 | 版本要求 | 用途 | 缺失时 |
|---|---|---|---|
| Python | ≥ 3.9 | 全部脚本 | 无法运行 |
| `python-pptx` | ≥ 0.6.21 | 生成与检查 PPTX | 无法生成 |
| `lxml` | ≥ 4.9 | PPTX XML 字体、占位符处理 | 无法生成 |
| `Pillow` | ≥ 9.0 | 图片裁剪、表格渲染、文字度量 | 图片页降级为要点页 |
| `matplotlib`（仅取字体文件） | — | 提供 DejaVu 字体用于文字宽度度量 | 回退系统 Arial |
| `PyMuPDF`（`fitz`） | ≥ 1.23 | PDF 文本、图表、表格抽取与预览栅格化 | 抽取失败，`status=failed` |
| LibreOffice（`soffice`）或 Windows WPS | 任意近期版本 | PPTX → PDF → PNG 预览 | 预览缺失，`render.status=no_renderer` |
| 字体 | Arial（拉丁）、Noto Sans CJK SC（中日韩） | 版面度量与渲染一致 | 换机打开可能替换字体 |

安装：

```bash
python -m pip install python-pptx lxml pillow pymupdf matplotlib
# LibO/soffice：Ubuntu `apt-get install libreoffice-impress poppler-utils`；
#               macOS `brew install --cask libreoffice`；
#               Windows 安装 LibreOffice 或用 WPS（脚本走 COM 回退）
```

脚本只依赖标准库与上表第三方包，不访问网络，不写入 Skill 目录以外的位置（除输出目录）。

## 3. 调用方式

单次调用的最小流程（4 条命令，示例输出见 §6）：

```bash
SKILL=/path/to/this/repo
python "$SKILL/scripts/extract_paper.py" paper.pdf --out work/paper.json --figdir work/figures
# —— 此步由模型阅读 paper.json，按 references/plan-schema.md 写出 work/plan.json ——
python "$SKILL/scripts/validate_plan.py" work/plan.json --paper work/paper.json
python "$SKILL/scripts/build_deck.py" work/plan.json --out out/deck.pptx \
    --evidence out/evidence.json --template template.pptx      # 无模板则省略 --template
python "$SKILL/scripts/render_preview.py" out/deck.pptx --out out/preview --json out/render.json
python "$SKILL/scripts/check_deck.py" out/deck.pptx --plan work/plan.json \
    --paper work/paper.json --json out/check.json
python "$SKILL/scripts/make_result.py" --case-id CASE --deck out/deck.pptx \
    --plan work/plan.json --evidence out/evidence.json --check out/check.json \
    --render out/render.json --pdf out/preview/deck.pdf --out out/result.json
```

作为 Agent Skill 使用时，只需给出论文与要求（"把这篇论文做成 15 分钟组会汇报，按这个模板排版"），由 `SKILL.md` 的 7 步流程驱动；评测环境读取 `/input/case.json`，产物写入 `/app/output/`。

## 4. 输入与输出

输入（`case.json` 常见字段，缺失时的默认取值见 `SKILL.md`）：`paper_path`、`template_path`、`max_slides`（默认 10–12）、`audience`、`duration_min`、`output_contract`。

输出：

| 文件 | 内容 | 用途 |
|---|---|---|
| `deck.pptx` | 可逐页编辑的演示文件 | 交付主结果 |
| `preview/deck.pdf`、`preview/slide-*.png` | 渲染件 | 放映与版式复核 |
| `evidence.json` | 页级证据映射：页码 + 类型 + 标签 + 原文短句 | 核对"每页内容能否回溯" |
| `check.json` | 溢出、字号、讲稿、页码越界、证据一致性 | 自查记录 |
| `result.json` | `case_id`、`status`、`claims`、`evidence_map`、`artifacts`、`uncertainty`、`change_log` | 结构化结果，供复核与统计 |

## 5. 关键方法

1. **主线重写而非段落切分**：先按 `references/outline-patterns.md` 选叙事骨架（问题—方法—证据—局限），再把段落改写为每页一句可被论文支持的主张；标题不复述主张。
2. **证据先行**：每个内容页必须挂 `evidence`（页码 + 图/表/章节/正文 + 原文短句），页脚自动生成"来源：图 1 p.3 · 表 2 p.8"，与 `evidence.json` 一致；示意性论述标注"本页为分析，非原文结论"。
3. **数字不被改写**：表格单元格解析不可靠时，改用表格渲染图（`tab_*.png`）嵌入，保留原始排版、单位与小数位，不做"修正"。
4. **版面可容纳**：以真实字体度量（DejaVu/系统字体，CJK 按 1 em 估算）计算换行与行高，逐步缩小字号；仍放不下则报警告并建议改文案，不静默截断、不把正文压到 9 pt 以下。
5. **模板优先**：有模板时只填占位符，保留母版配色、页脚、页号与版式层级；无匹配版式才回退内置 16:9 版式，并在 `warnings` 与 `uncertainty` 中说明。
6. **讲稿与页面分离**：`notes` 写过渡、强调点与被追问时的补充证据，不复述页面文字（`validate_plan.py` 对"备注等于标题"给出警告，`check_deck.py` 对缺讲稿给出警告）。

## 6. 最小调用示例

`examples/example_plan.json` 是一份 4 页示意计划（标题页 + 问题 + 结果 + 结论），其中文本与页码均为**示例数据，不是正式案例结果**：

```bash
python scripts/validate_plan.py examples/example_plan.json
python scripts/build_deck.py examples/example_plan.json --out /tmp/demo.pptx
```

预期：`validate_plan` 返回 `{"schema":"plan-check/v1","status":"pass",...}`；`build_deck` 生成 4 页 PPTX 并输出 JSON，含 `status`、`out`、`slides`、`template`（是否套用模板）、`warnings`、`body_sizes`（各页实际正文字号）。

## 7. 限制与已知边界

- 仅处理文本型 PDF；扫描件需先 OCR（评测环境提供 OCR 工具，本 Skill 不内置）；
- 多栏排版、公式图片化时章节切分可能偏粗，需人工核对 `paper.json` 的 `sections`/`figures`；
- 模板模式依赖占位符语义（标题/正文/图片），非标准模板会回退内置版式并记录 warning；
- 4:3 模板拉伸为 16:9 时占位符坐标不会自动换算，属模板自身问题，脚本按母版原坐标填充；
- 不判断论文结论的科学正确性，只保证"转写忠实、可回溯、可复核"；
- 渲染一致性已在 **Windows + WPS COM** 上实测（11 页、0 溢出）；LibreOffice 分支在同一套脚本内实现但未在容器环境实测，字体缺失时 PDF 可能替换字形，需按 `preview/slide-*.png` 复核。

## 8. 失败处理与自查

| 情况 | Skill 行为 | 自查方法 |
|---|---|---|
| PDF 加密/损坏 | `status=failed` + `reason=encrypted_pdf`，不生成占位内容 | 看 `result.json.status` |
| 图形抽不出 | 该页降级为要点页，`uncertainty` 记录影响页 | `check.json` 与 `uncertainty` |
| 表格解析错列 | 改用表格渲染图，不重排数字 | 对照 `paper.json.tables[].image` |
| 占位符不足 | 回退内置版式 + warning | `warnings` 字段 |
| 页数超限 | `validate_plan` 报错（硬门）；`build_deck` 仅作兜底截断并记 warning，应在计划阶段按页数上限合并次要页 | `validate_plan` 的 `max_slides` 校验 |
| 无渲染器 | `render.status=no_renderer`，不伪造预览 | `render.json` |
| 文字溢出 | 缩字号至下限后报 warning，不静默截断 | `check.json.per_slide[].overflow` |

自查顺序固定为：`validate_plan` → `build_deck` → `render_preview` → `check_deck` → `make_result`；任一步 `fail`/`error` 先修再继续，预算内先落一版可打开的 8 页再增量改进。

## 9. 版本与维护

- 版本：v0.1（2026-11-24）；已验证的端到端用例：arXiv:1706.03762《Attention Is All You Need》，15 页 PDF → 11 页 PPT，2 图、4 表、16 条证据、渲染 11 张 PNG，`plan-check`/`deck-check` 均 pass。
- 变更记录随 `result.json.change_log` 输出；脚本接口保持"一个脚本一件事"，新增版式在 `build_deck.py` 内按 `type` 扩展，不改调用方式。
- 外部工具出处：字体度量用 matplotlib 自带 DejaVu；渲染走 LibreOffice 命令行或 Windows WPS COM（`Kwpp.Application`）；PDF 解析用 PyMuPDF（`fitz`）。以上均为通用开源组件或本机已装软件，无私有依赖、无网络调用。

## 10. 许可

本作品供赛事评审与复用；第三方组件遵循其原始许可。
