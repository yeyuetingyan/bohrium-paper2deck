#!/usr/bin/env python3
"""Generate a small synthetic manuscript + case.json for local verification.

The synthetic manuscript is deliberately seeded with the failure modes the
skill is designed to catch: English-as-a-second-language phrasing, redundant
nominalisation, subject-verb disagreement, comma splices, punctuation drift,
hyphenation and capitalisation drift, an acronym used before its definition,
absolute claims, and hedging that must not be strengthened or weakened.

Every fact-like element (numbers, units, citations, cross references, formulas)
is intentional: the assembler must prove they survive polishing unchanged.

Usage:
  python make_sample_manuscript.py [outdir]      # default: ./sample
"""

from __future__ import annotations

import json
import os
import sys

PARAS = [
    ("heading", "# Interfacial Passivation of Perovskite Solar Cells with Phenethylammonium Iodide"),

    ("front-matter", "Abstract: In recent years, with the rapid development of perovskite "
                     "photovoltaics, the interfacial passivation of PSC has attracted more and "
                     "more attention. In this work, we conduct an investigation of "
                     "phenethylammonium iodide (PEAI) treatment on MAPbI3 films. The results "
                     "shows that the treated devices reach a power conversion efficiency (PCE) "
                     "of 23.5 % under 1 sun illumination, with an open-circuit voltage of 1.12 V "
                     "and a short-circuit current density of 23.5 mA cm-2 [12]. The unencapsulated "
                     "devices retains 78% of their initial efficiency after 1000 h at 45% "
                     "relative humidity. These findings proves that PEAI passivation is the best "
                     "strategy for stable PSC."),

    ("heading", "## 1. Introduction"),

    ("body", "Metal halide perovskites have attracted more and more attention because of their "
             "tunable bandgap and long carrier diffusion length [3,4]. Perovskite solar cells "
             "(PSC) have reached certified efficiencies above 26%, yet interfacial defects limit "
             "both efficiency and stability. It is worth noting that "
             "interfacial defects play an important role in non-radiative recombination, however, "
             "the mechanisms of passivation remain debated (Smith et al., 2021). In order to "
             "suppress these defects, several groups perform a comparison of ammonium salts. "
             "PEAI was reported to passivate the surface of PSC, but the reported stability gains "
             "are inconsistent across laboratories."),

    ("heading", "## 2. Methods"),

    ("body", "MAPbI3 precursor solutions were prepared at 2.5 mg mL-1 in dimethylformamide. "
             "Films were deposited by spin-coating at 3000 rpm for 30 s,then annealed at 150 C for "
             "10 min. PEAI was dissolved in isopropanol and spin-coated onto the cooled films. "
             "Control samples were prepared by spin coating without PEAI. X-ray diffraction (XRD) "
             "patterns were collected on a diffractometer using Cu K-alpha radiation."),

    ("body", "Absorption spectra were recorded from 300 nm to 800 nm. The film thickness was "
             "determined by a stylus profilometer, as described in Section 2.1. Steady-state "
             "photoluminescence was excited at 532 nm and the decay was fitted with a "
             "bi-exponential function, see Eq. (4)."),

    ("heading", "## 3. Results"),

    ("body", "Figure 2 shows the XRD patterns of the control and PEAI-treated films. The "
             "(110) reflection at 14.1 degrees is unchanged, while the PbI2 peak at 12.7 degrees "
             "decreases after treatment. The results indicates that unreacted PbI2 is converted "
             "into the perovskite phase,these observations are consistent with a surface "
             "reaction."),

    ("body", "The treated films exhibit a longer carrier lifetime (Table 1). The average PCE "
             "increases from 20.1% to 23.5%, and the hysteresis index decreases from 0.08 to "
             "0.02. The champion device retains 78% of its initial efficiency after 1000 h at "
             "85% relative humidity, which suggests that the passivation layer slow down "
             "moisture ingress."),

    ("heading", "## 4. Discussion"),

    ("body", "The improvement is clearly caused by defect passivation, since the PL lifetime "
             "increases by a factor of 3. The PEAI layer always reduces surface defects. We "
             "note that the stability trend may depend on the encapsulation strategy, and the "
             "mechanism is not fully resolved. Our data indicate that the passivation is partly "
             "reversible at elevated temperature."),

    ("body", "Several limitations should be considered. Devices were measured under 45% relative "
             "humidity,whereas field conditions vary widely. The absorption edge at 780 nm is "
             "unchanged, which indicates that the treatment does not alter the bandgap. Long-term "
             "operation data are not available in this work."),

    ("heading", "## 5. Conclusion"),

    ("body", "We prove that PEAI passivation improves both efficiency and moisture stability of "
             "MAPbI3 devices. The treated devices are more stable than the controls under the "
             "conditions tested here. Future work will examine whether the same treatment is "
             "effective for wider-bandgap compositions."),
]


def build(outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    text = "\n\n".join(p[1] for p in PARAS) + "\n"
    path = os.path.join(outdir, "manuscript.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    glossary = [
        {"term": "perovskite solar cell", "preferred": "perovskite solar cell",
         "variants": ["perovskite solar cells", "PSC"], "note": "首次出现给出全称与缩写，其后统一用缩写"},
        {"term": "power conversion efficiency", "preferred": "power conversion efficiency",
         "variants": ["PCE"], "note": "缩写仅在全称首次出现后使用"},
        {"term": "spin-coating", "preferred": "spin-coating",
         "variants": ["spin coating"], "note": "连字符写法需全篇统一"},
        {"term": "X-ray diffraction", "preferred": "X-ray diffraction",
         "variants": ["XRD", "x-ray diffraction"], "note": "大写 X，缩写统一"},
    ]
    case = {
        "case_id": "synth-polish-0001",
        "manuscript_path": "manuscript.md",
        "style": "journal-article",
        "audience": "peer reviewers and journal readers",
        "target_language": "en",
        "task": ("Polish the manuscript for submission to an English-language journal: fix "
                 "grammar, syntax, punctuation and word choice; keep every number, unit, "
                 "citation and cross reference unchanged; unify terminology; do not strengthen "
                 "or weaken any claim. Return the full revised text plus a per-edit record."),
        "glossary": glossary,
        "output_contract": {
            "manuscript": {"type": "text", "default": "revised.md"},
            "edits": {"type": "records", "default": "edits.jsonl"},
            "diff": {"type": "text", "default": "diff.md"},
            "glossary": {"type": "text", "default": "glossary.tsv"},
            "consistency": {"type": "json", "default": "consistency.json"},
            "check": {"type": "json", "default": "check.json"},
            "review": {"type": "text", "default": "review.md"},
        },
    }
    cpath = os.path.join(outdir, "case.json")
    with open(cpath, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return {"manuscript": path, "case": cpath, "chars": len(text)}


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")
    print(json.dumps(build(out), ensure_ascii=False))
