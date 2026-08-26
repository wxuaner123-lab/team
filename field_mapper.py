from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from field_config import clean_text


PROJECT_ROOT = Path(__file__).resolve().parent
USER_MAPPING_FILE = PROJECT_ROOT / "data" / "user_field_mappings.json"


FIELD_MAP: dict[str, dict[str, Any]] = {
    "energy_efficiency_label": {
        "display_name_zh": "能效标签",
        "aliases": (
            "ENERGY EFFICIENCY LABEL",
            "ENERGY LABEL",
            "能效标签",
            "ÉTIQUETTE ÉNERGÉTIQUE",
            "بطاقة كفاءة الطاقة",
        ),
    },
    "washing_machine": {
        "display_name_zh": "洗衣机",
        "aliases": (
            "WASHING MACHINE",
            "洗衣机",
            "MACHINE À LAVER",
            "غسالة ملابس",
        ),
    },
    "model_number": {
        "display_name_zh": "型号",
        "aliases": (
            "MODEL NUMBER",
            "MODEL NO",
            "MODEL",
            "产品型号",
            "规格型号",
            "型号",
            "NUMÉRO DE MODÈLE",
            "MODELE",
            "MODÈLE",
            "RÉFÉRENCE MODÈLE",
            "رقم الطراز",
        ),
    },
    "brand_name": {
        "display_name_zh": "品牌名称",
        "aliases": (
            "BRAND NAME",
            "BRAND",
            "品牌",
            "品牌名称",
            "MARQUE",
            "NOM DE MARQUE",
            "العلامة التجارية",
        ),
    },
    "manufacturer_name": {
        "display_name_zh": "生产者名称",
        "aliases": (
            "生产者名称",
            "生产者",
            "制造商",
            "制造商名称",
            "生产企业",
            "MANUFACTURER",
            "MANUFACTURER NAME",
            "PRODUCER",
            "PRODUCER NAME",
            "COMPANY NAME",
        ),
    },
    "made_in": {
        "display_name_zh": "产地",
        "aliases": (
            "MADE IN",
            "COUNTRY OF ORIGIN",
            "产地",
            "制造地",
            "PAYS D'ORIGINE",
            "FABRIQUÉ EN",
            "بلد الصنع",
        ),
    },
    "annual_energy_consumption": {
        "display_name_zh": "年耗电量",
        "aliases": (
            "ANNUAL ENERGY CONSUMPTION",
            "ENERGY CONSUMPTION",
            "年耗电量",
            "耗电量",
            "CONSOMMATION ANNUELLE D'ÉNERGIE",
            "CONSOMMATION D'ÉNERGIE",
            "استهلاك الطاقة السنوي",
        ),
    },
    "annual_water_consumption": {
        "display_name_zh": "年耗水量",
        "aliases": (
            "ANNUAL WATER CONSUMPTION",
            "WATER CONSUMPTION",
            "年耗水量",
            "用水量",
            "CONSOMMATION ANNUELLE D'EAU",
            "CONSOMMATION D'EAU",
            "استهلاك المياه السنوي",
        ),
    },
    "cleaning_ratio": {
        "display_name_zh": "洗净比",
        "aliases": (
            "洗净比",
            "洗涤比",
            "WASH RATIO",
            "CLEANING RATIO",
        ),
    },
    "wash_spin_capacity": {
        "display_name_zh": "洗涤/脱水容量",
        "aliases": (
            "洗涤/脱水容量",
            "洗涤脱水容量",
            "洗涤/脱水容量(公斤)",
            "WASH/SPIN CAPACITY",
            "WASHING/SPINNING CAPACITY",
        ),
    },
    "wash_capacity": {
        "display_name_zh": "洗涤容量",
        "aliases": ("洗涤容量", "WASH CAPACITY", "WASHING CAPACITY"),
    },
    "spin_capacity": {
        "display_name_zh": "脱水容量",
        "aliases": ("脱水容量", "SPIN CAPACITY", "SPINNING CAPACITY"),
    },
    "capacity": {
        "display_name_zh": "容量",
        "aliases": ("CAPACITY", "容量", "CAPACITÉ", "السعة"),
    },
    "standard_reference_no": {
        "display_name_zh": "标准编号",
        "aliases": (
            "STANDARD REFERENCE NO",
            "STANDARD NO",
            "REFERENCE NO",
            "标准编号",
            "依据标准",
            "RÉFÉRENCE DE LA NORME",
            "NUMÉRO DE NORME",
            "الرقم المرجعي للمواصفة",
        ),
    },
    "registration_no": {
        "display_name_zh": "注册号",
        "aliases": (
            "REGISTRATION NO",
            "REGISTRATION NUMBER",
            "注册号",
            "NUMÉRO D'ENREGISTREMENT",
            "رقم التسجيل",
        ),
    },
    "energy_class": {
        "display_name_zh": "能效等级",
        "aliases": (
            "ENERGY CLASS",
            "ENERGY EFFICIENCY CLASS",
            "能效等级",
            "CLASSE ÉNERGÉTIQUE",
            "فئة كفاءة الطاقة",
        ),
    },
    "product_category": {
        "display_name_zh": "产品类别",
        "aliases": (
            "REFRIGERATOR",
            "DISHWASHER",
            "冰箱",
            "洗碗机",
            "RÉFRIGÉRATEUR",
        ),
    },
    "water_consumption_efficiency": {
        "display_name_zh": "水耗效率",
        "aliases": ("WATER CONSUMPTION EFFICIENCY",),
    },
    "water_extraction_efficiency": {
        "display_name_zh": "脱水效率",
        "aliases": ("WATER EXTRACTION EFFICIENCY",),
    },
    "type": {
        "display_name_zh": "类型",
        "aliases": ("TYPE",),
    },
    "drawing_code": {
        "display_name_zh": "图纸编号",
        "aliases": ("图纸编号", "图纸编码", "DRAWING CODE", "DRAWING NO", "DWG NO", "DWG"),
    },
    "label_code": {
        "display_name_zh": "编码",
        "aliases": ("编码", "标签编码", "LABEL CODE", "CODE", "PART NO"),
    },
    "label_name": {
        "display_name_zh": "标签名称",
        "aliases": ("标签名称", "LABEL NAME", "LABEL", "铭牌", "能效标签"),
    },
}


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
FRENCH_HINT_RE = re.compile(r"[ÀÂÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœ]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_field_text(value: Any) -> str:
    text = clean_text(value).upper()
    text = strip_accents(text)
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[:：|/\\]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_field_text_for_fuzzy(value: Any) -> str:
    text = normalize_field_text(value)
    return text.translate(str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"}))


def detect_language(text: str) -> str:
    text = clean_text(text)
    upper = text.upper()
    if CHINESE_RE.search(text):
        return "zh"
    if ARABIC_RE.search(text):
        return "ar"
    if FRENCH_HINT_RE.search(text) or any(
        keyword in upper
        for keyword in ("NUMÉRO", "MODELE", "MODÈLE", "MARQUE", "FABRIQUÉ", "CONSOMMATION", "CAPACITÉ")
    ):
        return "fr"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "unknown"


def load_user_mappings() -> dict[str, dict[str, Any]]:
    if not USER_MAPPING_FILE.exists():
        return {}
    try:
        data = json.loads(USER_MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def mapping_for_key(field_key: str) -> dict[str, Any]:
    return FIELD_MAP.get(field_key, {})


def iter_aliases() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for field_key, spec in FIELD_MAP.items():
        for alias in spec.get("aliases", ()):
            rows.append((field_key, spec["display_name_zh"], alias))
    return rows


def map_field_name(source_field_name: str, unknown_index: int = 1) -> dict[str, Any]:
    source = clean_text(source_field_name)
    source_language = detect_language(source)
    normalized = normalize_field_text(source)

    user_mappings = load_user_mappings()
    for raw_name, mapping in user_mappings.items():
        if normalize_field_text(raw_name) == normalized:
            field_key = clean_text(mapping.get("field_key", ""))
            display_name = clean_text(mapping.get("display_name_zh", "")) or mapping_for_key(field_key).get("display_name_zh", "")
            return {
                "field_key": field_key or f"unknown_{unknown_index}",
                "display_name_zh": display_name or f"未知字段_{unknown_index}",
                "display_name": display_name or f"未知字段_{unknown_index}",
                "source_language": clean_text(mapping.get("source_language", "")) or source_language,
                "mapping_confidence": 1.0,
                "mapping_status": "MANUAL_CONFIRMED",
                "normalized_text": normalized,
                "matched_alias": raw_name,
            }

    for field_key, display_name, alias in iter_aliases():
        if normalize_field_text(alias) == normalized:
            return {
                "field_key": field_key,
                "display_name_zh": display_name,
                "display_name": display_name,
                "source_language": source_language,
                "mapping_confidence": 0.98,
                "mapping_status": "EXACT_MATCH",
                "normalized_text": normalized,
                "matched_alias": alias,
            }

    normalized_fuzzy = normalize_field_text_for_fuzzy(source)
    best: tuple[float, str, str, str] | None = None
    for field_key, display_name, alias in iter_aliases():
        alias_norm = normalize_field_text(alias)
        alias_fuzzy = normalize_field_text_for_fuzzy(alias)
        score = max(
            SequenceMatcher(None, normalized, alias_norm).ratio(),
            SequenceMatcher(None, normalized_fuzzy, alias_fuzzy).ratio(),
        )
        if best is None or score > best[0]:
            best = (score, field_key, display_name, alias)

    if best and best[0] >= 0.86:
        return {
            "field_key": best[1],
            "display_name_zh": best[2],
            "display_name": best[2],
            "source_language": source_language,
            "mapping_confidence": round(best[0], 4),
            "mapping_status": "FUZZY_MATCH",
            "normalized_text": normalized,
            "matched_alias": best[3],
        }

    return {
        "field_key": f"unknown_{unknown_index}",
        "display_name_zh": f"未知字段_{unknown_index}",
        "display_name": f"未知字段_{unknown_index}",
        "source_language": source_language,
        "mapping_confidence": 0.0,
        "mapping_status": "NEED_REVIEW",
        "normalized_text": normalized,
        "matched_alias": "",
    }
