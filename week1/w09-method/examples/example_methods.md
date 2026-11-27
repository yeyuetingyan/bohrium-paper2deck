# Methods and Experimental Section

## 1. Methods

本节按可执行顺序给出检索流水线。整体**输入**是长文档语料与查询集合，**输出**是测试集上的排序结果与指标。

- 文档切块：把每篇文档切成 512 token 的块，相邻块之间 stride 128，**输出**为片段索引。

- 候选召回：用 BM25 建立索引并召回，top_k 100，**输入**为查询，**输出**为候选文档列表。

- 精排打分：用双塔编码器 sparse-dual-encoder 给候选打分。编码器是 6 层 Transformer，隐藏维度 768，8 个注意力头；为省显存，前两层改为稀疏注意力（局部窗口 64，另加 16 个全局 token）。**输出**为候选得分。

- 训练：对比学习目标，温度系数 0.07，**输入**为查询与正负例三元组，**输出**为编码器权重。

- 评测：在测试集上计算 Recall@20 与 nDCG@10，**输出**为指标与逐查询排序；每个设置重复 3 次，报平均值与标准差。

训练入口是 `python train_retriever.py --config configs/sparse.yaml`，数据准备脚本见可复现性一节。

## 2. Experimental Settings

硬件是 2 x A100 80G，运行在 gpu-node-07 上。软件环境为 CUDA 11.8、torch 2.1.0+cu118、python 3.10.13、cudnn 8.9.2，驱动版本 535.104.05。

随机种子固定为 1234。每个设置重复 3 次，报平均值与标准差；环境用 requirements.txt 固定，但其中**没有写死 CUDA 版本**，实际使用的 CUDA 版本以日志记录为准（需要作者确认）。

环境变量 CUDA_VISIBLE_DEVICES=0,1，即使用两张卡并行。

## 3. Parameters

配置文件的超参数如下（取值与来源见 params.tsv，逐行给出文件名与行号）：模型侧 name=sparse-dual-encoder、hidden_dim 768、num_layers 6、num_heads 8、dropout 0.1、max_seq_len 512；稀疏注意力侧 window_size 64、global_tokens 16、enable_layers 2；训练侧 learning_rate 3e-5、warmup_steps 500、epochs 12、weight_decay 0.01、temperature 0.07、grad_clip 1.0；数据与评测侧 max_docs 98000、eval top_k 100、评测指标为 Recall@20 与 nDCG@10。

**batch_size 存在来源冲突**：配置里写的是 32，训练日志里是 64。本稿以实际运行的那次（日志）为准，并把该冲突列入待作者确认清单，不擅自按配置改写。

## 4. Datasets

使用两个数据集。LongDocQA（版本 v2.1，2026-03-14 发布）原始 120,000 篇文档，清洗后 98,000 篇，查询 8,400 条，领域为长文档问答（技术手册、年报）。

MSMarco-Doc（版本 v1）使用 320 万篇的子集，仅用于跨数据集泛化验证（只做测试），因此它的指标不与 LongDocQA 混用。

预处理：去掉长度小于 20 token 的文档，统一小写，去掉 HTML 标签。划分是 8:1:1，按文档 id 的 md5 哈希分桶：训练集、验证集、测试集三者不共享同一篇文档，避免查询跨集合。

## 5. Baselines

对照有两个：一是我们自己的 dense-only 模型（baseline），二是 BM25 基线。两者使用同一批数据、同样的训练预算；**dense-only 的具体版本号在材料中没有记录**，已列入待确认清单。

评价指标为 Recall@20 与 nDCG@10，每个设置重复 3 次并报平均值与标准差；稀疏注意力在 batch_size 小于 8 时收益不稳定，小批量场景不建议使用，因此对照实验统一在 batch_size 64 下进行。

## 6. Reproducibility and Limitations

复现步骤：先用 `python prepare_data.py --dataset longdocqa --out data/` 取得并预处理数据，再用 `python train_retriever.py --config configs/sparse.yaml` 训练；训练完成的权重保存在 runs/sparse-v2/ckpt-12.pt。完整环境与随机种子见实验设置一节。

限制一（具体）：当文档长度超过 8192 token 时，局部窗口会漏掉远距离依赖，此时 Recall@20 会明显下降。

限制二（具体）：稀疏注意力在 batch_size 小于 8 时收益不稳定，小批量场景不建议使用。

材料中「稀疏注意力的理论加速比还有待进一步研究」一句没有给出具体条件，既不能写成结论也不能据此选型，已列入待作者确认清单，正文不引用其数值。
