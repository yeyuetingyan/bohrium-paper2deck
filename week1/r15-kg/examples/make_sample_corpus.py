#!/usr/bin/env python3
"""生成两篇合成论文的测试语料（corpus-manifest / material / primary-material / secondary-material）。

用途：本地端到端验证与示例。**这不是平台测试集**——平台的固定案例在评测沙箱里注入，
形状与本文件产出的四份 JSON 一致（段落级 ID + 独立 source_id），但内容不同。

设计要点（对着题面第 84-88 行的口径来）：
* 两篇独立论文：primary 是原论文，secondary 是新增论文；**根 title/doi/authors 属于第一篇**。
* 段位用组织方口径的段落 ID（`p-<sec>-<idx>`），**没有 PDF 页码**。
* 故意埋了三类对齐陷阱，供 kg_prep/kg_assemble 展示：
  1. 可合并：`MAPbI3` / `CH3NH3PbI3` 同物异写；`perovskite solar cell (PSC)` 与后文 `PSC`。
  2. 不可合并：两篇的 `T80` 是同一指标名但在**不同湿度条件**下测得 → 条件不同，结论不得合并。
  3. 冲突：论文明说湿度加速衰减，新论文在封装条件下报告湿度下稳定性提升 → `conflicts_with` 必须保留。
  4. 同名不同物：两篇都出现 `MA`，但新论文里的 `MA` 指 methylamine 处理剂而非 methylammonium。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os


def sha16(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


PRIMARY_TITLE = "Humidity-Assisted Degradation Pathways in MAPbI3 Perovskite Solar Cells"
PRIMARY_DOI = "10.0000/synth.2026.0001"
PRIMARY_AUTHORS = ["Wei Zhang", "Lina Chen", "Haoran Xu"]
PRIMARY_LICENSE = "CC-BY-4.0 (synthetic fixture)"

SECONDARY_TITLE = "Encapsulated Cs0.05FA0.95PbI3 Devices Retain Efficiency under Damp Heat"
SECONDARY_DOI = "10.0000/synth.2026.0002"
SECONDARY_AUTHORS = ["Marta Ferreira", "Kenji Ito"]
SECONDARY_LICENSE = "CC-BY-4.0 (synthetic fixture)"

PRIMARY_SECTIONS = [
    ("Introduction", [
        "Perovskite solar cells (PSC) have reached certified power conversion efficiencies above 25%, "
        "yet their operational stability remains the main obstacle to commercialization.",
        "Methylammonium lead iodide (CH3NH3PbI3) is the most studied absorber, but it is known to "
        "decompose under humid air because the methylammonium cation is hygroscopic.",
        "Zhang et al. reported that devices degraded when the relative humidity exceeded 40%, though "
        "the reported lifetime varied widely across laboratories.",
    ]),
    ("Methods", [
        "We fabricated MAPbI3 films by spin-coating a 1.2 M precursor solution onto mesoporous TiO2, "
        "followed by annealing at 100 C for 10 min on a hot plate.",
        "Film morphology was characterized by scanning electron microscopy (SEM) and crystal structure "
        "by X-ray diffraction (XRD) using Cu K-alpha radiation.",
        "Stability tests were performed in a climate chamber at 25 C and 45% relative humidity under "
        "1 sun illumination, and T80 was defined as the time to 80% of the initial efficiency.",
    ]),
    ("Results", [
        "The pristine MAPbI3 devices reached an average power conversion efficiency (PCE) of 18.4% "
        "with a short-circuit current density of 22.1 mA cm-2 and an open-circuit voltage of 1.05 V.",
        "Under the 45% relative humidity test, T80 was 720 h for pristine devices and only 310 h for "
        "devices without encapsulation.",
        "XRD showed that the (110) reflection of CH3NH3PbI3 weakened after 300 h, and a PbI2 peak at "
        "12.7 degrees appeared, indicating decomposition of the absorber.",
        "SEM images revealed pinholes at grain boundaries after 300 h, and these pinholes correlated "
        "with the loss of open-circuit voltage.",
    ]),
    ("Discussion", [
        "Our results indicate that humidity degrades MAPbI3 devices mainly by decomposing the "
        "methylammonium cation, which reduces open-circuit voltage before the current density drops.",
        "The spread of T80 values in the literature is therefore explained by different humidity "
        "conditions rather than by different absorber chemistry.",
        "We conclude that reporting T80 without the humidity condition is not meaningful, and we "
        "recommend that future studies report the full damp-heat profile.",
    ]),
]

SECONDARY_SECTIONS = [
    ("Introduction", [
        "Triple-cation absorbers such as Cs0.05FA0.95PbI3 have replaced MAPbI3 in many record "
        "devices, but their behavior under damp heat is still debated.",
        "In this work we ask whether encapsulation alone can stabilize the absorber, using the same "
        "T80 metric that earlier MAPbI3 studies adopted.",
        "We note that methylamine (MA) vapor treatment is often used to recrystallize the film, and "
        "the abbreviation MA in this paper refers to methylamine unless stated otherwise.",
    ]),
    ("Methods", [
        "Cs0.05FA0.95PbI3 films were deposited by two-step spin-coating, and one batch received a "
        "methylamine (MA) vapor treatment for 30 s before encapsulation.",
        "Encapsulation used a glass-to-glass epoxy seal with a desiccant edge, applied in a nitrogen "
        "glovebox at 20 C.",
        "Damp-heat testing followed the same protocol as the earlier MAPbI3 work, at 25 C and 85% "
        "relative humidity under 1 sun.",
    ]),
    ("Results", [
        "Encapsulated Cs0.05FA0.95PbI3 devices retained 92% of their initial efficiency after 1000 h "
        "and reached a T80 of 1400 h at 85% relative humidity.",
        "Unencapsulated control devices reached a T80 of only 260 h under the same damp-heat "
        "condition, which is consistent with the role of the seal rather than of the absorber.",
        "The MA vapor treatment increased the average grain size from 320 nm to 780 nm and improved "
        "the power conversion efficiency from 20.1% to 21.6%.",
        "We attribute the improved damp-heat stability to the epoxy seal blocking water ingress, and "
        "we do not attribute it to the cesium content alone.",
    ]),
    ("Discussion", [
        "Our damp-heat results conflict with the claim that humidity always accelerates degradation: "
        "with encapsulation, humidity exposure for 1000 h did not degrade the device.",
        "However, the two studies used different absorbers and different humidities, so the T80 "
        "values must not be merged into one number.",
        "We conclude that the humidity threshold reported for MAPbI3 cannot be transferred to "
        "Cs0.05FA0.95PbI3 devices without re-measuring the full profile.",
    ]),
]

# 段落级 ID：组织方口径（JATS 段落 ID），不是 PDF 页码
def _paragraphs(sections, sid):
    out = []
    for si, (title, paras) in enumerate(sections, start=1):
        for pi, text in enumerate(paras, start=1):
            out.append({"paragraph_id": f"p-{si}-{pi:03d}", "section": title, "text": text})
    return out


def _paper_doc(sid, title, doi, authors, license_, sections, role):
    return {
        "source_id": sid,
        "role": role,
        "title": title,
        "doi": doi,
        "authors": authors,
        "license": license_,
        "source_sha256": None,  # 稍后按正文补
        "sections": [
            {"title": t, "paragraphs": [
                {"paragraph_id": f"p-{si}-{pi:03d}", "text": txt}
                for pi, txt in enumerate(paras, start=1)
            ]}
            for si, (t, paras) in enumerate(sections, start=1)
        ],
    }


def build():
    pdoc = _paper_doc("synth-primary-0001", PRIMARY_TITLE, PRIMARY_DOI, PRIMARY_AUTHORS,
                      PRIMARY_LICENSE, PRIMARY_SECTIONS, "primary")
    sdoc = _paper_doc("synth-secondary-0002", SECONDARY_TITLE, SECONDARY_DOI, SECONDARY_AUTHORS,
                      SECONDARY_LICENSE, SECONDARY_SECTIONS, "secondary")
    ptext = "\n".join(p["text"] for p in _paragraphs(PRIMARY_SECTIONS, "synth-primary-0001"))
    stext = "\n".join(p["text"] for p in _paragraphs(SECONDARY_SECTIONS, "synth-secondary-0002"))
    pdoc["source_sha256"] = sha16(ptext)
    sdoc["source_sha256"] = sha16(stext)

    manifest = {
        "schema": "corpus-manifest/1.0",
        "corpus_id": "synth-damp-heat-2papers",
        "papers": [
            {"source_id": pdoc["source_id"], "doi": pdoc["doi"], "title": pdoc["title"],
             "authors": pdoc["authors"], "license": pdoc["license"], "role": "primary",
             "source_sha256": pdoc["source_sha256"]},
            {"source_id": sdoc["source_id"], "doi": sdoc["doi"], "title": sdoc["title"],
             "authors": sdoc["authors"], "license": sdoc["license"], "role": "secondary",
             "source_sha256": sdoc["source_sha256"]},
        ],
        "notes": [
            "根 DOI/title/authors 属于第一篇论文，不得套用到第二篇。",
            "段落位置是组织方 JATS 段落 ID，本语料不含 PDF 页码。",
        ],
    }
    # 汇总索引：两篇的段落汇总（每段保留 source_id，避免跨篇串号）
    material = {
        "schema": "material-index/1.0",
        "corpus_id": manifest["corpus_id"],
        "paragraph_count": len(_paragraphs(PRIMARY_SECTIONS, "")) + len(_paragraphs(SECONDARY_SECTIONS, "")),
        "papers": [
            {"source_id": pdoc["source_id"], "title": pdoc["title"], "doi": pdoc["doi"],
             "authors": pdoc["authors"], "license": pdoc["license"],
             "paragraphs": _paragraphs(PRIMARY_SECTIONS, pdoc["source_id"])},
            {"source_id": sdoc["source_id"], "title": sdoc["title"], "doi": sdoc["doi"],
             "authors": sdoc["authors"], "license": sdoc["license"],
             "paragraphs": _paragraphs(SECONDARY_SECTIONS, sdoc["source_id"])},
        ],
    }
    case = {
        "case_id": "synth-damp-heat-2papers",
        "task": ("从两篇论文材料构建一份带证据定位的知识图谱，并回答至少 3 个查询。"),
        "material": "material.json",
        "corpus_manifest": "corpus-manifest.json",
        "primary_material": "primary-material.json",
        "secondary_material": "secondary-material.json",
        "output_contract": {
            "graph": {"type": "file", "default": None},
            "entities": {"type": "file", "default": None},
            "relations": {"type": "file", "default": None},
            "queries": {"type": "file", "default": None},
            "check": {"type": "file", "default": None},
        },
    }
    return {"corpus-manifest.json": manifest, "material.json": material,
            "primary-material.json": pdoc, "secondary-material.json": sdoc, "case.json": case}


def main():
    ap = argparse.ArgumentParser(description="生成 r15 两篇论文的合成测试语料")
    ap.add_argument("out_dir", nargs="?", default="corpus-out")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    for name, doc in build().items():
        p = os.path.join(a.out_dir, name)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"{name}  {os.path.getsize(p)} B")
    print(f"OK -> {os.path.abspath(a.out_dir)}")


if __name__ == "__main__":
    main()
