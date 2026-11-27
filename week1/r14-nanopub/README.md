# NanopubClaims：把论文结论拆成可逐字回查的断言

本目录是 **BOHRIUM 产品周赛·北化分站赛第一期** 阅读 14「Nanopublication」的参赛作品（Skill 形态）。
公开仓库地址：<https://github.com/yeyuetingyan/bohrium-paper2deck/tree/main/week1/r14-nanopub>

## 一句话

把论文里的一段结论拆成**若干条各自能判真假的断言**，每条绑定**逐字可回查的最小证据片段**，并输出完整的断言—证据—论文追溯链。拆得细、对得上、追得回、读得懂四件事里，前两件由确定性脚本兜底，模型只负责"怎么拆、怎么改写"。

## 为什么不是"让模型直接输出几条断言"

直接让模型抽断言，最常见的四类失败是：

| 失败模式 | 典型样子 | 本 Skill 的应对 |
|---|---|---|
| 拆不细 | 一整段塞进一个 `claim` 字段，或一句话里两个结论只交一条 | `nanoextract.py` 先把句子切成候选并标出复合句，`candidates.md` 明确要求"两个结论各成一条"；`avg_statement_clauses` 量化是否还在塞 |
| 对不上 | "证据"是模型自己复述的，原文里搜不到；或者整段照抄当证据 | 证据必须与 `sources.json` 里同一 `src_id` 的 `text` **逐字一致**，脚本三级比对 + 偏移校验；`quote_not_minimal` 卡住整段照抄 |
| 追不回 | 说得出结论，说不出页码 / 章节 / 版本 / 来源文件 | `provenance` 八个字段缺一即报；`nanopub_id = sha256(subject\|relation\|object\|polarity\|src_id\|quote\|source_sha256)` 让同一条断言永远得到同一个 id |
| 读不懂 | 字段名自创、结构随案例变、下游没法解析 | 固定 schema `nanokit/1.0` + 受控关系词表 + 字段字典（`references/field-dictionary.md`） |

## 关键设计：核验只认逐字字符串

"证据"如果允许改写，核验就退化成模型自证。所以本 Skill 的核验器对证据只有一条态度：**与原文逐字比对**。

由此派生的检查都不依赖上游标注，而是**直接扫证据片段本体**：

- 断言写 `negative` 而证据里没有否定线索 → `direction_conflict`（high）
- 断言写肯定而证据里有 `not measured` → `verify_direction`（low，提示核对否定作用对象）
- 证据里有 `Because the budget is fixed` 而 `conditions` 为空 → `condition_dropped`（medium）
- 证据里有 `may / suggest / typically` 而断言写成无限定的绝对判断 → `overbroad`（medium）

一共 21 类检查，判据与严重度见 `references/quality-checks.md`。

## 目录结构

```
r14-nanopub/
├── SKILL.md                      Skill 主文档（触发条件 / 输入输出 / 三步流程 / 断言协议 / 规则 / 降级）
├── README.md                     本文件
├── GITHUB_URL.txt                公开仓库链接（评审免登录可打开）
├── references/
│   ├── field-dictionary.md       字段字典：assertion / evidence / provenance / confidence / source / check
│   ├── evidence-binding.md       证据定位方法：三级比对、偏移重算、片段大小、反向核验
│   ├── quality-checks.md         21 类检查的判据与严重度、指标定义、刻意不检查的边界
│   └── relation_vocab.json       受控关系词表（15 个关系 + 中英线索词 + 方向约定）
├── scripts/
│   ├── paperkit.py               共用解析核：版面解析、段落/表格抽取、锚点、结果输出（与同系列 Skill 共用）
│   ├── nanoextract.py            切分原文 + 抽候选断言 + 自检（确定性，无模型调用）
│   └── nanoassemble.py           逐字核验 + 质量检查 + 导出 nanopublication（确定性，无模型调用）
└── examples/
    ├── make_sample_paper.py      合成演示论文（纯标准库手写 PDF，不依赖任何真实文献）
    ├── example_case.json         最小 case（含 output_contract）
    ├── example_assertions.json  20 条通过样例（含"一句拆两条"、七类关系、条件与量化）
    └── example_rejected.json    5 条故意被拒样例（每条带 nanopub_note 说明预期命中哪个检查）
```

## 怎么跑

```bash
# 造一份合成论文（仅演示用）
python3 examples/make_sample_paper.py /tmp/sample.pdf

# 第一步：切分 + 抽候选
python3 scripts/nanoextract.py --pdf /tmp/sample.pdf --out /tmp/work
#   => {"status":"ok","page_count":2,"source_count":21,"candidate_count":25,...}

# 第二步：读 work/candidates.md，把保留的断言写进 work/assertions.jsonl
#         （20 条示范见 examples/example_assertions.json）

# 第三步：核验 + 导出
python3 scripts/nanoassemble.py --work /tmp/work \
        --assertions /tmp/work/assertions.jsonl --out /tmp/output
#   => {"status":"ok","assertions":20,"quote_verified_rate":1.0,"minimal_evidence_rate":1.0,
#       "relation_vocab_rate":1.0,"provenance_complete_rate":1.0,"candidate_coverage":0.68}
```

看核验器抓得到什么：

```bash
python3 scripts/nanoassemble.py --work /tmp/work \
        --assertions examples/example_rejected.json --out /tmp/output-rej
#   => {"status":"partial","assertions":5,"with_issues":5,...}
```

## 可复用性

- **字段字典**（`references/field-dictionary.md`）与 **schema `nanokit/1.0`** 固定，任何人可以拿 `assertions.jsonl` 直接做下游解析。
- **受控词表可替换**：换领域的线索词只需替换 `references/relation_vocab.json`，脚本不动。
- **20 条断言样例 + 5 条被拒样例**构成最小题集：`example_assertions.json` 是回归测试的正例，`example_rejected.json` 是检查器的负例（每条注明预期命中项）。
- **中间的 `sources.json` / `candidates.jsonl`** 也是标准 JSON，可以被别的工具直接消费（例如换一个抽取策略只替换第一步）。
- 解析核 `paperkit.py` 与本系列其它 Skill 共用，换题不必重写版面解析。
