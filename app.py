import asyncio
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession


API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ.get("SESSION_STRING", "").strip()
SESSION_PATH = os.environ.get("SESSION_PATH", "/data/user.session")
SEND_TO = os.environ.get("SEND_TO", "me")

# New format: a JSON array in the AlwaysData environment.  TARGET_BOT remains
# supported so an old single-target deployment still starts normally.
TARGETS_JSON = os.environ.get("TARGETS_JSON", "").strip()
TARGET_BOT = os.environ.get("TARGET_BOT", "@okemby_bot")
START_CMD = os.environ.get("START_CMD", "/start")
BUTTON_KEYWORD = os.environ.get("BUTTON_KEYWORD", "签到")

TZ = os.environ.get("TZ", "Asia/Shanghai")
WINDOW_START = os.environ.get("WINDOW_START", "08:00")
WINDOW_END = os.environ.get("WINDOW_END", "08:30")
WAIT_REPLY_SEC = int(os.environ.get("WAIT_BOT_REPLY_SEC", "25"))
COOLDOWN_ON_FAIL_SEC = int(os.environ.get("COOLDOWN_ON_FAIL_SEC", "900"))


@dataclass
class Target:
    name: str
    target: Any
    message: str
    click_button: bool
    button_keyword: str


def parse_targets() -> list[Target]:
    """Read TARGETS_JSON, falling back to the legacy one-target variables."""
    if not TARGETS_JSON:
        return [Target(TARGET_BOT, TARGET_BOT, START_CMD, True, BUTTON_KEYWORD)]
    try:
        raw = json.loads(TARGETS_JSON)
    except json.JSONDecodeError as exc:
        raise ValueError(f"TARGETS_JSON is not valid JSON: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("TARGETS_JSON must be a non-empty JSON array.")

    targets = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict) or "target" not in item:
            raise ValueError(f"TARGETS_JSON item #{i} must be an object with 'target'.")
        target = item["target"]
        if not isinstance(target, (str, int)):
            raise ValueError(f"TARGETS_JSON item #{i}: target must be a username/link or numeric ID.")
        click_button = item.get("click_button", True)
        if not isinstance(click_button, bool):
            raise ValueError(f"TARGETS_JSON item #{i}: click_button must be true or false.")
        targets.append(Target(
            name=str(item.get("name") or target), target=target,
            message=str(item.get("message", START_CMD)), click_button=click_button,
            button_keyword=str(item.get("button_keyword", BUTTON_KEYWORD)),
        ))
    return targets


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def choose_next_run(now: datetime) -> datetime:
    start = datetime.combine(now.date(), parse_hhmm(WINDOW_START), tzinfo=now.tzinfo)
    end = datetime.combine(now.date(), parse_hhmm(WINDOW_END), tzinfo=now.tzinfo)
    if end <= start:
        raise ValueError("WINDOW_END must be later than WINDOW_START (same day).")
    if now < start:
        base, finish = start, end
    elif now <= end:
        base, finish = now, end
    else:
        base = datetime.combine(now.date() + timedelta(days=1), parse_hhmm(WINDOW_START), tzinfo=now.tzinfo)
        finish = datetime.combine(base.date(), parse_hhmm(WINDOW_END), tzinfo=now.tzinfo)
    return base + timedelta(seconds=random.randint(0, int((finish - base).total_seconds())))


def private_link_to_id(value: Any) -> Any:
    """Turn t.me/c/<internal id>/... into Telegram's marked channel ID."""
    if not isinstance(value, str):
        return value
    match = re.search(r"(?:https?://)?t\.me/c/(\d+)(?:/\d+)?/?$", value.strip(), re.I)
    return int("-100" + match.group(1)) if match else value.strip()


async def resolve_target(client: TelegramClient, target: Any):
    """Resolve usernames, numeric peer IDs, and t.me/c private links.

    Private groups/channels must already be visible to this Telegram account;
    Telegram requires an access hash, which is obtained from the dialog list.
    """
    target = private_link_to_id(target)
    try:
        return await client.get_input_entity(target)
    except (ValueError, TypeError):
        if not isinstance(target, int):
            raise
    async for dialog in client.iter_dialogs():
        if utils.get_peer_id(dialog.entity) == target:
            return await client.get_input_entity(dialog.entity)
    raise ValueError("Private target not found in this account's dialogs. Join/open it once first, then use its numeric ID or t.me/c link.")


