import re
from pathlib import Path

import pandas as pd
import pymupdf
import streamlit as st
from PIL import Image

from comparison import (
    compare_fields,
    extract_fields_from_label_text,
)
from history_manager import (
    load_detection_detail,
    load_detection_history,
    save_detection_record,
)
from ocr_parser import extract_label_text, recognize_label
from report_generator import generate_excel_report
from batch_comparison import (
    build_field_matrix,
    compare_multiple_labels,
    find_inconsistent_fields,
)
from batch_report_generator import (
    generate_batch_excel_report,
)
from drawing_parser import (
    debug_pdf_extraction as enhanced_debug_pdf_extraction,
    extract_drawing_content,
    extract_fields_from_pdf_text as enhanced_extract_fields_from_pdf_text,
    extract_pdf_text as enhanced_extract_pdf_text,
    score_pdf_extraction_modes as enhanced_score_pdf_extraction_modes,
)
from field_config import FIELD_CONFIG, FIELD_NAMES as ENHANCED_FIELD_NAMES


# =========================================================
# 页面配置
# =========================================================

st.set_page_config(
    page_title="图纸与标签一致性检测系统",
    page_icon="🔍",
    layout="wide",
)


# =========================================================
# 字段配置
# =========================================================

FIELD_NAMES = [
    "产品名称",
    "产品型号",
    "额定电压",
    "额定功率",
    "版本号",
    "序列号",
]


FIELD_ALIASES = {
    "产品名称": [
        "产品名称",
        "产品名称 / NAME",
        "产品名称/NAME",
        "NAME",
    ],
    "产品型号": [
        "产品型号",
        "产品型号 / MODEL",
        "产品型号/MODEL",
        "MODEL",
    ],
    "额定电压": [
        "额定电压",
        "额定电压 / VOLTAGE",
        "额定电压/VOLTAGE",
        "VOLTAGE",
    ],
    "额定功率": [
        "额定功率",
        "额定功率 / POWER",
        "额定功率/POWER",
        "POWER",
    ],
    "版本号": [
        "版本号",
        "版本号 / VERSION",
        "版本号/VERSION",
        "VERSION",
        "REVISION",
        "REV",
    ],
    "序列号": [
        "序列号",
        "序列号 / S/N",
        "序列号/S/N",
        "S/N",
        "SERIAL NUMBER",
        "SERIAL NO",
    ],
}


# =========================================================
# PDF文字提取
# =========================================================

def extract_pdf_text(
    pdf_bytes: bytes,
) -> tuple[str, int]:
    """
    使用多种模式提取PDF文字，并选择内容最完整的结果。
    """
    document = None

    try:
        document = pymupdf.open(
            stream=pdf_bytes,
            filetype="pdf",
        )

        page_results = []

        for page_number, page in enumerate(
            document,
            start=1,
        ):
            text_normal = page.get_text(
                "text",
                sort=False,
            ).strip()

            text_sorted = page.get_text(
                "text",
                sort=True,
            ).strip()

            blocks = page.get_text(
                "blocks",
                sort=True,
            )

            block_lines = []

            for block in blocks:
                if len(block) < 5:
                    continue

                block_text = str(
                    block[4]
                ).strip()

                if block_text:
                    block_lines.append(
                        block_text
                    )

            text_blocks = "\n".join(
                block_lines
            )

            words = page.get_text(
                "words",
                sort=True,
            )

            word_lines = []

            for word in words:
                if len(word) < 5:
                    continue

                word_text = str(
                    word[4]
                ).strip()

                if word_text:
                    word_lines.append(
                        word_text
                    )

            text_words = "\n".join(
                word_lines
            )

            candidate_texts = [
                text_normal,
                text_sorted,
                text_blocks,
                text_words,
            ]

            page_text = max(
                candidate_texts,
                key=len,
            )

            page_results.append(
                f"===== 第 {page_number} 页 =====\n"
                f"{page_text}"
            )

        return (
            "\n\n".join(page_results),
            document.page_count,
        )

    except Exception as error:
        raise RuntimeError(
            f"PDF解析失败：{error}"
        ) from error

    finally:
        if document is not None:
            document.close()


