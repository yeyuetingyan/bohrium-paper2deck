---
name: cite-manager
description: 核验并重排学术稿件的参考文献与正文引用：解析 BibTeX/RIS/编号制文献表，扫描 [1]/[1-3]、(Author, 2020)、\cite{} 三类引用，按首次出现重排编号并压缩区间，按 DOI/题名去重并给出合并依据，按 GB/T 7714—2015 生成文末表，检出悬空引用、未被引用条目、重复 DOI 与元数据缺失。当任务要求"参考文献管理""引用编号重排""文献表格式化""正文—文献一致性检查"或给出稿件与 .bib 要求核对引用时使用。
---

# CiteManager：引用核验与重排

稿件里的引用错，通常错在四件事：**挂得不对**（引到了不需要证据的句子）、**编不顺**（增删后编号与文末表脱节）、**收不净**（预印本与正式版各留一条）、**对不上**（文献表里有稿件从没引过的条目）。本 Skill 处理后三件与"悬空引用"，并用可复核的规则给出每处改动的依据；"挂得对不对"属于学术判断，只输出待人工确认的候选句。

## 何时触发

- 给定稿件（`.md`/`.txt`/`.tex`/`.docx`）与文献库（`.bib`/`.ris`/编号制文本），要求核对或整理引用；
- 要求把顺序编码制改成按出现顺序、或把文献表改成 GB/T 7714—2015；
- 要求找出重复条目、未被引用的条目、正文引了但表里没有的编号。

## 输入

`/input/case.json` 中稿件与文献库的字段名不固定，按以下顺序容错匹配：

| 角色 | 可能字段 |
|---|---|
| 稿件 | `manuscript_path`、`manuscript`、`doc`、`document`、`paper_path`、`draft` |
| 文献库 | `library_path`、`library`、`bibliography`、`bib`、`refs`、`references`（可为列表） |

找不到时在 case 目录下取第一个非 `.bib/.ris` 的文档，以及第一个 `.bib`/`.ris`。只读实际文件，不按领域标签补内容。

## 输出（写到 `/app/output/`）

```
output/
├── manuscript_revised.<ext>    # 重排编号后的稿件（numeric 样式；docx 转为 md）
├── references_gbt7714.txt      # 按新编号排序的文末表
├── references_deduped.bib      # 去重后的 BibTeX，可直接回填文献管理器
├── citation_map.json           # 旧号→新号、key→序号、合并记录、未解析引用
├── check.json                  # 悬空引用/未被引用/重复 DOI/字段缺失/待补引用候选
└── result.json                 # case_id / status / evidence / uncertainty / artifacts
```

## 流程

```bash
python "$SKILL/scripts/run_cite.py" --case /input/case.json --out /app/output
# 或显式指定
python "$SKILL/scripts/run_cite.py" --manuscript paper.md --library refs.bib --out out
```

一次调用完成解析、去重、重排、格式化、自检与结果组装；不联网。

## 规则（评分要点）

1. **原编号的含义**：顺序编码制下，正文 `[n]` 指文献库中第 n 条（去重前）。去重后保留 `old_index` 与 `aliases`，因此 `[4]` 若指向被合并的重复条目，会正确落到保留条目上。
2. **重排**：按正文首次出现排序，`[3,1]`→`[1,2]`，连续编号压缩为 `[1-3]`；只改标记，不改句子。悬空编号（表里没有）原样保留并报错，不猜测补条目。
3. **去重**：三档判据——DOI 相同 → 题名相似度 ≥0.90 且同年 → 首作者+年。合并时保留字段更全的一条，记录 `basis` 与被合并的 `old_index`，供人工复核；不做"同名作者即同一文献"的合并。
4. **GB/T 7714—2015**：西文作者姓全大写、名缩写（`VASWANI A`），超过 3 人取前 3 加 `et al`；中文作者用`，`与`等`；类型标识 `[J]/[M]/[C]/[D]/[P]/[S]/[R]/[Z]`；期刊 `刊名, 年, 卷(期): 起-止`；DOI 统一 `DOI: 10.xxxx/...`。字段缺失只留空，不编造。
5. **一致性检查**：悬空引用、未被引用条目、重复 DOI（去重后仍重复即报错）、DOI 形态不合法、必需字段缺失（文章需作者/题名/年）。
6. **待补引用候选**：含数字、百分比或"显著/提高/降低/优于"等断言、却没有引用标记的句子，列入 `check.json.candidates_needing_citation`，仅提示，不自动插入——引哪篇是学术判断。
7. **样式保留**：著者-出版年样式只做解析核验，不改写正文；LaTeX 保留 `\cite{key}`，输出按首次引用排序的 `.bib` 与 key→序号映射，编号交给模板样式。

## 证据与状态

- `result.json.evidence`：旧号→新号的前 20 条（含题名前 90 字）、合并记录（保留条目、被并条目、依据）。
- `status`：`ok`（无错误且无悬空引用）／`partial`（有悬空引用、去重后仍重复、或输入为 docx 未回写）／`failed`（没有可解析的文献库）。
- `uncertainty`：docx 未回写、著者-出版年未重排、LaTeX 编号交给样式等限制逐条写明。

## 异常处理

| 情况 | 处理 |
|---|---|
| 稿件找不到 | `status=failed`，列出搜索目录 |
| 文献库为空 | 不重排（避免把编号改坏），`status=failed` 并说明 |
| 文献库只有编号制文本 | 用 `[n] 作者. 题名[J]. 刊名, 年, 卷(期): 页.` 启发式抽取，抽不到的字段留空 |
| 正文用 `\cite{}` | 不改正文，输出排序后的 `.bib` 与映射 |
| 同一 DOI 两条且字段互补 | 合并并补全字段，`citation_map.json` 记录依据 |
| 编号制文献表条目跨行 | 以 `[n]` 起条，续行并入上一条 |
| docx 稿件 | 抽出段落文本处理，输出 `manuscript_revised.md`，原 docx 不动 |

## 最小示例

`examples/` 内是一份合成稿件与一份刻意做乱的文献库（含 1 条重复、1 条未被引用、1 条缺年份、正文 1 处悬空 `[12]`），可直接跑：

```bash
python scripts/run_cite.py --manuscript examples/manuscript.md --library examples/library.bib --out /tmp/demo
```

预期：11 条去重为 10 条，8 条被引用并按首次出现重排，`check.json` 报 1 条悬空引用、2 条未被引用、1 条字段缺失。示意输出见 `examples/expected_shape.json`（**示例数据，不是正式案例结果**）。

## 限制

- 不联网核验 DOI 是否真实存在，只查形态与条目间一致性；真实存在性需外部检索；
- 不做"该引哪篇"的推荐，只标记缺引用的断言句；
- 著者-出版年样式的重排（如 APA 字母序）不做，只做解析与匹配；
- 复杂英文姓名（复姓、粒子、缩写混合）可能切分不准，输出后需抽查前 5 条；
- docx 只读不写，回填需按 `citation_map.json` 在 Word 中执行。
