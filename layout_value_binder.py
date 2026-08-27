from __future__ import annotations

import re
from typing import Any

from field_config import clean_text
from field_definitions import FIELD_DEFINITIONS, all_field_definitions
from field_mapper import normalize_field_text


COUNTRY_VALUES = {
    "CHINA": "China",
    "中国": "中国",
    "PRC": "China",
    "P R C": "China",
    "P.R.C": "China",
}


def normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_field_text(value)).strip()


def compact_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9\u4e00-\u9fff\u0600-\u06ff]+", "", normalize_key(value))


def row_text(row: dict[str, Any]) -> str:
    return clean_text(row.get("识别文字") or row.get("text") or "")


def row_confidence(row: dict[str, Any]) -> float:
    try:
        return float(row.get("置信度", row.get("confidence", 0)) or 0)
    except Exception:
        return 0.0


def row_box(row: dict[str, Any]) -> list[float] | None:
    box = row.get("位置框") or row.get("bbox") or row.get("rec_box")
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return None
    try:
        return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
    except Exception:
        return None


def box_center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def alias_matches_text(alias: str, text: str) -> bool:
    alias_norm = normalize_key(alias)
    text_norm = normalize_key(text)
    if not alias_norm or not text_norm:
        return False
    if alias_norm == text_norm:
        return True
    if len(alias_norm) <= 5:
        return False
    return alias_norm in text_norm


def is_field_name_text(text: str) -> bool:
    normalized = normalize_key(text)
    if not normalized:
        return False
    for definition in all_field_definitions():
        for alias in definition.get("aliases", ()):
            if alias_matches_text(alias, normalized):
                return True
    return False


def matched_alias(definition: dict[str, Any], text: str) -> str:
    aliases = sorted(definition.get("aliases", ()), key=lambda value: len(normalize_key(value)), reverse=True)
    for alias in aliases:
        if alias_matches_text(alias, text):
            return alias
    return ""


def anchor_rows(rows: list[dict[str, Any]], definition: dict[str, Any]) -> list[dict[str, Any]]:
    anchors = []
    for row in rows:
        alias = matched_alias(definition, row_text(row))
        if alias:
            anchors.append({**row, "_matched_alias": alias})
    return anchors


