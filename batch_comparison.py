from __future__ import annotations

from typing import Any

from field_config import FIELD_NAMES, clean_text, normalize_value


def active_field_names(label_items: list[dict[str, Any]]) -> list[str]:
    names = [
        field_name
        for field_name in FIELD_NAMES
        if any(
            clean_text(
                item.get("字段", {}).get(field_name, "")
            )
            for item in label_items
        )
    ]
    return names or FIELD_NAMES[:6]


def compare_two_label_fields(
    baseline_fields: dict[str, Any],
    target_fields: dict[str, Any],
    baseline_name: str,
    target_name: str,
    field_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    comparison_rows: list[dict[str, Any]] = []
    fields_to_compare = field_names or FIELD_NAMES

    for field_name in fields_to_compare:
        baseline_value = clean_text(
            baseline_fields.get(
                field_name,
                "",
            )
        )
        target_value = clean_text(
            target_fields.get(
                field_name,
                "",
            )
        )
        baseline_normalized = normalize_value(
            field_name,
            baseline_value,
        )
        target_normalized = normalize_value(
            field_name,
            target_value,
        )

        if not baseline_value and not target_value:
            result = "无法判断"
            status = "not_applicable"
            message = "两张标签均未识别到该字段。"
        elif not baseline_value:
            result = "无法判断"
            status = "baseline_missing"
            message = "基准标签未识别到该字段。"
        elif not target_value:
            result = "无法判断"
            status = "target_missing"
            message = "对比标签缺少该字段或OCR未识别成功。"
        elif baseline_normalized == target_normalized:
            result = "PASS"
            status = "match"
            message = "标准化后完全一致。"
        else:
            result = "FAIL"
            status = "mismatch"
            message = "标签之间字段值不一致。"

        comparison_rows.append(
            {
                "字段名称": field_name,
                "基准标签": baseline_name,
                "基准值": baseline_value,
                "基准标准化值": baseline_normalized,
                "对比标签": target_name,
                "对比值": target_value,
                "对比标准化值": target_normalized,
                "字段状态": status,
                "检测结果": result,
                "异常说明": message,
            }
        )

    return comparison_rows


def compare_multiple_labels(
    label_items: list[dict[str, Any]],
    baseline_index: int = 0,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    str,
]:
    if not label_items:
        return [], [], "FAIL"

    if baseline_index < 0 or baseline_index >= len(label_items):
        raise ValueError("baseline_index超出标签列表范围。")

    fields_to_compare = active_field_names(label_items)
    baseline_item = label_items[baseline_index]
    baseline_name = str(
        baseline_item.get("文件名", f"标签{baseline_index + 1}")
    )
    baseline_fields = baseline_item.get("字段", {})
    if not isinstance(baseline_fields, dict):
        raise TypeError("基准标签的“字段”必须是字典。")

    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    baseline_missing_count = sum(
        1
        for field_name in fields_to_compare
        if not clean_text(baseline_fields.get(field_name, ""))
    )
    baseline_result = "PASS" if baseline_missing_count == 0 else "待人工确认"

    summary_rows.append(
        {
            "标签序号": baseline_index + 1,
            "标签文件名": baseline_name,
            "是否基准": "是",
            "一致字段数量": len(fields_to_compare) - baseline_missing_count,
            "异常字段数量": 0,
            "无法判断数量": baseline_missing_count,
            "标签检测结果": baseline_result,
        }
    )

    for item_index, target_item in enumerate(label_items):
        if item_index == baseline_index:
            continue

        target_name = str(
            target_item.get("文件名", f"标签{item_index + 1}")
        )
        target_fields = target_item.get("字段", {})
        if not isinstance(target_fields, dict):
            raise TypeError(f"{target_name}的“字段”必须是字典。")

        current_rows = compare_two_label_fields(
            baseline_fields=baseline_fields,
            target_fields=target_fields,
            baseline_name=baseline_name,
            target_name=target_name,
            field_names=fields_to_compare,
        )

        for row in current_rows:
            row["标签序号"] = item_index + 1
        detail_rows.extend(current_rows)

        pass_count = sum(1 for row in current_rows if row["检测结果"] == "PASS")
        fail_count = sum(1 for row in current_rows if row["检测结果"] == "FAIL")
        unknown_count = sum(1 for row in current_rows if row["检测结果"] == "无法判断")

        if fail_count > 0:
            label_result = "FAIL"
        elif unknown_count > 0:
            label_result = "待人工确认"
        else:
            label_result = "PASS"

        summary_rows.append(
            {
                "标签序号": item_index + 1,
                "标签文件名": target_name,
                "是否基准": "否",
                "一致字段数量": pass_count,
                "异常字段数量": fail_count,
                "无法判断数量": unknown_count,
                "标签检测结果": label_result,
            }
        )

    if any(row["标签检测结果"] == "FAIL" for row in summary_rows):
        overall_result = "FAIL"
    elif any(row["标签检测结果"] != "PASS" for row in summary_rows):
        overall_result = "待人工确认"
    else:
        overall_result = "PASS"

    return detail_rows, summary_rows, overall_result


def build_field_matrix(
    label_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matrix_rows: list[dict[str, Any]] = []
    fields_to_show = active_field_names(label_items)

    for index, item in enumerate(label_items, start=1):
        fields = item.get("字段", {})
        row: dict[str, Any] = {
            "标签序号": index,
            "标签文件名": item.get("文件名", f"标签{index}"),
        }
        for field_name in fields_to_show:
            row[field_name] = fields.get(field_name, "")
        matrix_rows.append(row)

    return matrix_rows


def find_inconsistent_fields(
    label_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inconsistent_rows: list[dict[str, Any]] = []
    if not label_items:
        return inconsistent_rows

    for field_name in active_field_names(label_items):
        raw_values: list[str] = []
        normalized_values: list[str] = []

        for item in label_items:
            value = clean_text(item.get("字段", {}).get(field_name, ""))
            raw_values.append(value)
            normalized_values.append(normalize_value(field_name, value))

        non_empty_values = [value for value in normalized_values if value]
        unique_values = set(non_empty_values)
        missing_indexes = [
            index + 1
            for index, value in enumerate(normalized_values)
            if not value
        ]

        if len(unique_values) > 1 or missing_indexes:
            if missing_indexes and len(unique_values) > 1:
                issue_type = "部分标签缺失且字段值不一致"
            elif missing_indexes:
                issue_type = "部分标签未识别该字段"
            else:
                issue_type = "字段值不一致"

            row: dict[str, Any] = {
                "字段名称": field_name,
                "异常类型": issue_type,
                "缺失标签": "、".join(str(index) for index in missing_indexes),
            }
            for index, item in enumerate(label_items, start=1):
                filename = item.get("文件名", f"标签{index}")
                row[f"标签{index}：{filename}"] = raw_values[index - 1]
            inconsistent_rows.append(row)

    return inconsistent_rows
