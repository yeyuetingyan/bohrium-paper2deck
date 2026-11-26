---
name: paper-polish
description: 学术语言润色与校对 Skill。把论文/学位论文/基金申请书/审稿回复的草稿做语法句法修正、术语与缩写全篇统一、学术语域调整，产出润色后的完整文本加逐处修改说明（原文/改文/类型/理由），并用确定性核验证明没有改坏东西：数字与单位、引用编号、图表公式指向、限定强度（may/should/可能）、否定与条件、因果与相关的表述全部逐字守恒。当用户要求润色、proofread、语言校对、学术英语润色、术语统一、语气调整、修改说明清单，或要求"改语法但别改意思"时触发。
---

# paper-polish：学术语言润色

**一句话价值**：把"润色"从一次整段重写变成**可核验的逐处修改**——交付润色后的完整文本 + 逐句修改说明，并用脚本证明数字、单位、引用、图表指向与限定强度一个字都没被动过。

## 何时触发

- 用户给出论文/草稿并要求"润色 / 语言校对 / proofread / 改语法 / 学术英语润色"。
- 用户要求"术语全篇统一""缩写首次出现规范化""把口语化表达改成学术语域"。
- 用户要求"改完告诉我改了哪些地方、为什么改"。
- **不适用**：要求改内容、补实验、重写论证结构、翻译成另一种语言（那些不是语言润色，语义变化的核验口径在这里不成立）。

## 输入

运行时输入在 `/input/`：

| 文件 | 必需 | 说明 |
|---|---|---|
| `case.json` | 是 | 任务描述；关键字段见下 |
| `task.md` | 是 | 题面全文 |
| 稿件 | 视 case 而定 | `manuscript_path` 指向的 `.md`/`.txt`/`.tex`/`.docx`；同名文件缺失时按 `manuscript.md`/`draft.md`/`document.md`/`source.md`/`paper.md` 等候选名兜底 |

`case.json` 关键字段：`case_id`、`manuscript_path`、`style`（*journal-article* / *thesis* / *grant-proposal* / *reviewer-response* / *abstract*）、`audience`、`target_language`、`task`、`glossary`（任务给定的术语表，具有最高优先级）、`output_contract`（键 → 默认文件名）。

## 输出

写在 `/app/output/`，默认对应 `output_contract` 的 7 个键：

```
revised.md        润色后的完整文本（manuscript）
edits.jsonl       逐处修改清单（edits）：每行一处修改
diff.md           原文/改文/类型/理由 对照表（diff）
glossary.tsv      锁定后的术语表（glossary）
consistency.json  逐段核验账本（consistency）：不可变成分、强度线索、术语
check.json        指标与问题清单（check）
review.md         人读报告（review）
result.json       主结果：状态 + 契约字段回填 + 证据 + 不确定性 + 产物哈希
```

## 流程（三步，前两步确定性）

### 第 1 步：`scripts/polish_prep.py`（确定性，不调用模型）

```bash
python scripts/polish_prep.py --case /input/case.json --out /app/work
```

产出：

- `work/segments.json`：逐段逐句的 `seg_id`（`p<四位段号>b<句号>`），每段带 `kind`、`section`、`cues`（限定/绝对化/否定/量词/条件/因果线索）、`balance`（强度计数）、`protected`（不可变成分：数字、单位、引用、交叉引用、公式、URL、DOI）。
- `work/segments.md`：**给 Agent 读的改写工作台**——每段原文 + "必须原样保留"清单 + 当前限定强度 + 候选修改点。
- `work/issues.jsonl`：确定性检测到的候选问题（语法一致、名词化冗赘、逗号拼接、翻译腔、标点、英美拼写混用、绝对化断言、术语漂移、单位间距不一致、缩写先于全称定义等），每条带 `seg_id` 与原文片段。
- `work/glossary_draft.tsv`：术语候选表，列为 `term / preferred / variants / freq / status / kind / source / note`；`source=case` 的行来自任务给定术语表（`status=prescribed`，优先级最高）。

### 第 2 步：Agent 改写（唯一需要模型判断的一步）

按 `work/segments.md` 逐段改写，并产出三份文件（建议写进 `/app/work/`）：

1. `revised.md`：**完整**润色后文本（段落数与顺序必须与原文一致，不得增删段落）。
2. `edits.jsonl`：每处修改一行
   ```json
   {"seg_id":"p0002b1","type":"grammar","before":"results shows","after":"results show","reason":"主谓一致：主语 results 为复数"}
   ```
   字段：`seg_id`（必须是 `segments.json` 里的段号）、`type`（见 `references/edit-taxonomy.md`）、`before`（**逐字**摘录原文片段）、`after`（逐字改后片段，纯删除写空串）、`reason`（中文或英文说明，≥6 字符）。
3. `glossary.tsv`：把 `glossary_draft.tsv` 每一行补上 `preferred` 并把 `status` 改为 `locked`。

### 第 3 步：`scripts/polish_assemble.py`（确定性核验 + 导出）

