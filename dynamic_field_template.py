from __future__ import annotations

import re
from typing import Any

from field_config import clean_text, normalize_value
from field_definitions import get_field_definition
from field_mapper import detect_language, map_field_name, mapping_for_key, normalize_field_text
from layout_value_binder import bind_field_values_by_layout


FIELD_DICTIONARY: list[dict[str, Any]] = [
    {
        "field_id": "energy_efficiency_label",
        "display_name_zh": "能效标签",
        "aliases": ("ENERGY EFFICIENCY LABEL", "ENERGY LABEL"),
        "value_type": "presence",
    },
    {
        "field_id": "washing_machine",
        "display_name_zh": "洗衣机",
        "aliases": ("WASHING MACHINE",),
        "value_type": "presence",
    },
    {
        "field_id": "energy_class",
        "display_name_zh": "能效等级",
        "aliases": ("ENERGY CLASS", "ENERGY EFFICIENCY CLASS"),
        "value_type": "class",
    },
    {
        "field_id": "annual_energy_consumption",
        "display_name_zh": "年耗电量",
        "aliases": ("ANNUAL ENERGY CONSUMPTION",),
        "value_type": "energy",
        "unit_aliases": ("KWH", "kWh", "千瓦时"),
    },
    {
        "field_id": "annual_water_consumption",
        "display_name_zh": "年耗水量",
        "aliases": ("ANNUAL WATER CONSUMPTION",),
        "value_type": "water",
        "unit_aliases": ("LITER", "LITRE", "L", "升"),
    },
    {
        "field_id": "capacity",
        "display_name_zh": "容量",
        "aliases": ("CAPACITY",),
        "value_type": "capacity",
        "unit_aliases": ("KG", "kg", "千克"),
    },
    {
        "field_id": "water_consumption_efficiency",
        "display_name_zh": "水耗效率",
        "aliases": ("WATER CONSUMPTION EFFICIENCY",),
        "value_type": "class",
    },
    {
        "field_id": "water_extraction_efficiency",
        "display_name_zh": "脱水效率",
        "aliases": ("WATER EXTRACTION EFFICIENCY",),
        "value_type": "class",
    },
    {
        "field_id": "type",
        "display_name_zh": "类型",
        "aliases": ("TYPE",),
        "value_type": "type",
    },
    {
        "field_id": "made_in",
        "display_name_zh": "产地",
        "aliases": ("MADE IN",),
        "value_type": "country",
    },
    {
        "field_id": "brand_name",
        "display_name_zh": "品牌名称",
        "aliases": ("BRAND NAME",),
        "value_type": "brand",
    },
    {
        "field_id": "manufacturer_name",
        "display_name_zh": "生产者名称",
        "aliases": ("生产者名称", "生产者", "制造商", "制造商名称", "生产企业", "MANUFACTURER", "PRODUCER", "MANUFACTURER NAME"),
        "value_type": "manufacturer",
    },
    {
        "field_id": "model_number",
        "display_name_zh": "型号",
        "aliases": ("MODEL NUMBER", "MODEL NO", "MODEL"),
        "value_type": "model",
    },
    {
        "field_id": "standard_reference_no",
        "display_name_zh": "标准编号",
        "aliases": ("STANDARD REFERENCE NO", "STANDARD REFERENCE NUMBER", "STANDARD NO"),
        "value_type": "standard_no",
    },
    {
        "field_id": "registration_no",
        "display_name_zh": "注册号",
        "aliases": ("REGISTRATION NO", "REGISTRATION NUMBER"),
        "value_type": "registration_no",
    },
    {
        "field_id": "cleaning_ratio",
        "display_name_zh": "洗净比",
        "aliases": ("洗净比", "洗涤比", "WASH RATIO", "CLEANING RATIO"),
        "value_type": "ratio",
    },
    {
        "field_id": "wash_spin_capacity",
        "display_name_zh": "洗涤/脱水容量",
        "aliases": ("洗涤/脱水容量", "洗涤脱水容量", "WASH/SPIN CAPACITY"),
        "value_type": "capacity_pair",
    },
    {
        "field_id": "wash_capacity",
        "display_name_zh": "洗涤容量",
        "aliases": ("洗涤容量", "WASH CAPACITY"),
        "value_type": "capacity",
    },
    {
        "field_id": "spin_capacity",
        "display_name_zh": "脱水容量",
        "aliases": ("脱水容量", "SPIN CAPACITY"),
        "value_type": "capacity",
    },
    {
        "field_id": "drawing_code",
        "display_name_zh": "图纸编号",
        "aliases": ("图纸编号", "图纸编码", "DRAWING CODE", "DRAWING NO", "DWG NO", "DWG"),
        "value_type": "code",
    },
    {
        "field_id": "label_code",
        "display_name_zh": "编码",
        "aliases": ("编码", "标签编码", "LABEL CODE", "CODE"),
        "value_type": "code",
    },
    {
        "field_id": "label_name",
        "display_name_zh": "标签名称",
        "aliases": ("标签名称", "LABEL NAME", "LABEL", "铭牌"),
        "value_type": "text",
    },
]


VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "class": re.compile(r"^[A-G]$", re.IGNORECASE),
    "energy": re.compile(r"^[0-9OISBl]+(?:\.[0-9OISBl]+)?$", re.IGNORECASE),
    "water": re.compile(r"^[0-9OISBl]{2,8}$", re.IGNORECASE),
    "capacity": re.compile(r"^[0-9OISBl]+(?:\.[0-9OISBl]+)?$", re.IGNORECASE),
    "country": re.compile(r"^[A-Za-z][A-Za-z .-]{1,30}$"),
    "manufacturer": re.compile(r"^(.{2,80}(公司|集团|厂|有限公司|科技|实业|制造|MANUFACTURER|COMPANY|CO\.?|LTD\.?|LIMITED|INC\.?|CORP\.?).*)$", re.IGNORECASE),
    "brand": re.compile(r"^[A-Za-z][A-Za-z0-9 ._-]{1,40}$"),
    "model": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{3,50}$"),
    "standard_no": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:/_-]{4,40}$"),
    "registration_no": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:/_-]{2,30}$"),
    "type": re.compile(r"^(TOP LOAD|FRONT LOAD|TWIN TUB|WITH DRYER)$", re.IGNORECASE),
    "ratio": re.compile(r"^[0-9OISBl]+(?:\.[0-9OISBl]+)?$", re.IGNORECASE),
    "capacity_pair": re.compile(r"^[0-9OISBl]+(?:\.[0-9OISBl]+)?\s*/\s*[0-9OISBl]+(?:\.[0-9OISBl]+)?$", re.IGNORECASE),
    "code": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:/_-]{1,50}$"),
    "text": re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:/_-]{1,60}$"),
}


VALUE_TRANSLATION = {
    "TOP LOAD": "上开盖/顶开式",
    "FRONT LOAD": "前开门/滚筒式",
    "TWIN TUB": "双桶",
    "WITH DRYER": "带烘干",
    "KWH": "千瓦时",
    "LITER": "升",
    "LITRE": "升",
    "KG": "千克",
    "CHINA": "中国",
}


FIELD_VALUE_TYPES = {
    "energy_efficiency_label": "presence",
    "washing_machine": "presence",
    "energy_class": "class",
    "annual_energy_consumption": "energy",
    "annual_water_consumption": "water",
    "capacity": "capacity",
    "water_consumption_efficiency": "class",
    "water_extraction_efficiency": "class",
    "made_in": "country",
    "manufacturer_name": "manufacturer",
    "brand_name": "brand",
    "model_number": "model",
    "standard_reference_no": "standard_no",
    "registration_no": "registration_no",
    "cleaning_ratio": "ratio",
    "wash_spin_capacity": "capacity_pair",
    "wash_capacity": "capacity",
    "spin_capacity": "capacity",
    "drawing_code": "code",
    "label_code": "code",
    "label_name": "text",
    "type": "type",
    "product_category": "presence",
}


FIELD_UNIT_ALIASES = {
    "annual_energy_consumption": ("KWH", "kWh", "千瓦时"),
    "annual_water_consumption": ("LITER", "LITRE", "L", "升"),
    "capacity": ("KG", "kg", "千克"),
}

INSPECTION_FIELD_KEYS = {
    "model_number",
    "manufacturer_name",
    "energy_class",
    "annual_energy_consumption",
    "annual_water_consumption",
    "cleaning_ratio",
    "wash_spin_capacity",
    "wash_capacity",
    "spin_capacity",
    "standard_reference_no",
    "capacity",
    "brand_name",
    "made_in",
    "registration_no",
    "water_consumption_efficiency",
    "water_extraction_efficiency",
    "type",
}

NON_INSPECTION_FIELD_KEYS = {
    "drawing_code",
    "label_code",
    "label_name",
}

NON_INSPECTION_NAME_HINTS = (
    "图纸编号",
    "图纸版本",
    "编码",
    "标签名称",
    "设计人",
    "审核人",
    "日期",
    "材质",
    "比例",
    "重量",
    "图样标记",
    "备注",
    "旧底图总号",
    "DRAWING",
    "DWG",
    "LABEL NAME",
)

INSPECTION_NAME_HINTS = (
    "型号",
    "规格型号",
    "生产者名称",
    "制造商",
    "制造商名称",
    "生产企业",
    "能效等级",
    "年耗电量",
    "耗电量",
    "年耗水量",
    "用水量",
    "洗净比",
    "洗涤比",
    "洗涤/脱水容量",
    "洗涤脱水容量",
    "洗涤容量",
    "脱水容量",
    "依据国家标准",
    "标准编号",
    "容量",
    "品牌名称",
    "产地",
    "注册号",
    "MODEL",
    "ENERGY CLASS",
    "ENERGY CONSUMPTION",
    "WATER CONSUMPTION",
    "CAPACITY",
    "BRAND",
    "MADE IN",
    "REGISTRATION",
    "STANDARD",
)

COUNTRY_VALUES = {"CHINA", "中国", "PRC", "P.R.C", "MADE IN CHINA"}


