from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from qr_parser import decode_qr_image


def render_pdf_page(page: Any, zoom: float = 2.0) -> Image.Image:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def detect_pdf_qr_codes(pdf_input: bytes | str | Path, max_pages: int = 3) -> dict[str, Any]:
    """
    Detect QR codes in the first pages of a PDF.

    This is intentionally a lightweight helper around the existing OpenCV QR
    decoder. It does not replace PDF text extraction or field parsing.
    """
    if isinstance(pdf_input, bytes):
        pdf_bytes = pdf_input
        filename = "uploaded.pdf"
    else:
        path = Path(pdf_input)
        pdf_bytes = path.read_bytes()
        filename = path.name

    values: list[str] = []
    page_results: list[dict[str, Any]] = []
    document = None
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_limit = min(document.page_count, max_pages)
        for page_index in range(page_limit):
            image = render_pdf_page(document[page_index], zoom=2.0)
            result = decode_qr_image(image_to_png_bytes(image))
            page_results.append(
                {
                    "page": page_index + 1,
                    "success": result["success"],
                    "values": result["values"],
                    "message": result["message"],
                }
            )
            for value in result["values"]:
                if value and value not in values:
                    values.append(value)
    finally:
        if document is not None:
            document.close()

    return {
        "filename": filename,
        "success": bool(values),
        "values": values,
        "text": values[0] if values else "",
        "pages_checked": len(page_results),
        "page_results": page_results,
        "message": "PDF二维码识别成功" if values else "PDF前几页未识别到二维码。",
    }
