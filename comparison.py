from __future__ import annotations

from typing import Any

from field_config import FIELD_CONFIG, FIELD_NAMES, clean_text, normalize_value
from field_extractor import extract_fields_from_text


FIELD_ALIASES = {
    field_name: list(rule.aliases)
    for field_name, rule in FIELD_CONFIG.items()
}


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

    # 保底输出原MVP六字段，避免页面/报告没有任何列可看。
    if not field_names:
        return FIELD_NAMES[:6]

    return field_names


def compare_single_field(
    field_name: str,
    drawing_value: str,
    label_value: str,
) -> dict[str, Any]:
    rule = FIELD_CONFIG.get(field_name)
    drawing_normalized = normalize_value(
        field_name,
        drawing_value,
    )
    label_normalized = normalize_value(
        field_name,
        label_value,
    )

    if not drawing_value and not label_value:
        status = "not_applicable"
        result = "无法判断"
        reason = "图纸和标签均未识别到该字段。"
        confidence = 0.0
    elif not drawing_value:
        status = "drawing_missing"
        result = "无法判断"
        reason = "图纸字段未识别，无法判断标签是否一致。"
        confidence = 0.0
    elif not label_value:
        status = "label_missing"
        result = "无法判断"
        reason = "标签字段缺失或OCR未识别，需要人工确认。"
        confidence = 0.0
    elif drawing_normalized == label_normalized:
        status = "match"
        result = "PASS"
        reason = "标准化后完全一致。"
        confidence = 0.98
    else:
        status = "mismatch"
        result = "FAIL"
        reason = "标准化后仍不一致。"
        confidence = 0.95

    return {
        "字段名称": field_name,
        "图纸值": drawing_value,
        "标签值": label_value,
        "图纸原始值": drawing_value,
        "图纸标准化值": drawing_normalized,
        "标签原始值": label_value,
        "标签标准化值": label_normalized,
        "字段状态": status,
        "检测结果": result,
        "异常说明": reason,
        "是否必填": "是" if rule and rule.required else "否",
        "置信度": confidence,
    }


def compare_fields(
    drawing_fields: dict[str, Any],
    label_fields: dict[str, Any],
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
            )
        )

    if any(row["检测结果"] == "FAIL" for row in comparison_rows):
        overall_result = "FAIL"
    elif any(row["检测结果"] == "无法判断" for row in comparison_rows):
        overall_result = "待人工确认"
    else:
        overall_result = "PASS"

    return comparison_rows, overall_result
