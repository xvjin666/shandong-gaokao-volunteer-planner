# GitHub 开源发布说明

本文件说明哪些内容适合进入公开 GitHub 仓库，哪些内容仅在本地保留。

## 本次整理原则

- 保留本地现有完整资料、数据、启动工具和交付包，不删除、不搬走。
- GitHub 源码包只放适合公开发布的源码、测试、文档、样例数据和来源清单。
- 开源包不包含真实完整数据库、官方网页/附件镜像、日志、备份、回滚快照、客户交付包和临时截图。

## 建议进入 GitHub 的内容

- `src/`
- `scripts/`
- `tests/`
- `docs/`
- `data/sample/`
- `data/sources/`
- `README.md`
- `DATA_SOURCES.md`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `CHANGELOG.md`
- `NOTICE`
- `pyproject.toml`
- `.gitignore`
- `.github/workflows/tests.yml`
- `start-sample-windows.bat`
- `start-sample-macos.command`

## 仅本地保留、不进入公开包

- `data/raw/`
- `data/processed/`
- `data/curated/`
- `data/local/`
- `data/uploads/`
- `dist/`
- `backups/`
- `rollback_snapshots/`
- `logs/`
- `reports/`
- `config/`
- `.cache/`
- `.pytest_cache/`
- `.vendor/`
- `*.sqlite`
- `*.db`
- `*.xls`
- `*.xlsx`
- `*.docx`
- `*.pdf`
- `*.zip`
- `tmp_*`
- `._*`
- `.DS_Store`

## 发布前检查

```bash
python -m pytest
```

并确认开源包内不存在：

```text
data/raw/
data/processed/
data/curated/
dist/
backups/
rollback_snapshots/
logs/
reports/
*.sqlite
*.xls
*.xlsx
*.docx
*.pdf
tmp_*
```
