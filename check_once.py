#!/usr/bin/env python3
"""One-shot checker for free scheduled cloud runners."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright

from monitor import (
    BROWSER_CHANNEL,
    HEADLESS,
    _availability_mail,
    check_availability,
    send_notifications,
    validate_notification_config,
)


log = logging.getLogger("last-supper-monitor.once")
END_AT_UTC = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)
MAX_ATTEMPTS = max(1, int(os.getenv("CHECK_MAX_ATTEMPTS", "3")))
RETRY_DELAY_SECONDS = max(5, int(os.getenv("CHECK_RETRY_DELAY_SECONDS", "20")))


async def main() -> None:
    if datetime.now(timezone.utc) > END_AT_UTC:
        log.info("目标日期已结束，不再访问售票网站。")
        return

    validate_notification_config()
    async with async_playwright() as playwright:
        launch_options = {"headless": HEADLESS}
        if BROWSER_CHANNEL:
            launch_options["channel"] = BROWSER_CHANNEL
        browser = await playwright.chromium.launch(**launch_options)
        try:
            result = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                context = await browser.new_context(
                    locale="en-US", timezone_id="Europe/Rome"
                )
                page = await context.new_page()
                try:
                    result = await check_availability(page)
                    break
                except Exception as exc:
                    if attempt >= MAX_ATTEMPTS:
                        raise
                    delay = RETRY_DELAY_SECONDS * attempt
                    log.warning(
                        "第 %s/%s 次检查失败：%s；%s 秒后使用新会话重试",
                        attempt,
                        MAX_ATTEMPTS,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                finally:
                    await context.close()

            if result is None:
                raise RuntimeError("检查未返回结果")
            log.info("检查完成 | available=%s | status=%s | times=%s", result.available, result.status, result.times)
            if result.available:
                subject, text_body, html_body = _availability_mail(result)
                await asyncio.to_thread(
                    send_notifications,
                    subject,
                    text_body,
                    html_body,
                    urgent=True,
                )
                log.warning("检测到余票，Bark 推送已发送。")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
