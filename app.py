import os
import asyncio
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from PIL import Image, ImageDraw, ImageFont


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
TARGET_BOT = os.environ.get("TARGET_BOT", "@okemby_bot")
START_CMD = os.environ.get("START_CMD", "/start")
BUTTON_TEXT = os.environ.get("BUTTON_TEXT", "签到")  # 你截图里就是“签到”
SEND_TO = os.environ.get("SEND_TO", "me")          # 发到收藏消息
TZ = os.environ.get("TZ", "Asia/Shanghai")         # 你要的8:00通常按中国时间，若不是可改
WINDOW_START = os.environ.get("WINDOW_START", "08:00")
WINDOW_END = os.environ.get("WINDOW_END", "08:30")

# 两种 session 方式二选一：
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
SESSION_PATH = os.environ.get("SESSION_PATH", "/data/user.session")


def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def choose_next_run(now: datetime) -> datetime:
    """每天在窗口内随机一次运行时间；如果今天窗口已过，选明天。"""
    tz = now.tzinfo
    start_t = parse_hhmm(WINDOW_START)
    end_t = parse_hhmm(WINDOW_END)

    today_start = datetime.combine(now.date(), start_t, tzinfo=tz)
    today_end = datetime.combine(now.date(), end_t, tzinfo=tz)

    # 生成窗口内随机秒
    window_seconds = int((today_end - today_start).total_seconds())
    if window_seconds <= 0:
        raise ValueError("WINDOW_END must be later than WINDOW_START")

    if now < today_start:
        base = today_start
    elif now <= today_end:
        base = now  # 现在已经在窗口内：立即挑一个“从现在到窗口结束”的随机时间
        window_seconds = int((today_end - base).total_seconds())
        if window_seconds <= 0:
            return now  # 已经到边界
    else:
        # 明天
        base = datetime.combine(now.date() + timedelta(days=1), start_t, tzinfo=tz)
        today_end = datetime.combine(base.date(), end_t, tzinfo=tz)
        window_seconds = int((today_end - base).total_seconds())

    offset = random.randint(0, max(0, window_seconds))
    return base + timedelta(seconds=offset)


def render_as_image(title: str, lines: list[str], out_path: str) -> None:
    """把文本渲染成一张图片（代替截图）。"""
    # 尽量用系统字体；没有也能用默认字体
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_bold = ImageFont.truetype("DejaVuSans.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font

    padding = 30
    max_width = 1100

    # 先测量高度
    dummy = Image.new("RGB", (max_width, 10), "white")
    d = ImageDraw.Draw(dummy)

    def wrap(text: str) -> list[str]:
        words = list(text)
        out, cur = [], ""
        for ch in words:
            test = cur + ch
            w = d.textlength(test, font=font)
            if w > (max_width - 2 * padding):
                out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
        return out

    wrapped = []
    wrapped.append(("title", title))
    for ln in lines:
        for wln in wrap(ln):
            wrapped.append(("line", wln))

    line_h = 34
    title_h = 44
    height = padding * 2 + title_h + (len(wrapped) - 1) * line_h + 20

    img = Image.new("RGB", (max_width, height), "white")
    draw = ImageDraw.Draw(img)

    y = padding
    # title
    draw.text((padding, y), title, fill="black", font=font_bold)
    y += title_h

    for kind, txt in wrapped[1:]:
        draw.text((padding, y), txt, fill="black", font=font)
        y += line_h

    img.save(out_path)


async def wait_buttons_message(client: TelegramClient, timeout: int = 25):
    """等待目标 bot 发来带按钮的消息。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remain = deadline - asyncio.get_event_loop().time()
        if remain <= 0:
            return None
        try:
            ev = await client.wait_for(events.NewMessage(from_users=TARGET_BOT), timeout=remain)
        except asyncio.TimeoutError:
            return None
        if ev.message.buttons:
            return ev.message


async def click_button_contains(msg, needle: str) -> bool:
    """点击按钮（按文字包含匹配）。"""
    if not msg.buttons:
        return False
    needle = needle.strip()
    for r, row in enumerate(msg.buttons):
        for c, btn in enumerate(row):
            t = (btn.text or "").strip()
            if needle and needle in t:
                await msg.click(r, c)
                return True
    return False


async def run_once(client: TelegramClient) -> str:
    """执行一次签到，并返回结果文本。"""
    # 1) 发 /start
    await client.send_message(TARGET_BOT, START_CMD)

    # 2) 等菜单按钮
    menu = await wait_buttons_message(client, timeout=25)
    if not menu:
        return "失败：没等到带按钮的菜单消息（25s 超时）。"

    # 3) 点击“签到”
    ok = await click_button_contains(menu, BUTTON_TEXT)
    if not ok:
        btns = []
        for row in menu.buttons:
            for b in row:
                btns.append((b.text or "").strip())
        return "失败：没找到匹配按钮。当前按钮有：\n- " + "\n- ".join(btns)

    # 4) 等 bot 返回结果消息（可能是新消息）
    try:
        ev = await client.wait_for(events.NewMessage(from_users=TARGET_BOT), timeout=25)
        result_msg = ev.message
    except asyncio.TimeoutError:
        result_msg = None

    # 5) 拉取最近几条消息用于“截图”
    msgs = await client.get_messages(TARGET_BOT, limit=6)
    msgs = list(reversed(msgs))

    lines = []
    for m in msgs:
        txt = (m.message or "").strip()
        if txt:
            # 只取前几行防止太长
            txt = "\n".join(txt.splitlines()[:8])
            lines.append(f"[Bot] {txt}")
        if m.buttons:
            btns = []
            for row in m.buttons:
                btns.append(" | ".join([(b.text or "").strip() for b in row]))
            lines.append("[Buttons] " + " / ".join(btns))

    if result_msg and (result_msg.message or "").strip():
        lines.append("——")
        lines.append("最终返回：")
        lines.append((result_msg.message or "").strip())

    return "\n".join(lines) if lines else "完成：已点击按钮，但未捕获到可展示的消息内容。"


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
    nxt = choose_next_run(now)
    await client.send_message(SEND_TO, f"✅ 签到定时服务已启动。\n时区：{TZ}\n下一次运行：{nxt.isoformat()}")

    while True:
        now = datetime.now(tz)
        run_at = choose_next_run(now)
        sleep_s = max(0, (run_at - now).total_seconds())
        await asyncio.sleep(sleep_s)

        stamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        try:
            result_text = await run_once(client)
            title = f"TG 签到结果（{stamp}，{TZ}）"
            out_path = "/tmp/checkin.png"
            render_as_image(title, result_text.splitlines(), out_path)

            await client.send_file(SEND_TO, out_path, caption=title)
        except Exception as e:
            await client.send_message(SEND_TO, f"❌ 签到任务异常（{stamp}）：{type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
