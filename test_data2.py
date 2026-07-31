from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from batch_comparison import (
    build_field_matrix,
    compare_multiple_labels,
    find_inconsistent_fields,
)
from batch_report_generator import generate_batch_excel_report
from comparison import compare_fields
from drawing_parser import extract_drawing_content
from field_extractor import summarize_fields
from history_manager import save_detection_record
from ocr_parser import recognize_label
from report_generator import generate_excel_report


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA2 = PROJECT_ROOT / "data" / "实物图" / "data 2"
DEBUG_OUTPUT = PROJECT_ROOT / "debug_output"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "ocr_debug.log"
TEST_RESULTS_JSON = DEBUG_OUTPUT / "data2_test_results.json"
TEST_RESULTS_XLSX = DEBUG_OUTPUT / "data2_test_results.xlsx"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_images(path: Path) -> list[Path]:
    return sorted(
        p
        for p in path.rglob("*")
        if p.is_file()
        and p.suffix.lower()
        in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    )


def choose_label_images(sample_dir: Path) -> list[Path]:
    label_dirs = sorted(
        p
        for p in sample_dir.iterdir()
        if p.is_dir() and p.name.lower().startswith("label")
    )
    chosen: list[Path] = []
    if label_dirs:
        for label_dir in label_dirs:
            images = find_images(label_dir)
            if images:
                chosen.append(images[0])
    else:
        chosen = find_images(sample_dir)

    return chosen[:5]


