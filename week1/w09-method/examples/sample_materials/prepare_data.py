#!/usr/bin/env python3
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
