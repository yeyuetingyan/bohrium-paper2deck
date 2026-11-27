---
name: nanopub-claims
description: 把论文拆成逐条可判断真假的断言，并为每条绑定逐字可回查的最小证据，导出可解析的 nanopublication 记录。适用于需要把整段结论拆细、给每条断言找到原文出处、检查断言过宽或证据不足、建立"断言—证据—论文"追溯链、以及做结果复核与复用的场景。
---

# nanopub-claims：把结论拆成可核验的断言

一段结论读起来像一个整体，其实里面藏着好几条各自能判真假的断言。这个 Skill 把"拆细"和"对得上"变成两步**确定性**的工作：脚本先把候选断言和它的原文位置摆出来，Agent 只负责决定拆成哪几条、怎么改写；最后由脚本逐字回查证据、跑质量检查、导出结构化的 nanopublication 记录。

价值在于：**每条断言的证据都能在原文里逐字找到，位置可指出**。所以下游（人或程序）不需要信任 Agent 的自述，直接回查即可。

## 何时触发

- 需要把论文/报告的结论段落拆成逐条断言（claim-level extraction）。
- 需要给每条断言绑定最小证据片段，并保留页码、章节、来源文件与版本。
- 需要检查断言是否过宽、证据是否不足、关系类型是否用错、条件是否被丢掉。
- 需要做结果复核与复用：断言集要能被别人重新解析、重新核验。

## 输入

| 输入 | 位置 | 说明 |
|---|---|---|
| 案例描述 | `/input/case.json` | 至少含 `paper_path`（支持 `pdf` / `pdf_path` / `paper` / `input_paper` / `document` 别名）；可选 `target_relations`、`output_contract`、`max_pages` |
| 题面 | `/input/task.md` | 人读，脚本不解析 |
| 论文文件 | `case.json` 指向的路径 | PDF（需文字层）或 txt / md |
| Agent 产出 | `<work>/assertions.jsonl` | 第二步由 Agent 写；这是唯一需要模型参与的文件 |

## 输出

上游工作目录 `/app/work`（中间产物，评测方也会看）：

```
sources.json        每个 source 单元：src_id / page / section / kind / text / anchor / sha256_16
candidates.jsonl    候选断言（含线索标注与形态提示）
candidates.md       同上的人/Agent 友好版（逐条给出"必须原样引用"的原文）
context.json        标题 / 作者 / 年份候选 / 章节 / 计数 / source_sha256
relation_vocab.json 受控关系词表（可用 references/relation_vocab.json 覆盖）
prep.json           第一步汇总 + next_step 指令
prep_check.json     空段 / 重复段号 / 页码缺口 / 未识别结构
assertions.jsonl    Agent 写的断言（输入）
```

产物目录 `/app/output`：

```
assertions.jsonl      核验后的断言（带 nanopub_id 与 validation{status,issues,evidence_verified,…}）
assertions.tsv        同上的表格视图，便于人工抽查
nanopublications.md   人读版：每条一条，断言 / 证据 / 出处 / 命中的问题
check.json            schema=nanokit/1.0、metrics、unresolved、sources_summary
review.md             需要人跟进的条目清单（unresolved）
result.json           status / primary_result / evidence / uncertainty / artifacts + 契约字段
```

## 流程

```bash
# 1) 切分原文 + 抽候选断言（确定性，不调模型）
python3 scripts/nanoextract.py --case /input/case.json --out /app/work --max-pages 40

# 2) Agent 读 work/candidates.md，写 work/assertions.jsonl
#    （每条断言一条 JSON；同一 src_id 的原文才能当证据）

# 3) 逐字核验 + 质量检查 + 导出（确定性，不调模型）
python3 scripts/nanoassemble.py --case /input/case.json --work /app/work --out /app/output
```

## 断言协议（第二步必须遵守）

1. **一条断言只表达一件事**。一句话里有两个结论就拆成两条；相关系词（and）连接的并列成分各成一条，除非它们必须一起才成立。
2. **证据逐字引用**。`evidence.quote` 必须与 `sources.json` 里同一 `src_id` 的 `text` 完全一致（含标点与大小写）；改写过就不是证据。
3. **最小充分**。证据只覆盖支撑该断言所需的那一小段（≤240 字符且 ≤2 句）。整段照抄会命中 `quote_not_minimal`。
4. **主体必须逐字出现在证据里**。客体默认也要能找到；确属归一化转述的，显式写 `assertion.object_normalized: true`。
5. **关系取自受控词表**（`work/relation_vocab.json`）。方向不得反向：证据说下降就不能写成 increase。
6. **条件不许丢**。原文的 `because / when / if / under …` 限定、样品范围、温度、预算等，写进 `assertion.conditions`。
7. **模糊限定要跟着走**。原文有 `may / suggest / typically`，译文式的断言就不能写成绝对判断；拿不准就写 `confidence.basis` 说明依据。
8. **出处字段齐全**：`paper_title / authors / year / source_file / source_sha256 / version / section / page`。
9. **只写文件，不写对话**。断言写进 `work/assertions.jsonl`，不要只在回答里列出来。

