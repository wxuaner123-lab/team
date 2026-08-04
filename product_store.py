from __future__ import annotations

import json
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from field_config import FIELD_NAMES, clean_text


PROJECT_ROOT = Path(__file__).resolve().parent
MASTER_DATA_DIR = PROJECT_ROOT / "master_data"
DRAWINGS_DIR = MASTER_DATA_DIR / "drawings"
PRODUCTS_FILE = MASTER_DATA_DIR / "products.json"
DRAWINGS_FILE = MASTER_DATA_DIR / "drawings.json"
FIELD_TEMPLATES_FILE = MASTER_DATA_DIR / "field_templates.json"
INSPECTION_FILE = PROJECT_ROOT / "records" / "quality_terminal_records.jsonl"
EVIDENCE_DIR = PROJECT_ROOT / "records" / "evidence"


DEFAULT_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_id": "ABC-001",
        "product_model": "ABC-001",
        "product_code": "ABC-001",
        "version": "V2.0",
        "qr_code": "ABC001-V2",
        "qr_samples": [
            "ABC001-V2",
            "PID=ABC-001;MODEL=ABC-001;SN=SN20260803001;BATCH=B20260803",
            '{"product_id":"ABC-001","model":"ABC-001","sn":"SN20260803001","batch":"B20260803"}',
        ],
        "drawing_file": "",
        "standard_fields": {
            "产品型号": "ABC-001",
            "规格型号": "ABC-001",
            "额定电压": "1500V",
            "额定功率": "250kW",
            "版本号": "V2.0",
        },
        "required_fields": [
            "产品型号",
            "额定电压",
            "额定功率",
            "版本号",
        ],
        "status": "active",
        "create_time": "2026-08-03 00:00:00",
        "updated_at": "2026-08-03 00:00:00",
    },
    {
        "product_id": "ICM-2400-A",
        "product_model": "ICM-2400-A",
        "product_code": "ICM-2400-A",
        "version": "V1.2",
        "qr_code": "ICM-2400-A-V1.2",
        "qr_samples": [
            "ICM-2400-A-V1.2",
            "PID=ICM-2400-A;MODEL=ICM-2400-A;SN=ICM2400A-260701;BATCH=DEMO-BATCH",
        ],
        "drawing_file": "test_samples/图纸标签OCR_MVP_批量横向对比测试样品_兼容版/batch_sample_compatible/drawing.pdf",
        "standard_fields": {
            "产品名称": "工业控制模块",
            "产品型号": "ICM-2400-A",
            "规格型号": "ICM-2400-A",
            "额定电压": "DC 24V",
            "额定功率": "120W",
            "版本号": "V1.2",
            "序列号": "ICM2400A-260701",
        },
        "required_fields": [
            "产品型号",
            "额定电压",
            "额定功率",
            "版本号",
        ],
        "status": "active",
        "create_time": "2026-08-03 00:00:00",
        "updated_at": "2026-08-03 00:00:00",
    }
]


DEFAULT_DRAWINGS: list[dict[str, Any]] = [
    {
        "drawing_id": "DRW-ICM-2400-A-V1-2",
        "product_id": "ICM-2400-A",
        "product_model": "ICM-2400-A",
        "pdf_path": "test_samples/图纸标签OCR_MVP_批量横向对比测试样品_兼容版/batch_sample_compatible/drawing.pdf",
        "pdf_name": "drawing.pdf",
        "version": "V1.2",
        "qr_code": "ICM-2400-A-V1.2",
        "upload_time": "2026-08-03 00:00:00",
        "update_time": "2026-08-03 00:00:00",
        "is_current": True,
        "standard_fields": {
            "产品名称": "工业控制模块",
            "产品型号": "ICM-2400-A",
            "规格型号": "ICM-2400-A",
            "额定电压": "DC 24V",
            "额定功率": "120W",
            "版本号": "V1.2",
            "序列号": "ICM2400A-260701",
        },
        "parse_mode": "text",
        "page_count": 1,
        "warnings": [],
    }
]


