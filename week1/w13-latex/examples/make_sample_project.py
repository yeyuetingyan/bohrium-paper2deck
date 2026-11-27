#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个含"真缺陷"的 LaTeX 最小工程，用于自测 tex_prep / tex_assemble。

用法：
    python make_sample_project.py [--out <目录>]      # 默认写到 <本文件目录>/sample_project

产出：
    sample_project/main.tex           含 10 类确定可检出缺陷的主文件
    sample_project/sections/method.tex 被 \\input 的子文件
    sample_project/references.bib     文献库（故意缺一条被引用的）
    sample_project/factsheet.md       事实底稿（数值/结论的来源）
    example_case.json                 指向上述材料的 case 文件

缺陷清单（与 expected_issues 对应）：
    brace_unbalanced / unclosed_env / undefined_ref / undefined_citation /
    numbered_equation_without_label / table_column_mismatch / table_no_rules /
    placeholder_left / package_order / missing_input
"""

import argparse
import io
import json
import os

MAIN_TEX = r"""% !TEX program = pdflatex
% 合成样例：用于测试 LaTeX Skill 的问题检出与修复流程（不是真实投稿）
\documentclass[11pt,a4paper]{article}

\usepackage[T1]{fontenc}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{hyperref}
\usepackage{cleveref}

\title{Stability of $\mathrm{MAPbI_3}$ Solar Cells under Damp Heat}
\author{Sample Author}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
We study the damp-heat stability of MAPbI3 solar cells and report a champion
power conversion efficiency of 23.5\% with an open-circuit voltage of 1.12~V.
\end{abstract}

\section{Introduction}
Perovskite solar cells have reached certified efficiencies above 25\% \cite{smith2021}.
The operational stability remains the limiting factor for deployment \cite{li2020}.
Recent work on passivation shows promise \cite{chen2019}, but the reported gains
depend strongly on the encapsulation scheme.
{TODO: add the missing paragraph on grain-boundary passivation.

\section{Methods}
\input{sections/method}

\section{Results}
Devices retained 78\% of their initial efficiency after 1000~h at 45\% relative
humidity, consistent with \cref{tab:stability} and \cref{sec:discussion}.
The fill factor settled at 78\% in all three independent runs.

\begin{equation}
\eta = \frac{P_{\max}}{P_{\mathrm{in}}} = \frac{V_{\mathrm{oc}}\,J_{\mathrm{sc}}\,\mathrm{FF}}{P_{\mathrm{in}}}
\end{equation}

\begin{table}[t]
\centering
\caption{Stability summary at 85~$^\circ$C and 85\% RH.}
\label{tab:stability}
\begin{tabular}{lcc}
Sample & $T_{80}$ (h) & Retention (\%)
Untreated & 300 & 41 \\
PEAI-treated & 1000 & 78 & extra \\
\end{tabular}
\end{table}

\section{Discussion}
\label{sec:discussions}
The improvement is consistent with reduced surface recombination
\begin{itemize}
\item lower non-radiative loss
\item suppressed ion migration

\section{Conclusion}
Passivation raises the damp-heat lifetime by a factor of three.

\bibliographystyle{plain}
\bibliography{references}

\end{document}
"""

METHOD_TEX = r"""% 子文件：方法段
Samples were spin-coated at 3000~rpm from a 1.2~M precursor solution.
Absorbance was recorded between 300--800~nm with a UV--vis spectrometer.
Current--voltage curves were measured under AM1.5G illumination.
Repeated measurements used a fixed random seed (1234) for the fitting routine.
"""

BIB = r"""@article{smith2021,
  author = {Smith, Alice and Khan, Bilal},
  title = {Certified efficiency of perovskite photovoltaics},
  journal = {Nature Energy},
  year = {2021},
  volume = {6},
  pages = {1--9},
  doi = {10.0000/synth.2021.0001}
}

@article{li2020,
  author = {Li, Chen and Zhao, Yue},
  title = {Damp-heat degradation pathways in hybrid perovskites},
  journal = {Joule},
  year = {2020},
  volume = {4},
  pages = {2100--2115},
  doi = {10.0000/synth.2020.0002}
}
"""

FACTSHEET = r"""# 事实底稿（合成样例）

- 器件结构：FTO/TiO2/MAPbI3/PEAI/Ag，对比组不含 PEAI。
- 制备：1.2 M 前驱液，3000 rpm 旋涂，退火 100 C / 10 min。
- 光电性能：冠军器件 PCE 23.5%，开路电压 1.12 V，填充因子 78%。
- 稳定性：85 C / 85% RH 环境下，未处理样品 T80 = 300 h，PEAI 处理样品 T80 = 1000 h；
  45% RH 条件下 1000 h 后保持初始效率的 78%。
- 复现设置：拟合程序随机种子固定为 1234；三个独立器件各测三次。
- 光谱：吸收测试覆盖 300--800 nm。
- 结论：表面钝化把湿热寿命提高到约三倍。
- 局限：未做长期户外验证；样品批次只有两批。
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_project"))
    args = ap.parse_args()
    out = args.out
    os.makedirs(os.path.join(out, "sections"), exist_ok=True)

    def w(rel, text):
        p = os.path.join(out, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return p

    w("main.tex", MAIN_TEX)
    w("sections/method.tex", METHOD_TEX)
    w("references.bib", BIB)
    w("factsheet.md", FACTSHEET)

    case = {
        "case_id": "synth-w13-0001",
        "task": "修复这份 LaTeX 稿件的编译问题，使其在 pdflatex 下编译通过，并保持数值与引用不变。",
        "audience": "期刊编辑与排版人员",
        "genre": "journal-article",
        "language": "en",
        "engine": "pdflatex",
        "format_constraints": {"template": "article", "max_pages": 8},
        "output_contract": {
            "revised": {"required": True},
            "changes": {"required": True},
            "diagnosis": {"required": True},
            "checklist": {"required": True},
            "source_map": {"required": True},
            "check": {"required": True},
            "review": {"required": True},
        },
        "material_files": [
            "sample_project/main.tex",
            "sample_project/sections/method.tex",
            "sample_project/references.bib",
            "sample_project/factsheet.md",
        ],
    }
    case_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_case.json")
    with io.open(case_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"out": out, "case": case_path}, ensure_ascii=False))


if __name__ == "__main__":
    main()
