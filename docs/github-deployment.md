# GitHub Actions 自动部署

## 发布模型

`main` 分支每次 push 都先执行测试。验证通过后，GitHub Actions 使用一把专用 SSH Key 连接生产服务器，并且只能提交如下命令：

```text
deploy <40 位小写 commit SHA>
```

服务器自行从公开仓库 fetch，确认 SHA 恰好是当前 `origin/main`，再创建独立 release、备份数据库、执行 Alembic migration、切换运行入口并检查 API 与 worker。GitHub 不保存数据库、PushPlus 或后台口令。

## 服务器目录

```text
/opt/haorizi/
├── backend -> releases/<sha>/backend
├── frontend -> releases/<sha>/frontend
├── current -> releases/<sha>
├── previous -> releases/<previous-sha>
├── repository.git/
├── releases/<sha>/
├── backups/
└── shared/backend.env
```

systemd 和 Nginx 仍使用 `/opt/haorizi/backend`、`/opt/haorizi/frontend`，因此首次切换后不需要在每次发布时修改基础设施配置。

## GitHub 配置

仓库创建 `production` Environment，并配置：

- `DEPLOY_HOST`
- `DEPLOY_PORT`（默认 22，可留空）
- `DEPLOY_USER`（固定为受限部署用户）
- `DEPLOY_SSH_KEY`（专用私钥）
- `DEPLOY_KNOWN_HOSTS`（预先核验的服务器 Host Key）

不要配置数据库连接、生产 `.env`、PushPlus Token 或 GitHub PAT。公开仓库由服务器通过 HTTPS 只读 fetch。

## 首次切换

首次切换属于人工维护窗口：

1. 确认当前两个 systemd 服务和 Nginx 健康。
2. 检查生产 schema、Alembic head 和 migration 内容。
3. 创建专用 ed25519 SSH Key；私钥写入 GitHub Environment Secret，公钥单独传到服务器临时目录。
4. 把本仓库复制到服务器临时目录，执行：

   ```bash
   sudo ./deploy/bootstrap-github-deploy.sh \
     --repo-url https://github.com/OWNER/haorizi.git \
     --sha <main 的完整 SHA> \
     --public-key-file <专用公钥文件>
   ```

5. 验证页面、健康接口、API/worker 状态、worker 日志和数据库 revision。
6. 删除服务器临时公钥文件；专用私钥不得保留在项目目录。

bootstrap 会复制现有生产 `.env` 到 `shared/backend.env`，设置 `AUTO_CREATE_TABLES=false`，并把原有代码目录保存在 `legacy-<UTC 时间>` 下。它不会把生产配置上传 GitHub。

## 每次发布

服务器部署脚本按顺序执行：

1. `flock` 阻止并发部署。
2. fetch 公开仓库并验证完整 SHA 等于 `origin/main`。
3. 准备独立 release 和虚拟环境，编译 Python 源码。
4. 校验 `AUTO_CREATE_TABLES=false`。
5. 创建数据库备份。
6. 先停 worker，再停 API，执行 `alembic upgrade head`。
7. 原子切换 `current`、`backend` 和 `frontend` 软链。
8. 启动 API，通过健康检查后启动 worker。

## 回滚边界

代码和数据库的回滚不是同一件事：

- 如果发布没有改变 Alembic revision，健康检查失败时脚本会自动恢复上一份代码。
- 如果数据库 revision 已变化，脚本会保留数据库备份并停止服务，拒绝自动执行 `alembic downgrade`；维护者必须检查 migration 的数据影响后再决定恢复数据库还是修复前进。
- migration 应优先使用 expand/contract，避免让旧代码立即无法兼容新 schema。

## 发布后检查

```bash
readlink -f /opt/haorizi/current
systemctl is-active haorizi-api haorizi-worker nginx
curl --fail --silent http://127.0.0.1:8000/api/public/health
journalctl -u haorizi-api -u haorizi-worker -n 100 --no-pager
```

还应验证公网 `/haorizi/`、`/haorizi-api/api/public/health`、进群和提醒 CRUD。生产 smoke 测试产生的数据需要有明确清理方式。