def value_type_for_field_key(field_key: str) -> str:
    return FIELD_VALUE_TYPES.get(field_key, "text")


def unit_aliases_for_field_key(field_key: str) -> tuple[str, ...]:
    return FIELD_UNIT_ALIASES.get(field_key, ())


def default_include_in_inspection(item: dict[str, Any]) -> bool:
    field_key = clean_text(item.get("field_key", "") or item.get("field_id", ""))
    display_name = clean_text(item.get("display_name_zh", ""))
    source_name = clean_text(item.get("source_field_name", ""))
    haystack = f"{field_key} {display_name} {source_name}".upper()
    if field_key in NON_INSPECTION_FIELD_KEYS:
        return False
    if field_key in INSPECTION_FIELD_KEYS:
        return True
    if any(clean_text(hint).upper() in haystack for hint in NON_INSPECTION_NAME_HINTS):
        return False
    if field_key.startswith("unknown_"):
        return any(clean_text(hint).upper() in haystack for hint in INSPECTION_NAME_HINTS)
    return any(clean_text(hint).upper() in haystack for hint in INSPECTION_NAME_HINTS)


def include_in_inspection(item: dict[str, Any]) -> bool:
    if item.get("is_deleted"):
        return False
    raw_value = item.get("include_in_inspection", None)
    if raw_value is None:
        return default_include_in_inspection(item)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() not in {"false", "0", "否", "不参与检测", "no"}
    return bool(raw_value)


def apply_field_mapping(item: dict[str, Any], unknown_index: int = 1) -> dict[str, Any]:
    source_name = clean_text(item.get("source_field_name", "")) or clean_text(item.get("display_name_zh", ""))
    mapping = map_field_name(source_name, unknown_index=unknown_index)
    mapped_value_type = value_type_for_field_key(mapping["field_key"])
    item_value_type = clean_text(item.get("value_type", ""))
    value_type = mapped_value_type if item_value_type in {"", "text"} and mapped_value_type != "text" else (item_value_type or mapped_value_type)
    mapped = {
        **item,
        "field_key": mapping["field_key"],
        "field_id": mapping["field_key"],
        "display_name_zh": mapping["display_name_zh"],
        "display_name": mapping["display_name"],
        "source_language": mapping["source_language"],
        "mapping_confidence": mapping["mapping_confidence"],
        "mapping_status": mapping["mapping_status"],
        "normalized_field_name": mapping["normalized_text"],
        "matched_alias": mapping["matched_alias"],
        "value_type": value_type,
        "needs_review": bool(item.get("needs_review")) or mapping["mapping_status"] == "NEED_REVIEW",
    }
    mapped["include_in_inspection"] = include_in_inspection(mapped)
    if not mapped["include_in_inspection"]:
        mapped["inspection_note"] = "字段属于图纸管理信息，默认不参与现场检测。"
    return mapped


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def normalize_key(value: Any) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_language(text: str) -> str:
    from field_mapper import detect_language as detect_mapped_language

    return detect_mapped_language(text)


def row_text(row: dict[str, Any]) -> str:
    return clean_text(row.get("识别文字", ""))


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


def match_field_definition(text: str) -> dict[str, Any] | None:
    normalized = normalize_key(text)
    if not normalized:
        return None
    for definition in sorted(FIELD_DICTIONARY, key=lambda item: max(len(a) for a in item["aliases"]), reverse=True):
        for alias in definition["aliases"]:
            alias_norm = normalize_key(alias)
            if normalized == alias_norm or alias_norm in normalized:
                return definition
    mapping = map_field_name(text)
    if mapping.get("mapping_status") != "NEED_REVIEW":
        spec = mapping_for_key(mapping["field_key"])
        return {
            "field_id": mapping["field_key"],
            "display_name_zh": mapping["display_name_zh"],
            "aliases": (text, *tuple(spec.get("aliases", ()))),
            "value_type": value_type_for_field_key(mapping["field_key"]),
            "unit_aliases": unit_aliases_for_field_key(mapping["field_key"]),
        }
    return None


def is_known_field_text(text: str) -> bool:
    return match_field_definition(text) is not None


def is_unit_text(text: str, definition: dict[str, Any]) -> bool:
    normalized = normalize_key(text)
    return any(normalize_key(unit) == normalized for unit in definition.get("unit_aliases", ()))


def clean_dynamic_value(value: str) -> str:
    value = clean_text(value).strip(" :：|")
    value = re.sub(r"\s+", " ", value)
    value = value.replace("0S ", "OS ")
    value = value.replace("O5 ", "OS ")
    normalized = normalize_key(value)
    type_ocr_fixes = {
        "TWIN TU TUS": "TWIN TUB",
        "FRONT LAD ALA": "FRONT LOAD",
        "JOLLAD AD": "TOP LOAD",
        "JOL LAD AD": "TOP LOAD",
    }
    if normalized in type_ocr_fixes:
        return type_ocr_fixes[normalized]
    return value.strip()


def translated_value(value: str) -> str:
    normalized = normalize_key(value)
    return VALUE_TRANSLATION.get(normalized, "")