def debug_pdf_extraction(
    pdf_bytes: bytes,
) -> dict[str, str]:
    """
    输出第一页的多种PDF提取结果，用于诊断。
    """
    document = None

    try:
        document = pymupdf.open(
            stream=pdf_bytes,
            filetype="pdf",
        )

        if document.page_count == 0:
            return {
                "普通文本模式": "",
                "坐标排序模式": "",
                "文字块模式": "",
                "单词模式": "",
            }

        page = document[0]

        normal_text = page.get_text(
            "text",
            sort=False,
        ).strip()

        sorted_text = page.get_text(
            "text",
            sort=True,
        ).strip()

        blocks = page.get_text(
            "blocks",
            sort=True,
        )

        block_text = "\n".join(
            str(block[4]).strip()
            for block in blocks
            if len(block) >= 5
            and str(block[4]).strip()
        )

        words = page.get_text(
            "words",
            sort=True,
        )

        word_text = "\n".join(
            str(word[4]).strip()
            for word in words
            if len(word) >= 5
            and str(word[4]).strip()
        )

        return {
            "普通文本模式": normal_text,
            "坐标排序模式": sorted_text,
            "文字块模式": block_text,
            "单词模式": word_text,
        }

    except Exception as error:
        return {
            "诊断失败": str(error),
        }

    finally:
        if document is not None:
            document.close()


# =========================================================
# 图纸字段结构化
# =========================================================

def clean_text_line(
    line: str,
) -> str:
    """
    清理连续空格和首尾空格。
    """
    return re.sub(
        r"\s+",
        " ",
        str(line),
    ).strip()


def normalize_field_text(
    text: str,
) -> str:
    """
    标准化字段名称，便于匹配。
    """
    return (
        clean_text_line(text)
        .replace("：", ":")
        .replace("／", "/")
        .upper()
    )


def is_drawing_field_name(
    line: str,
) -> bool:
    """
    判断文字是否属于字段名称。
    """
    normalized_line = normalize_field_text(
        line
    )

    for aliases in FIELD_ALIASES.values():
        for alias in aliases:
            if normalized_line == normalize_field_text(
                alias
            ):
                return True

    return False


def extract_fields_from_pdf_text(
    pdf_text: str,
) -> dict[str, str]:
    """
    从PDF文字中提取关键字段。
    """
    fields = {
        field_name: ""
        for field_name in FIELD_NAMES
    }

    lines = [
        clean_text_line(line)
        for line in pdf_text.splitlines()
        if clean_text_line(line)
    ]

    # 方法1：字段名称和值位于相邻行
    for index, line in enumerate(lines):
        normalized_line = normalize_field_text(
            line
        )

        for field_name, aliases in FIELD_ALIASES.items():
            normalized_aliases = [
                normalize_field_text(alias)
                for alias in aliases
            ]

            if normalized_line not in normalized_aliases:
                continue

            for offset in range(1, 4):
                next_index = index + offset

                if next_index >= len(lines):
                    break

                candidate_value = lines[
                    next_index
                ]

                if is_drawing_field_name(
                    candidate_value
                ):
                    continue

                fields[
                    field_name
                ] = candidate_value

                break

    # 方法2：字段名称和值位于同一行
    for line in lines:
        for field_name, aliases in FIELD_ALIASES.items():
            if fields[field_name]:
                continue

            for alias in aliases:
                patterns = [
                    (
                        rf"^{re.escape(alias)}"
                        rf"\s*[:：]\s*(.+)$"
                    ),
                    (
                        rf"^{re.escape(alias)}"
                        rf"\s+(.+)$"
                    ),
                ]

                for pattern in patterns:
                    match = re.match(
                        pattern,
                        line,
                        flags=re.IGNORECASE,
                    )

                    if not match:
                        continue

                    value = clean_text_line(
                        match.group(1)
                    )

                    if value:
                        fields[
                            field_name
                        ] = value

                    break

                if fields[field_name]:
                    break

    return fields


def validate_fields(
    fields: dict[str, str],
) -> list[str]:
    """
    返回必填但未成功识别的字段。
    """
    return [
        field_name
        for field_name, rule in FIELD_CONFIG.items()
        if rule.required and not fields.get(field_name)
    ]


# =========================================================
# 表格辅助函数
# =========================================================

def create_field_dataframe(
    fields: dict[str, str],
    value_column_name: str,
) -> pd.DataFrame:
    """
    将结构化字段转换成表格。
    """
    rows = []

    display_field_names = [
        field_name
        for field_name in FIELD_NAMES
        if fields.get(field_name)
    ] or FIELD_NAMES[:6]

    for field_name in display_field_names:
        field_value = fields.get(
            field_name,
            "",
        )

        rows.append(
            {
                "字段名称": field_name,
                value_column_name: field_value,
                "识别状态": (
                    "成功"
                    if field_value
                    else "未识别"
                ),
            }
        )

    return pd.DataFrame(rows)


