from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from comparison import compare_fields
from drawing_parser import extract_drawing_content
from field_config import FIELD_NAMES, clean_text
from image_quality import evaluate_label_image
from ocr_parser import recognize_label
from product_store import (
    PROJECT_ROOT,
    append_quality_record,
    build_standard_snapshot,
    ensure_storage,
    get_product_by_index,
    load_products,
    load_quality_records,
    lookup_product,
    parse_qr_payload,
    product_options,
    resolve_project_path,
    save_evidence_image,
    save_uploaded_drawing,
    upsert_product,
)
from qr_parser import decode_qr_image


st.set_page_config(
    page_title="制造现场质量确认终端",
    page_icon="✓",
    layout="wide",
)


STATUS_COLOR = {
    "PASS": "#16794c",
    "FAIL": "#b42318",
    "待人工确认": "#946200",
}


def init_session_state() -> None:
    st.session_state.setdefault("operator_name", "operator")
    st.session_state.setdefault("workstation", "Line-A")
    st.session_state.setdefault("last_product_id", "")
    st.session_state.setdefault("last_inspection", None)


def render_header() -> None:
    st.title("制造现场质量确认终端")
    st.caption("Phase 1 本地化MVP｜扫码取标准数据、拍照OCR、字段级比对、检测记录快照")
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
                "现场检测端",
                "后台管理",
                "检测记录",
                "MVP路线图",
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
        "字段名称",
        "图纸值",
        "标签值",
        "检测结果",
        "异常说明",
        "置信度",
    ]
    return pd.DataFrame(rows)[visible_columns]


def style_result_rows(dataframe: pd.DataFrame):
    def highlight(row):
        result = row.get("检测结果", "")
        if result == "PASS":
            return ["background-color: #ecfdf3; color: #067647;" for _ in row]
        if result == "FAIL":
            return ["background-color: #fef3f2; color: #b42318; font-weight: 700;" for _ in row]
        return ["background-color: #fffaeb; color: #946200;" for _ in row]

    return dataframe.style.apply(highlight, axis=1)


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


def get_product_from_scan() -> tuple[dict[str, Any] | None, dict[str, str], str]:
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
        "演示二维码内容：PID=ABC-001;MODEL=ABC-001;SN=SN20260803001;BATCH=B20260803"
    )

    product, qr_payload = lookup_product(qr_text) if qr_text else (None, {})

    options = product_options()
    selected_label = ""
    if not product and options:
        selected_index = st.selectbox(
            "未扫码时，可手动选择产品用于测试",
            range(len(options)),
            format_func=lambda index: options[index],
        )
        product = get_product_by_index(selected_index)
        selected_label = options[selected_index]

    if product:
        st.success("标准数据已加载")
        display_product_card(product, qr_payload or parse_qr_payload(qr_text))
    else:
        st.warning("请先扫描二维码，或在后台添加产品标准数据。")

    return product, qr_payload, selected_label


def load_product_drawing_fields(product: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    drawing_path = resolve_project_path(clean_text(product.get("drawing_file", "")))
    if not drawing_path or not drawing_path.exists():
        return {}, ["当前产品未绑定PDF图纸，使用后台维护的标准字段。"]
    try:
        drawing_content = extract_drawing_content(drawing_path)
        warnings = list(drawing_content.get("warnings", []))
        warnings.append(f"图纸解析模式：{drawing_content.get('parse_mode', '-')}")
        return drawing_content.get("fields", {}), warnings
    except Exception as error:
        return {}, [f"图纸解析失败，使用后台维护的标准字段：{error}"]


def render_standard_snapshot(product: dict[str, Any]) -> dict[str, str]:
    st.subheader("2. 标准字段快照")
    drawing_fields, warnings = load_product_drawing_fields(product)
    standard_snapshot = build_standard_snapshot(product, drawing_fields)

    for warning in warnings:
        st.info(warning)

    if not standard_snapshot:
        st.warning("当前产品没有可比对的标准字段。请先到后台维护。")
    else:
        snapshot_rows = [
            {"字段": field_name, "标准值": value}
            for field_name, value in standard_snapshot.items()
        ]
        st.dataframe(
            pd.DataFrame(snapshot_rows),
            width="stretch",
            hide_index=True,
        )
    return standard_snapshot


def get_label_image_bytes() -> tuple[bytes | None, str]:
    st.subheader("3. 拍摄 / 上传标签")
    camera_file = st.camera_input("使用iPad摄像头拍摄标签")
    uploaded_file = st.file_uploader(
        "也可以上传标签图片进行测试",
        type=["jpg", "jpeg", "png"],
    )

    selected_file = camera_file or uploaded_file
    if selected_file is None:
        return None, ""

    image_bytes = selected_file.getvalue()
    filename = getattr(selected_file, "name", "camera_label.png") or "camera_label.png"
    quality = evaluate_label_image(image_bytes)

    metric_cols = st.columns(4)
    metric_cols[0].metric("图片质量", quality["status"])
    metric_cols[1].metric("质量分", quality["score"])
    metric_cols[2].metric("清晰度", quality["metrics"]["sharpness"])
    metric_cols[3].metric("反光比例", quality["metrics"]["glare_ratio"])

    if quality["warnings"]:
        for warning in quality["warnings"]:
            st.warning(warning)
    else:
        st.success("图片质量检查通过")

    return image_bytes, filename


def build_inspection_record(
    product: dict[str, Any],
    qr_payload: dict[str, str],
    standard_snapshot: dict[str, str],
    label_result: dict[str, Any],
    comparison_rows: list[dict[str, Any]],
    overall_result: str,
    evidence_path: str,
) -> dict[str, Any]:
    fail_fields = [
        row["字段名称"]
        for row in comparison_rows
        if row.get("检测结果") == "FAIL"
    ]
    unknown_fields = [
        row["字段名称"]
        for row in comparison_rows
        if row.get("检测结果") not in {"PASS", "FAIL"}
    ]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "operator": st.session_state.operator_name,
        "workstation": st.session_state.workstation,
        "product_id": product.get("product_id", ""),
        "product_model": product.get("product_model", ""),
        "product_version": product.get("version", ""),
        "sn": qr_payload.get("sn") or qr_payload.get("serial") or "",
        "batch_no": qr_payload.get("batch") or qr_payload.get("batch_no") or "",
        "qr_payload": qr_payload,
        "result": overall_result,
        "fail_fields": fail_fields,
        "unknown_fields": unknown_fields,
        "standard_snapshot": standard_snapshot,
        "label_fields": label_result.get("fields", {}),
        "comparison_rows": comparison_rows,
        "ocr_confidence": label_result.get("confidence", 0),
        "ocr_text": label_result.get("raw_text", ""),
        "ocr_rows": label_result.get("ocr_rows", []),
        "ocr_warnings": label_result.get("warnings", []),
        "selected_preprocess": label_result.get("selected_preprocess", ""),
        "evidence_image": evidence_path,
    }


