# 参与 HaoRiZi 开发

感谢参与改进 HaoRiZi。公开仓库采用 Fork/分支 + Pull Request 的协作方式，`main` 始终对应可发布状态。

## 开发流程

1. Fork 仓库，或由维护者邀请为 collaborator。
2. 从最新 `main` 创建功能分支，例如 `feature/admin-search` 或 `fix/reminder-retry`。
3. 按 `backend/.env.example` 创建本地 `backend/.env`，不要提交真实配置。
4. 安装依赖并运行测试：

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   cd ..
   python -m pytest -q
   ```

5. 提交 Pull Request，说明变更、验证结果和发布影响。

## 数据库变更

- SQLAlchemy 模型变化必须同时提交 Alembic migration。
- migration 需要支持从空数据库执行，也要说明已有生产数据的处理方式。
- 删除列、去重或不可逆数据转换必须在 PR 中明确标注，不能依赖 `create_all()`。

## 安全边界

- 禁止提交 `.env`、数据库文件、Cookie、Token、密码、私钥和生产日志。
- 不要在 Issue、PR、测试截图或 Actions 日志中粘贴生产凭据。
- 涉及 `.github/workflows/`、`deploy/` 和 `backend/alembic/` 的修改需要仓库维护者审核。

## 发布

合并到受保护的 `main` 后会触发生产发布。发布任务会重新运行测试，并只部署该次提交的完整 SHA；Pull Request 本身不会接触生产 Secrets，也不会发布生产环境。