def value_matches_type(text: str, definition: dict[str, Any]) -> bool:
    text = clean_dynamic_value(text)
    if not text or is_known_field_text(text):
        return False
    value_type = definition.get("value_type", "text")
    if value_type == "presence":
        return False
    if value_type == "text":
        return bool(text) and len(text) <= 80
    if value_type == "manufacturer" and is_country_value(text):
        return False
    pattern = VALUE_PATTERNS.get(value_type, VALUE_PATTERNS["text"])
    if not pattern.match(text):
        return False
    if value_type in {"energy", "water", "capacity"}:
        return bool(re.search(r"\d", text))
    return True


def join_value_with_unit(value: str, unit: str, definition: dict[str, Any]) -> str:
    value = clean_dynamic_value(value)
    unit = clean_dynamic_value(unit)
    if unit and is_unit_text(unit, definition):
        return f"{value} {unit}"
    return value


def nearby_candidates(
    anchor: dict[str, Any],
    rows: list[dict[str, Any]],
    definition: dict[str, Any],
) -> list[dict[str, Any]]:
    anchor_box = row_box(anchor)
    candidates: list[dict[str, Any]] = []
    value_type = definition.get("value_type", "text")

    for row in rows:
        if row is anchor:
            continue
        text = row_text(row)
        if not value_matches_type(text, definition):
            continue
        score = 0.0
        reasons: list[str] = []
        box = row_box(row)
        if anchor_box and box:
            ax, ay = box_center(anchor_box)
            bx, by = box_center(box)
            anchor_h = max(1.0, anchor_box[3] - anchor_box[1])
            same_row = abs(by - ay) <= max(anchor_h * 1.3, 18)
            close_row = abs(by - ay) <= max(anchor_h * 2.6, 34)
            left_of_anchor = bx < ax
            right_of_anchor = bx > ax

            if same_row and left_of_anchor:
                score += 130
                reasons.append("候选值位于字段名左侧同一行")
            elif same_row and right_of_anchor:
                score += 105
                reasons.append("候选值位于字段名右侧同一行")
            elif close_row:
                score += 65
                reasons.append("候选值位于字段名近邻行")
            score -= min(abs(by - ay), 300) / 8
            score -= min(abs(bx - ax), 500) / 18
            if value_type in {"energy", "water", "capacity"}:
                # In RTL/English mixed energy labels the numeric value is often
                # farther left than the unit; prefer the numeric token over the
                # nearby unit-only token.
                score += max(0.0, ax - bx) / 20
        else:
            offset = abs(int(row.get("序号", 0)) - int(anchor.get("序号", 0)))
            score += max(0, 80 - offset * 10)
            reasons.append("候选值位于字段名附近文本行")

        try:
            score += float(row.get("置信度", 0)) * 8
        except Exception:
            pass

        if value_type in {"energy", "water", "capacity"}:
            unit = nearest_unit(row, rows, definition)
            value = join_value_with_unit(text, unit, definition)
        else:
            value = clean_dynamic_value(text)

        candidates.append(
            {
                "value": value,
                "raw_text": text,
                "row_index": row.get("序号", ""),
                "confidence": row.get("置信度", 0),
                "bbox": box,
                "score": round(score, 3),
                "reason": "；".join(reasons) or "字段类型约束匹配",
            }
        )

    return [item for item in sorted(candidates, key=lambda x: x["score"], reverse=True) if item_score_ok(item)]


def item_score_ok(item: dict[str, Any]) -> bool:
    return float(item.get("score", 0) or 0) >= 40


def nearest_unit(value_row: dict[str, Any], rows: list[dict[str, Any]], definition: dict[str, Any]) -> str:
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
        if vertical_gap > 28 or horizontal_gap > 140:
            continue
        distance = vertical_gap + horizontal_gap / 2
        if best is None or distance < best[0]:
            best = (distance, text)
    return best[1] if best else ""


