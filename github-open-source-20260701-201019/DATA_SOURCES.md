# 数据来源与发布政策

本项目定位为开源决策引擎，可以内置少量可发布数据用于演示和测试，但不把受限数据、客户数据或官方网页镜像作为开源仓库内容发布。

## 内置数据

`data/sample/` 下的数据是合成样例：

- `admissions_sample.csv`：多年度招生/投档样例，覆盖 2023-2025。
- `score_rank_sample.csv`：多年度一分一段样例，覆盖 2023-2026。

这些文件的 `source_id` 使用 `demo_sample_not_official`，只用于演示导入、推荐、冲稳保和位次换算流程，不代表真实录取数据。

## 用户导入数据

用户可以在本地导入自己合法取得的数据。系统支持一个数据库内保存多个年度的数据，核心字段是 `year`。

招生/投档数据建议字段：

```text
year, source_id, school_code, school_name, major_code, major_name,
min_score, min_rank, plan_count, subjects, province, city,
school_level, school_type, tuition, tags
```

一分一段数据建议字段：

```text
year, source_id, score, segment_count, cumulative_count, subject_group
```

导入后应保留本地原始文件、来源 URL、下载时间、字段映射、清洗脚本和校验报告。正式填报前必须人工复核院校招生章程、选科要求、体检限制、学费、校区和计划变更。

## 不进入开源仓库的数据

以下内容不得提交到公开仓库：

- 山东省教育招生考试院原始 HTML 页面、附件镜像或整站归档。
- 未确认开放授权的第三方网页、图片、表格和 PDF。
- 完整真实 SQLite 数据库、清洗后的全量官方数据集。
- 客户交付包、账号密码、授权码、机器码、license 文件。
- 日志、报告、备份、回滚快照和本地临时文件。

## 官方数据处理建议

开源仓库可以保存官方来源清单、下载脚本和转换脚本。用户在本地运行这些脚本时，应确认自己对数据的使用方式符合来源网站条款和适用法规。

如果后续需要发布部分真实基础数据，建议只发布经过法律和来源授权复核的最小数据集，并在文件中标记：

- `source_id`
- `source_type`
- `collected_at`
- `license_or_terms`
- `confidence`
- `limitations`

任何网络汇编、用户补充或未完整公开的资料，都不能标成官方完整数据。