def first_number(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return match.group(0) if match else ""


def normalize_ocr_value(value: str) -> str:
    text = clean_text(value).strip(" :：|")
    normalized = normalize_key(text)
    fixes = {
        "0S": "OS",
        "O5": "OS",
        "TWIN TU TUS": "TWIN TUB",
        "FRONT LAD ALA": "FRONT LOAD",
        "JOLLAD AD": "TOP LOAD",
        "JOL LAD AD": "TOP LOAD",
    }
    if normalized in fixes:
        return fixes[normalized]
    if re.match(r"(?i)^0S\s+\d", text):
        return re.sub(r"(?i)^0S", "OS", text)
    if re.match(r"(?i)^O5\s+\d", text):
        return re.sub(r"(?i)^O5", "OS", text)
    return text


def is_unit_text(text: str, definition: dict[str, Any]) -> bool:
    normalized = compact_key(text)
    return any(compact_key(unit) == normalized for unit in definition.get("expected_units", ()))


def nearby_unit(value_row: dict[str, Any], rows: list[dict[str, Any]], definition: dict[str, Any]) -> str:
    value_box = row_box(value_row)
    if not value_box:
        return ""
    vx, vy = box_center(value_box)
    best: tuple[float, str] | None = None
    for row in rows:
        text = row_text(row)
        if not is_unit_text(text, definition):
            continue
        box = row_box(row)
        if not box:
            continue
        ux, uy = box_center(box)
        vertical_gap = abs(uy - vy)
        horizontal_gap = abs(ux - vx)
        if vertical_gap > 28 or horizontal_gap > 170:
            continue
        distance = vertical_gap + horizontal_gap / 3
        if best is None or distance < best[0]:
            best = (distance, text)
    return clean_text(best[1]) if best else ""


def is_country_value(value: Any) -> bool:
    normalized = normalize_key(value)
    compact = compact_key(value)
    return normalized in COUNTRY_VALUES or compact in {compact_key(item) for item in COUNTRY_VALUES}


def is_company_like(value: str) -> bool:
    return bool(re.search(r"(公司|集团|有限公司|科技|实业|制造|MANUFACTURER|COMPANY|CO\.?|LTD\.?|LIMITED|INC\.?|CORP\.?)", value, re.IGNORECASE))


def is_model_like(value: str) -> bool:
    text = clean_text(value)
    if " " in text.strip():
        return False
    return bool(re.match(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9._/-]{5,60}$", text))


def is_standard_like(value: str) -> bool:
    return bool(re.match(r"(?i)^(OS|GB|IEC|EN|ISO)\s*[A-Z0-9 .:/_-]{2,40}$", normalize_ocr_value(value)))


def is_registration_like(value: str) -> bool:
    return bool(re.match(r"(?i)^\d{2,8}\s*[A-Z]?\d{0,3}$", clean_text(value))) or bool(re.match(r"(?i)^[A-Z]{1,4}\s*\d{2,8}\s*[A-Z]?\d{0,3}$", clean_text(value)))


def enum_value(value: str, definition: dict[str, Any]) -> str:
    normalized = normalize_key(value)
    for item in definition.get("enum_values", ()):
        if normalize_key(item) == normalized:
            return item
    return ""


def value_type_score(text: str, definition: dict[str, Any]) -> tuple[float, str, str]:
    text = normalize_ocr_value(text)
    if not text:
        return -100, "", "空文本不是有效候选值"
    if is_field_name_text(text):
        return -100, "", "候选文本是字段名，不作为字段值"

    value_type = definition.get("expected_value_type", "text")
    if value_type == "presence":
        return -100, "", "标题字段不需要绑定数值"
    if value_type == "number":
        number = first_number(text)
        if not number:
            return -80, "", "候选值不含数字"
        score = 30.0
        integer_part = number.split(".", 1)[0]
        score += min(len(integer_part) * 3, 15)
        if definition.get("field_key") == "annual_water_consumption":
            try:
                numeric = float(number)
            except Exception:
                numeric = 0.0
            if numeric < 10:
                score -= 28
            if "." in number:
                score -= 10
            if len(integer_part) >= 3:
                score += 14
        if definition.get("field_key") == "capacity" and "." in number:
            score += 8
        return score, number, "候选值符合数字类型"
    if value_type == "class":
        normalized = clean_text(text).strip().upper()
        if re.fullmatch(r"[A-G1-5]", normalized):
            return 30, normalized, "候选值符合等级类型"
        return -70, "", "候选值不符合等级类型"
    if value_type == "capacity_pair":
        if re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?", text):
            return 35, text, "候选值符合容量对格式"
        return -70, "", "候选值不符合容量对格式"
    if value_type == "country":
        if is_country_value(text):
            return 35, "China" if compact_key(text) in {compact_key("CHINA"), compact_key("PRC"), compact_key("P.R.C")} else text, "候选值符合国家/产地类型"
        if is_model_like(text) or is_standard_like(text):
            return -90, "", "候选值更像型号或标准编号"
        return 5, text, "候选值为文本，产地需人工确认"
    if value_type == "brand":
        if is_country_value(text):
            return -90, "", "候选值更像产地，不作为品牌"
        if is_model_like(text):
            return -90, "", "候选值更像型号，不作为品牌"
        if is_standard_like(text):
            return -90, "", "候选值更像标准编号，不作为品牌"
        if re.match(r"^[A-Za-z][A-Za-z0-9 ._-]{1,40}$", text):
            return 30, text, "候选值符合品牌文本类型"
        return -50, "", "候选值不符合品牌文本类型"
    if value_type == "model_code":
        if is_model_like(text):
            return 35, text, "候选值符合型号编码格式"
        return -60, "", "候选值不符合型号编码格式"
    if value_type == "standard_code":
        if is_standard_like(text):
            return 40, normalize_ocr_value(text), "候选值符合标准编号格式"
        return -80, "", "候选值不是完整标准编号"
    if value_type == "registration_code":
        if is_company_like(text):
            return -95, "", "候选值更像公司名称，不作为注册号"
        if is_registration_like(text):
            return 38, re.sub(r"(?i)(\d)(V\d)$", r"\1 \2", text), "候选值符合注册号格式"
        return -60, "", "候选值不符合注册号格式"
    if value_type == "enum":
        enum = enum_value(normalize_ocr_value(text), definition)
        if enum:
            return 35, enum, "候选值符合枚举类型"
        return -65, "", "候选值不在枚举范围"
    if value_type == "manufacturer":
        if is_country_value(text):
            return -95, "", "候选值更像产地，不作为生产者名称"
        if is_model_like(text) or is_standard_like(text):
            return -90, "", "候选值更像型号或标准编号"
        if is_company_like(text):
            return 35, text, "候选值符合公司/生产者名称特征"
        return -35, "", "候选值不像公司/生产者名称"
    if value_type == "code":
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9 .:/_-]{1,60}$", text):
            return 20, text, "候选值符合编码格式"
        return -50, "", "候选值不符合编码格式"
    return 15, text, "候选值符合文本类型"


def apply_unit_score(value_row: dict[str, Any], rows: list[dict[str, Any]], definition: dict[str, Any], value: str) -> tuple[float, str, str]:
    expected_units = tuple(definition.get("expected_units", ()))
    if not expected_units:
        return 0.0, value, ""
    unit = nearby_unit(value_row, rows, definition)
    raw_with_unit = f"{value} {unit}".strip() if unit else value
    if unit:
        return 28.0, raw_with_unit, f"候选值附近识别到期望单位 {unit}"
    return -18.0, value, "未在候选值附近识别到期望单位，降低置信度"


def forbidden_score(value: str, definition: dict[str, Any]) -> tuple[float, str]:
    normalized = normalize_key(value)
    for forbidden in definition.get("forbidden_values", ()):
        if normalize_key(forbidden) == normalized or normalize_key(forbidden) in normalized:
            return -120.0, f"候选值命中禁用值 {forbidden}"
    for unit in ("KWH", "LITER", "LITRE", "KG"):
        if unit in compact_key(value):
            expected = {compact_key(item) for item in definition.get("expected_units", ())}
            if expected and compact_key(unit) not in expected:
                return -100.0, f"候选值单位 {unit} 与字段期望单位不符"
    return 0.0, ""


def spatial_score(anchor: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, str]:
    anchor_box = row_box(anchor)
    candidate_box = row_box(candidate)
    if not anchor_box or not candidate_box:
        try:
            offset = abs(int(candidate.get("序号", 0)) - int(anchor.get("序号", 0)))
        except Exception:
            offset = 99
        return max(0.0, 45.0 - offset * 8), "候选值位于字段名附近文本行"

    ax, ay = box_center(anchor_box)
    bx, by = box_center(candidate_box)
    anchor_h = max(1.0, anchor_box[3] - anchor_box[1])
    same_row = abs(by - ay) <= max(anchor_h * 1.4, 20)
    close_row = abs(by - ay) <= max(anchor_h * 2.4, 38)
    if same_row:
        horizontal_gap = abs(bx - ax)
        if bx < ax:
            return max(40.0, 86.0 - horizontal_gap / 16), "候选值位于字段名左侧同一行"
        return max(35.0, 78.0 - horizontal_gap / 18), "候选值位于字段名右侧同一行"
    if close_row:
        return 35.0 - abs(by - ay) / 6 - abs(bx - ax) / 45, "候选值位于字段名近邻行"
    return -50.0, "候选值距离字段名过远"


def candidate_rows_for_anchor(anchor: dict[str, Any], rows: list[dict[str, Any]], definition: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if row is anchor or row.get("序号") == anchor.get("序号"):
            continue
        text = row_text(row)
        type_score, normalized_value, type_reason = value_type_score(text, definition)
        if type_score <= -70:
            continue
        unit_score, value_with_unit, unit_reason = apply_unit_score(row, rows, definition, normalized_value, )
        block_score, block_reason = forbidden_score(value_with_unit, definition)
        score, spatial_reason = spatial_score(anchor, row)
        score += type_score + unit_score + block_score + row_confidence(row) * 8
        reasons = [spatial_reason, type_reason]
        if unit_reason:
            reasons.append(unit_reason)
        if block_reason:
            reasons.append(block_reason)
        if block_score <= -100:
            score -= 50
        if score < 35:
            continue
        candidates.append(
            {
                "value": value_with_unit,
                "raw_text": text,
                "row_index": row.get("序号", ""),
                "confidence": row_confidence(row),
                "bbox": row_box(row),
                "score": round(score, 3),
                "reason": "；".join(reasons),
            }
        )
    return sorted(candidates, key=lambda item: float(item.get("score", 0) or 0), reverse=True)


def bind_one_field(rows: list[dict[str, Any]], definition: dict[str, Any]) -> dict[str, Any]:
    anchors = anchor_rows(rows, definition)
    all_candidates: list[dict[str, Any]] = []
    for anchor in anchors:
        candidates = candidate_rows_for_anchor(anchor, rows, definition)
        for candidate in candidates:
            candidate["anchor_text"] = row_text(anchor)
            candidate["anchor_alias"] = anchor.get("_matched_alias", "")
            candidate["anchor_bbox"] = row_box(anchor)
            all_candidates.append(candidate)
    all_candidates = sorted(all_candidates, key=lambda item: float(item.get("score", 0) or 0), reverse=True)
    best = all_candidates[0] if all_candidates else {}
    confidence = min(0.99, max(0.0, float(best.get("score", 0) or 0) / 145)) if best else 0.0
    min_confidence = float(definition.get("min_confidence_for_pass", 0.75) or 0.75)
    warnings: list[str] = []
    if not anchors:
        warnings.append("标签中未定位字段锚点")
    if best and confidence < min_confidence:
        warnings.append("字段候选置信度低，需要人工确认")
    if not best and anchors:
        warnings.append("定位到字段锚点，但未找到符合类型/单位约束的值")
    if best and is_field_name_text(clean_text(best.get("value", ""))):
        warnings.append("最终候选值疑似字段名，已阻止自动通过")
    strong_values = []
    if all_candidates:
        best_score = float(best.get("score", 0) or 0)
        for candidate in all_candidates:
            if float(candidate.get("score", 0) or 0) >= best_score - 12:
                value = clean_text(candidate.get("value", ""))
                if value and value not in strong_values:
                    strong_values.append(value)
    if len(strong_values) > 1:
        warnings.append("存在多个接近候选值，需要人工确认")
    return {
        "field_key": definition.get("field_key", ""),
        "display_name_zh": definition.get("display_name_zh", ""),
        "source_field_name": best.get("anchor_alias", "") or (anchors[0].get("_matched_alias", "") if anchors else ""),
        "selected_value": clean_text(best.get("value", "")),
        "confidence": round(confidence, 4),
        "needs_review": bool(warnings) or confidence < min_confidence,
        "warnings": warnings,
        "select_reason": clean_text(best.get("reason", "")) if best else "；".join(warnings),
        "candidates": all_candidates[:8],
        "candidate_values": strong_values[:6],
        "anchors": [
            {
                "text": row_text(anchor),
                "alias": anchor.get("_matched_alias", ""),
                "bbox": row_box(anchor),
                "confidence": row_confidence(anchor),
            }
            for anchor in anchors[:5]
        ],
    }


def bind_field_values_by_layout(
    ocr_rows: list[dict[str, Any]] | None,
    target_field_keys: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    rows = [row for row in (ocr_rows or []) if row_text(row)]
    target_keys = set(target_field_keys or FIELD_DEFINITIONS.keys())
    results: dict[str, dict[str, Any]] = {}
    for field_key, definition in FIELD_DEFINITIONS.items():
        if field_key not in target_keys:
            continue
        if definition.get("expected_value_type") == "presence":
            anchors = anchor_rows(rows, definition)
            if anchors:
                results[field_key] = {
                    "field_key": field_key,
                    "display_name_zh": definition.get("display_name_zh", ""),
                    "source_field_name": anchors[0].get("_matched_alias", ""),
                    "selected_value": anchors[0].get("_matched_alias", ""),
                    "confidence": round(row_confidence(anchors[0]), 4),
                    "needs_review": False,
                    "warnings": [],
                    "select_reason": "检测到标题/类别字段",
                    "candidates": [],
                    "candidate_values": [anchors[0].get("_matched_alias", "")],
                    "anchors": [{"text": row_text(anchors[0]), "alias": anchors[0].get("_matched_alias", ""), "bbox": row_box(anchors[0]), "confidence": row_confidence(anchors[0])}],
                }
            continue
        binding = bind_one_field(rows, definition)
        if binding.get("anchors") or binding.get("selected_value"):
            results[field_key] = binding
    return results
