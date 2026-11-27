# 六类要素清单（写得全）

「写得全」在评分里占最大的一块：章节必须覆盖六类要素，缺一类就要在 `elements.json` 里如实标注并说明去向。

对每一类，脚本会在 `check.json` 里做两件事：

1. **材料侧**：这类要素在材料里到底有没有（`elements_checklist.json` 的 `found` / `count`）；
2. **稿子侧**：稿子里写没写（`elements.json` 的 `found` / `section` / `evidence`）。

两边都对上才算齐备；材料有而稿子没写 → `element_not_written`（medium）；材料没有而稿子也没提 → `element_absent_silent`（medium，鼓励显式声明"材料未提供"）。

## 1. `steps` —— 方法步骤

- **要写成什么样**：数据怎么来、怎么预处理、模型怎么搭、怎么训练、怎么评测，一步一句；每步要有入口（脚本名或命令）与产出。
- **判定**：`steps_candidates.jsonl` 里 `kind ∈ code_function / listed_step / log_stage / command / script_path` 的候选被覆盖 ≥5 条；稿子里出现可执行入口（`python xxx.py`、`.sh`、函数名）。
- **常见缺口**：只写"我们用稀疏注意力训练模型"，不写数据构造与评测流程；步骤里没有可执行入口（`step_no_command`）；步骤没有输入/输出（`step_no_io`）。

## 2. `settings` —— 实验设置

- **要写成什么样**：硬件、驱动/CUDA/框架版本、随机种子、重复次数、环境变量。
- **判定**：`settings_candidates.json` 的五类（`versions` / `seeds` / `hardware` / `env_vars` / `repeats`）尽量都落到正文；材料里有种子而稿子没写 → `seed_missing`（high）。
- **常见缺口**：写了 GPU 型号不写 CUDA 与框架版本；不写随机种子；写了"重复三次"但不写报什么统计量（均值/标准差）。

## 3. `params` —— 参数与来源

见 `param-rules.md`。要点：**每个参数一行，带来源文件与行号；正文里的每个数值必须能在材料里逐字找到。**

## 4. `datasets` —— 数据集与划分

- **要写成什么样**：数据集名称 + 版本、来源、规模、划分方式与比例、划分依据（如按文档 id 哈希）。
- **判定**：`datasets_candidates.jsonl` 的名字与版本被写进正文；划分比例与 `splits_candidates.json` 一致（`split_mismatch` high）；划分术语要出现训练/验证/测试三者的关系（`split_terms_incomplete` medium）。
- **常见缺口**：只写"我们用了 LongDocQA"，不写版本；写 `8:1:1` 但不说按什么分；验证集与测试集用途混着说。

## 5. `baselines` —— 对照实验

- **要写成什么样**：对照系统名称与版本、与本文方法的可比性（同数据、同预算、同评测脚本）。
- **判定**：`baselines_candidates.jsonl` 的对照名出现在正文（`baseline_not_in_text` medium）；对照名必须在材料里出现过（`baseline_not_in_material` medium，小节标题如 `## 5. Baselines` 不算）。
- **常见缺口**：对照没有版本号（"dense-only 基线"）；对照与本文方法用的数据/预算不同却不说；只列名字不做比较。

## 6. `repro_limits` —— 可复现性与限制条件

- **要写成什么样**：读者照着能复做的清单（版本、环境、种子、命令、检查点、数据文件）+ 明确的失效场景。
- **判定**：`repro.json` 四要素齐备（`repro_incomplete` high）；限制句要么带具体条件（如 `batch_size < 8`），要么写成"材料未给出，待确认"（`limit_too_vague` medium 的豁免）。
- **常见缺口**：限制写成"性能有待进一步研究"；复现清单缺命令或检查点；限制不给适用条件。

## 与 `gaps.json` 的分工

材料里**确实没有**的信息不要编：写进 `gaps.json`，写明 `question`（要问作者什么）与 `action`（正文里怎么处理的）。核验时 `element_absent_silent` 与 `limit_too_vague` 都会因为这条记录而放行——**显式声明缺口是加分项，不是减分项**。
