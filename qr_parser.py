from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlparse
import json
import re

import cv2
import numpy as np
from PIL import Image, ImageOps


def image_bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def decode_qr_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Decode QR content from a camera/uploaded image with OpenCV.

    Returns a rule-based result. It intentionally avoids cloud calls so the
    factory terminal can keep working on an intranet.
    """
    image = image_bytes_to_cv2(image_bytes)
    detector = cv2.QRCodeDetector()

    decoded_values: list[str] = []
    points_count = 0

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
        if ok and decoded_info:
            decoded_values = [value for value in decoded_info if value]
            points_count = 0 if points is None else len(points)
    except Exception:
        decoded_values = []

    if not decoded_values:
        value, points, _ = detector.detectAndDecode(image)
        if value:
            decoded_values = [value]
            points_count = 0 if points is None else 1

    return {
        "success": bool(decoded_values),
        "values": decoded_values,
        "text": decoded_values[0] if decoded_values else "",
        "parsed": parse_qr_content(decoded_values[0] if decoded_values else ""),
        "qr_count": points_count,
        "message": "二维码识别成功" if decoded_values else "未识别到二维码，请重拍或手动输入。",
    }


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_qr_text(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def parse_key_values(text: str) -> dict[str, str]:
    text = clean_text(text)
    if not text:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return {
                str(key).strip().lower(): clean_text(value)
                for key, value in payload.items()
                if clean_text(value)
            }
    except Exception:
        pass

    parsed_url = urlparse(text)
    if parsed_url.scheme in {"http", "https"} and parsed_url.query:
        query = parse_qs(parsed_url.query)
        return {
            str(key).strip().lower(): clean_text(values[0])
            for key, values in query.items()
            if values and clean_text(values[0])
        }

    pairs: dict[str, str] = {}
    for chunk in text.replace("|", ";").replace(",", ";").split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            continue
        key = clean_text(key).lower()
        value = clean_text(value)
        if key and value:
            pairs[key] = value
    return pairs


def parse_qr_content(raw_text: str, known_drawing_ids: set[str] | None = None, known_drawing_qrs: set[str] | None = None) -> dict[str, Any]:
    raw = clean_text(raw_text)
    normalized = normalize_qr_text(raw)
    fields = parse_key_values(raw)
    upper_keys = {key.upper() for key in fields}
    upper_raw = raw.upper()
    known_drawing_ids = known_drawing_ids or set()
    known_drawing_qrs = known_drawing_qrs or set()

    parsed_fields = {
        "product_id": first_field(fields, ("product_id", "pid", "product", "产品id", "产品编号")),
        "model": first_field(fields, ("model", "product_model", "型号", "产品型号")),
        "sn": first_field(fields, ("sn", "serial", "serial_no", "序列号")),
        "batch": first_field(fields, ("batch", "batch_no", "批次")),
        "drawing_id": first_field(fields, ("drawing_id", "drawing", "drw", "pdf", "图纸编号", "图号")),
        "url": raw if is_url(raw) else "",
    }

    if normalized and normalize_lookup(normalized) in {normalize_lookup(x) for x in known_drawing_ids | known_drawing_qrs}:
        return qr_result(raw, normalized, "drawing_qr", parsed_fields, 0.96, "二维码内容命中已有图纸ID或图纸二维码。")

    drawing_markers = {"DRAWING_ID", "DRAWING", "DRW", "PDF", "图纸编号", "图号"}
    if upper_keys.intersection(drawing_markers) or any(marker in upper_raw for marker in drawing_markers):
        return qr_result(raw, normalized, "drawing_qr", parsed_fields, 0.9, "二维码包含图纸标识字段。")

    product_markers = {"PRODUCT_ID", "PID", "MODEL", "SN", "BATCH", "PRODUCT_MODEL"}
    if upper_keys.intersection(product_markers):
        return qr_result(raw, normalized, "product_qr", parsed_fields, 0.9, "二维码包含产品字段。")

    if is_url(raw):
        return qr_result(raw, normalized, "label_url_qr", parsed_fields, 0.82, "二维码是URL，未命中已有产品或图纸绑定时按标签/平台链接处理。")

    return qr_result(raw, normalized, "unknown_qr", parsed_fields, 0.35 if raw else 0.0, "二维码内容无法稳定判断类型。")


def qr_result(raw: str, normalized: str, qr_type: str, parsed_fields: dict[str, str], confidence: float, reason: str) -> dict[str, Any]:
    return {
        "raw_text": raw,
        "normalized_text": normalized,
        "qr_type": qr_type,
        "parsed_fields": parsed_fields,
        "confidence": confidence,
        "reason": reason,
    }


def first_field(fields: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        if alias.lower() in fields:
            return clean_text(fields[alias.lower()])
    return ""


def is_url(text: str) -> bool:
    parsed = urlparse(clean_text(text))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def normalize_lookup(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_text(value).upper())
