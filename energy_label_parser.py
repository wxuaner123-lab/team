from __future__ import annotations

import re
from typing import Any

from field_config import clean_text, normalize_field_label, normalize_value


ENERGY_LABEL_FIELDS = (
    "生产者名称",
    "规格型号",
    "耗电量",
    "用水量",
    "洗净比",
    "洗涤/脱水容量",
    "依据国家标准",
    "能效等级",
)


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "生产者名称": ("生产者名称", "生产者", "生产商", "制造商"),
    "规格型号": ("规格型号", "型号规格"),
    "耗电量": ("耗电量", "耗电量(千瓦时/工作周期)"),
    "用水量": ("用水量", "用水量(升/工作周期)"),
    "洗净比": ("洗净比",),
    "洗涤/脱水容量": ("洗涤/脱水容量", "洗涤/脱水容量(公斤)"),
    "依据国家标准": ("依据国家标准", "国家标准", "执行标准"),
    "能效等级": ("能效等级",),
}


VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "规格型号": re.compile(r"\b[A-Z]{1,6}[A-Z0-9.-]*-[A-Z0-9.-]{3,}\b", re.IGNORECASE),
    "耗电量": re.compile(r"\b[0-9][0-9OISBl]*\.[0-9OISBl]{1,4}\b"),
    "用水量": re.compile(r"^[0-9OISBl]{1,3}$"),
    "洗净比": re.compile(r"\b[0-9][0-9OISBl]*\.[0-9OISBl]{1,3}\b"),
    "洗涤/脱水容量": re.compile(r"\b[0-9OISBl]+(?:\.[0-9OISBl]+)?\s*/\s*[0-9OISBl]+(?:\.[0-9OISBl]+)?\b"),
    "依据国家标准": re.compile(r"\bGB\s*[0-9][0-9.\- ]{4,30}\b", re.IGNORECASE),
    "能效等级": re.compile(r"^[1-5]\s*(?:级|等級|LEVEL|CLASS)?$", re.IGNORECASE),
}


INLINE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "生产者名称": (
        re.compile(r"生产者名称\s*[:：]?\s*([^\n\r]{2,60})"),
    ),
    "规格型号": (
        re.compile(r"规格型号\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{3,60})"),
    ),
    "耗电量": (
        re.compile(r"耗电量[^\n\r0-9OISBl]{0,30}([0-9OISBl]+\.[0-9OISBl]{1,4})"),
        re.compile(r"([0-9OISBl]+\.[0-9OISBl]{1,4})\s*\n\s*耗电量"),
    ),
    "用水量": (
        re.compile(r"用水量[^\n\r0-9OISBl]{0,30}([0-9OISBl]{1,3})"),
        re.compile(r"([0-9OISBl]{1,3})\s*\n\s*用水量"),
    ),
    "洗净比": (
        re.compile(r"洗净比[^\n\r0-9OISBl]{0,20}([0-9OISBl]+\.[0-9OISBl]{1,3})"),
        re.compile(r"([0-9OISBl]+\.[0-9OISBl]{1,3})\s*\n\s*洗净比"),
    ),
    "洗涤/脱水容量": (
        re.compile(r"洗涤\s*/\s*脱水容量[^\n\r0-9OISBl]{0,20}([0-9OISBl.]+\s*/\s*[0-9OISBl.]+)"),
        re.compile(r"([0-9OISBl.]+\s*/\s*[0-9OISBl.]+)\s*\n\s*洗涤\s*/\s*脱水容量"),
    ),
    "依据国家标准": (
        re.compile(r"依据国家标准\s*[:：]?\s*([A-Za-z]{1,4}\s*[0-9.\- ]{5,30})"),
    ),
    "能效等级": (
        re.compile(r"([1-5])\s*级"),
        re.compile(r"能效等级\s*[:：]?\s*([1-5])"),
    ),
}


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


def center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    normalized = normalize_field_label(text)
    return any(normalize_field_label(alias) in normalized for alias in aliases)


