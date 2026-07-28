# HaoRiZi 部署与运维

## 服务组成

- `haorizi-api`：FastAPI，监听 `127.0.0.1:8000`
- `haorizi-worker`：每分钟扫描提醒计划
- MySQL：生产数据库
- Nginx：HTTPS 与静态 H5

## 安装

```bash
cd /opt/haorizi/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
```

生产必须修改：

- `DATABASE_URL`
- `SESSION_SECRET`
- `ADMIN_TOKEN`
- `PUBLIC_BASE_URL`
- `CORS_ORIGINS`
- `TRUSTED_PROXY_IPS`
- `PUSHPLUS_TOKEN`
- `PUSHPLUS_SECRET_KEY`

安装 `deploy/` 下的 systemd 与 Nginx 示例后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now haorizi-api haorizi-worker
sudo nginx -t
sudo systemctl reload nginx
```

## 健康检查

```bash
curl http://127.0.0.1:8000/api/public/health
systemctl is-active haorizi-api haorizi-worker nginx
journalctl -u haorizi-api -n 100 --no-pager
journalctl -u haorizi-worker -n 100 --no-pager
```

发送状态从 `send_logs` 查询；worker 日志会记录启动、计划重建和扫描结果。

## 生产数据库变更

`Base.metadata.create_all()` 不会升级已有表。发布涉及字段或表变化时必须：

1. 先备份数据库并检查 `information_schema.columns`
2. 停止 API 与 worker 写入
3. 执行 `alembic upgrade head`
4. 重启并验证健康检查、建群、进群、提醒 CRUD 和 worker

首次从旧个人 OpenID demo 升级且还没有 `groups` 表时，migration 会把与新模型同名的旧表改名为
`legacy_pre_group_20260728_*`，保留旧数据后再创建当前五张业务表。`users`、
`anniversary_events` 等不冲突旧表不会自动改动。迁移前后都要核对表名和数据量；不要把归档表当作长期状态，
确认不再回滚且完成数据留档后再人工删除。

生产环境应设置 `AUTO_CREATE_TABLES=false`，由 Alembic migration 唯一管理 schema：

```bash
cd /opt/haorizi/backend
source .venv/bin/activate
alembic current
alembic heads
alembic upgrade head
```

迁移后必须检查 `alembic current`、五张业务表、索引和服务日志，再恢复外部流量。

GitHub Actions 自动发布、受限 SSH、数据库备份、release 目录和回滚边界见 `docs/github-deployment.md`。

## 运营流程

1. 在 PushPlus 创建群组并取得 topic code
2. 用 `admin.html` 创建业务群组
3. 把 `join.html` 链接和群组码发给亲友
4. 成员扫码加入 PushPlus 群，并在工作台维护提醒

当前通知仍由 PushPlus 发送；微信身份接入边界见 `wechat-identity-roadmap.md`。
