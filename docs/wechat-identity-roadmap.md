# 微信身份下一阶段

当前版本不实现微信身份，也不创建闲置用户表。接入公众号配置后再执行以下独立迁移：

- `users`：内部用户 ID、状态和 session version
- `user_identities`：`provider + app_id + openid` 唯一，可选 unionid
- `group_members`：`group_id + user_id` 唯一，记录 active/removed
- `reminders.created_by_member_id/updated_by_member_id`：新提醒归属；旧提醒保持 NULL、仅管理员可修改

普通入口使用公众号 `snsapi_base` 静默授权。无群进入加群页，一个群直接进入，多个群进入群组选择器；非微信浏览器提示在微信中打开。群内成员看全部提醒，只能修改自己创建的提醒，平台管理员可维护全部。

重置群组码只阻止后续使用旧码加入，不清退已有成员；成员移除与全员强制退出是独立操作。通知渠道仍使用 PushPlus。
