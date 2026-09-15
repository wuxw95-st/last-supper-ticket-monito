#!/usr/bin/env python3
"""High-frequency availability monitor for Cenacolo Vinciano tickets."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from playwright.async_api import Browser, Page, async_playwright


load_dotenv()

EVENT_URL = os.getenv(
    "EVENT_URL",
    "https://cenacolovinciano.vivaticket.it/en/event/cenacolo-vinciano/151991",
)
TARGET_MONTH = os.getenv("TARGET_MONTH", "OCTOBER 2026").upper()
TARGET_DAY = int(os.getenv("TARGET_DAY", "6"))
CHECK_INTERVAL_SECONDS = max(60, int(os.getenv("CHECK_INTERVAL_SECONDS", "120")))
INTERVAL_JITTER_SECONDS = max(0, int(os.getenv("INTERVAL_JITTER_SECONDS", "15")))
REMINDER_INTERVAL_SECONDS = max(300, int(os.getenv("REMINDER_INTERVAL_SECONDS", "600")))
STATE_FILE = Path(os.getenv("STATE_FILE", "data/state.json"))
SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", "data/screenshots"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
HEADLESS = os.getenv("HEADLESS", "true").lower() not in {"0", "false", "no"}
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "").strip()


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("last-supper-monitor")


@dataclass
class Availability:
    available: bool
    checked_at: str
    month: str
    day: int
    status: str
    times: list[str]
    page_url: str
    screenshot: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _recipients() -> list[str]:
    value = os.getenv("EMAIL_TO", "")
    return [item.strip() for item in value.split(",") if item.strip()]


def email_is_configured() -> bool:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO"]
    return all(os.getenv(name) for name in required)


def bark_is_configured() -> bool:
    return bool(os.getenv("BARK_URL", "").strip())


def validate_notification_config() -> None:
    if not bark_is_configured() and not email_is_configured():
        raise RuntimeError("Bark 和邮件均未配置，请先运行 setup.py。")


def is_day_available(classes: Iterable[str], title: str) -> bool:
    """Classify the site's calendar marker conservatively to avoid false alerts."""
    class_set = set(classes)
    normalized_title = title.strip().lower()
    return not ({"inactive", "no-event"} & class_set or "not available" in normalized_title)


def send_email(subject: str, text_body: str, html_body: str) -> None:
    if not email_is_configured():
        raise RuntimeError("邮件配置不完整")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = ", ".join(_recipients())
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    timeout = int(os.getenv("SMTP_TIMEOUT_SECONDS", "30"))
    mode = os.getenv("SMTP_SECURITY", "ssl").lower()
    context = ssl.create_default_context()

    if mode == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)


