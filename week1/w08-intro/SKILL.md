---
name: paper-intro
description: 依据科研材料与文献库撰写论文的「引言与相关工作」。当需要写研究背景、相关工作综述、研究空白或贡献陈述，并且要求"每条论断都能追溯到材料原文与参考文献"时使用；也适用于检查已写好的引言是否存在引用解析不到、引文被改写、数字材料外、引用未分组、贡献缺锚点等问题。产出可直接进入论文的四节正文 + 逐条论断的引用绑定与来源定位 + 引用元数据对照 + 自动核验报告。
---

# 引言与相关工作写作（paper-intro）

把"科研材料 + 文献库"变成**可直接进入论文的四节正文**，并让每一句话都能回查到来源。

## 何时使用

- 需要写论文的引言、相关工作、研究空白、贡献四节，且必须以给定材料与文献为依据。
- 需要核对一份已有的引言：引用是否都能解析、引文是否被顺手改写、数字是否来自材料、相关工作是否真的做了分组比较、贡献是否有锚点。
- 需要把"文献 → 分组 → 比较 → 空白 → 贡献"这一整条链条显式留痕，供审稿人或合作者逐条复核。

## 输入

平台把输入挂到 `/input/case.json`，常见字段：

| 字段 | 说明 |
|---|---|
| `material_path` / `material_text` | 科研材料（.md/.txt/.tex/.pdf/.docx），或直接内联文本。也可与 case 同目录放 `material.md` 等（见 `references/field-dictionary.md` 的兜底文件名表）。 |
| `bibliography_path` | 文献库（`.bib`），或内联的文献数组。 |
| `audience` / `genre` / `language` | 目标读者、文体、语言。 |
| `format_constraints` | 格式约束（引用制式、数字写法等）。 |
| `output_contract` | 需要交付的字段，核验器按它回填 `result.json`。 |

工作目录 `/app/work`，产物写 `/app/output`。

## 三步流程

### 第一步：`scripts/intro_prep.py`（确定性，不调用模型）

```bash
python scripts/intro_prep.py --case /input/case.json --out /app/work
```

产出（都在 `/app/work`）：

- `facts.jsonl` —— 可引材料句，每条带 `fact_id`/`sent_id`/`para_id`/`text`/`anchor_text`/`score`/`reasons`/`cues`/`protected`。
- `facts.md` —— 人/Agent 读的清单：逐条原文 + **必须原样保留**的数字·单位·引用标记 + 文献记录 + 编号映射 + 数字-引用绑定对。
- `references.json` —— `{count, records[], census{positional_number_map, numbering_basis, ...}}`。
- `ref_groups.jsonl` —— 文献聚类候选（按共享内容词与同一来源），供分组参考。
- `gap_candidates.jsonl` / `contribution_candidates.jsonl` —— 空白与贡献候选。
- `terms.jsonl` —— 术语与缩写候选。
- `number_citations.jsonl` —— 材料里"数字 + 紧随引用"的绑定对。
- `context.json` / `prep.json` / `prep_check.json` —— 上下文、下一步指令、自检项。

**编号映射**：文献表若不带编号，`census.numbering_basis` 会写成 `positional`，并按条目出现顺序给出 `positional_number_map`。这是**可复核的假设**，不是原文事实，写正文时要按它对齐。

### 第二步：Agent 写六份交付物到 `/app/work`

| 文件 | 内容 |
|---|---|
| `introduction.md` | 四节正文：研究背景 / 相关工作 / 研究空白 / 贡献（标题可用中文或英文，需按此顺序）。 |
| `claims.jsonl` | 逐条论断：`claim_id`/`claim_kind`/`text`/`citations`/`source{para_id,quote}`，贡献句与本文结果句另给 `result_anchor`。 |
| `contributions.jsonl` | 贡献条目：`contrib_id`/`text`/`anchors[{kind,ref,quote}]`。 |
| `groups.jsonl` | 相关工作分组：`group_id`/`dimension`/`members[]`/`compare_on`/`summary`。 |
| `citation_map.json` | 编号 → 文献元数据（`key`/`bibtex_key`/`authors`/`year`/`venue`/`title`/`doi`）。 |
| `gaps.jsonl` | 研究空白：`gap_id`/`statement`/`from_refs[]`/`how_filled`。 |
| `terms.jsonl` | 术语与缩写统一表（可选但推荐）。 |

### 第三步：`scripts/intro_assemble.py`（确定性，硬核验 + 导出）

```bash
python scripts/intro_assemble.py --case /input/case.json --work /app/work --out /app/output
```

产出 `introduction.md`、`citation_map.json`、`claims.jsonl`、`contributions.jsonl`、`groups.jsonl`、`gaps.jsonl`、`diff.md`、`check.json`、`review.md`、`result.json`；退出码 `0`=ok/partial，`2`=材料不可用或缺少正文。

## 写作协议（七条）