def ensure_storage() -> None:
    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DRAWINGS_DIR.mkdir(parents=True, exist_ok=True)
    INSPECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not PRODUCTS_FILE.exists():
        save_products(DEFAULT_PRODUCTS)
    else:
        try:
            products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            products = []
        if isinstance(products, list):
            existing_ids = {item.get("product_id") for item in products if isinstance(item, dict)}
            missing_defaults = [
                item for item in DEFAULT_PRODUCTS if item["product_id"] not in existing_ids
            ]
            migrated_products = []
            for product in products:
                if not isinstance(product, dict):
                    continue
                migrated_product = dict(product)
                migrated_product.setdefault("product_model", migrated_product.get("model", ""))
                migrated_product.setdefault("product_code", migrated_product.get("product_id", ""))
                migrated_product.setdefault("qr_code", first_non_empty(migrated_product.get("qr_samples", [])))
                migrated_product.setdefault("create_time", migrated_product.get("updated_at", now))
                migrated_product.setdefault("updated_at", now)
                migrated_products.append(migrated_product)
            if missing_defaults or migrated_products != products:
                save_products([*migrated_products, *missing_defaults])

    if not DRAWINGS_FILE.exists():
        save_drawings(migrate_product_drawings(DEFAULT_DRAWINGS))
    else:
        try:
            drawings = json.loads(DRAWINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            drawings = []
        if isinstance(drawings, list):
            existing_ids = {item.get("drawing_id") for item in drawings if isinstance(item, dict)}
            missing_defaults = [
                item for item in DEFAULT_DRAWINGS if item["drawing_id"] not in existing_ids
            ]
            migrated_drawings = migrate_product_drawings(drawings)
            if missing_defaults or migrated_drawings != drawings:
                save_drawings([*migrated_drawings, *missing_defaults])

    if not FIELD_TEMPLATES_FILE.exists():
        save_field_templates(build_field_templates_from_products_and_drawings())


def load_json_file(path: Path, default: Any) -> Any:
    ensure_storage()
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_products() -> list[dict[str, Any]]:
    products = load_json_file(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    return products if isinstance(products, list) else []


def save_products(products: list[dict[str, Any]]) -> None:
    write_json_file(PRODUCTS_FILE, products)


def load_drawings() -> list[dict[str, Any]]:
    drawings = load_json_file(DRAWINGS_FILE, DEFAULT_DRAWINGS)
    return drawings if isinstance(drawings, list) else []


def save_drawings(drawings: list[dict[str, Any]]) -> None:
    write_json_file(DRAWINGS_FILE, drawings)


def load_field_templates() -> list[dict[str, Any]]:
    templates = load_json_file(FIELD_TEMPLATES_FILE, [])
    return templates if isinstance(templates, list) else []


def save_field_templates(templates: list[dict[str, Any]]) -> None:
    write_json_file(FIELD_TEMPLATES_FILE, templates)


def first_non_empty(values: Any) -> str:
    if isinstance(values, str):
        return clean_text(values)
    if isinstance(values, list):
        for value in values:
            cleaned = clean_text(value)
            if cleaned:
                return cleaned
    return ""


def normalize_key(value: Any) -> str:
    return clean_text(value).upper().replace(" ", "")


def safe_filename_part(value: Any, fallback: str = "item") -> str:
    text = clean_text(value) or fallback
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)


def generate_drawing_id(product_id: str, version: str, pdf_name: str, qr_code: str = "") -> str:
    digest_source = "|".join([product_id, version, pdf_name, qr_code])
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    return f"DRW-{safe_filename_part(product_id)}-{digest}"


def extract_lookup_values(qr_text: str, qr_payload: dict[str, str] | None = None) -> set[str]:
    payload = qr_payload or parse_qr_payload(qr_text)
    values = {normalize_key(qr_text)}
    for key, value in payload.items():
        if key in {
            "product_id",
            "pid",
            "product",
            "model",
            "product_model",
            "drawing_id",
            "drawing",
            "qr",
            "qr_code",
            "code",
            "型号",
            "产品型号",
            "raw",
        }:
            values.add(normalize_key(value))
    return {value for value in values if value}


def infer_product_id_from_qr(qr_text: str, fallback: str = "") -> str:
    payload = parse_qr_payload(qr_text)
    for key in ("product_id", "pid", "product", "model", "product_model", "型号", "产品型号", "raw"):
        value = clean_text(payload.get(key, ""))
        if value:
            return value
    return clean_text(qr_text) or fallback


def infer_version_from_qr(qr_text: str, fallback: str = "V1.0") -> str:
    payload = parse_qr_payload(qr_text)
    for key in ("version", "ver", "rev", "revision", "版本", "版本号"):
        value = clean_text(payload.get(key, ""))
        if value:
            return value
    compact = clean_text(qr_text)
    if "-V" in compact.upper():
        return compact[compact.upper().rfind("-V") + 1 :]
    return fallback


def read_json_file_direct(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def build_field_templates_from_products_and_drawings(
    products: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if products is None:
        products = read_json_file_direct(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    if drawings is None:
        drawings = read_json_file_direct(DRAWINGS_FILE, DEFAULT_DRAWINGS)
    for product in products:
        product_id = clean_text(product.get("product_id", ""))
        for field_name, value in product.get("standard_fields", {}).items():
            cleaned = clean_text(value)
            if cleaned:
                templates.append(
                    {
                        "product_id": product_id,
                        "drawing_id": "",
                        "field_name": field_name,
                        "standard_value": cleaned,
                        "source": "product",
                        "update_time": now,
                    }
                )
    for drawing in drawings:
        product_id = clean_text(drawing.get("product_id", ""))
        drawing_id = clean_text(drawing.get("drawing_id", ""))
        for field_name, value in drawing.get("standard_fields", {}).items():
            cleaned = clean_text(value)
            if cleaned:
                templates.append(
                    {
                        "product_id": product_id,
                        "drawing_id": drawing_id,
                        "field_name": field_name,
                        "standard_value": cleaned,
                        "source": "drawing",
                        "update_time": now,
                    }
                )
    return templates


def replace_field_templates(
    product_id: str,
    drawing_id: str,
    standard_fields: dict[str, Any],
    source: str = "drawing",
) -> None:
    templates = [
        template
        for template in load_field_templates()
        if not (
            template.get("product_id") == product_id
            and template.get("drawing_id", "") == drawing_id
            and template.get("source") == source
        )
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for field_name, value in standard_fields.items():
        cleaned = clean_text(value)
        if cleaned:
            templates.append(
                {
                    "product_id": product_id,
                    "drawing_id": drawing_id,
                    "field_name": field_name,
                    "standard_value": cleaned,
                    "source": source,
                    "update_time": now,
                }
            )
    save_field_templates(templates)


def migrate_product_drawings(
    existing_drawings: list[dict[str, Any]],
    products: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    drawings = [dict(item) for item in existing_drawings if isinstance(item, dict)]
    existing_paths = {
        clean_text(item.get("pdf_path", ""))
        for item in drawings
        if clean_text(item.get("pdf_path", ""))
    }
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if products is None:
        products = read_json_file_direct(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    for product in products:
        drawing_file = clean_text(product.get("drawing_file", ""))
        if not drawing_file or drawing_file in existing_paths:
            continue
        product_id = clean_text(product.get("product_id", ""))
        version = clean_text(product.get("version", "V1.0")) or "V1.0"
        qr_code = clean_text(product.get("qr_code", "")) or first_non_empty(product.get("qr_samples", []))
        pdf_name = Path(drawing_file).name
        drawings.append(
            {
                "drawing_id": generate_drawing_id(product_id, version, pdf_name, qr_code),
                "product_id": product_id,
                "product_model": clean_text(product.get("product_model", "")) or product_id,
                "pdf_path": drawing_file,
                "pdf_name": pdf_name,
                "version": version,
                "qr_code": qr_code,
                "upload_time": now,
                "update_time": now,
                "is_current": True,
                "standard_fields": normalize_standard_fields(product.get("standard_fields", {})),
                "parse_mode": "",
                "page_count": "",
                "warnings": [],
            }
        )
        existing_paths.add(drawing_file)
    return drawings


def parse_qr_payload(qr_text: str) -> dict[str, str]:
    text = clean_text(qr_text)
    if not text:
        return {}

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return {
                str(key).lower(): clean_text(value)
                for key, value in payload.items()
                if clean_text(value)
            }
    except json.JSONDecodeError:
        pass

    parsed_url = urlparse(text)
    if parsed_url.query:
        query = parse_qs(parsed_url.query)
        return {
            str(key).lower(): clean_text(values[0])
            for key, values in query.items()
            if values and clean_text(values[0])
        }

    pairs: dict[str, str] = {}
    for chunk in text.replace("|", ";").replace(",", ";").split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            continue
        key = clean_text(key).lower()
        value = clean_text(value)
        if key and value:
            pairs[key] = value

    if pairs:
        return pairs

    return {"raw": text}


def lookup_product(qr_text: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
    qr_payload = parse_qr_payload(qr_text)
    lookup_values = {
        normalize_key(value)
        for key, value in qr_payload.items()
        if key in {"product_id", "pid", "product", "model", "product_model", "型号", "产品型号", "raw"}
        and value
    }

    products = load_products()
    for product in products:
        candidates = {
            normalize_key(product.get("product_id")),
            normalize_key(product.get("product_model")),
            normalize_key(product.get("product_code")),
        }
        candidates.update(normalize_key(item) for item in product.get("qr_samples", []))
        if lookup_values.intersection(candidates):
            return product, qr_payload

    raw_value = normalize_key(qr_text)
    for product in products:
        sample_matches = any(raw_value == normalize_key(item) for item in product.get("qr_samples", []))
        if sample_matches:
            return product, qr_payload

    return None, qr_payload


def get_product(product_id: str) -> dict[str, Any] | None:
    normalized_id = normalize_key(product_id)
    for product in load_products():
        if normalize_key(product.get("product_id")) == normalized_id:
            return product
    return None


def drawing_matches_lookup(drawing: dict[str, Any], lookup_values: set[str]) -> bool:
    candidates = {
        normalize_key(drawing.get("drawing_id")),
        normalize_key(drawing.get("product_id")),
        normalize_key(drawing.get("product_model")),
        normalize_key(drawing.get("qr_code")),
        normalize_key(drawing.get("version")),
    }
    return bool(lookup_values.intersection(candidates))


def product_matches_lookup(product: dict[str, Any], lookup_values: set[str]) -> bool:
    candidates = {
        normalize_key(product.get("product_id")),
        normalize_key(product.get("product_model")),
        normalize_key(product.get("product_code")),
        normalize_key(product.get("qr_code")),
    }
    candidates.update(normalize_key(item) for item in product.get("qr_samples", []))
    return bool(lookup_values.intersection(candidates))


def list_drawings_for_product(product_id: str) -> list[dict[str, Any]]:
    normalized_id = normalize_key(product_id)
    drawings = [
        drawing
        for drawing in load_drawings()
        if normalize_key(drawing.get("product_id")) == normalized_id
    ]
    return sorted(
        drawings,
        key=lambda drawing: (
            bool(drawing.get("is_current")),
            clean_text(drawing.get("update_time", "")),
        ),
        reverse=True,
    )


def get_drawing(drawing_id: str) -> dict[str, Any] | None:
    normalized_id = normalize_key(drawing_id)
    for drawing in load_drawings():
        if normalize_key(drawing.get("drawing_id")) == normalized_id:
            return drawing
    return None


def get_current_drawing_for_product(product_id: str) -> dict[str, Any] | None:
    drawings = list_drawings_for_product(product_id)
    return drawings[0] if drawings else None


def lookup_product_and_drawing(
    qr_text: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, str]]:
    qr_payload = parse_qr_payload(qr_text)
    lookup_values = extract_lookup_values(qr_text, qr_payload)

    for drawing in load_drawings():
        if drawing_matches_lookup(drawing, lookup_values):
            product = get_product(clean_text(drawing.get("product_id", "")))
            if product is None:
                product = {
                    "product_id": drawing.get("product_id", ""),
                    "product_model": drawing.get("product_model", ""),
                    "product_code": drawing.get("product_id", ""),
                    "qr_code": drawing.get("qr_code", ""),
                    "qr_samples": [drawing.get("qr_code", "")],
                    "version": drawing.get("version", ""),
                    "standard_fields": drawing.get("standard_fields", {}),
                }
            return product, drawing, qr_payload

    for product in load_products():
        if product_matches_lookup(product, lookup_values):
            return product, get_current_drawing_for_product(product.get("product_id", "")), qr_payload

    return None, None, qr_payload


def save_pdf_bytes_to_library(
    pdf_bytes: bytes,
    pdf_name: str,
    product_id: str,
    version: str,
) -> str:
    ensure_storage()
    safe_product = safe_filename_part(product_id, "product")
    safe_version = safe_filename_part(version, "version")
    safe_pdf_name = Path(pdf_name).name or "drawing.pdf"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = DRAWINGS_DIR / f"{safe_product}_{safe_version}_{timestamp}_{safe_pdf_name}"
    target_path.write_bytes(pdf_bytes)
    return str(target_path.relative_to(PROJECT_ROOT))


def set_current_drawing(product_id: str, drawing_id: str) -> None:
    drawings = load_drawings()
    for drawing in drawings:
        if drawing.get("product_id") == product_id:
            drawing["is_current"] = drawing.get("drawing_id") == drawing_id
    save_drawings(drawings)


def delete_drawing(drawing_id: str) -> bool:
    drawings = load_drawings()
    target = next((drawing for drawing in drawings if drawing.get("drawing_id") == drawing_id), None)
    if target is None:
        return False
    remaining = [drawing for drawing in drawings if drawing.get("drawing_id") != drawing_id]
    save_drawings(remaining)
    templates = [
        template
        for template in load_field_templates()
        if template.get("drawing_id", "") != drawing_id
    ]
    save_field_templates(templates)
    return True


def update_drawing_metadata(
    drawing_id: str,
    version: str = "",
    qr_code: str = "",
    product_model: str = "",
) -> dict[str, Any] | None:
    drawings = load_drawings()
    updated_drawing: dict[str, Any] | None = None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for drawing in drawings:
        if drawing.get("drawing_id") != drawing_id:
            continue
        if clean_text(version):
            drawing["version"] = clean_text(version)
        if clean_text(qr_code):
            drawing["qr_code"] = clean_text(qr_code)
        if clean_text(product_model):
            drawing["product_model"] = clean_text(product_model)
        drawing["update_time"] = now
        updated_drawing = drawing
        break
    if updated_drawing is None:
        return None
    save_drawings(drawings)

    product = get_product(clean_text(updated_drawing.get("product_id", "")))
    if product is not None:
        qr_samples = list(product.get("qr_samples", []))
        if clean_text(updated_drawing.get("qr_code", "")) and updated_drawing["qr_code"] not in qr_samples:
            qr_samples.append(updated_drawing["qr_code"])
        upsert_product(
            {
                **product,
                "product_model": clean_text(updated_drawing.get("product_model", ""))
                or product.get("product_model", ""),
                "version": clean_text(updated_drawing.get("version", "")) or product.get("version", ""),
                "qr_code": clean_text(updated_drawing.get("qr_code", "")) or product.get("qr_code", ""),
                "qr_samples": qr_samples,
            }
        )
    return updated_drawing


def register_drawing_pdf(
    pdf_bytes: bytes,
    pdf_name: str,
    qr_text: str = "",
    product_id: str = "",
    product_model: str = "",
    version: str = "",
    make_current: bool = True,
) -> dict[str, Any]:
    from drawing_parser import extract_drawing_content
    from pdf_qr_parser import detect_pdf_qr_codes

    detected_qr = detect_pdf_qr_codes(pdf_bytes)
    qr_code = clean_text(qr_text) or clean_text(detected_qr.get("text", ""))
    inferred_product_id = clean_text(product_id) or infer_product_id_from_qr(qr_code, Path(pdf_name).stem)
    inferred_version = clean_text(version) or infer_version_from_qr(qr_code, "V1.0")
    inferred_model = clean_text(product_model) or inferred_product_id

    pdf_path = save_pdf_bytes_to_library(
        pdf_bytes=pdf_bytes,
        pdf_name=pdf_name,
        product_id=inferred_product_id,
        version=inferred_version,
    )
    drawing_result = extract_drawing_content(
        PROJECT_ROOT / pdf_path,
        debug_output_dir=PROJECT_ROOT / "debug_output" / "drawing_library",
        file_stem=safe_filename_part(inferred_product_id),
    )
    standard_fields = normalize_standard_fields(drawing_result.get("fields", {}))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    drawing_id = generate_drawing_id(
        inferred_product_id,
        inferred_version,
        pdf_name,
        qr_code,
    )
    drawing_record = {
        "drawing_id": drawing_id,
        "product_id": inferred_product_id,
        "product_model": inferred_model,
        "pdf_path": pdf_path,
        "pdf_name": Path(pdf_name).name,
        "version": inferred_version,
        "qr_code": qr_code,
        "pdf_qr_values": detected_qr.get("values", []),
        "upload_time": now,
        "update_time": now,
        "is_current": make_current,
        "standard_fields": standard_fields,
        "parse_mode": drawing_result.get("parse_mode", ""),
        "page_count": drawing_result.get("page_count", ""),
        "warnings": drawing_result.get("warnings", []),
    }

    drawings = [
        drawing for drawing in load_drawings() if drawing.get("drawing_id") != drawing_id
    ]
    if make_current:
        for drawing in drawings:
            if drawing.get("product_id") == inferred_product_id:
                drawing["is_current"] = False
    drawings.append(drawing_record)
    save_drawings(drawings)

    existing_product = get_product(inferred_product_id) or {}
    qr_samples = [
        item
        for item in existing_product.get("qr_samples", [])
        if clean_text(item)
    ]
    if qr_code and qr_code not in qr_samples:
        qr_samples.append(qr_code)
    product_payload = {
        "product_id": inferred_product_id,
        "product_model": inferred_model,
        "product_code": clean_text(existing_product.get("product_code", "")) or inferred_product_id,
        "version": inferred_version,
        "qr_code": qr_code or clean_text(existing_product.get("qr_code", "")),
        "qr_samples": qr_samples,
        "drawing_file": pdf_path,
        "current_drawing_id": drawing_id,
        "standard_fields": standard_fields or existing_product.get("standard_fields", {}),
        "required_fields": [
            field_name
            for field_name, value in (standard_fields or {}).items()
            if clean_text(value)
        ],
        "status": "active",
        "create_time": clean_text(existing_product.get("create_time", "")) or now,
    }
    product_record = upsert_product(product_payload)
    replace_field_templates(
        product_id=inferred_product_id,
        drawing_id=drawing_id,
        standard_fields=standard_fields,
        source="drawing",
    )

    return {
        "product": product_record,
        "drawing": drawing_record,
        "drawing_parse": drawing_result,
        "pdf_qr": detected_qr,
    }


def product_options() -> list[str]:
    return [
        f"{item.get('product_id', '')} / {item.get('product_model', '')}"
        for item in load_products()
    ]


def get_product_by_index(index: int) -> dict[str, Any] | None:
    products = load_products()
    if 0 <= index < len(products):
        return products[index]
    return None


def normalize_standard_fields(fields: dict[str, Any]) -> dict[str, str]:
    return {
        field_name: clean_text(fields.get(field_name, ""))
        for field_name in FIELD_NAMES
        if clean_text(fields.get(field_name, ""))
    }


def build_standard_snapshot(product: dict[str, Any], drawing_fields: dict[str, Any] | None = None) -> dict[str, str]:
    snapshot = normalize_standard_fields(product.get("standard_fields", {}))
    if drawing_fields:
        for field_name, value in drawing_fields.items():
            cleaned_value = clean_text(value)
            if cleaned_value and not snapshot.get(field_name):
                snapshot[field_name] = cleaned_value
    return snapshot


def upsert_product(product_payload: dict[str, Any]) -> dict[str, Any]:
    products = load_products()
    product_id = clean_text(product_payload.get("product_id"))
    if not product_id:
        raise ValueError("product_id is required")

    product_payload = dict(product_payload)
    product_payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for index, product in enumerate(products):
        if product.get("product_id") == product_id:
            products[index] = {**product, **product_payload}
            save_products(products)
            return products[index]

    products.append(product_payload)
    save_products(products)
    return product_payload


def save_uploaded_drawing(uploaded_file: Any, product_id: str) -> str:
    ensure_storage()
    safe_product_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in product_id)
    safe_name = Path(uploaded_file.name).name
    target_path = DRAWINGS_DIR / f"{safe_product_id}_{safe_name}"
    target_path.write_bytes(uploaded_file.getvalue())
    return str(target_path.relative_to(PROJECT_ROOT))


def resolve_project_path(path_value: str) -> Path | None:
    cleaned_path = clean_text(path_value)
    if not cleaned_path:
        return None
    path = Path(cleaned_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def save_evidence_image(image_bytes: bytes, detection_id: str, filename: str) -> str:
    ensure_storage()
    suffix = Path(filename).suffix.lower() or ".png"
    safe_detection_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in detection_id)
    target_path = EVIDENCE_DIR / f"{safe_detection_id}{suffix}"
    target_path.write_bytes(image_bytes)
    return str(target_path.relative_to(PROJECT_ROOT))


def append_quality_record(record: dict[str, Any]) -> dict[str, Any]:
    ensure_storage()
    record = dict(record)
    record.setdefault("inspection_id", datetime.now().strftime("QT-%Y%m%d-%H%M%S-%f"))
    record.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with INSPECTION_FILE.open("a", encoding="utf-8") as output_file:
        output_file.write(json.dumps(record, ensure_ascii=False))
        output_file.write("\n")
    return record


def load_quality_records(limit: int | None = None) -> list[dict[str, Any]]:
    ensure_storage()
    if not INSPECTION_FILE.exists():
        return []
    records: list[dict[str, Any]] = []
    with INSPECTION_FILE.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    records.reverse()
    if limit is not None:
        return records[:limit]
    return records


def export_master_data(target_dir: str | Path) -> Path:
    ensure_storage()
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    export_path = target / f"master_data_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(MASTER_DATA_DIR, export_path)
    return export_path
