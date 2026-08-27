from __future__ import annotations

from io import BytesIO
from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np
from paddleocr import PaddleOCR
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from energy_label_parser import merge_energy_fields, parse_energy_label_fields
from field_extractor import extract_fields_from_text, summarize_fields


_ocr_engine: PaddleOCR | None = None
_last_ocr_init_seconds = 0.0
_last_recognize_timing: dict[str, float] = {}
_cached_build_paddle_ocr_engine = None

try:
    import streamlit as st
except Exception:
    st = None


def _build_paddle_ocr_engine() -> PaddleOCR:
    return PaddleOCR(
        lang="ch",
        device="cpu",
        enable_mkldnn=False,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
    )


def get_ocr_engine() -> PaddleOCR:
    """
    创建并缓存PaddleOCR引擎。

    引擎保留原项目的方向和文档矫正能力；实际 predict 时由
    recognize_image 决定是否启用，以避免真实大图无条件走慢流程。
    """
    global _ocr_engine, _last_ocr_init_seconds, _cached_build_paddle_ocr_engine
    if _ocr_engine is None:
        started = time.perf_counter()
        if _cached_build_paddle_ocr_engine is None:
            _cached_build_paddle_ocr_engine = (
                st.cache_resource(show_spinner=False)(_build_paddle_ocr_engine)
                if st is not None
                else _build_paddle_ocr_engine
            )
        _ocr_engine = _cached_build_paddle_ocr_engine()
        _last_ocr_init_seconds = time.perf_counter() - started
    else:
        _last_ocr_init_seconds = 0.0
    return _ocr_engine


def get_last_ocr_init_seconds() -> float:
    return _last_ocr_init_seconds


def get_last_recognize_timing() -> dict[str, float]:
    return dict(_last_recognize_timing)


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


def to_plain_points(value: Any) -> Any:
    try:
        if hasattr(value, "tolist"):
            value = value.tolist()
    except Exception:
        pass
    if isinstance(value, (list, tuple)):
        return [to_plain_points(item) for item in value]
    try:
        if isinstance(value, (np.integer, np.floating)):
            return float(value)
    except Exception:
        pass
    return value


def resize_for_ocr(image: Image.Image, max_side: int = 1600) -> Image.Image:
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
    max_side: int = 1600,
) -> list[dict[str, Any]]:
    """
    返回多个候选图像及处理信息。
    """
    original = image_bytes_to_pil(image_bytes)
    save_debug_image(original, debug_output_dir, "原图", file_stem)

    resized = resize_for_ocr(original, max_side=max_side)
    auto_resized = resized.size != original.size
    deskewed, skew_angle = deskew_image(resized)
    save_debug_image(deskewed, debug_output_dir, "旋转校正图", file_stem)

    full_gray, full_enhanced, _ = enhance_for_ocr(deskewed)
    save_debug_image(full_gray.convert("RGB"), debug_output_dir, "整图灰度图", file_stem)
    save_debug_image(full_enhanced, debug_output_dir, "整图增强图", file_stem)

    cropped, crop_note = crop_label_region(deskewed)
    cropped = resize_for_ocr(cropped, max_side=max_side)
    save_debug_image(cropped, debug_output_dir, "透视校正图", file_stem)

    gray, enhanced, binary = enhance_for_ocr(cropped)
    save_debug_image(gray.convert("RGB"), debug_output_dir, "灰度图", file_stem)
    save_debug_image(enhanced, debug_output_dir, "增强图", file_stem)
    save_debug_image(binary, debug_output_dir, "二值化图", file_stem)

    candidates: list[dict[str, Any]] = [
        {
            "name": "整图增强",
            "image": full_enhanced,
            "steps": [
                "整图增强候选，避免边框裁剪丢失字段",
                f"OCR自动压缩: {original.size[0]}x{original.size[1]} -> {resized.size[0]}x{resized.size[1]}"
                if auto_resized
                else "OCR未压缩: 图片尺寸未超过阈值",
            ],
            "preprocess_meta": {
                "original_size": original.size,
                "ocr_input_size": full_enhanced.size,
                "max_side": max_side,
                "auto_resized": auto_resized,
            },
        },
        {
            "name": "裁剪增强",
            "image": enhanced,
            "steps": [
                crop_note,
                f"倾斜角: {skew_angle:.2f}" if skew_angle is not None else "未检测到倾斜",
                f"OCR自动压缩: {original.size[0]}x{original.size[1]} -> {resized.size[0]}x{resized.size[1]}"
                if auto_resized
                else "OCR未压缩: 图片尺寸未超过阈值",
            ],
            "preprocess_meta": {
                "original_size": original.size,
                "ocr_input_size": enhanced.size,
                "max_side": max_side,
                "auto_resized": auto_resized,
            },
        }
    ]

    # 真实铭牌和多语言表格经常横向贴在竖拍照片中；在基础候选字段不足时再尝试。
    if cropped.height > cropped.width * 1.15:
        candidates.append(
            {
                "name": "裁剪增强_顺时针90",
                "image": enhanced.rotate(90, expand=True, fillcolor=(255, 255, 255)),
                "steps": ["竖图横排候选: 顺时针90度"],
                "preprocess_meta": candidates[0]["preprocess_meta"],
            }
        )
        candidates.append(
            {
                "name": "裁剪增强_逆时针90",
                "image": enhanced.rotate(270, expand=True, fillcolor=(255, 255, 255)),
                "steps": ["竖图横排候选: 逆时针90度"],
                "preprocess_meta": candidates[0]["preprocess_meta"],
            }
        )

    candidates.append(
        {
            "name": "二值化",
            "image": binary,
            "steps": ["自适应二值化候选"],
            "preprocess_meta": candidates[0]["preprocess_meta"],
        }
    )
    return candidates