def style_comparison_dataframe(
    dataframe: pd.DataFrame,
):
    """
    为PASS、FAIL和无法判断设置背景提示。
    """

    def highlight_row(row):
        result = row.get(
            "检测结果",
            "",
        )

        if result == "PASS":
            style = (
                "background-color: #d9ead3;"
                "color: #274e13;"
            )

        elif result == "FAIL":
            style = (
                "background-color: #f4cccc;"
                "color: #9c0006;"
            )

        else:
            style = (
                "background-color: #fff2cc;"
                "color: #7f6000;"
            )

        return [
            style
            for _ in row
        ]

    return dataframe.style.apply(
        highlight_row,
        axis=1,
    )


# =========================================================
# 使用增强后的共享解析实现，保留原页面结构
# =========================================================

FIELD_NAMES = ENHANCED_FIELD_NAMES
extract_pdf_text = enhanced_extract_pdf_text
debug_pdf_extraction = enhanced_debug_pdf_extraction
score_pdf_extraction_modes = enhanced_score_pdf_extraction_modes
extract_fields_from_pdf_text = enhanced_extract_fields_from_pdf_text


# =========================================================
# 页面标题
# =========================================================

st.title(
    "制造业图纸与标签自动一致性检测系统"
)

st.caption(
    "MVP V1.1｜PDF解析、标签OCR、自动比对、Excel报告与历史记录"
)

st.divider()


# =========================================================
# 上传文件区域
# =========================================================

left_column, right_column = st.columns(
    2
)


with left_column:
    st.subheader(
        "1. 上传PDF图纸"
    )

    drawing_file = st.file_uploader(
        "请选择PDF格式的工程图纸",
        type=["pdf"],
        key="mvp_drawing_pdf_uploader",
    )

    if drawing_file is not None:
        st.success(
            f"图纸上传成功：{drawing_file.name}"
        )

        st.write(
            f"文件大小："
            f"{drawing_file.size / 1024:.2f} KB"
        )


with right_column:
    st.subheader(
        "2. 上传多张标签图片"
    )

    label_files = st.file_uploader(
        "请选择一张或多张JPG、JPEG或PNG格式的标签图片",
        type=[
            "jpg",
            "jpeg",
            "png",
        ],
        accept_multiple_files=True,
        key="mvp_batch_label_image_uploader",
    )

    if label_files:
        st.success(
            f"标签上传成功：共 {len(label_files)} 张"
        )

        if len(label_files) > 5:
            st.warning(
                "最多支持5张标签。本次请保留前5张或重新选择文件。"
            )

        preview_columns = st.columns(
            min(
                len(label_files),
                3,
            )
        )

        for index, uploaded_label in enumerate(
            label_files
        ):
            try:
                with preview_columns[
                    index % len(preview_columns)
                ]:
                    label_image = Image.open(
                        uploaded_label
                    )

                    st.image(
                        label_image,
                        caption=uploaded_label.name,
                        width="stretch",
                    )

            except Exception as error:
                st.error(
                    f"{uploaded_label.name}读取失败：{error}"
                )


st.divider()


# =========================================================
# 开始检测
# =========================================================

start_button = st.button(
    "开始检测",
    type="primary",
    width="stretch",
    key="mvp_start_detection_button",
)


