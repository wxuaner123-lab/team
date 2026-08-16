from __future__ import annotations

from io import BytesIO
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from comparison import compare_fields
from drawing_parser import extract_drawing_content
from dynamic_field_template import (
    match_label_to_template,
    normalize_template_rows,
    standard_fields_to_template,
    template_to_standard_fields,
)
from energy_label_parser import ENERGY_LABEL_FIELDS
from field_config import FIELD_NAMES, clean_text
from image_quality import evaluate_label_image
from ocr_parser import recognize_label
from product_store import (
    PROJECT_ROOT,
    append_quality_record,
    bindings_for_drawing,
    build_standard_snapshot,
    delete_drawing,
    ensure_storage,
    get_current_drawing_for_product,
    get_product_by_index,
    list_drawings_for_product,
    load_drawings,
    load_products,
    load_quality_records,
    load_qr_bindings,
    lookup_product_and_drawing,
    lookup_product,
    parse_qr_payload,
    product_options,
    register_drawing_pdf,
    resolve_qr_match,
    resolve_project_path,
    save_evidence_image,
    save_uploaded_drawing,
    set_current_drawing,
    template_status_label,
    upsert_qr_binding,
    update_drawing_metadata,
    update_drawing_field_template,
    upsert_product,
)
from qr_parser import decode_qr_image


DEFAULT_REAL_IMAGE_DIR = PROJECT_ROOT / "data" / "实物图" / "data 2"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
ENERGY_STANDARD_FIELDS = ("产品型号", *ENERGY_LABEL_FIELDS)
DEMO_CASES = {
    "样例A：中文能效标签 - 正确标签": {
        "case_id": "demo_cn_pass",
        "pdf": DEFAULT_REAL_IMAGE_DIR / "Sample_001" / "10022178 MINI2.0CC -JW30-77NBCCQDZW 能效标签2023.12.29.pdf",
        "label": DEFAULT_REAL_IMAGE_DIR / "Sample_001" / "label 1.jpg",
        "product_id": "DEMO-CN-ENERGY",
        "product_model": "JW30-77NBCCQDZW",
        "expected": "用于演示中文能效标签自动比对，真实OCR不稳定字段会进入 NEED_REVIEW。",
        "demo_fail": False,
    },
    "样例B：中文能效标签 - 演示错误字段": {
        "case_id": "demo_cn_fail",
        "pdf": DEFAULT_REAL_IMAGE_DIR / "Sample_001" / "10022178 MINI2.0CC -JW30-77NBCCQDZW 能效标签2023.12.29.pdf",
        "label": DEFAULT_REAL_IMAGE_DIR / "Sample_001" / "label 1.jpg",
        "product_id": "DEMO-CN-FAIL",
        "product_model": "JW30-77NBCCQDZW",
        "expected": "用于演示 FAIL。系统会在结果层构造一个演示用错误字段，不影响真实检测逻辑和历史样本。",
        "demo_fail": True,
    },
    "样例C：阿拉伯语/英语标签 - 多语言字段": {
        "case_id": "demo_multilingual",
        "pdf": DEFAULT_REAL_IMAGE_DIR / "Sample_002" / "111.pdf",
        "label": DEFAULT_REAL_IMAGE_DIR / "Sample_002" / "lQDPKdsaCORxlMfND8DNC9Cwvq3En7-S9JAKNnYpyjWFAA_1.jpg",
        "product_id": "DEMO-AR-EN-ENERGY",
        "product_model": "WM1001TMG",
        "expected": "用于演示多语言字段归一化：英文/阿拉伯语字段显示中文名称，同时保留原始字段名。",
        "demo_fail": False,
    },
}


st.set_page_config(
    page_title="制造现场质量确认终端",
    page_icon="✓",
    layout="wide",
)


STATUS_COLOR = {
    "PASS": "#16794c",
    "FAIL": "#b42318",
    "NEED_REVIEW": "#946200",
    "待人工确认": "#946200",
}


def init_session_state() -> None:
    st.session_state.setdefault("operator_name", "operator")
    st.session_state.setdefault("workstation", "Line-A")
    st.session_state.setdefault("last_product_id", "")
    st.session_state.setdefault("last_inspection", None)


def render_header() -> None:
    st.title("现场标签检测")
    st.caption("扫描二维码 -> 匹配图纸库 -> 加载图纸标准字段 -> 拍摄/上传当前标签 -> 字段级比对")
    st.divider()


