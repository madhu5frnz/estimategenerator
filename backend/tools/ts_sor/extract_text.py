"""Extract page-marked text from a PDF (pdfplumber is only needed to rebuild the data)."""

from __future__ import annotations

import sys


def extract(pdf_path: str) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            parts.append(f"\n=====PAGE {number}/{total}=====\n")
            parts.append(page.extract_text() or "")
    return "".join(parts)


if __name__ == "__main__":
    sys.stdout.write(extract(sys.argv[1]))
