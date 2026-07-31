from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


# =========================================================
# 路径配置
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parent

RECORDS_DIR = PROJECT_ROOT / "records"

REPORTS_DIR = RECORDS_DIR / "reports"

HISTORY_FILE = RECORDS_DIR / "detection_history.csv"

DETAIL_FILE = RECORDS_DIR / "detection_details.jsonl"


# =========================================================
# 历史记录字段
# =========================================================

HISTORY_HEADERS = [
    "检测编号",
    "检测时间",
    "图纸文件名",
    "标签文件名",
    "总体结果",
    "一致字段数量",
    "异常字段数量",
    "无法判断数量",
    "Excel报告路径",
]


# =========================================================
# 初始化目录
# =========================================================

def ensure_history_storage() -> None:
    """
    确保检测记录目录和基础文件存在。

    当历史CSV不存在、为空或缺少正确表头时，
    自动重新创建表头。
    """
    RECORDS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    history_file_needs_header = (
        not HISTORY_FILE.exists()
        or HISTORY_FILE.stat().st_size == 0
    )

    if not history_file_needs_header:
        try:
            with HISTORY_FILE.open(
                mode="r",
                newline="",
                encoding="utf-8-sig",
            ) as csv_file:
                reader = csv.reader(
                    csv_file
                )

                existing_headers = next(
                    reader,
                    [],
                )

            history_file_needs_header = (
                existing_headers
                != HISTORY_HEADERS
            )

        except Exception:
            history_file_needs_header = True

    if history_file_needs_header:
        with HISTORY_FILE.open(
            mode="w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=HISTORY_HEADERS,
            )

            writer.writeheader()

    if not DETAIL_FILE.exists():
        DETAIL_FILE.touch()

# =========================================================
# 检测编号
# =========================================================

def generate_detection_id() -> str:
    """
    生成唯一检测编号。

    示例：
    OCR-20260722-183012-452198
    """
    current_time = datetime.now()

    return current_time.strftime(
        "OCR-%Y%m%d-%H%M%S-%f"
    )


# =========================================================
# 统计结果
# =========================================================

def calculate_result_counts(
    comparison_rows: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """
    统计PASS、FAIL和无法判断数量。
    """
    pass_count = 0
    fail_count = 0
    unknown_count = 0

    for row in comparison_rows:
        result = str(
            row.get(
                "检测结果",
                "",
            )
        ).strip()

        if result == "PASS":
            pass_count += 1

        elif result == "FAIL":
            fail_count += 1

        else:
            unknown_count += 1

    return (
        pass_count,
        fail_count,
        unknown_count,
    )


# =========================================================
# 保存Excel报告
# =========================================================

def save_excel_report(
    report_bytes: bytes,
    report_filename: str,
) -> Path:
    """
    将Excel报告保存到records/reports目录。
    """
    ensure_history_storage()

    safe_filename = Path(
        report_filename
    ).name

    report_path = (
        REPORTS_DIR
        / safe_filename
    )

    report_path.write_bytes(
        report_bytes
    )

    return report_path


# =========================================================
# 保存检测汇总
# =========================================================

def append_history_row(
    history_row: dict[str, Any],
) -> None:
    """
    将一次检测汇总追加到CSV历史记录。
    """
    ensure_history_storage()

    normalized_row = {
        header: history_row.get(
            header,
            "",
        )
        for header in HISTORY_HEADERS
    }

    with HISTORY_FILE.open(
        mode="a",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=HISTORY_HEADERS,
        )

        writer.writerow(
            normalized_row
        )


# =========================================================
# 保存检测明细
# =========================================================

def append_detection_detail(
    detection_detail: dict[str, Any],
) -> None:
    """
    将完整检测明细保存为JSON Lines。

    每一行是一条完整检测记录。
    """
    ensure_history_storage()

    with DETAIL_FILE.open(
        mode="a",
        encoding="utf-8",
    ) as detail_file:
        detail_file.write(
            json.dumps(
                detection_detail,
                ensure_ascii=False,
            )
        )

        detail_file.write(
            "\n"
        )


# =========================================================
# 保存一次完整检测
# =========================================================

def save_detection_record(
    drawing_filename: str,
    label_filename: str,
    overall_result: str,
    comparison_rows: list[dict[str, Any]],
    drawing_fields: dict[str, str],
    label_fields: dict[str, str],
    drawing_text: str,
    label_text: str,
    ocr_rows: list[dict[str, Any]],
    excel_report_bytes: bytes,
    excel_report_filename: str,
) -> dict[str, Any]:
    """
    保存一次完整检测记录。

    包含：
    1. 保存Excel报告；
    2. 保存CSV汇总；
    3. 保存JSONL完整明细；
    4. 返回本次检测信息。
    """
    ensure_history_storage()

    detection_id = generate_detection_id()

    detection_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    (
        pass_count,
        fail_count,
        unknown_count,
    ) = calculate_result_counts(
        comparison_rows
    )

    report_path = save_excel_report(
        report_bytes=excel_report_bytes,
        report_filename=excel_report_filename,
    )

    relative_report_path = report_path.relative_to(
        PROJECT_ROOT
    )

    history_row = {
        "检测编号": detection_id,
        "检测时间": detection_time,
        "图纸文件名": drawing_filename,
        "标签文件名": label_filename,
        "总体结果": overall_result,
        "一致字段数量": pass_count,
        "异常字段数量": fail_count,
        "无法判断数量": unknown_count,
        "Excel报告路径": str(
            relative_report_path
        ),
    }

    append_history_row(
        history_row
    )

    detection_detail = {
        **history_row,
        "图纸字段": drawing_fields,
        "标签字段": label_fields,
        "字段比对明细": comparison_rows,
        "OCR识别明细": ocr_rows,
        "PDF原始文字": drawing_text,
        "标签OCR原始文字": label_text,
    }

    append_detection_detail(
        detection_detail
    )

    return history_row


# =========================================================
# 读取历史汇总
# =========================================================

def load_detection_history(
    limit: int | None = None,
) -> list[dict[str, str]]:
    """
    读取检测历史汇总。

    参数：
        limit：
            只返回最近多少条；
            None表示返回全部。
    """
    ensure_history_storage()

    with HISTORY_FILE.open(
        mode="r",
        newline="",
        encoding="utf-8-sig",
    ) as csv_file:
        reader = csv.DictReader(
            csv_file
        )

        history_rows = list(
            reader
        )

    history_rows.reverse()

    if limit is not None:
        return history_rows[
            :limit
        ]

    return history_rows


# =========================================================
# 根据编号读取完整明细
# =========================================================

def load_detection_detail(
    detection_id: str,
) -> dict[str, Any] | None:
    """
    根据检测编号读取完整检测明细。
    """
    ensure_history_storage()

    with DETAIL_FILE.open(
        mode="r",
        encoding="utf-8",
    ) as detail_file:
        for line in detail_file:
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(
                    line
                )
            except json.JSONDecodeError:
                continue

            if (
                record.get(
                    "检测编号"
                )
                == detection_id
            ):
                return record

    return None