async def wait_incoming(client: TelegramClient, peer, timeout: int):
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    async def handler(event):
        if not result.done():
            result.set_result(event.message)

    client.add_event_handler(handler, events.NewMessage(chats=peer, incoming=True))
    try:
        return await asyncio.wait_for(result, timeout=timeout)
    finally:
        client.remove_event_handler(handler)


async def latest_buttons(client: TelegramClient, peer, limit: int = 60):
    messages = await client.get_messages(peer, limit=limit)
    return next((message for message in messages if message.buttons), None)


async def click_matching_button(message, keyword: str) -> tuple[bool, str]:
    for row, buttons in enumerate(message.buttons or []):
        for col, button in enumerate(buttons):
            if keyword.strip() and keyword.strip() in (button.text or "").strip():
                await message.click(row, col)
                return True, (button.text or "").strip()
    labels = [" | ".join((b.text or "").strip() for b in row) for row in message.buttons or []]
    return False, "; ".join(labels) or "(no buttons)"


async def check_in(client: TelegramClient, target: Target) -> tuple[bool, str]:
    try:
        peer = await resolve_target(client, target.target)
        await client.send_message(peer, target.message)

        # A one-message target has completed its required action.  We do not
        # wait for a reply because many groups/bots intentionally send none.
        if not target.click_button:
            return True, f"已发送：{target.message}"

        try:
            await wait_incoming(client, peer, WAIT_REPLY_SEC)
        except asyncio.TimeoutError:
            # Still inspect history: a response may arrive just before the
            # handler is installed, or be a channel post not marked incoming.
            pass
        menu = await latest_buttons(client, peer)
        if not menu:
            return False, "未找到带按钮的消息"
        clicked, detail = await click_matching_button(menu, target.button_keyword)
        if not clicked:
            return False, f"未找到按钮“{target.button_keyword}”（当前：{detail}）"
        return True, f"已发送并点击：{detail}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def make_summary(stamp: str, results: list[tuple[Target, bool, str]]) -> str:
    ok = [(target, detail) for target, success, detail in results if success]
    failed = [(target, detail) for target, success, detail in results if not success]
    lines = [f"TG 保号签到汇总（{stamp} {TZ}）", f"成功 {len(ok)} 个，失败 {len(failed)} 个。"]
    if ok:
        lines.append("\n✅ 成功")
        lines.extend(f"• {target.name}：{detail}" for target, detail in ok)
    if failed:
        lines.append("\n❌ 失败")
        lines.extend(f"• {target.name}：{detail}" for target, detail in failed)
    return "\n".join(lines)


async def main():
    targets = parse_targets()
    tz = ZoneInfo(TZ)
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH) if SESSION_STRING else TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()

    next_run = choose_next_run(datetime.now(tz))
    await client.send_message(SEND_TO, f"✅ TG 保号签到服务已启动\n目标数={len(targets)}\n窗口={WINDOW_START}-{WINDOW_END}\n下次运行={next_run.isoformat()}")

    last_run_date = None
    while True:
        now = datetime.now(tz)
        if last_run_date == now.date():
            tomorrow = datetime.combine(now.date() + timedelta(days=1), parse_hhmm(WINDOW_START), tzinfo=tz)
            await asyncio.sleep(max(60, int((tomorrow - now).total_seconds())))
            continue
        await asyncio.sleep(max(0, (choose_next_run(now) - now).total_seconds()))

        stamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        results = []
        for target in targets:
            results.append((target, *await check_in(client, target)))
        last_run_date = datetime.now(tz).date()
        # Exactly one daily notification, after every target has been handled.
        await client.send_message(SEND_TO, make_summary(stamp, results))
        if any(not success for _, success, _ in results):
            await asyncio.sleep(COOLDOWN_ON_FAIL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
