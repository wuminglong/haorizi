# HaoRiZi 文档

当前系统只保留群组提醒模型。运行时唯一主链是：

```text
管理员运维台 → 用户输入群组码 → 共享维护提醒 → 严格日历生成计划 → worker 发送到 PushPlus 群组
```

## 当前文档

- [架构说明](./group-reminder-architecture.md)
- API 契约：运行服务后的 `/openapi.json` 与 `/docs`
- [提醒规则与验收矩阵](./group-reminder-rule-matrix.md)
- [部署与运维](./group-reminder-ops.md)
- [PushPlus 配置](./pushplus.md)
- [隐私说明](./privacy.md)
- [产品决策记录](./group-reminder-decisions-frozen.md)
- [微信身份下一阶段](./wechat-identity-roadmap.md)

数据库结构以 [models.py](../backend/app/models.py) 和 `backend/alembic/versions/` 为事实源，生产数据库只通过 Alembic 升级。
