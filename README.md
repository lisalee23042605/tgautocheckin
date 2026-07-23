# tgautocheckin

每天在设定的时间窗口内随机运行一次 Telegram 保号签到。全部目标执行结束后，才向收藏消息（`me`）发送 **一条** 汇总通知，其中分别列出成功和失败的目标。

## 必填环境变量

- `API_ID`
- `API_HASH`
- `SESSION_STRING`（AlwaysData 推荐）或 `SESSION_PATH`

## 多目标配置：`TARGETS_JSON`

在 AlwaysData 的环境变量中把下面内容压成一行填写。每个对象都可以独立决定是否需要第二步点击：

```json
[
  {"name":"Emby Bot","target":"@okemby_bot","message":"/start","click_button":true,"button_keyword":"签到"},
  {"name":"只发消息的群","target":-1001234567890,"message":"签到","click_button":false},
  {"name":"私有频道","target":"https://t.me/c/1234567890/42","message":"/start","click_button":true,"button_keyword":"每日签到"}
]
```

字段说明：

- `name`：汇总显示名称（可选，默认使用 `target`）。
- `target`：`@用户名`、普通链接、私有群/频道数值 ID（通常以 `-100` 开头），或私有消息链接 `https://t.me/c/<内部ID>/<消息ID>`。
- `message`：第一步发送的文字，默认 `/start`。
- `click_button`：是否需要第二步点按钮；设为 `false` 时只发送 `message`，不会等待或点击。
- `button_keyword`：需要点按钮时的包含匹配关键词，默认 `签到`。

私有群/频道的前提是：运行脚本的 Telegram 账号必须已经加入并至少打开过该会话一次。Telegram 需要账号本地保存的访问凭据，未加入的私有链接无法被脚本主动访问。

## 兼容旧配置

不设置 `TARGETS_JSON` 时，脚本仍按旧方式使用 `TARGET_BOT`、`START_CMD` 和 `BUTTON_KEYWORD`，并默认需要点击按钮。

## 其他可选变量

- `SEND_TO=me`：汇总发送到收藏消息。
- `TZ=Asia/Shanghai`
- `WINDOW_START=08:00`、`WINDOW_END=08:30`
- `WAIT_BOT_REPLY_SEC=25`
- `COOLDOWN_ON_FAIL_SEC=900`
