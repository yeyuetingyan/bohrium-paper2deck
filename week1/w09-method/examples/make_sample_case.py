#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 w09 方法的合成测试案例（示意材料，非正式测试案例）。

产出 <out>/materials/ 下四份形态各异的材料 + <out>/case.json：
  factsheet.md      —— 作者手写的事实底稿（含方法草稿、零散设置、限制）
  config.yaml       —— 训练配置（参数主要来源）
  train.log.txt         —— 实验日志（含阶段标记、硬件、版本、指标）
  prepare_data.py   —— 数据预处理脚本（步骤与数据集信息）
  dataset_notes.md  —— 数据集说明（版本、规模、划分）

刻意埋入的检验点：
  * 参数冲突：config.yaml 里 batch_size=32，train.log.txt 里 batch_size=64
  * 随机种子只在日志里出现一次，配置里没有
  * 一条笼统限制（"有待进一步研究"）与两条具体限制
  * 对照基线只在事实底稿里点名，未给版本
"""
from __future__ import annotations

import argparse
import io
import json
import os

FACTSHEET = """# 实验记录底稿（作者手写，未整理）

## 想法
我们想搞清楚稀疏注意力在长文档检索任务上到底值不值。上个月跑了三组实验，笔记比较乱，先记下来。

## 方法草稿
先把文档切成 512 token 的块，用 BM25 先召回候选，再用双塔编码器打分；编码器用的是 6 层 Transformer，
隐藏维度 768，8 个注意力头。为了省显存，前两层改成稀疏注意力（局部窗口 64 + 全局 token 16 个）。
训练目标还是对比学习，温度系数 0.07。

## 实验设置
机器是 2 x A100 80G，CUDA 11.8，torch 2.1.0。学习率 3e-5，warmup 500 步，训练 12 个 epoch，权重衰减 0.01。
训练时 batch_size 在配置里写的是 32，但日志里我看到的是 64，应该是后来改了配置没同步，以实际跑的那次为准（需要确认）。
评测用的检索指标是 Recall@20 和 nDCG@10。每个设置重复 3 次，报平均值和标准差。

## 对照
跟我们自己的 dense-only 模型比（baseline），也跟 BM25 基线比。基线用的是同一批数据、同样的训练预算，
但我们当时没记下 dense-only 的具体版本号，需要从实验记录里翻。

## 数据集
用两个数据集：LongDocQA（版本 v2.1）和 MSMarco-Doc（版本 v1）。LongDocQA 原始 12 万篇文档，清洗后 9.8 万篇；
MSMarco-Doc 用了 320 万篇的子集。划分是 8:1:1，按文档 id 哈希分桶，避免同一篇文档的查询跨集合。
预处理：去掉了长度小于 20 token 的文档，统一小写，去掉了 HTML 标签。

## 限制
1. 当文档长度超过 8192 token 时，我们的局部窗口会漏掉远距离依赖，此时 Recall@20 会明显下降。
2. 稀疏注意力在 batch_size 小于 8 时收益不稳定，小批量场景不建议使用。
3. 稀疏注意力的理论加速比还有待进一步研究。

## 复现
代码在仓库里，训练用 `python train_retriever.py --config configs/sparse.yaml`，
数据获取脚本是 `python prepare_data.py --dataset longdocqa --out data/`。
环境用 requirements.txt 固定，但里面没写死 CUDA 版本。
"""

CONFIG = """# 训练配置（configs/sparse.yaml）
model:
  name: sparse-dual-encoder
  hidden_dim: 768
  num_layers: 6
  num_heads: 8
  dropout: 0.1
  max_seq_len: 512
sparse:
  window_size: 64
  global_tokens: 16
  enable_layers: 2
train:
  batch_size: 32
  learning_rate: 3.0e-05
  warmup_steps: 500
  weight_decay: 0.01
  epochs: 12
  temperature: 0.07
  grad_clip: 1.0
  fp16: true
data:
  train_file: data/longdocqa_train.jsonl
  val_file: data/longdocqa_val.jsonl
  test_file: data/longdocqa_test.jsonl
  max_docs: 98000
eval:
  metrics: [recall@20, ndcg@10]
  top_k: 100
