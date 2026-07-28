# HaoRiZi 好日子提醒

面向亲友小范围使用的群组纪念日提醒系统。

用户打开 H5，输入线下获得的群组码，加入 PushPlus 推送群；群内成员共同维护提醒，系统按“提前 N 天 / 当天”自动发送。

## 当前版本能力

- 管理员运维台：群组、全部提醒、发送记录、失败重试
- 群组码进入，使用 HttpOnly Cookie 保持会话
- 展示 PushPlus 入群二维码
- 群内共享提醒 CRUD
- 严格农历：1901–2099、闰月与缺日策略、未来日期预览
- 极简规则：提前 N 天 + 是否当天提醒
- worker 到点群发、失败隔离重试和 stale 任务恢复
- 苹果简约风 H5：
  - `join.html`
  - `index.html`（提醒 / 日程 / 我的，绿色加号新增）
  - `admin.html`

微信 OpenID、成员归属和“成员只能修改自己创建的提醒”属于下一阶段，当前版本仍为群内共同编辑。

## 本地启动

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

另开终端启动 worker：

```bash
cd backend
source .venv/bin/activate
python -m app.worker
```

打开：

- 管理台：http://localhost:8000/admin.html
- 加入：http://localhost:8000/join.html
- 工作台：http://localhost:8000/index.html

管理员密码由 `.env` 的 `ADMIN_TOKEN` 决定。示例配置仅用于本机开发，部署时必须替换 `SESSION_SECRET`、`ADMIN_TOKEN` 和推送凭据。

## 测试

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
cd ..
python -m pytest -q
```

## 文档

见 `docs/group-reminder-README.md`。

生产发布前必须备份数据库并运行 `alembic upgrade head`；不要提交 `.env`、数据库文件或任何生产凭据。

## 参与开发

开发、测试、数据库 migration 和安全要求见 `CONTRIBUTING.md`。GitHub Actions 发布的服务器操作边界、备份和回滚规则见 `docs/github-deployment.md`。
