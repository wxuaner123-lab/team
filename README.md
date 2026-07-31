# Drawing OCR MVP

PDF 图纸与实物标签 OCR 自动比对的 Streamlit MVP。

## 功能

- PDF 图纸文字解析，支持文本型 PDF 和扫描/转曲 PDF OCR fallback
- 实物标签图片 OCR，支持 EXIF 方向、裁剪、增强、二值化和旋转候选
- 图纸字段与标签字段自动比对
- 最多 5 张标签横向比对
- Excel 报告导出
- 历史记录保存和查询
- `data/实物图/data 2` 真实样本批量测试

## 本地启动

```bash
cd /path/to/drawing_ocr_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run app_batch_report.py
```

如果项目目录移动过，优先使用 `python -m streamlit ...`，不要直接调用 `.venv/bin/streamlit`。

## 推荐页面

- `app_batch_report.py`：推荐入口，支持 1-5 张标签、批量报告和历史记录
- `app.py`：单标签基础入口

## 批量测试

```bash
python test_data2.py
```

测试结果会写入：

- `debug_output/data2_test_results.json`
- `debug_output/data2_test_results.xlsx`
- `logs/ocr_debug.log`

这些调试和历史输出默认不会提交到 Git。

## 数据说明

项目包含本地样例数据和真实测试数据：

- `data/图纸标签OCR_MVP_五组测试样品`
- `data/实物图/data 2`
- `test_samples`

如果真实客户数据不适合公开，请在推送前移除或脱敏 `data/实物图/data 2`。
