# paper-method — 方法与实验章节写作 Skill

把一个实验的全部材料（配置、日志、训练脚本、数据说明、事实底稿）变成**可投稿的方法与实验章节**，并且让章节里的每一个数字、每一处设置都能指回材料里的具体位置。

## 它解决什么问题

方法章节最常见的三种毛病：

1. **写得不准** —— 正文里的参数与配置文件里的不一致（配置写 `batch_size: 32`，日志里跑的是 64），或者顺手补了一个材料里根本没有的数值。
2. **写得不全** —— 缺随机种子、缺数据集版本、缺划分方式、缺对照设置，读者照着做不出来。
3. **说得不住** —— 限制写「性能有待进一步研究」这种套话，或者把材料里的冲突默默抹平。

这个 Skill 的做法是：**先把材料变成结构化清单（确定性脚本），再写章节（Agent），最后逐条对账（确定性脚本）**。写不出证据的地方不许编，必须进 `gaps.json` 交作者确认。

## 目录结构

```
SKILL.md                        本 Skill 的使用说明（何时触发、三步流程、写作协议）
README.md                       本文件：设计说明与快速上手
scripts/methodkit.py            共用核：归一化、数值/引用/版本/种子/命令抽取、配置与日志解析、结果导出
scripts/method_prep.py          第一步：确定性抽取 → work/ 下的候选清单与人读摘要
scripts/method_assemble.py      第三步：硬核验 + 导出交付物（11 个文件）
examples/make_sample_case.py    生成一套合成案例（材料 + case.json），可脱离平台自测
examples/sample_materials/      合成材料：factsheet.md / config.yaml / train.log / prepare_data.py / dataset_notes.md
examples/example_*.{md,tsv,json,jsonl}  六份示例交付物 + 九条反例说明
references/                     字段字典、要素清单、参数规则、核验规则
```

## 快速开始

```bash
# 1) 抽取：材料 → work/（不调用模型）
python scripts/method_prep.py --case examples/example_case.json --out /tmp/work

# 2) 写：Agent 读 work/facts.md 与 work/*_candidates.*，产出六份交付物到同一个 work 目录
#    methods.md / params.tsv / elements.json / gaps.json / repro.json / source_map.json
#    （示例见 examples/example_*）

# 3) 核验并导出
python scripts/method_assemble.py --case examples/example_case.json --work /tmp/work \
  --methods examples/example_methods.md --params examples/example_params.tsv \
  --elements examples/example_elements.json --gaps examples/example_gaps.json \
  --repro examples/example_repro.json --source-map examples/example_source_map.json --out /tmp/out
# → status ok / high 0 / medium 0 / low 1
```

## 设计要点

- **确定性优先**：能算的都算，不让模型自述充当证据。参数取值、数值出现位置、划分比例、版本号、种子、命令，全部由脚本从材料里抽出来，Agent 只做"选与写"。
- **来源绑定**：`params.tsv` 的每一行带「文件:行号」，`source_map.json` 的每一段带逐字引文，`elements.json` 的每一类要素带所在小节与证据句。
- **归一化只用一套**：脚本内部所有比对都走同一个 `norm_hard()`（去标点、压缩空白、小写）。混用"保留标点"和"去标点"两套归一，会让 `2.1.0+cu118`、`data/x.jsonl` 这类字符串永远匹配不上，把好稿子判成错稿子。
- **冲突显式化**：同一参数在不同来源取值不同时，不静默取一个，而是核对成 `conflict`，写进 `gaps.json`（`high`），并在正文里说明选值理由。
- **材料顺序即契约**：`fact_id` 形如 `f-m-00N-sNNN`，编号与材料顺序绑定。任何示例、测试件都必须保持 `material_files` 的原始顺序，否则来源映射会整体错位。

## 核验覆盖什么、不覆盖什么

覆盖（脚本能证伪的）：正文数值是否在材料里、参数值与来源、划分比例、版本与种子、命令可执行形态、每段是否有来源映射、六类要素是否齐备、限制是否具体、冲突是否交代。

不覆盖（需要人判断的）：实验设计是否合理、对照是否公平、统计方法是否恰当、章节语言质量、材料本身是否真实。这些写进 `check.json` 的 `unresolved` 与 `result.json` 的 `uncertainty`，由作者与审稿人决定。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常（`status` 为 `ok` 或 `partial`） |
| 1 | 参数或环境问题（如 `--case` 路径不存在） |
| 2 | 材料不可用：`no_case` / `no_material` / `empty_material` / `unreadable_material` / `no_paragraphs`，原因写在 `prep.json` 的 `reason` 与 `hint` |

**退出码 2 表示"没得写"，不是脚本故障**，补齐材料再跑，不要对同一份材料反复重试。

## 依赖

Python ≥ 3.9，脚本只用标准库；材料含 PDF 时需要 `PyMuPDF`。
