from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from dynamic_field_template import (
    build_dynamic_field_template,
    standard_fields_to_template,
    template_to_standard_fields,
)
from field_extractor import extract_fields_from_text, summarize_fields
from ocr_parser import recognize_image, save_debug_image


_drawing_cache: dict[str, dict[str, Any]] = {}


def read_pdf_bytes(pdf_input: bytes | str | Path) -> tuple[bytes, str]:
    if isinstance(pdf_input, bytes):
        return pdf_input, "uploaded.pdf"
    path = Path(pdf_input)
    return path.read_bytes(), path.name


def get_pdf_extraction_candidates(page) -> dict[str, str]:
    text_normal = page.get_text("text", sort=False).strip()
    text_sorted = page.get_text("text", sort=True).strip()
    blocks = page.get_text("blocks", sort=True)
    block_lines = [str(block[4]).strip() for block in blocks if len(block) >= 5 and str(block[4]).strip()]
    words = page.get_text("words", sort=True)
    word_lines = [str(word[4]).strip() for word in words if len(word) >= 5 and str(word[4]).strip()]
    return {
        "普通文本模式": text_normal,
        "坐标排序模式": text_sorted,
        "文字块模式": "\n".join(block_lines),
        "单词模式": "\n".join(word_lines),
    }


def score_text(text: str) -> tuple[int, int, int]:
    fields = summarize_fields(extract_fields_from_text(text))
    keyword_hits = sum(
        1
        for keyword in (
            "MODEL",
            "规格型号",
            "耗电量",
            "Rated",
            "Capacity",
            "编码",
            "能效",
            "铭牌",
        )
        if keyword.lower() in text.lower()
    )
    return len(fields), keyword_hits, len(text)


def extract_direct_pdf_text(document) -> str:
    page_results: list[str] = []
    for page_number, page in enumerate(document, start=1):
        candidates = get_pdf_extraction_candidates(page)
        selected_text = max(candidates.values(), key=score_text)
        page_results.append(f"===== 第 {page_number} 页 =====\n{selected_text}")
    return "\n\n".join(page_results)


def render_page_to_image(page, zoom: float = 2.0) -> Image.Image:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def resize_page_image(image: Image.Image, max_side: int = 1800) -> Image.Image:
    current_max = max(image.size)
    if current_max <= max_side:
        return image
    scale = max_side / current_max
    return image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))


def ocr_pdf_pages(
    document,
    debug_output_dir: str | Path | None = None,
    file_stem: str = "drawing",
) -> tuple[str, list[dict[str, Any]], float]:
    page_texts: list[str] = []
    ocr_rows: list[dict[str, Any]] = []
    confidences: list[float] = []

    for page_index, page in enumerate(document, start=1):
        image = resize_page_image(render_page_to_image(page), max_side=1800)
        save_debug_image(
            image,
            debug_output_dir,
            "PDF_OCR渲染图",
            f"{file_stem}_page_{page_index}",
        )
        text, rows, confidence = recognize_image(
            image,
            confidence_threshold=0.25,
            fast_mode=True,
        )
        page_texts.append(f"===== 第 {page_index} 页 OCR =====\n{text}")
        for row in rows:
            row = dict(row)
            row["页码"] = page_index
            ocr_rows.append(row)
        confidences.append(confidence)

    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n\n".join(page_texts), ocr_rows, average_confidence


def extract_drawing_content(
    pdf_input: bytes | str | Path,
    debug_output_dir: str | Path | None = None,
    file_stem: str = "drawing",
) -> dict[str, Any]:
    """
    解析PDF图纸。

    返回 raw_text、normalized_text、fields、parse_mode、warnings 和耗时。
    """
    pdf_bytes, filename = read_pdf_bytes(pdf_input)
    cache_key = hashlib.sha256(pdf_bytes).hexdigest()
    if cache_key in _drawing_cache:
        cached = dict(_drawing_cache[cache_key])
        cached["from_cache"] = True
        return cached

    started_at = time.perf_counter()
    warnings: list[str] = []
    document = None
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        direct_text = extract_direct_pdf_text(document)
        direct_fields = extract_fields_from_text(direct_text)
        direct_field_count = len(summarize_fields(direct_fields))
        direct_text_length = len(direct_text.strip())

        should_run_ocr = direct_text_length < 80 or direct_field_count < 4
        parse_mode = "text"
        raw_text = direct_text
        ocr_rows: list[dict[str, Any]] = []
        ocr_confidence = 0.0

        if should_run_ocr:
            reason = (
                "PDF文字层为空或有效字段过少，已启用PDF OCR模式。"
                if direct_text_length < 80
                else "PDF文字层存在但关键字段命中过少，已补充PDF OCR模式。"
            )
            warnings.append(reason)
            try:
                ocr_text, ocr_rows, ocr_confidence = ocr_pdf_pages(
                    document,
                    debug_output_dir=debug_output_dir,
                    file_stem=file_stem,
                )
                ocr_fields = extract_fields_from_text(ocr_text)
                if len(summarize_fields(ocr_fields)) >= direct_field_count:
                    raw_text = ocr_text
                    parse_mode = "ocr"
            except Exception as error:
                warnings.append(f"PDF OCR失败，保留文字层结果：{error}")

        fields = extract_fields_from_text(raw_text)
        summarized_fields = summarize_fields(fields)
        field_template = build_dynamic_field_template(raw_text, ocr_rows)
        dynamic_fields = template_to_standard_fields(field_template)
        if len(dynamic_fields) >= 4 or len(dynamic_fields) >= len(summarized_fields):
            fields = dynamic_fields
        elif summarized_fields:
            field_template = standard_fields_to_template(summarized_fields)
            fields = summarized_fields
        result = {
            "filename": filename,
            "raw_text": raw_text,
            "normalized_text": raw_text,
            "fields": fields,
            "field_template": field_template,
            "parse_mode": parse_mode,
            "warnings": warnings,
            "page_count": document.page_count,
            "ocr_rows": ocr_rows,
            "confidence": round(ocr_confidence, 4),
            "timings": {
                "pdf_parse_seconds": round(time.perf_counter() - started_at, 3),
            },
            "from_cache": False,
        }
        _drawing_cache[cache_key] = dict(result)
        return result
    except Exception as error:
        raise RuntimeError(f"PDF解析失败：{error}") from error
    finally:
        if document is not None:
            document.close()


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    result = extract_drawing_content(pdf_bytes)
    return result["raw_text"], int(result["page_count"])


def extract_fields_from_pdf_text(pdf_text: str) -> dict[str, str]:
    return extract_fields_from_text(pdf_text)


def debug_pdf_extraction(pdf_bytes: bytes) -> dict[str, str]:
    document = None
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        if document.page_count == 0:
            return {
                "普通文本模式": "",
                "坐标排序模式": "",
                "文字块模式": "",
                "单词模式": "",
            }
        return get_pdf_extraction_candidates(document[0])
    except Exception as error:
        return {"诊断失败": str(error)}
    finally:
        if document is not None:
            document.close()


def score_pdf_extraction_modes(debug_results: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode_name, mode_text in debug_results.items():
        fields = summarize_fields(extract_fields_from_text(mode_text))
        rows.append(
            {
                "提取模式": mode_name,
                "字段命中数量": len(fields),
                "命中字段": "、".join(fields),
                "文字长度": len(mode_text),
            }
        )
    return sorted(rows, key=lambda row: (row["字段命中数量"], row["文字长度"]), reverse=True)
