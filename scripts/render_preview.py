#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a PPTX to PDF + per-slide PNG previews.

Order of preference:
  1. LibreOffice / soffice on PATH (also common install paths)
  2. WPS Presentation via COM on Windows
  3. give up honestly and report renderer=missing

PDF -> PNG uses PyMuPDF, so poppler is not required.

Usage:
  python render_preview.py deck.pptx --out previews [--dpi 110] [--json render.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys


def find_soffice():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice", "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.exists(p):
            return p
    return None


def convert_soffice(pptx, outdir):
    exe = find_soffice()
    if not exe:
        return None
    cmd = [exe, "--headless", "--norestore", "--convert-to", "pdf",
           "--outdir", outdir, pptx]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    if os.path.exists(pdf):
        return pdf
    return None


def convert_wps(pptx, outdir):
    """Windows-only fallback through WPS/PowerPoint COM.

    The file is staged under an ASCII temporary path first: COM/PowerShell
    argument passing mangles non-ASCII paths on some systems.
    """
    if os.name != "nt":
        return None
    import tempfile
    stage = tempfile.mkdtemp(prefix="deck_render_")
    src = os.path.join(stage, "deck.pptx")
    shutil.copyfile(pptx, src)
    pdf_stage = os.path.join(stage, "deck.pdf")
    ps = (
        "$ErrorActionPreference='Stop';"
        "$app=New-Object -ComObject Kwpp.Application;$app.Visible=$true;"
        "Start-Sleep -Seconds 2;"
        f"$p=$app.Presentations.Open('{src}');"
        f"$p.SaveAs('{pdf_stage}',32);$p.Close();$app.Quit();"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    if not os.path.exists(pdf_stage):
        return None
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(pptx))[0] + ".pdf")
    shutil.move(pdf_stage, pdf)
    return pdf


def pdf_to_png(pdf, outdir, dpi=110):
    import pymupdf as fitz
    doc = fitz.open(pdf)
    pages = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        name = f"slide-{i+1:02d}.png"
        path = os.path.join(outdir, name)
        pix.save(path)
        pages.append(name)
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx")
    ap.add_argument("--out", default="previews")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    pptx = os.path.abspath(args.pptx)
    pdf = convert_soffice(pptx, args.out)
    renderer = "libreoffice"
    if not pdf:
        pdf = convert_wps(pptx, args.out)
        renderer = "wps-com"
    if not pdf:
        result = {"status": "no_renderer", "renderer": None,
                  "reason": "LibreOffice/soffice not found and WPS COM unavailable",
                  "previews": []}
        print(json.dumps(result, ensure_ascii=False))
        if args.json:
            json.dump(result, open(args.json, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        return 3

    pages = pdf_to_png(pdf, args.out, args.dpi)
    result = {"status": "ok", "renderer": renderer, "pdf": pdf,
              "previews": pages, "out": args.out}
    print(json.dumps(result, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
