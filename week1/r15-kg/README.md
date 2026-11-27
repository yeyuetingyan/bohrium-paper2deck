# literature-kg — 跨篇文献知识图谱 Skill

把**两篇（及以上）论文正文**整理成可回查的知识图谱：实体、关系、来源、合并裁决全部逐字绑定原文段落，并给出至少 3 个真实执行过的查询。

核心主张：**先证据，后图谱**。每个节点、每条边都能回到"哪篇论文的哪一段、哪句原文"；同名不同物、同名指标条件不同这类陷阱会被显式记为"不可合并"，而不是悄悄糊成一个结论。

## 快速开始

```bash
# 1) 确定性预处理：切段落、抽实体/关系/合并候选（不调模型）
python3 scripts/kg_prep.py --case /input/case.json --out /app/work --max-paragraphs 400

# 2) Agent 读 work/passages.md 与各候选，写四份文件
#    work/entities.jsonl  work/relations.jsonl  work/merges.jsonl  work/queries.json

# 3) 确定性核验 + 导出图谱 + 跑查询（不调模型）
python3 scripts/kg_assemble.py --case /input/case.json --work /app/work --out /app/output

# 4) 临时追问
python3 scripts/kg_query.py --graph /app/output/graph.json --label MAPbI3 --type neighbors
```

本地跑通（含合成语料）：

```bash
python3 examples/make_sample_corpus.py <workdir>          # 生成两篇合成论文的四件输入
python3 scripts/kg_prep.py --case <workdir>/case.json --out <workdir>/work
python3 scripts/kg_assemble.py --case <workdir>/case.json --work <workdir>/work \
        --entities examples/example_entities.json --relations examples/example_relations.json \
        --merges examples/example_merges.json --queries examples/example_queries.json \
        --out <workdir>/out
```

## 目录

```
SKILL.md                 主文档：何时触发、协议、核验规则、边界、降级
README.md                本文件
scripts/kgkit.py         共用核：schema 宽容读取、段落切分、指标、result.json 导出
scripts/kg_prep.py       第一步：确定性切段落 + 抽实体/别名/关系/冲突候选
scripts/kg_assemble.py   第三步：核验（实体/关系/合并/查询）+ 导出图谱 + 跑查询
scripts/kg_query.py      查询器：九类查询，结果行强制带证据
references/entity_types.json  受控实体类型（8 类）
references/relation_vocab.json 受控关系词表（14 个有向关系）
references/field-dictionary.md 四份输入文件与导出字段的完整定义
references/evidence-rules.md   证据与位置的检查项清单（级别 + 怎么过）
references/merge-rules.md      合并/不合并的判断标准与四类陷阱
references/query-templates.md  九类查询的参数模板
examples/make_sample_corpus.py 合成两篇论文语料（含四个对齐陷阱）
examples/example_case.json     示例 case.json
examples/example_entities.json / example_relations.json / example_merges.json / example_queries.json
examples/example_rejected.json 6 条「故意被拒」样例（每条写明预期命中哪个检查）
```

## 已验证的行为（合成语料，两篇 26 段）

| 场景 | 结果 |
|---|---|
| 正常样例 | `status=ok`，19 节点 / 9 边 / 7 查询，`evidence_verified_rate=1.0`、`relation_vocab_rate=1.0`，0 high / 0 medium |
| 别名合并（MAPbI3 ↔ CH3NH3PbI3、XRD ↔ X-ray diffraction…） | 合并裁决全部有位置证据，跨篇合并显式 `cross_paper` |
| 同名指标条件不同（两篇的 T80 分别在 45% / 85% RH 下） | 判 `keep_separate`，写进 `graph.json.must_not_merge` |
| 同名不同物（一篇的 MA = methylamine，另一篇的 MA = methylammonium） | 判 `keep_separate` 并说明理由 |
| 跨篇趋势相反（湿度致衰减 vs 封装后 1000 h 不衰减） | 作为冲突保留并逐篇给证据，不做平均 |
| 故意被拒的 6 条坏样例 | `relation_quote_not_found`、`condition_from_other_source`、`relation_not_in_vocab`、`relation_quote_too_short`、`merge_across_conditions`、`merge_without_evidence` 全部按预期命中 |
| 材料缺失 / 读不动 / 无段落 | `prep.json` 写 `reason` + `hint`，退出码 2（不写半张图谱） |

## 边界

- 不做语义级判断：不评价结论科不科学，只保证"这条边有原文依据、方向与条件与原文一致"。
- 不推断未报告的数据：本包无图像像素、补充附件与底层实验数据。
- 不补造输入材料以外的对象；不替 Agent 决定合并，只把候选与依据摆出来并如实记账。
- 位置是**组织方 JATS 段落 ID**，不是 PDF 页码。

## 依赖

Python ≥ 3.9，仅标准库；`references/` 下两个 JSON 词表可直接替换为领域版本。
