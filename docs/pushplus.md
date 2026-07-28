# PushPlus 配置

当前版本只使用 PushPlus 群组推送。每个业务群组通过 `groups.push_topic_code` 绑定一个 PushPlus 群组。

## 服务端配置

```bash
PUSHPLUS_ENABLED=true
PUSHPLUS_TOKEN=你的PushPlusToken
PUSHPLUS_SECRET_KEY=你的OpenAPISecretKey
PUSHPLUS_QR_SECONDS=604800
PUSHPLUS_QR_SCAN_COUNT=-1
```

- `PUSHPLUS_TOKEN`：发送消息和调用 OpenAPI
- `PUSHPLUS_SECRET_KEY`：获取 access key，用于查询 topic 和生成入群二维码
- topic code 不放在环境变量中；创建业务群组时填写并保存到数据库

配置完成后重启：

```bash
sudo systemctl restart haorizi-api haorizi-worker
```

未启用 PushPlus 时，worker 使用 dry-run 写成功日志，便于本地开发；生产环境必须启用并完成真实收件验证。
