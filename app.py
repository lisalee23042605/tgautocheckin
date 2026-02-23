import os
import asyncio
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from PIL import Image, ImageDraw, ImageFont


# ====== 必填环境变量 ======
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()  # 推荐云上用它
SESSION_PATH = os.environ.get("SESSION_PATH", "/data/user.session")

TARGET_BOT = os.environ.get("TARGET_BOT", "@okemby_bot")
SEND_TO = os.environ.get("SEND_TO", "me")

# ====== 可选配置 ======
TZ = os.environ.get("TZ", "Asia/Shanghai")
START_CMD = os.environ.get("START_CMD", "/start")
BUTTON_KEYWORD = os.environ.get("BUTTON_KEYWORD", "签到")  # 用“关键词包含匹配”，能点到“🎯 签到”
WINDOW_START = os.environ.get("WINDOW_START", "20:55")
WINDOW_END = os.environ.get("WINDOW_END", "21:00")

WAIT_BOT_REPLY_SEC = int(os.environ.get("WAIT_BOT_REPLY_SEC", "25"))
COOLDOWN_ON_FAIL_SEC = int(os.environ.get("COOLDOWN_ON_FAIL_SEC", "900"))  # 失败冷却 15 分钟


def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def choose_next_run(now: datetime) -> datetime:
    """
    每天在窗口内随机一次运行时间。
    - 如果现在早于窗口开始：在 [start, end] 内随机
    - 如果现在在窗口内：在 [now, end] 内随机（避免“过去时间”）
    - 如果现在晚于窗口结束：选明天窗口
    """
    tz = now.tzinfo
    start_t = parse_hhmm(WINDOW_START)
    end_t = parse_hhmm(WINDOW_END)

    today_start = datetime.combine(now.date(), start_t, tzinfo=tz)
    today_end = datetime.combine(now.date(), end_t, tzinfo=tz)

    if today_end <= today_start:
        raise ValueError("WINDOW_END must be later than WINDOW_START (same day).")

    if now < today_start:
        base = today_start
        span = int((today_end - today_start).total_seconds())
    elif now <= today_end:
        base = now
        span = int((today_end - now).total_seconds())
        if span < 0:
            span = 0
    else:
        base = datetime.combine(now.date() + timedelta(days=1), start_t, tzinfo=tz)
        tomorrow_end = datetime.combine(base.date(), end_t, tzinfo=tz)
        span = int((tomorrow_end - base).total_seconds())

    offset = random.randint(0, max(0, span))
    return base + timedelta(seconds=offset)


def render_as_image(title: str, lines: list[str], out_path: str) -> None:
    """把文本渲染成图片，作为“截图”发给你。"""
    max_width = 1100
    padding = 30

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_bold = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font

    dummy = Image.new("RGB", (max_width, 10), "white")
    draw = ImageDraw.Draw(dummy)

    def wrap(text: str) -> list[str]:
        # 按字符换行，兼容中文
        out, cur = [], ""
        for ch in text:
            test = cur + ch
            w = draw.textlength(test, font=font)
            if w > (max_width - 2 * padding):
                out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
        return out

    wrapped = [("title", title)]
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            wrapped.append(("line", ""))
            continue
        for wln in wrap(ln):
            wrapped.append(("line", wln))

    line_h = 34
    title_h = 52
    height = padding * 2 + title_h + max(0, len(wrapped) - 1) * line_h + 10

    img = Image.new("RGB", (max_width, height), "white")
    d2 = ImageDraw.Draw(img)

    y = padding
    d2.text((padding, y), title, fill="black", font=font_bold)
    y += title_h

    for _, txt in wrapped[1:]:
        d2.text((padding, y), txt, fill="black", font=font)
        y += line_h

    img.save(out_path)


async def wait_new_message(client, *, from_user, timeout=25):
    """
    等待来自指定用户/机器人的一条新消息（兼容没有 client.wait_for 的 telethon 版本）。
    """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    builder = events.NewMessage(from_users=from_user)

    async def handler(event):
        if not fut.done():
            fut.set_result(event.message)

    client.add_event_handler(handler, builder)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        client.remove_event_handler(handler, builder)


async def find_latest_message_with_buttons(client, limit=50):
    msgs = await client.get_messages(TARGET_BOT, limit=limit)
    for m in msgs:
        if m.buttons:
            return m
    return None


def format_buttons(msg) -> list[str]:
    if not msg.buttons:
        return []
    rows = []
    for row in msg.buttons:
        rows.append(" | ".join([(b.text or "").strip() for b in row]))
    return rows