"""

TRAIN_LOG = """[2026-10-08 09:12:03] [env] host=gpu-node-07 python=3.10.13 torch=2.1.0+cu118 cuda=11.8 cudnn=8.9.2
[2026-10-08 09:12:03] [env] CUDA_VISIBLE_DEVICES=0,1 nvidia-smi: 2 x A100 80G driver=535.104.05
[2026-10-08 09:12:04] [stage] load_data dataset=LongDocQA version=v2.1 docs=98000
[2026-10-08 09:12:31] [stage] tokenize max_seq_len=512 stride=128
[2026-10-08 09:13:02] [stage] build_index retriever=bm25 top_k=100
[2026-10-08 09:13:40] [stage] train start epochs=12 batch_size=64 lr=3e-05 seed=1234
[2026-10-08 09:20:11] epoch=1 loss=0.4812 recall@20=0.512 ndcg@10=0.397
[2026-10-08 09:28:44] epoch=2 loss=0.4103 recall@20=0.578 ndcg@10=0.451
[2026-10-08 09:37:20] epoch=3 loss=0.3861 recall@20=0.606 ndcg@10=0.474
[2026-10-08 09:46:02] epoch=4 loss=0.3702 recall@20=0.623 ndcg@10=0.489
[2026-10-08 09:54:39] epoch=5 loss=0.3598 recall@20=0.634 ndcg@10=0.497
[2026-10-08 10:03:15] epoch=6 loss=0.3521 recall@20=0.641 ndcg@10=0.503
[2026-10-08 10:12:00] epoch=7 loss=0.3466 recall@20=0.646 ndcg@10=0.507
[2026-10-08 10:20:41] epoch=8 loss=0.3422 recall@20=0.649 ndcg@10=0.510
[2026-10-08 10:29:18] epoch=9 loss=0.3388 recall@20=0.651 ndcg@10=0.512
[2026-10-08 10:38:02] epoch=10 loss=0.3361 recall@20=0.653 ndcg@10=0.513
[2026-10-08 10:46:37] epoch=11 loss=0.3340 recall@20=0.654 ndcg@10=0.514
[2026-10-08 10:55:12] epoch=12 loss=0.3324 recall@20=0.655 ndcg@10=0.515
[2026-10-08 11:02:44] [stage] eval test split=test recall@20=0.655 ndcg@10=0.515 latency_ms=38.4
[2026-10-08 11:03:10] [stage] done checkpoint=runs/sparse-v2/ckpt-12.pt
"""

CODE = '''#!/usr/bin/env python3
"""prepare_data.py —— 数据集下载与预处理（示意代码）。"""
import argparse
import hashlib


def download(dataset, out):
    """下载原始数据集到 out 目录。"""
    print("downloading %s" % dataset)


def clean(docs, min_tokens=20):
    """去掉过短文档、HTML 标签，统一小写。"""
    out = []
    for d in docs:
        t = d.lower()
        if len(t.split()) >= min_tokens:
            out.append(t)
    return out


def split_by_hash(docs, ratios=(0.8, 0.1, 0.1)):
    """按文档 id 哈希分桶，保证同一文档不跨集合。"""
    buckets = {"train": [], "val": [], "test": []}
    for d in docs:
        h = int(hashlib.md5(d["id"].encode()).hexdigest(), 16) % 10
        key = "train" if h < 8 else ("val" if h == 8 else "test")
        buckets[key].append(d)
    return buckets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    download(a.dataset, a.out)


if __name__ == "__main__":
    main()
'''

DATASET_NOTES = """# 数据集说明

## LongDocQA
- 版本：v2.1（2026-03-14 发布）
- 规模：原始 120,000 篇文档，清洗后 98,000 篇；查询 8,400 条
- 领域：长文档问答（技术手册、年报）
- 预处理：去 HTML 标签、统一小写、丢弃 <20 token 的文档
- 划分：train:val:test = 8:1:1，按文档 id 的 md5 哈希分桶
- 用途：训练与主评测

## MSMarco-Doc
- 版本：v1
- 规模：使用 3,200,000 篇的子集
- 用途：跨数据集泛化验证（仅测试）
"""

CASE = {
    "case_id": "synth-w09-0001",
    "task": "依据提供的材料，撰写「方法与实验章节」，包含方法步骤、实验设置、参数、数据集与划分、对照实验、复现与限制六部分；"
            "所有数值必须可回溯到材料，缺口与需人工确认处要显式标注。",
    "audience": "期刊审稿人与希望复现该实验的研究者",
    "genre": "journal-article",
    "language": "en",
    "format_constraints": {"max_words": 1200, "sections": ["methods", "settings", "params", "datasets",
                                                           "baselines", "reproducibility", "limitations"]},
    "output_contract": {
        "methods": {"required": True, "default": None},
        "params": {"required": True, "default": None},
        "elements": {"required": True, "default": None},
        "gaps": {"required": True, "default": None},
        "repro": {"required": True, "default": None},
        "check": {"required": True, "default": None},
        "review": {"required": False, "default": None},
    },
    "material_files": [
        "materials/factsheet.md",
        "materials/config.yaml",
        "materials/train.log.txt",
        "materials/prepare_data.py",
        "materials/dataset_notes.md",
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="输出目录（会创建 materials/ 子目录）")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    md = os.path.join(out, "materials")
    os.makedirs(md, exist_ok=True)
    payload = {
        "factsheet.md": FACTSHEET,
        "config.yaml": CONFIG,
        "train.log.txt": TRAIN_LOG,
        "prepare_data.py": CODE,
        "dataset_notes.md": DATASET_NOTES,
    }
    for name, text in payload.items():
        with io.open(os.path.join(md, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    with io.open(os.path.join(out, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(CASE, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"out": out, "files": len(payload) + 1}, ensure_ascii=False))


if __name__ == "__main__":
    main()
