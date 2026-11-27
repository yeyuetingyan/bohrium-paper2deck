# 字段字典

本文件列出 `paper-method` 的输入、中间产物与交付物的全部字段。字段名以脚本实际输出为准，写文档、写测试、对接下游时都以此为准。

## 一、输入

### `case.json`（`--case` 指向，默认 `/input/case.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str | 案例标识，回填进 `result.json.case_id` |
| `task` | str | 任务描述（写章节时参考） |
| `audience` | str | 目标读者 |
| `genre` | str | 体裁（如 `journal-article`） |
| `language` | str | 语言 |
| `format_constraints` | obj | 篇幅/格式约束 |
| `output_contract` | obj | 期望产出：`{<键>: {required: bool, default: any}}`，脚本按它回填 `result.json` 顶层 |
| `material_files` | list[str] | 材料路径列表（相对 case 文件所在目录）**顺序即 `fact_id` 编号顺序，不可重排** |
| `materials` / `material` / `sources` | list/str | `material_files` 的别名，同样支持 |

材料按扩展名识别：`.yaml/.yml/.toml/.ini/.cfg/.json` → `config`；`.log/.out` → `log`；`.py/.sh/.ipynb` → `code`；`.md/.txt/.tex/.bib/.pdf` → `doc`。

## 二、第一步产物（`work/`，由 `method_prep.py` 写）

| 文件 | 内容 |
|---|---|
| `sources.json` | 材料索引：`[{source_id, path, kind, chars, lines, note}]`；`source_id` 形如 `m-001` |
| `facts.jsonl` | 可引用的事实行：`{fact_id, source_id, line, kind, text, score, protected, cues}`；`fact_id = f-<source_id>-s<行号>` |
| `facts.md` | 人读摘要：材料清单 + 逐条事实 + 数值/引用/不可变成分 + 提示 |
| `params_candidates.tsv` | 参数候选：`name value unit source material_kind`（`source` 为 `文件:行号`） |
| `settings_candidates.json` | 实验设置候选：`{versions[], seeds[], hardware[], env_vars[], repeats[]}` |
| `splits_candidates.json` | 划分候选：`[{raw, parts{}, source, optional}]` |
| `datasets_candidates.jsonl` | 数据集候选：`{name, version, source, line, note}` |
| `steps_candidates.jsonl` | 步骤候选：`{kind, text, source, line, has_input_cue, has_output_cue, has_decision_cue}`；`kind ∈ code_function / listed_step / log_stage / command / script_path` |
| `baselines_candidates.jsonl` | 对照候选：`{name, cue, source, line}` |
| `limits_candidates.jsonl` | 限制候选：`{text, concrete, vague, source, line}` |
| `conflicts.json` | 参数冲突：`{key, values: [{value, sources: [{source, line}]}]}` |
| `elements_checklist.json` | 六要素齐备度：`{<键>: {found, count, evidence[]}}` |
| `gap_candidates.json` | 待确认候选（材料缺口、冲突、缺版本等） |
| `context.json` | 汇总计数、材料顺序、`source_sha256` 等 |
| `prep.json` | `{status, reason?, hint?, counts{}, next_step[]}`；`next_step` 是给 Agent 的 7 步指令 |
| `prep_check.json` | 抽取自检：空材料、重复行号、候选为空等 |

## 三、第二步交付物（Agent 写，放入同一个 `work/`）

### `methods.md`
六个小节，标题建议（脚本按中英双语正则识别，节序错会报 `section_order`）：

1. `1. Methods`（方法步骤）
2. `2. Experimental Settings`（实验设置）
3. `3. Parameters`（参数）
4. `4. Datasets`（数据集与划分）
5. `5. Baselines`（对照实验）
6. `6. Reproducibility and Limitations`（复现与限制）

### `params.tsv`
制表符分隔，表头固定为 `name	value	unit	source`：`model.hidden_dim	768		configs/sparse.yaml:4`。`unit` 允许为空；`source` 必须写「文件:行号」。

### `elements.json`
```json
{"schema": "method-elements/1.0",
 "elements": {"steps": {"found": true, "count": 5, "section": "1. Methods", "evidence": "……", "artifact": "params.tsv"}}}
```
六键：`steps`、`settings`、`params`、`datasets`、`baselines`、`repro_limits`。

### `gaps.json`
```json
{"schema": "method-gaps/1.0",
 "gaps": [{"gap_id": "g1", "element": "params", "severity": "high",
           "question": "……", "action": "……",
           "conflict": {"key": "batch_size",
                        "values": [{"value": "32", "sources": [{"source": "config.yaml", "line": 14}]}]}}]}
```
`severity ∈ high / medium / low`；`conflict` 只在参数冲突时出现。

### `repro.json`
```json
{"schema": "method-repro/1.0",
 "versions": {"python": "3.10.13", "torch": "2.1.0+cu118"},
 "environment": {"os_hint": "...", "requirements": "...", "env_vars": {}, "hardware": "..."},
 "seeds": {"python_seed": "1234", "note": "..."},
 "commands": ["python train.py --config configs/sparse.yaml"],
 "checkpoint": "runs/.../ckpt-12.pt",
 "data_files": ["data/train.jsonl"]}
```
`versions` / `environment` / `seeds` / `commands` 四项任一为空会报 `repro_incomplete`（`commands` 必须是可执行入口形态）。

### `source_map.json`
```json
{"version": "source_map/1.0",
 "paragraphs": [{"para_id": "m-p003", "section": "1. Methods", "fact_ids": ["f-m-001-s004"],
                 "evidence": [{"fact_id": "f-m-001-s004", "quote": "……", "source": "factsheet.md", "line": 12}]}]}
```
`quote` 必须逐字取自材料（脚本去标点归一后比对）；每个正文段落都应有一条。

## 四、第三步产物（`/app/output`，由 `method_assemble.py` 写）

| 文件 | 内容 |
|---|---|
| `methods.md` 等六份 | 核验后的定稿（回写） |
| `consistency.json` | 逐段一致性账：段落 → 来源事实 → 数值/参数覆盖情况 |
| `check.json` | `{status, metrics{}, checks{}, issues[], unresolved[]}` |
| `review.md` | 人读报告：逐节表、未通过项、核验边界 |
| `diff.md` | 稿子与材料的差异说明（改了哪些、为什么） |
| `result.json` | 见下 |

### `result.json`

顶层固定键：`schema`、`case_id`、`status`、`primary_result`、`evidence`、`uncertainty`、`artifacts`、`change_log`、`issues`，随后是**契约键**（`output_contract` 里出现过的名字，如 `methods.md`/`params.tsv`/`elements.json`/`gaps.json`/`repro.json`/`check.json`/`review.md`），以及从 `primary_result` 提升到顶层的 `summary` / `status_detail` / `sections_found` / `issues_high`。

`artifacts[]` 每项 `{path, role, media_type, bytes, sha256}`；`evidence[]` 记录核验依据；`uncertainty[]` 记录脚本无法判断的事项（至少包含"材料里同名不同值的参数需作者确认"和"本核验不判断实验设计是否合理"）。