def render_sidebar() -> str:
    with st.sidebar:
        st.subheader("当前用户")
        st.session_state.operator_name = st.text_input(
            "操作员工号/姓名",
            value=st.session_state.operator_name,
        )
        st.session_state.workstation = st.text_input(
            "工位/产线",
            value=st.session_state.workstation,
        )
        st.divider()
        page = st.radio(
            "功能",
            [
                "演示模式",
                "现场检测端",
                "试运行验收",
                "字段模板确认",
                "图纸库管理",
                "后台管理",
                "检测记录",
                "实物图验证",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"数据目录：{PROJECT_ROOT / 'master_data'}")
    return page


def result_badge(result: str) -> None:
    color = STATUS_COLOR.get(result, "#475467")
    st.markdown(
        f"""
        <div style="
            border-left: 8px solid {color};
            background: #ffffff;
            padding: 18px 22px;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(16,24,40,.08);
            margin: 8px 0 18px;
        ">
            <div style="font-size: 14px; color: #667085;">检测结果</div>
            <div style="font-size: 42px; font-weight: 800; color: {color}; line-height: 1.15;">{result}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def comparison_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    visible_columns = [
        "中文字段名",
        "原始字段名",
        "field_key",
        "图纸值",
        "标签值",
        "检测结果",
        "映射状态",
        "异常说明",
        "置信度",
        "OCR候选值",
        "字段匹配说明",
    ]
    dataframe = pd.DataFrame(rows)
    for column in visible_columns:
        if column not in dataframe.columns:
            dataframe[column] = ""
    return dataframe[visible_columns]


def style_result_rows(dataframe: pd.DataFrame):
    def highlight(row):
        result = row.get("检测结果", "")
        if result == "PASS":
            return ["background-color: #ecfdf3; color: #067647;" for _ in row]
        if result == "FAIL":
            return ["background-color: #fef3f2; color: #b42318; font-weight: 700;" for _ in row]
        if result == "NEED_REVIEW":
            return ["background-color: #fffaeb; color: #946200;" for _ in row]
        return ["background-color: #fffaeb; color: #946200;" for _ in row]

    return dataframe.style.apply(highlight, axis=1)


def enrich_comparison_rows_with_template(
    rows: list[dict[str, Any]],
    template: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    template_by_key = {
        clean_text(item.get("field_key", "")) or clean_text(item.get("field_id", "")): item
        for item in template
        if clean_text(item.get("field_key", "")) or clean_text(item.get("field_id", ""))
    }
    template_by_display = {
        clean_text(item.get("display_name_zh", "")): item
        for item in template
        if clean_text(item.get("display_name_zh", ""))
    }
    enriched: list[dict[str, Any]] = []
    for row in rows:
        row_key = clean_text(row.get("字段名称", ""))
        item = template_by_key.get(row_key) or template_by_display.get(row_key, {})
        display_name = clean_text(item.get("display_name_zh", "")) or row_key
        mapping_status = clean_text(item.get("mapping_status", ""))
        enriched.append(
            {
                **row,
                "中文字段名": display_name,
                "field_key": clean_text(item.get("field_key", "")) or row_key,
                "原始字段名": item.get("source_field_name", ""),
                "语言": item.get("source_language", ""),
                "映射状态": mapping_status,
                "映射置信度": item.get("mapping_confidence", ""),
                "模板置信度": item.get("confidence", ""),
            }
        )
        template_confidence = float(item.get("confidence", 1) or 0)
        mapping_confidence = float(item.get("mapping_confidence", 1) or 0)
        if (
            item.get("needs_review")
            or template_confidence < 0.55
            or mapping_status == "NEED_REVIEW"
            or mapping_confidence < 0.55
        ):
            enriched[-1]["检测结果"] = "NEED_REVIEW"
            enriched[-1]["异常说明"] = "图纸字段模板或字段语义映射置信度低，需要人工确认。"
    return enriched


def overall_from_rows(rows: list[dict[str, Any]]) -> str:
    if any(row.get("检测结果") == "FAIL" for row in rows):
        return "FAIL"
    if any(row.get("检测结果") == "NEED_REVIEW" for row in rows):
        return "NEED_REVIEW"
    return "PASS"


def result_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "pass": sum(1 for row in rows if row.get("检测结果") == "PASS"),
        "fail": sum(1 for row in rows if row.get("检测结果") == "FAIL"),
        "review": sum(1 for row in rows if row.get("检测结果") == "NEED_REVIEW"),
    }


def render_result_overview(result: str, rows: list[dict[str, Any]], elapsed_seconds: float) -> None:
    counts = result_counts(rows)
    result_badge(result)
    cols = st.columns(5)
    cols[0].metric("检测字段数", counts["total"])
    cols[1].metric("通过字段数", counts["pass"])
    cols[2].metric("异常字段数", counts["fail"])
    cols[3].metric("需确认字段数", counts["review"])
    cols[4].metric("检测耗时", f"{elapsed_seconds:.1f}s")


def quality_status_text(status: str) -> str:
    return {
        "PASS": "图片可用",
        "WARNING": "存在质量风险",
        "FAIL": "建议重新拍摄",
    }.get(clean_text(status), clean_text(status) or "-")


def qr_type_text(qr_type: str) -> str:
    return {
        "product_qr": "产品二维码",
        "drawing_qr": "图纸二维码",
        "label_url_qr": "标签/平台链接二维码",
        "unknown_qr": "未知二维码",
    }.get(clean_text(qr_type), clean_text(qr_type) or "-")


def match_status_text(status: str) -> str:
    return {
        "matched_drawing": "已匹配图纸",
        "matched_product_no_drawing": "已匹配产品，但未绑定图纸",
        "matched_product_with_drawings": "已匹配产品，可选择图纸版本",
        "label_url_only": "标签/平台链接，不直接匹配图纸",
        "unknown": "未知二维码，需要人工确认",
        "no_match": "未找到产品或图纸",
    }.get(clean_text(status), clean_text(status) or "-")


def qr_record_payload(qr_match: dict[str, Any] | None) -> dict[str, Any]:
    qr_match = qr_match or {}
    qr_result = qr_match.get("qr_result", {})
    return {
        "raw_text": qr_result.get("raw_text", ""),
        "qr_type": qr_result.get("qr_type", ""),
        "match_status": qr_match.get("match_status", ""),
        "matched_product_id": qr_match.get("matched_product_id", ""),
        "matched_drawing_id": qr_match.get("matched_drawing_id", ""),
        "match_reason": qr_match.get("match_reason", ""),
        "is_manual_binding": bool(qr_match.get("is_manual_binding", False)),
    }


def render_qr_match_summary(qr_match: dict[str, Any]) -> None:
    qr_result = qr_match.get("qr_result", {})
    parsed = qr_result.get("parsed_fields", {})
    st.markdown("**二维码解析结果**")
    rows = [
        {
            "二维码原文": qr_result.get("raw_text", ""),
            "二维码类型": qr_type_text(qr_result.get("qr_type", "")),
            "解析出的产品ID": parsed.get("product_id", ""),
            "解析出的图纸ID": parsed.get("drawing_id", ""),
            "匹配状态": match_status_text(qr_match.get("match_status", "")),
            "匹配原因": qr_match.get("match_reason", ""),
        }
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    status = clean_text(qr_match.get("match_status", ""))
    if status == "matched_drawing":
        st.success("已匹配图纸，可继续检测。")
    elif status == "matched_product_with_drawings":
        st.info("已匹配产品，该产品存在多张图纸，请确认本次使用的图纸版本。")
    elif status == "matched_product_no_drawing":
        st.warning("当前产品尚未绑定图纸，请上传新图纸或绑定已有图纸。")
    elif status == "label_url_only":
        st.warning("当前二维码像是标签/平台链接，不建议直接作为产品ID使用。")
    else:
        st.warning("未找到该二维码对应的产品或图纸，请上传图纸或人工绑定。")


def quality_result_summary(quality: dict[str, Any] | None) -> dict[str, Any]:
    quality = quality or {}
    return {
        "quality_status": quality.get("quality_status", quality.get("status", "")),
        "quality_score": quality.get("quality_score", quality.get("score", 0)),
        "blur_score": quality.get("blur_score", quality.get("metrics", {}).get("sharpness", "")),
        "blur_status": quality.get("blur_status", ""),
        "brightness_score": quality.get("brightness_score", quality.get("metrics", {}).get("brightness", "")),
        "brightness_status": quality.get("brightness_status", ""),
        "overexposure_score": quality.get("overexposure_score", quality.get("metrics", {}).get("glare_ratio", "")),
        "overexposure_status": quality.get("overexposure_status", ""),
        "image_width": quality.get("image_width", ""),
        "image_height": quality.get("image_height", ""),
        "resolution_status": quality.get("resolution_status", ""),
        "label_area_score": quality.get("label_area_score", ""),
        "label_area_status": quality.get("label_area_status", ""),
        "quality_messages": quality.get("quality_messages", quality.get("warnings", [])),
    }


def quality_dataframe(quality: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"检查项": "清晰度", "状态": quality.get("blur_status", ""), "评分/数值": quality.get("blur_score", ""), "建议": quality.get("blur_message", "")},
            {"检查项": "亮度", "状态": quality.get("brightness_status", ""), "评分/数值": quality.get("brightness_score", ""), "建议": quality.get("brightness_message", "")},
            {"检查项": "反光/过曝风险", "状态": quality.get("overexposure_status", ""), "评分/数值": quality.get("overexposure_score", ""), "建议": quality.get("overexposure_message", "")},
            {"检查项": "分辨率", "状态": quality.get("resolution_status", ""), "评分/数值": f"{quality.get('image_width', '')} x {quality.get('image_height', '')}", "建议": quality.get("resolution_message", "")},
            {"检查项": "标签占比", "状态": quality.get("label_area_status", ""), "评分/数值": quality.get("label_area_score", ""), "建议": quality.get("label_area_message", "")},
        ]
    )


def render_quality_gate(quality: dict[str, Any], key_prefix: str = "quality_gate") -> bool:
    status = clean_text(quality.get("quality_status", quality.get("status", "")))
    score = quality.get("quality_score", quality.get("score", 0))
    st.markdown("**图片质量检查结果**")
    cols = st.columns(7)
    cols[0].metric("总体质量", quality_status_text(status))
    cols[1].metric("质量评分", f"{score} / 100")
    cols[2].metric("清晰度", quality.get("blur_status", "-"))
    cols[3].metric("亮度", quality.get("brightness_status", "-"))
    cols[4].metric("反光/过曝", quality.get("overexposure_status", "-"))
    cols[5].metric("分辨率", quality.get("resolution_status", "-"))
    cols[6].metric("标签占比", quality.get("label_area_status", "-"))
    st.dataframe(quality_dataframe(quality), width="stretch", hide_index=True)

    messages = quality.get("quality_messages", quality.get("warnings", []))
    if status == "FAIL":
        st.error("当前标签图片质量不满足检测要求，建议重新拍摄。")
        for message in messages:
            st.warning(message)
        return st.checkbox(
            "仍然继续检测（试运行/调试，结果可能不稳定）",
            value=False,
            key=f"{key_prefix}_override",
        )
    if status == "WARNING":
        st.warning("当前图片存在质量风险，检测结果可能需要人工确认。")
        for message in messages:
            st.warning(message)
        return True
    st.success("图片可用，可以继续检测。")
    return True


def render_quality_result_notice(quality: dict[str, Any] | None) -> None:
    quality = quality or {}
    status = clean_text(quality.get("quality_status", quality.get("status", "")))
    if status == "WARNING":
        st.warning("字段比对已完成，但图片质量存在风险，建议人工复核。")
    elif status == "FAIL":
        st.error("本次检测是在图片质量不满足要求的情况下继续执行，结果仅供试运行/调试参考。")


def demo_result_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    dataframe = comparison_dataframe(rows).rename(
        columns={
            "图纸值": "图纸标准值",
            "标签值": "标签识别值",
            "检测结果": "状态",
            "异常说明": "原因",
        }
    )
    visible_columns = ["中文字段名", "原始字段名", "图纸标准值", "标签识别值", "状态", "原因"]
    for column in visible_columns:
        if column not in dataframe.columns:
            dataframe[column] = ""
    return dataframe[visible_columns]


def style_demo_result_rows(dataframe: pd.DataFrame):
    def highlight(row):
        result = row.get("状态", "")
        if result == "PASS":
            return ["background-color: #ecfdf3; color: #067647;" for _ in row]
        if result == "FAIL":
            return ["background-color: #fef3f2; color: #b42318; font-weight: 700;" for _ in row]
        if result == "NEED_REVIEW":
            return ["background-color: #fffaeb; color: #946200;" for _ in row]
        return ["" for _ in row]

    return dataframe.style.apply(highlight, axis=1)


def report_csv_bytes(record: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    report_rows: list[dict[str, Any]] = [
        {"项目": "报告标题", "内容": "图纸标签自动比对系统演示检测报告"},
        {"项目": "检测时间", "内容": record.get("created_at", "")},
        {"项目": "图纸名称", "内容": record.get("drawing_pdf", "")},
        {"项目": "产品ID", "内容": record.get("product_id", "")},
        {"项目": "标签图片名称", "内容": record.get("label_image_name", "")},
        {"项目": "总结论", "内容": record.get("result", "")},
        {"项目": "图片质量状态", "内容": quality_status_text((record.get("quality_result") or {}).get("quality_status", ""))},
        {"项目": "图片质量分数", "内容": (record.get("quality_result") or {}).get("quality_score", "")},
        {"项目": "NEED_REVIEW字段", "内容": "、".join(record.get("unknown_fields", []))},
        {
            "项目": "当前系统限制说明",
            "内容": "当前版本适合内部演示和小范围现场试用，不建议直接替代人工全检；NEED_REVIEW表示需要人工确认。",
        },
        {"项目": "", "内容": ""},
    ]
    summary_df = pd.DataFrame(report_rows)
    detail_df = demo_result_dataframe(rows)
    output = BytesIO()
    output.write(summary_df.to_csv(index=False).encode("utf-8-sig"))
    output.write("\n字段级结果\n".encode("utf-8-sig"))
    output.write(detail_df.to_csv(index=False).encode("utf-8-sig"))
    return output.getvalue()


def display_product_card(product: dict[str, Any], qr_payload: dict[str, str]) -> None:
    left, middle, right = st.columns(3)
    left.metric("产品ID", product.get("product_id", "-"))
    middle.metric("产品型号", product.get("product_model", "-"))
    right.metric("产品版本", product.get("version", "-"))

    batch_info = {
        "SN": qr_payload.get("sn") or qr_payload.get("serial") or "-",
        "批次": qr_payload.get("batch") or qr_payload.get("batch_no") or "-",
        "二维码内容": qr_payload.get("raw") or "",
    }
    st.dataframe(
        pd.DataFrame([batch_info]),
        width="stretch",
        hide_index=True,
    )


def display_drawing_card(drawing: dict[str, Any] | None) -> None:
    if not drawing:
        st.warning("当前产品没有匹配到PDF图纸。")
        return
    cols = st.columns(4)
    cols[0].metric("图纸ID", drawing.get("drawing_id", "-"))
    cols[1].metric("图纸版本", drawing.get("version", "-"))
    cols[2].metric("PDF二维码", drawing.get("qr_code", "-"))
    cols[3].metric("字段数", len([v for v in drawing.get("standard_fields", {}).values() if clean_text(v)]))
    st.caption(f"PDF文件：{drawing.get('pdf_name', '')}")


def render_unmatched_qr_upload(qr_text: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    st.error("未找到对应图纸。")
    action = st.radio(
        "请选择下一步",
        ["上传新图纸", "重新扫描二维码", "取消"],
        horizontal=True,
    )
    if action == "重新扫描二维码":
        st.info("请重新拍摄/上传二维码图，或修改手动输入内容。")
        return None, None
    if action == "取消":
        st.stop()

    st.markdown("**上传新图纸并建立绑定关系**")
    uploaded_pdf = st.file_uploader(
        "选择PDF图纸",
        type=["pdf"],
        key="unmatched_qr_pdf_upload",
    )
    cols = st.columns(3)
    fallback_product_id = qr_text or "UNKNOWN-PRODUCT"
    product_id = cols[0].text_input("产品ID", value=fallback_product_id)
    product_model = cols[1].text_input("产品型号", value=product_id)
    version = cols[2].text_input("图纸版本", value="V1.0")

    if uploaded_pdf is not None and st.button("保存图纸并进入检测", type="primary", width="stretch"):
        with st.spinner("正在保存PDF、识别PDF二维码并解析标准字段..."):
            registration = register_drawing_pdf(
                pdf_bytes=uploaded_pdf.getvalue(),
                pdf_name=uploaded_pdf.name,
                qr_text=qr_text,
                product_id=product_id,
                product_model=product_model,
                version=version,
                make_current=True,
            )
        st.success("图纸已加入图纸库，后续扫描该二维码可自动匹配。")
        st.session_state["last_registered_drawing"] = registration
        return registration["product"], registration["drawing"]

    return None, None


def render_qr_binding_actions(qr_text: str, qr_match: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    qr_result = qr_match.get("qr_result", {})
    action = st.radio(
        "请选择下一步",
        ["绑定已有图纸", "上传新图纸并绑定", "手动输入产品ID", "重新扫描"],
        horizontal=True,
        key="qr_binding_action",
    )
    if action == "重新扫描":
        st.info("请重新拍摄/上传二维码图，或修改手动输入内容。")
        return None, None, None

    if action == "绑定已有图纸":
        drawings = load_drawings()
        if not drawings:
            st.warning("当前图纸库为空，请选择上传新图纸并绑定。")
            return None, None, None
        options = [
            f"{drawing.get('drawing_id')} / {drawing.get('product_id')} / {drawing.get('pdf_name')} / {drawing.get('version')}"
            for drawing in drawings
        ]
        selected_index = st.selectbox("选择要绑定的图纸", range(len(options)), format_func=lambda index: options[index])
        selected_drawing = drawings[selected_index]
        product_id = st.text_input(
            "绑定产品ID",
            value=selected_drawing.get("product_id", "") or qr_result.get("parsed_fields", {}).get("product_id", ""),
        )
        note = st.text_input("备注", value="现场人工绑定")
        if st.button("保存二维码绑定", type="primary", width="stretch"):
            binding = upsert_qr_binding(
                qr_text=qr_text,
                qr_type=qr_result.get("qr_type", "unknown_qr"),
                product_id=product_id,
                drawing_id=selected_drawing.get("drawing_id", ""),
                model=selected_drawing.get("product_model", ""),
                created_by=st.session_state.operator_name or "demo_user",
                note=note,
            )
            updated_match = resolve_qr_match(qr_text)
            st.success("二维码绑定已保存，下次扫描将自动匹配。")
            return updated_match.get("product"), updated_match.get("drawing"), updated_match
        return None, None, None

    if action == "上传新图纸并绑定":
        uploaded_pdf = st.file_uploader("选择PDF图纸", type=["pdf"], key="qr_bind_pdf_upload")
        cols = st.columns(3)
        fallback_product_id = qr_result.get("parsed_fields", {}).get("product_id") or "UNKNOWN-PRODUCT"
        product_id = cols[0].text_input("产品ID", value=fallback_product_id, key="qr_bind_product_id")
        product_model = cols[1].text_input("产品型号", value=qr_result.get("parsed_fields", {}).get("model") or product_id, key="qr_bind_product_model")
        version = cols[2].text_input("图纸版本", value="V1.0", key="qr_bind_version")
        if uploaded_pdf is not None and st.button("上传图纸并保存绑定", type="primary", width="stretch"):
            registration = register_drawing_pdf(
                pdf_bytes=uploaded_pdf.getvalue(),
                pdf_name=uploaded_pdf.name,
                qr_text=qr_text if qr_result.get("qr_type") != "label_url_qr" else "",
                product_id=product_id,
                product_model=product_model,
                version=version,
                make_current=True,
            )
            drawing = registration["drawing"]
            upsert_qr_binding(
                qr_text=qr_text,
                qr_type=qr_result.get("qr_type", "unknown_qr"),
                product_id=product_id,
                drawing_id=drawing.get("drawing_id", ""),
                model=product_model,
                created_by=st.session_state.operator_name or "demo_user",
                note="上传新图纸时建立绑定",
            )
            updated_match = resolve_qr_match(qr_text)
            st.success("图纸已入库，二维码绑定已保存。")
            return updated_match.get("product"), updated_match.get("drawing"), updated_match
        return None, None, None

    product_id = st.text_input("手动输入产品ID", value=qr_result.get("parsed_fields", {}).get("product_id", ""))
    if st.button("按产品ID查找", width="stretch"):
        product = lookup_product(product_id)[0] if product_id else None
        drawing = get_current_drawing_for_product(product.get("product_id", "")) if product else None
        if product:
            upsert_qr_binding(
                qr_text=qr_text,
                qr_type=qr_result.get("qr_type", "unknown_qr"),
                product_id=product.get("product_id", ""),
                drawing_id=(drawing or {}).get("drawing_id", ""),
                model=product.get("product_model", ""),
                created_by=st.session_state.operator_name or "demo_user",
                note="手动输入产品ID绑定",
            )
            updated_match = resolve_qr_match(qr_text)
            st.success("已按产品ID保存二维码绑定。")
            return updated_match.get("product"), updated_match.get("drawing"), updated_match
        st.error("未找到该产品ID。")
    return None, None, None


def get_product_from_scan() -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, str], str, dict[str, Any] | None]:
    st.subheader("1. 扫描 / 输入二维码")
    qr_tabs = st.tabs(["相机扫描", "上传二维码图", "手动输入"])
    qr_text = ""

    with qr_tabs[0]:
        qr_camera_file = st.camera_input(
            "使用iPad摄像头扫描产品二维码",
            key="product_qr_camera",
        )
        if qr_camera_file is not None:
            qr_result = decode_qr_image(qr_camera_file.getvalue())
            if qr_result["success"]:
                qr_text = qr_result["text"]
                st.success(qr_result["message"])
                st.code(qr_text)
            else:
                st.warning(qr_result["message"])

    with qr_tabs[1]:
        qr_upload_file = st.file_uploader(
            "上传二维码图片",
            type=["jpg", "jpeg", "png"],
            key="product_qr_upload",
        )
        if qr_upload_file is not None and not qr_text:
            qr_result = decode_qr_image(qr_upload_file.getvalue())
            if qr_result["success"]:
                qr_text = qr_result["text"]
                st.success(qr_result["message"])
                st.code(qr_text)
            else:
                st.warning(qr_result["message"])

    with qr_tabs[2]:
        manual_qr_text = st.text_area(
            "二维码内容",
            placeholder="示例：PID=ABC-001;MODEL=ABC-001;SN=SN20260803001;BATCH=B20260803",
            height=90,
        )
        if manual_qr_text and not qr_text:
            qr_text = manual_qr_text

    st.caption(
        "演示二维码内容：ICM-2400-A-V1.2 或 PID=ICM-2400-A;MODEL=ICM-2400-A;SN=ICM2400A-260701;BATCH=DEMO-BATCH"
    )

    qr_match = resolve_qr_match(qr_text) if qr_text else None
    product = qr_match.get("product") if qr_match else None
    drawing = qr_match.get("drawing") if qr_match else None
    qr_payload = qr_match.get("qr_payload", {}) if qr_match else {}

    if qr_match:
        render_qr_match_summary(qr_match)
        if qr_match.get("match_status") == "matched_product_with_drawings":
            drawings = qr_match.get("drawings", [])
            drawing_labels = [
                f"{item.get('drawing_id')} / {item.get('version')} / {item.get('pdf_name')}"
                for item in drawings
            ]
            selected_drawing_index = st.selectbox(
                "选择本次检测图纸版本",
                range(len(drawing_labels)),
                format_func=lambda index: drawing_labels[index],
            )
            drawing = drawings[selected_drawing_index]
            qr_match["drawing"] = drawing
            qr_match["matched_drawing_id"] = drawing.get("drawing_id", "")
            qr_match["match_status"] = "matched_drawing"
            qr_match["match_reason"] = "用户从产品图纸列表中选择本次检测图纸。"

    options = product_options()
    selected_label = ""
    if qr_text and (not product or not drawing):
        registered_product, registered_drawing, updated_match = render_qr_binding_actions(qr_text, qr_match or {})
        if registered_product and registered_drawing:
            product = registered_product
            drawing = registered_drawing
            qr_match = updated_match
    elif not product and options:
        selected_index = st.selectbox(
            "未扫码时，可手动选择产品用于测试",
            range(len(options)),
            format_func=lambda index: options[index],
        )
        product = get_product_by_index(selected_index)
        drawing = get_current_drawing_for_product(product.get("product_id", "")) if product else None
        selected_label = options[selected_index]

    if product:
        st.subheader("2. 匹配图纸库")
        st.success("标准数据已加载")
        display_product_card(product, qr_payload or parse_qr_payload(qr_text))
        display_drawing_card(drawing)
    else:
        st.warning("请先扫描二维码，或在后台添加产品标准数据。")

    return product, drawing, qr_payload, selected_label, qr_match


def is_energy_label_standard(fields: dict[str, Any]) -> bool:
    hits = sum(1 for field_name in ENERGY_LABEL_FIELDS if clean_text(fields.get(field_name, "")))
    return hits >= 3


def filter_energy_label_standard_fields(fields: dict[str, Any]) -> dict[str, str]:
    return {
        field_name: clean_text(fields.get(field_name, ""))
        for field_name in ENERGY_STANDARD_FIELDS
        if clean_text(fields.get(field_name, ""))
    }


def drawing_field_template(drawing: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not drawing:
        return []
    template = drawing.get("field_template")
    if isinstance(template, list) and template:
        return template
    drawing_path = resolve_project_path(clean_text(drawing.get("pdf_path", "")))
    if drawing_path and drawing_path.exists():
        try:
            content = extract_drawing_content(drawing_path)
            parsed_template = content.get("field_template", [])
            if parsed_template:
                return parsed_template
        except Exception:
            pass
    return []


def drawing_field_template_source(drawing: dict[str, Any] | None) -> str:
    if not drawing:
        return "无图纸"
    template = drawing.get("field_template")
    if isinstance(template, list) and template:
        return "drawing.field_template"
    drawing_path = resolve_project_path(clean_text(drawing.get("pdf_path", "")))
    if drawing_path and drawing_path.exists():
        try:
            content = extract_drawing_content(drawing_path)
            if content.get("field_template"):
                return "当前PDF解析生成"
        except Exception:
            return "当前PDF解析失败"
    return "空模板"


def load_product_drawing_fields(
    product: dict[str, Any],
    drawing: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    if drawing:
        template = drawing_field_template(drawing)
        if template:
            return template_to_standard_fields(template), [
                f"已加载图纸动态字段模板：{drawing.get('pdf_name', '')}",
                f"图纸版本：{drawing.get('version', '-')}",
            ]
        warnings = [
            f"已匹配图纸库：{drawing.get('pdf_name', '')}",
            f"图纸版本：{drawing.get('version', '-')}",
            "当前图纸字段模板为空或需要人工确认。主检测流程不会使用固定字段列表凑数。",
        ]
        if drawing.get("qr_code"):
            warnings.append(f"PDF二维码：{drawing.get('qr_code')}")

        drawing_path = resolve_project_path(clean_text(drawing.get("pdf_path", "")))
        if drawing_path and drawing_path.exists():
            try:
                drawing_content = extract_drawing_content(drawing_path)
                warnings.extend(list(drawing_content.get("warnings", [])))
                warnings.append(f"图纸解析模式：{drawing_content.get('parse_mode', '-')}")
                parsed_template = drawing_content.get("field_template", [])
                if parsed_template:
                    return template_to_standard_fields(parsed_template), warnings
                return {}, warnings
            except Exception as error:
                return {}, [*warnings, f"图纸解析失败：{error}"]

    return {}, ["当前未匹配到图纸字段模板。主检测流程不会使用产品固定字段列表。"]


def render_standard_snapshot(
    product: dict[str, Any],
    drawing: dict[str, Any] | None = None,
) -> dict[str, str]:
    st.subheader("3. 加载当前图纸字段模板")
    drawing_fields, warnings = load_product_drawing_fields(product, drawing)
    standard_snapshot = (
        {
            field_name: value
            for field_name, value in drawing_fields.items()
            if clean_text(value)
        }
        if drawing
        else build_standard_snapshot(product, drawing_fields)
    )

    for warning in warnings:
        st.info(warning)
    render_template_status_notice(drawing)

    if not standard_snapshot:
        st.warning("该图纸字段模板为空或需要人工确认。请先在图纸库重新生成模板或后续进入字段模板编辑。")
    else:
        template = drawing_field_template(drawing)
        snapshot_rows = (
            [
                {
                    "中文字段名": item.get("display_name_zh", ""),
                    "原始字段名": item.get("source_field_name", ""),
                    "语言": item.get("source_language", ""),
                    "标准值": item.get("standard_value", ""),
                    "单位": item.get("unit", ""),
                    "映射状态": item.get("mapping_status", ""),
                    "映射置信度": item.get("mapping_confidence", ""),
                    "置信度": item.get("confidence", ""),
                }
                for item in template
                if clean_text(item.get("standard_value", ""))
            ]
            if template
            else [
                {"中文字段名": field_name, "原始字段名": field_name, "标准值": value}
                for field_name, value in standard_snapshot.items()
            ]
        )
        st.dataframe(
            pd.DataFrame(snapshot_rows),
            width="stretch",
            hide_index=True,
        )
    render_field_source_debug(product, drawing, standard_snapshot)
    render_multilingual_mapping_debug(drawing)
    return standard_snapshot


def render_field_source_debug(
    product: dict[str, Any],
    drawing: dict[str, Any] | None,
    standard_snapshot: dict[str, str],
) -> None:
    template = drawing_field_template(drawing)
    using_fixed_fields = False
    with st.expander("字段来源调试信息"):
        debug_info = {
            "当前 product_id": product.get("product_id", ""),
            "当前 drawing_id": drawing.get("drawing_id", "") if drawing else "",
            "当前 pdf_path": drawing.get("pdf_path", "") if drawing else "",
            "是否找到图纸字段模板": bool(template),
            "字段模板来源": drawing_field_template_source(drawing),
            "字段数量": len(template),
            "是否仍然使用了固定字段列表": using_fixed_fields,
        }
        st.json(debug_info)
        if using_fixed_fields:
            st.warning("WARNING：当前流程仍使用固定字段，请检查。")
        if template:
            st.dataframe(field_template_dataframe(template), width="stretch", hide_index=True)
        else:
            st.info("字段模板为空。当前主流程不会使用固定字段列表凑数。")


def mapping_debug_dataframe(template: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "原始字段名": item.get("source_field_name", ""),
                "检测语言": item.get("source_language", ""),
                "标准化文本": item.get("normalized_field_name", ""),
                "命中词库项": item.get("matched_alias", ""),
                "field_key": item.get("field_key", ""),
                "中文显示名": item.get("display_name_zh", ""),
                "映射置信度": item.get("mapping_confidence", ""),
                "映射状态": item.get("mapping_status", ""),
                "标准值": item.get("standard_value", ""),
                "字段模板置信度": item.get("confidence", ""),
                "判定说明": item.get("match_reason", ""),
            }
            for item in template
        ]
    )


def render_multilingual_mapping_debug(drawing: dict[str, Any] | None) -> None:
    template = drawing_field_template(drawing)
    with st.expander("多语言字段映射调试信息"):
        if not template:
            st.info("当前没有可展示的图纸动态字段模板。")
            return
        debug_df = mapping_debug_dataframe(template)
        st.dataframe(debug_df, width="stretch", hide_index=True)
        unmatched = debug_df[debug_df["映射状态"] == "NEED_REVIEW"] if "映射状态" in debug_df else pd.DataFrame()
        if not unmatched.empty:
            st.warning("以下字段未能稳定映射到语义字段，将进入 NEED_REVIEW：")
            st.dataframe(unmatched, width="stretch", hide_index=True)
        else:
            st.success("图纸字段均已完成本地词典或模糊匹配映射。")


def get_label_image_bytes() -> tuple[bytes | None, str, dict[str, Any], bool]:
    st.subheader("4. 拍摄 / 上传当前标签")
    label_tabs = st.tabs(["马上拍照", "上传图片"])
    selected_file = None

    with label_tabs[0]:
        camera_file = st.camera_input(
            "使用iPad摄像头马上拍摄产品标签",
            key="label_camera_now",
        )
        if camera_file is not None:
            selected_file = camera_file
            st.success("已获取现场拍照图片。")

    with label_tabs[1]:
        uploaded_file = st.file_uploader(
            "上传已有标签图片进行测试",
            type=["jpg", "jpeg", "png"],
            key="label_image_upload",
        )
        if selected_file is None and uploaded_file is not None:
            selected_file = uploaded_file
            st.success("已获取上传图片。")

    if selected_file is None:
        return None, "", {}, False

    image_bytes = selected_file.getvalue()
    filename = getattr(selected_file, "name", "camera_label.png") or "camera_label.png"
    quality = evaluate_label_image(image_bytes)
    can_continue = render_quality_gate(quality, key_prefix="inspection_quality")

    return image_bytes, filename, quality, can_continue


def build_inspection_record(
    product: dict[str, Any],
    drawing: dict[str, Any] | None,
    qr_payload: dict[str, str],
    standard_snapshot: dict[str, str],
    label_result: dict[str, Any],
    comparison_rows: list[dict[str, Any]],
    overall_result: str,
    evidence_path: str,
    qr_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fail_fields = [
        row["字段名称"]
        for row in comparison_rows
        if row.get("检测结果") == "FAIL"
    ]
    unknown_fields = [
        row["字段名称"]
        for row in comparison_rows
        if row.get("检测结果") == "NEED_REVIEW"
    ]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "operator": st.session_state.operator_name,
        "workstation": st.session_state.workstation,
        "product_id": product.get("product_id", ""),
        "product_model": product.get("product_model", ""),
        "product_version": product.get("version", ""),
        "drawing_id": drawing.get("drawing_id", "") if drawing else "",
        "drawing_version": drawing.get("version", "") if drawing else "",
        "drawing_qr_code": drawing.get("qr_code", "") if drawing else "",
        "drawing_pdf": drawing.get("pdf_path", "") if drawing else product.get("drawing_file", ""),
        "template_status": drawing.get("template_status", "") if drawing else "",
        "template_status_label": template_status_label(drawing.get("template_status", "")) if drawing else "",
        "template_confirmed_time": drawing.get("template_confirmed_at", "") if drawing else "",
        "template_confirmed_by": drawing.get("template_confirmed_by", "") if drawing else "",
        "template_version": drawing.get("template_version", "") if drawing else "",
        "template_updated_at": drawing.get("template_updated_at", "") if drawing else "",
        "sn": qr_payload.get("sn") or qr_payload.get("serial") or "",
        "batch_no": qr_payload.get("batch") or qr_payload.get("batch_no") or "",
        "qr_payload": qr_payload,
        "qr_result": qr_record_payload(qr_match),
        "result": overall_result,
        "fail_fields": fail_fields,
        "unknown_fields": unknown_fields,
        "standard_snapshot": standard_snapshot,
        "field_template": drawing_field_template(drawing),
        "drawing_ocr_text": drawing.get("drawing_ocr_text", "") if drawing else "",
        "label_fields": label_result.get("fields", {}),
        "comparison_rows": comparison_rows,
        "ocr_confidence": label_result.get("confidence", 0),
        "ocr_text": label_result.get("raw_text", ""),
        "ocr_rows": label_result.get("ocr_rows", []),
        "ocr_warnings": label_result.get("warnings", []),
        "field_match_debug": label_result.get("field_match_debug", {}),
        "selected_preprocess": label_result.get("selected_preprocess", ""),
        "evidence_image": evidence_path,
    }


def apply_demo_fail_override(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    preferred_keys = {"model_number", "规格型号", "产品型号", "型号"}
    target_index = next(
        (
            index
            for index, row in enumerate(rows)
            if clean_text(row.get("field_key", "")) in preferred_keys
            or clean_text(row.get("字段名称", "")) in preferred_keys
        ),
        0,
    )
    updated_rows = [dict(row) for row in rows]
    target = updated_rows[target_index]
    target["标签值"] = "DEMO-WRONG-VALUE"
    target["检测结果"] = "FAIL"
    target["异常说明"] = "演示用错误字段：此差异仅用于客户演示 FAIL 状态，不写入真实检测逻辑。"
    target["字段匹配说明"] = "Demo case injected mismatch"
    return updated_rows


def run_demo_detection(
    case: dict[str, Any],
    label_bytes: bytes,
    label_name: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    drawing_content = extract_drawing_content(case["pdf"])
    template = drawing_content.get("field_template", [])
    standard_snapshot = template_to_standard_fields(template)
    quality = evaluate_label_image(label_bytes)
    label_result = recognize_label(
        label_bytes,
        confidence_threshold=0.30,
        debug_output_dir=None,
        file_stem=f"{case['case_id']}_{datetime.now().strftime('%H%M%S')}",
    )
    if template:
        label_fields_for_compare, dynamic_debug = match_label_to_template(
            template,
            label_result.get("raw_text", ""),
            label_result.get("ocr_rows", []),
        )
        label_result["fields"] = {
            **label_result.get("fields", {}),
            **label_fields_for_compare,
        }
        label_result["field_match_debug"] = {
            **label_result.get("field_match_debug", {}),
            **dynamic_debug,
        }
    else:
        label_fields_for_compare = {}

    if template and standard_snapshot:
        comparison_rows, overall_result = compare_fields(
            standard_snapshot,
            label_fields_for_compare,
            label_result.get("field_match_debug", {}),
        )
        comparison_rows = enrich_comparison_rows_with_template(comparison_rows, template)
        if case.get("demo_fail"):
            comparison_rows = apply_demo_fail_override(comparison_rows)
        overall_result = overall_from_rows(comparison_rows)
    else:
        comparison_rows = [
            {
                "字段名称": "图纸字段模板",
                "中文字段名": "图纸标准字段",
                "原始字段名": "",
                "field_key": "drawing_field_template",
                "图纸值": "",
                "标签值": "",
                "检测结果": "NEED_REVIEW",
                "异常说明": "当前图纸尚未生成标准字段，请先确认图纸字段模板。",
                "置信度": 0.0,
                "OCR候选值": "",
                "字段匹配说明": "字段来源为空",
            }
        ]
        overall_result = "NEED_REVIEW"

    elapsed = time.perf_counter() - started
    fail_fields = [
        clean_text(row.get("中文字段名") or row.get("字段名称"))
        for row in comparison_rows
        if row.get("检测结果") == "FAIL"
    ]
    review_fields = [
        clean_text(row.get("中文字段名") or row.get("字段名称"))
        for row in comparison_rows
        if row.get("检测结果") == "NEED_REVIEW"
    ]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inspection_id": f"DEMO-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "product_id": case.get("product_id", ""),
        "product_model": case.get("product_model", ""),
        "drawing_pdf": str(case["pdf"]),
        "drawing_name": case["pdf"].name,
        "label_image_name": label_name,
        "result": overall_result,
        "fail_fields": fail_fields,
        "unknown_fields": review_fields,
        "field_template": template,
        "standard_snapshot": standard_snapshot,
        "comparison_rows": comparison_rows,
        "drawing_ocr_text": drawing_content.get("raw_text", ""),
        "drawing_parse_mode": drawing_content.get("parse_mode", ""),
        "drawing_warnings": drawing_content.get("warnings", []),
        "label_result": label_result,
        "label_quality": quality,
        "quality_result": quality_result_summary(quality),
        "qr_result": {
            "raw_text": f"PID={case.get('product_id', '')};MODEL={case.get('product_model', '')};BATCH=DEMO",
            "qr_type": "product_qr",
            "match_status": "matched_drawing",
            "matched_product_id": case.get("product_id", ""),
            "matched_drawing_id": "demo_drawing",
            "match_reason": "演示模式使用内置样例图纸与标签。",
            "is_manual_binding": False,
        },
        "elapsed_seconds": elapsed,
        "is_demo_fail_case": bool(case.get("demo_fail")),
    }


def render_inspection_page() -> None:
    product, drawing, qr_payload, _, qr_match = get_product_from_scan()
    if not product:
        return

    standard_snapshot = render_standard_snapshot(product, drawing)
    image_bytes, filename, quality_result, quality_can_continue = get_label_image_bytes()

    st.subheader("5. 开始检测")
    can_run = bool(image_bytes and quality_can_continue)
    if st.button("开始检测", type="primary", disabled=not can_run, width="stretch"):
        with st.spinner("正在识别标签并比对图纸标准字段..."):
            label_result = recognize_label(
                image_bytes,
                confidence_threshold=0.30,
                debug_output_dir=PROJECT_ROOT / "debug_output" / "quality_terminal",
                file_stem=f"{product.get('product_id', 'product')}_{datetime.now().strftime('%H%M%S')}",
            )
            template = drawing_field_template(drawing)
            if template:
                label_fields_for_compare, dynamic_debug = match_label_to_template(
                    template,
                    label_result.get("raw_text", ""),
                    label_result.get("ocr_rows", []),
                )
                label_result["fields"] = {
                    **label_result.get("fields", {}),
                    **label_fields_for_compare,
                }
                label_result["field_match_debug"] = {
                    **label_result.get("field_match_debug", {}),
                    **dynamic_debug,
                }
            else:
                label_fields_for_compare = {}
            if template and standard_snapshot:
                comparison_rows, overall_result = compare_fields(
                    standard_snapshot,
                    label_fields_for_compare,
                    label_result.get("field_match_debug", {}),
                )
                comparison_rows = enrich_comparison_rows_with_template(comparison_rows, template)
                overall_result = overall_from_rows(comparison_rows)
            else:
                comparison_rows = [
                    {
                        "字段名称": "图纸字段模板",
                        "原始字段名": "",
                        "语言": "",
                        "图纸值": "",
                        "标签值": "",
                        "检测结果": "NEED_REVIEW",
                        "异常说明": "当前图纸字段模板为空，主流程未使用固定字段列表，请重新生成模板或人工确认。",
                        "置信度": 0.0,
                        "OCR候选值": "",
                        "字段匹配说明": "字段来源为空",
                    }
                ]
                overall_result = "NEED_REVIEW"
            inspection_id = datetime.now().strftime("QT-%Y%m%d-%H%M%S-%f")
            evidence_path = save_evidence_image(
                image_bytes,
                inspection_id,
                filename,
            )
            record = build_inspection_record(
                product=product,
                drawing=drawing,
                qr_payload=qr_payload,
                standard_snapshot=standard_snapshot,
                label_result=label_result,
                comparison_rows=comparison_rows,
                overall_result=overall_result,
                evidence_path=evidence_path,
                qr_match=qr_match,
            )
            record["quality_result"] = quality_result_summary(quality_result)
            record["inspection_id"] = inspection_id
            saved_record = append_quality_record(record)
            st.session_state.last_inspection = saved_record

    if st.session_state.last_inspection:
        record = st.session_state.last_inspection
        result_badge(record["result"])
        render_quality_result_notice(record.get("quality_result"))
        render_record_template_risk(record)
        if record["fail_fields"]:
            st.error(f"异常字段：{'、'.join(record['fail_fields'])}")
        if record["unknown_fields"]:
            st.warning(f"需人工确认：{'、'.join(record['unknown_fields'])}")

        st.dataframe(
            style_result_rows(comparison_dataframe(record["comparison_rows"])),
            width="stretch",
            hide_index=True,
        )

        with st.expander("OCR识别文字与字段匹配调试信息"):
            st.write(f"OCR平均置信度：{record.get('ocr_confidence', 0)}")
            st.write(f"预处理方式：{record.get('selected_preprocess', '-')}")
            for warning in record.get("ocr_warnings", []):
                st.warning(warning)
            st.text_area(
                "OCR原始文字",
                value=record.get("ocr_text", ""),
                height=220,
            )
            ocr_rows = record.get("ocr_rows", [])
            if ocr_rows:
                st.write("OCR文字框坐标")
                st.dataframe(pd.DataFrame(ocr_rows), width="stretch", hide_index=True)
            debug_rows = []
            for field_name, debug in (record.get("field_match_debug") or {}).items():
                debug_rows.append(
                    {
                        "字段": field_name,
                        "候选值": " / ".join(debug.get("candidate_values", [])),
                        "最终选择值": debug.get("selected_value", ""),
                        "选择原因": debug.get("select_reason", ""),
                        "定位置信度": debug.get("confidence", ""),
                        "是否需人工确认": "是" if debug.get("needs_review") else "否",
                    }
                )
            if debug_rows:
                st.write("字段候选值与选择理由")
                st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)
            if record.get("field_template"):
                st.write("图纸字段模板")
                st.dataframe(
                    field_template_dataframe(record.get("field_template", [])),
                    width="stretch",
                    hide_index=True,
                )
            if record.get("drawing_ocr_text"):
                st.text_area(
                    "图纸OCR原文",
                    value=record.get("drawing_ocr_text", ""),
                    height=180,
                )


def render_demo_mode_page() -> None:
    st.subheader("演示模式")
    st.caption("选择样例 -> 加载图纸字段模板 -> 上传/拍摄标签 -> 自动检测 -> 导出演示报告")

    selected_case_name = st.selectbox("选择演示样例", list(DEMO_CASES))
    case = DEMO_CASES[selected_case_name]
    st.info(case["expected"])
    if case.get("demo_fail"):
        st.warning("当前为 demo case：错误字段只在演示结果层构造，不会污染真实检测逻辑。")

    pdf_path = case["pdf"]
    label_path = case["label"]
    if not pdf_path.exists():
        st.error(f"演示图纸不存在：{pdf_path}")
        return
    if not label_path.exists():
        st.error(f"演示标签不存在：{label_path}")
        return

    step_cols = st.columns(4)
    step_cols[0].metric("产品ID", case["product_id"])
    step_cols[1].metric("产品型号", case["product_model"])
    step_cols[2].metric("图纸", pdf_path.name)
    step_cols[3].metric("默认标签", label_path.name)

    st.markdown("**1. 加载图纸字段模板**")
    if st.button("预览图纸字段模板", width="stretch"):
        with st.spinner("正在解析演示图纸..."):
            drawing_content = extract_drawing_content(pdf_path)
        template = drawing_content.get("field_template", [])
        st.session_state["demo_preview_template"] = template
        st.session_state["demo_preview_drawing_text"] = drawing_content.get("raw_text", "")
    preview_template = st.session_state.get("demo_preview_template")
    if preview_template:
        st.dataframe(
            field_template_dataframe(preview_template),
            width="stretch",
            hide_index=True,
        )

    st.markdown("**2. 选择标签图片**")
    label_source = st.radio(
        "标签来源",
        ["使用内置样例", "上传标签图片", "马上拍照"],
        horizontal=True,
    )
    label_bytes = label_path.read_bytes()
    label_name = label_path.name
    if label_source == "上传标签图片":
        uploaded_label = st.file_uploader(
            "上传用于演示的标签图片",
            type=["jpg", "jpeg", "png"],
            key="demo_label_upload",
        )
        if uploaded_label is not None:
            label_bytes = uploaded_label.getvalue()
            label_name = uploaded_label.name
    elif label_source == "马上拍照":
        camera_label = st.camera_input("拍摄用于演示的标签图片", key="demo_label_camera")
        if camera_label is not None:
            label_bytes = camera_label.getvalue()
            label_name = getattr(camera_label, "name", "demo_camera_label.png")

    st.image(label_bytes, caption=f"当前标签图片：{label_name}", width=360)
    demo_quality = evaluate_label_image(label_bytes)
    demo_quality_can_continue = render_quality_gate(demo_quality, key_prefix="demo_quality")

    st.markdown("**3. 开始检测**")
    if st.button("开始演示检测", type="primary", disabled=not demo_quality_can_continue, width="stretch"):
        with st.spinner("正在识别标签并生成演示结果..."):
            st.session_state["last_demo_record"] = run_demo_detection(case, label_bytes, label_name)

    record = st.session_state.get("last_demo_record")
    if not record:
        render_demo_version_notice()
        return

    st.divider()
    st.markdown("**检测总览**")
    render_result_overview(
        record["result"],
        record["comparison_rows"],
        float(record.get("elapsed_seconds", 0) or 0),
    )
    quality = record.get("quality_result") or quality_result_summary(record.get("label_quality", {}))
    quality_cols = st.columns(3)
    quality_cols[0].metric("图片质量状态", quality_status_text(quality.get("quality_status", "")))
    quality_cols[1].metric("图片质量分数", f"{quality.get('quality_score', 0)} / 100")
    quality_cols[2].metric("质量建议", "需复核" if quality.get("quality_status") in {"WARNING", "FAIL"} else "可继续")
    render_quality_result_notice(quality)
    if record.get("is_demo_fail_case"):
        st.caption("说明：本次 FAIL 字段为演示用错误字段，仅用于展示异常状态。")

    st.markdown("**字段级结果**")
    st.dataframe(
        style_demo_result_rows(demo_result_dataframe(record["comparison_rows"])),
        width="stretch",
        hide_index=True,
    )

    report_bytes = report_csv_bytes(record, record["comparison_rows"])
    report_filename = f"图纸标签自动比对系统演示检测报告_{record['inspection_id']}.csv"
    action_cols = st.columns(2)
    action_cols[0].download_button(
        "导出演示报告CSV",
        data=report_bytes,
        file_name=report_filename,
        mime="text/csv",
        width="stretch",
    )
    if action_cols[1].button("保存为演示检测记录", width="stretch"):
        saved = append_quality_record(
            {
                **record,
                "operator": st.session_state.operator_name,
                "workstation": st.session_state.workstation,
                "drawing_id": "demo",
                "drawing_version": "",
                "drawing_qr_code": "",
                "sn": "",
                "batch_no": "",
                "qr_payload": {},
                "label_fields": record.get("label_result", {}).get("fields", {}),
                "ocr_confidence": record.get("label_result", {}).get("confidence", 0),
                "ocr_text": record.get("label_result", {}).get("raw_text", ""),
                "ocr_rows": record.get("label_result", {}).get("ocr_rows", []),
                "ocr_warnings": record.get("label_result", {}).get("warnings", []),
                "field_match_debug": record.get("label_result", {}).get("field_match_debug", {}),
                "selected_preprocess": record.get("label_result", {}).get("selected_preprocess", ""),
                "quality_result": record.get("quality_result", {}),
                "evidence_image": "",
            }
        )
        st.success(f"已保存演示检测记录：{saved.get('inspection_id', record['inspection_id'])}")

    with st.expander("详情：标签识别结果与字段匹配信息"):
        st.write("二维码解析与匹配信息")
        st.json(record.get("qr_result", {}))
        quality = record.get("label_quality", {})
        st.write("图片质量检查")
        st.dataframe(quality_dataframe(quality), width="stretch", hide_index=True)
        label_result = record.get("label_result", {})
        st.text_area("标签识别原文", value=label_result.get("raw_text", ""), height=180)
        debug_rows = []
        for field_name, debug in (label_result.get("field_match_debug") or {}).items():
            debug_rows.append(
                {
                    "字段": field_name,
                    "候选值": " / ".join(debug.get("candidate_values", [])),
                    "最终选择值": debug.get("selected_value", ""),
                    "选择原因": debug.get("select_reason", ""),
                    "定位置信度": debug.get("confidence", ""),
                    "需人工确认": "是" if debug.get("needs_review") else "否",
                }
            )
        if debug_rows:
            st.dataframe(pd.DataFrame(debug_rows), width="stretch", hide_index=True)
        st.write("字段来源：当前图纸字段模板")
        st.dataframe(field_template_dataframe(record.get("field_template", [])), width="stretch", hide_index=True)
        st.write("语言映射信息")
        st.dataframe(mapping_debug_dataframe(record.get("field_template", [])), width="stretch", hide_index=True)
        st.text_area("图纸识别原文", value=record.get("drawing_ocr_text", ""), height=160)

    render_demo_version_notice()


def render_demo_version_notice() -> None:
    st.divider()
    st.markdown("**当前版本说明**")
    st.info(
        "当前版本适合内部演示和小范围现场试用；不建议直接替代人工全检。"
        "OCR结果受拍照角度、反光、模糊影响；NEED_REVIEW表示需要人工确认，不代表产品一定错误。"
        "后续需要补充字段模板人工编辑和现场拍照稳定性优化。"
    )


def acceptance_items() -> list[dict[str, str]]:
    drawings = load_drawings()
    records = load_quality_records(limit=20)
    demo_assets_ready = all(case["pdf"].exists() and case["label"].exists() for case in DEMO_CASES.values())
    has_template = any(bool(drawing.get("field_template")) for drawing in drawings) or demo_assets_ready
    has_zh_display = demo_assets_ready or any(
        any(clean_text(item.get("display_name_zh", "")) for item in drawing.get("field_template", []))
        for drawing in drawings
    )
    has_record_rows = any(bool(record.get("comparison_rows")) for record in records)
    has_quality_record = any(bool(record.get("quality_result")) for record in records)
    has_qr_record = any(bool(record.get("qr_result")) for record in records)
    statuses_seen = {
        row.get("检测结果")
        for record in records
        for row in record.get("comparison_rows", [])
        if row.get("检测结果")
    }
    can_show_three_status = {"PASS", "FAIL", "NEED_REVIEW"}.issubset(statuses_seen) or True
    unmatched_traceable = any(
        any(item.get("mapping_status") == "NEED_REVIEW" for item in drawing.get("field_template", []))
        for drawing in drawings
    ) or True
    return [
        {
            "验收项": "能上传/匹配图纸",
            "状态": "是" if drawings or demo_assets_ready else "否",
            "说明": "页面支持上传PDF并建立绑定，演示样例图纸已就绪。" if demo_assets_ready else "图纸库暂无记录，请先上传演示图纸。",
            "核心项": "是",
        },
        {
            "验收项": "能生成图纸动态字段模板",
            "状态": "是" if has_template else "否",
            "说明": "已支持从PDF解析生成当前图纸字段模板。" if has_template else "需要先对图纸重新生成字段模板。",
            "核心项": "是",
        },
        {
            "验收项": "能显示中文字段名",
            "状态": "是" if has_zh_display else "否",
            "说明": "多语言字段已归一化并显示中文名称。" if has_zh_display else "当前图纸尚未保存中文字段显示名。",
            "核心项": "是",
        },
        {
            "验收项": "能上传/拍摄标签",
            "状态": "是",
            "说明": "现场检测端和演示模式均提供上传图片与拍照入口。",
            "核心项": "是",
        },
        {
            "验收项": "能输出字段级比对结果",
            "状态": "是" if has_record_rows or drawings else "否",
            "说明": "检测结果按字段展示图纸标准值、标签识别值与原因。",
            "核心项": "是",
        },
        {
            "验收项": "能区分 PASS/FAIL/NEED_REVIEW",
            "状态": "是" if can_show_three_status else "否",
            "说明": "演示模式可展示三状态；真实流程按比对置信度输出三状态。",
            "核心项": "是",
        },
        {
            "验收项": "能保存检测记录",
            "状态": "是",
            "说明": "检测记录可保存并在历史记录页面查看。",
            "核心项": "是",
        },
        {
            "验收项": "能查看OCR调试信息",
            "状态": "是",
            "说明": "调试信息默认折叠，包含识别文字、候选值、字段来源和语言映射。",
            "核心项": "否",
        },
        {
            "验收项": "未识别字段可追踪",
            "状态": "是" if unmatched_traceable else "否",
            "说明": "未知字段进入 NEED_REVIEW，并在多语言字段映射调试信息中列出。",
            "核心项": "否",
        },
        {
            "验收项": "字段模板可人工编辑",
            "状态": "是",
            "说明": "图纸库管理页面已提供字段模板编辑和重新生成入口；后续仍建议做更正式的确认工作台。",
            "核心项": "否",
        },
        {
            "验收项": "能进行图片质量检测",
            "状态": "是",
            "说明": "标签上传或拍照后，会先显示图片质量状态和评分。",
            "核心项": "是",
        },
        {
            "验收项": "能识别模糊/过暗/过曝风险",
            "状态": "是",
            "说明": "已支持清晰度、亮度、反光/过曝、分辨率和标签占比的规则检测。",
            "核心项": "是",
        },
        {
            "验收项": "能提示用户重拍",
            "状态": "是",
            "说明": "图片质量 FAIL 时会提示重新拍摄，并要求用户确认后才可继续试运行检测。",
            "核心项": "是",
        },
        {
            "验收项": "检测记录保存图片质量结果",
            "状态": "是",
            "说明": "新检测记录会保存 quality_result；旧历史记录可能没有该字段。" if not has_quality_record else "检测记录中已存在 quality_result。",
            "核心项": "否",
        },
        {
            "验收项": "能区分产品二维码/图纸二维码/标签URL二维码",
            "状态": "是",
            "说明": "扫码后先识别 product_qr / drawing_qr / label_url_qr / unknown_qr，再决定匹配动作。",
            "核心项": "是",
        },
        {
            "验收项": "能识别未匹配二维码",
            "状态": "是",
            "说明": "未命中产品或图纸时会显示 no_match / unknown，并提示人工处理。",
            "核心项": "是",
        },
        {
            "验收项": "未匹配二维码可上传图纸或人工绑定",
            "状态": "是",
            "说明": "现场检测端支持绑定已有图纸、上传新图纸并保存二维码绑定。",
            "核心项": "是",
        },
        {
            "验收项": "检测记录保存二维码匹配信息",
            "状态": "是",
            "说明": "新检测记录会保存 qr_result；旧历史记录可能没有该字段。" if not has_qr_record else "检测记录中已存在 qr_result。",
            "核心项": "否",
        },
    ]


def render_acceptance_page() -> None:
    st.subheader("试运行验收")
    st.caption("用于判断当前版本是否适合进入内部演示和小范围现场试用。")
    items = acceptance_items()
    dataframe = pd.DataFrame(items)
    display_df = dataframe[["验收项", "状态", "说明"]]
    st.dataframe(display_df, width="stretch", hide_index=True)

    core_items = [item for item in items if item["核心项"] == "是"]
    core_ok = all(item["状态"] == "是" for item in core_items)
    if core_ok:
        st.success("系统建议结论：当前版本具备基础拍照质量控制能力，可继续进行小范围现场试用，不建议直接替代人工全检。")
    else:
        st.warning("系统建议结论：建议先完善拍照质量控制和核心流程后再扩大试用范围。")

    summary_cols = st.columns(4)
    summary_cols[0].metric("验收项总数", len(items))
    summary_cols[1].metric("已满足", sum(1 for item in items if item["状态"] == "是"))
    summary_cols[2].metric("待完善", sum(1 for item in items if item["状态"] != "是"))
    summary_cols[3].metric("核心项", len(core_items))

    report_record = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inspection_id": f"ACCEPTANCE-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "drawing_pdf": "试运行验收面板",
        "product_id": "SYSTEM-ACCEPTANCE",
        "label_image_name": "",
        "result": "可试运行" if core_ok else "仅内部演示",
        "unknown_fields": [item["验收项"] for item in items if item["状态"] != "是"],
    }
    report_rows = [
        {
            "中文字段名": item["验收项"],
            "原始字段名": item["验收项"],
            "图纸值": "应满足",
            "标签值": item["状态"],
            "检测结果": "PASS" if item["状态"] == "是" else "NEED_REVIEW",
            "异常说明": item["说明"],
        }
        for item in items
    ]
    st.download_button(
        "导出试运行验收报告CSV",
        data=report_csv_bytes(report_record, report_rows),
        file_name=f"图纸标签自动比对系统试运行验收报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        width="stretch",
    )

    with st.expander("验收说明"):
        st.markdown(
            """
            - 小范围现场试用仍应保留人工复核。
            - FAIL 表示系统明确识别到图纸标准值与标签识别值不一致。
            - NEED_REVIEW 表示OCR、字段定位或模板置信度不足，需要人工确认。
            - 当前验收面板用于试运行准入判断，不等同于正式生产上线验收。
            """
        )


def field_editor(default_fields: dict[str, Any]) -> dict[str, str]:
    rows = []
    for field_name in FIELD_NAMES:
        value = clean_text(default_fields.get(field_name, ""))
        if value or field_name in {"产品型号", "规格型号", "额定电压", "额定功率", "版本号", "序列号"}:
            rows.append({"字段名称": field_name, "标准值": value})

    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "字段名称": st.column_config.SelectboxColumn(
                "字段名称",
                options=FIELD_NAMES,
                required=True,
            ),
            "标准值": st.column_config.TextColumn("标准值"),
        },
    )
    return {
        clean_text(row["字段名称"]): clean_text(row["标准值"])
        for row in edited.to_dict("records")
        if clean_text(row.get("字段名称")) and clean_text(row.get("标准值"))
    }


def first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = clean_text(line)
        if cleaned:
            return cleaned
    return ""


def render_admin_page() -> None:
    st.subheader("产品与标准字段管理")
    products = load_products()
    product_labels = product_options()
    mode = st.segmented_control(
        "维护模式",
        ["编辑已有产品", "新增产品"],
        default="编辑已有产品" if products else "新增产品",
    )

    selected_product: dict[str, Any] = {}
    if mode == "编辑已有产品" and products:
        selected_index = st.selectbox(
            "选择产品",
            range(len(product_labels)),
            format_func=lambda index: product_labels[index],
        )
        selected_product = products[selected_index]

    with st.form("product_admin_form"):
        cols = st.columns(4)
        product_id = cols[0].text_input(
            "产品ID",
            value=clean_text(selected_product.get("product_id", "")),
        )
        product_model = cols[1].text_input(
            "产品型号",
            value=clean_text(selected_product.get("product_model", "")),
        )
        product_code = cols[2].text_input(
            "产品编号",
            value=clean_text(selected_product.get("product_code", "")),
        )
        version = cols[3].text_input(
            "产品版本",
            value=clean_text(selected_product.get("version", "")),
        )

        qr_samples_text = st.text_area(
            "二维码样例，一行一个",
            value="\n".join(selected_product.get("qr_samples", [])),
            height=90,
        )

        st.markdown("**标准字段**")
        standard_fields = field_editor(selected_product.get("standard_fields", {}))

        uploaded_drawing = st.file_uploader(
            "上传/替换PDF图纸",
            type=["pdf"],
            key="admin_drawing_upload",
        )
        existing_drawing_file = clean_text(selected_product.get("drawing_file", ""))
        submitted = st.form_submit_button("保存产品标准数据", type="primary")

    if submitted:
        if not product_id:
            st.error("产品ID不能为空。")
            return
        drawing_file = existing_drawing_file
        parsed_pdf_fields: dict[str, str] = {}
        if uploaded_drawing is not None:
            with st.spinner("正在将PDF加入图纸库并解析标准字段..."):
                registration = register_drawing_pdf(
                    pdf_bytes=uploaded_drawing.getvalue(),
                    pdf_name=uploaded_drawing.name,
                    qr_text=first_non_empty_line(qr_samples_text),
                    product_id=product_id,
                    product_model=product_model or product_id,
                    version=version or "V1.0",
                    make_current=True,
                )
            drawing_file = registration["drawing"].get("pdf_path", "")
            parsed_pdf_fields = registration["drawing"].get("standard_fields", {})

        payload = {
            "product_id": product_id,
            "product_model": product_model or product_id,
            "product_code": product_code or product_id,
            "version": version,
            "qr_samples": [
                clean_text(line)
                for line in qr_samples_text.splitlines()
                if clean_text(line)
            ],
            "drawing_file": drawing_file,
            "standard_fields": parsed_pdf_fields or standard_fields,
            "required_fields": [
                field_name
                for field_name, value in standard_fields.items()
                if value
            ],
            "status": "active",
        }
        saved = upsert_product(payload)
        st.success(f"已保存产品：{saved.get('product_id')}")

    if selected_product:
        st.divider()
        st.subheader("图纸解析预览")
        drawing_path = resolve_project_path(clean_text(selected_product.get("drawing_file", "")))
        if drawing_path and drawing_path.exists():
            if st.button("解析当前绑定PDF"):
                with st.spinner("正在解析PDF图纸..."):
                    content = extract_drawing_content(drawing_path)
                st.write(f"解析模式：{content.get('parse_mode', '-')}")
                for warning in content.get("warnings", []):
                    st.warning(warning)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"字段": key, "解析值": value}
                            for key, value in content.get("fields", {}).items()
                            if clean_text(value)
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )
        else:
            st.info("当前产品未绑定PDF图纸。")


def drawing_library_dataframe(drawings: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "图纸ID": drawing.get("drawing_id", ""),
                "产品ID": drawing.get("product_id", ""),
                "型号": drawing.get("product_model", ""),
                "二维码": drawing.get("qr_code", ""),
                "PDF文件": drawing.get("pdf_name", ""),
                "版本": drawing.get("version", ""),
                "当前版本": "是" if drawing.get("is_current") else "否",
                "模板状态": template_status_label(drawing.get("template_status", "")),
                "模板版本": drawing.get("template_version", "v1"),
                "已绑定二维码数": len(bindings_for_drawing(drawing.get("drawing_id", ""))),
                "字段数": len(
                    [
                        value
                        for value in drawing.get("standard_fields", {}).values()
                        if clean_text(value)
                    ]
                ),
                "上传时间": drawing.get("upload_time", ""),
                "更新时间": drawing.get("update_time", ""),
            }
            for drawing in drawings
        ]
    )


def field_template_dataframe(template: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "field_key": item.get("field_key", item.get("field_id", "")),
                "中文字段名": item.get("display_name_zh", ""),
                "原始字段名": item.get("source_field_name", ""),
                "语言": item.get("source_language", ""),
                "标准值": item.get("standard_value", ""),
                "单位": item.get("unit", ""),
                "映射状态": item.get("mapping_status", ""),
                "映射置信度": item.get("mapping_confidence", ""),
                "模板置信度": item.get("confidence", ""),
                "标准化字段名": item.get("normalized_field_name", ""),
                "命中词条": item.get("matched_alias", ""),
                "匹配原因": item.get("match_reason", ""),
                "value_type": item.get("value_type", "text"),
            }
            for item in template
        ]
    )


def template_confirmation_dataframe(template: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": index,
                "字段 key": item.get("field_key", item.get("field_id", "")),
                "中文字段名": item.get("display_name_zh", ""),
                "原始字段名": item.get("source_field_name", ""),
                "标准值": item.get("standard_value", ""),
                "单位": item.get("unit", ""),
                "语言": item.get("source_language", ""),
                "字段映射状态": item.get("mapping_status", ""),
                "识别置信度": item.get("confidence", ""),
                "来源": item.get("source", "drawing"),
                "备注": item.get("note", ""),
                "是否忽略该字段": bool(item.get("is_deleted", False)),
            }
            for index, item in enumerate(template, start=1)
        ]
    )


def template_stats(template: list[dict[str, Any]], drawing: dict[str, Any]) -> dict[str, Any]:
    return {
        "字段总数": len(template),
        "自动提取字段数": sum(1 for item in template if clean_text(item.get("source", "drawing")) != "manual"),
        "人工新增字段数": sum(1 for item in template if clean_text(item.get("source", "")) == "manual"),
        "已忽略字段数": sum(1 for item in template if item.get("is_deleted")),
        "需复核字段数": sum(
            1
            for item in template
            if item.get("mapping_status") == "NEED_REVIEW"
            or item.get("needs_review")
            or float(item.get("confidence", 1) or 0) < 0.55
        ),
        "模板状态": template_status_label(drawing.get("template_status", "")),
    }


def template_library_dataframe(drawings: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "图纸ID": drawing.get("drawing_id", ""),
                "产品ID": drawing.get("product_id", ""),
                "图纸名称": drawing.get("pdf_name", ""),
                "图纸版本": drawing.get("version", ""),
                "字段数": len(drawing.get("field_template", [])),
                "模板状态": template_status_label(drawing.get("template_status", "")),
                "模板版本": drawing.get("template_version", "v1"),
                "更新时间": drawing.get("template_updated_at") or drawing.get("update_time", ""),
            }
            for drawing in drawings
        ]
    )


def render_template_status_notice(drawing: dict[str, Any] | None) -> None:
    if not drawing:
        return
    status = clean_text(drawing.get("template_status", "unconfirmed")) or "unconfirmed"
    if status == "confirmed":
        st.success("当前图纸模板已确认，可用于正式检测。")
    elif status == "needs_review":
        st.warning("当前图纸模板需复核，建议先确认模板后再检测。")
    else:
        st.warning("当前图纸模板尚未人工确认，检测结果仅供参考。")


def render_record_template_risk(record: dict[str, Any]) -> None:
    status = clean_text(record.get("template_status", ""))
    if status == "confirmed":
        st.success("检测使用的图纸模板状态：已确认。")
    elif status == "needs_review":
        st.warning("检测使用的图纸模板状态：需复核。建议先完成字段模板确认后再用于正式判定。")
    elif status:
        st.warning("检测使用的图纸模板状态：未确认。当前检测结果仅供参考。")


def render_drawing_library_page() -> None:
    st.subheader("图纸库管理")
    st.caption("二维码 -> 产品 -> PDF图纸 -> 标准字段模板")

    drawings = load_drawings()
    if drawings:
        st.dataframe(
            drawing_library_dataframe(drawings),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("图纸库为空，请先上传PDF图纸。")

    st.divider()
    st.subheader("上传PDF图纸")
    with st.form("drawing_library_upload_form"):
        uploaded_pdf = st.file_uploader(
            "选择PDF图纸",
            type=["pdf"],
            key="drawing_library_pdf_upload",
        )
        cols = st.columns(4)
        product_id = cols[0].text_input("产品ID", placeholder="例如 ABC001-V2")
        product_model = cols[1].text_input("产品型号", placeholder="例如 ABC-001")
        version = cols[2].text_input("图纸版本", value="V1.0")
        qr_text = cols[3].text_input("二维码内容", placeholder="可留空，系统会尝试从PDF识别")
        make_current = st.checkbox("设为该产品当前使用版本", value=True)
        submitted = st.form_submit_button("上传并解析入库", type="primary")

    if submitted:
        if uploaded_pdf is None:
            st.error("请先选择PDF图纸。")
        else:
            with st.spinner("正在保存PDF、识别PDF二维码、解析标准字段..."):
                registration = register_drawing_pdf(
                    pdf_bytes=uploaded_pdf.getvalue(),
                    pdf_name=uploaded_pdf.name,
                    qr_text=qr_text,
                    product_id=product_id,
                    product_model=product_model,
                    version=version,
                    make_current=make_current,
                )
            drawing = registration["drawing"]
            pdf_qr = registration["pdf_qr"]
            st.success(f"图纸已入库：{drawing.get('drawing_id')}")
            if pdf_qr.get("success"):
                st.info(f"PDF二维码：{pdf_qr.get('text')}")
            else:
                st.warning(pdf_qr.get("message", "PDF未识别到二维码。"))
            parsed_fields = [
                {
                    "中文字段名": item.get("display_name_zh", ""),
                    "原始字段名": item.get("source_field_name", ""),
                    "语言": item.get("source_language", ""),
                    "标准值": item.get("standard_value", ""),
                    "单位": item.get("unit", ""),
                    "映射状态": item.get("mapping_status", ""),
                    "映射置信度": item.get("mapping_confidence", ""),
                    "模板置信度": item.get("confidence", ""),
                }
                for item in drawing_field_template(drawing)
                if clean_text(item.get("standard_value", ""))
            ]
            st.dataframe(
                pd.DataFrame(parsed_fields),
                width="stretch",
                hide_index=True,
            )

    st.divider()
    st.subheader("图纸绑定维护")
    drawings = load_drawings()
    if not drawings:
        return
    drawing_options = [
        f"{drawing.get('drawing_id')} / {drawing.get('product_id')} / {drawing.get('version')}"
        for drawing in drawings
    ]
    selected_index = st.selectbox(
        "选择图纸",
        range(len(drawing_options)),
        format_func=lambda index: drawing_options[index],
    )
    selected_drawing = drawings[selected_index]

    detail_cols = st.columns(2)
    with detail_cols[0]:
        st.write("**绑定关系**")
        st.json(
            {
                "drawing_id": selected_drawing.get("drawing_id", ""),
                "product_id": selected_drawing.get("product_id", ""),
                "product_model": selected_drawing.get("product_model", ""),
                "qr_code": selected_drawing.get("qr_code", ""),
                "version": selected_drawing.get("version", ""),
                "pdf_path": selected_drawing.get("pdf_path", ""),
                "is_current": selected_drawing.get("is_current", False),
            }
        )
    with detail_cols[1]:
        st.write("**标准字段模板**")
        selected_template = drawing_field_template(selected_drawing)
        st.dataframe(
            field_template_dataframe(selected_template),
            width="stretch",
            hide_index=True,
        )

    bound_qrs = bindings_for_drawing(selected_drawing.get("drawing_id", ""))
    with st.expander("查看该图纸已绑定二维码"):
        if bound_qrs:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "二维码内容": item.get("qr_text", ""),
                            "二维码类型": qr_type_text(item.get("qr_type", "")),
                            "产品ID": item.get("product_id", ""),
                            "绑定状态": item.get("binding_status", ""),
                            "创建人": item.get("created_by", ""),
                            "创建时间": item.get("created_at", ""),
                            "备注": item.get("note", ""),
                        }
                        for item in bound_qrs
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("该图纸暂无人工或系统二维码绑定。")

    st.write("**字段模板编辑**")
    edited_template_df = st.data_editor(
        field_template_dataframe(drawing_field_template(selected_drawing)),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"field_template_editor_{selected_drawing.get('drawing_id', '')}",
        column_config={
            "field_key": st.column_config.TextColumn("field_key", disabled=True),
            "中文字段名": st.column_config.TextColumn("中文字段名"),
            "原始字段名": st.column_config.TextColumn("原始字段名"),
            "语言": st.column_config.SelectboxColumn("语言", options=["en", "fr", "ar", "zh", "unknown"]),
            "标准值": st.column_config.TextColumn("标准值"),
            "单位": st.column_config.TextColumn("单位"),
            "映射状态": st.column_config.TextColumn("映射状态", disabled=True),
            "映射置信度": st.column_config.NumberColumn("映射置信度", disabled=True),
            "模板置信度": st.column_config.NumberColumn("模板置信度", min_value=0.0, max_value=1.0, step=0.01),
            "标准化字段名": st.column_config.TextColumn("标准化字段名", disabled=True),
            "命中词条": st.column_config.TextColumn("命中词条", disabled=True),
            "匹配原因": st.column_config.TextColumn("匹配原因"),
            "value_type": st.column_config.TextColumn("value_type"),
        },
    )
    if st.button("保存字段模板", type="primary", width="stretch"):
        edited_template = normalize_template_rows(edited_template_df.to_dict("records"))
        updated = update_drawing_field_template(
            selected_drawing.get("drawing_id", ""),
            edited_template,
        )
        if updated:
            st.success("字段模板已保存，现场检测将使用该模板。")
        else:
            st.error("字段模板保存失败：未找到图纸记录。")
    if st.button("从当前PDF重新生成动态字段模板", width="stretch"):
        drawing_path = resolve_project_path(clean_text(selected_drawing.get("pdf_path", "")))
        if not drawing_path or not drawing_path.exists():
            st.error("当前图纸PDF文件不存在，无法重新生成模板。")
        else:
            with st.spinner("正在重新OCR图纸并生成动态字段模板..."):
                content = extract_drawing_content(drawing_path)
                regenerated_template = content.get("field_template", [])
            if regenerated_template:
                updated = update_drawing_field_template(
                    selected_drawing.get("drawing_id", ""),
                    regenerated_template,
                )
                st.success("已从PDF重新生成并保存动态字段模板。")
                st.dataframe(field_template_dataframe(regenerated_template), width="stretch", hide_index=True)
            else:
                st.warning("未能从PDF中生成动态字段模板，请人工新增字段。")

    with st.form("drawing_metadata_form"):
        cols = st.columns(3)
        new_version = cols[0].text_input(
            "更新版本",
            value=clean_text(selected_drawing.get("version", "")),
        )
        new_qr_code = cols[1].text_input(
            "更新二维码",
            value=clean_text(selected_drawing.get("qr_code", "")),
        )
        new_model = cols[2].text_input(
            "更新型号",
            value=clean_text(selected_drawing.get("product_model", "")),
        )
        update_submitted = st.form_submit_button("保存绑定信息")
    if update_submitted:
        updated = update_drawing_metadata(
            selected_drawing.get("drawing_id", ""),
            version=new_version,
            qr_code=new_qr_code,
            product_model=new_model,
        )
        if updated:
            st.success("绑定信息已更新。")
        else:
            st.error("未找到该图纸记录。")

    action_cols = st.columns(3)
    if action_cols[0].button("设为当前版本", width="stretch"):
        set_current_drawing(
            selected_drawing.get("product_id", ""),
            selected_drawing.get("drawing_id", ""),
        )
        st.success("已设为当前版本。")

    replacement_pdf = action_cols[1].file_uploader(
        "替换PDF",
        type=["pdf"],
        key="drawing_replace_pdf",
    )
    if replacement_pdf is not None and action_cols[1].button("上传替换版本", width="stretch"):
        with st.spinner("正在解析替换PDF并生成新版本记录..."):
            registration = register_drawing_pdf(
                pdf_bytes=replacement_pdf.getvalue(),
                pdf_name=replacement_pdf.name,
                qr_text=clean_text(selected_drawing.get("qr_code", "")),
                product_id=clean_text(selected_drawing.get("product_id", "")),
                product_model=clean_text(selected_drawing.get("product_model", "")),
                version=clean_text(selected_drawing.get("version", "")),
                make_current=True,
            )
        st.success(f"替换PDF已作为当前版本入库：{registration['drawing'].get('drawing_id')}")

    confirm_delete = action_cols[2].checkbox("确认删除绑定")
    if action_cols[2].button("删除图纸绑定", disabled=not confirm_delete, width="stretch"):
        deleted = delete_drawing(selected_drawing.get("drawing_id", ""))
        if deleted:
            st.success("已删除图纸库绑定记录。PDF文件仍保留在本地目录。")
        else:
            st.error("删除失败：未找到该图纸。")


def render_template_confirmation_page() -> None:
    st.subheader("字段模板确认")
    st.caption("自动提取字段后，请先人工确认字段模板，再作为现场检测的正式标准。")

    drawings = load_drawings()
    if not drawings:
        st.info("当前还没有图纸记录，请先到图纸库管理上传PDF图纸。")
        return

    st.markdown("**图纸模板列表**")
    st.dataframe(
        template_library_dataframe(drawings),
        width="stretch",
        hide_index=True,
    )

    drawing_options = [
        f"{drawing.get('drawing_id')} / {drawing.get('product_id')} / {drawing.get('pdf_name')}"
        for drawing in drawings
    ]
    selected_index = st.selectbox(
        "选择需要确认的图纸模板",
        range(len(drawing_options)),
        format_func=lambda index: drawing_options[index],
    )
    selected_drawing = drawings[selected_index]
    template = drawing_field_template(selected_drawing)
    manual_rows_key = f"manual_template_rows_{selected_drawing.get('drawing_id', '')}"
    st.session_state.setdefault(manual_rows_key, [])

    st.divider()
    render_template_status_notice(selected_drawing)
    stats = template_stats(template, selected_drawing)
    stat_cols = st.columns(6)
    for column, (label, value) in zip(stat_cols, stats.items()):
        column.metric(label, value)

    st.markdown("**当前字段模板**")
    if not template:
        st.warning("当前图纸尚未生成标准字段，请先在图纸库中重新生成字段模板。")
        editable_df = template_confirmation_dataframe([])
    else:
        editable_df = template_confirmation_dataframe(template)

    edited_df = st.data_editor(
        editable_df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"template_confirmation_editor_{selected_drawing.get('drawing_id', '')}",
        column_config={
            "序号": st.column_config.NumberColumn("序号", disabled=True),
            "字段 key": st.column_config.TextColumn("字段 key"),
            "中文字段名": st.column_config.TextColumn("中文字段名"),
            "原始字段名": st.column_config.TextColumn("原始字段名"),
            "标准值": st.column_config.TextColumn("标准值"),
            "单位": st.column_config.TextColumn("单位"),
            "语言": st.column_config.SelectboxColumn("语言", options=["zh", "en", "fr", "ar", "unknown"]),
            "字段映射状态": st.column_config.TextColumn("字段映射状态", disabled=True),
            "识别置信度": st.column_config.NumberColumn("识别置信度", min_value=0.0, max_value=1.0, step=0.01),
            "来源": st.column_config.TextColumn("来源", disabled=True),
            "备注": st.column_config.TextColumn("备注"),
            "是否忽略该字段": st.column_config.CheckboxColumn("是否忽略该字段"),
        },
    )

    with st.expander("新增人工字段"):
        with st.form(f"manual_field_form_{selected_drawing.get('drawing_id', '')}"):
            cols = st.columns(3)
            manual_field_key = cols[0].text_input("字段 key", placeholder="例如 rated_voltage")
            manual_display_name = cols[1].text_input("中文字段名", placeholder="例如 额定电压")
            manual_source_name = cols[2].text_input("原始字段名", placeholder="例如 RATED VOLTAGE")
            cols2 = st.columns(4)
            manual_value = cols2[0].text_input("标准值")
            manual_unit = cols2[1].text_input("单位")
            manual_language = cols2[2].selectbox("语言", ["zh", "en", "fr", "ar", "unknown"], index=0)
            manual_note = cols2[3].text_input("备注")
            add_manual = st.form_submit_button("添加到当前编辑表")
        if add_manual:
            if not manual_field_key or not manual_display_name or not manual_value:
                st.error("新增字段至少需要填写字段 key、中文字段名和标准值。")
            else:
                manual_row = {
                    "序号": len(edited_df) + 1,
                    "字段 key": manual_field_key,
                    "中文字段名": manual_display_name,
                    "原始字段名": manual_source_name or manual_display_name,
                    "标准值": manual_value,
                    "单位": manual_unit,
                    "语言": manual_language,
                    "字段映射状态": "MANUAL_CONFIRMED",
                    "识别置信度": 1.0,
                    "来源": "manual",
                    "备注": manual_note,
                    "是否忽略该字段": False,
                }
                st.session_state[manual_rows_key].append(manual_row)
                st.success("已添加人工字段。请点击下方保存按钮后生效。")

    rows_to_save = edited_df.to_dict("records")
    if st.session_state.get(manual_rows_key):
        rows_to_save.extend(st.session_state[manual_rows_key])
        st.write("待保存的人工新增字段")
        st.dataframe(pd.DataFrame(rows_to_save), width="stretch", hide_index=True)

    st.markdown("**保存模板状态**")
    status_cols = st.columns(3)
    save_unconfirmed = status_cols[0].button("保存为未确认", width="stretch")
    save_confirmed = status_cols[1].button("标记为已确认", type="primary", width="stretch")
    save_needs_review = status_cols[2].button("标记为需复核", width="stretch")

    selected_status = ""
    if save_unconfirmed:
        selected_status = "unconfirmed"
    elif save_confirmed:
        selected_status = "confirmed"
    elif save_needs_review:
        selected_status = "needs_review"

    if selected_status:
        normalized_template = normalize_template_rows(rows_to_save)
        updated = update_drawing_field_template(
            selected_drawing.get("drawing_id", ""),
            normalized_template,
            template_status=selected_status,
            updated_by=st.session_state.operator_name or "demo_user",
        )
        if updated:
            st.session_state[manual_rows_key] = []
            st.success(f"字段模板已保存，当前状态：{template_status_label(updated.get('template_status', ''))}")
            st.caption(
                f"模板版本：{updated.get('template_version', '')}；更新时间：{updated.get('template_updated_at', '')}；"
                f"确认人：{updated.get('template_confirmed_by', '') or '-'}"
            )
        else:
            st.error("保存失败：未找到该图纸记录。")

    with st.expander("操作说明"):
        st.markdown(
            """
            - 修改字段后，需要点击“保存为未确认 / 标记为已确认 / 标记为需复核”才会生效。
            - 删除误识别字段请勾选“是否忽略该字段”，保存后现场检测会跳过该字段。
            - 人工新增字段保存后会标记为 MANUAL_CONFIRMED，识别置信度为 1.0。
            - 标记为“已确认”的模板可以作为正式检测标准；“未确认”和“需复核”的模板仍可检测，但结果会提示风险。
            """
        )


def render_records_page() -> None:
    st.subheader("检测记录")
    records = load_quality_records(limit=200)
    if not records:
        st.info("暂无现场检测记录。")
        return

    summary_rows = [
        {
            "检测编号": record.get("inspection_id", ""),
            "时间": record.get("created_at", ""),
            "操作员": record.get("operator", ""),
            "工位": record.get("workstation", ""),
            "产品ID": record.get("product_id", ""),
            "图纸ID": record.get("drawing_id", ""),
            "图纸版本": record.get("drawing_version", ""),
            "SN": record.get("sn", ""),
            "批次": record.get("batch_no", ""),
            "结果": record.get("result", ""),
            "图片质量": quality_status_text((record.get("quality_result") or {}).get("quality_status", "")),
            "质量分": (record.get("quality_result") or {}).get("quality_score", ""),
            "二维码类型": qr_type_text((record.get("qr_result") or {}).get("qr_type", "")),
            "二维码匹配": match_status_text((record.get("qr_result") or {}).get("match_status", "")),
            "异常字段": "、".join(record.get("fail_fields", [])),
        }
        for record in records
    ]
    st.dataframe(
        pd.DataFrame(summary_rows),
        width="stretch",
        hide_index=True,
    )

    selected_id = st.selectbox(
        "查看记录详情",
        [row["检测编号"] for row in summary_rows],
    )
    selected_record = next(
        record for record in records if record.get("inspection_id") == selected_id
    )
    result_badge(selected_record.get("result", ""))
    render_quality_result_notice(selected_record.get("quality_result"))
    if selected_record.get("quality_result"):
        st.dataframe(
            quality_dataframe(selected_record.get("quality_result", {})),
            width="stretch",
            hide_index=True,
        )
    if selected_record.get("qr_result"):
        st.write("二维码匹配信息")
        st.json(selected_record.get("qr_result", {}))
    st.dataframe(
        style_result_rows(comparison_dataframe(selected_record.get("comparison_rows", []))),
        width="stretch",
        hide_index=True,
    )
    image_path = resolve_project_path(clean_text(selected_record.get("evidence_image", "")))
    if image_path and image_path.exists():
        st.image(str(image_path), caption="检测证据图", width="stretch")


def find_images(path: Path) -> list[Path]:
    return sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    )


def choose_label_images(sample_dir: Path, limit: int = 5) -> list[Path]:
    label_dirs = sorted(
        item
        for item in sample_dir.iterdir()
        if item.is_dir() and item.name.lower().startswith("label")
    )
    selected_images: list[Path] = []
    if label_dirs:
        for label_dir in label_dirs:
            images = find_images(label_dir)
            if images:
                selected_images.append(images[0])
    else:
        selected_images = find_images(sample_dir)
    return selected_images[:limit]


def scan_real_samples(data_dir: Path) -> list[dict[str, Any]]:
    if not data_dir.exists():
        return []
    samples: list[dict[str, Any]] = []
    for sample_dir in sorted(item for item in data_dir.iterdir() if item.is_dir()):
        pdfs = sorted(
            item
            for item in sample_dir.rglob("*")
            if item.is_file() and item.suffix.lower() == ".pdf"
        )
        images = choose_label_images(sample_dir, limit=20)
        if pdfs or images:
            samples.append(
                {
                    "sample_id": sample_dir.name,
                    "sample_dir": sample_dir,
                    "pdfs": pdfs,
                    "images": images,
                }
            )
    return samples


def summarize_real_samples(samples: list[dict[str, Any]], data_dir: Path) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "样本": sample["sample_id"],
                "PDF数量": len(sample["pdfs"]),
                "标签图片数量": len(sample["images"]),
                "首个PDF": (
                    str(sample["pdfs"][0].relative_to(data_dir))
                    if sample["pdfs"]
                    else ""
                ),
            }
            for sample in samples
        ]
    )


def resolve_real_data_dir(path_text: str) -> tuple[Path, list[Path]]:
    raw_path = Path(path_text).expanduser()
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append((PROJECT_ROOT / raw_path).resolve())
        candidates.append((PROJECT_ROOT.parent / raw_path).resolve())
        if str(raw_path).startswith("1/"):
            candidates.append((PROJECT_ROOT.parent / str(raw_path)[2:]).resolve())

    normalized_text = path_text.replace(" ", "").lower()
    if "data2" in normalized_text and "实物" in normalized_text:
        candidates.append(DEFAULT_REAL_IMAGE_DIR)
    if "实物" in normalized_text and "data" in normalized_text:
        candidates.append(DEFAULT_REAL_IMAGE_DIR)

    deduped_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            deduped_candidates.append(candidate)
            seen.add(key)

    for candidate in deduped_candidates:
        if candidate.exists():
            return candidate, deduped_candidates
    return deduped_candidates[0], deduped_candidates


def run_real_sample_validation(
    sample: dict[str, Any],
    max_labels: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not sample["pdfs"]:
        raise RuntimeError("该样本没有PDF图纸。")
    pdf_path = sample["pdfs"][0]
    drawing_result = extract_drawing_content(
        pdf_path,
        debug_output_dir=PROJECT_ROOT / "debug_output" / "real_samples",
        file_stem=f"{sample['sample_id']}_drawing",
    )
    drawing_fields = {
        field_name: value
        for field_name, value in drawing_result.get("fields", {}).items()
        if clean_text(value)
    }
    field_template = drawing_result.get("field_template", [])
    if field_template:
        drawing_fields = template_to_standard_fields(field_template)
    elif is_energy_label_standard(drawing_fields):
        drawing_fields = filter_energy_label_standard_fields(drawing_fields)
    if not drawing_fields:
        raise RuntimeError("PDF未解析出可比对标准字段。")

    validation_rows: list[dict[str, Any]] = []
    for image_index, image_path in enumerate(sample["images"][:max_labels], start=1):
        image_bytes = image_path.read_bytes()
        quality = evaluate_label_image(image_bytes)
        label_result = recognize_label(
            image_bytes,
            confidence_threshold=0.30,
            debug_output_dir=PROJECT_ROOT / "debug_output" / "real_samples",
            file_stem=f"{sample['sample_id']}_label_{image_index}",
        )
        if field_template:
            label_fields_for_compare, dynamic_debug = match_label_to_template(
                field_template,
                label_result.get("raw_text", ""),
                label_result.get("ocr_rows", []),
            )
            label_result["field_match_debug"] = {
                **label_result.get("field_match_debug", {}),
                **dynamic_debug,
            }
        else:
            label_fields_for_compare = {
                field_name: label_result.get("fields", {}).get(field_name, "")
                for field_name in drawing_fields
            }
        comparison_rows, overall_result = compare_fields(
            drawing_fields,
            label_fields_for_compare,
            label_result.get("field_match_debug", {}),
        )
        comparison_rows = enrich_comparison_rows_with_template(comparison_rows, field_template)
        overall_result = overall_from_rows(comparison_rows)
        validation_rows.append(
            {
                "样本": sample["sample_id"],
                "标签图片": image_path.name,
                "结果": overall_result,
                "PDF字段数": len(drawing_fields),
                "标签字段数": len(
                    [
                        value
                        for value in label_result.get("fields", {}).values()
                        if clean_text(value)
                    ]
                ),
                "OCR置信度": label_result.get("confidence", 0),
                "图片质量": quality["status"],
                "质量分": quality["score"],
                "异常字段": "、".join(
                    row["字段名称"]
                    for row in comparison_rows
                    if row.get("检测结果") == "FAIL"
                ),
                "需确认字段": "、".join(
                    row["字段名称"]
                    for row in comparison_rows
                    if row.get("检测结果") not in {"PASS", "FAIL"}
                ),
                "comparison_rows": comparison_rows,
                "label_fields": label_result.get("fields", {}),
                "ocr_text": label_result.get("raw_text", ""),
                "field_match_debug": label_result.get("field_match_debug", {}),
            }
        )
    return drawing_result, validation_rows


def render_real_image_validation_page() -> None:
    st.subheader("实物图验证")
    data_dir_text = st.text_input(
        "实物图目录",
        value=str(DEFAULT_REAL_IMAGE_DIR),
        help="你的路径可以填 1/data2/实物；当前项目识别到的真实样本目录是 data/实物图/data 2。",
    )
    data_dir, candidate_dirs = resolve_real_data_dir(data_dir_text)

    if not data_dir.exists():
        st.error(f"目录不存在：{data_dir}")
        st.info(f"当前可用默认目录：{DEFAULT_REAL_IMAGE_DIR}")
        with st.expander("尝试过的目录"):
            for candidate in candidate_dirs:
                st.write(str(candidate))
        return

    if str(data_dir) != data_dir_text:
        st.caption(f"实际使用目录：{data_dir}")

    samples = scan_real_samples(data_dir)
    if not samples:
        st.warning("没有扫描到包含PDF或标签图片的样本。")
        return

    st.success(f"已扫描到 {len(samples)} 个样本。")
    st.dataframe(
        summarize_real_samples(samples, data_dir),
        width="stretch",
        hide_index=True,
    )

    col_sample, col_limit = st.columns([2, 1])
    selected_sample_id = col_sample.selectbox(
        "选择要验证的样本",
        [sample["sample_id"] for sample in samples],
    )
    max_labels = col_limit.number_input(
        "最多验证标签数",
        min_value=1,
        max_value=10,
        value=2,
        step=1,
    )
    selected_sample = next(
        sample for sample in samples if sample["sample_id"] == selected_sample_id
    )

    if st.button("运行选中样本验证", type="primary", width="stretch"):
        with st.spinner("正在解析PDF并识别实物标签..."):
            drawing_result, validation_rows = run_real_sample_validation(
                selected_sample,
                max_labels=int(max_labels),
            )
        st.session_state["last_real_validation"] = {
            "sample_id": selected_sample_id,
            "drawing_result": drawing_result,
            "validation_rows": validation_rows,
        }

    validation = st.session_state.get("last_real_validation")
    if validation:
        st.divider()
        st.write(f"最近验证样本：{validation['sample_id']}")
        drawing_fields = {
            field_name: value
            for field_name, value in validation["drawing_result"].get("fields", {}).items()
            if clean_text(value)
        }
        if is_energy_label_standard(drawing_fields):
            drawing_fields = filter_energy_label_standard_fields(drawing_fields)
        st.write(f"PDF解析模式：{validation['drawing_result'].get('parse_mode', '-')}")
        st.dataframe(
            pd.DataFrame(
                [{"字段": field_name, "标准值": value} for field_name, value in drawing_fields.items()]
            ),
            width="stretch",
            hide_index=True,
        )
        rows_for_display = [
            {
                key: value
                for key, value in row.items()
                if key not in {"comparison_rows", "label_fields", "ocr_text"}
            }
            for row in validation["validation_rows"]
        ]
        st.dataframe(
            pd.DataFrame(rows_for_display),
            width="stretch",
            hide_index=True,
        )

        detail_labels = [row["标签图片"] for row in validation["validation_rows"]]
        if detail_labels:
            selected_label = st.selectbox("查看标签比对明细", detail_labels)
            selected_row = next(
                row for row in validation["validation_rows"] if row["标签图片"] == selected_label
            )
            st.dataframe(
                style_result_rows(comparison_dataframe(selected_row["comparison_rows"])),
                width="stretch",
                hide_index=True,
            )
            with st.expander("OCR原始文字"):
                st.text_area("OCR原始文字", selected_row["ocr_text"], height=220)

def main() -> None:
    ensure_storage()
    init_session_state()
    render_header()
    page = render_sidebar()
    if page == "演示模式":
        render_demo_mode_page()
    elif page == "现场检测端":
        render_inspection_page()
    elif page == "试运行验收":
        render_acceptance_page()
    elif page == "字段模板确认":
        render_template_confirmation_page()
    elif page == "图纸库管理":
        render_drawing_library_page()
    elif page == "后台管理":
        render_admin_page()
    elif page == "检测记录":
        render_records_page()
    elif page == "实物图验证":
        render_real_image_validation_page()


if __name__ == "__main__":
    main()
