# paper-intro — 引言与相关工作写作 Skill

`paper-intro` 把「科研材料 + 文献库」变成**可直接进入论文的四节正文**（研究背景 / 相关工作 / 研究空白 / 贡献），
并让每一句话都能回查到材料原文与参考文献。

它针对的是学术写作里最常见、也最容易被审稿人抓住的四类问题：

| 问题 | 本 Skill 的处置 |
|---|---|
| 背景空转（"近年来受到广泛关注"） | `boilerplate_background` 检查 + 强制每条论断绑定 `fact_id` |
| 相关工作变成逐篇摘要拼接 | `groups.jsonl` 要求给出分组维度、比较项与比较结论 |
| 引用对不上、数字被顺手改掉 | 引用解析、引文逐字定位、数字材料外检测 |
| 贡献与正文/结果脱节 | `contributions.jsonl` 的锚点必须能在正文里逐字定位 |

## 结构

```
submission/
├── SKILL.md                      本 Skill 的说明（Agent 主入口）
├── README.md                     本文件
├── GITHUB_URL.txt                公开仓库地址
├── scripts/
│   ├── introkit.py               共用核：句子切分、可保护成分、引用解析、文献读取、结果写出
│   ├── intro_prep.py             第一步（确定性）：切段、抽可引材料句、文献普查、分组/空白/贡献候选
│   └── intro_assemble.py         第三步（确定性）：硬核验 + 导出交付物
├── references/
│   ├── field-dictionary.md       全部字段字典（输入 / 中间产物 / 交付物）
│   ├── claim-rules.md            论断绑定规则与引用纪律
│   ├── grouping-rules.md         相关工作分组的判定口径
│   └── verification-rules.md     核验项清单、宽容处与不做的事
└── examples/
    ├── make_sample_case.py       生成合成语料的脚本
    ├── example_case.json         最小可跑案例
    ├── example_material.md       合成事实底稿
    ├── example_bibliography.bib  12 条合成文献
    ├── example_introduction.md   示例正文（四节）
    ├── example_claims.json      15 条论断绑定示例
    ├── example_contributions.json / example_groups.json / example_citation_map.json / example_gaps.json / example_terms.json
    └── example_rejected.json    九条"只破坏一处"的反例及其预期命中项
```

## 快速开始

```bash
export PYTHONDONTWRITEBYTECODE=1

python scripts/intro_prep.py     --case examples/example_case.json --out /app/work
# Agent 依据 /app/work/facts.md 写 introduction.md / claims.jsonl / contributions.jsonl /
#   groups.jsonl / citation_map.json / gaps.jsonl
python scripts/intro_assemble.py --case examples/example_case.json --work /app/work --out /app/output
```

示例案例跑完的实测结果（在本机 `D:\Python\python.exe`、cwd=`C:\` 下）：

```
intro_prep    : {"status":"ok","paragraphs":11,"sentences":25,"facts":19,"number_citations":4,
                 "references":12,"ref_groups":9,"gap_candidates":8,"contribution_candidates":2,
                 "terms":8,"numbering_basis":"positional","unresolved_citations_in_material":0}
intro_assemble: {"status":"ok","citations":12,"claims":15,"groups":6,
                 "high":0,"medium":0,"low":3,"unresolved_citations":0}
metrics       : claims_source_verified_rate=1.0  cited_grouped_rate=1.0
                contributions_with_anchor=3/3  references_uncited=0
                numbers_not_in_material=0      boilerplate_hits=0
```

三条 low 是刻意保留的友好提示：贡献句与本文结果句没有引用（本来就正常），但核验器会提醒你它们必须带锚点。

## 设计原则

1. **确定性脚本做核验，模型只做写作**。哪些句子可引、引用能不能解析、引文是否逐字、数字是否材料外，这些都用脚本算，事实自证而非自述。
2. **证据必须逐字可定位**。`source.quote`/`anchors[].quote`/`groups[].summary` 都要能在材料或正文里 `find()` 到，核验器才认。
3. **编号映射写清楚是假设**。文献表不带编号时按出现顺序映射，`numbering_basis: positional` 明写在 `references.json` 与 `facts.md` 里。
4. **边界自曝**。`check.json.unresolved` 与 `review.md` 明说"论断是否真的被引文支持、分组是否合理、空白是否成立"不在自动范围内。

## 反例集

`examples/example_rejected.json` 收录九条"只破坏一处"的案例，全部经脚本核验按预期命中：

| 案例 | 破坏点 | 预期命中 |
|---|---|---|
| `b1_unknown_citation` | 引用文献表外的 key | `claim_citation_unknown` |
| `b2_quote_rewritten` | 把来源引文改写成自己的话 | `claim_source_not_in_material` |
| `b3_gap_no_citation` | 空白句不加引用 | `gap_claim_without_citation` |
| `b4_contrib_no_anchor` | 贡献条目没有锚点 | `contribution_anchor_missing` |
| `b5_number_not_in_material` | 把 23.5% 改成 27.5% | `number_not_in_material`（+ `claim_text_not_in_introduction`） |
| `b6_citation_metadata` | `citation_map` 年份与 `.bib` 不符 | `citation_metadata_mismatch` |
| `b7_group_member_unknown` | 分组里塞进不存在的文献 | `group_member_unknown` |
| `b8_no_introduction` | 没写正文 | `introduction_missing`（退出码 2） |
| `b9_overclaim` | 分组结论写成 "best/most novel/always" | `group_summary_overclaim` |

## 依赖

- Python ≥ 3.9，纯标准库；读 `.pdf` 需要 `PyMuPDF`。
- 跑脚本时设置 `PYTHONDONTWRITEBYTECODE=1`。
