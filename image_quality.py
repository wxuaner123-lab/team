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
    image_height, image_width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    overexposure_score = float(np.mean(gray > 245))
    dark_ratio = float(np.mean(gray < 35))
    label_area_score = estimate_label_area_score(gray)

    blur_status, blur_message = status_from_thresholds(
        blur_score,
        fail_limit=45,
        warning_limit=95,
        higher_is_better=True,
        pass_message="图片清晰度满足识别要求。",
        warning_message="图片略模糊，建议保持设备稳定后拍摄。",
        fail_message="图片明显模糊，建议重新拍摄。",
    )
    brightness_status, brightness_message = brightness_status_message(brightness, dark_ratio)
    overexposure_status, overexposure_message = overexposure_status_message(overexposure_score, brightness)
    resolution_status, resolution_message = resolution_status_message(image_width, image_height)
    label_area_status, label_area_message = label_area_status_message(label_area_score)

    quality_messages = [
        message
        for status, message in (
            (blur_status, blur_message),
            (brightness_status, brightness_message),
            (overexposure_status, overexposure_message),
            (resolution_status, resolution_message),
            (label_area_status, label_area_message),
        )
        if status != "PASS"
    ]

    statuses = [blur_status, brightness_status, overexposure_status, resolution_status, label_area_status]
    if "FAIL" in statuses:
        quality_status = "FAIL"
    elif "WARNING" in statuses:
        quality_status = "WARNING"
    else:
        quality_status = "PASS"

    quality_score = 100
    quality_score -= penalty_for_status(blur_status, warning=12, fail=35)
    quality_score -= penalty_for_status(brightness_status, warning=10, fail=30)
    quality_score -= penalty_for_status(overexposure_status, warning=10, fail=28)
    quality_score -= penalty_for_status(resolution_status, warning=8, fail=25)
    quality_score -= penalty_for_status(label_area_status, warning=8, fail=18)
    if contrast < 28:
        quality_score -= 8
        quality_messages.append("文字与背景对比度偏低，可能影响识别。")

    return {
        "quality_status": quality_status,
        "quality_score": max(int(round(quality_score)), 0),
        "quality_messages": quality_messages,
        "status": quality_status,
        "score": max(int(round(quality_score)), 0),
        "warnings": quality_messages,
        "blur_score": round(blur_score, 2),
        "blur_status": blur_status,
        "blur_message": blur_message,
        "brightness_score": round(brightness, 2),
        "brightness_status": brightness_status,
        "brightness_message": brightness_message,
        "overexposure_score": round(overexposure_score, 4),
        "overexposure_status": overexposure_status,
        "overexposure_message": overexposure_message,
        "image_width": int(image_width),
        "image_height": int(image_height),
        "resolution_status": resolution_status,
        "resolution_message": resolution_message,
        "label_area_score": round(label_area_score, 4),
        "label_area_status": label_area_status,
        "label_area_message": label_area_message,
        "metrics": {
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
            "sharpness": round(blur_score, 2),
            "glare_ratio": round(overexposure_score, 4),
            "dark_ratio": round(dark_ratio, 4),
        },
    }


def estimate_label_area_score(gray: np.ndarray) -> float:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = np.ones((9, 9), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(gray.shape[0] * gray.shape[1])
    if image_area <= 0 or not contours:
        return 0.0
    largest_area = max(cv2.contourArea(contour) for contour in contours)
    return float(largest_area / image_area)


def status_from_thresholds(
    value: float,
    fail_limit: float,
    warning_limit: float,
    higher_is_better: bool,
    pass_message: str,
    warning_message: str,
    fail_message: str,
) -> tuple[str, str]:
    if higher_is_better:
        if value < fail_limit:
            return "FAIL", fail_message
        if value < warning_limit:
            return "WARNING", warning_message
        return "PASS", pass_message
    if value > fail_limit:
        return "FAIL", fail_message
    if value > warning_limit:
        return "WARNING", warning_message
    return "PASS", pass_message


def brightness_status_message(brightness: float, dark_ratio: float) -> tuple[str, str]:
    if brightness < 38 or dark_ratio > 0.48:
        return "FAIL", "图片过暗，请补光后重新拍摄。"
    if brightness < 60 or dark_ratio > 0.34:
        return "WARNING", "图片偏暗，建议增加照明后拍摄。"
    if brightness > 235:
        return "FAIL", "图片整体过亮，请降低曝光或避开强光。"
    if brightness > 215:
        return "WARNING", "图片偏亮，请注意避免反光。"
    return "PASS", "图片亮度满足识别要求。"


def overexposure_status_message(overexposure_ratio: float, brightness: float) -> tuple[str, str]:
    if overexposure_ratio > 0.28 or (overexposure_ratio > 0.18 and brightness > 210):
        return "FAIL", "图片存在明显反光或过曝区域，建议调整角度后重拍。"
    if overexposure_ratio > 0.12:
        return "WARNING", "图片存在反光/过曝风险，建议调整角度。"
    return "PASS", "未发现明显反光或过曝风险。"


def resolution_status_message(width: int, height: int) -> tuple[str, str]:
    short_edge = min(width, height)
    long_edge = max(width, height)
    if short_edge < 480 or long_edge < 800:
        return "FAIL", "图片分辨率过低，请靠近标签重新拍摄。"
    if short_edge < 720 or long_edge < 1080:
        return "WARNING", "图片分辨率偏低，建议靠近标签拍摄。"
    return "PASS", "图片分辨率满足识别要求。"


def label_area_status_message(label_area_score: float) -> tuple[str, str]:
    if label_area_score < 0.05:
        return "WARNING", "标签区域占比较小或无法稳定判断，请靠近并保持标签完整入镜。"
    if label_area_score < 0.12:
        return "WARNING", "标签可能占比偏小，建议靠近拍摄。"
    return "PASS", "标签主体区域占比较合理。"


def penalty_for_status(status: str, warning: int, fail: int) -> int:
    if status == "FAIL":
        return fail
    if status == "WARNING":
        return warning
    return 0
