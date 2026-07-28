# GitHub Actions 自动部署

## 发布模型

`main` 分支每次 push 都先执行测试。验证通过后，GitHub Actions 会：

1. 打包当前提交的代码归档
2. 用专用 SSH Key 通过受限命令 `receive <SHA>` 把归档流式写入 `/opt/haorizi/incoming/<SHA>.tar.gz`
3. 通过受限命令 `deploy <SHA>` 触发服务器安装与切换

服务器不会访问 GitHub，也不开放交互式 shell。这样可兼容 `my` 无法直接访问 `github.com:443` 的网络环境。

## 服务器目录

```text
/opt/haorizi/
├── backend -> releases/<sha>/backend
├── frontend -> releases/<sha>/frontend
├── current -> releases/<sha>
├── previous -> releases/<previous-sha>
├── incoming/<sha>.tar.gz
├── releases/<sha>/
├── backups/
└── shared/backend.env
```

systemd 和 Nginx 仍使用 `/opt/haorizi/backend`、`/opt/haorizi/frontend`，因此首次切换后不需要在每次发布时修改基础设施配置。

## GitHub 配置

仓库创建 `production` Environment，并配置：

- `DEPLOY_HOST`
- `DEPLOY_PORT`（默认 22，可留空）
- `DEPLOY_USER`（固定为受限部署用户 `haorizi-deploy`）
- `DEPLOY_SSH_KEY`（专用私钥）
- `DEPLOY_KNOWN_HOSTS`（预先核验的服务器 Host Key）

不要配置数据库连接、生产 `.env`、PushPlus Token 或 GitHub PAT。

## 首次切换

首次切换属于人工维护窗口：

1. 确认当前两个 systemd 服务和 Nginx 健康。
2. 检查生产 schema 和 migration 内容。
3. 创建专用 ed25519 SSH Key；私钥写入 GitHub Environment Secret，公钥单独传到服务器临时目录。
4. 在本地打出与目标 SHA 对应的归档，复制到服务器并执行：

   ```bash
   tar --exclude='.git' --exclude='backend/.env' --exclude='backend/.venv' \
     --exclude='backend/**/__pycache__' --exclude='**/*.pyc' --exclude='.pytest_cache' --exclude='*.db' \
     -czf /tmp/haorizi-<SHA>.tar.gz backend frontend deploy docs README.md CONTRIBUTING.md SECURITY.md pytest.ini .gitignore

   scp -r deploy my:/tmp/haorizi-bootstrap/
   scp /path/to/github-actions.pub /tmp/haorizi-<SHA>.tar.gz my:/tmp/

   ssh my "sudo /tmp/haorizi-bootstrap/bootstrap-github-deploy.sh \
     --sha <main 的完整 SHA> \
     --archive /tmp/haorizi-<SHA>.tar.gz \
     --public-key-file /tmp/github-actions.pub"
   ```

5. 验证页面、健康接口、API/worker 状态、worker 日志和数据库 revision。
6. 删除服务器临时公钥和临时归档。

bootstrap 会复制现有生产 `.env` 到 `shared/backend.env`，设置 `AUTO_CREATE_TABLES=false`，并把原有代码目录保存在 `legacy-<UTC 时间>` 下。它不会把生产配置上传 GitHub。

## 每次发布

服务器部署脚本按顺序执行：

1. `flock` 阻止并发部署。
2. 校验 `/opt/haorizi/incoming/<SHA>.tar.gz` 存在。
3. 解压到独立 release，创建/复用 venv 并安装 requirements。
4. 校验 `AUTO_CREATE_TABLES=false`。
5. 创建数据库备份。
6. 先停 worker，再停 API，执行 `alembic upgrade head`。
7. 原子切换 `current`、`backend` 和 `frontend` 软链。
8. 启动 API，通过健康检查后启动 worker。

## 回滚边界

代码和数据库的回滚不是同一件事：

- 如果发布没有改变 Alembic revision，健康检查失败时脚本会自动恢复上一份代码。
- 如果数据库 revision 已变化，脚本会保留数据库备份并停止服务，拒绝自动执行 `alembic downgrade`。
- migration 应优先使用 expand/contract，避免让旧代码立即无法兼容新 schema。

## 发布后检查

```bash
readlink -f /opt/haorizi/current
systemctl is-active haorizi-api haorizi-worker nginx
curl --fail --silent http://127.0.0.1:8000/api/public/health
journalctl -u haorizi-api -u haorizi-worker -n 100 --no-pager
```