if start_button:
    if drawing_file is None:
        st.warning(
            "请先上传PDF图纸。"
        )

    elif not label_files:
        st.warning(
            "请至少上传一张标签图片。"
        )

    elif len(label_files) > 5:
        st.warning(
            "最多支持5张标签，请重新选择文件后再开始检测。"
        )

    else:
        try:
            pdf_bytes = drawing_file.getvalue()

            # ---------------------------------------------
            # PDF解析与图纸字段提取
            # ---------------------------------------------

            with st.spinner(
                "正在解析PDF图纸……"
            ):
                drawing_content = extract_drawing_content(
                    pdf_bytes,
                    debug_output_dir=Path("debug_output"),
                    file_stem=Path(drawing_file.name).stem,
                )

                drawing_text = drawing_content[
                    "raw_text"
                ]

                page_count = drawing_content[
                    "page_count"
                ]

                debug_results = debug_pdf_extraction(
                    pdf_bytes
                )

                drawing_fields = drawing_content[
                    "fields"
                ]

                pdf_parse_mode = drawing_content[
                    "parse_mode"
                ]

                pdf_warnings = drawing_content.get(
                    "warnings",
                    [],
                )

            # ---------------------------------------------
            # 批量标签OCR、字段提取、图纸比对和历史保存
            # ---------------------------------------------

            label_results = []

            progress_bar = st.progress(
                0,
                text="准备识别标签……",
            )

            for index, uploaded_label in enumerate(
                label_files,
                start=1,
            ):
                progress_bar.progress(
                    int(
                        (index - 1)
                        / len(label_files)
                        * 100
                    ),
                    text=(
                        f"正在处理第 {index}/{len(label_files)} 张："
                        f"{uploaded_label.name}"
                    ),
                )

                label_bytes = uploaded_label.getvalue()

                current_label_result = recognize_label(
                    label_bytes,
                    confidence_threshold=0.30,
                    debug_output_dir=Path("debug_output"),
                    file_stem=(
                        f"label_{index}_"
                        f"{Path(uploaded_label.name).stem}"
                    ),
                )

                current_label_text = current_label_result[
                    "raw_text"
                ]

                current_label_ocr_rows = current_label_result[
                    "ocr_rows"
                ]

                for row in current_label_ocr_rows:
                    row.setdefault(
                        "预处理方式",
                        current_label_result[
                            "selected_preprocess"
                        ],
                    )

                current_label_fields = current_label_result[
                    "fields"
                ]

                # 保留旧函数调用链兼容：若增强结果为空，再用文本提取函数兜底。
                if not any(
                    current_label_fields.values()
                ):
                    current_label_fields = (
                        extract_fields_from_label_text(
                            current_label_text
                        )
                    )

                (
                    current_comparison_rows,
                    current_overall_result,
                ) = compare_fields(
                    drawing_fields,
                    current_label_fields,
                )

                (
                    current_excel_bytes,
                    current_excel_filename,
                ) = generate_excel_report(
                    drawing_filename=drawing_file.name,
                    label_filename=uploaded_label.name,
                    overall_result=current_overall_result,
                    comparison_rows=current_comparison_rows,
                    ocr_rows=current_label_ocr_rows,
                    drawing_text=drawing_text,
                    label_text=current_label_text,
                )

                current_history_row = save_detection_record(
                    drawing_filename=drawing_file.name,
                    label_filename=uploaded_label.name,
                    overall_result=current_overall_result,
                    comparison_rows=current_comparison_rows,
                    drawing_fields=drawing_fields,
                    label_fields=current_label_fields,
                    drawing_text=drawing_text,
                    label_text=current_label_text,
                    ocr_rows=current_label_ocr_rows,
                    excel_report_bytes=current_excel_bytes,
                    excel_report_filename=current_excel_filename,
                )

                label_results.append(
                    {
                        "文件名": uploaded_label.name,
                        "字段": current_label_fields,
                        "OCR文字": current_label_text,
                        "OCR明细": current_label_ocr_rows,
                        "图纸比对明细": current_comparison_rows,
                        "图纸比对结果": current_overall_result,
                        "Excel字节": current_excel_bytes,
                        "Excel文件名": current_excel_filename,
                        "历史记录": current_history_row,
                        "OCR置信度": current_label_result[
                            "confidence"
                        ],
                        "预处理方式": current_label_result[
                            "selected_preprocess"
                        ],
                        "OCR警告": current_label_result.get(
                            "warnings",
                            [],
                        ),
                    }
                )

            progress_bar.progress(
                100,
                text="全部标签处理完成。",
            )

            # ---------------------------------------------
            # 标签之间横向对比
            # ---------------------------------------------

            (
                batch_detail_rows,
                batch_summary_rows,
                batch_overall_result,
            ) = compare_multiple_labels(
                label_results,
                baseline_index=0,
            )

            for summary_row in batch_summary_rows:
                label_index = int(
                    summary_row.get(
                        "标签序号",
                        0,
                    )
                )
                if 1 <= label_index <= len(label_results):
                    source_result = label_results[
                        label_index - 1
                    ]
                    summary_row["预处理方式"] = source_result.get(
                        "预处理方式",
                        "",
                    )
                    summary_row["OCR平均置信度"] = source_result.get(
                        "OCR置信度",
                        "",
                    )
                    summary_row["OCR警告"] = "；".join(
                        source_result.get(
                            "OCR警告",
                            [],
                        )
                    )

            field_matrix_rows = build_field_matrix(
                label_results
            )

            inconsistent_rows = find_inconsistent_fields(
                label_results
            )

            batch_summary_dataframe = pd.DataFrame(
                batch_summary_rows
            )

            batch_detail_dataframe = pd.DataFrame(
                batch_detail_rows
            )

            field_matrix_dataframe = pd.DataFrame(
                field_matrix_rows
            )

            inconsistent_dataframe = pd.DataFrame(
                inconsistent_rows
            )

            # ---------------------------------------------
            # 生成批量检测总Excel报告
            # ---------------------------------------------

            with st.spinner(
                "正在生成批量检测总报告……"
            ):
                (
                    batch_excel_report_bytes,
                    batch_excel_report_filename,
                ) = generate_batch_excel_report(
                    drawing_filename=drawing_file.name,
                    batch_overall_result=batch_overall_result,
                    label_results=label_results,
                    batch_summary_rows=batch_summary_rows,
                    batch_detail_rows=batch_detail_rows,
                    field_matrix_rows=field_matrix_rows,
                    inconsistent_rows=inconsistent_rows,
                )

            # 兼容原有单标签详情页：默认展示第一张标签
            primary_result = label_results[0]

            label_text = primary_result[
                "OCR文字"
            ]

            label_ocr_rows = primary_result[
                "OCR明细"
            ]

            label_fields = primary_result[
                "字段"
            ]

            comparison_rows = primary_result[
                "图纸比对明细"
            ]

            overall_result = primary_result[
                "图纸比对结果"
            ]

            excel_report_bytes = primary_result[
                "Excel字节"
            ]

            excel_report_filename = primary_result[
                "Excel文件名"
            ]

            saved_history_row = primary_result[
                "历史记录"
            ]

            comparison_dataframe = pd.DataFrame(
                comparison_rows
            )

            st.success(
                f"批量处理完成：图纸共 {page_count} 页，"
                f"共识别 {len(label_results)} 张标签。"
            )

            st.info(
                f"PDF解析方式：{pdf_parse_mode}"
            )

            if pdf_warnings:
                with st.expander(
                    "PDF解析提示",
                    expanded=False,
                ):
                    for warning in pdf_warnings:
                        st.warning(
                            warning
                        )

            st.info(
                "每张标签均已生成独立Excel报告并保存检测历史。"
            )

            if len(label_results) == 1:
                st.warning(
                    "当前只上传了1张标签，无法执行多标签横向差异判断。"
                )

            elif batch_overall_result == "PASS":
                st.success(
                    "多标签横向对比通过：所有标签关键字段一致。"
                )

            else:
                st.error(
                    "多标签横向对比不通过：发现标签字段不一致或缺失。"
                )

            # ---------------------------------------------
            # 统计结果
            # ---------------------------------------------

            pass_count = int(
                (
                    comparison_dataframe[
                        "检测结果"
                    ] == "PASS"
                ).sum()
            )

            fail_count = int(
                (
                    comparison_dataframe[
                        "检测结果"
                    ] == "FAIL"
                ).sum()
            )

            unknown_count = int(
                (
                    comparison_dataframe[
                        "检测结果"
                    ] == "无法判断"
                ).sum()
            )

            (
                overall_column,
                pass_column,
                fail_column,
                unknown_column,
            ) = st.columns(4)

            with overall_column:
                st.metric(
                    label="总体检测结果",
                    value=overall_result,
                )

            with pass_column:
                st.metric(
                    label="一致字段",
                    value=pass_count,
                )

            with fail_column:
                st.metric(
                    label="异常字段",
                    value=fail_count,
                )

            with unknown_column:
                st.metric(
                    label="无法判断",
                    value=unknown_count,
                )

            if overall_result == "PASS":
                st.success(
                    "检测通过：图纸字段与标签字段全部一致。"
                )
            else:
                st.error(
                    "检测不通过：发现字段不一致、字段缺失或识别失败。"
                )

            # ---------------------------------------------
            # 结果标签页
            # ---------------------------------------------

            (
                batch_summary_tab,
                batch_compare_tab,
                comparison_tab,
                drawing_field_tab,
                label_field_tab,
                ocr_tab,
                raw_pdf_tab,
                history_tab,
            ) = st.tabs(
                [
                    "批量检测汇总",
                    "多标签横向对比",
                    "第一张标签与图纸",
                    "图纸结构化字段",
                    "第一张标签字段",
                    "第一张标签OCR",
                    "PDF原始文字",
                    "历史记录",
                ]
            )

            # =============================================
            # 批量检测汇总
            # =============================================

            with batch_summary_tab:
                st.subheader(
                    "各标签检测汇总"
                )

                st.dataframe(
                    batch_summary_dataframe,
                    width="stretch",
                    hide_index=True,
                )

                st.subheader(
                    "标签字段矩阵"
                )

                st.dataframe(
                    field_matrix_dataframe,
                    width="stretch",
                    hide_index=True,
                )

                batch_summary_csv = (
                    batch_summary_dataframe.to_csv(
                        index=False
                    ).encode(
                        "utf-8-sig"
                    )
                )

                download_left, download_right = st.columns(
                    2
                )

                with download_left:
                    st.download_button(
                        label="下载批量检测汇总CSV",
                        data=batch_summary_csv,
                        file_name="batch_detection_summary.csv",
                        mime="text/csv",
                        width="stretch",
                        key="download_batch_summary_csv",
                    )

                with download_right:
                    st.download_button(
                        label="下载批量检测总Excel报告",
                        data=batch_excel_report_bytes,
                        file_name=batch_excel_report_filename,
                        mime=(
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        ),
                        width="stretch",
                        key="download_batch_excel_report",
                    )

            # =============================================
            # 多标签横向对比
            # =============================================

            with batch_compare_tab:
                st.subheader(
                    "以第一张标签为基准的逐字段对比"
                )

                if batch_detail_dataframe.empty:
                    st.info(
                        "至少上传2张标签后才会生成横向对比明细。"
                    )
                else:
                    st.dataframe(
                        batch_detail_dataframe,
                        width="stretch",
                        hide_index=True,
                    )

                st.subheader(
                    "不一致字段汇总"
                )

                if inconsistent_dataframe.empty:
                    st.success(
                        "未发现标签之间存在字段差异。"
                    )
                else:
                    st.dataframe(
                        inconsistent_dataframe,
                        width="stretch",
                        hide_index=True,
                    )

                    inconsistent_csv = (
                        inconsistent_dataframe.to_csv(
                            index=False
                        ).encode(
                            "utf-8-sig"
                        )
                    )

                    st.download_button(
                        label="下载标签差异汇总CSV",
                        data=inconsistent_csv,
                        file_name="label_inconsistent_fields.csv",
                        mime="text/csv",
                        width="stretch",
                        key="download_label_inconsistent_csv",
                    )

            # =============================================
            # 自动比对结果
            # =============================================

            with comparison_tab:
                st.subheader(
                    "图纸与标签逐字段比对"
                )

                if comparison_dataframe.empty:
                    st.warning(
                        "没有生成比对结果。"
                    )

                else:
                    st.dataframe(
                        style_comparison_dataframe(
                            comparison_dataframe
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                    failed_rows = (
                        comparison_dataframe[
                            comparison_dataframe[
                                "检测结果"
                            ] != "PASS"
                        ]
                    )

                    if not failed_rows.empty:
                        st.subheader(
                            "异常明细"
                        )

                        for _, row in failed_rows.iterrows():
                            st.error(
                                f"{row['字段名称']}："
                                f"图纸值为「{row['图纸值']}」，"
                                f"标签值为「{row['标签值']}」。"
                                f"{row['异常说明']}"
                            )

                    csv_data = (
                        comparison_dataframe.to_csv(
                            index=False
                        ).encode(
                            "utf-8-sig"
                        )
                    )

                    st.download_button(
                        label="下载比对结果CSV",
                        data=csv_data,
                        file_name=(
                            "drawing_label_"
                            "comparison_result.csv"
                        ),
                        mime="text/csv",
                        width="stretch",
                        key="download_comparison_csv_button",
                    )

                    st.download_button(
                        label="下载正式Excel检测报告",
                        data=excel_report_bytes,
                        file_name=excel_report_filename,
                        mime=(
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        ),
                        width="stretch",
                        key="download_excel_report_button",
                    )

            # =============================================
            # 图纸结构化字段
            # =============================================

            with drawing_field_tab:
                drawing_dataframe = create_field_dataframe(
                    drawing_fields,
                    "图纸值",
                )

                st.dataframe(
                    drawing_dataframe,
                    width="stretch",
                    hide_index=True,
                )

                missing_drawing_fields = validate_fields(
                    drawing_fields
                )

                if missing_drawing_fields:
                    st.warning(
                        "图纸未识别字段："
                        + "、".join(
                            missing_drawing_fields
                        )
                    )
                else:
                    st.success(
                        "图纸六个字段全部提取成功。"
                    )

                st.subheader(
                    "图纸字段JSON"
                )

                st.json(
                    drawing_fields,
                    expanded=True,
                )

            # =============================================
            # 标签结构化字段
            # =============================================

            with label_field_tab:
                label_dataframe = create_field_dataframe(
                    label_fields,
                    "标签值",
                )

                st.dataframe(
                    label_dataframe,
                    width="stretch",
                    hide_index=True,
                )

                missing_label_fields = validate_fields(
                    label_fields
                )

                if missing_label_fields:
                    st.warning(
                        "标签未识别字段："
                        + "、".join(
                            missing_label_fields
                        )
                    )
                else:
                    st.success(
                        "标签六个字段全部提取成功。"
                    )

                st.subheader(
                    "标签字段JSON"
                )

                st.json(
                    label_fields,
                    expanded=True,
                )

            # =============================================
            # 标签OCR结果
            # =============================================

            with ocr_tab:
                st.subheader(
                    "标签OCR原始文字"
                )

                if label_text.strip():
                    st.text_area(
                        label="OCR识别文字",
                        value=label_text,
                        height=420,
                        key="label_ocr_text_area",
                    )

                    st.download_button(
                        label="下载标签OCR文字",
                        data=label_text,
                        file_name="label_ocr_text.txt",
                        mime="text/plain",
                        width="stretch",
                        key="download_label_ocr_text_button",
                    )

                else:
                    st.warning(
                        "标签图片未识别到文字。"
                    )

                st.subheader(
                    "OCR识别明细"
                )

                if label_ocr_rows:
                    label_ocr_dataframe = pd.DataFrame(
                        label_ocr_rows
                    )

                    st.dataframe(
                        label_ocr_dataframe,
                        width="stretch",
                        hide_index=True,
                    )

                    if (
                        "置信度"
                        in label_ocr_dataframe.columns
                    ):
                        average_score = float(
                            label_ocr_dataframe[
                                "置信度"
                            ].mean()
                        )

                        st.metric(
                            label="平均识别置信度",
                            value=f"{average_score:.2%}",
                        )

                        low_score_count = int(
                            (
                                label_ocr_dataframe[
                                    "置信度"
                                ] < 0.80
                            ).sum()
                        )

                        if low_score_count > 0:
                            st.warning(
                                f"有 {low_score_count} 条文字"
                                "的置信度低于80%。"
                            )

                else:
                    st.info(
                        "暂无OCR识别明细。"
                    )

            # =============================================
            # PDF原始文字
            # =============================================

            with raw_pdf_tab:
                if drawing_text.strip():
                    st.text_area(
                        label="PDF原始文字",
                        value=drawing_text,
                        height=420,
                        key="drawing_pdf_text_area",
                    )

                    st.download_button(
                        label="下载PDF提取文字",
                        data=drawing_text,
                        file_name="drawing_text.txt",
                        mime="text/plain",
                        width="stretch",
                        key="download_drawing_text_button",
                    )

                else:
                    st.warning(
                        "PDF没有提取到文字。"
                    )

                with st.expander(
                    "查看PDF提取诊断结果"
                ):
                    for index, (
                        method_name,
                        method_text,
                    ) in enumerate(
                        debug_results.items(),
                        start=1,
                    ):
                        st.markdown(
                            f"#### {method_name}"
                        )

                        st.text_area(
                            label=f"{method_name}结果",
                            value=method_text,
                            height=220,
                            key=(
                                f"pdf_debug_text_"
                                f"{index}"
                            ),
                        )

            # =============================================
            # 历史记录
            # =============================================

            with history_tab:
                st.subheader(
                    "历史检测记录"
                )

                history_rows = load_detection_history(
                    limit=200
                )

                if not history_rows:
                    st.info(
                        "暂无历史检测记录。"
                    )

                else:
                    history_dataframe = pd.DataFrame(
                        history_rows
                    )

                    filter_left, filter_right = st.columns(
                        2
                    )

                    with filter_left:
                        result_filter = st.selectbox(
                            "按总体结果筛选",
                            options=[
                                "全部",
                                "PASS",
                                "FAIL",
                            ],
                            key="history_result_filter",
                        )

                    with filter_right:
                        filename_filter = st.text_input(
                            "按图纸或标签文件名搜索",
                            value="",
                            key="history_filename_filter",
                        ).strip()

                    filtered_history = history_dataframe.copy()

                    if result_filter != "全部":
                        filtered_history = filtered_history[
                            filtered_history[
                                "总体结果"
                            ] == result_filter
                        ]

                    if filename_filter:
                        filename_mask = (
                            filtered_history[
                                "图纸文件名"
                            ].astype(str).str.contains(
                                filename_filter,
                                case=False,
                                na=False,
                            )
                            |
                            filtered_history[
                                "标签文件名"
                            ].astype(str).str.contains(
                                filename_filter,
                                case=False,
                                na=False,
                            )
                        )

                        filtered_history = filtered_history[
                            filename_mask
                        ]

                    st.caption(
                        f"共找到 {len(filtered_history)} 条记录"
                    )

                    st.dataframe(
                        filtered_history,
                        width="stretch",
                        hide_index=True,
                    )

                    if filtered_history.empty:
                        st.warning(
                            "当前筛选条件下没有记录。"
                        )

                    else:
                        detection_options = (
                            filtered_history[
                                "检测编号"
                            ].astype(str).tolist()
                        )

                        selected_detection_id = st.selectbox(
                            "选择检测编号查看完整详情",
                            options=detection_options,
                            key="history_detection_selector",
                        )

                        selected_detail = load_detection_detail(
                            selected_detection_id
                        )

                        if selected_detail is None:
                            st.error(
                                "未找到该检测编号对应的完整明细。"
                            )

                        else:
                            st.divider()

                            st.subheader(
                                "检测详情"
                            )

                            detail_col_1, detail_col_2, detail_col_3 = st.columns(
                                3
                            )

                            with detail_col_1:
                                st.metric(
                                    "检测编号",
                                    selected_detail.get(
                                        "检测编号",
                                        "",
                                    ),
                                )

                            with detail_col_2:
                                st.metric(
                                    "总体结果",
                                    selected_detail.get(
                                        "总体结果",
                                        "",
                                    ),
                                )

                            with detail_col_3:
                                st.metric(
                                    "检测时间",
                                    selected_detail.get(
                                        "检测时间",
                                        "",
                                    ),
                                )

                            st.write(
                                f"**图纸文件：** "
                                f"{selected_detail.get('图纸文件名', '')}"
                            )

                            st.write(
                                f"**标签文件：** "
                                f"{selected_detail.get('标签文件名', '')}"
                            )

                            (
                                detail_compare_tab,
                                detail_drawing_tab,
                                detail_label_tab,
                                detail_ocr_tab,
                                detail_text_tab,
                            ) = st.tabs(
                                [
                                    "字段比对明细",
                                    "图纸字段",
                                    "标签字段",
                                    "OCR明细",
                                    "原始文字",
                                ]
                            )

                            with detail_compare_tab:
                                detail_comparison_rows = selected_detail.get(
                                    "字段比对明细",
                                    [],
                                )

                                if detail_comparison_rows:
                                    detail_comparison_df = pd.DataFrame(
                                        detail_comparison_rows
                                    )

                                    st.dataframe(
                                        style_comparison_dataframe(
                                            detail_comparison_df
                                        ),
                                        width="stretch",
                                        hide_index=True,
                                    )
                                else:
                                    st.info(
                                        "该记录没有字段比对明细。"
                                    )

                            with detail_drawing_tab:
                                historical_drawing_fields = selected_detail.get(
                                    "图纸字段",
                                    {},
                                )

                                st.dataframe(
                                    create_field_dataframe(
                                        historical_drawing_fields,
                                        "图纸值",
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )

                                st.json(
                                    historical_drawing_fields,
                                    expanded=True,
                                )

                            with detail_label_tab:
                                historical_label_fields = selected_detail.get(
                                    "标签字段",
                                    {},
                                )

                                st.dataframe(
                                    create_field_dataframe(
                                        historical_label_fields,
                                        "标签值",
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )

                                st.json(
                                    historical_label_fields,
                                    expanded=True,
                                )

                            with detail_ocr_tab:
                                historical_ocr_rows = selected_detail.get(
                                    "OCR识别明细",
                                    [],
                                )

                                if historical_ocr_rows:
                                    st.dataframe(
                                        pd.DataFrame(
                                            historical_ocr_rows
                                        ),
                                        width="stretch",
                                        hide_index=True,
                                    )
                                else:
                                    st.info(
                                        "该记录没有OCR识别明细。"
                                    )

                            with detail_text_tab:
                                st.text_area(
                                    "历史PDF原始文字",
                                    value=selected_detail.get(
                                        "PDF原始文字",
                                        "",
                                    ),
                                    height=280,
                                    key=(
                                        "history_pdf_text_"
                                        f"{selected_detection_id}"
                                    ),
                                )

                                st.text_area(
                                    "历史标签OCR原始文字",
                                    value=selected_detail.get(
                                        "标签OCR原始文字",
                                        "",
                                    ),
                                    height=280,
                                    key=(
                                        "history_label_text_"
                                        f"{selected_detection_id}"
                                    ),
                                )

                            report_relative_path = selected_detail.get(
                                "Excel报告路径",
                                "",
                            )

                            if report_relative_path:
                                report_path = (
                                    Path(__file__).resolve().parent
                                    / report_relative_path
                                )

                                if report_path.exists():
                                    st.download_button(
                                        label="下载该历史记录的Excel报告",
                                        data=report_path.read_bytes(),
                                        file_name=report_path.name,
                                        mime=(
                                            "application/vnd.openxmlformats-"
                                            "officedocument.spreadsheetml.sheet"
                                        ),
                                        width="stretch",
                                        key=(
                                            "download_history_excel_"
                                            f"{selected_detection_id}"
                                        ),
                                    )
                                else:
                                    st.warning(
                                        "历史记录存在，但对应Excel报告文件未找到。"
                                    )

        except RuntimeError as error:
            st.error(
                str(error)
            )

        except Exception as error:
            st.error(
                f"程序运行失败：{error}"
            )
