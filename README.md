# tg-checkin-cron

每天在 08:00–08:30（可配置）随机执行一次：
- 给目标 bot 发 /start
- 自动点击按钮（默认“签到”）
- 把最近消息渲染成图片并发送到你的收藏消息（me）

## 环境变量

必须：
- API_ID
- API_HASH
- TARGET_BOT (例如 @okemby_bot)

推荐：
- SESSION_STRING （推荐在云上用它，避免文件 session / 交互登录）
- TZ（默认 Asia/Shanghai）
- SEND_TO（默认 me）
- BUTTON_TEXT（默认 签到）
- START_CMD（默认 /start）
- WINDOW_START（默认 08:00）
- WINDOW_END（默认 08:30）

## 生成 SESSION_STRING（本机一次性执行）

```bash
pip install telethon==1.34.0
python - << 'PY'
import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("SESSION_STRING=" + client.session.save())
PY
