#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 fixtures 里的两个日志交给 texkit 的解析器，核对"错误定位到文件:行号 + 根因分类"。

用法：
    python check_logs.py [--kit <texkit.py 所在目录>] [--fixtures <fixtures 目录>]

退出码：0 全部断言通过；1 有断言失败。
"""

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

EXPECT = {
    "pdflatex_missing_package.log.txt": {
        "errors": 1,
        "category": "missing_package",
        "file": "main.tex",
        "line": 42,
        "warnings": {"undefined_cites": ["chen2019"]},
    },
    "xelatex_multi_error.log.txt": {
        "errors": 5,
        "root_errors": 4,
        "categories": ["brace_error", "missing_class", "math_syntax", "env_mismatch"],
        "file": "sections/method.tex",
        "lines": [18, 22, 31, 44],
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default=os.path.join(os.path.dirname(HERE), "scripts"))
    ap.add_argument("--fixtures", default=os.path.join(HERE, "fixtures"))
    args = ap.parse_args()
    sys.path.insert(0, args.kit)
    import texkit as tk  # noqa: E402

    results = []
    ok = True
    for name, exp in EXPECT.items():
        path = os.path.join(args.fixtures, name)
        text, _ = tk.read_text_any(path)
        parsed = tk.parse_log(text, default_file="main.tex")
        cats = tk.classify_errors(parsed, text)
        got = {
            "errors": len(parsed["errors"]),
            "root_errors": len([e for e in parsed["errors"] if not e.get("cascade")]),
            "categories": [c["category"] for c in cats],
            "files": sorted({c.get("file") for c in cats if c.get("file")}),
            "lines": sorted({c.get("line") for c in cats if c.get("line")}),
            "undefined_cites": parsed["warnings"]["undefined_cites"],
        }
        row = {"log": name, "got": got, "expected": exp, "pass": True, "fail": []}
        if got["errors"] != exp["errors"]:
            row["pass"] = False
            row["fail"].append("errors %s != %s" % (got["errors"], exp["errors"]))
        if "root_errors" in exp and got["root_errors"] != exp["root_errors"]:
            row["pass"] = False
            row["fail"].append("root_errors %s != %s（cascade 不算独立根因）" % (got["root_errors"], exp["root_errors"]))
        for ln in exp.get("lines", []):
            if ln not in got["lines"]:
                row["pass"] = False
                row["fail"].append("line %s not located (got %s)" % (ln, got["lines"]))
        if "category" in exp and exp["category"] not in got["categories"]:
            row["pass"] = False
            row["fail"].append("category %s missing" % exp["category"])
        for c in exp.get("categories", []):
            if c not in got["categories"]:
                row["pass"] = False
                row["fail"].append("category %s missing" % c)
        if exp.get("file") and exp["file"] not in got["files"]:
            row["pass"] = False
            row["fail"].append("file %s not located (got %s)" % (exp["file"], got["files"]))
        if exp.get("line") and exp["line"] not in got["lines"]:
            row["pass"] = False
            row["fail"].append("line %s not located (got %s)" % (exp["line"], got["lines"]))
        for k, v in (exp.get("warnings") or {}).items():
            if got[k] != v:
                row["pass"] = False
                row["fail"].append("warnings.%s %s != %s" % (k, got[k], v))
        ok = ok and row["pass"]
        results.append(row)

    out = os.path.join(HERE, "log_check.json")
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"pass": ok, "results": results}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"pass": ok, "checked": len(results),
                      "failures": [r["log"] + ": " + "; ".join(r["fail"]) for r in results if not r["pass"]]},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
