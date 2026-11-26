# 查询模板（query-templates）

图谱交付时必须带**至少 3 个真实执行的查询**：不是"图谱支持查询"，而是"这几个问题已跑过，结果与证据在这里"。本文件给出九类查询的参数与用途，直接照抄改参数即可。

## 命令形态

```bash
# 批量：跑 queries.json 里的全部查询（第三步会自动执行，也可单独跑）
python3 scripts/kg_query.py --graph /app/output/graph.json --queries work/queries.json --out work/query_results.json

# 临时追问：直接查
python3 scripts/kg_query.py --graph /app/output/graph.json --label MAPbI3 --type neighbors
```

每条结果行**强制带证据**（`source_id` + `paragraph_id` + 引文），没有证据的行会被判 `query_result_without_evidence`（HIGH）。

## 九类查询

| `type` | `args` | 回答什么问题 | 适合的评分点 |
|---|---|---|---|
| `entity` | `{"entity": "MAPbI3"}` | 这个对象的别名、全部出现位置、所有关联边 | 查得到回得去 |
| `neighbors` | `{"entity": "T80", "depth": 1}` | 与某实体直接相连的实体与关系 | 连得对 |
| `path` | `{"from": "MA vapor treatment", "to": "grain size"}` | 两个实体之间有没有带证据的路径；没有就明说没有 | 查得到回得去 |
| `relation` | `{"relation": "improves"}` | 某类关系的全部边与各自依据 | 连得对 |
| `keyword` | `{"keyword": "humidity"}` | 哪些位置提到某个词（含条件值） | 抽得准 |
| `evidence` | `{"source_id": "synth-secondary-0002", "paragraph_id": "p-3-001"}` | 某一段支撑了哪些节点与边 | 来源绑定 |
| `conflicts` | `{}` | 跨篇冲突/不可合并分歧清单（读 `must_not_merge`） | 对得齐 |
| `subgraph` | `{"entities": ["MAPbI3", "T80"], "depth": 1}` | 给定节点的邻域子图 | 对得齐 |
| `stats` | `{}` | 规模与类型分布（**唯一不需要证据的一类**） | 完整性 |

## 可直接使用的 queries.json（示例项目）

```json
{"queries": [
  {"id": "q1", "type": "entity", "question": "材料里关于 MAPbI3 有哪些可回查的原始位置？",
   "args": {"entity": "MAPbI3"}, "expect": "别名 + 全部 occurrence + 全部关联边（含引文）"},
  {"id": "q2", "type": "neighbors", "question": "与 T80 直接相连的有哪些实体、各由谁报告？",
   "args": {"entity": "T80", "depth": 1}, "expect": "列出边与各自的条件与来源"},
  {"id": "q3", "type": "relation", "question": "图谱里所有 improves 边及各自依据？",
   "args": {"relation": "improves"}, "expect": "每条边带逐字引文与位置"},
  {"id": "q4", "type": "path", "question": "从 MA vapor treatment 到 grain size 有没有带证据的路径？",
   "args": {"from": "MA vapor treatment", "to": "grain size"}, "expect": "有则给路径，没有则明确说没有"},
  {"id": "q5", "type": "conflicts", "question": "跨篇的冲突/不可合并分歧有哪些？",
   "args": {}, "expect": "冲突记录 + 各自证据位置"},
  {"id": "q6", "type": "keyword", "question": "哪些位置提到湿度相关条件？",
   "args": {"keyword": "humidity"}, "expect": "命中条件节点与带条件的引文"},
  {"id": "q7", "type": "stats", "question": "图谱规模与关系类型分布？",
   "args": {}, "expect": "节点/边计数与类型分布"}
]}
```

## 写查询的三条纪律

1. **问题要真**：写成一个研究者会真问的问题，而不是"证明我的图谱能用"的摆设；空结果也要如实记录。
2. **参数用原文写法**：`entity` / `from` / `to` 写 label 或 alias（查询器会解析别名）；写不存在的名字会得到空结果，不会善报。
3. **答案与证据一起给**：`answer` 是给人读的结论，`rows[].evidence` 是回查入口；两者缺一不可。
