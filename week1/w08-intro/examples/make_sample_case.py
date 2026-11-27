#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成用于本 Skill 端到端自测的合成案例（材料 + 文献库 + case.json）。

产物（写到 --out 目录）：
  material.md       事实底稿：背景 / 方法 / 结果（含数字）/ 局限 / 贡献线索
  bibliography.bib  文献库（12 条，含 1 条未被引用、1 条被引用但元数据可核对）
  case.json         audience / genre / format_constraints / output_contract / 路径
说明：全部内容为**合成示意**，不得当作任何真实论文的事实。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

MATERIAL = """# 事实底稿（合成示意材料）

## 研究背景

Methylammonium lead iodide (MAPbI3) solar cells have reached certified power conversion efficiency (PCE) above 25% [1], yet operational stability remains the main obstacle to commercialization [2]. Moisture ingress is widely reported to trigger irreversible degradation of the perovskite lattice [3]. Encapsulation strategies based on epoxy seals extend the T80 lifetime from 300 h to 1000 h at 45% relative humidity [4].

## 相关工作

Spin-coated films usually show larger grain size but poorer uniformity than vapor-assisted films [5]. A vapor-assisted route produced grain sizes of 1.2 um with a surface roughness of 18 nm [6]. Solution-processed devices reached 21.4% PCE with a hysteresis index of 0.03 [7]. In contrast, blade-coated devices reached 19.8% PCE at a coating speed of 5 mm s-1 [8]. Additive engineering with phenethylammonium iodide (PEAI) improved the open-circuit voltage to 1.12 V [9].

## 研究空白

The combined effect of vapor-assisted growth and PEAI passivation has not been reported. Few studies quantify moisture-driven lattice strain at the grain boundary. Whether the improved T80 under 45% relative humidity holds at 85% relative humidity remains unknown.

## 本文工作

We propose a two-step route that combines vapor-assisted growth with PEAI passivation. We quantify lattice strain by X-ray diffraction (XRD) at 300-800 nm probe depth. The optimized device reached 23.5% PCE, an open-circuit voltage of 1.12 V, and a short-circuit current density of 23.5 mA cm-2. The T80 lifetime improved to 1000 h at 45% relative humidity, and to 420 h at 85% relative humidity.

## 局限

The strain quantification relies on a single diffraction geometry, so out-of-plane strain cannot be separated from in-plane strain. Devices were measured under 1 sun illumination only; low-light performance was not evaluated. The 85% relative humidity test used three devices, which limits the statistical strength of the T80 value.
"""

BIB = """@article{zhang2021mapbi3,
  author = {Zhang, Wei and Liu, Yan},
  title = {Certified efficiency progress of metal halide perovskite solar cells},
  journal = {Nature Energy},
  year = {2021},
  doi = {10.0000/synth.2021.0001}
}

@article{chen2020stability,
  author = {Chen, Hui and Park, Jimin},
  title = {Operational stability of perovskite photovoltaics: mechanisms and metrics},
  journal = {Joule},
  year = {2020},
  doi = {10.0000/synth.2020.0002}
}

@article{liu2019moisture,
  author = {Liu, Yan and Zhang, Wei},
  title = {Moisture-induced degradation pathways in methylammonium lead iodide},
  journal = {ACS Energy Letters},
  year = {2019},
  doi = {10.0000/synth.2019.0003}
}

@article{wang2022encapsulation,
  author = {Wang, Lei and Sun, Qi},
  title = {Epoxy encapsulation extends T80 lifetime of perovskite modules},
  journal = {Solar RRL},
  year = {2022},
  doi = {10.0000/synth.2022.0004}
}

@article{kumar2018spincoat,
  author = {Kumar, Raj and Silva, Ana},
  title = {Spin coating versus vapor assisted growth of perovskite films},
  journal = {Thin Solid Films},
  year = {2018},
  doi = {10.0000/synth.2018.0005}
}

@article{tanaka2020vapor,
  author = {Tanaka, Ken and Mori, Aya},
  title = {Vapor assisted growth yields micrometer scale grains},
  journal = {Crystal Growth and Design},
  year = {2020},
  doi = {10.0000/synth.2020.0006}
}

@article{nguyen2021hysteresis,
  author = {Nguyen, Binh and Tran, Lan},
  title = {Hysteresis suppression in solution processed perovskite devices},
  journal = {Advanced Materials},
  year = {2021},
  doi = {10.0000/synth.2021.0007}
}

@article{garcia2019blade,
  author = {Garcia, Marta and Lopez, Diego},
  title = {Blade coating of perovskite films at low coating speed},
  journal = {Progress in Photovoltaics},
  year = {2019},
  doi = {10.0000/synth.2019.0008}
}

@article{jones2023peai,
  author = {Jones, Emily and Brown, Tom},
  title = {Phenethylammonium iodide passivation improves open circuit voltage},
  journal = {Energy and Environmental Science},
  year = {2023},
  doi = {10.0000/synth.2023.0009}
}

@article{ahmed2022strain,
  author = {Ahmed, Omar and Rossi, Luca},
  title = {Lattice strain quantification in perovskite films by X-ray diffraction},
  journal = {Journal of Applied Crystallography},
  year = {2022},
  doi = {10.0000/synth.2022.0010}
}

@article{sato2024lowlight,
  author = {Sato, Rin and Ito, Mei},
  title = {Low light performance of perovskite solar cells for indoor applications},
  journal = {Solar Energy Materials},
  year = {2024},
  doi = {10.0000/synth.2024.0011}
}

@article{moreau2017review,
  author = {Moreau, Claire and Dubois, Paul},
  title = {A review of characterization techniques for hybrid perovskites},
  journal = {Materials Today},
  year = {2017},
  doi = {10.0000/synth.2017.0012}
}
"""

CONTRACT = {
    "introduction": {"description": "可直接进入论文的引言与相关工作正文（研究背景/相关工作/研究空白/贡献四节齐全）", "required": True},
    "claims": {"description": "逐条论断的引用绑定与来源定位", "required": True},
    "contributions": {"description": "贡献条目及其正文/图表/结果锚点", "required": True},
    "groups": {"description": "相关工作的分组与比较维度", "required": True},
    "citation_map": {"description": "引用 key 与文献元数据（作者/年份/来源）的对照", "required": True},
    "check": {"description": "自动核验报告", "required": True},
    "review": {"description": "人工复核清单与边界说明", "required": False},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出目录（同时作为 case 所在目录）")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    mat = os.path.join(args.out, "material.md")
    bib = os.path.join(args.out, "bibliography.bib")
    with open(mat, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MATERIAL)
    with open(bib, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(BIB)
    case = {
        "case_id": "synth-w08-0001",
        "task": "依据事实底稿与文献库，写出可直接进入论文的引言与相关工作（研究背景、相关工作、研究空白、贡献），"
                "每条论断都必须绑定引用与来源，不得引入材料外事实。",
        "audience": "Journal of Materials Chemistry A 的审稿人与读者",
        "genre": "journal-article",
        "language": "en",
        "format_constraints": [
            "四节齐全并按 研究背景 / 相关工作 / 研究空白 / 贡献 顺序承接",
            "引用使用编号制，与 bibliography.bib 中的条目一致",
            "不得使用文献库以外的文献",
            "数字、单位、图表指向必须与事实底稿逐字一致",
        ],
        "material_path": "material.md",
        "bibliography_path": "bibliography.bib",
        "output_contract": CONTRACT,
    }
    p = os.path.join(args.out, "case.json")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    sys.stdout.write(json.dumps({"ok": True, "case": p, "material": mat, "bibliography": bib},
                                ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
