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
                page
