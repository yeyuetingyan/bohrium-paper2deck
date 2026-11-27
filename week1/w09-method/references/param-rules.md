# 参数抽取、来源标注与冲突处置规则

## 一、参数从哪来

`method_prep.py` 按材料类型分头抽取，四类来源各自有明确的语法，**不做泛化猜测**：

| 材料类型 | 识别形态 | 例子 |
|---|---|---|
| 配置（`.yaml/.yml/.toml/.ini/.cfg/.json`） | 键值对 + 缩进层级 | `model:` → `hidden_dim: 768` → 记作 `model.hidden_dim` |
| 日志（`.log/.out`） | `key=value` 或 `key: value` | `batch_size=64` |
| 正文（`.md/.txt/.tex`） | 键值对 + 中文「参数 X 为 Y」形态 | `学习率 3e-5` |
| 代码（`.py/.sh/.ipynb`） | **只认两种显式声明** | `os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0,1")`、`ap.add_argument("--top_k", default=100)` |

代码文件**不走**泛化的 `key = value`：代码里的中间变量（`out = []`、`ap = ArgumentParser()`、`__name__ == "__main__"`）不是实验参数。`JUNK_PARAM_KEYS` 与 `is_junk_param_key()` 还会过滤掉值里括号不配对、值明显是表达式或容器的行。

## 二、去重规则

去重键是 **`(key, 来源文件, 行号)`**，且同一位置若既有结构化解析（配置/日志）又有正文扫描结果，**保留结构化那条**。

> 反例（早期实现的 bug）：正文扫描按逗号切分，会把 `CUDA_VISIBLE_DEVICES=0,1` 读成 `0`，于是凭空多出一条"`CUDA_VISIBLE_DEVICES` 冲突：`0,1` vs `0`"。这类假冲突比漏报更有害——它会让作者去改一个不存在的问题。

## 三、来源标注

`params.tsv` 的 `source` 列一律写 **`文件:行号`**（如 `configs/sparse.yaml:14`）。同一参数在多个来源出现时，正文只保留实际生效的那个，并把差异写进 `gaps.json`：

```json
{"gap_id": "g1", "element": "params", "severity": "high",
 "question": "参数 `batch_size` 在不同来源出现不同取值（32 / 64），请确认以哪一处为准。",
 "action": "本稿按日志的 64 写入正文，若实际以配置为准请告知，我会同步改正文与 params.tsv。",
 "conflict": {"key": "batch_size",
              "values": [{"value": "32", "sources": [{"source": "config.yaml", "line": 14}]},
                         {"value": "64", "sources": [{"source": "train.log.txt", "line": 6}]}]}}
```

## 四、冲突判定（不算冲突的情形）

以下情形**不**产生 `conflicts`，否则日志会被判得满屏冲突：

- **序列键**（`SERIES_KEYS`：`epoch` / `step` / `iter` / `loss` / `acc` / `time` 等）——日志里天然每轮一个值，不是冲突。
- **同一键取值多于 3 种** —— 更像统计输出或表列，不是"A 处写 32、B 处写 64"这种二选一。
- **值只是尾随标点差异** —— `clean_value()` 会把 `20):` 清洗成 `20`。

真正留下的冲突应当是"两个来源对同一参数给了不同取值"，例如配置 `batch_size: 32` 与日志 `batch_size=64`。

## 五、取值比对（核验侧的规则）

`method_assemble.py` 判定"参数值是否在材料里"时：

- **数值型取值**（匹配 `[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d{1,3}|%)?`）→ **只与材料的数值集合精确比对**（`number_pool`）。
- **非数值型取值** → 归一化后子串匹配（`hard(value) in hard(material)`）。

为什么数值不能走子串：`hard("48")` 是 `0.4812`、`8,400` 去标点后的子串，会把改过的参数值误判成"材料里有"（反向样例 `b2_param_value_not_in_material` 就是靠这条规则才被抓到）。

数值形态统一在 `methodkit.NUM_RE` 里定义，**含科学计数法**（`3e-5`、`1.5×10^-3`）与常见单位后缀。早期的 `val` 组不认指数，`3e-5` 被读成 `3`，而 `3` 在材料里出现过，于是"把 `3e-5` 改成 `4e-5`"这种改动完全不报。

## 六、工具类常见坑

- 中英混排的 `\b` 不可用：CJK 与 CJK 之间没有词边界，`\b限制\b` 匹配不到「限制」。脚本统一用 `LB = (?<![A-Za-z0-9])`、`RB = (?![A-Za-z0-9])` 作为边界。
- 比对双方必须走**同一套归一**：`flat()`（保留标点）与 `norm_hard()`（去标点）混用，会让 `2.1.0+cu118`、`data/train.jsonl` 永远匹配不上。
