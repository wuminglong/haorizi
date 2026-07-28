# 提醒规则用例矩阵（冻结：极简版）

> 目标日统一假设：`target_date = 2026-05-24`，`remind_time = 09:00`
> 规则字段仅：`advance_days` + `include_on_day`

## A. 正常路径

| 用例 | 规则 | 期望 due 日期 |
|---|---|---|
| N1 默认 | advance=7, on_day=true | 05-17 advance#1；05-24 on_day |
| N2 仅当天 | advance=0, on_day=true | 05-24 on_day |
| N3 仅提前 | advance=7, on_day=false | 05-17 advance#1 |
| N4 提前1天+当天 | advance=1, on_day=true | 05-23 advance#1；05-24 on_day |

## B. 边界

| 用例 | 规则/场景 | 期望 |
|---|---|---|
| B1 无提醒 | advance=0, on_day=false | 校验失败，拒绝保存 |
| B2 编辑重算 | 修改 advance_days | 旧 pending/failed 取消，按新规则生成 |
| B3 已发送保留 | 同 target/kind 已 sent | 不重复插入 |
| B4 一次性过去日 | is_recurring=false 且目标日 < today | 无未来 plan |

## C. 日历

| 用例 | 输入 | 期望 |
|---|---|---|
| C1 阳历普通 | 2026-10-01 | target=2026-10-01 |
| C2 农历普通 | lunar 四月初八 | 转为对应公历 |
| C3 农历闰月默认 | is_leap_month=true, policy=skip | 无该闰月的年份跳过 |
| C4 农历闰月兜底 | policy=regular_month | 无该闰月时按普通同月并明确标记 |
| C5 农历三十默认 | missing_day_policy=last_day | 小月按廿九并明确标记 |
| C6 农历三十跳过 | missing_day_policy=skip | 小月无 occurrence |
| C7 阳历+闰月 | solar + leap | 校验失败 |
| C8 非每年无年 | is_recurring=false 且 event_year 空 | 校验失败 |
| C9 跨春节 | 2026-01-01 查农历腊月二十 | 命中农历 2025 年对应的 2026-02-07 |

## D. 发送

| 用例 | 场景 | 期望 |
|---|---|---|
| S1 到点发送 | due_at <= now 且 pending | PushPlus topic 成功后 sent |
| S2 失败重试 | 第一次失败 | attempt+1，due_at 延后 |
| S3 最终失败 | attempt >= max_attempts | failed + 日志 |
| S4 提醒停用 | enabled=false | pending cancel |
| S5 群停用 | group.status=disabled | pending cancel |
| S6 单条发送异常 | 批次中一条失败 | 其他计划继续处理并分别提交 |
| S7 stale processing | processing 超时 | 恢复 pending 后重新领取 |

## E. 进入 / 建群 / 安全

| 用例 | 场景 | 期望 |
|---|---|---|
| J1 正确群组码 | FAMILY01 | session + 群信息 |
| J2 错误群组码 | 不存在 | 404 群组码无效 |
| J3 格式错误 | ab | 400 |
| J4 频繁 join | 同 IP 超限 | 429 |
| J5 连续错误 | 错 8 次 | 冷却 15 分钟 |
| J6 重置群组码 | admin reset | 旧 token 401 |
| J7 二维码失败 | PushPlus 异常 | join 成功，qr 可空 |
| C1 建群口令正确 | admin token 有效 | 创建成功 |
| C2 建群口令错误 | token 无效 | 401 |
| C3 建群刷接口 | IP 超限 | 429 |
