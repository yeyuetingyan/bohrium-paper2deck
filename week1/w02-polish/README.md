# paper-polish

学术语言润色与校对 Skill：**润色后的完整文本 + 逐处修改说明 + 可核验的"没改坏"证明**。

## 它解决什么问题

语言润色最容易出的事故不是"改得不够好"，而是**改坏了没人发现**：把 `may` 改成 `will`（结论被加强）、把 `23.5%` 顺手写成 `24.5%`、把 `Table 1` 改成 `Table 2`、把 `caused by` 降级成 `associated with`、把否定词吃掉。这些改动在通读时几乎看不出来，却会直接改写论文的主张。

本 Skill 的做法是把润色拆成三件事，其中两件交给脚本：

| 步骤 | 由谁做 | 产物 |
|---|---|---|
| 1. 切段、清点不可变成分、列候选问题 | **脚本**（确定性） | `work/segments.md`、`work/issues.jsonl`、`work/glossary_draft.tsv` |
| 2. 逐段改写、写修改说明 | Agent（需要判断） | `revised.md`、`edits.jsonl`、`glossary.tsv` |
| 3. 硬核验 + 导出交付物 | **脚本**（确定性） | `diff.md`、`consistency.json`、`check.json`、`review.md`、`result.json` |

## 核验账本（第 3 步会算出来的数）

- `protected_total` / `protected_missing` / `protected_preserved_rate`：数字、单位、引用、交叉引用、公式、URL、DOI 的守恒率。
- `similarity` / `minimal_edit_rate`：改动幅度（越接近 1 越接近最小编辑）。
- `edits` / `edits_with_reason`：修改条数与带理由的条数。
- `unexplained_changes`：改后文本与原文不同、却没有对应说明的段落数。
- `terms_locked` / `terms_unified` / `term_unified_rate`：术语统一率。
- `issues_high|medium|low`：未通过项按级别计数。

## 快速开始

```bash
# 生成自带的合成样例（15 段论文草稿，内含 6 类刻意埋下的语言问题）
python examples/make_sample_manuscript.py out-demo

# 第 1 步
python scripts/polish_prep.py --case out-demo/case.json --out out-demo/work

# 第 2 步：Agent 依据 out-demo/work/segments.md 改写
#   产出 out-demo/revised.md、out-demo/edits.jsonl、out-demo/glossary.tsv
#   （仓库里的 examples/example_revised.md + example_edits.json + example_glossary.txt 就是一份"称职 Agent"的样例答卷）

# 第 3 步
python scripts/polish_assemble.py --case out-demo/case.json --work out-demo/work \
  --revised examples/example_revised.md --edits examples/example_edits.json \
  --glossary examples/example_glossary.txt --out out-demo/output
```

样例答卷的实测结果：`status=ok`、`protected_preserved_rate=1.0`、`similarity=0.937`、`edits=14`（全部带理由）、`term_unified_rate=1.0`、`issues_high=0`、`issues_medium=0`、`issues_low=1`（唯一一条 low 是"已在修改说明中声明"的 `always` 删除提示）。

## 反向样例：证明检查器真的会拦

`examples/example_rejected.json` 收录 9 个"只破坏一处"的案例，每个都写出了预期命中的检查项与实测结果：

| 案例 | 破坏方式 | 命中检查 |
|---|---|---|
| `b1_strength` | `may` → `will`（且标成 punctuation） | `hedging_strengthened` |
| `b2_number` | `23.5%` → `24.5%` | `protected_token_changed` + `number_invented` |
| `b3_crossref` | `Table 1` → `Table 2` | `protected_token_changed` |
| `b4_unexplained` | 改了段却没有说明 | `unexplained_change` |
| `b5_edit_before` | `before` 片段不是原文逐字 | `edit_before_not_found` |
| `b6_term` | 把统一后的术语改回漂移写法 | `term_not_unified` |
| `b7_no_edits` | 交空修改清单 | `edits_missing` |
| `b8_no_revised` | 只交清单不交全文 | `revised_missing`（退出码 2） |
| `b9_causal` | `caused by` → `associated with` | `causal_downgraded` |

## 文件地图

```
SKILL.md                        主文档：流程、协议、评分口径、降级约定
README.md                       本文件
scripts/polishkit.py            共用核：切句、线索词表、不可变成分、IO、契约回填
scripts/polish_prep.py          第 1 步：切段、候选问题、术语候选
scripts/polish_assemble.py      第 3 步：硬核验、导出、报告
examples/make_sample_manuscript.py  合成稿件生成器（纯标准库）
examples/example_*.{md,jsonl,tsv}   样例答卷与反向样例
references/                     字段字典、修改类型表、强度规则、核验规则
```

## 边界（本 Skill 不假装能做的事）

- 语法是否"真的改对"、语域是否真的贴合目标文体、改写是否仍是作者本意——**这些需要人工评审**，脚本只负责可机械比对的部分，`result.json` 的 `uncertainty` 里明写了这一条。
- 领域术语是否"译得对/用得对"不在核验范围，本 Skill 只保证**全篇一致**。
- 不从图片、补充材料、外部数据推断任何数值。

## 依赖

Python ≥ 3.9，纯标准库；仅当输入为 `.pdf` 时需要 PyMuPDF。
