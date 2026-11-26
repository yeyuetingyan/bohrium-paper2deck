---
name: literature-kg
description: 把多篇论文正文抽成可回查的文献知识图谱——实体、关系、来源与合并裁决全部逐字绑定原文段落，并能用真实查询回答"哪些结论来自哪篇哪段"。适用于跨篇实体对齐、关系抽取、来源绑定、图谱查询，以及需要区分"同一概念的不同写法"和"同名不同物"的场景。
---

# literature-kg：跨篇文献知识图谱，每条边都能回到原文

图谱最怕两件事：**把不是一回事的东西合并**，和**把说不上来的关系画成边**。这个 Skill 把这两件事交给**确定性脚本**来守：脚本先切好段落、抽出实体与关系候选、并把跨篇的合并/冲突候选摆出来；Agent 只负责决定收哪些实体、连哪些边、哪些该合哪些不该合；最后由脚本逐字回查证据、裁决合并、导出图谱并跑真实查询。

价值在于：**每个节点、每条边都带"哪篇论文的哪一段、哪句原文"**。下游不必信任 Agent 的叙述，直接回查即可；同名不同物、条件不同的同名指标这类陷阱会被显式记成"不可合并"，而不是悄悄糊成一个结论。

## 何时触发

- 要把两篇及以上论文正文整理成实体—关系图谱（materials / methods / metrics / tasks / conditions）。
- 要做跨篇实体对齐：缩写与全称、大小写差异该合并，同名不同物不能合并。
- 要给每条关系绑定逐字证据与段落位置，并保留条件限定。
- 要能回答真实查询（某实体出现在哪、谁报告了哪个数值、两个实体之间有没有路径），且答案必须带证据。
- 要显式记录跨篇冲突（趋势相反、同名指标条件不同）而不是和稀泥。

## 输入

| 输入 | 位置 | 说明 |
|---|---|---|
| 案例描述 | `/input/case.json` | 指向材料文件；支持 `material` / `documents` / `papers` 等候选键，也支持文件名兜底（`material.json`、`primary-material.json`、`secondary-material.json`、`corpus-manifest.json`） |
| 题面 | `/input/task.md` | 人读，脚本不解析 |
| 材料（多篇） | `case.json` 指向的路径 | 每篇的段落带 `source_id` / `paragraph_id` / 正文；段落 ID 是**组织方给出的 JATS 段落 ID**，不是 PDF 页码 |
| 来源清单 | 同上（可选） | `corpus-manifest.json`：各篇 DOI / 标题 / 作者 / 许可证 / 来源哈希 |
| Agent 产出 | `<work>/relations.jsonl`、`<work>/merges.jsonl`、`<work>/entities.jsonl`、`<work>/queries.json` | 第二步由 Agent 写；这是唯一需要模型参与的地方 |

## 输出

上游工作目录 `/app/work`（中间产物，评测方也会看）：

```
passages.json             每篇的段落：source_id / paragraph_id / section / text / sentences / cues
passages.md               同上的人/Agent 友好版（逐段给出原文，供逐字引用）
entities_draft.jsonl      实体候选（含每个候选在原文里的全部出现位置）
merge_candidates.jsonl    别名/缩写候选（可合并，需给依据）
must_not_merge.jsonl      不可合并候选（同名不同物、同名指标条件不同、跨篇张力）
relations_candidates.jsonl 关系候选（同句内、线索词命中、两端实体都在句内）
entity_types.json         受控实体类型表（可用 references/entity_types.json 覆盖）
relation_vocab.json       受控关系词表（可用 references/relation_vocab.json 覆盖）
prep.json                 第一步汇总 + next_step 指令
prep_check.json           无段落 / 只有一篇 / 段落 ID 重复 等提示
```

产物目录 `/app/output`：

```
graph.json         图谱本体：nodes（含 aliases / occurrences / degree）、edges（含 evidence）、must_not_merge、caveats
graph.md           人读版：节点表、边表、不可合并清单
entities.json      导出用的实体表
relations.json     导出用的关系表
query_results.json 每条查询的问题 / 结果行 / 答案 / 是否带证据
check.json         schema=kgkit/1.0、metrics、issues、unresolved、conflicts_preserved
review.md          需要人跟进的条目清单
result.json        status / primary_result / evidence / uncertainty / artifacts + 契约字段
```

## 流程

```bash
# 1) 切段落 + 抽实体/关系/合并候选（确定性，不调模型）
python3 scripts/kg_prep.py --case /input/case.json --out /app/work --max-paragraphs 400

# 2) Agent 读 work/passages.md 与各类候选，写：
#    work/entities.jsonl   收录哪些实体（可只用候选，也可补充遗漏的）
#    work/relations.jsonl  每条边 + 逐字引文 + 条件 + evidence_kind
#    work/merges.jsonl     逐条裁决每个合并候选（merge / keep_separate）
#    work/queries.json     ≥3 个真实查询（含问题、参数、期望）
cp work/relation_vocab.json work/entity_types.json /app/work/   # 需要时用 references/ 覆盖

# 3) 逐字核验 + 合并裁决 + 导出图谱 + 跑查询（确定性，不调模型）
python3 scripts/kg_assemble.py --case /input/case.json --work /app/work --out /app/output

# 4) 需要临时追问时，直接查已导出的图谱（确定性）
python3 scripts/kg_query.py --graph /app/output/graph.json --label MAPbI3 --type neighbors
```

## 建图协议（第二步必须遵守）