def scan_cases(data2_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for sample_dir in sorted(p for p in data2_dir.iterdir() if p.is_dir()):
        pdfs = sorted(
            p
            for p in sample_dir.rglob("*")
            if p.is_file() and p.suffix.lower() == ".pdf"
        )
        labels = choose_label_images(sample_dir)
        if not pdfs and not labels:
            continue
        cases.append(
            {
                "case_id": sample_dir.name,
                "drawing": str(pdfs[0].relative_to(data2_dir)) if pdfs else "",
                "labels": [str(path.relative_to(data2_dir)) for path in labels],
            }
        )
    return cases


def load_or_create_cases(data2_dir: Path) -> list[dict[str, Any]]:
    config_path = data2_dir / "test_cases.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))

    cases = scan_cases(data2_dir)
    config_path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cases


def trim_for_excel(value: Any, limit: int = 30000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[trimmed {len(text) - limit} chars]"


def classify_failures(
    drawing_result: dict[str, Any],
    label_result: dict[str, Any],
    comparison_rows: list[dict[str, Any]],
    label_path: Path,
) -> list[str]:
    reasons: list[str] = []
    if drawing_result.get("parse_mode") == "ocr":
        reasons.append("PDF 是扫描件或关键字段需要 OCR 补充")
    if not drawing_result.get("raw_text", "").strip():
        reasons.append("PDF 没有解析出文字")
    if drawing_result.get("warnings"):
        reasons.extend(str(item) for item in drawing_result["warnings"])
    if not summarize_fields(drawing_result.get("fields", {})):
        reasons.append("PDF 字段名称未匹配或正则表达式不支持真实格式")
    if not summarize_fields(label_result.get("fields", {})):
        reasons.append("标签字段名称未匹配或 OCR 漏字/错字")
    if label_result.get("confidence", 1.0) < 0.65:
        reasons.append("OCR 不确定")
    if label_result.get("warnings"):
        reasons.extend(str(item) for item in label_result["warnings"])
    for row in comparison_rows:
        status = row.get("字段状态")
        if status == "mismatch":
            reasons.append(f"{row.get('字段名称')} 字段值没有标准化或真实不一致")
        elif status == "label_missing":
            reasons.append(f"{row.get('字段名称')} 标签缺失或未识别")
        elif status == "drawing_missing":
            reasons.append(f"{row.get('字段名称')} 图纸缺失或未识别")
    if label_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        # 详细图像质量指标在 data2 文件清单阶段输出；这里保留处理层判断。
        if "90" in str(label_result.get("selected_preprocess", "")):
            reasons.append("标签图片旋转")
    return sorted(set(reason for reason in reasons if reason))


def run_case(
    case: dict[str, Any],
    data2_dir: Path,
    save_history: bool,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    logging.info("case=%s stage=start", case_id)
    started = time.perf_counter()
    drawing_path = data2_dir / case["drawing"]
    label_paths = [data2_dir / label for label in case.get("labels", [])]
    case_debug_dir = DEBUG_OUTPUT

    result: dict[str, Any] = {
        "case_id": case_id,
        "drawing_file": str(drawing_path.relative_to(data2_dir)),
        "label_files": [str(path.relative_to(data2_dir)) for path in label_paths],
        "labels": [],
        "errors": [],
    }

    drawing_started = time.perf_counter()
    try:
        drawing_result = extract_drawing_content(
            drawing_path,
            debug_output_dir=case_debug_dir,
            file_stem=f"{case_id}_drawing",
        )
    except Exception as error:
        drawing_result = {
            "raw_text": "",
            "fields": {},
            "parse_mode": "error",
            "warnings": [str(error)],
            "page_count": 0,
        }
        result["errors"].append(f"PDF处理失败：{error}")
        logging.exception("case=%s stage=pdf error=%s", case_id, error)

    result["drawing"] = drawing_result
    result["timings"] = {
        "pdf_parse_seconds": round(time.perf_counter() - drawing_started, 3)
    }

    label_items: list[dict[str, Any]] = []
    all_report_seconds = 0.0
    all_compare_seconds = 0.0
    all_history_seconds = 0.0

    for label_index, label_path in enumerate(label_paths, start=1):
        label_started = time.perf_counter()
        label_entry: dict[str, Any] = {
            "label_index": label_index,
            "label_file": str(label_path.relative_to(data2_dir)),
        }
        try:
            label_result = recognize_label(
                label_path.read_bytes(),
                confidence_threshold=0.30,
                debug_output_dir=case_debug_dir,
                file_stem=f"{case_id}_label_{label_index}",
            )
            label_entry["ocr"] = label_result
        except Exception as error:
            label_result = {
                "raw_text": "",
                "fields": {},
                "confidence": 0.0,
                "selected_preprocess": "error",
                "warnings": [str(error)],
                "ocr_rows": [],
            }
            label_entry["ocr"] = label_result
            label_entry["error"] = str(error)
            result["errors"].append(f"{label_path.name} OCR失败：{error}")
            logging.exception("case=%s label=%s stage=ocr error=%s", case_id, label_path, error)

        label_entry["timings"] = {
            "image_preprocess_and_ocr_seconds": round(time.perf_counter() - label_started, 3)
        }

        compare_started = time.perf_counter()
        comparison_rows, overall = compare_fields(
            drawing_result.get("fields", {}),
            label_result.get("fields", {}),
        )
        compare_seconds = time.perf_counter() - compare_started
        all_compare_seconds += compare_seconds

        report_started = time.perf_counter()
        excel_report_bytes = b""
        excel_report_filename = ""
        try:
            excel_report_bytes, excel_report_filename = generate_excel_report(
                drawing_filename=drawing_path.name,
                label_filename=label_path.name,
                overall_result=overall,
                comparison_rows=comparison_rows,
                ocr_rows=label_result.get("ocr_rows", []),
                drawing_text=drawing_result.get("raw_text", ""),
                label_text=label_result.get("raw_text", ""),
            )
        except Exception as error:
            result["errors"].append(f"{label_path.name} Excel生成失败：{error}")
            logging.exception("case=%s label=%s stage=excel error=%s", case_id, label_path, error)
        report_seconds = time.perf_counter() - report_started
        all_report_seconds += report_seconds

        history_row = {}
        if save_history and excel_report_bytes:
            history_started = time.perf_counter()
            try:
                history_row = save_detection_record(
                    drawing_filename=drawing_path.name,
                    label_filename=label_path.name,
                    overall_result=overall,
                    comparison_rows=comparison_rows,
                    drawing_fields=drawing_result.get("fields", {}),
                    label_fields=label_result.get("fields", {}),
                    drawing_text=drawing_result.get("raw_text", ""),
                    label_text=label_result.get("raw_text", ""),
                    ocr_rows=label_result.get("ocr_rows", []),
                    excel_report_bytes=excel_report_bytes,
                    excel_report_filename=excel_report_filename,
                )
            except Exception as error:
                result["errors"].append(f"{label_path.name} 历史记录保存失败：{error}")
                logging.exception("case=%s label=%s stage=history error=%s", case_id, label_path, error)
            all_history_seconds += time.perf_counter() - history_started

        label_entry.update(
            {
                "label_fields": label_result.get("fields", {}),
                "comparison_rows": comparison_rows,
                "overall_result": overall,
                "failure_reasons": classify_failures(
                    drawing_result,
                    label_result,
                    comparison_rows,
                    label_path,
                ),
                "excel_report_filename": excel_report_filename,
                "history_record": history_row,
            }
        )
        label_entry["timings"].update(
            {
                "field_compare_seconds": round(compare_seconds, 3),
                "report_generate_seconds": round(report_seconds, 3),
            }
        )
        result["labels"].append(label_entry)
        label_items.append(
            {
                "文件名": str(label_path.relative_to(data2_dir)),
                "字段": label_result.get("fields", {}),
                "OCR文字": label_result.get("raw_text", ""),
                "OCR明细": label_result.get("ocr_rows", []),
                "图纸比对明细": comparison_rows,
                "图纸比对结果": overall,
            }
        )
        logging.info(
            "case=%s label=%s stage=done overall=%s fields=%s elapsed=%.3f",
            case_id,
            label_path.name,
            overall,
            len(summarize_fields(label_result.get("fields", {}))),
            label_entry["timings"]["image_preprocess_and_ocr_seconds"],
        )

    batch_started = time.perf_counter()
    batch_detail_rows, batch_summary_rows, batch_overall = compare_multiple_labels(label_items)
    field_matrix_rows = build_field_matrix(label_items)
    inconsistent_rows = find_inconsistent_fields(label_items)
    batch_report_bytes = b""
    batch_report_filename = ""
    try:
        batch_report_bytes, batch_report_filename = generate_batch_excel_report(
            drawing_filename=drawing_path.name,
            batch_overall_result=batch_overall,
            label_results=label_items,
            batch_summary_rows=batch_summary_rows,
            batch_detail_rows=batch_detail_rows,
            field_matrix_rows=field_matrix_rows,
            inconsistent_rows=inconsistent_rows,
        )
    except Exception as error:
        result["errors"].append(f"批量Excel生成失败：{error}")
        logging.exception("case=%s stage=batch_excel error=%s", case_id, error)

    result["batch_comparison"] = {
        "detail_rows": batch_detail_rows,
        "summary_rows": batch_summary_rows,
        "field_matrix_rows": field_matrix_rows,
        "inconsistent_rows": inconsistent_rows,
        "overall_result": batch_overall,
        "batch_excel_report_filename": batch_report_filename,
        "batch_excel_report_size": len(batch_report_bytes),
    }
    result["timings"].update(
        {
            "field_compare_seconds": round(all_compare_seconds, 3),
            "report_generate_seconds": round(all_report_seconds, 3),
            "history_save_seconds": round(all_history_seconds, 3),
            "batch_compare_and_report_seconds": round(time.perf_counter() - batch_started, 3),
            "total_seconds": round(time.perf_counter() - started, 3),
        }
    )
    logging.info(
        "case=%s stage=complete batch_overall=%s elapsed=%.3f",
        case_id,
        batch_overall,
        result["timings"]["total_seconds"],
    )
    return result


def save_results(results: list[dict[str, Any]]) -> None:
    DEBUG_OUTPUT.mkdir(parents=True, exist_ok=True)
    TEST_RESULTS_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_rows = []
    drawing_rows = []
    label_rows = []
    comparison_rows = []
    horizontal_rows = []

    for case in results:
        drawing_fields = case.get("drawing", {}).get("fields", {})
        summary_rows.append(
            {
                "案例编号": case["case_id"],
                "图纸文件": case["drawing_file"],
                "PDF解析方式": case.get("drawing", {}).get("parse_mode", ""),
                "PDF页数": case.get("drawing", {}).get("page_count", ""),
                "图纸字段数": len(summarize_fields(drawing_fields)),
                "标签数量": len(case.get("labels", [])),
                "标签横向比对": case.get("batch_comparison", {}).get("overall_result", ""),
                "错误信息": "；".join(case.get("errors", [])),
                "处理耗时": case.get("timings", {}).get("total_seconds", ""),
            }
        )
        for field_name, field_value in drawing_fields.items():
            if field_value:
                drawing_rows.append(
                    {
                        "案例编号": case["case_id"],
                        "图纸文件": case["drawing_file"],
                        "字段": field_name,
                        "值": field_value,
                    }
                )
        for label in case.get("labels", []):
            ocr = label.get("ocr", {})
            label_rows.append(
                {
                    "案例编号": case["case_id"],
                    "标签文件": label["label_file"],
                    "OCR预处理方式": ocr.get("selected_preprocess", ""),
                    "OCR置信度": ocr.get("confidence", ""),
                    "整体结果": label.get("overall_result", ""),
                    "失败原因": "；".join(label.get("failure_reasons", [])),
                    "OCR原始文字": trim_for_excel(ocr.get("raw_text", "")),
                }
            )
            for row in label.get("comparison_rows", []):
                row_copy = dict(row)
                row_copy["案例编号"] = case["case_id"]
                row_copy["标签文件"] = label["label_file"]
                comparison_rows.append(row_copy)
        for row in case.get("batch_comparison", {}).get("detail_rows", []):
            row_copy = dict(row)
            row_copy["案例编号"] = case["case_id"]
            horizontal_rows.append(row_copy)

    with pd.ExcelWriter(TEST_RESULTS_XLSX, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="案例汇总", index=False)
        pd.DataFrame(drawing_rows).to_excel(writer, sheet_name="图纸字段", index=False)
        pd.DataFrame(label_rows).to_excel(writer, sheet_name="标签OCR", index=False)
        pd.DataFrame(comparison_rows).to_excel(writer, sheet_name="图纸标签比对", index=False)
        pd.DataFrame(horizontal_rows).to_excel(writer, sheet_name="标签横向比对", index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量测试 data 2 真实图纸和标签。")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA2),
        help="真实测试数据目录，默认 data/实物图/data 2",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="只测试，不写入 records 历史记录。",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    data2_dir = Path(args.data_dir)
    cases = load_or_create_cases(data2_dir)
    logging.info("stage=scan cases=%s data_dir=%s", len(cases), data2_dir)
    results = []
    for case in cases:
        results.append(
            run_case(
                case,
                data2_dir=data2_dir,
                save_history=not args.no_history,
            )
        )
        save_results(results)
        print(
            json.dumps(
                {
                    "案例编号": case["case_id"],
                    "结果文件": str(TEST_RESULTS_JSON),
                    "已完成案例数": len(results),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    save_results(results)
    print(f"JSON结果：{TEST_RESULTS_JSON}")
    print(f"Excel结果：{TEST_RESULTS_XLSX}")
    print(f"日志：{LOG_FILE}")


if __name__ == "__main__":
    main()
