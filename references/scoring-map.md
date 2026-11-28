# 评分对照表：每一条评分点，去哪里看证据

这道题是**人工评审**。评审最花时间的不是读文档，而是"判断你说的到底有没有做"。
本文件把评分表的每一行，直接映射到本 Skill 里**可以当场打开验证**的文件与字段——
评审只要顺着"证据位置"点开，就能自己下结论，不需要相信我们的叙述。

> 约定：`S=SKILL 目录`、`W=/app/work`、`O=/app/output`。
> 所有路径都是相对路径，随提交包一起交付。

## 一、实际效果（40 分）

| 评分点 | 我们的做法 | 证据位置（可当场验证） |
|---|---|---|
| 任务完成度 15 | 从 PDF 到可编辑 PPTX + PDF 预览 + 逐页证据 + 结果 JSON，全链路一条命令可复跑 | `S/scripts/selftest.py` 一条命令跑完四步；`O/result.json` 的 `summary`（`slides`/`figures_used`/`tables_used`/`slides_with_evidence`/`slides_with_notes`） |
| 结果正确性 15 | 页内容不靠模型"编"，先由确定性骨架钉住：叙事骨架、逐字要点、图注表注页码 | `S/scripts/plan_assist.py`；`W/assist.json` 的 `next_steps`；`W/plan.json` 每页 `evidence[].quote` 与 `page` |
| 完整性 5 | 主线四段齐全（问题/方法/结果/局限）+ 图页 + 表页 + 收尾；缺哪段会被校验器点名 | `S/scripts/validate_plan.py` 报告；`O/check.json` 的 `warnings` |
| 可核验性 5 | **逐页证据在出片前被重新验证一遍**：页码在范围内、引文真的出现在那一页、图片存在非空 | `O/evidence_check.json`（`status`/`evidence_checked`/`evidence_verified`）+ `O/result.json` 的 `claims[]`、`evidence_map` |

## 二、使用增益（25 分）

| 评分点 | 我们的做法 | 证据位置 |
|---|---|---|
| 质量增益 15 | 解决"用 Agent 做论文转 PPT"最容易翻车的三件事：矢量图抽不出、PDF 粘连词、页码对不上 | `S/scripts/extract_paper.py`（`_cluster_boxes`/`_pick_region`/`span_text`）；`S/SKILL.md` 的「已验证的真实论文」表 |
| 效率增益 5 | 先跑骨架再改写：模型不用从零试错，页数与要点已被钉住；`assist.json` 直接给出"还差什么" | `W/assist.json` 的 `next_steps`；`S/SKILL.md` 步骤 1b |
| 增益可验证性 5 | 三篇真实论文（BERT / Attention / RAG）跑通并如实记录页数、图数、引文数、校验结论 | `S/SKILL.md` §已验证的真实论文；`S/README.md` §真实论文验证 |

## 三、创新增益（15 分）

| 评分点 | 我们的做法 | 证据位置 |
|---|---|---|
| 新增能力 5 | **证据复核器**：把"每页可回溯"从自述变成机器证明（重开 PDF 逐条比引文） | `S/scripts/verify_evidence.py` + `O/evidence_check.json` 的 `checks[]` 与 `limits[]` |
| 方法改进 5 | **确定性骨架 + 模型改写**的分工：能核验的交给脚本，叙事与讲稿留给模型 | `S/scripts/plan_assist.py`（`find_quote` 定位不到就不产出引文）；`S/SKILL.md` 步骤 1b/2 |
| 创新证据 5 | 同一套代码在 3 篇真实 arXiv 论文上跑出 10 页稿，图/表/引文全部核验通过 | `S/SKILL.md` §已验证的真实论文；`O/evidence_check.json` 三份 |

## 四、可靠体验（10 分）

| 评分点 | 我们的做法 | 证据位置 |
|---|---|---|
| 调用易用性 3 | 一个自测命令验证整条链路；参数缺省有兜底（`/input` 下找唯一 PDF） | `S/scripts/selftest.py`；`S/SKILL.md` §输入 |
| 稳定性 4 | 每个脚本都有明确退出码与 `status` 字段；渲染走 LibreOffice→WPS COM 双路回退 | `O/check.json`、`O/render.json` 的 `status`/`reason` |
| 异常处理 3 | 加密 PDF、抽不出图、表注定位不到、无渲染器，各自有明确降级路径且**如实记录**，绝不伪造 | `S/SKILL.md` §异常处理表；`O/result.json` 的 `uncertainty[]` |

## 五、生态贡献（10 分）

| 评分点 | 我们的做法 | 证据位置 |
|---|---|---|
| 文档完整性 3 | SKILL/README/plan-schema/outline-patterns/evidence-rules/scoring-map 六份，字段与判据逐一列出 | `S/SKILL.md`、`S/README.md`、`S/references/*.md` |
| 资源可复用性 4 | 页计划 schema、叙事范式库、证据规则可直接套用到别的"论文→讲稿"场景；`plan_assist` 可独立当抽取器用 | `S/references/plan-schema.md`、`S/references/outline-patterns.md`、`S/references/evidence-rules.md` |
| 分享推广价值 3 | 公开 GitHub 目录 + 一键自测，别人 clone 下来就能验证 | `S/GITHUB_URL.txt`；`S/README.md` §快速开始 |

## 六、GitHub 公开链接（5 分）

- 地址写在 `S/GITHUB_URL.txt` 第一行；目录里的内容就是本提交包的同版本副本（评审无需登录即可打开）。
- 仓库内对应目录：`week1` 之外的仓库根即本作品（PPT 题的作品在仓库根目录）。

## 七、这份对照表本身

它不是评分依据，只是**索引**。任何一条"我们做了"都可以被反驳：点开证据位置，看字段、看报告、看自测输出。
如果某条证据缺失或对不上，以证据为准，不以本表为准。