1. **先读 `facts.md` 再动笔**：每条论断选一条 `fact_id`，`source.quote` 必须能在材料里逐字找到。
2. **引用只用文献表内的条目**：正文写编号 `[3]`，分组写 BibTeX key 都可以，核验器会把两者归一到同一条文献。
3. **数字与单位原样保留**：材料里的 `23.5%`、`1000 h`、`45%` 照抄；不得出现材料外数字。
4. **相关工作按维度分组比较**，不要逐篇摘要拼接：每组给 `dimension`/`compare_on`/`summary`，`summary` 里要有比较结论与局限。
5. **空白必须由已引文献推出**：`from_refs` 至少一条真实文献，并写清 `how_filled`。
6. **贡献必须给锚点**：贡献句本身不需要引用，但 `anchors` 要指向正文小节或某个结果。
7. **不美化、不夸口**：`first/best/novel/always/首次/最优` 这类词会被 `overclaim` 检查点名；证据不足的论断写成"作者判断"（`claim_kind` 落在 uncertain 类）而不是事实句。

## 核验口径

`check.json` 的 `issues[]` 分 high/medium/low 三级，覆盖：

- **结构**：四节是否齐全、顺序、是否过短。
- **引用**：正文引用能否解析到文献表、文献表里哪些未被引用、`citation_map` 是否缺条目 / 元数据是否与 `.bib` 不符 / 是否出现表外 key。
- **论断**：论断句是否逐字出现在正文里、来源引文是否来自科研材料（而不是正文自己）、引文是否被改写、gap 句有没有引用、数字是否在材料里、引文里出现却未登记的数字。
- **贡献**：是否有锚点、锚点引文能否逐字定位、是否用了夸大词。
- **分组**：成员是否在文献表内、是否给了比较维度与比较结论、`summary` 是否夸大、被引文献是否有未分组项。
- **空白**：是否给出 `from_refs`、是否都能解析、是否写了 `how_filled`。
- **不变量**：空转套话（`in recent years...`/`受到广泛关注`）、材料外数字与图表指向、术语不统一。

`result.json` 顶层含 `schema`/`case_id`/`status`/`primary_result`/`evidence`/`uncertainty`/`artifacts`（逐文件 sha256）/`change_log` + 契约字段（`introduction`/`claims`/`contributions`/`groups`/`citation_map`/`check`/`review`）+ `issues`。

## 自动核验的边界（写进 `check.json.unresolved`）

自动核验**只覆盖可机械比对的部分**：

- ✅ 引用能否解析、引文是否逐字在材料里、数字是否材料外、分组与贡献是否给维度与锚点、术语是否统一。
- ❌ **论断是否真的被引文支持**、分组是否合理、空白是否成立、贡献是否真有价值——这些必须人工判断。

因此 `check.json` 全绿不代表文章写得好，只代表**没有可机械发现的硬伤**。

## 依赖

- Python ≥ 3.9，纯标准库。
- 读 `.pdf` 材料需要 `PyMuPDF`（`pip install pymupdf`）；`.docx` 走标准库 zipfile，无需额外依赖。
- **调用脚本时设置 `PYTHONDONTWRITEBYTECODE=1`**，避免 `__pycache__` 混入提交包。

## 最小调用示例

```bash
# 0) 依赖
export PYTHONDONTWRITEBYTECODE=1

# 1) 确定性预处理
python scripts/intro_prep.py --case examples/example_case.json --out /app/work

# 2) Agent 按 facts.md 写 introduction.md / claims.jsonl / contributions.jsonl /
#    groups.jsonl / citation_map.json / gaps.jsonl

# 3) 硬核验 + 导出
python scripts/intro_assemble.py --case examples/example_case.json --work /app/work --out /app/output
```

`examples/` 里给出了同一案例的完整输入与产出（`example_material.md`、`example_bibliography.bib`、`example_introduction.md`、`example_claims.jsonl`、`example_contributions.jsonl`、`example_groups.jsonl`、`example_citation_map.json`、`example_gaps.jsonl`、`example_terms.jsonl`），以及**九条"只破坏一处"的反例**（`example_rejected.jsonl`）——每条都标注了预期命中的检查项。**示例中的科研内容是合成的示意材料**，不代表真实文献结论。

## 异常与降级

| 情形 | `prep.json`/`check.json` | 退出码 |
|---|---|---|
| 找不到 `case.json` | `reason: no_case` | 2 |
| 找不到科研材料 | `reason: no_material` | 2 |
| 材料文件为空 | `reason: empty_material` | 2 |
| 材料读不出文本（扫描版 PDF / 编码异常） | `reason: unreadable_material` | 2 |
| 材料只有标题、没有正文段 | `reason: no_paragraphs` | 2 |
| Agent 没写 `introduction.md` | `reason: introduction_missing` | 2 |
| 有 high 级问题 | `status: partial` | 0 |
| 无误 | `status: ok` | 0 |

**退出码 2 = 输入没得写，不是脚本坏了**；修好输入后重跑，不要对同一份坏输入反复重试。
