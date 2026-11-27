# 不变量（paper-latex）

「改得对」的核心是**改之外的东西一个字都没动**。项目用三类不变量把这件事变成可核对的账。

## 一、数值与引用账本

`tex_prep.py` 把材料里所有「不可变成分」抓成 `protected_spans(text)`，返回六类：

| kind | 例 |
|---|---|
| `number` | `23.5 %`、`1.12 V`、`1000 h`、`3e-5` |
| `citation` | `[12]`、`(Smith et al., 2020)`、`\cite{key}` |
| `crossref` | `Fig. 2`、`Table 3`、`Eq. (4)`、`Section 2.1`、`\ref{…}` |
| `label` | `\label{eq:efficiency}` 的键 |
| `url` / `doi` | 链接与 DOI |
| `formula` | 行内/行间公式片段 |

## 二、「缺少」的判定范围（`protected_scope`）

交付的 `revised.tex` 经常把 `\input{sections/method}` 内联成单文件，于是主文件里出现了原本属于
子文件的数值。若把**所有** `.tex` 的数值并成一锅去比对，这些数值会被算成「多出来的」，
而主文件本来就有的会被算成「缺失」——产生一批假 high。

所以 `numbers.json` 是结构化账本：

```json
{"schema":"tex-numbers/1.0","main_file":"main.tex",
 "main":{"items":{...},"count":26},
 "by_file":{"sections/method.tex":{"items":{...},"count":9}},
 "all":{"items":{...},"count":31}}
```

`tex_assemble.py` **只在 `main` 范围内判「缺失」**（`protected_dropped_undeclared`），
新增则按全部判（`protected_added_undeclared`，medium）。当前口径原样写在
`check.json.metrics.protected_scope` 里（例：`"主文件 main.tex"`）。

## 三、归一化只有一套

所有比对走 `texkit.norm_hard()`：去标点、压空白、转小写。**不要**和 `flat()`（保留标点）
混用——混用会让下面这类串永远匹配不上：

- `2.1.0+cu118`（`+` 被去标点后位置变化）
- `data/longdocqa_train.jsonl`（`/` `.` 都是标点）
- 含中文全角标点的引文（`。` `，` 在 `flat()` 里保留、在 `norm_hard()` 里去掉了）

同理，`source_map` 的引文核对也在 `norm_hard` 下进行，所以 `23.5 %` ≡ `23.5%`。

## 四、引用闭环

| 检查 | 级别 | 含义 |
|---|---|---|
| `undefined_ref` | high | `\ref`/`\cref` 指向不存在的 `\label` |
| `undefined_citation` | high | `\cite` 的 key 不在 `.bib` 里 |
| `unused_label` | low | 有 `\label` 没人引用（可能是笔误或残留） |
| `uncited_bib_entry` | low | 有 bib 条目没被引用 |
| `no_citations` | medium | 改后文件既没有引用也没有文献库 |

编译日志侧的对应项是 `compile_undefined_refs` / `compile_undefined_cites`（high）与
`compile_needs_rerun`（low）。

## 五、改动登记

`changes.jsonl` 每条的 `before` 必须能在原文件里逐字找到（否则 `change_row_invalid` 之外还会有
核验不上的问题），`after` 必须出现在交付稿里。`kind` 不在约定集合内 → `change_kind_unknown`（medium）；
`reason` 短于 6 字符 → `change_reason_too_short`（low）；
**整个清单为空或没交付 → `changes_missing`（high）**。