1. **实体必须是原文里真实出现的字符串**。不许凭常识补一个"应该存在"的概念；每个实体至少一条 occurrence，occurrence 的 `quote` 必须与所属段落正文逐字一致，位置写 `source_id` + `paragraph_id`。
2. **位置只写段落 ID，不写 PDF 页码**。本包没有 PDF 页码；把自建页面 1 称作"原 PDF 第 1 页"是错的。
3. **关系取自受控词表**（`work/relation_vocab.json`），方向不可反：主语是施动/被测量的一方，宾语是对象或结果。
4. **每条边必须带逐字引文**，且引文要覆盖主语与宾语都出现的那一小段；引文越长越容易把无关条件卷进来，也越容易命中 `relation_quote_not_minimal`。
5. **条件不得丢、也不得跨篇搬运**。原文的 `at 45% relative humidity` / `after 300 h` / `under 1 sun` 写进 `conditions`；条件只出现在另一篇时会被判 `condition_from_other_source`（HIGH）。
6. **转述要标注**。段落含 `reported / according to / et al.` 这类线索时，用 `evidence_kind: "reported"` 与 `"direct"` 区分本文实验与他人结论。
7. **合并要逐条裁决**。`merge_candidates.jsonl` 的每条都要有裁决（合并要写依据，不合并也要写理由）；`must_not_merge.jsonl` 的每条必须显式裁决，不能沉默跳过。
8. **同名指标条件不同 → 不合并**。两篇都写 `T80`，但一个是 45% RH、一个是 85% RH，合并成一个节点等于把两套条件与数值糊在一起，命中 `merge_across_conditions`（HIGH）。
9. **相同通用术语 ≠ 同一物理样品**。两篇都用"钙钛矿/旋涂/封装"不代表同一材料体系或同一批样品；合并依据只能是原文能支撑的同一性。
10. **查询必须真跑**。`queries.json` 里每条查询都要在第三步实际执行，结果与证据一起落进 `query_results.json`；答案为空就写"没有"，不许编。
11. **只写文件，不写对话**。实体/关系/裁决/查询写进 `work/`，不要只在回答里列出来。

## 核验与评分规则

`kg_assemble.py` 对实体、边、合并裁决、查询逐项核验（检查项清单见 `references/merge-rules.md`、`references/evidence-rules.md`），产出指标：

| 指标 | 含义 | 对应评分点 |
|---|---|---|
| `evidence_verified_rate` | 边/节点的引文能在原文逐字找到的比例 | 查得到回得去 |
| `relation_vocab_rate` | 关系取自受控词表的比例 | 连得对 |
| `conditions_kept_rate` | 含条件线索的边把条件带上的比例 | 连得对 |
| `nodes_cross_paper` / `cross_paper_edges` | 跨篇共享节点数与跨篇边数 | 对得齐 |
| `merge_addressed` / `merge_candidates` | 合并候选被显式裁决的比例 | 对得齐 |
| `conflicts_preserved` | 显式保留的不可合并/冲突记录数 | 对得齐 |
| `queries_with_results` / `queries_with_evidence` | 有结果、且结果带证据的查询数 | 抽得准 |

状态判定：无实体或无关系 → `failed`；有 high → `partial`；否则 `ok`。`direction_suspect`、`conditions_from_paragraph` 这类 low 只是友好提示，不阻断 `ok`。

## 边界（本 Skill 不做什么）

- **不做语义级判断**：它不能替你判断"这条结论科不科学"，只保证"这条边有没有原文依据、方向与条件是否与原文一致"。
- **不推断未报告的数据**：本包不提供图像像素、补充附件与底层实验数据，脚本不会从中推断数值。
- **不覆盖输入材料以外的对象**：图谱里只有材料中真实出现过的实体；没出现过的概念不会被补进来。
- **不替 Agent 决定合并**：脚本只把候选与依据摆出来，合并与否由 Agent 显式裁决，裁决会被核验并如实记账。
- **不掩盖分歧**：跨篇趋势相反、同名指标条件不同这类情况，会作为 `must_not_merge` 记录留在图谱里，而不是被平均掉。

## 异常与降级

| 情况 | 第一步行为 | 第二步（Agent） | 第三步行为 |
|---|---|---|---|
| 找不到材料文件 | `prep.json`: `reason=no_material`，退出码 2 | — | 不运行 |
| 材料读不动 / 结构不认识 | `reason=unreadable_material`，退出码 2 | — | 不运行 |
| 材料里没有可抽取段落 | `reason=no_paragraphs`，退出码 2 | — | 不运行 |
| 只有一篇材料（题面要求两篇） | 正常跑，`prep_check.json` 记提示 | 只做单篇图谱，`note` 里说明缺第二篇 | `status=partial`（缺跨篇证据），把该情况写进 `uncertainty` |
| 段落缺 `paragraph_id` | 按序编号 `<source_id>#p0001` 并写 `warnings` | 引用时用脚本给的编号 | 正常核验 |
| 没有关系可核验 | 正常出候选 | — | `reason=no_relations`，退出码 2 |

退出码约定：`0` 正常（`ok` / `partial`）；`1` 参数或环境问题；`2` 材料不可用或没有可用产物（`reason` 与 `hint` 写在 `prep.json` / `result.json` 里，**不要对同一份坏材料反复重试**）。

## 依赖

- Python ≥ 3.9（只用标准库，无需第三方包）。
- `references/` 下的 `entity_types.json` 与 `relation_vocab.json` 是受控词表，可直接替换为领域版本；两个脚本都会优先读取工作目录下的同名文件。
