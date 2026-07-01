# 山东高考志愿决策引擎

这是一个面向山东省普通类高考志愿填报的开源、本地优先决策系统。项目提供可解释推荐内核、数据导入校验、SQLite 数据库和命令行工具；内置数据只用于演示，真实填报数据由用户从官方渠道获取并在本地导入。

系统目标不是给出一句“推荐”，而是为每个“专业 + 院校”志愿提供可追溯、可比较、可证伪的依据。输出结果仅供辅助决策，正式填报必须以山东省教育招生考试院、高校招生章程和人工复核为准。

## 开源边界

- 开源：算法、数据模型、导入工具、校验逻辑、CLI、Web 本地服务、测试和样例数据。
- 内置：`data/sample/` 下的合成多年度样例数据，用来演示 2023-2026 多年度导入、推荐和位次换算流程。
- 不内置：官方原始网页/附件镜像、完整真实数据库、客户交付包、账号密码、授权文件、机器码、日志和备份。
- 用户自建：用户可以把自己合法取得并整理好的 CSV/XLSX 数据导入本地 SQLite 数据库，系统按 `year` 字段支持多个年度并存。

更多数据说明见 [DATA_SOURCES.md](DATA_SOURCES.md)。

## 安装

```bash
python -m pip install -e ".[test]"
```

如需导入 Excel：

```bash
python -m pip install -e ".[excel]"
```

## 运行合成样例

直接从 CSV 生成推荐：

```bash
python -m gaokao_decision.cli recommend \
  --admissions data/sample/admissions_sample.csv \
  --score 610 \
  --rank 32000 \
  --subjects 物理 化学 \
  --interests 计算机 电子 信息 \
  --max-tuition 12000 \
  --limit 12
```

构建开源样例 SQLite 数据库：

```bash
python -m gaokao_decision.cli build-sample-db \
  --db data/sample/open_demo.sqlite
```

也可以直接启动开源样例界面：

Windows：

```bat
start-sample-windows.bat
```

macOS：

```bash
chmod +x start-sample-macos.command
./start-sample-macos.command
```

从样例数据库生成冲稳保方案：

```bash
python -m gaokao_decision.cli plan-db \
  --db data/sample/open_demo.sqlite \
  --score 610 \
  --rank 32000 \
  --subjects 物理 化学 \
  --interests 计算机 电子 信息 \
  --strategy balanced \
  --target-size 96
```

按 2026 位次换算历年等效分，并生成方案：

```bash
python -m gaokao_decision.cli rank-plan-db \
  --db data/sample/open_demo.sqlite \
  --score 610 \
  --rank 32000 \
  --subjects 物理 化学 \
  --interests 计算机 软件 人工智能 电子 自动化 \
  --strategy balanced \
  --target-size 96 \
  --band-width 20
```

## 用户导入真实数据

初始化数据库：

```bash
python -m gaokao_decision.cli init-db --db data/local/my_gaokao.sqlite
```

导入招生/投档数据。文件可以包含一个或多个年度，必须有 `year` 列：

```bash
python -m gaokao_decision.cli import-admissions \
  --db data/local/my_gaokao.sqlite \
  --admissions path/to/admissions.csv \
  --batch-name sdzk_admissions_2023_2025
```

导入一分一段数据。CSV/XLSX 可以自带 `year` 和 `source_id` 列；如果文件没有这些列，可以用命令参数指定默认值：

```bash
python -m gaokao_decision.cli import-score-rank \
  --db data/local/my_gaokao.sqlite \
  --input path/to/score_rank.csv \
  --batch-name score_rank_2023_2026
```

旧版官方 `.xls` 文件建议先归档，再转换成 CSV/XLSX。项目也保留了官方一分一段 `.xls` 解析入口，但必须显式指定年份和来源：

```bash
python -m gaokao_decision.cli import-score-rank \
  --db data/local/my_gaokao.sqlite \
  --input path/to/official_score_rank.xls \
  --year 2026 \
  --source-id sdzk_2026_score_rank
```

## 数据字段

招生数据支持中英文字段名：

```text
year, source_id, school_code, school_name, major_code, major_name,
min_score, min_rank, plan_count, subjects, province, city,
school_level, school_type, tuition, tags
```

一分一段数据支持：

```text
year, source_id, score, segment_count, cumulative_count, subject_group
```

多年度通用性的核心规则是：同一数据库可以同时保存 2023、2024、2025、2026 或更多年度的数据；推荐、趋势、证据点和位次换算都按 `year` 聚合。

## 本地 Web 服务

```bash
python scripts/serve_app.py \
  --db data/sample/open_demo.sqlite \
  --host 127.0.0.1 \
  --port 8765
```

然后访问：

```text
http://127.0.0.1:8765/
```

## 测试

```bash
python -m pytest -q
```

## 发布前检查

公开仓库不应包含真实数据库、官方网页镜像、官方附件、客户包、授权信息、日志或备份。建议只发布源码、测试、文档、`data/sample/` 和 `data/sources/`。
