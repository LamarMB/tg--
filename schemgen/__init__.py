"""Генератор комплекта документации на шкаф управления (PDF по ГОСТ)."""
from .document import render_pdf
from .excel_io import TemplateError, read_document, write_workbook

__all__ = ["render_pdf", "read_document", "write_workbook", "TemplateError"]
