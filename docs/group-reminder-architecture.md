# HaoRiZi 架构

## 运行链路

```text
admin.html ── admin cookie ──> /api/admin/*
join.html ── 群组码 ──> /api/public/groups/join ──> HttpOnly group cookie
index.html ── group cookie ──> 提醒 / 日程 / 我的
worker ── claim pending plan ──> PushPlus(topic=group.push_topic_code)
```

## 数据模型

- `groups`：群组、群组码和 PushPlus topic
- `reminders`：群组共享提醒及闰月/缺日策略
- `reminder_rules`：提醒时间、提前天数、是否当天提醒
- `reminder_plans`：具体待发送任务
- `send_logs`：发送结果与错误信息

`groups 1:N reminders`，`reminders 1:1 reminder_rules`，`reminders 1:N reminder_plans`。

## 权限

- `ADMIN_TOKEN`：换取管理员 Cookie；`X-Admin-Token` 暂时保留给运维脚本
- 群组码：换取 30 天 group session
- group session：查看和修改当前群组提醒
- 加入 PushPlus 群：接收通知；它与工作台权限相互独立

重置群组码会更新 `code_updated_at`，旧 session 因 `code_ver` 不匹配而失效。

## 提醒规则

- `advance_days > 0`：目标日前发送一次
- `include_on_day = true`：目标日当天发送一次
- 禁止 `advance_days = 0` 且 `include_on_day = false`

时间按群组 `Asia/Shanghai` 解释，写入数据库时转换为 UTC。农历先按上海当天确定当前农历年，再寻找未来三个有效日期；非法农历日期不得静默改写。
