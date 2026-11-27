# 第一期周赛作品（week1）

本目录收录 BOHRIUM 产品周赛·北京化工大学分站赛第一期的参赛作品。每题一个自包含目录，内含 `SKILL.md`、`scripts/` 与 `examples/`，可原样作为 `/app/submission` 提交；目录内容与该题提交包一致。仓库根目录是首份作品「论文转学术 PPT」。

| 题号 | 题目 | Skill | 目录 |
|---|---|---|---|
| 阅读01 | 文献文档解析 | `paper-parse-md` | [r01-parse](./r01-parse/) |
| 阅读03 | 文献翻译 | `paper-translate` | [r03-translate](./r03-translate/) |
| 阅读10 | 文献总结与结构化笔记 | `paper-notes` | [r10-notes](./r10-notes/) |
| 阅读14 | Nanopublication 断言抽取 | `nanopub-claims` | [r14-nanopub](./r14-nanopub/) |
| 阅读15 | 文献知识图谱构建 | `literature-kg` | [r15-kg](./r15-kg/) |
| 写作02 | 学术语言润色 | `paper-polish` | [w02-polish](./w02-polish/) |
| 写作04 | 引用管理与格式核对 | `cite-manager` | [w04-cite](./w04-cite/) |
| 写作08 | 引言与相关工作写作 | `paper-intro` | [w08-intro](./w08-intro/) |
| 写作09 | 方法与实验章节写作 | `paper-method` | [w09-method](./w09-method/) |

## 约定

- 每个目录的 `README.md` 写明适用条件、依赖、调用方式与已知限制；`SKILL.md` 是对 Agent 的入口说明。
- 纯 Python 实现，唯一外部依赖为 PyMuPDF；不联网、不调用外部服务，只在输出目录写文件。
- `examples/` 只放 UTF-8 文本与生成示例 PDF 的脚本，不含预制案例答案或正式测试产物。
- 各目录 `GITHUB_URL.txt` 第一行即该作品的公开链接。

## 提交

```bash
playground submit --challenge-id <id> --outputs <dir> \
  --trace trace.jsonl --model dsflash-high --harness SciMaster
```
