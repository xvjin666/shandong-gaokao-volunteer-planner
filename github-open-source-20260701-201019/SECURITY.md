# 安全政策

## 报告范围

欢迎报告以下问题：

- 账号、密码、授权码、机器码或其他敏感信息误提交。
- 未授权数据、客户数据、日志或完整数据库被纳入发布包。
- 本地 Web 服务存在任意文件读取、命令执行、跨站脚本或越权访问风险。
- 数据导入过程可能导致静默错误、错误年份混入或错误来源标记。

## 报告方式

请通过 GitHub Security Advisory 或维护者在仓库中公布的安全联系方式报告。不要在公开 issue 中粘贴真实账号、密码、授权码、机器码、客户信息或未授权数据样本。

## 发布要求

公开发布前应运行：

```bash
python -m pytest -q
git status --short
```

并确认仓库不包含：

- `dist/`
- `backups/`
- `rollback_snapshots/`
- `logs/`
- `reports/`
- `config/`
- `data/raw/`
- `data/processed/`
- `data/curated/`
- `*.sqlite`
- `*.db`
- `*.zip`
- `*.xls`
- `*.xlsx`
- `*.docx`
- `*.pdf`
- `tmp_*`

如果敏感信息已经进入 Git 历史，必须撤销或轮换相应凭据，并使用历史清理工具重写仓库历史；仅在最新提交删除文件是不够的。