```bash
python scripts/polish_assemble.py --case /input/case.json --work /app/work \
  --revised /app/work/revised.md --edits /app/work/edits.jsonl \
  --glossary /app/work/glossary.tsv --out /app/output
```

不传 `--revised/--edits/--glossary` 时按候选文件名在 `--work` 下自动查找。

## 改写协议（Agent 必须遵守）

1. **最小编辑**：能改一个词就不改一句，能改一句就不重写一段。`similarity` 会算出来，无关重写会被 `unexplained_change` 逮住。
2. **不可变成分逐字保留**：数字、单位、引用编号 `[12]`、交叉引用 `Fig. 2`/`Table 1`/`Eq. (4)`/`Section 2.1`、公式、URL、DOI 一律原样。`23.5 %` 与 `23.5%` 视为等价，其余改动一律报错。
3. **强度守恒**：不得把 `may` 改成 `will`、不得删 `approximately`、不得把 `suggests` 改成 `proves`、不得加 `always`/`all`/`never`、不得把 `caused by` 降级成 `associated with` 或反向升格。**确有必要改强度时必须单独列一条 `hedging` 类型的修改并写明理由**——脚本会据此判定"已声明"，否则按未声明处理。
4. **否定与条件守恒**：`not`、`only`、`unless`、`when`、`under ... conditions` 不得丢失或移位到改变适用范围。
5. **术语按锁定表统一**：全篇只用 `glossary.tsv` 的 `preferred` 写法；缩写首次出现必须先给全称再给缩写。
6. **每处修改都要有说明**：`before`/`after` 必须是原文与改文里**逐字存在**的片段（不是改写后的转述）。
7. **只写文件，不写对话**：结果必须落盘，聊天里的建议不算交付。

## 规则（对应评分口径）

- **改得对**：`edits` 的 `before` 必须在原文对应句子里逐字找到（否则 `edit_before_not_found`），`after` 必须在改后文本里逐字找到（否则 `edit_after_not_found`）；修改类型必须来自受控表（否则 `edit_type_unknown`）。
- **说得像**：语域由 `case.style` 决定（`journal-article` 等），`consistency.json` 逐段记录；术语一致率 `term_unified_rate` 由锁定表算出。
- **没改坏**：`protected_total` / `protected_missing` / `protected_preserved_rate` 是硬账；`hedging_strengthened`、`quantifier_strengthened`、`boost_added`、`negation_lost`、`conditional_lost`、`causal_downgraded`、`correlation_upgraded` 是强度与逻辑的硬检查。
- **讲得清**：`diff.md` 是逐处修改对照表；`edits_with_reason` 必须等于 `edits`。

## 异常与降级

| 情况 | 行为 |
|---|---|
| 找不到稿件 | `prep.json` 写 `status=failed`、`reason=no_material`、`hint`，**退出码 2** |
| 稿件存在但内容为空 | `reason=empty_material`，退出码 2 |
| 稿件读不出（损坏/加密/无文字层的扫描件/编码坏） | `reason=unreadable_material`，退出码 2 |
| 稿件读到了但切不出句子 | `reason=no_segments`，退出码 2 |
| 只交了修改清单、没交改后全文 | `revised_missing`（high），`status=failed`，退出码 2 |
| 没交修改清单 | `edits_missing`（high），`status=partial`，退出码 0（其余产物仍可用） |
| 上游 prep 失败/告警 | 第一阶段的原因与告警一路带进 `result.json` 的 `uncertainty` |

退出码：`0` 正常（`ok`/`partial`）／`1` 参数或环境错误／`2` 材料不可用或缺少改后全文。

## 示例命令（本 Skill 自带合成样例）

```bash
python examples/make_sample_manuscript.py /tmp/w02          # 生成 15 段合成稿件 + case.json
python scripts/polish_prep.py --case /tmp/w02/case.json --out /tmp/w02/work
# Agent 依据 work/segments.md 写出 revised.md / edits.jsonl / glossary.tsv
python scripts/polish_assemble.py --case /tmp/w02/case.json --work /tmp/w02/work \
  --revised /tmp/w02/revised.md --edits /tmp/w02/edits.jsonl --glossary /tmp/w02/glossary.tsv \
  --out /tmp/w02/out
```

## 依赖

- Python ≥ 3.9，**纯标准库**即可跑通 `.md`/`.txt`/`.tex`/`.docx`。
- 只有输入 `.pdf` 时才需要 PyMuPDF（`fitz`）；缺失时 `polishkit.read_text_any()` 会返回告警而不是崩溃。

## 参考文档

- `references/edit-taxonomy.md`：10 种修改类型与判定口径。
- `references/strength-rules.md`：强度守恒规则（限定、绝对化、量词、否定、条件、因果）。
- `references/verification-rules.md`：全部检查项、刻意宽容处、刻意不检查处。
- `references/field-dictionary.md`：`segments.json` / `edits.jsonl` / `glossary.tsv` / `check.json` / `consistency.json` 字段字典。
