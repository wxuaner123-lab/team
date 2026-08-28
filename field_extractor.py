from __future__ import annotations

import re
from typing import Any

from field_config import (
    FIELD_CONFIG,
    FIELD_NAMES,
    clean_text,
    field_aliases,
    find_matching_field,
    normalize_field_label,
)
from energy_label_parser import merge_energy_fields, parse_energy_label_fields


VALUE_STOP_FIELDS = {
    normalize_field_label(alias)
    for rule in FIELD_CONFIG.values()
    for alias in rule.aliases
}


def split_lines(text: str) -> list[str]:
    return [
        clean_text(line)
        for line in str(text or "").splitlines()
        if clean_text(line)
    ]


def is_noise_value(value: str) -> bool:
    normalized = normalize_field_label(value)
    if not normalized:
        return True
    if normalized in VALUE_STOP_FIELDS:
        return True
    noise_keywords = (
        "CMYK",
        "借通用件登记",
        "描图",
        "校描",
        "签字",
        "日期",
        "比例",
        "单位",
        "技术要求",
        "材质工艺要求",
        "更改文件号",
        "旧底图总号",
        "二维码",
        "QR CODE",
    )
    return any(keyword.upper() in normalized for keyword in noise_keywords)


def clean_candidate_value(value: str) -> str:
    value = clean_text(value)
    value = value.strip(" :：|")
    value = re.sub(r"\s{2,}", " ", value)
    value = re.split(r"\s{3,}", value)[0]
    return value.strip()


def set_field_once(fields: dict[str, str], field_name: str, value: str) -> None:
    candidate = clean_candidate_value(value)
    if not candidate or is_noise_value(candidate):
        return
    if len(candidate) > 90:
        candidate = candidate[:90].strip()
    if not fields.get(field_name):
        fields[field_name] = candidate


def extract_inline_values(lines: list[str], fields: dict[str, str]) -> None:
    for line in lines:
        for field_name in FIELD_NAMES:
            if fields.get(field_name):
                continue
            aliases = sorted(field_aliases(field_name), key=len, reverse=True)
            for alias in aliases:
                escaped = re.escape(alias)
                patterns = (
                    rf"^\s*{escaped}\s*[:：]\s*(.+)$",
                    rf"^\s*{escaped}\s{{2,}}(.+)$",
                    rf"^\s*{escaped}\s+([A-Za-z0-9][A-Za-z0-9./ _()~:-]{{0,60}})$",
                )
                for pattern in patterns:
                    match = re.match(pattern, line, flags=re.IGNORECASE)
                    if match:
                        set_field_once(fields, field_name, match.group(1))
                        break
                if fields.get(field_name):
                    break


def extract_adjacent_values(lines: list[str], fields: dict[str, str]) -> None:
    for index, line in enumerate(lines):
        matched_field = find_matching_field(line)
        if not matched_field or fields.get(matched_field):
            continue
        for offset in range(1, 6):
            next_index = index + offset
            if next_index >= len(lines):
                break
            candidate = lines[next_index]
            if find_matching_field(candidate):
                break
            if not is_noise_value(candidate):
                set_field_once(fields, matched_field, candidate)
                break


def extract_regex_values(text: str, fields: dict[str, str]) -> None:
    normalized_text = clean_text(text)
    joined_text = "\n".join(split_lines(normalized_text))
    compact_joined = re.sub(r"[ \t]+", " ", joined_text)

    for field_name, rule in FIELD_CONFIG.items():
        if fields.get(field_name):
            continue
        for pattern in rule.patterns:
            match = re.search(pattern, compact_joined, flags=re.IGNORECASE)
            if match:
                set_field_once(fields, field_name, match.group(1))
                break


def extract_fallback_known_values(text: str, fields: dict[str, str]) -> None:
    compact = clean_text(text)

    if not fields.get("制造地"):
        match = re.search(r"\bMADE\s+IN\s+([A-Za-z][A-Za-z .'-]{1,40})\b", compact, flags=re.IGNORECASE)
        if match:
            fields["制造地"] = clean_candidate_value(match.group(1))

    if not fields.get("品牌"):
        match = re.search(r"\bBRAND\s+NAME\s+([A-Za-z][A-Za-z0-9 ._-]{1,40})\b", compact, flags=re.IGNORECASE)
        if match:
            fields["品牌"] = clean_candidate_value(match.group(1))

    if not fields.get("标签名称"):
        if re.search(r"CHINA\s+ENERGY\s+LABEL|中国能效标识|能效标签", compact, re.IGNORECASE):
            fields["标签名称"] = "能效标签"
        elif re.search(r"RATING\s+LABEL|铭牌", compact, re.IGNORECASE):
            fields["标签名称"] = "铭牌"
        elif re.search(r"Multilingual\s+Overview", compact, re.IGNORECASE):
            fields["标签名称"] = "Multilingual Overview"

    if not fields.get("项目名称"):
        match = re.search(r"项目名称\s*[:：]?\s*([^\n\r]{2,40})", compact)
        if match:
            set_field_once(fields, "项目名称", match.group(1))


def extract_fields_from_text(text: str) -> dict[str, str]:
    fields = {field_name: "" for field_name in FIELD_NAMES}
    lines = split_lines(text)
    extract_inline_values(lines, fields)
    extract_adjacent_values(lines, fields)
    extract_regex_values(text, fields)
    extract_fallback_known_values(text, fields)
    energy_fields, _ = parse_energy_label_fields(text, [])
    fields = merge_energy_fields(fields, energy_fields)

    # Keep old and real-data model names interoperable for existing reports.
    if fields.get("规格型号") and not fields.get("产品型号"):
        fields["产品型号"] = fields["规格型号"]
    if fields.get("产品型号") and not fields.get("规格型号"):
        fields["规格型号"] = fields["产品型号"]

    return fields


def summarize_fields(fields: dict[str, Any]) -> dict[str, str]:
    return {
        field_name: clean_text(fields.get(field_name, ""))
        for field_name in FIELD_NAMES
        if clean_text(fields.get(field_name, ""))
    }