def recognize_image(
    image: Image.Image,
    confidence_threshold: float = 0.30,
    fast_mode: bool = True,
) -> tuple[str, list[dict[str, Any]], float]:
    global _last_recognize_timing
    init_started = time.perf_counter()
    ocr_engine = get_ocr_engine()
    init_seconds = time.perf_counter() - init_started
    image_array = np.array(image.convert("RGB"))
    predict_started = time.perf_counter()
    results = ocr_engine.predict(
        input=image_array,
        use_doc_orientation_classify=not fast_mode,
        use_doc_unwarping=False if fast_mode else True,
        use_textline_orientation=False if fast_mode else True,
    )
    predict_seconds = time.perf_counter() - predict_started
    _last_recognize_timing = {
        "ocr_init_seconds": round(init_seconds, 4),
        "ocr_model_init_seconds": round(get_last_ocr_init_seconds(), 4),
        "ocr_predict_seconds": round(predict_seconds, 4),
    }

    all_texts: list[str] = []
    detail_rows: list[dict[str, Any]] = []
    scores: list[float] = []

    for result in results:
        result_data = get_result_data(get_result_dict(result))
        rec_texts = result_data.get("rec_texts") or []
        rec_scores = result_data.get("rec_scores") or []
        rec_boxes = result_data.get("rec_boxes") or []
        rec_polys = result_data.get("rec_polys") or result_data.get("dt_polys") or []
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
            box = to_plain_points(rec_boxes[index]) if index < len(rec_boxes) else None
            poly = to_plain_points(rec_polys[index]) if index < len(rec_polys) else None
            detail_rows.append(
                {
                    "序号": len(detail_rows) + 1,
                    "识别文字": clean_line,
                    "置信度": round(score, 4),
                    "位置框": box,
                    "文字多边形": poly,
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
    total_started = time.perf_counter()
    preprocess_started = time.perf_counter()
    candidates = preprocess_label_image(
        image_bytes,
        debug_output_dir=debug_output_dir,
        file_stem=file_stem,
    )
    preprocess_seconds = time.perf_counter() - preprocess_started
    warnings: list[str] = []
    best_result: dict[str, Any] | None = None
    ocr_init_seconds = 0.0
    ocr_predict_seconds = 0.0

    for candidate_index, candidate in enumerate(candidates):
        raw_text, rows, confidence = recognize_image(
            candidate["image"],
            confidence_threshold=confidence_threshold,
            fast_mode=True,
        )
        timing = get_last_recognize_timing()
        ocr_init_seconds += float(timing.get("ocr_model_init_seconds", 0.0) or 0.0)
        ocr_predict_seconds += float(timing.get("ocr_predict_seconds", 0.0) or 0.0)
        fields = extract_fields_from_text(raw_text)
        energy_fields, field_match_debug = parse_energy_label_fields(raw_text, rows)
        fields = merge_energy_fields(fields, energy_fields)
        score = score_candidate(raw_text, fields, confidence)
        result = {
            "raw_text": raw_text,
            "normalized_text": raw_text,
            "fields": fields,
            "field_match_debug": field_match_debug,
            "confidence": round(confidence, 4),
            "ocr_rows": rows,
            "selected_preprocess": candidate["name"],
            "preprocess_steps": candidate.get("steps", []),
            "preprocess_meta": candidate.get("preprocess_meta", {}),
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

    best_result["performance_trace"] = {
        "image_load_seconds": 0.0,
        "ocr_preprocess_seconds": round(preprocess_seconds, 4),
        "ocr_init_seconds": round(ocr_init_seconds, 4),
        "ocr_recognition_seconds": round(ocr_predict_seconds, 4),
        "ocr_total_seconds": round(time.perf_counter() - total_started, 4),
    }

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
