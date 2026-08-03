from __future__ import annotations

from io import BytesIO
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps


def load_image_array(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    return np.array(image.convert("RGB"))


def evaluate_label_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Lightweight image quality gate for label capture.

    The score is intentionally rule-based. It should warn operators to retake
    obviously bad images, not decide final inspection results.
    """
    rgb = load_image_array(image_bytes)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    glare_ratio = float(np.mean(gray > 245))
    dark_ratio = float(np.mean(gray < 35))

    warnings: list[str] = []
    if sharpness < 80:
        warnings.append("图片可能偏模糊，建议重新拍摄。")
    if brightness < 55:
        warnings.append("图片偏暗，建议增加照明后重拍。")
    if brightness > 220:
        warnings.append("图片整体过亮，建议降低曝光或调整角度。")
    if contrast < 28:
        warnings.append("文字与背景对比度偏低，可能影响OCR。")
    if glare_ratio > 0.18:
        warnings.append("疑似存在明显反光/过曝区域，建议调整角度重拍。")
    if dark_ratio > 0.35:
        warnings.append("暗部面积较大，建议补光。")

    if warnings:
        status = "WARN"
    else:
        status = "OK"

    score = 100
    if sharpness < 80:
        score -= 25
    if brightness < 55 or brightness > 220:
        score -= 20
    if contrast < 28:
        score -= 15
    if glare_ratio > 0.18:
        score -= 25
    if dark_ratio > 0.35:
        score -= 15

    return {
        "status": status,
        "score": max(score, 0),
        "warnings": warnings,
        "metrics": {
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
            "sharpness": round(sharpness, 2),
            "glare_ratio": round(glare_ratio, 4),
            "dark_ratio": round(dark_ratio, 4),
        },
    }