## 核验与评分规则

`nanoassemble.py` 对每条断言跑 21 类检查（详见 `references/quality-checks.md`），产出指标：

| 指标 | 含义 | 对应评分点 |
|---|---|---|
| `quote_verified_rate` | 证据能在原文逐字找到的比例 | 对得上 |
| `minimal_evidence_rate` | 证据不超长的比例 | 对得上 |
| `relation_vocab_rate` | 关系取自受控词表且无方向冲突的比例 | 拆得细 / 读得懂 |
| `provenance_complete_rate` | 出处字段齐全的比例 | 追得回 |
| `candidate_coverage` | 用掉的候选 / 全部候选 | 拆得细 |
| `condition_kept_rate` | 原文含条件线索而断言未丢条件的比例 | 读得懂 |

状态判定：**每条断言** 无问题 → `ok`；只有 medium / low → `partial`；有 high → `failed`。**整体** `result.json.status`：有 high → `partial`；全干净 → `ok`；0 条断言或上游材料不可读 → `failed`（并带 `reason` 与 `hint`）。

## 边界（本 Skill 不做什么）

- **不判断断言的学术真伪**：只保证"证据里说了这句话"，不保证这句话本身正确。
- **不做语义蕴含推理**：证据必须**逐字**支撑断言；需要跨句推理的结论请拆成多条。
- **不覆盖叙述质量**：文风、连贯性、读者友好度不在核验范围内。
- **不替代人工评审**：自动核验只覆盖可机械比对的部分，其余写进 `unresolved` 与 `result.json.uncertainty`。

## 异常与降级

| 情况 | 行为 |
|---|---|
| 材料缺失 | `prep.json` 写 `{"status":"failed","reason":"no_material",…}`，**退出码 2** |
| PDF 加密 | `reason: encrypted_pdf` + `hint`，退出码 2；不要重试同一份文件 |
| PDF 损坏 | `reason: damaged_pdf`，退出码 2 |
| 扫描件（无文字层） | `reason: no_text_layer` + `skipped_pages` 记录页码，退出码 2（本 Skill 不做 OCR） |
| 有文字层但抽不出候选 | `reason: no_candidates`，退出码 2；可放宽 `--min-score` 重跑 |
| Agent 没写 `assertions.jsonl` | `result.json` 写 `status=failed, reason=no_assertions` + `hint`，退出码 2 |
| 上游 `prep.json` 是 failed | `result.json` 一路带上 `reason`/`hint`，状态降为 `failed` |

退出码约定：`0` 正常，`1` 参数/环境错误，`2` 材料或输入不可用（**不是脚本坏了**）。

## 示例

```bash
# 造一份合成论文（仅用于演示，接入真实案例时不需要）
python3 examples/make_sample_paper.py /tmp/sample.pdf

# 两步跑通
python3 scripts/nanoextract.py  --pdf /tmp/sample.pdf --out /tmp/work
python3 scripts/nanoassemble.py --work /tmp/work \
        --assertions examples/example_assertions.json --out /tmp/out
# => {"status":"ok","assertions":20,"quote_verified_rate":1.0,"minimal_evidence_rate":1.0,…}

# 看核验器抓得到什么：5 条故意被拒的样例
python3 scripts/nanoassemble.py --work /tmp/work \
        --assertions examples/example_rejected.json --out /tmp/out-rej
# => {"status":"partial","assertions":5,"with_issues":5,…}
```

`examples/example_assertions.json` 是 20 条**通过样例**（含三处"一句拆两条"的示范、七类关系、否定极性、条件与量化）；`examples/example_rejected.json` 是 5 条**故意被拒样例**，每条带 `nanopub_note` 说明预期命中哪个检查。

## 依赖

- Python ≥ 3.9（脚本只用标准库）
- PyMuPDF（`pip install pymupdf`，import 名 `fitz`）——仅处理 PDF 时需要；txt/md 不需要
- 资源说明见 `references/`：字段字典、证据定位方法、质量检查判据、受控关系词表
