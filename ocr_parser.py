from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from paddleocr import PaddleOCR
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from field_extractor import extract_fields_from_text, summarize_fields


_ocr_engine: PaddleOCR | None = None


def get_ocr_engine() -> PaddleOCR:
    """
    创建并缓存PaddleOCR引擎。

    引擎保留原项目的方向和文档矫正能力；实际 predict 时由
    recognize_image 决定是否启用，以避免真实大图无条件走慢流程。
    """
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(
            lang="ch",
            device="cpu",
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
        )
    return _ocr_engine


def image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")
    except Exception as error:
        raise RuntimeError(f"标签图片读取失败：{error}") from error


def image_bytes_to_numpy(image_bytes: bytes) -> np.ndarray:
    return np.array(image_bytes_to_pil(image_bytes))


def get_result_dict(result: Any) -> dict:
    result_json = getattr(result, "json", None)
    if callable(result_json):
        try:
            result_json = result_json()
        except Exception:
            result_json = None
    if isinstance(result_json, dict):
        return result_json
    try:
        converted_result = dict(result)
        if isinstance(converted_result, dict):
            return converted_result
    except Exception:
        pass
    return {}


def get_result_data(result_dict: dict) -> dict:
    result_data = result_dict.get("res", result_dict)
    return result_data if isinstance(result_data, dict) else {}


def resize_for_ocr(image: Image.Image, max_side: int = 1800) -> Image.Image:
    width, height = image.size
    current_max = max(width, height)
    if current_max <= max_side:
        return image
    scale = max_side / current_max
    return image.resize((max(1, int(width * scale)), max(1, int(height * scale))))


def save_debug_image(
    image: Image.Image,
    debug_output_dir: str | Path | None,
    stage_name: str,
    file_stem: str,
) -> None:
    if debug_output_dir is None:
        return
    stage_dir = Path(debug_output_dir) / stage_name
    stage_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in file_stem)
    image.save(stage_dir / f"{safe_stem}.png")


def estimate_skew_degrees(image: Image.Image) -> float | None:
    gray = np.array(image.convert("L"))
    try:
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=120,
            minLineLength=max(80, min(gray.shape[:2]) // 6),
            maxLineGap=20,
        )
        if lines is None:
            return None
        angles: list[float] = []
        for line in lines[:, 0, :]:
            x1, y1, x2, y2 = line
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0:
                continue
            angle = float(np.degrees(np.arctan2(dy, dx)))
            while angle <= -45:
                angle += 90
            while angle > 45:
                angle -= 90
            if abs(angle) <= 12:
                angles.append(angle)
        if not angles:
            return None
        return float(np.median(angles))
    except Exception:
        return None


def deskew_image(image: Image.Image) -> tuple[Image.Image, float | None]:
    angle = estimate_skew_degrees(image)
    if angle is None or abs(angle) < 2.0:
        return image, angle
    return image.rotate(angle * -1, expand=True, fillcolor=(255, 255, 255)), angle


def crop_label_region(image: Image.Image) -> tuple[Image.Image, str]:
    """
    尝试用最大外接轮廓裁剪标签/纸张区域。失败时返回原图。
    """
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image, "未检测到稳定边框，使用整图"

    image_area = arr.shape[0] * arr.shape[1]
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.05 or area > image_area * 0.98:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 120 or h < 120:
            continue
        candidates.append((area, x, y, w, h))

    if not candidates:
        return image, "未找到足够大的标签区域，使用整图"

    _, x, y, w, h = max(candidates, key=lambda item: item[0])
    pad = int(max(w, h) * 0.03)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(arr.shape[1], x + w + pad)
    y2 = min(arr.shape[0], y + h + pad)
    cropped = image.crop((x1, y1, x2, y2))
    return cropped, "最大外接轮廓裁剪"


def enhance_for_ocr(image: Image.Image) -> tuple[Image.Image, Image.Image, Image.Image]:
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    enhanced = ImageEnhance.Contrast(gray).enhance(1.8)
    enhanced = enhanced.filter(ImageFilter.SHARPEN)
    gray_arr = np.array(enhanced)
    binary_arr = cv2.adaptiveThreshold(
        gray_arr,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        11,
    )
    binary = Image.fromarray(binary_arr)
    return gray, enhanced.convert("RGB"), binary.convert("RGB")