def render_inspection_page() -> None:
    product, qr_payload, _ = get_product_from_scan()
    if not product:
        return

    standard_snapshot = render_standard_snapshot(product)
    image_bytes, filename = get_label_image_bytes()

    st.subheader("4. OCR识别与自动比对")
    can_run = bool(standard_snapshot and image_bytes)
    if st.button("开始检测", type="primary", disabled=not can_run, width="stretch"):
        with st.spinner("正在识别标签并比对标准字段..."):
            label_result = recognize_label(
                image_bytes,
                confidence_threshold=0.30,
                debug_output_dir=PROJECT_ROOT / "debug_output" / "quality_terminal",
                file_stem=f"{product.get('product_id', 'product')}_{datetime.now().strftime('%H%M%S')}",
            )
            label_fields_for_compare = {
                field_name: label_result.get("fields", {}).get(field_name, "")
                for field_name in standard_snapshot
            }
            comparison_rows, overall_result = compare_fields(
                standard_snapshot,
                label_fields_for_compare,
            )
            inspection_id = datetime.now().strftime("QT-%Y%m%d-%H%M%S-%f")
            evidence_path = save_evidence_image(
                image_bytes,
                inspection_id,
                filename,
            )
            record = build_inspection_record(
                product=product,
                qr_payload=qr_payload,
                standard_snapshot=standard_snapshot,
                label_result=label_result,
                comparison_rows=comparison_rows,
                overall_result=overall_result,
                evidence_path=evidence_path,
            )
            record["inspection_id"] = inspection_id
            saved_record = append_quality_record(record)
            st.session_state.last_inspection = saved_record

    if st.session_state.last_inspection:
        record = st.session_state.last_inspection
        result_badge(record["result"])
        if record["fail_fields"]:
            st.error(f"异常字段：{'、'.join(record['fail_fields'])}")
        if record["unknown_fields"]:
            st.warning(f"需人工确认：{'、'.join(record['unknown_fields'])}")

        st.dataframe(
            style_result_rows(comparison_dataframe(record["comparison_rows"])),
            width="stretch",
            hide_index=True,
        )

        with st.expander("OCR原始文字与调试信息"):
            st.write(f"OCR平均置信度：{record.get('ocr_confidence', 0)}")
            st.write(f"预处理方式：{record.get('selected_preprocess', '-')}")
            for warning in record.get("ocr_warnings", []):
                st.warning(warning)
            st.text_area(
                "OCR原始文字",
                value=record.get("ocr_text", ""),
                height=220,
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
        if uploaded_drawing is not None:
            drawing_file = save_uploaded_drawing(uploaded_drawing, product_id)

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
            "standard_fields": standard_fields,
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
            "SN": record.get("sn", ""),
            "批次": record.get("batch_no", ""),
            "结果": record.get("result", ""),
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
    st.dataframe(
        style_result_rows(comparison_dataframe(selected_record.get("comparison_rows", []))),
        width="stretch",
        hide_index=True,
    )
    image_path = resolve_project_path(clean_text(selected_record.get("evidence_image", "")))
    if image_path and image_path.exists():
        st.image(str(image_path), caption="检测证据图", width="stretch")


def render_roadmap_page() -> None:
    st.subheader("MVP开发路线图")
    st.markdown(
        """
        **Phase 1：本地验证版**

        - 本地产品主数据与标准字段管理
        - iPad Web拍照/上传标签
        - PaddleOCR识别与字段比对
        - 检测记录与证据图片留存

        **Phase 2：现场试用版**

        - 二维码扫码组件
        - FastAPI服务化
        - PostgreSQL / MinIO数据存储
        - PDF字段解析确认工作台
        - 低置信字段人工复核

        **Phase 3：工业化版本**

        - MES / PLM / ERP对接
        - OCR模型微调与边缘部署
        - 离线缓存与审计日志
        - 多工厂、多产线、多模板管理
        """
    )


def main() -> None:
    ensure_storage()
    init_session_state()
    render_header()
    page = render_sidebar()
    if page == "现场检测端":
        render_inspection_page()
    elif page == "后台管理":
        render_admin_page()
    elif page == "检测记录":
        render_records_page()
    else:
        render_roadmap_page()


if __name__ == "__main__":
    main()
