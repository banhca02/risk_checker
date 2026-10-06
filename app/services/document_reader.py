from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import io

import pymupdf  
from PIL import Image


@dataclass
class PageText:
    page_number: int
    text: str
    source: str  # "embedded_text" or "ocr"


@dataclass
class ReadDocument:
    filename: str
    pages: list[PageText]

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"[PAGE {page.page_number}]\n{page.text}" for page in self.pages
        )


def _ocr_image(image: Image.Image) -> str:
    """
    Optional OCR fallback using pytesseract.
    Install the Tesseract executable separately on the machine, then:
      pip install pytesseract
    If Tesseract is unavailable, raise a clear error rather than silently returning
    empty text.
    """
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "This PDF page appears to be scanned. Install pytesseract and the "
            "Tesseract OCR engine, or use a vision model."
        ) from exc

    return pytesseract.image_to_string(image, lang="eng+vie")


def read_pdf(path: str | Path, min_embedded_chars: int = 30,
             use_ocr_fallback: bool = False) -> ReadDocument:
    """
    Read embedded text from each PDF page first.
    OCR is optional and only used for pages with very little embedded text.
    """
    path = Path(path)
    pages: list[PageText] = []

    with pymupdf.open(path) as pdf:
        for index, page in enumerate(pdf):
            text = page.get_text("text").strip()

            if len(text) >= min_embedded_chars:
                pages.append(PageText(index + 1, text, "embedded_text"))
                continue

            if not use_ocr_fallback:
                pages.append(PageText(index + 1, text, "embedded_text"))
                continue

            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_text = _ocr_image(image).strip()
            pages.append(PageText(index + 1, ocr_text, "ocr"))

    return ReadDocument(filename=path.name, pages=pages)


def read_text_file(path: str | Path) -> ReadDocument:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return ReadDocument(
        filename=path.name,
        pages=[PageText(page_number=1, text=text, source="embedded_text")]
    )


def read_document(path: str | Path, use_ocr_fallback: bool = False) -> ReadDocument:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path, use_ocr_fallback=use_ocr_fallback)
    if suffix in {".txt", ".md"}:
        return read_text_file(path)
    raise ValueError(f"Unsupported file type: {suffix}. Supported: PDF, TXT, MD.")