def clean_energy_value(field_name: str, value: str) -> str:
    value = clean_text(value)
    value = value.strip(" :：|")
    if field_name == "依据国家标准":
        match = VALUE_PATTERNS[field_name].search(value)
        return clean_text(match.group(0)) if match else value
    if field_name == "能效等级":
        match = re.search(r"[1-5]", value)
        return match.group(0) if match else value
    pattern = VALUE_PATTERNS.get(field_name)
    if pattern:
        match = pattern.search(value)
        if match:
            return clean_text(match.group(0))
    return value


def value_matches_field(field_name: str, value: str) -> bool:
    value = clean_text(value)
    if not value:
        return False
    if field_name == "生产者名称":
        return not any(contains_alias(value, aliases) for aliases in FIELD_ALIASES.values()) and len(value) >= 4
    pattern = VALUE_PATTERNS.get(field_name)
    return bool(pattern.search(value)) if pattern else bool(value)


def extract_inline_value(field_name: str, text: str) -> str:
    for pattern in INLINE_PATTERNS.get(field_name, ()):
        match = pattern.search(text)
        if match:
            return clean_energy_value(field_name, match.group(1))
    return ""


def extract_line_neighbor_value(field_name: str, text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    aliases = FIELD_ALIASES.get(field_name, (field_name,))
    for index, line in enumerate(lines):
        if not contains_alias(line, aliases):
            continue

        inline_value = candidate_from_inline_anchor(field_name, line)
        if inline_value:
            return inline_value

        if field_name in {"耗电量", "用水量", "洗净比", "洗涤/脱水容量"}:
            search_offsets = (1, -1, 2)
        else:
            search_offsets = (1, 2)
        for offset in search_offsets:
            candidate_index = index + offset
            if candidate_index < 0 or candidate_index >= len(lines):
                continue
            candidate = lines[candidate_index]
            if any(contains_alias(candidate, alias_group) for alias_group in FIELD_ALIASES.values()):
                continue
            if value_matches_field(field_name, candidate):
                return clean_energy_value(field_name, candidate)
    return ""


def candidate_from_inline_anchor(field_name: str, anchor_text: str) -> str:
    for alias in FIELD_ALIASES.get(field_name, (field_name,)):
        alias_index = anchor_text.find(alias)
        if alias_index < 0:
            continue
        tail = anchor_text[alias_index + len(alias) :]
        tail = tail.strip(" :：()（）")
        if tail and value_matches_field(field_name, tail):
            return clean_energy_value(field_name, tail)
    return ""


def spatial_candidates(field_name: str, anchor: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchor_box = row_box(anchor)
    anchor_index = int(anchor.get("序号", 0))
    candidates: list[dict[str, Any]] = []

    for row in rows:
        text = row_text(row)
        if not text or row is anchor:
            continue
        if contains_alias(text, FIELD_ALIASES.get(field_name, ())):
            continue
        if not value_matches_field(field_name, text):
            continue

        reason_parts: list[str] = []
        score = 0.0
        if anchor_box and row_box(row):
            box = row_box(row)
            assert box is not None
            ax, ay = center(anchor_box)
            bx, by = center(box)
            anchor_h = max(1.0, anchor_box[3] - anchor_box[1])
            anchor_w = max(1.0, anchor_box[2] - anchor_box[0])
            vertical_gap = abs(by - ay)
            horizontal_gap = abs(bx - ax)
            same_column = horizontal_gap <= anchor_w * 0.75
            same_row = vertical_gap <= anchor_h * 0.75

            if field_name in {"耗电量", "用水量", "洗净比", "洗涤/脱水容量"}:
                if same_row and bx > ax:
                    score += 130
                    reason_parts.append("候选值位于字段名右侧同一行")
                elif by < ay and same_column and vertical_gap <= anchor_h * 2.5:
                    score += 95
                    reason_parts.append("候选值位于字段名上方近邻同列")
                elif by > ay and same_column and vertical_gap <= anchor_h * 2.5:
                    score += 70
                    reason_parts.append("候选值位于字段名下方同列")
            else:
                if by > ay and same_column:
                    score += 100
                    reason_parts.append("候选值位于字段名下方同列")
                elif same_row and bx > ax:
                    score += 85
                    reason_parts.append("候选值位于字段名右侧同一行")

            score -= min(vertical_gap, 300) / 8
            score -= min(horizontal_gap, 300) / 12
        else:
            offset = int(row.get("序号", 0)) - anchor_index
            if field_name in {"耗电量", "用水量", "洗净比", "洗涤/脱水容量"} and offset == -1:
                score += 80
                reason_parts.append("候选值位于字段名前一行")
            elif field_name not in {"耗电量", "用水量", "洗净比", "洗涤/脱水容量"} and offset == 1:
                score += 80
                reason_parts.append("候选值位于字段名后一行")
            score -= abs(offset) * 8

        try:
            score += float(row.get("置信度", 0)) * 10
        except Exception:
            pass

        candidates.append(
            {
                "value": clean_energy_value(field_name, text),
                "raw_text": text,
                "row_index": row.get("序号", ""),
                "confidence": row.get("置信度", 0),
                "box": row_box(row),
                "score": round(score, 3),
                "reason": "；".join(reason_parts) or "字段格式匹配",
            }
        )

    return [
        candidate
        for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True)
        if candidate["score"] > 35
    ]


def parse_energy_label_fields(
    raw_text: str,
    ocr_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    text = clean_text(raw_text)
    rows = ocr_rows or []
    fields: dict[str, str] = {}
    debug: dict[str, Any] = {}

    for field_name in ENERGY_LABEL_FIELDS:
        selected = extract_line_neighbor_value(field_name, text) or extract_inline_value(field_name, text)
        candidates: list[dict[str, Any]] = []
        reason = "文本正则命中"
        anchor_info: dict[str, Any] | None = None

        anchors = [
            row
            for row in rows
            if contains_alias(row_text(row), FIELD_ALIASES.get(field_name, (field_name,)))
        ]
        if anchors:
            anchor = anchors[0]
            anchor_info = {
                "row_index": anchor.get("序号", ""),
                "text": row_text(anchor),
                "box": row_box(anchor),
            }
            inline_anchor_value = candidate_from_inline_anchor(field_name, row_text(anchor))
            candidates = spatial_candidates(field_name, anchor, rows)
            if inline_anchor_value:
                candidates.insert(
                    0,
                    {
                        "value": inline_anchor_value,
                        "raw_text": row_text(anchor),
                        "row_index": anchor.get("序号", ""),
                        "confidence": anchor.get("置信度", 0),
                        "box": row_box(anchor),
                        "score": 160,
                        "reason": "字段名同一OCR行内含值",
                    },
                )
            if candidates and field_name in {"耗电量", "用水量", "洗净比", "洗涤/脱水容量"}:
                selected = candidates[0]["value"]
                reason = candidates[0]["reason"]
            elif not selected and candidates:
                selected = candidates[0]["value"]
                reason = candidates[0]["reason"]

        if selected:
            fields[field_name] = selected

        relevant_candidates = [
            candidate
            for candidate in candidates
            if not candidates or candidate.get("score", 0) >= candidates[0].get("score", 0) - 25
        ]
        unique_candidate_values = []
        for candidate in relevant_candidates:
            if candidate["value"] not in unique_candidate_values:
                unique_candidate_values.append(candidate["value"])

        confidence = 0.0
        if candidates:
            confidence = min(0.99, max(0.0, float(candidates[0].get("score", 0)) / 130))
        elif selected:
            confidence = 0.82

        debug[field_name] = {
            "anchor": anchor_info,
            "candidates": candidates[:6],
            "candidate_values": unique_candidate_values[:6],
            "selected_value": selected,
            "select_reason": reason if selected else "未定位到符合字段格式的候选值",
            "confidence": round(confidence, 4),
            "needs_review": bool(len(unique_candidate_values) > 1 and selected),
        }

    return fields, debug


def merge_energy_fields(
    base_fields: dict[str, str],
    energy_fields: dict[str, str],
) -> dict[str, str]:
    merged = dict(base_fields)
    for field_name, value in energy_fields.items():
        if not value:
            continue
        if field_name in ENERGY_LABEL_FIELDS:
            merged[field_name] = value
    if merged.get("规格型号") and not merged.get("产品型号"):
        merged["产品型号"] = merged["规格型号"]
    return merged
