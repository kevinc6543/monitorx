import os
import json
import re
import yaml
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

STATE_FILE = Path("state.json")
CONFIG_FILE = Path("config.yaml")

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def send_telegram(token: str, chat_id: str, message: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

def check_target(page, target, settings):
    method = target.get("method", "text").lower()
    value = target["value"]
    found = False

    try:
        if method == "text":
            # 最常用：直接搵商品名
            content = page.content()
            found = value in content

        elif method == "css":
            locator = page.locator(value)
            found = locator.count() > 0 and locator.first.is_visible()

        elif method == "xpath":
            locator = page.locator(f"xpath={value}")
            found = locator.count() > 0 and locator.first.is_visible()

        elif method == "regex":
            content = page.content()
            found = bool(re.search(value, content, re.IGNORECASE | re.DOTALL))

        else:
            print(f"未知 method: {method}")
            return "ERROR"

        # 可選：再確認有貨關鍵字
        if found and target.get("in_stock_keywords"):
            content = page.content()
            stock_ok = any(kw in content for kw in target["in_stock_keywords"])
            if not stock_ok:
                found = False

        return "FOUND" if found else "LOST"

    except Exception as e:
        print(f"檢查 {target['id']} 時出錯: {e}")
        return "ERROR"

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise ValueError("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")

    config = load_config()
    settings = config.get("settings", {})
    targets = config.get("targets", [])
    state = load_state()
    changed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.get("headless", True))
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="zh-HK"
        )
        page = context.new_page()
        page.set_default_timeout(settings.get("timeout", 20000))

        for target in targets:
            tid = target["id"]
            name = target.get("name", tid)
            url = target["url"]

            print(f"正在檢查: {name}")

            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(settings.get("wait_after_load", 1500))

                current_status = check_target(page, target, settings)
            except PlaywrightTimeout:
                print(f"{name} 載入超時")
                current_status = "ERROR"
            except Exception as e:
                print(f"{name} 發生錯誤: {e}")
                current_status = "ERROR"

            previous = state.get(tid, "LOST")

            if current_status in ("FOUND", "LOST") and current_status != previous:
                state[tid] = current_status
                changed = True

                if current_status == "FOUND":
                    msg = (
                        f"<b>有貨通知！</b>\n\n"
                        f"商品：<b>{name}</b>\n"
                        f"狀態：FOUND\n"
                        f"連結：{url}"
                    )
                    send_telegram(token, chat_id, msg)
                    print(f"→ 已通知有貨: {name}")

                elif current_status == "LOST" and previous == "FOUND":
                    # 可選：冇貨都通知（而家預設會通知）
                    msg = (
                        f"<b>已經冇貨</b>\n\n"
                        f"商品：<b>{name}</b>\n"
                        f"連結：{url}"
                    )
                    send_telegram(token, chat_id, msg)
                    print(f"→ 已通知冇貨: {name}")

            elif current_status == "ERROR":
                print(f"→ {name} 檢查失敗，保持舊狀態")

        browser.close()

    if changed:
        save_state(state)
        # 輸出給 workflow 知道有改變
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=true\n")
    else:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=false\n")

    print("監控完成")

if __name__ == "__main__":
    main()