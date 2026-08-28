# 图纸驱动标签检测 MVP 试运行候选版 v0.5

发布日期：2026-08-28

## 版本定位

本版本用于客户演示、内部汇报和小范围现场试运行评估。当前系统仍不建议直接替代人工全检。

## 核心能力

- 图纸字段模板驱动检测。
- 字段模板人工确认。
- `include_in_inspection` 字段范围控制。
- 模板状态和字段比对结论解耦。
- 图片质量门禁。
- 二维码类型识别。
- 检测记录保存。
- demo A confirmed 模板。
- 真实样本轻量回归测试入口。
- OCR 模型缓存、图纸模板缓存和 OCR 输入图片安全缩放。
- 通用字段定义 `field_definitions.py`。
- 布局字段值绑定 `layout_value_binder.py`。
- 多语言字段别名、bbox 空间匹配、单位校验和值类型校验。
- 字段名误提取和跨字段错位防护。

## 当前验证结果

- demo A：7 PASS / 0 FAIL / 1 NEED_REVIEW。
- demo A 模板：`DEMO-CN-ENERGY-SAMPLE-A`，`confirmed`，`template_version=v2`，`template_confirmed_by=demo_seed`。
- 中东/阿曼样例：10 PASS / 0 FAIL / 0 NEED_REVIEW。
- 回归样例：7 个 case 均达标。
- records/evidence 写入已验证。

## 回归样例

| case_id | 结果 |
|---|---|
| cn_pass | 达标 |
| cn_fail_demo | 达标 |
| multilingual | 达标 |
| middle_east_energy_label | 达标 |
| bad_image | 达标 |
| qr_url | 达标 |
| template_unconfirmed | 达标 |

## 当前限制

- 多语言字段仍需继续通过更多真实样本扩充和验证。
- 首次新图纸解析可能较慢，试运行时建议先入库并确认模板。
- 真实现场图纸模板需人工确认。
- 本地 JSONL 记录不适合作为正式生产数据库。
- 正式上线前仍需数据库、权限、审批、审计和异常复核闭环。
- OCR 结果仍受拍照角度、反光、模糊和标签区域占比影响。
- 不建议直接替代人工全检。

## 部署后手动检查

- Streamlit Cloud 页面是否能打开。
- demo A 是否仍为 7 PASS / 0 FAIL / 1 NEED_REVIEW。
- 真实样本回归测试是否可运行。
- records/evidence 在部署环境是否可写。
- 页面是否仍然没有依赖 `/Users/weixuaner/Desktop` 本地绝对路径。
