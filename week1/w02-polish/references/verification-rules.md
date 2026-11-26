# 核验规则（verification rules）

第 3 步 `polish_assemble.py` 会把改动逐项过一遍，输出到 `check.json` 的 `issues[]`（每条 `{level, kind, where, detail}`）。本文件是全部检查项的判据表，以及**刻意宽容**与**刻意不检查**的边界。

## 一、不可变成分（protected）

原文里的数字、单位、引用编号、交叉引用、公式、URL、DOI 全部登记成账本，与改后文本逐项比对。比对时按"去空白"归一，因此 `23.5 %` ≡ `23.5%`。

| 检查项 | 级别 | 判据 |
|---|---|---|
| `protected_token_changed` | high | 账本项个数不变但某项不同（`23.5%` → `24.5%`、`Table 1` → `Table 2`） |
| `number_invented` | high | 改后出现原文没有的**数值** |
| `protected_token_added` | high | 改后多出引用/交叉引用等非数值项 |

指标：`protected_total`、`protected_missing`、`protected_extra`、`protected_preserved_rate`（= 未变动项 / 总项数）。

## 二、段落结构与说明覆盖率

| 检查项 | 级别 | 判据 |
|---|---|---|
| `paragraph_dropped` | high | 原文档有、改后没有的段落 |
| `paragraph_added` | high | 改后多出的段落 |
| `paragraph_count_changed` | medium | 段落数不同（走 `difflib` 配对时统一记账） |
| `unexplained_change` | medium | 该段文本有变化，但没有任何一条修改记录的 `seg_id` 落在该段 |

指标：`paragraphs_source`、`paragraphs_revised`、`paragraphs_changed`、`paragraphs_declared`、`unexplained_changes`。

## 三、强度与逻辑（详见 `strength-rules.md`）

| 检查项 | 级别 |
|---|---|
| `hedging_strengthened` | high（已声明时降为 low） |
| `hedging_softened_undeclared` | medium |
| `quantifier_strengthened` | high |
| `universal_quantifier_removed` | medium（已声明时降为 low） |
| `boost_added` | high |
| `negation_lost` / `conditional_lost` | high |
| `causal_downgraded` | medium |
| `correlation_upgraded` | high |

## 四、修改清单自身

| 检查项 | 级别 | 判据 |
|---|---|---|
| `edits_missing` | high | 清单缺失或为空 |
| `edits_unreadable` | medium | 清单读不动（JSON 坏） |
| `edit_field_missing` | high | 缺 `seg_id`/`type`/`before`/`after` |
| `edit_seg_unknown` | medium | `seg_id` 不在 `segments.json` |
| `edit_type_unknown` | medium | 类型不在受控表 |
| `edit_before_not_found` / `edit_after_not_found` | high | 片段在对应文本里找不到 |
| `edit_before_whitespace_variant` / `edit_after_whitespace_variant` | low | 仅空白差异 |
| `edit_reason_too_short` | low | 理由 < 6 字符 |
| `no_change_claim` | medium | `no-change` 类型却 `before` ≠ `after` |
| `edit_protected_changed` | high | 条目自身改动了不可变成分 |

指标：`edits`、`edits_with_reason`、`edits_per_1k_chars`、`edit_type_histogram`。

## 五、术语一致性

| 检查项 | 级别 | 判据 |
|---|---|---|
| `glossary_locked_missing` | medium | 没有提供锁定术语表 |
| `term_not_unified` | medium | 锁定术语的 `preferred` 之外写法仍出现在正文（**复数与纯大写缩写形态豁免**） |

指标：`terms_locked`、`terms_unified`、`terms_drifted`、`term_unified_rate`。

## 六、最小编辑

`similarity = difflib.SequenceMatcher` 的段落级相似度平均；`minimal_edit_rate` 与之一致。**这两项只作为参考指标，不单独触发 issue**——全篇重写不会被单独判错，但会通过 `unexplained_change` 与逐条修改记录的可核验性暴露出来。

## 七、缺失与降级

| 检查项 | 级别 | 行为 |
|---|---|---|
| `revised_missing` / `revised_empty` | high | `status=failed`、`reason=no_revised_text`、**退出码 2** |
| `segments_missing` | high | `status=failed`、退出码 2（必须先跑第 1 步） |

状态口径：**有 high → `partial`；无 high → `ok`；缺改后全文或上游产物 → `failed`（退出码 2）**。`medium`/`low` 不改变状态，只出现在 `issues[]` 与 `review.md` 里。

## 八、刻意宽容的地方

- `23.5 %` ≡ `23.5%`、`1000 h` ≡ `1000h`：去空白后比对。
- 单位/数字的全角半角、千分位、`1.0` ≡ `1`。
- `Fig. 2` ↔ `图 2` 这类中英标签对照（改后文本里两种都认）。
- 缩写的纯大写形态（`XRD`）与术语表里的混合写法不做漂移判定。
- 同一词干的语法修正（`shows`→`show`、`indicates`→`indicate`）不算强度改动。
- 已声明的强度改动降级为 `low` 提示，而不是直接报错。

## 九、刻意不检查的地方（写进 `result.json` 的 `unresolved`）

1. **语法是否"真的改对"**——脚本只验证改动的形式与守恒，不判断改后的句子是否更规范。
2. **语域是否真的贴合目标文体**——`style` 只作为上下文记录，是否"像学术论文"需要人工判断。
3. **改写是否仍是作者本意**——除线索词守恒外，语义层面的忠实度不在自动核验范围。
4. **领域术语是否用得对**——本 Skill 只保证全篇一致，不保证术语选择正确。
5. **指代消解是否恰当**——把 `this` 明确成具体名词是否正确，需要人能读懂上下文。

这五条会原样写进 `result.json.uncertainty`，作为交付时的诚实边界。
