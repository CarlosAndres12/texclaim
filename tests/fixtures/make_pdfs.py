"""Generate test PDFs at test time with fpdf2; no binary PDFs live in the repository."""

from __future__ import annotations

import datetime
import io

from fpdf import FPDF
from pypdf import PdfWriter

FIXED_DATE = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
MIN_DOWNLOAD_BYTES = 12_000  # downloads must exceed 10 KB (PLAN §7.4)


def _pad(data: bytes, size: int = MIN_DOWNLOAD_BYTES) -> bytes:
    return data + b"\n%" + b"x" * max(0, size - len(data)) + b"\n" if len(data) < size else data


def make_pdf(
    pages: list[str],
    *,
    first_label: int | None = None,
    pad: bool = True,
) -> bytes:
    """One page per string. `first_label` sets printed page labels (e.g. 1423, 1424, ...)."""
    pdf = FPDF()
    pdf.set_creation_date(FIXED_DATE)
    pdf.set_auto_page_break(False)
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, text)
    data = bytes(pdf.output())
    if first_label is not None:
        w = PdfWriter(clone_from=io.BytesIO(data))
        w.set_page_label(0, len(pages) - 1, "/D", start=first_label)
        buf = io.BytesIO()
        w.write(buf)
        data = buf.getvalue()
    return _pad(data) if pad else data


def make_scanned_pdf(n_pages: int = 2, pad: bool = True) -> bytes:
    """Image-only pages: no text layer."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(img).text((10, 10), "scanned page", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    pdf = FPDF()
    pdf.set_creation_date(FIXED_DATE)
    for _ in range(n_pages):
        pdf.add_page()
        pdf.image(io.BytesIO(buf.getvalue()), x=10, y=10, w=150)
    data = bytes(pdf.output())
    return _pad(data) if pad else data


def make_html_as_pdf() -> bytes:
    return b"<!DOCTYPE html><html><body>Please verify you are human</body></html>" + b" " * 12_000


def paper_pdf(title: str, author: str, body: list[str], **kw) -> bytes:
    """A PDF whose first page carries the title and author line, like a real paper."""
    first = f"{title}\n\n{author}\n\n{body[0] if body else ''}"
    return make_pdf([first, *body[1:]], **kw)
