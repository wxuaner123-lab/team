# Drawing OCR MVP

PDF 图纸与实物标签 OCR 自动比对的 Streamlit MVP。

## 功能

- Phase 1 产品化现场端：扫码/输入二维码、加载产品标准数据、拍摄标签、OCR比对、保存记录
- 本地后台管理：维护产品型号、二维码样例、标准字段、绑定PDF图纸
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

- `app_quality_terminal.py`：产品化 Phase 1 入口，包含现场检测端、后台管理、检测记录和MVP路线图
- `app_batch_report.py`：推荐入口，支持 1-5 张标签、批量报告和历史记录
- `app.py`：单标签基础入口

启动产品化现场端：

```bash
python -m streamlit run app_quality_terminal.py
```

默认会在本地生成一个演示产品：

```text
PID=ABC-001;MODEL=ABC-001;SN=SN20260803001;BATCH=B20260803
```

该二维码内容可以直接粘贴到“现场检测端”测试流程。

也会生成一个绑定内置样例图纸的演示产品：

```text
PID=ICM-2400-A;MODEL=ICM-2400-A;SN=ICM2400A-260701;BATCH=DEMO-BATCH
```

可配合以下标签图片测试：

```text
test_samples/图纸标签OCR_MVP_批量横向对比测试样品_兼容版/batch_sample_compatible/label_001_baseline.png
```

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

本地运行产生的产品主数据、上传图纸和检测证据默认不会提交到 Git：

- `master_data/products.json`
- `master_data/drawings/`
- `records/`