def send_bark(title: str, body: str, *, urgent: bool, link: str = EVENT_URL) -> None:
    bark_url = os.getenv("BARK_URL", "").strip().rstrip("/")
    if not bark_url:
        raise RuntimeError("Bark 未配置")
    payload = {
        "title": title,
        "body": body,
        "url": link,
        "url_title": "立即打开官方购票页",
        "group": "last-supper-tickets",
        "sound": os.getenv("BARK_SOUND", "alarm"),
        "level": os.getenv("BARK_LEVEL", "timeSensitive"),
    }
    if urgent:
        payload["call"] = "1"
    request = urllib.request.Request(
        bark_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "last-supper-monitor/2.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if response.status // 100 != 2:
                raise RuntimeError(f"Bark 返回 HTTP {response.status}: {response_body[:200]}")
            try:
                parsed = json.loads(response_body)
                if parsed.get("code") not in (None, 200):
                    raise RuntimeError(f"Bark 推送失败：{response_body[:200]}")
            except json.JSONDecodeError:
                pass
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Bark 推送请求失败：{exc}") from exc


def send_notifications(title: str, text_body: str, html_body: str, *, urgent: bool) -> None:
    errors: list[str] = []
    sent = 0
    if bark_is_configured():
        try:
            send_bark(title, text_body, urgent=urgent)
            sent += 1
        except Exception as exc:
            errors.append(f"Bark: {exc}")
    if email_is_configured():
        try:
            send_email(title, text_body, html_body)
            sent += 1
        except Exception as exc:
            errors.append(f"Email: {exc}")
    if sent == 0:
        raise RuntimeError("；".join(errors) or "没有可用的通知渠道")
    if errors:
        log.error("部分通知渠道失败：%s", "；".join(errors))


async def _calendar_month(page: Page) -> str:
    month = page.locator("text=/^[A-Z]+\\s+2026$/").first
    return (await month.inner_text(timeout=8_000)).strip().upper()


async def _move_to_target_month(page: Page) -> None:
    for _ in range(12):
        current = await _calendar_month(page)
        if current == TARGET_MONTH:
            return
        next_button = page.get_by_role("link", name="›")
        if await next_button.count() == 0:
            raise RuntimeError(f"找不到日历下一月按钮；当前月份：{current}")
        await next_button.click()
        await page.wait_for_timeout(500)
    raise RuntimeError(f"12 次翻页后仍找不到 {TARGET_MONTH}")


async def check_availability(page: Page) -> Availability:
    await page.goto(EVENT_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_selector("#dayOfTheMonth_151991", timeout=30_000)

    decline = page.get_by_role("button", name="I decline")
    if await decline.is_visible():
        await decline.click()

    await _move_to_target_month(page)
    selector = f"#dayOfTheMonth_151991 li.cal10{TARGET_DAY}"
    day = page.locator(selector)
    if await day.count() != 1:
        raise RuntimeError(f"目标日期元素异常：{selector} 匹配到 {await day.count()} 个")

    classes = set((await day.get_attribute("class") or "").split())
    title = (await day.get_attribute("title") or "").strip()
    unavailable = not is_day_available(classes, title)
    status = title or "available" if not unavailable else title or "unavailable"
    times: list[str] = []
    screenshot: str | None = None

    if not unavailable:
        await day.click()
        await page.wait_for_timeout(900)
        time_candidates = await page.locator(
            "button, a, label, li"
        ).all_inner_texts()
        times = sorted({
            token.strip()
            for raw in time_candidates
            for token in raw.replace("\n", " ").split()
            if len(token) == 5 and token[2] == ":" and token.replace(":", "").isdigit()
        })
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = SCREENSHOT_DIR / f"available-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        await page.screenshot(path=str(shot), full_page=True)
        screenshot = str(shot)

    return Availability(
        available=not unavailable,
        checked_at=_now_iso(),
        month=TARGET_MONTH,
        day=TARGET_DAY,
        status=status,
        times=times,
        page_url=page.url,
        screenshot=screenshot,
    )


def _availability_mail(result: Availability, reminder: bool = False) -> tuple[str, str, str]:
    prefix = "再次提醒" if reminder else "发现余票"
    subject = f"【{prefix}】最后的晚餐 2026-10-06 门票可购买"
    time_text = "、".join(result.times) if result.times else "官网已显示当天可选，请立即进入查看"
    text_body = (
        f"{prefix}：米兰《最后的晚餐》2026 年 10 月 6 日门票可能可以购买。\n\n"
        f"可见时间：{time_text}\n检查时间（UTC）：{result.checked_at}\n"
        f"立即购票：{EVENT_URL}\n\n热门票可能很快售罄，请以结算页为准。"
    )
    html_body = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6">
      <h2 style="color:#b42318">{html.escape(prefix)}：2026-10-06 出现可选门票</h2>
      <p><strong>可见时间：</strong>{html.escape(time_text)}</p>
      <p><strong>检查时间（UTC）：</strong>{html.escape(result.checked_at)}</p>
      <p><a href="{html.escape(EVENT_URL)}" style="display:inline-block;background:#b42318;color:white;padding:12px 18px;text-decoration:none;border-radius:6px">立即打开官方购票页</a></p>
      <p style="color:#667085">热门票可能很快售罄，请以结算页为准。</p>
    </body></html>
    """
    return subject, text_body, html_body


async def monitor() -> None:
    validate_notification_config()
    log.info("开始监控 %s %s %s，每 %s 秒检查", TARGET_MONTH, TARGET_DAY, EVENT_URL, CHECK_INTERVAL_SECONDS)
    state = _load_state()

    async with async_playwright() as playwright:
        launch_options = {"headless": HEADLESS}
        if BROWSER_CHANNEL:
            launch_options["channel"] = BROWSER_CHANNEL
        browser: Browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context(locale="en-US", timezone_id="Europe/Rome")
        page = await context.new_page()
        consecutive_errors = 0

        while True:
            try:
                result = await check_availability(page)
                consecutive_errors = 0
                log.info("检查完成 | available=%s | status=%s | times=%s", result.available, result.status, result.times)

                last_notified = float(state.get("last_notified_epoch", 0))
                now_epoch = datetime.now(timezone.utc).timestamp()
                was_available = bool(state.get("available", False))
                reminder_due = result.available and now_epoch - last_notified >= REMINDER_INTERVAL_SECONDS
                should_notify = result.available and (not was_available or reminder_due)

                if should_notify:
                    subject, text_body, html_body = _availability_mail(result, reminder=was_available)
                    await asyncio.to_thread(
                        send_notifications,
                        subject,
                        text_body,
                        html_body,
                        urgent=not was_available,
                    )
                    state["last_notified_epoch"] = now_epoch
                    log.warning("余票通知已发送")

                state.update(asdict(result))
                _save_state(state)
            except Exception as exc:
                consecutive_errors += 1
                log.exception("本轮检查失败：%s", exc)
                last_error_notice = float(state.get("last_error_notice_epoch", 0))
                now_epoch = datetime.now(timezone.utc).timestamp()
                if consecutive_errors >= 3 and now_epoch - last_error_notice >= 3600:
                    try:
                        await asyncio.to_thread(
                            send_notifications,
                            "【监控异常】最后的晚餐余票监控连续失败",
                            f"监控已连续失败 {consecutive_errors} 次。最近错误：{exc}\n请检查网络或运行日志。",
                            f"<h2>余票监控连续失败</h2><p>已连续失败 {consecutive_errors} 次。</p><p>最近错误：{html.escape(str(exc))}</p><p>请检查网络或运行日志。</p>",
                            urgent=False,
                        )
                        state["last_error_notice_epoch"] = now_epoch
                        _save_state(state)
                    except Exception:
                        log.exception("监控异常邮件也发送失败")

            delay = CHECK_INTERVAL_SECONDS + random.randint(-INTERVAL_JITTER_SECONDS, INTERVAL_JITTER_SECONDS)
            await asyncio.sleep(max(60, delay))


if __name__ == "__main__":
    try:
        asyncio.run(monitor())
    except KeyboardInterrupt:
        log.info("监控已停止")
