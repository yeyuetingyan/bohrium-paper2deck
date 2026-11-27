# PaperTranslate：术语锁定的段落级双语对照翻译 Skill

本目录是 **BOHRIUM 产品周赛·北化分站赛第一期** 阅读 03「文献翻译」的参赛作品（Skill 形态）。
公开仓库地址：<https://github.com/yeyuetingyan/bohrium-paper2deck/tree/main/week1/r03-translate>

## 一句话

把论文 PDF 变成**段落级双语对照 + 锁定术语表 + 译文核验清单**：先按语义边界切段并抽候选术语，锁定译名后逐段翻译，再用确定性脚本咬住数字、单位、引用、图表编号、公式、否定与限定的漂移。

## 为什么不是"直接让模型翻一遍"

科研翻译里真正被判"不行"的，几乎都不是"这句不优美"，而是这四类：

| 失败模式 | 典型样子 | 本 Skill 的应对 |
|---|---|---|
| 术语漂移 | 同一篇里 `passivation` 一会儿"钝化"一会儿"钝化处理" | 先产 `glossary_draft.tsv`，锁定 `zh` 列后才允许开译；`term_consistency_rate` 逐条量化 |
| 漏段 / 重译 | 跨栏跨页的段被吞掉，表格数字被正文和表格各译一遍 | 表格 bbox 先从正文挖掉，只作 `table_row` 段；折行接续自动合并；段号 `p<页>b<块>` 与原文一一对应 |
| 关系断裂 | `[12]` 变成"有研究指出"、`Table 3` 变成"表 2"、"未观察到差异"变成"观察到差异" | 数字多重集、引用标记、图表编号、否定线索四类不变量逐段比对 |
| 不可核验 | 交一份译文，说不出哪句依据什么 | 每段带锚点与 `note`；`review.md` 列出待人工确认项；`result.json` 记录 artifacts 的 sha256 |

## 目录结构

```
r03-translate/
├── SKILL.md                      Skill 主文档（触发条件 / 输入输出 / 三步流程 / 翻译协议 / 规则 / 降级）
├── README.md                     本文件
├── GITHUB_URL.txt                公开仓库链接（评审免登录可打开）
├── references/
│   ├── glossary-format.md        术语表格式与"从候选到锁定"的操作步骤、一致性算法
│   └── verification-rules.md     核验口径：每项检查的判据、刻意宽容处、刻意不检查处
├── scripts/
│   ├── paperkit.py               共用解析核：版面解析、段落/表格抽取、锚点、结果输出（与同系列 Skill 共用）
│   ├── translate_prep.py         切段 + 抽候选术语 + 自检（确定性，无模型调用）
│   └── translate_assemble.py     双语装配 + 不变量核验 + 出 result.json（确定性，无模型调用）
└── examples/
    ├── make_sample_paper.py      合成演示论文（纯标准库手写 PDF，不依赖任何真实文献）
    ├── example_case.json         最小 case（含 output_contract）
    ├── example_translations.json 18 段演示译文（带译法依据 note）
    └── example_glossary.txt      9 条锁定术语示例
```

## 怎么跑

```bash
SKILL=<本目录>

# 1) 切段 + 抽候选术语（确定性）
python "$SKILL/scripts/translate_prep.py" --case /input/case.json --out /app/work

# 2) 翻译：读 /app/work/segments.md，补齐 /app/work/glossary_draft.tsv 的 zh 列，
#    逐段翻译写入 /app/work/translations.json（格式见 SKILL.md「翻译协议」第 7 条）

# 3) 装配 + 核验（确定性）
python "$SKILL/scripts/translate_assemble.py" --case /input/case.json \
    --segments /app/work/segments.json --translations /app/work/translations.json \
    --glossary /app/work/glossary_draft.tsv --out /app/output
```

`--case` 缺省 `/input/case.json`，不存在时退化到 `/input` 下首个 `.pdf`，再退化到 `.md` / `.txt`。依赖只有标准库 + `PyMuPDF`（`fitz`）。

## 现场复现（本目录自带，非正式案例结果）

```bash
cd <本目录>
python examples/make_sample_paper.py /tmp/sample.pdf
python scripts/translate_prep.py --pdf /tmp/sample.pdf --out /tmp/work
python scripts/translate_assemble.py --segments /tmp/work/segments.json \
    --translations examples/example_translations.json \
    --glossary examples/example_glossary.txt --out /tmp/out
```

实测输出（Python 3.14.6 / PyMuPDF）：

```
prep     {"status":"ok","page_count":2,"segment_count":18,
          "by_kind":{"title":1,"body":7,"abstract":1,"heading":4,"table":1,"table_row":4},
          "candidate_terms":17}
assemble {"status":"ok","coverage_rate":1.0,"invariant_pass_rate":1.0,
          "term_consistency_rate":1.0,"negation_kept_rate":1.0,
          "terms_locked":9,"terms_with_hits":9}
```

`examples/` 里的原文由 `make_sample_paper.py` 现场合成，译文与术语表都是**演示样例**，用于说明接口与全流程；正式案例的原文与答案由评测平台提供。

## 输出物

| 文件 | 给谁看 | 内容 |
|---|---|---|
| `bilingual.md` | 人 | 段号 / 页码 / 类型 / 原文 / 译文 / 译法依据 / 待确认，逐段对齐 |
| `translation.zh.md` | 人 | 纯译文（保留段号），便于通读 |
| `translation.json` | 机器 | 段级结构 + 每段核验状态 |
| `segments.json` | 机器 | 段号 ↔ 页码 ↔ 原文 ↔ 不变量，供独立复核 |
| `glossary.tsv` | 人 | 锁定后的术语表（含出现次数、页码、状态、译法依据） |
| `check.json` | 机器 | 覆盖率 / 不变量通过率 / 术语一致率 / 否定保留率 / `unresolved` |
| `review.md` | 人 | 待人工确认清单（原文摘句 / 当前译文 / 期望 / 建议动作） |
| `result.json` | 平台 | `case_id` / `status` / `primary_result` / `evidence` / `uncertainty` / `artifacts`（含 sha256） |

## 诚实边界

- 自动核验**不覆盖**语义忠实度、学术语气、长句可读性，也不保证领域术语"译对了"——只保证"全篇一致"。这一条写在 `result.json.uncertainty` 里。
- 扫描件（无文字层）与加密 PDF 直接 `status=failed` 并说明原因，不臆造原文；页数超限截断会标为部分结果。
- 中英混排材料里已是目标语言的段落原样保留，不重复翻译。

## 作者与许可

北京化工大学 · 玻尔科学空间高校挑战赛北化分站赛参赛作品。
`paperkit.py` 为本系列 Skill 共用解析核（同时用于阅读 01 结构化解析、阅读 10 笔记生成），在本仓库 `week1/` 下各题目录中保持一致版本。