def preprocess_label_image(
    image_bytes: bytes,
    debug_output_dir: str | Path | None = None,
    file_stem: str = "label",
    max_side: int = 1800,
) -> list[dict[str, Any]]:
    """
    返回多个候选图像及处理信息。
    """
    original = image_bytes_to_pil(image_bytes)
    save_debug_image(original, debug_output_dir, "原图", file_stem)

    resized = resize_for_ocr(original, max_side=max_side)
    deskewed, skew_angle = deskew_image(resized)
    save_debug_image(deskewed, debug_output_dir, "旋转校正图", file_stem)

    cropped, crop_note = crop_label_region(deskewed)
    cropped = resize_for_ocr(cropped, max_side=max_side)
    save_debug_image(cropped, debug_output_dir, "透视校正图", file_stem)

    gray, enhanced, binary = enhance_for_ocr(cropped)
    save_debug_image(gray.convert("RGB"), debug_output_dir, "灰度图", file_stem)
    save_debug_image(enhanced, debug_output_dir, "增强图", file_stem)
    save_debug_image(binary, debug_output_dir, "二值化图", file_stem)

    candidates: list[dict[str, Any]] = [
        {
            "name": "裁剪增强",
            "image": enhanced,
            "steps": [crop_note, f"倾斜角: {skew_angle:.2f}" if skew_angle is not None else "未检测到倾斜"],
        }
    ]

    # 真实铭牌和多语言表格经常横向贴在竖拍照片中；在基础候选字段不足时再尝试。
    if cropped.height > cropped.width * 1.15:
        candidates.append(
            {
                "name": "裁剪增强_顺时针90",
                "image": enhanced.rotate(90, expand=True, fillcolor=(255, 255, 255)),
                "steps": ["竖图横排候选: 顺时针90度"],
            }
        )
        candidates.append(
            {
                "name": "裁剪增强_逆时针90",
                "image": enhanced.rotate(270, expand=True, fillcolor=(255, 255, 255)),
                "steps": ["竖图横排候选: 逆时针90度"],
            }
        )

    candidates.append(
        {
            "name": "二值化",
            "image": binary,
            "steps": ["自适应二值化候选"],
        }
    )
    return candidates


def recognize_image(
    image: Image.Image,
    confidence_threshold: float = 0.30,
    fast_mode: bool = True,
) -> tuple[str, list[dict[str, Any]], float]:
    image_array = np.array(image.convert("RGB"))
    ocr_engine = get_ocr_engine()
    results = ocr_engine.predict(
        input=image_array,
        use_doc_orientation_classify=not fast_mode,
        use_doc_unwarping=False if fast_mode else True,
        use_textline_orientation=False if fast_mode else True,
    )

    all_texts: list[str] = []
    detail_rows: list[dict[str, Any]] = []
    scores: list[float] = []

    for result in results:
        result_data = get_result_data(get_result_dict(result))
        rec_texts = result_data.get("rec_texts") or []
        rec_scores = result_data.get("rec_scores") or []
        for index, text in enumerate(rec_texts):
            clean_line = str(text).strip()
            if not clean_line:
                continue
            try:
                score = float(rec_scores[index]) if index < len(rec_scores) else 0.0
            except Exception:
                score = 0.0
            if score < confidence_threshold:
                continue
            all_texts.append(clean_line)
            scores.append(score)
            detail_rows.append(
                {
                    "序号": len(detail_rows) + 1,
                    "识别文字": clean_line,
                    "置信度": round(score, 4),
                }
            )

    average_confidence = float(sum(scores) / len(scores)) if scores else 0.0
    return "\n".join(all_texts), detail_rows, average_confidence


def score_candidate(raw_text: str, fields: dict[str, str], confidence: float) -> float:
    non_empty_fields = len(summarize_fields(fields))
    keyword_hits = sum(
        1
        for keyword in (
            "MODEL",
            "规格型号",
            "耗电量",
            "Rated",
            "Capacity",
            "Multilingual",
            "能效",
            "铭牌",
        )
        if keyword.lower() in raw_text.lower()
    )
    return non_empty_fields * 20 + keyword_hits * 4 + confidence * 10 + min(len(raw_text), 2000) / 1000


def recognize_label(
    image_bytes: bytes,
    confidence_threshold: float = 0.30,
    debug_output_dir: str | Path | None = None,
    file_stem: str = "label",
) -> dict[str, Any]:
    """
    识别标签图片并返回结构化结果。
    """
    candidates = preprocess_label_image(
        image_bytes,
        debug_output_dir=debug_output_dir,
        file_stem=file_stem,
    )
    warnings: list[str] = []
    best_result: dict[str, Any] | None = None

    for candidate_index, candidate in enumerate(candidates):
        raw_text, rows, confidence = recognize_image(
            candidate["image"],
            confidence_threshold=confidence_threshold,
            fast_mode=True,
        )
        fields = extract_fields_from_text(raw_text)
        score = score_candidate(raw_text, fields, confidence)
        result = {
            "raw_text": raw_text,
            "normalized_text": raw_text,
            "fields": fields,
            "confidence": round(confidence, 4),
            "ocr_rows": rows,
            "selected_preprocess": candidate["name"],
            "preprocess_steps": candidate.get("steps", []),
            "warnings": list(warnings),
            "score": round(score, 4),
        }

        if best_result is None or score > best_result["score"]:
            best_result = result

        # Stop early when the first cheap pass is already useful.
        if candidate_index == 0 and len(summarize_fields(fields)) >= 4:
            break

    if best_result is None:
        raise RuntimeError("标签OCR未返回任何候选结果。")

    if len(summarize_fields(best_result["fields"])) == 0:
        best_result["warnings"].append("OCR未提取到可比较字段，需要人工确认。")
    if best_result["confidence"] < 0.65:
        best_result["warnings"].append("OCR平均置信度偏低。")

    return best_result


def extract_label_text(
    image_bytes: bytes,
    confidence_threshold: float = 0.50,
) -> tuple[str, list[dict[str, Any]]]:
    """
    兼容旧页面：返回OCR原始文字和明细。
    """
    try:
        result = recognize_label(
            image_bytes,
            confidence_threshold=confidence_threshold,
        )
        rows = result["ocr_rows"]
        for row in rows:
            row.setdefault("预处理方式", result["selected_preprocess"])
        return result["raw_text"], rows
    except Exception as error:
        raise RuntimeError(f"标签OCR识别失败：{error}") from error
