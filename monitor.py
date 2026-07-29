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
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram 回應: {resp.status_code}")
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

def check_target(page, target):
    method = target.get("method", "text").lower()
    value = target["value"]

    try:
        if method == "text":
            content = page.content()
            found = value in content
            print(f"  → 頁面內容長度: {len(content)} 字元")
            print(f"  → 有冇搵到「{value}」: {found}")
            return "FOUND" if found else "LOST"

        elif method == "css":
            locator = page.locator(value)
            count = locator.count()
            found = count > 0
            print(f"  → CSS 找到 {count} 個元素")
            return "FOUND" if found else "LOST"

        elif method == "xpath":
            locator = page.locator(f"xpath={value}")
            count = locator.count()
            found = count > 0
            print(f"  → XPath 找到 {count} 個元素")
            return "FOUND" if found else "LOST"

        elif method == "regex":
            content = page.content()
            found = bool(re.search(value, content, re.IGNORECASE | re.DOTALL))
            print(f"  → Regex 結果: {found}")
            return "FOUND" if found else "LOST"

        return "ERROR"

    except Exception as e:
        print(f"  → 檢查時出錯: {e}")
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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-HK"
        )
        page = context.new_page()
        page.set_default_timeout(settings.get("timeout", 30000))

        for target in targets:
            tid = target["id"]
            name = target.get("name", tid)
            url = target["url"]

            print(f"正在檢查: {name}")
            print(f"網址: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                # 嘗試向下滾動，觸發懶加載
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                current_status = check_target(page, target)
                print(f"  → 判斷結果: {current_status}")

            except Exception as e:
                print(f"  → 載入頁面失敗: {e}")
                current_status = "ERROR"

            previous = state.get(tid, "LOST")
            print(f"  → 上次狀態: {previous}")

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
                    print(f"→ 已發送有貨通知")

                elif current_status == "LOST":
                    msg = (
                        f"<b>已經冇貨</b>\n\n"
                        f"商品：<b>{name}</b>\n"
                        f"連結：{url}"
                    )
                    send_telegram(token, chat_id, msg)
                    print(f"→ 已發送冇貨通知")

        browser.close()

    if changed:
        save_state(state)
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=true\n")
    else:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("changed=false\n")

    print("監控完成")

if __name__ == "__main__":
    main()
