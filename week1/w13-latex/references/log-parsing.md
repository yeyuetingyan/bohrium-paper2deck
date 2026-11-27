# 日志解析（paper-latex）

TeX 日志里的报错从来不是一行一条：一条真错误会引出 `Emergency stop`、一串 `Undefined control
sequence`、以及几十行无关的 `LaTeX Warning`。本项目的解析器目标不是「少报」，而是
**每条真错误都定位到文件与行号，连锁错误只标注不隐藏**。

## 三步

1. **建立文件打开事件表**：TeX 用 `(` / `)` 嵌套表示「进入/离开某个文件」。
   `track_file_events(text)` 扫全日志，把每个 `(` 记成 `open`、`)` 记成 `close`，
   并用文件名正则（`.tex|.sty|.cls|.def|.ltx|cfg|fd|bib|bbl|aux|toc|out|clo|ldf`）取出路径。
   日志里路径常被截断（`/usr/local/texlive/2024/.../article.cls` 与 `./sections/method.tex` 混排），
   所以按「路径片段」而不是「完整路径」匹配。

2. **定位当前文件**：`_file_at(events, pos, prefer_tex=True)` 取该位置最内层的**仍处于打开状态**
   的文件；优先 `.tex`，否则回退到最近的任意已打开文件。

3. **定位行号**：TeX 的行号形态是 `l.42`。`_next_lnum_after(text, pos)` 从报错位置往后找第一个
   `l.NN`。**关键判据**：如果中间先出现**另一条真错误**，那这个行号不属于本条（本条无行号）；
   但 `! Emergency stop` 与 `! ==> Fatal error` 属于**连锁标记**（`CHAIN_MARK_RE`），不阻断行号归属。

## 连锁错误的两种归并

- **缺文件引发的瀑布**：`! LaTeX Error: File 'foo.sty' not found.` 之后紧跟 `! Emergency stop`，
  后者并入前者，前者记 `merged: ['emergency_stop']`。
- **插入型连锁**：`\begin{document} ended by \end{itemize}` 这类，往往是前面某处少了一个 `}`。
  这类错误**保留**，只标注 `cascade: true` / `cascade_of: <根错误 log_line>` / `cascade_count`。
  统计「根因数」时用 `root_errors`（排除 cascade），需要全部错误时用 `errors`。

同一行日志上同时出现环境配对错误与普通错误时，**环境配对错误优先**（它更接近根因）。
缺文件之后紧跟的无行号 `Undefined control sequence` 也并入缺文件那条。

## 错误分类与建议

| category | 触发 | 建议 |
|---|---|---|
| `missing_package` | `File 'x.sty' not found` / `\usepackage` 相关 | 装宏包或换等价宏包 |
| `missing_class` | `File 'x.cls' not found` | 装模板类或用模板给的路径 |
| `missing_bst` | `.bst` 找不到 | 给出 `.bst` 或换 `plain` 风格 |
| `missing_file` | 其它 `File '…' not found` | 补文件或改路径 |
| `wrong_engine` | `ifpdf`/`fontspec` 与新引擎冲突 | 换 `pdflatex` ↔ `xelatex` |
| `math_syntax` | `Missing $ inserted` / `Double subscript` 等 | 补 `$` 或修公式 |
| `brace_error` | `Missing } inserted` / `Extra }` | 配对花括号 |
| `env_mismatch` | `\begin{X} ended by \end{Y}` | 配对环境 |
| `citation` | `Citation 'x' undefined` | 补 bib 条目或删引用 |
| `reference` | `Reference 'x' undefined` / `Rerun` | 补 label 或再编译一轮 |
| `font_error` | `Font … not loadable` | 换字体或换 `xelatex` |
| `encoding` | `Unicode character … not set up` | 加 `inputenc`/`fontspec` |
| `template_requirement` | 模板类自己的必填项报错 | 按模板说明补齐 |
| `unknown` | 其它 `!` 行 | 人工看日志 |

## 多轮编译

`compile_project()` 的顺序是：`engine → (bibtex|biber) → engine → engine …`，最多 `max_passes`
轮，`needs_rerun(parsed)` 为假时提前结束。

- **引擎选择**：显式 `engine` > 源码 `%!TEX program` > 含中文或 `fontspec`/`xeCJK` → `xelatex` > `pdflatex`。
- **文献工具**：`\addbibresource`/`\printbibliography` → `biber`；`\bibliography` → `bibtex`。
- **bib 必须在 `.aux` 所在目录跑**，并注入 `BIBINPUTS` / `BSTINPUTS`（工程目录 + 输出目录），
  否则报 `I couldn't open file name 'xxx.aux'` 或找不到 `.bib`。
- `bibtex` **失败时退出码仍是 0**，所以要按日志标记判失败：
  `I couldn't open` / `I found no \bibdata` / `I found no \bibstyle` / `I found no \citation` /
  `error message` / `Error:` / `fatal error`，结果写进 `passes[].failed`。
- MiKTeX 首次运行会**按需下载宏包**，第一轮可能几十秒到几分钟（实测 xelatex 首轮 249 秒）。
  超时会被单列成 `reason = "engine_timeout"` 并给出提示，不会伪装成编译失败。
