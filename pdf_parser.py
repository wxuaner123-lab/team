from __future__ import annotations

from drawing_parser import extract_fields_from_pdf_text
from field_config import FIELD_NAMES


def clean_text_line(line: str) -> str:
    return " ".join(str(line or "").split())


def validate_fields(fields: dict[str, str]) -> list[str]:
    return [
        field_name
        for field_name in FIELD_NAMES
        if not fields.get(field_name)
    ]
