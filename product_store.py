from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from field_config import FIELD_NAMES, clean_text


PROJECT_ROOT = Path(__file__).resolve().parent
MASTER_DATA_DIR = PROJECT_ROOT / "master_data"
DRAWINGS_DIR = MASTER_DATA_DIR / "drawings"
PRODUCTS_FILE = MASTER_DATA_DIR / "products.json"
INSPECTION_FILE = PROJECT_ROOT / "records" / "quality_terminal_records.jsonl"
EVIDENCE_DIR = PROJECT_ROOT / "records" / "evidence"


DEFAULT_PRODUCTS: list[dict[str, Any]] = [
    {
        "product_id": "ABC-001",
        "product_model": "ABC-001",
        "product_code": "ABC-001",
        "version": "V2.0",
        "qr_samples": [
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
        "updated_at": "2026-08-03 00:00:00",
    },
    {
        "product_id": "ICM-2400-A",
        "product_model": "ICM-2400-A",
        "product_code": "ICM-2400-A",
        "version": "V1.2",
        "qr_samples": [
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
        "updated_at": "2026-08-03 00:00:00",
    }
]


def ensure_storage() -> None:
    MASTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DRAWINGS_DIR.mkdir(parents=True, exist_ok=True)
    INSPECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
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
            if missing_defaults:
                save_products([*products, *missing_defaults])


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


def normalize_key(value: Any) -> str:
    return clean_text(value).upper().replace(" ", "")


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