async def click_button_contains_on_message(msg, keyword: str) -> bool:
    """
    遍历按钮，按坐标点击。
    适用于 inline keyboard（回调按钮）。keyword 用“包含匹配”。
    """
    if not msg.buttons:
        return False
    keyword = keyword.strip()
    for r, row in enumerate(msg.buttons):
        for c, btn in enumerate(row):
            t = (btn.text or "").strip()
            if keyword and (keyword in t):
                await msg.click(r, c)
                return True
    return False


async def run_once(client) -> tuple[bool, str]:
    """
    执行一次：/start -> 找带按钮的消息 -> 点包含“签到”的按钮 -> 收集最近消息文本
    返回 (success, text)
    """
    # 1) 发 /start
    await client.send_message(TARGET_BOT, START_CMD)

    # 2) 等 bot 至少回一条（有些 bot 会先回文字再给按钮）
    try:
        await wait_new_message(client, from_user=TARGET_BOT, timeout=WAIT_BOT_REPLY_SEC)
    except asyncio.TimeoutError:
        return False, f"失败：发送 {START_CMD} 后 {WAIT_BOT_REPLY_SEC}s 没收到 bot 回复。"

    # 3) 找最近带 buttons 的消息
    menu = await find_latest_message_with_buttons(client, limit=60)
    if not menu:
        return False, "失败：最近 60 条里都没有 buttons，无法点击。"

    # 4) 点“签到”按钮（包含匹配）
    ok = await click_button_contains_on_message(menu, BUTTON_KEYWORD)
    if not ok:
        btn_rows = format_buttons(menu)
        return False, "失败：没找到包含“%s”的按钮。\n当前按钮：\n- %s" % (
            BUTTON_KEYWORD,
            "\n- ".join(btn_rows) if btn_rows else "(空)"
        )

    # 5) 等 bot 回结果（不一定必须，但通常会有）
    try:
        await wait_new_message(client, from_user=TARGET_BOT, timeout=WAIT_BOT_REPLY_SEC)
    except asyncio.TimeoutError:
        pass

    # 6) 把最近几条消息整理成“截图内容”
    msgs = await client.get_messages(TARGET_BOT, limit=8)
    msgs = list(reversed(msgs))

    lines = []
    for m in msgs:
        txt = (m.message or "").strip()
        if txt:
            # 控制长度，避免图片太长
            txt = "\n".join(txt.splitlines()[:10])
            lines.append(txt)
        if m.buttons:
            rows = format_buttons(m)
            if rows:
                lines.append("[Buttons] " + " / ".join(rows))

    if not lines:
        lines = ["完成：已点击按钮，但未抓到可展示的文本消息。"]
    return True, "\n".join(lines)


async def main():
    tz = ZoneInfo(TZ)

    # 创建 client
    if SESSION_STRING:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    else:
        client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

    await client.start()

    # 启动提示
    now = datetime.now(tz)
    next_run = choose_next_run(now)
    await client.send_message(
        SEND_TO,
        f"✅ 签到定时服务已启动\n"
        f"TZ={TZ}\n"
        f"窗口={WINDOW_START}-{WINDOW_END}\n"
        f"下一次运行={next_run.isoformat()}"
    )

    last_run_date = None  # 确保“每天只执行一次”

    while True:
        now = datetime.now(tz)

        # 如果今天已经执行过，就睡到明天窗口前再算
        if last_run_date == now.date():
            tomorrow = datetime.combine(now.date() + timedelta(days=1), parse_hhmm(WINDOW_START), tzinfo=tz)
            sleep_s = max(60, int((tomorrow - now).total_seconds()))
            await asyncio.sleep(sleep_s)
            continue

        run_at = choose_next_run(now)
        sleep_s = max(0, (run_at - now).total_seconds())
        await asyncio.sleep(sleep_s)

        stamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        try:
            success, text = await run_once(client)
            last_run_date = datetime.now(tz).date()

            title = f"TG 签到结果（{stamp} {TZ}）"
            out_path = "/tmp/checkin.png"
            render_as_image(
                title=title,
                lines=text.splitlines(),
                out_path=out_path
            )

            caption = "✅ 成功" if success else "❌ 失败"
            await client.send_file(SEND_TO, out_path, caption=f"{caption}\n{title}")

            # 失败的话冷却，避免短期反复
            if not success:
                await asyncio.sleep(COOLDOWN_ON_FAIL_SEC)

        except Exception as e:
            await client.send_message(SEND_TO, f"❌ 任务异常（{stamp}）：{type(e).__name__}: {e}")
            await asyncio.sleep(COOLDOWN_ON_FAIL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
