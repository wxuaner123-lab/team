from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal


CompareType = Literal["text", "model", "code", "number", "unit", "version"]


@dataclass(frozen=True)
class FieldRule:
    name: str
    aliases: tuple[str, ...]
    compare_type: CompareType = "text"
    required: bool = False
    ocr_digit_fix: bool = False
    patterns: tuple[str, ...] = field(default_factory=tuple)


FIELD_CONFIG: dict[str, FieldRule] = {
    "产品名称": FieldRule(
        name="产品名称",
        aliases=("产品名称", "NAME", "PRODUCT NAME"),
        compare_type="text",
    ),
    "产品型号": FieldRule(
        name="产品型号",
        aliases=("产品型号", "MODEL", "MODEL NO", "PRODUCT MODEL"),
        compare_type="model",
        required=True,
        patterns=(
            r"\bModel\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{1,40})",
            r"规格型号\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{1,40})",
        ),
    ),
    "额定电压": FieldRule(
        name="额定电压",
        aliases=("额定电压", "VOLTAGE", "RATED VOLTAGE"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Voltage\s*[:：]?\s*([0-9OISBl.\-~～ ]+\s*V\s*~?)",),
    ),
    "额定功率": FieldRule(
        name="额定功率",
        aliases=("额定功率", "POWER", "RATED POWER"),
        compare_type="unit",
        ocr_digit_fix=True,
    ),
    "版本号": FieldRule(
        name="版本号",
        aliases=("版本号", "VERSION", "REVISION", "REV"),
        compare_type="version",
        patterns=(r"版本号\s*[:：]?\s*([A-Za-z0-9. _-]{1,20})",),
    ),
    "序列号": FieldRule(
        name="序列号",
        aliases=("序列号", "S/N", "SN", "SERIAL NUMBER", "SERIAL NO", "SERIAL"),
        compare_type="code",
        patterns=(r"\b(?:S/N|SN|SERIAL(?:\s+NO)?)\s*[:：]?\s*([A-Za-z0-9._/-]{3,40})",),
    ),
    "生产者名称": FieldRule(
        name="生产者名称",
        aliases=("生产者名称", "生产商", "制造商", "PRODUCER", "MANUFACTURER"),
        compare_type="text",
        patterns=(r"生产者名称\s*[:：]?\s*([^\n\r]{2,60})",),
    ),
    "规格型号": FieldRule(
        name="规格型号",
        aliases=("规格型号", "型号规格", "MODEL", "MODEL NUMBER", "MODEL NO"),
        compare_type="model",
        required=True,
        patterns=(
            r"规格型号\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{1,50})",
            r"\bModel\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{1,50})",
            r"\bMODEL\s+NUMBER\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9./ _()~-]{1,50})",
        ),
    ),
    "能效等级": FieldRule(
        name="能效等级",
        aliases=("能效等级", "ENERGY CLASS", "ENERGY EFFICIENCY CLASS"),
        compare_type="code",
        ocr_digit_fix=True,
        patterns=(r"([1-5A-G])\s*(?:级|等級|CLASS)",),
    ),
    "耗电量": FieldRule(
        name="耗电量",
        aliases=("耗电量", "耗电量(千瓦时/工作周期)", "ENERGY CONSUMPTION"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"耗电量[^\n\r\d]{0,30}([0-9OISBl.]+)",),
    ),
    "用水量": FieldRule(
        name="用水量",
        aliases=("用水量", "用水量(升/工作周期)", "WATER CONSUMPTION"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"用水量[^\n\r\d]{0,30}([0-9OISBl.]+)",),
    ),
    "洗净比": FieldRule(
        name="洗净比",
        aliases=("洗净比", "WASH RATIO"),
        compare_type="number",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"洗净比\s*([0-9OISBl.]+)",),
    ),
    "洗涤/脱水容量": FieldRule(
        name="洗涤/脱水容量",
        aliases=("洗涤/脱水容量", "洗涤/脱水容量(公斤)"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"洗涤\s*/\s*脱水容量[^\n\r\d]{0,20}([0-9OISBl.]+\s*/\s*[0-9OISBl.]+)",),
    ),
    "依据国家标准": FieldRule(
        name="依据国家标准",
        aliases=("依据国家标准", "国家标准", "执行标准", "STANDARD", "GB"),
        compare_type="code",
        required=True,
        patterns=(r"依据国家标准\s*[:：]?\s*([A-Za-z]{1,4}\s*[0-9.\- ]{5,30})",),
    ),
    "年耗电量": FieldRule(
        name="年耗电量",
        aliases=("年耗电量", "ANNUAL ENERGY CONSUMPTION", "ANNUAL ENERGY CONSUMPTION KWH"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"(?:ANNUAL\s+ENERGY\s+CONSUMPTION|KWH)\D{0,30}([0-9OISBl.]+)\s*(?:KWH|kWh)?",),
    ),
    "年耗水量": FieldRule(
        name="年耗水量",
        aliases=("年耗水量", "ANNUAL WATER CONSUMPTION", "LITER"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"(?:ANNUAL\s+WATER\s+CONSUMPTION|LITER)\D{0,30}([0-9OISBl.]+)\s*(?:LITER|L)?",),
    ),
    "额定容量": FieldRule(
        name="额定容量",
        aliases=("额定容量", "CAPACITY", "Rated Capacity"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"\bCAPACITY\D{0,20}([0-9OISBl.]+)\s*(?:KG|kg)?",),
    ),
    "防水等级": FieldRule(
        name="防水等级",
        aliases=("防水等级", "DEGREE OF WATER-PROOF", "WATER-PROOF", "IP"),
        compare_type="code",
        required=True,
        patterns=(r"Degree\s+of\s+Water[- ]Proof\s*[:：]?\s*([A-Za-z0-9]+)",),
    ),
    "额定频率": FieldRule(
        name="额定频率",
        aliases=("额定频率", "FREQUENCY", "RATED FREQUENCY"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Frequency\s*[:：]?\s*([0-9OISBl.]+\s*Hz)",),
    ),
    "洗涤容量": FieldRule(
        name="洗涤容量",
        aliases=("洗涤容量", "RATED CAPACITY OF WASH", "CAPACITY OF WASH"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Capacity\s+of\s+Wash\s*[:：]?\s*([0-9OISBl.]+\s*kg)",),
    ),
    "脱水容量": FieldRule(
        name="脱水容量",
        aliases=("脱水容量", "RATED CAPACITY OF SPIN", "CAPACITY OF SPIN"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Capacity\s+of\s+Spin\s*[:：]?\s*([0-9OISBl.]+\s*kg)",),
    ),
    "洗涤输入功率": FieldRule(
        name="洗涤输入功率",
        aliases=("洗涤输入功率", "RATED INPUT POWER OF WASH", "INPUT POWER OF WASH"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Input\s+Power\s+of\s+Wash\s*[:：]?\s*([0-9OISBl.]+\s*W)",),
    ),
    "脱水输入功率": FieldRule(
        name="脱水输入功率",
        aliases=("脱水输入功率", "RATED INPUT POWER OF SPIN", "INPUT POWER OF SPIN"),
        compare_type="unit",
        required=True,
        ocr_digit_fix=True,
        patterns=(r"Rated\s+Input\s+Power\s+of\s+Spin\s*[:：]?\s*([0-9OISBl.]+\s*W)",),
    ),
    "制造地": FieldRule(
        name="制造地",
        aliases=("制造地", "MADE IN", "MADE IN CHINA"),
        compare_type="text",
        patterns=(r"MADE\s+IN\s+([A-Za-z ]{2,30})",),
    ),
    "品牌": FieldRule(
        name="品牌",
        aliases=("品牌", "BRAND", "BRAND NAME"),
        compare_type="text",
        patterns=(r"\bBRAND\s+NAME\s*[:：]?\s*([A-Za-z0-9 _-]{2,40})",),
    ),
    "注册号": FieldRule(
        name="注册号",
        aliases=("注册号", "REGISTRATION NO", "REGISTRATION NUMBER"),
        compare_type="code",
        ocr_digit_fix=True,
        patterns=(r"\bREGISTRATION\s+NO\D{0,20}([0-9OISBl Vv.-]{2,30})",),
    ),
    "编码": FieldRule(
        name="编码",
        aliases=("编码", "CODE", "PART NO", "图纸编号"),
        compare_type="code",
        ocr_digit_fix=True,
        patterns=(r"编码\s*[:：]?\s*([0-9OISBl]{5,12})", r"\b(100[0-9OISBl]{5})\b"),
    ),
    "项目名称": FieldRule(
        name="项目名称",
        aliases=("项目名称", "PROJECT NAME"),
        compare_type="text",
        patterns=(r"项目名称\s*[:：]?\s*([^\n\r]{2,40})",),
    ),
    "标签名称": FieldRule(
        name="标签名称",
        aliases=("标签名称", "LABEL", "RATING LABEL", "ENERGY LABEL"),
        compare_type="text",
        patterns=(r"(能效标签\s+LABEL-ENERGY|铭牌\s*RATING\s*LABEL|电器铭牌\s*LABEL-RATING)",),
    ),
}


FIELD_NAMES = list(FIELD_CONFIG)

CANONICAL_EQUIVALENTS = {
    "产品型号": "规格型号",
    "规格型号": "产品型号",
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("：", ":").replace("／", "/").replace("\\", "/")
    text = text.replace("－", "-").replace("—", "-").replace("–", "-")
    text = text.replace("~", "~").replace("～", "~")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", clean_text(value)).upper()


def normalize_field_label(value: Any) -> str:
    text = clean_text(value).upper().strip(" :")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text)
    return text


def fix_ocr_digits(value: str) -> str:
    return value.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"}))


def normalize_value(field_name: str, value: Any) -> str:
    rule = FIELD_CONFIG.get(field_name)
    text = clean_text(value)
    if not text:
        return ""

    if rule and rule.ocr_digit_fix:
        text = fix_ocr_digits(text)

    text = text.upper()
    text = text.replace("ＫＧ", "KG").replace("ＫＷＨ", "KWH")
    text = text.replace("KGS", "KG").replace("KWH/YEAR", "KWH")
    text = re.sub(r"\bLITERS?\b", "L", text)
    text = re.sub(r"\bHZ\b", "HZ", text)
    text = re.sub(r"\s+", "", text)
    text = text.strip(":：")

    if rule and rule.compare_type in {"unit", "number"}:
        text = re.sub(r"(?<=\d)\.0+(?=\D|$)", "", text)

    return text


def field_aliases(field_name: str) -> tuple[str, ...]:
    rule = FIELD_CONFIG.get(field_name)
    return rule.aliases if rule else (field_name,)


def find_matching_field(text: str) -> str | None:
    normalized = normalize_field_label(text)
    if not normalized:
        return None
    for field_name, rule in FIELD_CONFIG.items():
        for alias in rule.aliases:
            alias_norm = normalize_field_label(alias)
            if normalized == alias_norm:
                return field_name
            if "/" in normalized and alias_norm in {part.strip() for part in normalized.split("/") if part.strip()}:
                return field_name
    return None
