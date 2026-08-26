from __future__ import annotations

import re
from typing import Any

from field_config import FIELD_CONFIG, FIELD_NAMES, clean_text, normalize_value
from field_extractor import extract_fields_from_text


FIELD_ALIASES = {
    field_name: list(rule.aliases)
    for field_name, rule in FIELD_CONFIG.items()
}

FIELD_KEY_COMPARE_ALIASES = {
    "model_number": "规格型号",
    "energy_class": "能效等级",
    "annual_energy_consumption": "年耗电量",
    "annual_water_consumption": "年耗水量",
    "capacity": "额定容量",
    "made_in": "制造地",
    "brand_name": "品牌",
    "manufacturer_name": "生产者名称",
    "standard_reference_no": "依据国家标准",
    "registration_no": "注册号",
    "cleaning_ratio": "洗净比",
    "wash_spin_capacity": "洗涤/脱水容量",
    "wash_capacity": "洗涤容量",
    "spin_capacity": "脱水容量",
    "drawing_code": "编码",
    "label_code": "编码",
    "label_name": "标签名称",
}

UNIT_OPTIONAL_FIELDS = {"年耗电量", "年耗水量", "容量", "额定容量", "annual_energy_consumption", "annual_water_consumption", "capacity", "wash_capacity", "spin_capacity", "wash_spin_capacity"}
CODE_LIKE_FIELDS = {"产品型号", "规格型号", "型号", "model_number", "standard_reference_no", "registration_no", "版本号", "序列号"}
UNIT_NORMALIZATION = (
    (r"千瓦时|ＫＷＨ|KWH/YEAR|KWH", "KWH"),
    (r"LITERS?|LITRES?|升", "L"),
    (r"千克|公斤|KGS?|KG", "KG"),
)


def compare_rule_name(field_name: str) -> str:
    return FIELD_KEY_COMPARE_ALIASES.get(field_name, field_name)


def extract_fields_from_label_text(label_text: str) -> dict[str, str]:
    """
    从标签OCR文字中提取结构化字段。

    保持旧函数名，内部改用统一字段配置和真实样本扩展规则。
    """
    return extract_fields_from_text(label_text)


def normalize_compare_value(
    value: str,
    field_name: str = "",
) -> str:
    """
    兼容旧调用的比对值标准化函数。
    """
    return normalize_value(field_name, value)


def canonical_compare_value(field_name: str, value: Any) -> str:
    text = normalize_value(compare_rule_name(field_name), value)
    if not text:
        return ""
    for pattern, replacement in UNIT_NORMALIZATION:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    text = text.replace(":", "").replace("：", "")
    text = re.sub(r"[\s_\-]+", "", text.upper())
    if field_name in CODE_LIKE_FIELDS or compare_rule_name(field_name) in CODE_LIKE_FIELDS:
        text = text.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))
    return text


def number_unit_pair(field_name: str, value: Any) -> tuple[str, str]:
    canonical = canonical_compare_value(field_name, value)
    number = first_number(canonical)
    unit = ""
    for candidate in ("KWH", "KG", "L"):
        if candidate in canonical:
            unit = candidate
            break
    return number, unit


def iter_comparison_fields(
    drawing_fields: dict[str, Any],
    label_fields: dict[str, Any],
) -> list[str]:
    field_names = [
        field_name
        for field_name in FIELD_NAMES
        if clean_text(drawing_fields.get(field_name, ""))
        or clean_text(label_fields.get(field_name, ""))
    ]
    seen = set(field_names)
    for source in (drawing_fields, label_fields):
        for field_name, value in source.items():
            clean_name = clean_text(field_name)
            if clean_name and clean_name not in seen and clean_text(value):
                field_names.append(clean_name)
                seen.add(clean_name)

    return field_names