def build_dynamic_field_template(
    raw_text: str,
    ocr_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = ocr_rows or []
    template: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        text = row_text(row)
        definition = match_field_definition(text)
        if not definition or definition["field_id"] in seen:
            continue
        seen.add(definition["field_id"])
        source_field_name = next(
            alias for alias in definition["aliases"] if normalize_key(alias) in normalize_key(text)
        )
        candidates = nearby_candidates(row, rows, definition)
        if definition.get("value_type") == "presence":
            standard_value = source_field_name
            reason = "标题/类别字段，以出现为准"
            confidence = float(row.get("置信度", 0) or 0)
        elif candidates:
            standard_value = candidates[0]["value"]
            reason = candidates[0]["reason"]
            confidence = min(0.99, max(0.0, float(candidates[0].get("score", 0)) / 140))
        else:
            standard_value = ""
            reason = "未找到满足字段类型约束的值，需要人工确认"
            confidence = 0.0

        template.append(
            apply_field_mapping(
                {
                "field_id": definition["field_id"],
                "display_name_zh": definition["display_name_zh"],
                "source_field_name": source_field_name,
                "source_language": detect_language(source_field_name),
                "standard_value": standard_value,
                "unit": infer_unit(standard_value),
                "bbox": row_box(row),
                "confidence": round(confidence, 4),
                "value_type": definition.get("value_type", "text"),
                "required": True,
                "candidates": candidates[:5],
                "match_reason": reason,
                "needs_review": not bool(standard_value) or confidence < 0.55,
                },
                unknown_index=len(template) + 1,
            )
        )

    if not template:
        template = build_template_from_text(raw_text)
    template = apply_layout_bindings_to_template(template, rows)
    add_energy_class_if_missing(template, rows)
    return template


def apply_layout_bindings_to_template(
    template: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return template
    bindings = bind_field_values_by_layout(rows)
    if not bindings:
        return template

    merged = [dict(item) for item in template]
    index_by_key = {
        clean_text(item.get("field_key", "") or item.get("field_id", "")): index
        for index, item in enumerate(merged)
        if clean_text(item.get("field_key", "") or item.get("field_id", ""))
    }

    for field_key, binding in bindings.items():
        definition = get_field_definition(field_key) or {}
        value = clean_text(binding.get("selected_value", ""))
        if not value:
            continue
        confidence = float(binding.get("confidence", 0) or 0)
        min_confidence = float(definition.get("min_confidence_for_pass", 0.75) or 0.75)
        source_name = clean_text(binding.get("source_field_name", "")) or clean_text(definition.get("aliases", ("",))[0])
        item = apply_field_mapping(
            {
                "field_id": field_key,
                "field_key": field_key,
                "display_name_zh": clean_text(definition.get("display_name_zh", "")) or field_key,
                "source_field_name": source_name,
                "source_language": detect_language(source_name),
                "standard_value": value,
                "unit": infer_unit(value),
                "bbox": (binding.get("anchors") or [{}])[0].get("bbox"),
                "confidence": confidence,
                "value_type": value_type_for_field_key(field_key),
                "required": True,
                "candidates": binding.get("candidates", [])[:5],
                "match_reason": binding.get("select_reason", "布局字段绑定"),
                "needs_review": bool(binding.get("needs_review")) or confidence < min_confidence,
                "layout_binding": binding,
            },
            unknown_index=len(merged) + 1,
        )
        if field_key in index_by_key:
            current = merged[index_by_key[field_key]]
            current_confidence = float(current.get("confidence", 0) or 0)
            if confidence >= current_confidence or clean_text(current.get("standard_value", "")) != value:
                merged[index_by_key[field_key]] = {**current, **item}
        else:
            index_by_key[field_key] = len(merged)
            merged.append(item)

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in merged:
        key = clean_text(item.get("field_key", "") or item.get("field_id", ""))
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(item)
    return deduped


def add_energy_class_if_missing(template: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    if any(item.get("field_id") == "energy_class" for item in template):
        return
    class_rows = []
    for row in rows:
        match = re.match(r"^\s*([A-G])\s*[|/\\]?\s*$", row_text(row), flags=re.IGNORECASE)
        if match:
            class_rows.append({**row, "识别文字": match.group(1).upper()})
    if not class_rows:
        return
    # The selected class in this sample appears as a separate large/boxed class
    # near the upper label area; OCR may also see the whole A-G scale. Choose the
    # left-most class among high-confidence candidates, then leave it editable.
    class_rows = [
        row
        for row in class_rows
        if float(row.get("置信度", 0) or 0) >= 0.6
        and (row_box(row) or [0, 0, 0, 0])[1] > 350
    ]
    if not class_rows:
        return
    class_rows = sorted(
        class_rows,
        key=lambda row: (row_box(row) or [99999, 0, 99999, 0])[0],
    )
    selected = class_rows[0]
    value = row_text(selected).upper()
    template.insert(
        2,
        apply_field_mapping(
            {
            "field_id": "energy_class",
            "display_name_zh": "能效等级",
            "source_field_name": "Energy Class",
            "source_language": "en",
            "standard_value": value,
            "unit": "",
            "bbox": row_box(selected),
            "confidence": float(selected.get("置信度", 0) or 0),
            "value_type": "class",
            "required": True,
            "candidates": [
                {
                    "value": row_text(row).upper(),
                    "raw_text": row_text(row),
                    "row_index": row.get("序号", ""),
                    "confidence": row.get("置信度", 0),
                    "bbox": row_box(row),
                    "score": row.get("置信度", 0),
                    "reason": "能效等级候选",
                }
                for row in class_rows[:7]
            ],
            "match_reason": "从A-G能效等级区域识别",
            "needs_review": False,
            },
            unknown_index=len(template) + 1,
        ),
    )


def build_template_from_text(raw_text: str) -> list[dict[str, Any]]:
    lines = [clean_text(line) for line in raw_text.splitlines() if clean_text(line)]
    template: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        definition = match_field_definition(line)
        if not definition or definition["field_id"] in seen:
            continue
        seen.add(definition["field_id"])
        value = ""
        if definition.get("value_type") == "presence":
            value = definition["aliases"][0]
        else:
            value = find_value_from_text_lines(lines, index, definition)
        template.append(
            apply_field_mapping(
                {
                "field_id": definition["field_id"],
                "display_name_zh": definition["display_name_zh"],
                "source_field_name": definition["aliases"][0],
                "source_language": detect_language(definition["aliases"][0]),
                "standard_value": value,
                "unit": infer_unit(value),
                "bbox": None,
                "confidence": 0.62 if value else 0.0,
                "value_type": definition.get("value_type", "text"),
                "required": True,
                "candidates": [],
                "match_reason": "文本邻近行匹配" if value else "未找到候选值",
                "needs_review": not bool(value),
                },
                unknown_index=len(template) + 1,
            )
        )
    return template


def find_value_from_text_lines(lines: list[str], index: int, definition: dict[str, Any]) -> str:
    for direction in (1, -1):
        for distance in range(1, 6):
            pos = index + distance * direction
            if not 0 <= pos < len(lines):
                break
            text = lines[pos]
            if is_known_field_text(text):
                break
            if is_unit_text(text, definition):
                continue
            if not value_matches_type(text, definition):
                continue
            if definition.get("value_type") in {"energy", "water", "capacity"}:
                next_pos = pos + 1
                unit = lines[next_pos] if next_pos < len(lines) and is_unit_text(lines[next_pos], definition) else ""
                return join_value_with_unit(text, unit, definition)
            return clean_dynamic_value(text)
    return ""


def infer_unit(value: str) -> str:
    normalized = normalize_key(value)
    for unit in ("KWH", "LITER", "LITRE", "KG"):
        if unit in normalized:
            return {"KWH": "kWh", "LITER": "Liter", "LITRE": "Liter", "KG": "kg"}[unit]
    return ""


def template_to_standard_fields(
    template: list[dict[str, Any]],
    inspection_only: bool = False,
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for index, item in enumerate(template, start=1):
        if item.get("is_deleted"):
            continue
        if inspection_only and not include_in_inspection(item):
            continue
        name = clean_text(item.get("field_key", "")) or clean_text(item.get("display_name_zh", "")) or f"unknown_{index}"
        value = clean_text(item.get("standard_value", ""))
        if value:
            fields[name] = value
    return fields


def standard_fields_to_template(fields: dict[str, Any]) -> list[dict[str, Any]]:
    template: list[dict[str, Any]] = []
    for index, (name, value) in enumerate(fields.items(), start=1):
        if not clean_text(value):
            continue
        template.append(
            apply_field_mapping(
                {
                "field_id": f"legacy_{index}_{normalize_key(name).lower().replace(' ', '_') or index}",
                "display_name_zh": clean_text(name),
                "source_field_name": clean_text(name),
                "source_language": detect_language(name),
                "standard_value": clean_text(value),
                "unit": infer_unit(clean_text(value)),
                "bbox": None,
                "confidence": 0.5,
                "value_type": "text",
                "required": True,
                "candidates": [],
                "match_reason": "历史字段字典兼容生成",
                "needs_review": False,
                },
                unknown_index=index,
            )
        )
    return template


def match_label_to_template(
    template: list[dict[str, Any]],
    label_raw_text: str,
    label_ocr_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    rows = label_ocr_rows or []
    label_fields: dict[str, str] = {}
    debug: dict[str, Any] = {}
    target_keys = [
        clean_text(item.get("field_key", "") or item.get("field_id", ""))
        for item in template
        if not item.get("is_deleted") and include_in_inspection(item)
    ]
    layout_bindings = bind_field_values_by_layout(rows, target_keys)

    for item in template:
        if item.get("is_deleted") or not include_in_inspection(item):
            continue
        field_key = clean_text(item.get("field_key", "")) or clean_text(item.get("display_name_zh", ""))
        if not field_key:
            continue
        definition = definition_for_template_item(item)
        layout_binding = layout_bindings.get(field_key)
        layout_value = clean_text((layout_binding or {}).get("selected_value", ""))
        layout_confidence = float((layout_binding or {}).get("confidence", 0) or 0)
        layout_min_confidence = float((get_field_definition(field_key) or {}).get("min_confidence_for_pass", 0.75) or 0.75)
        layout_warnings = [clean_text(item) for item in (layout_binding or {}).get("warnings", []) if clean_text(item)]

        if (
            layout_binding
            and definition.get("value_type") != "presence"
            and layout_value
            and layout_confidence >= layout_min_confidence
            and not layout_warnings
        ):
            candidates = layout_binding.get("candidates", [])
            value = layout_value
            reason = f"布局字段绑定：{layout_binding.get('select_reason', '')}".strip("：")
            confidence = layout_confidence
        else:
            anchors = [
                row
                for row in rows
                if normalize_key(clean_text(item.get("source_field_name", ""))) in normalize_key(row_text(row))
                or any(normalize_key(alias) in normalize_key(row_text(row)) for alias in definition.get("aliases", ()))
            ]
            if definition.get("value_type") == "presence":
                found = bool(anchors) or normalize_key(item.get("source_field_name", "")) in normalize_key(label_raw_text)
                value = clean_text(item.get("standard_value", "")) if found else ""
                candidates = []
                reason = "标签中检测到该标题/类别字段" if found else "标签中未定位该标题/类别字段"
                confidence = 0.9 if found else 0.0
            elif anchors:
                candidates = nearby_candidates(anchors[0], rows, definition)
                standard_value = find_standard_value_in_text(label_raw_text, item, definition)
                if standard_value:
                    value = standard_value
                    reason = "已定位字段名，标签全文中找到与图纸标准值一致的值"
                    confidence = 0.82
                    if not candidates or candidates[0].get("value") != value:
                        candidates.insert(
                            0,
                            {
                                "value": value,
                                "raw_text": value,
                                "row_index": "",
                                "confidence": confidence,
                                "bbox": None,
                                "score": 120,
                                "reason": reason,
                            },
                        )
                elif candidates:
                    value = candidates[0]["value"]
                    reason = candidates[0]["reason"]
                    confidence = min(0.99, max(0.0, float(candidates[0].get("score", 0)) / 140))
                else:
                    fallback_value = fallback_find_value_in_text(label_raw_text, item, definition)
                    value = fallback_value
                    reason = "已定位字段名，使用文本邻近行兜底匹配" if fallback_value else "定位到字段名，但未找到合理候选值"
                    confidence = 0.55 if fallback_value else 0.0
                    if value:
                        candidates = [
                            {
                                "value": value,
                                "raw_text": value,
                                "row_index": "",
                                "confidence": confidence,
                                "bbox": None,
                                "score": 70,
                                "reason": reason,
                            }
                        ]
            else:
                candidates = []
                standard_value = find_standard_value_in_text(label_raw_text, item, definition)
                if standard_value:
                    value = standard_value
                    reason = "字段锚点未稳定识别，但标签全文中找到与图纸标准值一致的值"
                    confidence = 0.72
                    candidates = [
                        {
                            "value": value,
                            "raw_text": value,
                            "row_index": "",
                            "confidence": 0.72,
                            "bbox": None,
                            "score": 92,
                            "reason": reason,
                        }
                    ]
                else:
                    value = fallback_find_value_in_text(label_raw_text, item, definition)
                    reason = "文本兜底匹配" if value else "标签中未定位字段锚点"
                    confidence = 0.52 if value else 0.0
        if definition.get("field_id") == "manufacturer_name" and is_country_value(value):
            value = ""
            candidates = []
            reason = "标签值 CHINA/中国 更像是产地，不应匹配生产者名称。标签中未定位到生产者名称字段。"
            confidence = 0.0
        elif definition.get("field_id") == "manufacturer_name" and not value:
            reason = "标签中未定位到生产者名称字段"

        if value:
            label_fields[field_key] = value
        candidate_values = []
        for candidate in candidates:
            if candidate["value"] not in candidate_values:
                candidate_values.append(candidate["value"])
        if value and value not in candidate_values:
            candidate_values.insert(0, value)
        strong_candidate_values = []
        best_score = max([float(candidate.get("score", 0) or 0) for candidate in candidates], default=0.0)
        for candidate in candidates:
            if float(candidate.get("score", 0) or 0) >= best_score - 10:
                candidate_value = clean_text(candidate.get("value", ""))
                if candidate_value and candidate_value not in strong_candidate_values:
                    strong_candidate_values.append(candidate_value)
        debug[field_key] = {
            "source_field_name": item.get("source_field_name", ""),
            "display_name_zh": item.get("display_name_zh", ""),
            "field_key": field_key,
            "candidate_values": candidate_values[:6],
            "strong_candidate_values": strong_candidate_values[:6],
            "selected_value": value,
            "select_reason": reason,
            "confidence": round(confidence, 4),
            "needs_review": not bool(value) or len(set(strong_candidate_values)) > 1 or confidence < 0.5,
            "candidates": candidates[:6],
            "layout_binding": layout_binding or {},
        }

    return label_fields, debug


def definition_for_template_item(item: dict[str, Any]) -> dict[str, Any]:
    item_keys = {
        clean_text(item.get("field_id", "")),
        clean_text(item.get("field_key", "")),
    }
    for definition in FIELD_DICTIONARY:
        if definition["field_id"] in item_keys:
            aliases = tuple(
                dict.fromkeys(
                    (
                        clean_text(item.get("source_field_name", "")),
                        clean_text(item.get("display_name_zh", "")),
                        *definition.get("aliases", ()),
                    )
                )
            )
            return {**definition, "aliases": tuple(alias for alias in aliases if alias)}
    source_name = clean_text(item.get("source_field_name", "")) or clean_text(item.get("display_name_zh", ""))
    aliases = tuple(
        alias
        for alias in dict.fromkeys(
            (
                source_name,
                clean_text(item.get("display_name_zh", "")),
                clean_text(item.get("field_key", "")),
            )
        )
        if alias
    )
    return {
        "field_id": item.get("field_id", source_name),
        "display_name_zh": item.get("display_name_zh", source_name),
        "aliases": aliases or (source_name,),
        "value_type": item.get("value_type", "text"),
        "unit_aliases": (),
    }


def fallback_find_value_in_text(raw_text: str, item: dict[str, Any], definition: dict[str, Any]) -> str:
    lines = [clean_text(line) for line in raw_text.splitlines() if clean_text(line)]
    anchor_keys = [
        normalize_key(value)
        for value in (
            item.get("source_field_name", ""),
            item.get("display_name_zh", ""),
            item.get("field_key", ""),
            *definition.get("aliases", ()),
        )
        if normalize_key(value)
    ]
    for index, line in enumerate(lines):
        normalized_line = normalize_key(line)
        if anchor_keys and not any(anchor_key in normalized_line for anchor_key in anchor_keys):
            continue
        for offset in (-1, 1, -2, 2):
            pos = index + offset
            if 0 <= pos < len(lines) and value_matches_type(lines[pos], definition):
                return clean_dynamic_value(lines[pos])
    return ""


def is_country_value(value: Any) -> bool:
    normalized = normalize_key(value)
    return normalized in {normalize_key(item) for item in COUNTRY_VALUES}


def find_standard_value_in_text(raw_text: str, item: dict[str, Any], definition: dict[str, Any]) -> str:
    standard_value = clean_text(item.get("standard_value", ""))
    if not standard_value:
        return ""
    raw_compact = comparable_text(raw_text, definition)
    standard_compact = comparable_text(standard_value, definition)
    if standard_compact and standard_compact in raw_compact:
        return standard_value
    number = first_number(standard_value)
    value_type = definition.get("value_type", "")
    if value_type in {"energy", "water", "capacity"} and number and number in raw_compact:
        return standard_value
    return ""


def comparable_text(value: Any, definition: dict[str, Any]) -> str:
    text = normalize_value(definition.get("display_name_zh", ""), value)
    text = text.replace("千瓦时", "KWH").replace("升", "L").replace("千克", "KG")
    text = re.sub(r"\bLITERS?\b", "L", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLITRES?\b", "L", text, flags=re.IGNORECASE)
    return re.sub(r"[^A-Z0-9./:-]+", "", text.upper())


def first_number(value: Any) -> str:
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", clean_text(value))
    return match.group(0) if match else ""


def normalize_template_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    template: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        display_name = clean_text(row.get("中文字段名") or row.get("display_name_zh") or row.get("字段") or f"未知字段_{index}")
        source_name = clean_text(row.get("原始字段名") or row.get("source_field_name") or display_name)
        standard_value = clean_text(row.get("标准值") or row.get("standard_value"))
        field_key = clean_text(row.get("字段 key") or row.get("field_key") or row.get("field_id"))
        is_deleted_value = row.get("是否忽略该字段", row.get("is_deleted", False))
        is_deleted = bool(is_deleted_value) if not isinstance(is_deleted_value, str) else is_deleted_value in {"是", "true", "True", "1"}
        include_value = row.get("是否参与检测", row.get("include_in_inspection", None))
        if not display_name and not source_name and not standard_value:
            continue
        matched = match_field_definition(source_name) or {}
        base_item = {
                "field_id": field_key or matched.get("field_id") or f"manual_{index}_{normalize_key(source_name).lower().replace(' ', '_')}",
                "display_name_zh": display_name,
                "source_field_name": source_name,
                "source_language": clean_text(row.get("语言") or row.get("source_language")) or detect_language(source_name),
                "standard_value": standard_value,
                "unit": clean_text(row.get("单位") or row.get("unit")) or infer_unit(standard_value),
                "bbox": row.get("bbox") if isinstance(row.get("bbox"), list) else None,
                "confidence": float(row.get("模板置信度") or row.get("置信度") or row.get("confidence") or 0.8),
                "value_type": clean_text(row.get("value_type")) or matched.get("value_type", "text"),
                "required": bool(row.get("required", True)),
                "candidates": row.get("candidates", []) if isinstance(row.get("candidates"), list) else [],
                "match_reason": clean_text(row.get("匹配原因") or row.get("match_reason") or "人工编辑保存"),
                "needs_review": False,
                "note": clean_text(row.get("备注") or row.get("note")),
                "source": clean_text(row.get("source")) or ("manual" if clean_text(row.get("映射状态") or row.get("mapping_status")) == "MANUAL_CONFIRMED" else "drawing"),
                "is_deleted": is_deleted,
                "include_in_inspection": include_value,
        }
        mapped_item = apply_field_mapping(base_item, unknown_index=index)
        if field_key:
            mapped_item["field_key"] = field_key
            mapped_item["field_id"] = field_key
        if clean_text(row.get("映射状态") or row.get("mapping_status")) == "MANUAL_CONFIRMED" or base_item["source"] == "manual":
            mapped_item["mapping_status"] = "MANUAL_CONFIRMED"
            mapped_item["mapping_confidence"] = 1.0
            mapped_item["source"] = "manual"
            mapped_item["needs_review"] = False
        mapped_item["note"] = base_item["note"]
        mapped_item["is_deleted"] = is_deleted
        mapped_item["include_in_inspection"] = include_in_inspection(mapped_item)
        if not mapped_item["include_in_inspection"]:
            mapped_item["inspection_note"] = "字段属于图纸管理信息，默认不参与现场检测。"
        template.append(mapped_item)
    return template
