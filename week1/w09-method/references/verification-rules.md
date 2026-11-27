# 核验规则（`check.json` 的全部判据）

核验由 `scripts/method_assemble.py` 执行，只做**能机械证伪**的判断：数值是否存在、字符串是否逐字出现、比例是否一致、字段是否齐备。语义判断（结论对不对、方法好不好）不在范围内。

级别：`high` 阻止 `status=ok`；`medium` 同样阻止（`ok` 要求 high 与 medium 都为 0）；`low` 只是提示。

## 一、数值与不可变成分

| 检查项 | 级别 | 判据 |
|---|---|---|
| `number_not_in_material` | high | 正文出现材料数值集合之外的数字（`number_pool`） |
| `number_unit_mismatch` | medium | 同一数值在正文与材料里的单位不同 |
| `protected_token_not_in_material` | high | 版本号/路径/DOI/引用编号等不可变成分被改写 |
| `seed_missing` | high | 材料里有随机种子，稿子里没写 |
| `version_missing` | medium | 材料里有版本号，稿子里没写 |

## 二、参数

| 检查项 | 级别 | 判据 |
|---|---|---|
| `params_missing` / `params_unreadable` | high | 参数表缺失/读不出 |
| `param_row_invalid` | high | 行字段数不对或表头不符 |
| `param_value_empty` | high | 取值为空 |
| `param_value_not_in_material` | high | 数值型取值不在材料数值集合；非数值型归一后找不到 |
| `param_candidates_uncovered` | medium | 配置材料里的参数没进参数表（接受 `model.dropout` 覆盖 `dropout`） |
| `param_source_missing` | low | 来源列没写 |
| `conflict_unreported` | medium | 材料里有同名不同值，稿子完全没提 |
| `conflict_value_unwritten` | medium | 正文没写实际采用的取值 |

## 三、划分、对照、限制

| 检查项 | 级别 | 判据 |
|---|---|---|
| `split_mismatch` | high | 稿子里的划分比例与材料不一致 |
| `split_terms_incomplete` | medium | 划分没点明训练/验证/测试三者的关系 |
| `baseline_not_in_text` | medium | 材料里的对照名没出现在正文 |
| `baseline_not_in_material` | medium | 正文写了材料里没有的对照名（小节标题等泛词不计） |
| `limit_not_written` | medium | 材料里的具体限制没进「复现与限制」一节（带数值者只认数值；无数值者按内容词覆盖 ≥50%） |
| `limit_too_vague` | medium | 限制写成套话且未标注待确认（句含"需确认/待确认/材料未给出/不足以判定"时豁免） |
| `boilerplate_phrase` | low | 出现"有待进一步研究/具有重要意义"类空话 |

## 四、复现

| 检查项 | 级别 | 判据 |
|---|---|---|
| `repro_missing` / `repro_unreadable` | high | 复现清单缺失/读不出 |
| `repro_incomplete` | high | `versions` / `environment` / `seeds` / `commands` 任一为空。`commands` 必须是**可执行入口形态**（`python xxx.py`、`bash/sh/sbatch/qsub/make/docker run`、`.sh/.ipynb/.cmd/.ps1`、`command:` 前缀），`python 3.10.13` 这种版本号不算 |
| `repro_number_not_in_material` | high | 复现清单里的数值材料里没有 |
| `repro_command_not_in_material` | medium | 命令在材料里找不到（允许只给脚本名） |

## 五、来源映射

| 检查项 | 级别 | 判据 |
|---|---|---|
| `source_map_missing` | high | 没有来源映射 |
| `source_map_empty` | high | 映射里没有任何段落 |
| `source_fact_unknown` | high | 引用了不存在的事实号 |
| `source_quote_not_found` | high | 引文在材料里找不到（去标点归一后比对） |
| `source_quote_too_short` | low | 引文短于 12 字符 |
| `source_quote_not_minimal` | medium | 引文过长（超过 400 字符或 3 句） |
| `source_quote_not_in_methods` | low | 引文与该段落的内容词覆盖度低（改写过多时的提示） |
| `paragraph_unmapped` | medium | 正文段落没有来源映射 |

## 六、结构

| 检查项 | 级别 | 判据 |
|---|---|---|
| `methods_missing` / `methods_empty` | high | 稿子缺失/为空（退出码 2） |
| `section_missing` | high | 六节里有缺失（同一节被多个标题命中时取跨度最大者） |
| `section_too_short` | medium | 小节正文短于 60 字符 |
| `section_order` | medium | 小节顺序与规范不符 |
| `no_headings` | low | 完全没有标题 |
| `element_absent_silent` | medium | 材料里没有的要素，稿子也不声明 |
| `element_not_declared` | medium | 要素没写进 `elements.json` |
| `element_not_written` | medium | `elements.json` 说写了，正文里找不到 |
| `steps_too_few` | medium | 方法步骤少于 5 条 |
| `step_no_command` / `step_no_io` | medium | 步骤没有可执行入口 / 没写输入输出 |

## 七、刻意宽容处

- **数值形态**：`23.5%` ≡ `23.5 %`；`1,000` ≡ `1000`；科学计数法 `3e-5` 与 `3×10^-5` 等价（同属一个数值）。
- **引文换行与标点**：比对前统一压缩空白、去标点、小写，因此跨行引文、全角/半角混用不会被判错。
- **参数表行数**：不要求把所有候选都写进表（日志里的 host、driver 属于"实验设置"而非参数），只有 `config` 类候选必须覆盖。
- **多标题命中**：同一小节被 `# Methods` 与 `## 1. Methods` 同时命中时取跨度更大的那个，避免把文档大标题当成小节。
- **泛词不作为对照名**：`baseline` / `control` / `对照` 这类泛词、以及小节标题本身，都不算对照系统的名字。

## 八、刻意不检查处

1. 实验设计是否合理、对照是否公平（需要领域判断）。
2. 统计方法是否恰当（只检查是否写了，不检查写得对不对）。
3. 语言质量与学术语域（不是本 Skill 的职责）。
4. 材料本身是否真实、是否有伪造的实验数据。
5. 方法与结论是否匹配（那需要读结果的章节）。
6. 图表是否恰当（本 Skill 不处理图像）。

`check.json` 的 `unresolved` 与 `result.json` 的 `uncertainty` 会把上述边界写成文字，交给作者与审稿人。