def compare_single_field(
    field_name: str,
    drawing_value: str,
    label_value: str,
    label_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rule_name = compare_rule_name(field_name)
    rule = FIELD_CONFIG.get(rule_name)
    drawing_normalized = normalize_value(
        rule_name,
        drawing_value,
    )
    label_normalized = normalize_value(
        rule_name,
        label_value,
    )
    drawing_canonical = canonical_compare_value(field_name, drawing_value)
    label_canonical = canonical_compare_value(field_name, label_value)
    drawing_number = first_number(drawing_normalized)
    label_number = first_number(label_normalized)
    drawing_number_unit = number_unit_pair(field_name, drawing_value)
    label_number_unit = number_unit_pair(field_name, label_value)
    raw_candidate_values = (label_debug or {}).get("strong_candidate_values") or (label_debug or {}).get("candidate_values", [])
    candidate_values = [
        clean_text(value)
        for value in raw_candidate_values
        if clean_text(value)
    ]
    candidate_normalized_values = {
        normalize_value(rule_name, value)
        for value in candidate_values
    }
    candidate_canonical_values = {
        canonical_compare_value(field_name, value)
        for value in candidate_values
    }
    field_confidence = float((label_debug or {}).get("confidence", 0) or 0)
    has_candidate_conflict = bool((label_debug or {}).get("needs_review")) or len(
        set(candidate_canonical_values or candidate_normalized_values)
    ) > 1
    numeric_compare_allowed = (
        field_name in UNIT_OPTIONAL_FIELDS
        or rule_name in UNIT_OPTIONAL_FIELDS
        or bool(rule and rule.compare_type in {"unit", "number"})
    )
    values_match = (
        drawing_normalized == label_normalized
        or drawing_canonical == label_canonical
        or (
            numeric_compare_allowed
            and drawing_number
            and label_number
            and drawing_number == label_number
        )
        or (
            numeric_compare_allowed
            and
            drawing_number_unit[0]
            and label_number_unit[0]
            and drawing_number_unit[0] == label_number_unit[0]
            and (not drawing_number_unit[1] or not label_number_unit[1] or drawing_number_unit[1] == label_number_unit[1])
        )
    )

    if not drawing_value and not label_value:
        status = "not_applicable"
        result = "NEED_REVIEW"
        reason = "图纸和标签均未识别到该字段。"
        confidence = 0.0
    elif not drawing_value:
        status = "drawing_missing"
        result = "NEED_REVIEW"
        reason = "图纸字段未识别，无法判断标签是否一致。"
        confidence = 0.0
    elif not label_value:
        status = "label_missing"
        result = "NEED_REVIEW"
        reason = clean_text((label_debug or {}).get("select_reason", "")) or "标签字段缺失或OCR未定位，需要人工确认。"
        confidence = 0.0
    elif values_match:
        if 0 < field_confidence < 0.45:
            status = "match_need_review"
            result = "NEED_REVIEW"
            reason = "识别值与图纸一致，但字段定位置信度偏低，需要人工确认。"
            confidence = max(field_confidence, 0.50)
        else:
            status = "match"
            result = "PASS"
            reason = "图纸标准值与标签识别值标准化后一致。"
            if drawing_canonical == label_canonical and drawing_normalized != label_normalized:
                reason = "大小写、空格、冒号或单位写法差异已归一化，标准值一致。"
            elif drawing_normalized != label_normalized:
                reason = "数值一致，单位写法差异或标签单位缺失但字段锚点明确。"
            if has_candidate_conflict:
                reason += " OCR存在其他候选值，已保留在调试信息中。"
            confidence = max(field_confidence, 0.98)
    else:
        if drawing_normalized in candidate_normalized_values or drawing_canonical in candidate_canonical_values:
            status = "candidate_conflict"
            result = "NEED_REVIEW"
            reason = "最终选择值与图纸不一致，但OCR候选值中存在图纸标准值，疑似字段错位，需要人工确认。"
            confidence = max(field_confidence, 0.55)
        elif has_candidate_conflict or 0 < field_confidence < 0.55:
            status = "low_confidence_mismatch"
            result = "NEED_REVIEW"
            reason = "识别值与图纸不一致，但字段定位存在冲突或置信度不足，暂不判定产品失败。"
            confidence = max(field_confidence, 0.4)
        else:
            status = "mismatch"
            result = "FAIL"
            reason = "图纸标准值与标签识别值明确不一致。"
            confidence = max(field_confidence, 0.95)

    return {
        "字段名称": field_name,
        "图纸值": drawing_value,
        "标签值": label_value,
        "图纸原始值": drawing_value,
        "图纸标准化值": drawing_normalized,
        "图纸比对归一值": drawing_canonical,
        "标签原始值": label_value,
        "标签标准化值": label_normalized,
        "标签比对归一值": label_canonical,
        "字段状态": status,
        "检测结果": result,
        "异常说明": reason,
        "是否必填": "是" if rule and rule.required else "否",
        "置信度": round(confidence, 4),
        "OCR候选值": " / ".join(candidate_values),
        "字段匹配说明": clean_text((label_debug or {}).get("select_reason", "")),
    }


def first_number(value: str) -> str:
    import re

    match = re.search(r"[0-9]+(?:\.[0-9]+)?", value)
    return match.group(0) if match else ""


def compare_fields(
    drawing_fields: dict[str, Any],
    label_fields: dict[str, Any],
    label_debug: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    对图纸字段和标签字段逐项比较。

    返回：
    - comparison_rows：逐字段结构化结果，兼容旧Excel列名。
    - overall_result：PASS、FAIL或待人工确认。
    """
    comparison_rows: list[dict[str, Any]] = []

    for field_name in iter_comparison_fields(
        drawing_fields,
        label_fields,
    ):
        drawing_value = clean_text(
            drawing_fields.get(
                field_name,
                "",
            )
        )
        label_value = clean_text(
            label_fields.get(
                field_name,
                "",
            )
        )
        comparison_rows.append(
            compare_single_field(
                field_name,
                drawing_value,
                label_value,
                (label_debug or {}).get(field_name, {}),
            )
        )

    if any(row["检测结果"] == "FAIL" for row in comparison_rows):
        overall_result = "FAIL"
    elif any(row["检测结果"] == "NEED_REVIEW" for row in comparison_rows):
        overall_result = "NEED_REVIEW"
    else:
        overall_result = "PASS"

    return comparison_rows, overall_result
