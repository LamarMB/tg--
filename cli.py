"""Командная строка.

  python cli.py данные.xlsx               -> данные.pdf рядом
  python cli.py данные.xlsx -o out.pdf
  python cli.py --template шаблон.xlsx     -> пустой шаблон для заполнения
"""
import argparse
import sys
from pathlib import Path

from schemgen import TemplateError, read_document, render_pdf, write_workbook


def main() -> int:
    ap = argparse.ArgumentParser(description="Excel -> PDF комплект документации")
    ap.add_argument("xlsx", nargs="?", help="заполненный Excel-шаблон")
    ap.add_argument("-o", "--out", help="куда сохранить PDF")
    ap.add_argument("--template", metavar="PATH", help="создать пустой шаблон")
    a = ap.parse_args()
    if a.template:
        write_workbook(a.template)
        print(f"Шаблон сохранён: {a.template}")
        return 0
    if not a.xlsx:
        ap.print_help()
        return 1
    out = a.out or str(Path(a.xlsx).with_suffix(".pdf"))
    try:
        doc = read_document(a.xlsx)
    except TemplateError as e:
        print("Ошибки в файле:\n- " + "\n- ".join(e.problems), file=sys.stderr)
        return 2
    n = render_pdf(doc, out)
    print(f"Готово: {out} ({n} листов)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
